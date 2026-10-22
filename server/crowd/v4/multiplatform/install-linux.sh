#!/bin/sh
# Public tools only. No password prompt, private repository clone or identity copy.
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = --help ]; then
  printf '%s\n' 'Linux/WSL2 installer: automatically checks public tools, uses local licensed Pro components.' 'Existing node: sh install-linux.sh --root YOUR_EXISTING_ROOT --check (or --upgrade)' 'Then: sh bind-linux.sh --root YOUR_EXISTING_ROOT --status' 'New node: sh install-linux.sh --root NODE_ROOT --cloud-config PRIVATE --pro-home LOCAL_LICENSED_PRO_DIRECTORY' 'Advanced exact runtime/source/tool flags remain available in install-linux.py --help.' 'The SDK/Signer/Bridge are not downloaded. No password, pairing or platform request is performed.'
  exit 0
fi
fail() { printf '%s\n' "$1" >&2; exit 2; }
[ "$(uname -s)" = Linux ] || fail linux_or_wsl2_required
# Read-only callers can reuse a validated interpreter without bootstrapping tools.
if [ "${1:-}" = --python-path ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=$(command -v python3.12)
  else
    RECORD="$HOME/.local/share/CrowdV4Updater/bootstrap/python312.record"
    [ -f "$RECORD" ] && [ ! -L "$RECORD" ] || fail python312_not_installed_run_install_linux
    [ "$(stat -c %u "$RECORD")" = "$(id -u)" ] && [ "$(stat -c %a "$RECORD")" = 600 ] && [ "$(stat -c %h "$RECORD")" = 1 ] || fail unsafe_python_record
    PYTHON=$(sed -n '1p' "$RECORD"); PIN=$(sed -n '2p' "$RECORD")
    [ "$(wc -l < "$RECORD" | tr -d ' ')" = 2 ] || fail unsafe_python_record
    case "$PYTHON" in /*) ;; *) fail unsafe_python_record ;; esac
    [ -f "$PYTHON" ] && [ ! -L "$PYTHON" ] && [ -x "$PYTHON" ] || fail python312_changed
    [ "${#PIN}" = 64 ] || fail unsafe_python_record
    printf '%s  %s\n' "$PIN" "$PYTHON" | sha256sum -c - >/dev/null || fail python312_changed
  fi
  "$PYTHON" -I -c 'import sys;assert sys.version_info[:2]==(3,12)' || fail python312_unavailable
  printf '%s\n' "$PYTHON"; exit 0
fi
for arg in "$@"; do
  if [ "$arg" = --check ]; then
    PYTHON=$(sh "$SCRIPT_DIR/install-linux.sh" --python-path)
    exec "$PYTHON" -B "$SCRIPT_DIR/install-linux.py" "$@"
  fi
done
# A complete existing node already owns its selected environments. Reuse them
# before considering public-tool downloads, including when uv is not on PATH.
NODE_ROOT="$HOME/.local/share/CrowdWorker"; previous=''
for arg in "$@"; do
  if [ "$previous" = --root ]; then NODE_ROOT=$arg; fi
  case "$arg" in --root=*) NODE_ROOT=${arg#--root=} ;; esac
  previous=$arg
done
if [ -f "$NODE_ROOT/node-install.json" ]; then
  PYTHON=$(sh "$SCRIPT_DIR/install-linux.sh" --python-path)
  exec "$PYTHON" -B "$SCRIPT_DIR/install-linux.py" "$@"
fi
UV=''; CACHE=''; previous='' 
for arg in "$@"; do
  if [ "$previous" = --uv ]; then UV=$arg; fi
  case "$arg" in --uv=*) UV=${arg#--uv=} ;; esac
  if [ "$previous" = --bootstrap-cache ]; then CACHE=$arg; fi
  case "$arg" in --bootstrap-cache=*) CACHE=${arg#--bootstrap-cache=} ;; esac
  previous=$arg
done
if [ -n "$UV" ]; then [ -x "$UV" ] || fail explicit_uv_unavailable
elif command -v uv >/dev/null 2>&1; then UV=$(command -v uv); fi
TOOLS=''
if [ "${1:-}" != --bootstrap-only ]; then command -v git >/dev/null 2>&1 || TOOLS='git'; fi
if [ -z "$UV" ] && [ -z "$CACHE" ] && ! command -v curl >/dev/null 2>&1; then TOOLS="$TOOLS curl ca-certificates"; fi
if [ -n "$TOOLS" ]; then
  command -v timeout >/dev/null 2>&1 || fail system_package_timeout_tool_missing
  # Existing privileges only; never prompt for a password or add a repository.
  if [ "$(id -u)" = 0 ]; then privilege='';
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then privilege='sudo -n';
  else fail "system_tools_need_existing_admin_permission: install missing git/curl using your distro package manager"; fi
  if command -v apt-get >/dev/null 2>&1; then
    $privilege timeout 180 env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o Acquire::Retries=0 update -qq || fail system_package_index_unavailable
    $privilege timeout 180 env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o Acquire::Retries=0 install -y --no-install-recommends $TOOLS || fail system_package_install_failed
  elif command -v dnf >/dev/null 2>&1; then $privilege timeout 180 dnf install -y $TOOLS || fail system_package_install_failed
  else fail unsupported_system_package_manager_install_git_curl; fi
fi
BOOT="$HOME/.local/share/CrowdV4Updater/bootstrap"
[ ! -L "$BOOT" ] || fail unsafe_bootstrap_directory
mkdir -p "$BOOT"; chmod 700 "$BOOT"
if [ -z "$UV" ]; then
  case "$(uname -m)" in
    aarch64|arm64) TARGET=aarch64-unknown-linux-gnu; PIN=66393193038dd7eb108abd7a218d9cec04ac70ab98242b0720fa94de19223b7c ;;
    x86_64) TARGET=x86_64-unknown-linux-gnu; PIN=788f18abea7c5f55d6216e4f5613fd89d4d59b631efeec117b2b07fe72f1da21 ;;
    *) fail bootstrap_architecture_unsupported ;;
  esac
  ARCHIVE="$BOOT/uv-0.12.7-$TARGET.tar.gz"; UV="$BOOT/uv-0.12.7-$TARGET"
  if [ ! -f "$ARCHIVE" ] && [ -n "$CACHE" ]; then
    CACHED="$CACHE/uv-$TARGET.tar.gz"
    printf '%s  %s\n' "$PIN" "$CACHED" | sha256sum -c - >/dev/null || fail uv_archive_changed
    cp "$CACHED" "$ARCHIVE"
  fi
  if [ ! -f "$ARCHIVE" ]; then
    TEMP=$(mktemp "$BOOT/.download-XXXXXX")
    trap 'rm -f "$TEMP"' EXIT HUP INT TERM
    curl --fail --silent --show-error --proto '=https' --proto-redir '=https' --location --max-redirs 5 --connect-timeout 15 --max-time 180 "https://github.com/astral-sh/uv/releases/download/0.12.7/uv-$TARGET.tar.gz" -o "$TEMP"
    printf '%s  %s\n' "$PIN" "$TEMP" | sha256sum -c - >/dev/null || fail uv_archive_changed
    mv "$TEMP" "$ARCHIVE"; trap - EXIT HUP INT TERM
  fi
  printf '%s  %s\n' "$PIN" "$ARCHIVE" | sha256sum -c - >/dev/null || fail uv_archive_changed
  BINARY=$(mktemp "$BOOT/.binary-XXXXXX"); trap 'rm -f "$BINARY"' EXIT HUP INT TERM
  tar -xOzf "$ARCHIVE" "uv-$TARGET/uv" > "$BINARY"
  if [ -f "$UV" ]; then cmp -s "$UV" "$BINARY" || fail uv_binary_changed
  else chmod 700 "$BINARY"; mv "$BINARY" "$UV"; fi
  rm -f "$BINARY"; trap - EXIT HUP INT TERM
fi
PYTHON=''
if command -v python3.12 >/dev/null 2>&1; then PYTHON=$(command -v python3.12)
else
  # uv's original managed Python distribution; no shell profile/PATH modification.
  export UV_PYTHON_INSTALL_DIR="$BOOT/python"
  MIRROR=''
  if [ -n "$CACHE" ]; then
    case "$(uname -m)" in
      aarch64|arm64) PYARCH=aarch64; PYPIN=4c250ec7cea2aedde2b2e8925d7aaf5ba4924895469d6b5c81c7bdc453341c65 ;;
      x86_64) PYARCH=x86_64; PYPIN=7ce4a71285d913955a76053cc7605ea96da8ecada54dba9cf395245961816421 ;;
      *) fail bootstrap_architecture_unsupported ;;
    esac
    PYARCHIVE="$CACHE/20260825/cpython-3.12.14+20260825-$PYARCH-unknown-linux-gnu-install_only_stripped.tar.gz"
    printf '%s  %s\n' "$PYPIN" "$PYARCHIVE" | sha256sum -c - >/dev/null || fail python_archive_changed
    MIRROR="file://$(CDPATH= cd -- "$CACHE" && pwd)"
  fi
  env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" UV_PYTHON_INSTALL_DIR="$BOOT/python" UV_KEYRING_PROVIDER=disabled UV_PYTHON_DOWNLOADS=automatic UV_PYTHON_INSTALL_MIRROR="$MIRROR" "$UV" --no-config python install --no-bin 3.12.14
  PYTHON=$("$UV" --no-config python find --managed-python --no-python-downloads 3.12.14)
fi
"$PYTHON" -I -c 'import sys;assert sys.version_info[:2]==(3,12)' || fail python312_unavailable
# The private interpreter record is consumed only after owner/mode/hash validation.
"$PYTHON" -I -c 'import hashlib,os,pathlib,sys,tempfile; p=pathlib.Path(sys.executable).resolve(); root=pathlib.Path(sys.argv[1]); data=(str(p)+"\n"+hashlib.sha256(p.read_bytes()).hexdigest()+"\n").encode(); fd,name=tempfile.mkstemp(prefix=".python-",dir=root); os.fchmod(fd,0o600); os.write(fd,data); os.fsync(fd); os.close(fd); os.replace(name,root/"python312.record")' "$BOOT"
if [ "${1:-}" = --bootstrap-only ]; then
  "$PYTHON" -I -c 'import json,sys;print(json.dumps({"state":"python_tools_ready","python":sys.executable,"version":sys.version.split()[0],"source_or_identity_started":False}))'
  exit 0
fi
exec "$PYTHON" -B "$SCRIPT_DIR/install-linux.py" --uv "$UV" "$@"
