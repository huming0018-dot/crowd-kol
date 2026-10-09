#!/bin/bash
set -eu
crowd_app_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$crowd_app_dir"
exec python3 dashboard.py --open
