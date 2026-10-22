#!/bin/sh
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3.12 -B "$SCRIPT_DIR/first_bind.py" "$@"
