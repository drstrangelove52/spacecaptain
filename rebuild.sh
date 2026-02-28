#!/bin/bash
# =============================================================
# SpaceCaptain — Rebuild / Update Script
#
# Holt die aktuelle Version von Git und startet die Container
# neu. Alle bestehenden Container und Volumes werden gelöscht.
#
# Verwendung:
#   sudo bash rebuild.sh /pfad/zur/.env    # .env übergeben
#   sudo bash rebuild.sh                   # .env muss bereits im Projektordner liegen
# =============================================================

set -e

REPO_URL="git@github.com:drstrangelove52/spacecaptain.git"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}▶ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $1${NC}"; }
error() { echo -e "${RED}✗ $1${NC}"; exit 1; }

# ── .env auswerten ────────────────────────────────────────────
ENV_SOURCE="${1:-}"
if [ -n "$ENV_SOURCE" ]; then
    [ -f "$ENV_SOURCE" ] || error ".env nicht gefunden: $ENV_SOURCE"
    info ".env Quelle: $(realpath "$ENV_SOURCE")"
elif [ -f "$APP_DIR/.env" ]; then
    ENV_SOURCE="$APP_DIR/.env"
    info ".env bereits vorhanden im Projektordner."
else
    error "Keine .env angegeben und keine in $APP_DIR gefunden.\n  Verwendung: sudo bash rebuild.sh /pfad/zur/.env"
fi

# ── Bestätigung ───────────────────────────────────────────────
warn "Alle Container, Volumes und Daten werden GELÖSCHT."
read -rp "Fortfahren? [j/N] " confirm
[[ "$confirm" =~ ^[jJ]$ ]] || { echo "Abgebrochen."; exit 0; }

# ── Git: neueste Version holen ────────────────────────────────
[ -d "$APP_DIR/.git" ] || error "Kein Git-Repository in $APP_DIR.\n  Bitte zuerst klonen: git clone $REPO_URL"

# Bei sudo den echten User verwenden (SSH-Keys liegen beim User, nicht bei root)
GIT_USER="${SUDO_USER:-$(whoami)}"
info "Hole aktuelle Version von Git (als $GIT_USER)..."
sudo -u "$GIT_USER" git -C "$APP_DIR" pull --ff-only \
    || error "Git pull fehlgeschlagen. SSH-Key für '$GIT_USER' eingerichtet?"

# ── .env kopieren (falls externe Quelle angegeben) ───────────
if [ "$(realpath "$ENV_SOURCE")" != "$(realpath "$APP_DIR/.env" 2>/dev/null || echo "")" ]; then
    info "Kopiere .env..."
    cp "$ENV_SOURCE" "$APP_DIR/.env"
fi

# ── Container stoppen & alles löschen ────────────────────────
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    info "Container stoppen und Volumes löschen..."
    docker compose -f "$APP_DIR/docker-compose.yml" down -v --rmi all 2>/dev/null || true
else
    warn "Kein docker-compose.yml gefunden — überspringe Container-Abbau."
fi

# ── Container bauen & starten ─────────────────────────────────
info "Container bauen und starten..."
docker compose -f "$APP_DIR/docker-compose.yml" up -d --build

# ── Warten bis Backend antwortet ─────────────────────────────
info "Warte auf Backend..."
for i in $(seq 1 30); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/api/auth/me 2>/dev/null || true)
    if [[ "$STATUS" =~ ^(200|401|422)$ ]]; then
        break
    fi
    sleep 2
done

info "Fertig! SpaceCaptain läuft."
echo ""
echo "  URL:      http://$(hostname -I | awk '{print $1}')"
echo "  Login:    admin@makerspace.local / admin1234"
echo ""
