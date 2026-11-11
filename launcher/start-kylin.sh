#!/bin/sh
# Run from a portable ARM64 distribution built on the target Kylin baseline.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$APP_DIR/runtime/bin/python3"
if [ ! -x "$PYTHON" ]; then
  printf '%s\n' 'Missing bundled ARM64 runtime. This source checkout is not a Linux portable release.' >&2
  exit 1
fi
case "$(uname -m)" in aarch64|arm64) ;; *) printf '%s\n' 'This launcher expects ARM64.' >&2; exit 1 ;; esac
export PYTHONNOUSERSITE=1
exec "$PYTHON" "$APP_DIR/app.py" "$@"
