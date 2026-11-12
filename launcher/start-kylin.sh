#!/bin/sh
# Portable launcher for a 银河麒麟 V10 package (ARM64 or x86_64).
# The bundled runtime is built against glibc 2.17 symbols and is not a Windows runtime.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$APP_DIR/runtime/bin/python3"
if [ ! -x "$PYTHON" ]; then
  printf '%s\n' '未找到随包 runtime/bin/python3。请解压完整的银河麒麟便携包，不要使用 Windows 包。' >&2
  exit 1
fi
# ELF e_machine is a little-endian uint16 at offset 18: 62 = x86_64, 183 = AArch64.
mach=$(od -An -tu2 -j 18 -N 2 "$PYTHON" | tr -d ' ')
host=$(uname -m)
case "$mach:$host" in
  62:x86_64|183:aarch64|183:arm64) ;;
  *) printf '%s\n' "当前系统架构是 ${host}，与随包运行库不匹配。请改用对应架构的银河麒麟 V10 安装包。" >&2
     exit 1 ;;
esac
export PYTHONNOUSERSITE=1
export LD_LIBRARY_PATH="$APP_DIR/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export FONTCONFIG_PATH="$APP_DIR/runtime/etc/fonts"
export QT_PLUGIN_PATH="$APP_DIR/runtime/lib/qt6/plugins"
export QML_IMPORT_PATH="$APP_DIR/runtime/lib/qt6/qml"
cd "$APP_DIR"
exec "$PYTHON" "$APP_DIR/app.py" "$@"
