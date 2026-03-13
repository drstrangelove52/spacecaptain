#!/usr/bin/env bash
# SpaceCaptain Kiosk Setup
# Usage: SPACECAPTAIN_URL="https://your-host/display" bash raspi-setup.sh

set -e

URL="${SPACECAPTAIN_URL:-}"

if [ -z "$URL" ]; then
    echo "Bitte SPACECAPTAIN_URL setzen:"
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

# Chromium installieren
echo "[1/4] Chromium installieren..."
sudo apt-get update -qq
sudo apt-get install -y -qq chromium-browser unclutter

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
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars --no-first-run --ozone-platform=x11 "$URL"
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
