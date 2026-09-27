#!/bin/bash
# Keep Grok Voice attached. Watcher argv is this script, not the worker module.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1
while true; do
  "$ROOT/.venv/bin/python" -u -m app.voice.run_worker
  echo "worker-exit $? $(date)"
  sleep 1
done
