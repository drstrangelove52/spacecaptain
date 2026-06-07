#!/bin/bash
# SpaceCaptain Update Watcher
# Läuft auf dem Host als systemd-Service.
# Wenn der Backend-Container die Datei update_trigger/trigger anlegt,
# führt dieses Skript git pull + docker compose up durch.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIGGER_FILE="$PROJECT_DIR/update_trigger/trigger"
RESTART_FILE="$PROJECT_DIR/update_trigger/restart"
LOG_FILE="$PROJECT_DIR/update_trigger/update.log"
STATUS_FILE="$PROJECT_DIR/update_trigger/update.status"

mkdir -p "$PROJECT_DIR/update_trigger"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "Update-Watcher gestartet (Projekt: $PROJECT_DIR)"

while true; do
  if [ -f "$RESTART_FILE" ]; then
    log "Restart-Trigger erkannt — starte Backend neu..."
    rm -f "$RESTART_FILE"
    cd "$PROJECT_DIR"
    _RESTART_BUILD=$(git rev-list --count HEAD)
    echo "$_RESTART_BUILD" > "$PROJECT_DIR/update_trigger/build_nr"
    if BUILD_NR=$_RESTART_BUILD docker compose up -d backend >> "$LOG_FILE" 2>&1; then
      log "Neustart abgeschlossen"
      echo "restarted" > "$STATUS_FILE"
    else
      log "FEHLER: Neustart fehlgeschlagen"
      echo "error" > "$STATUS_FILE"
    fi
  fi

  if [ -f "$TRIGGER_FILE" ]; then
    log "Trigger erkannt — starte Update..."
    rm -f "$TRIGGER_FILE"

    cd "$PROJECT_DIR"

    log "git pull..."
    GIT_OUT=$(git pull 2>&1)
    echo "$GIT_OUT" >> "$LOG_FILE"
    if [ $? -ne 0 ]; then
      log "FEHLER: git pull fehlgeschlagen"
      echo "error" > "$STATUS_FILE"
      sleep 10
      continue
    fi
    log "git pull erfolgreich"

    if echo "$GIT_OUT" | grep -q "Already up to date"; then
      log "Bereits aktuell — kein Rebuild nötig"
      echo "up_to_date" > "$STATUS_FILE"
    else
      BUILD_NR=$(git rev-list --count HEAD)
      echo "$BUILD_NR" > "$PROJECT_DIR/update_trigger/build_nr"
      log "Build-Nr: $BUILD_NR — starte docker compose up..."
      if BUILD_NR=$BUILD_NR docker compose up -d --build --force-recreate backend >> "$LOG_FILE" 2>&1; then
        log "Update abgeschlossen (Build $BUILD_NR)"
        echo "updated" > "$STATUS_FILE"
      else
        log "FEHLER: docker compose up fehlgeschlagen"
        echo "error" > "$STATUS_FILE"
      fi
    fi
  fi
  sleep 5
done
