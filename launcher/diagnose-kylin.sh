#!/bin/sh
# Read-only diagnostics; no sudo, installation or system modifications.
printf '\n== Platform ==\n'
uname -sm
[ ! -r /etc/os-release ] || cat /etc/os-release
printf '\n== libc ==\n'
getconf GNU_LIBC_VERSION 2>/dev/null || true
printf '\n== Session ==\n'
printf 'session=%s display=%s wayland=%s\n' "${XDG_SESSION_TYPE:-}" "${DISPLAY:-}" "${WAYLAND_DISPLAY:-}"
printf '\n== Available tools ==\n'
command -v python3 || true
command -v soffice || true
printf '\n== Graphics ==\n'
command -v glxinfo >/dev/null 2>&1 && glxinfo -B 2>/dev/null || true
printf '\n== User storage ==\n'
printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/WenJu"
