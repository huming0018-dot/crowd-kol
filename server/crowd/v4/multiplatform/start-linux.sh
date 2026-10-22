#!/bin/sh
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=$(sh "$SCRIPT_DIR/install-linux.sh" --python-path)
CHECK=false
for arg in "$@"; do [ "$arg" != --check ] || CHECK=true; done
if [ "$CHECK" = false ]; then "$PYTHON" -B "$SCRIPT_DIR/first_bind.py" --ensure-bridge "$@"; fi
exec "$PYTHON" -B "$SCRIPT_DIR/install_machine_node.py" start "$@"
