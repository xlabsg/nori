#!/bin/sh
set -eu
mkdir -p /workspace/.config/xfce4/xfconf/xfce-perchannel-xml /workspace/.cache \
  /workspace/Desktop /workspace/Documents /workspace/Downloads "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
# Seed once, so reconnects preserve the user's desktop state within this container.
if [ ! -f /workspace/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml ]; then
  cp /opt/desktop/panel.xml /workspace/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
  cp /opt/desktop/launchers/*.desktop /workspace/Desktop/
  chmod +x /workspace/Desktop/*.desktop
  printf 'XDG_DESKTOP_DIR="%s/Desktop"\nXDG_DOCUMENTS_DIR="%s/Documents"\nXDG_DOWNLOAD_DIR="%s/Downloads"\n' \
    "$HOME" "$HOME" "$HOME" > /workspace/.config/user-dirs.dirs
fi
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
for attempt in $(seq 1 50); do
  if DISPLAY=:99 xdotool getdisplaygeometry >/dev/null 2>&1; then break; fi
  sleep 0.1
done
dbus-run-session -- startxfce4 >/tmp/desktop-session.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -listen 127.0.0.1 -rfbport 5900 -quiet &
websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 &
chromium --lang=en-US --no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir=/workspace/.chromium --window-size=1000,650 --window-position=140,60 \
  file:///opt/desktop/welcome.html >/dev/null 2>&1 &
# An absolute lifetime bounds unattended background processes in this local prototype.
sleep 1800
