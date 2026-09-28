#!/bin/bash
# Keep Grok Voice attached. Watcher argv is this script, not the worker module.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1
while true; do
  "$ROOT/.venv/bin/python" -u -m app.voice.run_worker
  worker_status=$?
  echo "worker-exit $worker_status $(date)"
  if [ "$worker_status" -eq 0 ]; then
    exit 0
  fi
  sleep 1
done
