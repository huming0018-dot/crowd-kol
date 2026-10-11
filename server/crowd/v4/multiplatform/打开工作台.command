#!/bin/bash
set -eu
crowd_app_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$crowd_app_dir"
crowd_bundled_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ -x "$crowd_bundled_python" ]; then
  exec "$crowd_bundled_python" dashboard.py --open
fi
exec python3 dashboard.py --open
