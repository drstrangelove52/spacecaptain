#!/usr/bin/env bash
# SpaceCaptain Kiosk Setup
# Usage: curl -sk https://your-host/raspi-setup.sh | bash -s https://your-host/display
# Hinweis: -k ist nötig bei selbstsignierten Zertifikaten (Standard-Setup mit gencert.sh)

set -e

URL="${1:-}"

if [ -z "$URL" ]; then
    read -rp "Display-URL (z.B. https://spacecaptain.local/display): " URL
fi

if [ -z "$URL" ]; then
    echo "Fehler: Keine URL angegeben." >&2
    exit 1
fi

echo ""
echo "=== SpaceCaptain Kiosk Setup ==="
echo "URL: $URL"
echo ""

# Chromium installieren (Paketname je nach OS-Version unterschiedlich)
echo "[1/4] Chromium installieren..."
sudo apt-get update -qq
if apt-cache policy chromium-browser 2>/dev/null | grep -q "Candidate: [0-9]"; then
    CHROMIUM_PKG="chromium-browser"
else
    CHROMIUM_PKG="chromium"
fi
sudo apt-get install -y -qq "$CHROMIUM_PKG" unclutter fonts-noto-color-emoji

# Screensaver / Display-Blank deaktivieren
echo "[2/4] Display-Blank deaktivieren..."
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/10-blanking.conf > /dev/null <<'EOF'
Section "ServerFlags"
    Option "BlankTime"   "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime"     "0"
EndSection
EOF

# DPMS in lightdm deaktivieren (falls vorhanden)
if [ -d /etc/lightdm ]; then
    LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
    if ! grep -q "xserver-command" "$LIGHTDM_CONF" 2>/dev/null; then
        sudo sed -i '/\[Seat:\*\]/a xserver-command=X -s 0 dpms' "$LIGHTDM_CONF" 2>/dev/null || true
    fi
fi

# Autostart-Eintrag anlegen
echo "[3/4] Kiosk-Autostart einrichten..."
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/spacecaptain-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SpaceCaptain Kiosk
Exec=$CHROMIUM_PKG --kiosk --noerrdialogs --disable-infobars --no-first-run --ozone-platform=x11 --password-store=basic "$URL"
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

# unclutter Autostart (Mauszeiger verstecken)
cat > "$AUTOSTART_DIR/unclutter.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Unclutter
Exec=unclutter -idle 1 -root
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

echo "[4/4] Fertig."
echo ""
echo "Kiosk-URL: $URL"
echo ""
echo "Neustart empfohlen. Jetzt neu starten? [j/N]"
read -rp "" REBOOT
if [[ "$REBOOT" =~ ^[jJyY]$ ]]; then
    sudo reboot
fi
