#!/bin/sh
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=$(sh "$SCRIPT_DIR/install-linux.sh" --python-path)
exec "$PYTHON" -B "$SCRIPT_DIR/first_bind.py" "$@"
