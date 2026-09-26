# Vercel deployment operations

## Current production site

`https://rallyplans.vercel.app` is the production group archive. Its `rallyplans` Vercel project contains an exported snapshot generated from the Mac's local Rally database and allowed media files. The Mac publisher refreshes changed snapshots about every five minutes after the history import is complete.

Do not use `vercel deploy` from the repository root or point a website build at the `rallyplans` project. Either action can replace the live archive with unrelated files. GitHub Actions is not configured for Vercel deployments.

## Refresh the approved archive manually

Run this on the Mac that has Rally's database, media, `.env`, Vercel CLI login, and BlueBubbles data:

```sh
cd /path/to/Rally
set -a
. ./.env
set +a
RALLY_PORTAL_PUBLISH_APPROVED=1 .venv/bin/python -m scripts.publish_portal
```

The publisher verifies that every allowlisted group's history import is complete, rebuilds `data/portal_build`, and deploys that directory to the linked `rallyplans` project. It returns without deploying when history is incomplete or the exported content has not changed. The approval flag is an explicit guard against publishing archive data accidentally. Do not copy the database, `.env`, or media directory to a GitHub runner.

The regular local publisher normally handles updates automatically, so this command is only needed to force an immediate refresh. If a deployment fails, inspect the command output and the Mac's Vercel CLI authentication before retrying.

## Future standalone website

This repository currently has no standalone website source directory. When one is added, deploy it manually with the Vercel CLI from that directory and link it to a Vercel project separate from `rallyplans`:

```sh
cd /path/to/Rally/<website-directory>
vercel link --project <separate-website-project>
vercel deploy --prod
```

Use synthetic fixtures for previews and tests. Keep personal relationship data, credentials, and the Mac's operational database out of website build inputs. Do not add an Actions workflow unless deployment ownership changes and the target project is verified to be separate from the group archive.
