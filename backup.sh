#!/bin/bash
# =============================================================
# Makerspace — Automatisches Backup-Skript
# Nutzt die eingebaute JSON-Export-API (/api/backup/export)
#
# Konfiguration via .env:
#   BACKUP_EMAIL     Admin-E-Mail für die API-Authentifizierung
#   BACKUP_PASSWORD  Passwort des Admin-Accounts
#   BACKUP_DIR       Zielverzeichnis (Standard: ./backups)
#   BACKUP_KEEP      Anzahl zu behaltender Backups (Standard: 30)
#   HTTP_PORT        API-Port (Standard: 80)
#
# Cron-Beispiel (täglich um 03:00 Uhr):
#   0 3 * * * /home/martin/makerspace/backup.sh >> /home/martin/makerspace/backups/backup.log 2>&1
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# .env laden (falls vorhanden)
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# Konfiguration mit Standardwerten
API_BASE="http://localhost:${HTTP_PORT:-80}/api"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-30}"

# Pflichtfelder prüfen
if [ -z "${BACKUP_EMAIL:-}" ] || [ -z "${BACKUP_PASSWORD:-}" ]; then
    echo "FEHLER: BACKUP_EMAIL und BACKUP_PASSWORD müssen in .env gesetzt sein." >&2
    exit 1
fi

# Backup-Verzeichnis anlegen
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_FILE="$BACKUP_DIR/makerspace-backup-${TIMESTAMP}.json.gz"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Makerspace Backup gestartet ==="
log "Ziel: $BACKUP_FILE"

# ── 1. JWT-Token holen ────────────────────────────────────────
log "Authentifiziere als ${BACKUP_EMAIL}..."

LOGIN_RESPONSE=$(curl -sf \
    --max-time 30 \
    -X POST "${API_BASE}/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${BACKUP_EMAIL}\",\"password\":\"${BACKUP_PASSWORD}\"}") || {
    log "FEHLER: Login-Request fehlgeschlagen (API erreichbar?)"
    exit 1
}

TOKEN=$(echo "$LOGIN_RESPONSE" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) || {
    log "FEHLER: Kein Token erhalten. Zugangsdaten korrekt?"
    exit 1
}

log "Login erfolgreich."

# ── 2. Export durchführen ─────────────────────────────────────
log "Exportiere Daten..."

TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

HTTP_STATUS=$(curl -sf \
    --max-time 120 \
    -o "$TMP_FILE" \
    -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API_BASE}/backup/export") || {
    log "FEHLER: Export-Request fehlgeschlagen."
    exit 1
}

if [ "$HTTP_STATUS" != "200" ]; then
    log "FEHLER: API antwortete mit HTTP ${HTTP_STATUS}."
    exit 1
fi

if [ ! -s "$TMP_FILE" ]; then
    log "FEHLER: Leere Antwort vom Server."
    exit 1
fi

# JSON validieren und komprimiert speichern
python3 -c "import sys,json; json.load(sys.stdin)" < "$TMP_FILE" || {
    log "FEHLER: Ungültiges JSON in der Serverantwort."
    exit 1
}

gzip -c "$TMP_FILE" > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
RECORDS=$(python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Benutzer:{len(d.get('users',[]))} Gäste:{len(d.get('guests',[]))} Maschinen:{len(d.get('machines',[]))} Sessions:{len(d.get('sessions',[]))}\")
" < "$TMP_FILE")

log "Backup erstellt: $(basename "$BACKUP_FILE") (${SIZE}, ${RECORDS})"

# ── 3. Backup-Rotation ────────────────────────────────────────
log "Backup-Rotation: behalte die letzten ${BACKUP_KEEP} Backups..."

DELETED=0
while IFS= read -r OLD_FILE; do
    rm -f "$OLD_FILE"
    log "Gelöscht: $(basename "$OLD_FILE")"
    DELETED=$((DELETED + 1))
done < <(ls -1t "$BACKUP_DIR"/makerspace-backup-*.json.gz 2>/dev/null \
    | tail -n +$((BACKUP_KEEP + 1)))

REMAINING=$(ls -1 "$BACKUP_DIR"/makerspace-backup-*.json.gz 2>/dev/null | wc -l)
log "Rotation: ${DELETED} alte(s) Backup(s) gelöscht, ${REMAINING} verbleiben."

log "=== Backup erfolgreich abgeschlossen ==="
