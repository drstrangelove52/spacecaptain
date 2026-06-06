#!/bin/bash
# SpaceCaptain Update Watcher
# Läuft auf dem Host als systemd-Service.
# Wenn der Backend-Container die Datei update_trigger/trigger anlegt,
# führt dieses Skript git pull + docker compose up durch.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIGGER_FILE="$PROJECT_DIR/update_trigger/trigger"
LOG_FILE="$PROJECT_DIR/update_trigger/update.log"

mkdir -p "$PROJECT_DIR/update_trigger"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "Update-Watcher gestartet (Projekt: $PROJECT_DIR)"

while true; do
  if [ -f "$TRIGGER_FILE" ]; then
    log "Trigger erkannt — starte Update..."
    rm -f "$TRIGGER_FILE"

    cd "$PROJECT_DIR"

    log "git pull..."
    if git pull >> "$LOG_FILE" 2>&1; then
      log "git pull erfolgreich"
    else
      log "FEHLER: git pull fehlgeschlagen"
      sleep 10
      continue
    fi

    BUILD_NR=$(git rev-list --count HEAD)
    log "Build-Nr: $BUILD_NR — starte docker compose up..."
    if BUILD_NR=$BUILD_NR docker compose up -d --build backend >> "$LOG_FILE" 2>&1; then
      log "Update abgeschlossen (Build $BUILD_NR)"
    else
      log "FEHLER: docker compose up fehlgeschlagen"
    fi
  fi
  sleep 5
done
