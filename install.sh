#!/bin/bash
# ============================================================
# SpaceCaptain — Installationsscript
# ============================================================
# Verwendung: bash install.sh
# Voraussetzungen: Docker, git, openssl, python3, sudo-Rechte

set -euo pipefail

# --- Konfiguration ---
REPO_URL="https://github.com/drstrangelove52/spacecaptain.git"
INSTALL_DIR="$HOME/spacecaptain"
DEFAULT_TZ="Europe/Zurich"

# --- Farben ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[FEHLER]${NC} $*"; exit 1; }
sep()   { echo -e "${BOLD}────────────────────────────────────────${NC}"; }

gen_pass()   { openssl rand -base64 18 | tr -d '/+=' | head -c 20; }
gen_secret() { openssl rand -hex 32; }

# ============================================================
# 1. Voraussetzungen prüfen
# ============================================================
check_deps() {
    info "Prüfe Voraussetzungen..."
    local missing=()
    for cmd in docker git openssl python3; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    docker compose version &>/dev/null || missing+=("docker-compose-plugin")
    if [ ${#missing[@]} -gt 0 ]; then
        err "Folgende Programme fehlen: ${missing[*]}"
    fi
    ok "Alle Voraussetzungen erfüllt"
}

# ============================================================
# 2. Fragen stellen
# ============================================================
ask_questions() {
    echo ""
    sep
    echo -e "   ${BOLD}SpaceCaptain — Installation${NC}"
    sep
    echo ""

    # Installationsverzeichnis
    read -rp "$(echo -e "  ${BOLD}Installationsverzeichnis${NC} [$INSTALL_DIR]: ")" DIR_INPUT
    INSTALL_DIR="${DIR_INPUT:-$INSTALL_DIR}"

    # Zeitzone
    CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "$DEFAULT_TZ")
    read -rp "$(echo -e "  ${BOLD}Zeitzone${NC} [$CURRENT_TZ]: ")" TZ_INPUT
    TIMEZONE="${TZ_INPUT:-$CURRENT_TZ}"

    # Server-IP
    DETECTED_IP=$(hostname -I | awk '{print $1}')
    read -rp "$(echo -e "  ${BOLD}Server-IP oder Hostname${NC} [$DETECTED_IP]: ")" IP_INPUT
    SERVER_HOST="${IP_INPUT:-$DETECTED_IP}"

    # Admin-Zugangsdaten
    echo ""
    echo -e "  ${BOLD}Erster Admin-Benutzer:${NC}"
    read -rp "    Benutzername: " ADMIN_NAME
    while [[ -z "$ADMIN_NAME" ]]; do
        read -rp "    Benutzername (darf nicht leer sein): " ADMIN_NAME
    done

    read -rp "    E-Mail: " ADMIN_EMAIL
    while [[ -z "$ADMIN_EMAIL" ]]; do
        read -rp "    E-Mail (darf nicht leer sein): " ADMIN_EMAIL
    done

    GENERATED_PASS=$(gen_pass)
    read -rp "    Passwort [generiert: ${GENERATED_PASS}]: " PASS_INPUT
    ADMIN_PASSWORD="${PASS_INPUT:-$GENERATED_PASS}"

    echo ""
    sep
    echo -e "  ${BOLD}Zusammenfassung:${NC}"
    echo "    Verzeichnis: $INSTALL_DIR"
    echo "    Zeitzone:    $TIMEZONE"
    echo "    Server:      $SERVER_HOST"
    echo "    Admin:       $ADMIN_NAME ($ADMIN_EMAIL)"
    sep
    echo ""
    read -rp "  Installation starten? [J/n]: " CONFIRM
    case "${CONFIRM:-j}" in
        [jJyY]*) ;;
        *) echo "Abgebrochen."; exit 0 ;;
    esac
    echo ""
}

# ============================================================
# 3. Repository klonen
# ============================================================
clone_repo() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        warn "Verzeichnis $INSTALL_DIR existiert bereits — überspringe Clone"
    else
        info "Klone Repository nach $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
        ok "Repository geklont"
    fi
}

# ============================================================
# 4. Zeitzone setzen
# ============================================================
set_timezone() {
    CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "")
    if [ "$CURRENT_TZ" = "$TIMEZONE" ]; then
        ok "Zeitzone bereits korrekt: $TIMEZONE"
    else
        info "Setze Zeitzone auf $TIMEZONE..."
        sudo timedatectl set-timezone "$TIMEZONE"
        ok "Zeitzone gesetzt"
    fi
}

# ============================================================
# 5. .env generieren
# ============================================================
generate_env() {
    info "Generiere .env mit Zufallspasswörtern..."

    DB_ROOT_PASS=$(gen_pass)
    DB_PASS=$(gen_pass)
    JWT_SECRET=$(gen_secret)
    BACKUP_PASS=$(gen_pass)

    cat > "$INSTALL_DIR/.env" <<EOF
# ============================================================
# SpaceCaptain — Umgebungsvariablen
# Generiert: $(date '+%Y-%m-%d %H:%M:%S')
# ============================================================

# Datenbank
DB_ROOT_PASSWORD=$DB_ROOT_PASS
DB_NAME=spacecaptain
DB_USER=spacecaptain
DB_PASSWORD=$DB_PASS

# JWT Auth
JWT_SECRET=$JWT_SECRET
JWT_EXPIRE_MINUTES=60

# HTTP/HTTPS Ports
HTTP_PORT=80
HTTPS_PORT=443

# CORS — erlaubte Origins
ALLOWED_ORIGINS=https://$SERVER_HOST

# Zeitzone
TIMEZONE=$TIMEZONE

# Backup
BACKUP_EMAIL=backup@spacecaptain.local
BACKUP_PASSWORD=$BACKUP_PASS

# NFC-Schreibgerät (optional, später im UI konfigurierbar)
NFC_WRITER_URL=
EOF

    chmod 600 "$INSTALL_DIR/.env"
    ok ".env generiert"
}

# ============================================================
# 6. TLS-Zertifikat generieren
# ============================================================
generate_cert() {
    info "Generiere Self-Signed TLS-Zertifikat für $SERVER_HOST..."
    mkdir -p "$INSTALL_DIR/certs"

    if [[ "$SERVER_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        SAN="IP:$SERVER_HOST"
    else
        SAN="DNS:$SERVER_HOST"
    fi

    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$INSTALL_DIR/certs/key.pem" \
        -out   "$INSTALL_DIR/certs/cert.pem" \
        -subj  "/CN=$SERVER_HOST/O=SpaceCaptain" \
        -addext "subjectAltName=$SAN" \
        2>/dev/null

    chmod 600 "$INSTALL_DIR/certs/key.pem"
    ok "Zertifikat erstellt (gültig 10 Jahre, $SAN)"
}

# ============================================================
# 7. systemd-Service installieren
# ============================================================
install_service() {
    info "Installiere spacecaptain-updater als systemd-Service..."

    sudo tee /etc/systemd/system/spacecaptain-updater.service > /dev/null <<EOF
[Unit]
Description=SpaceCaptain Update Watcher
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/spacecaptain-updater.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    chmod +x "$INSTALL_DIR/spacecaptain-updater.sh"
    sudo systemctl daemon-reload
    sudo systemctl enable spacecaptain-updater
    sudo systemctl start spacecaptain-updater
    ok "systemd-Service installiert und gestartet"
}

# ============================================================
# 8. Container starten
# ============================================================
start_containers() {
    info "Baue und starte Container (das kann einige Minuten dauern)..."
    cd "$INSTALL_DIR"
    BUILD_NR=$(git rev-list --count HEAD) docker compose up -d --build
    ok "Container gestartet"
}

# ============================================================
# 9. Auf Backend warten
# ============================================================
wait_for_backend() {
    info "Warte auf Backend..."
    local attempts=0
    local max=40  # max 120s

    while [ $attempts -lt $max ]; do
        if curl -skf "https://$SERVER_HOST/openapi.json" > /dev/null 2>&1; then
            echo ""
            ok "Backend ist bereit"
            return 0
        fi
        sleep 3
        attempts=$((attempts + 1))
        echo -n "."
    done

    echo ""
    err "Backend nicht erreichbar nach 120s — prüfe: docker compose logs backend"
}

# ============================================================
# 10. Ersten Admin anlegen
# ============================================================
create_admin() {
    info "Erstelle Admin-Benutzer '$ADMIN_NAME'..."

    cd "$INSTALL_DIR"
    docker compose exec -T \
        -e SC_NAME="$ADMIN_NAME" \
        -e SC_EMAIL="$ADMIN_EMAIL" \
        -e SC_PASSWORD="$ADMIN_PASSWORD" \
        backend python3 -c "
import os, bcrypt, asyncio
from app.database import AsyncSessionLocal, engine
from app.models import User, UserRole

name     = os.environ['SC_NAME']
email    = os.environ['SC_EMAIL']
password = os.environ['SC_PASSWORD']

async def create():
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    async with AsyncSessionLocal() as db:
        user = User(
            name=name,
            email=email,
            password_hash=pw_hash,
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
    await engine.dispose()

asyncio.run(create())
"
    ok "Admin-Benutzer erstellt"
}

# ============================================================
# 11. Abschluss
# ============================================================
print_summary() {
    echo ""
    sep
    echo -e "   ${GREEN}${BOLD}SpaceCaptain erfolgreich installiert!${NC}"
    sep
    echo ""
    echo -e "   ${BOLD}URL:${NC}       https://$SERVER_HOST"
    echo -e "   ${BOLD}Benutzer:${NC}  $ADMIN_NAME"
    echo -e "   ${BOLD}Passwort:${NC}  $ADMIN_PASSWORD"
    echo ""
    echo -e "   ${YELLOW}Hinweis:${NC} Das Passwort wird nicht erneut angezeigt."
    echo -e "            Der Browser meldet eine Zertifikatswarnung (Self-Signed) —"
    echo -e "            diese kann ignoriert/akzeptiert werden."
    echo ""
    sep
    echo ""
}

# ============================================================
# Hauptablauf
# ============================================================
check_deps
ask_questions
clone_repo
set_timezone
generate_env
generate_cert
install_service
start_containers
wait_for_backend
create_admin
print_summary
