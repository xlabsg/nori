FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS browser-tools
WORKDIR /opt/browser-tools
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM debian@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xvfb x11vnc chromium novnc websockify xdotool scrot xterm \
    xfce4-session xfce4-panel xfdesktop4 xfwm4 xfce4-settings thunar \
    mousepad ristretto evince file-roller libreoffice-calc libreoffice-writer \
    python3 python3-pip python3-venv python3-numpy python3-pandas \
    python3-matplotlib python3-scipy python3-requests \
    git curl wget jq ripgrep unzip zip less procps \
    ca-certificates fonts-noto-cjk dbus-x11 adwaita-icon-theme \
    && rm -rf /var/lib/apt/lists/*
COPY --from=browser-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=browser-tools /opt/browser-tools/ /opt/browser-tools/
COPY start.sh welcome.html /opt/desktop/
COPY launchers/ /opt/desktop/launchers/
COPY panel.xml /opt/desktop/panel.xml
RUN chmod 755 /opt/desktop/start.sh \
    && groupadd --gid 1000 finance \
    && useradd --uid 1000 --gid 1000 --home-dir /workspace --shell /bin/bash --no-create-home finance
ENV DISPLAY=:99 HOME=/workspace XDG_CONFIG_HOME=/workspace/.config \
    XDG_CACHE_HOME=/workspace/.cache XDG_RUNTIME_DIR=/tmp/runtime-finance
USER 1000:1000
WORKDIR /workspace
EXPOSE 6080
ENTRYPOINT ["/opt/desktop/start.sh"]
