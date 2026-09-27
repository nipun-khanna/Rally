"""Build a data-minimized static mirror of allowlisted group portals.

This command only writes a local build directory. Publishing its private
contents to an external host is a separate, explicit step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

from app.portal_data import build_portal_data
from app.portal_store import PortalStore
from app.portal_view import render_portal
from app.store import Store


LANDING = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rally</title><body style="font:16px -apple-system,sans-serif;max-width:40rem;margin:12vh auto;padding:1rem"><h1>Rally</h1><p>Ask Rally in your group chat for your private page link.</p></body></html>'
VERCEL_CONFIG = {
    "cleanUrls": False,
    "trailingSlash": False,
    "headers": [
        {"source": "/(.*)", "headers": [
            {"key": "X-Content-Type-Options", "value": "nosniff"},
            {"key": "Referrer-Policy", "value": "no-referrer"},
        ]},
        {"source": "/:group/download/:file", "headers": [
            {"key": "Content-Disposition", "value": "attachment; filename=attachment.bin"},
            {"key": "Content-Security-Policy", "value": "sandbox; default-src 'none'"},
        ]},
        {"source": "/:group/media/:file", "headers": [
            {"key": "Content-Security-Policy", "value": "sandbox; default-src 'none'"},
        ]},
    ],
}


def _safe_inline(source: Path, mime: str) -> bool:
    with source.open("rb") as stream:
        head = stream.read(16)
    return (
        (mime == "image/png" and head.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/jpeg" and head.startswith(b"\xff\xd8\xff"))
        or (mime == "image/gif" and head.startswith((b"GIF87a", b"GIF89a")))
        or (mime == "image/webp" and head.startswith(b"RIFF") and head[8:12] == b"WEBP")
        or (mime in {"video/mp4", "video/quicktime", "audio/mp4"} and head[4:8] == b"ftyp")
        or (mime == "audio/mpeg" and (head.startswith(b"ID3") or head[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}))
        or (mime == "audio/wav" and head.startswith(b"RIFF") and head[8:12] == b"WAVE")
    )


class _Service:
    def __init__(self, store):
        self.store = store


def _search_script(group_id: str) -> str:
    path = json.dumps(f"/{group_id}/history-index.json")
    return f'''<script>
(() => {{
  const form = document.querySelector("form.old-plan-search");
  if (!form) return;
  form.addEventListener("submit", async (event) => {{
    event.preventDefault();
    const query = form.querySelector("input").value.trim().toLowerCase();
    const box = document.getElementById("historical-results");
    box.replaceChildren();
    if (query.length < 3 || query.length > 200) {{ box.textContent = "Ask a question between 3 and 200 characters."; return; }}
    try {{
      const response = await fetch({path});
      if (!response.ok) throw new Error("search index unavailable");
      const messages = await response.json();
      const skip = new Set(["what","were","the","our","old","past","plans","plan","show","find","from","about"]);
      const terms = (query.match(/[a-z0-9']+/g) || []).filter(x => x.length > 2 && !skip.has(x));
      const plan = /\\b(plan|dinner|lunch|brunch|meet|trip|movie|party|concert|reservation|book|going|tomorrow|weekend)\\b/i;
      const found = messages.filter(m => plan.test(m.text) && (!terms.length || terms.some(t => m.text.toLowerCase().includes(t)))).slice(0,8);
      const heading = document.createElement("h3"); heading.textContent = "Possible older plans"; box.append(heading);
      if (!found.length) {{ const p = document.createElement("p"); p.textContent = "No matching older plan mentions found."; box.append(p); return; }}
      const list = document.createElement("ul");
      for (const m of found) {{
        const item = document.createElement("li");
        const strong = document.createElement("strong"); strong.textContent = "Possible plan · " + m.sent_at.slice(0,10); item.append(strong);
        const detail = document.createElement("p"); detail.textContent = "This older message mentions a possible plan. Check the conversation for what the group agreed to."; item.append(detail);
        const evidence = document.createElement("blockquote"); evidence.textContent = m.text; item.append(evidence);
        list.append(item);
      }}
      box.append(list);
    }} catch (_) {{ box.textContent = "Past plan search is unavailable right now."; }}
  }});
}})();
</script>'''


def _private_chats(portal_store: PortalStore) -> set[str]:
    with portal_store._db() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        private_chats = set()
        if 'rel_sources' in tables:
            private_chats.update(r[0] for r in db.execute('SELECT chat_id FROM rel_sources'))
        if 'rel_config' in tables:
            private_chats.update(r[0] for r in db.execute('SELECT destination FROM rel_config'))
    return private_chats


def _write_site_root(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(LANDING, encoding="utf-8")
    (output / ".vercelignore").write_text(".env*\n.vercel\n", encoding="utf-8")
    (output / "vercel.json").write_text(json.dumps(VERCEL_CONFIG), encoding="utf-8")


def _export_one_group(service, portal_store, group: dict, media_base: Path,
                      output: Path) -> dict:
    chat_id = group["chat_id"]
    group_id = group["public_id"]
    target = output / group_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    summary = {"groups": 1, "pages": 0, "media": 0}
    before = None
    page_number = 1
    while True:
        data = build_portal_data(service, portal_store, group, before=before)
        next_before = None
        if data["older_url"]:
            next_before = parse_qs(urlsplit(data["older_url"]).query).get("before", [None])[0]
        if next_before and portal_store.list_messages(chat_id, before=next_before, limit=1):
            data["older_url"] = f"/{group_id}/history/{page_number + 1}.html"
        else:
            data["older_url"] = None
        if group["sections"].get("history", True) and group["sections"].get("media", True):
            for message in data["messages"]:
                for attachment in message["attachments"]:
                    if not attachment["available"]:
                        continue
                    attachment_id = unquote(attachment["url"].rsplit("/", 1)[-1])
                    record = portal_store.get_attachment(chat_id, attachment_id)
                    source = Path(record["local_path"]).resolve() if record and record["local_path"] else None
                    if not source or not source.is_relative_to(media_base) or not source.is_file():
                        attachment["available"] = False
                        continue
                    inline = _safe_inline(source, attachment.get("mime") or "")
                    extension = (mimetypes.guess_extension(attachment.get("mime") or "") or "") if inline else ".bin"
                    filename = hashlib.sha256(attachment_id.encode()).hexdigest() + extension
                    media_kind = "media" if inline else "download"
                    media_dir = target / media_kind
                    media_dir.mkdir(exist_ok=True)
                    dest = media_dir / filename
                    if not dest.exists():
                        shutil.copyfile(source, dest)
                        summary["media"] += 1
                    attachment["url"] = f"/{group_id}/{media_kind}/{filename}"
                    if not inline:
                        attachment["mime"] = "application/octet-stream"
        html = render_portal(data)
        if group["sections"].get("plans", True) and group["sections"].get("history", True):
            html = html.replace("</body>", _search_script(group_id) + "</body>")
        filename = target / "index.html" if page_number == 1 else target / "history" / f"{page_number}.html"
        filename.parent.mkdir(exist_ok=True)
        filename.write_text(html, encoding="utf-8")
        summary["pages"] += 1
        if not data["older_url"]:
            break
        before = next_before
        page_number += 1
    if group["sections"].get("history", True) and group["sections"].get("plans", True):
        with portal_store._db() as db, (target / "history-index.json").open("w", encoding="utf-8") as output_file:
            rows = db.execute("""SELECT m.text, m.sent_at FROM portal_messages m
                WHERE m.chat_id=? AND m.is_deleted=0 AND m.text!=''
                AND NOT EXISTS (SELECT 1 FROM messages live
                    WHERE live.chat_id=m.chat_id AND live.message_id=m.message_id)
                ORDER BY m.sent_at DESC""", (chat_id,))
            output_file.write("[")
            for index, row in enumerate(rows):
                if index:
                    output_file.write(",")
                json.dump(dict(row), output_file, ensure_ascii=False)
            output_file.write("]")
    return summary


def export_group(database_path: str | Path, media_root: str | Path,
                 chat_id: str, output_dir: str | Path) -> dict:
    """Write one group's snapshot into an existing portal_build without wiping others."""
    output = Path(output_dir).resolve()
    if output.name != "portal_build":
        raise ValueError("Output directory must be named portal_build")
    _write_site_root(output)
    portal_store = PortalStore(database_path)
    if chat_id in _private_chats(portal_store):
        return {"groups": 0, "pages": 0, "media": 0}
    group = portal_store.group_for_chat(chat_id)
    if group is None:
        return {"groups": 0, "pages": 0, "media": 0}
    live_group = dict(group)
    live_group["sections"] = {**group["sections"], "history": True, "plans": True}
    return _export_one_group(_Service(Store(database_path)), portal_store, live_group,
                             Path(media_root).resolve(), output)


def export_portal(database_path: str | Path, media_root: str | Path,
                  allowed_chat_ids: set[str] | frozenset[str], output_dir: str | Path) -> dict:
    output = Path(output_dir).resolve()
    if output.name != "portal_build":
        raise ValueError("Output directory must be named portal_build")
    if output.exists():
        shutil.rmtree(output)
    _write_site_root(output)
    portal_store = PortalStore(database_path)
    private_chats = _private_chats(portal_store)
    service = _Service(Store(database_path))
    media_base = Path(media_root).resolve()
    summary = {"groups": 0, "pages": 0, "media": 0}
    for chat_id in sorted(allowed_chat_ids):
        if chat_id in private_chats:
            continue
        group = portal_store.group_for_chat(chat_id)
        if group is None:
            continue
        part = _export_one_group(service, portal_store, group, media_base, output)
        summary["groups"] += part["groups"]
        summary["pages"] += part["pages"]
        summary["media"] += part["media"]
    return summary


def main() -> None:
    from app.config import Settings
    parser = argparse.ArgumentParser(description="Build a local static Rally portal snapshot")
    parser.add_argument("--output", default="data/portal_build")
    args = parser.parse_args()
    settings = Settings.from_env()
    result = export_portal(settings.database_path,
                           settings.database_path.parent / "portal_media",
                           settings.allowed_chat_ids, args.output)
    print(result)


if __name__ == "__main__":
    main()
