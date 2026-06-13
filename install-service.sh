#!/bin/bash
# Installiert den SpaceCaptain Update Watcher als systemd-Service.
# Muss als root ausgeführt werden: sudo ./install-service.sh

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="spacecaptain-updater"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="${SUDO_USER:-root}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root ausführen: sudo $0"
  exit 1
fi

echo "Installationsverzeichnis : $INSTALL_DIR"
echo "Service läuft als User   : $RUN_USER"

chmod +x "$INSTALL_DIR/spacecaptain-updater.sh"

sed \
  -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  -e "s|__USER__|$RUN_USER|g" \
  "$INSTALL_DIR/spacecaptain-updater.service" \
  > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
systemctl status "$SERVICE_NAME" --no-pager
