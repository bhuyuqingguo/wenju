#!/bin/sh
# One entry for the Linux / 麒麟 package. No root.
# Creates a user desktop file, hicolor icons, and a start-menu entry.
# Tries to pin on GNOME and UKUI. KDE has no stable pin command here.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP=$HERE/文矩
if [ ! -x "$APP/runtime/bin/python3" ]; then
  printf '%s\n' '请把「打开文矩.sh」和旁边的「文矩」文件夹放在一起，不要只拷走脚本。' >&2
  exit 1
fi
DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || printf '%s\n' "$HOME/Desktop")
if [ ! -d "$DESKTOP" ] && [ -d "$HOME/桌面" ]; then DESKTOP=$HOME/桌面; fi
if [ "${1:-}" = --uninstall ]; then
  rm -f "$HOME/.local/share/applications/wenju.desktop" "$DESKTOP/文矩.desktop"
  find "$HOME/.local/share/icons/hicolor" -path '*/apps/wenju.png' -delete 2>/dev/null || true
  printf '%s\n' '已去掉桌面、开始菜单和用户图标。程序文件夹还在，可以自行删除。'
  exit 0
fi
mkdir -p "$DESKTOP" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor"
ICON_NAME=wenju
for dir in "$APP"/launcher/icons/hicolor/*; do
  [ -d "$dir" ] || continue
  size=$(basename "$dir")
  mkdir -p "$HOME/.local/share/icons/hicolor/$size/apps"
  cp -f "$dir/apps/wenju.png" "$HOME/.local/share/icons/hicolor/$size/apps/wenju.png"
done
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
write_desktop() {
  dest=$1
  cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=文矩
GenericName=文档格式整理
Comment=文矩 3.4.0
Exec="$APP/runtime/bin/python3" "$APP/app.py"
Path=$APP
Icon=wenju
StartupWMClass=wenju
Terminal=false
Categories=Office;
EOF
  chmod 755 "$dest"
  if command -v gio >/dev/null 2>&1; then
    gio set "$dest" metadata::trusted true >/dev/null 2>&1 || true
  fi
}
write_desktop "$HOME/.local/share/applications/wenju.desktop"
write_desktop "$DESKTOP/文矩.desktop"
# Start menu is the applications directory. Pin when the desktop exposes favorites.
if command -v gsettings >/dev/null 2>&1; then
  for schema in org.gnome.shell org.ukui.panel org.mate.panel; do
    if gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
      key=favorite-apps
      if [ "$schema" = org.ukui.panel ]; then key=favorite-apps; fi
      if gsettings list-keys "$schema" 2>/dev/null | grep -qx "$key"; then
        current=$(gsettings get "$schema" "$key" 2>/dev/null || printf '%s\n' '@as []')
        case $current in
          *"wenju.desktop"*) ;;
          '@as []') gsettings set "$schema" "$key" "['wenju.desktop']" >/dev/null 2>&1 || true ;;
          *) gsettings set "$schema" "$key" "$(printf '%s' "$current" | sed "s/]$/, 'wenju.desktop']/")" >/dev/null 2>&1 || true ;;
        esac
      fi
    fi
  done
fi
exec "$APP/launcher/start-kylin.sh" "$@"
