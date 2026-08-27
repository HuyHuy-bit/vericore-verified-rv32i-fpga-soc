#!/usr/bin/env bash
set -euo pipefail

: "${RV32I_ENVIRONMENT_MARKER:=/opt/rv32i/environment.json}"
: "${HOST_UID:=0}"
: "${HOST_GID:=0}"

python3 /work/tools/tool_environment.py container

if [ "$HOST_UID" = 0 ] && [ "$HOST_GID" = 0 ]; then
    exec "$@"
fi

runtime_home="/tmp/rv32i-home-$HOST_UID"
mkdir -p "$runtime_home"
chown "$HOST_UID:$HOST_GID" "$runtime_home" /opt/rv32i-cache
export HOME="$runtime_home"
exec setpriv --reuid "$HOST_UID" --regid "$HOST_GID" --clear-groups "$@"
