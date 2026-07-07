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
DOCKER_INSTALL_URL="https://docs.docker.com/engine/install/"

offer_docker_install() {
    warn "Docker ist nicht installiert."
    if ! command -v apt &>/dev/null; then
        err "Automatische Installation nur auf Debian/Ubuntu (apt) unterstützt. Bitte manuell installieren: $DOCKER_INSTALL_URL"
    fi
    echo ""
    read -rp "  Docker jetzt automatisch installieren (offizielles Docker-Installationsscript)? [J/n]: " INSTALL_DOCKER
    case "${INSTALL_DOCKER:-j}" in
        [jJyY]*)
            info "Installiere Docker (curl -fsSL https://get.docker.com | sh)..."
            curl -fsSL https://get.docker.com | sh
            sudo usermod -aG docker "$USER"
            ok "Docker installiert."
            warn "Deine Gruppenmitgliedschaft (docker-Gruppe) greift erst nach erneutem Login."
            echo "  Bitte ausloggen/wieder einloggen (oder 'newgrp docker' ausführen) und install.sh erneut starten."
            exit 0
            ;;
        *)
            err "Docker wird benötigt. Installationsanleitung: $DOCKER_INSTALL_URL"
            ;;
    esac
}

check_deps() {
    info "Prüfe Voraussetzungen..."

    local missing=()
    for cmd in git openssl python3; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        err "Folgende Programme fehlen: ${missing[*]} — z.B. mit 'sudo apt install ${missing[*]}' installieren und Script erneut starten."
    fi

    if ! command -v docker &>/dev/null; then
        offer_docker_install
    elif ! docker compose version &>/dev/null; then
        err "Docker ist installiert, aber das Compose-Plugin fehlt. Installiere es mit 'sudo apt install docker-compose-plugin' (oder Docker über $DOCKER_INSTALL_URL aktualisieren) und starte das Script erneut."
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

    # Datenbank — alles vorbelegt, Enter uebernimmt den jeweiligen Default
    echo ""
    echo -e "  ${BOLD}Datenbank${NC} (Enter = Vorschlag übernehmen):"
    read -rp "    Datenbankname [spacecaptain]: " DB_NAME_INPUT
    DB_NAME="${DB_NAME_INPUT:-spacecaptain}"

    read -rp "    Datenbank-Benutzer [spacecaptain]: " DB_USER_INPUT
    DB_USER="${DB_USER_INPUT:-spacecaptain}"

    GENERATED_DB_ROOT_PASS=$(gen_pass)
    read -rp "    Root-Passwort [generiert: ${GENERATED_DB_ROOT_PASS}]: " DB_ROOT_PASS_INPUT
    DB_ROOT_PASSWORD="${DB_ROOT_PASS_INPUT:-$GENERATED_DB_ROOT_PASS}"

    GENERATED_DB_PASS=$(gen_pass)
    read -rp "    Datenbank-Passwort [generiert: ${GENERATED_DB_PASS}]: " DB_PASS_INPUT
    DB_PASSWORD="${DB_PASS_INPUT:-$GENERATED_DB_PASS}"

    # JWT Auth
    echo ""
    GENERATED_JWT=$(gen_secret)
    read -rp "$(echo -e "  ${BOLD}JWT-Secret${NC} [Enter = automatisch generiert]: ")" JWT_SECRET_INPUT
    JWT_SECRET="${JWT_SECRET_INPUT:-$GENERATED_JWT}"

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
    echo "    Datenbank:   $DB_NAME (Benutzer: $DB_USER)"
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
        return
    fi

    # Zielverzeichnis evtl. nicht vom aktuellen Benutzer beschreibbar (z.B. /opt) —
    # dann gezielt mit sudo anlegen/übernehmen, statt das ganze Script als root laufen zu lassen
    if [ -d "$INSTALL_DIR" ]; then
        if [ ! -w "$INSTALL_DIR" ]; then
            info "Kein Schreibzugriff auf $INSTALL_DIR — übernehme Verzeichnis mit sudo..."
            sudo chown "$(id -u):$(id -g)" "$INSTALL_DIR"
        fi
    elif ! mkdir -p "$INSTALL_DIR" 2>/dev/null; then
        info "Kein Schreibzugriff auf $(dirname "$INSTALL_DIR") — lege $INSTALL_DIR mit sudo an..."
        sudo mkdir -p "$INSTALL_DIR"
        sudo chown "$(id -u):$(id -g)" "$INSTALL_DIR"
    fi

    info "Klone Repository nach $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Repository geklont"
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
    info "Generiere .env..."

    # DB_NAME/DB_USER/DB_ROOT_PASSWORD/DB_PASSWORD/JWT_SECRET kommen aus
    # ask_questions() (dort mit automatisch generiertem Default vorbelegt,
    # per Enter uebernehmbar oder ueberschreibbar).

    # Nur echte Bootstrap-Secrets/Infra-Werte landen in .env - alles was nach dem
    # ersten Start ueber die UI konfigurierbar ist (NFC-Geraet, Fernzugriff,
    # Session-Dauer etc.) bleibt bewusst aussen vor, siehe .env.example.
    cat > "$INSTALL_DIR/.env" <<EOF
# ============================================================
# SpaceCaptain — Umgebungsvariablen
# Generiert: $(date '+%Y-%m-%d %H:%M:%S')
# ============================================================

# Datenbank
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD

# JWT Auth
JWT_SECRET=$JWT_SECRET

# HTTP/HTTPS Ports
HTTP_PORT=80
HTTPS_PORT=443

# CORS — erlaubte Origins
ALLOWED_ORIGINS=https://$SERVER_HOST

# Zeitzone
TIMEZONE=$TIMEZONE
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
    info "Erstelle Admin-Benutzer '$ADMIN_NAME' und entferne den vorinstallierten Standard-Admin..."

    cd "$INSTALL_DIR"
    docker compose exec -T \
        -e SC_NAME="$ADMIN_NAME" \
        -e SC_EMAIL="$ADMIN_EMAIL" \
        -e SC_PASSWORD="$ADMIN_PASSWORD" \
        backend python3 -c "
import os, bcrypt, asyncio
from sqlalchemy import delete
from app.database import AsyncSessionLocal, engine
from app.models import User, UserRole

name     = os.environ['SC_NAME']
email    = os.environ['SC_EMAIL']
password = os.environ['SC_PASSWORD']

async def create():
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    async with AsyncSessionLocal() as db:
        # db/init.sql seedet bei jeder frischen DB einen Standard-Admin
        # (admin@spacecaptain.local, bekanntes Default-Passwort) - ueberfluessig
        # und ein Sicherheitsrisiko sobald der echte Admin existiert. Zuerst
        # entfernen, dann den echten Admin anlegen (deckt auch den Fall ab,
        # dass der echte Admin zufaellig dieselbe E-Mail verwendet).
        await db.execute(delete(User).where(User.email == 'admin@spacecaptain.local'))
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
    ok "Admin-Benutzer erstellt, Standard-Admin entfernt"
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
    echo -e "   ${BOLD}URL:${NC}       https://$SERVER_HOST/labmanager"
    echo -e "   ${BOLD}E-Mail:${NC}    $ADMIN_EMAIL"
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
