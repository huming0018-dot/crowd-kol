#!/usr/bin/env bash
set -euo pipefail
BRIDGE_DIR=$(cd -- "$(dirname -- "$0")/.." && pwd)
IMAGE=${CROWD_WORKER_IMAGE:-mcr.microsoft.com/playwright/python:v1.49.0-noble}
ACTION=${1:-help}
shift || true

absolute_dir() { mkdir -p -- "$1"; (cd -- "$1" && pwd -P); }
common=(--read-only --cap-drop ALL --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,nodev,size=256m --shm-size 256m -e HOME=/tmp/worker-home -e PYTHONDONTWRITEBYTECODE=1)

case "$ACTION" in
  test)
    EVIDENCE=$(absolute_dir "${1:?usage: worker.sh test EVIDENCE_DIR}")
    docker run --rm --network none "${common[@]}" \
      --mount "type=bind,source=$BRIDGE_DIR,target=/bridge,readonly" \
      --mount "type=bind,source=$EVIDENCE,target=/evidence" \
      "$IMAGE" python /bridge/docker/verify.py /evidence
    ;;
  init-env)
    ENV_DIR=$(absolute_dir "${1:?usage: worker.sh init-env LINUX_ENV_DIR}")
    docker run --rm --network none "${common[@]}" \
      --mount "type=bind,source=$ENV_DIR,target=/linux-env" \
      "$IMAGE" python -m venv --without-pip --system-site-packages /linux-env/.venv
    printf '%s\n' 'Linux environment created; MC-specific dependencies must still be installed and checked separately.'
    ;;
  start)
    MC_DIR=$(cd -- "${1:?usage: worker.sh start MC_DIR LINUX_ENV_DIR RUNTIME_DIR [NAME]}" && pwd -P)
    ENV_DIR=$(cd -- "${2:?LINUX_ENV_DIR required}" && pwd -P)
    RUNTIME=$(absolute_dir "${3:?RUNTIME_DIR required}")
    NAME=${4:-crowd-linux-worker}
    [[ -f "$ENV_DIR/.venv/bin/python" || -L "$ENV_DIR/.venv/bin/python" ]] || { printf '%s\n' 'Linux .venv missing; run init-env and install MC dependencies.' >&2; exit 1; }
    [[ -d "$MC_DIR/.venv" ]] || { printf '%s\n' 'MC .venv mountpoint must already exist; worker does not modify source.' >&2; exit 1; }
    [[ "$ENV_DIR" != "$MC_DIR" && "$ENV_DIR/" != "$MC_DIR/"* ]] || { printf '%s\n' 'Linux environment must be outside MC source.' >&2; exit 1; }
    [[ "$RUNTIME" != "$MC_DIR" && "$RUNTIME/" != "$MC_DIR/"* ]] || { printf '%s\n' 'Runtime must be outside MC source.' >&2; exit 1; }
    docker run --detach --name "$NAME" --network "${CROWD_WORKER_NETWORK:-none}" "${common[@]}" \
      --mount "type=bind,source=$BRIDGE_DIR,target=/bridge,readonly" \
      --mount "type=bind,source=$MC_DIR,target=/executor,readonly" \
      --mount "type=bind,source=$ENV_DIR/.venv,target=/executor/.venv,readonly" \
      --mount "type=bind,source=$RUNTIME,target=/runtime" \
      "$IMAGE" python /bridge/docker/worker.py serve
    ;;
  exec)
    NAME=${1:?usage: worker.sh exec NAME ACTION < payload.json}
    COMMAND=${2:?ACTION required}
    case "$COMMAND" in capabilities|start|status|stop|import|list) ;; *) printf '%s\n' 'Invalid public bridge action.' >&2; exit 1;; esac
    docker exec -i "$NAME" python /bridge/docker/worker.py "$COMMAND"
    ;;
  stop)
    NAME=${1:-crowd-linux-worker}
    docker stop --time 15 "$NAME"
    ;;
  *) printf '%s\n' 'worker.sh test EVIDENCE_DIR | init-env LINUX_ENV_DIR | start MC_DIR LINUX_ENV_DIR RUNTIME_DIR [NAME] | exec NAME ACTION | stop [NAME]' ;;
esac
