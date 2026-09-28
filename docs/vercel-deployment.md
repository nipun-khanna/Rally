# Vercel deployment operations

## Current production site

`https://rallyplans.vercel.app` is the production group archive. Its `rallyplans` Vercel project contains an exported snapshot generated from the Mac's local Rally database and allowed media files. The Mac publisher refreshes changed snapshots about every five minutes when publication is approved. Pages label history imports that are still in progress, and a group whose import is pending or running is still included so the other groups are not held back.

Do not use `vercel deploy` from the repository root or point a website build at the `rallyplans` project. Either action can replace the live archive with unrelated files. GitHub Actions is not configured for Vercel deployments.

Automatic approval to publish group history was rejected. Building a local snapshot does not authorize a deploy. Do not set `RALLY_PORTAL_PUBLISH_APPROVED=1` to bypass that review. A person must review the snapshot and explicitly authorize the upload before anyone runs the publisher below.

## Review a snapshot without deploying

On the Mac that has Rally's database and media:

```sh
cd /path/to/Rally
.venv/bin/python -m scripts.export_portal
```

This writes `data/portal_build` only. The export runs under an exclusive lock, renders each allowlisted group into a staging directory, and swaps that finished tree into place. A crash during the swap leaves the previous tree under a sibling backup, and the next export restores it before writing again. An interrupted render never replaces a finished snapshot with a partial one. Direct chats and relationship-selected chats are omitted. If a previously exported chat becomes one of those, a later single-group export removes its directory from the local snapshot.

Open `data/portal_build/index.html` and each group directory. Confirm the pages show plans, analytics, and activity, that pending imports are labeled, and that private relationship content, direct-message threads, `.env`, and the SQLite database are absent. Configured group titles, member names, and section visibility are left as stored. See [portal demo check](portal-demo-check.md) for the latest local and read-only production check.

## Refresh the approved archive manually

Run this on the Mac that has Rally's database, media, `.env`, Vercel CLI login, and BlueBubbles data:

```sh
cd /path/to/Rally
set -a
. ./.env
set +a
RALLY_PORTAL_PUBLISH_APPROVED=1 .venv/bin/python -m scripts.publish_portal
```

The publisher holds the same export lock through the Vercel upload, rebuilds `data/portal_build` from allowlisted group content (including groups whose history import is still pending), and deploys that directory to the linked `rallyplans` project. It returns without deploying when the exported content has not changed. The approval flag is an explicit guard against publishing archive data accidentally. It is not a substitute for a person's review of this snapshot. Do not copy the database, `.env`, or media directory to a GitHub runner.

The regular local publisher normally handles updates automatically, so this command is only needed to force an immediate refresh. If a deployment fails, inspect the command output and the Mac's Vercel CLI authentication before retrying.

## Future standalone website

This repository currently has no standalone website source directory. When one is added, deploy it manually with the Vercel CLI from that directory and link it to a Vercel project separate from `rallyplans`:

```sh
cd /path/to/Rally/<website-directory>
vercel link --project <separate-website-project>
vercel deploy --prod
```

Use synthetic fixtures for previews and tests. Keep personal relationship data, credentials, and the Mac's operational database out of website build inputs. Do not add an Actions workflow unless deployment ownership changes and the target project is verified to be separate from the group archive.
