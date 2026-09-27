"""Load Rally .env files in Python so shell `source` cannot truncate GUIDs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


_GUID_KEYS = frozenset({
    "RALLY_BROWSER_OWNER_CHAT_ID",
    "RALLY_ALLOWED_CHAT_GUIDS",
})


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines, including unquoted values that contain semicolons."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def guid_was_truncated(key: str, current: str, file_value: str) -> bool:
    """True when a shell `source` likely kept only the text before the first `;`."""
    if key not in _GUID_KEYS or ";" not in file_value:
        return False
    if not current:
        return True
    if ";" not in current and ";" in file_value:
        return True
    return file_value.startswith(current) and current != file_value


def merge_dotenv(environ: Mapping[str, str], file_values: Mapping[str, str]) -> dict[str, str]:
    merged = dict(environ)
    for key, value in file_values.items():
        current = merged.get(key, "")
        if guid_was_truncated(key, current, value) or key not in merged or current == "":
            merged[key] = value
    return merged


def resolve_settings_env(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | str | None = None,
) -> dict[str, str]:
    """Use an explicit mapping as-is; otherwise merge process env with `.env`."""
    if env is not None:
        return dict(env)
    paths = []
    if dotenv_path is not None:
        paths.append(Path(dotenv_path))
    else:
        paths.append(Path.cwd() / ".env")
        paths.append(Path(__file__).resolve().parents[1] / ".env")
    merged = dict(os.environ)
    for path in paths:
        if path.is_file():
            return merge_dotenv(merged, parse_env_file(path))
    return merged


def quote_semicolon_values(path: Path) -> int:
    """Quote RALLY_* values that contain `;` so `source .env` stays safe. Returns edits."""
    if not path.is_file():
        return 0
    original = path.read_text()
    lines = original.splitlines(keepends=True)
    changed = 0
    out: list[str] = []
    for line in lines:
        body = line.rstrip("\n")
        newline = line[len(body):]
        stripped = body.strip()
        if not stripped or stripped.startswith("#") or "=" not in body:
            out.append(line)
            continue
        key, _, value = body.partition("=")
        if not key.strip().startswith("RALLY_") or ";" not in value:
            out.append(line)
            continue
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            out.append(line)
            continue
        out.append(f'{key}="{value}"{newline}')
        changed += 1
    if changed:
        path.write_text("".join(out))
    return changed
