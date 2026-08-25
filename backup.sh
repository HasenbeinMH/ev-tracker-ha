#!/bin/bash
# ============================================================
# EV-Tracker Backup Script  (läuft auf dem Docker-PC)
# Sichert die SQLite-Datenbank per rclone nach OneDrive.
# Cronjob: 0 2 * * * /home/smarthome/ev-tracker/backup.sh
# ============================================================

# ── Konfiguration ───────────────────────────────────────────
DATA_DIR="${EV_TRACKER_DATA_DIR:-/home/smarthome/ev-tracker/data}"
DB_SRC="$DATA_DIR/ev_tracker.db"
CONTAINER="ev-tracker"

RCLONE_REMOTE="onedrive:EV-Tracker-Backup"
RETENTION_DAYS=60

LOG_FILE="$DATA_DIR/backup.log"     # im Datenordner: Webapp kann mitlesen
TRIGGER="$DATA_DIR/.backup_now"    # von der Webapp angelegt = Backup anstossen
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
TMP_DIR="/tmp/ev-tracker-backup-$$"
# ────────────────────────────────────────────────────────────

mkdir -p "$TMP_DIR"
rm -f "$TRIGGER"
trap 'rm -rf "$TMP_DIR"' EXIT

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Backup gestartet: $TIMESTAMP"

FINAL_STATUS="error"
DB_SNAP="$TMP_DIR/ev_tracker_${TIMESTAMP}.db"

# ── 1. SQLite Hot-Backup ────────────────────────────────────
if [ ! -f "$DB_SRC" ]; then
    log "  ✗ Datenbank nicht gefunden: $DB_SRC"
    exit 1
fi

if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_SRC" ".backup '$DB_SNAP'" 2>> "$LOG_FILE"
else
    # Kein sqlite3 auf dem Host – Python im Container nutzen
    log "  sqlite3 nicht vorhanden, nutze Container-Python"
    docker exec "$CONTAINER" python -c "
import sqlite3
src = sqlite3.connect('/data/ev_tracker.db')
dst = sqlite3.connect('/tmp/snap.db')
with dst:
    src.backup(dst)
dst.close(); src.close()
" 2>> "$LOG_FILE" && docker cp "$CONTAINER:/tmp/snap.db" "$DB_SNAP" 2>> "$LOG_FILE" \
      && docker exec "$CONTAINER" rm -f /tmp/snap.db 2>> "$LOG_FILE"
fi

if [ -s "$DB_SNAP" ]; then
    log "  ✓ DB-Snapshot erstellt: $(du -h "$DB_SNAP" | cut -f1)"
else
    log "  ✗ DB-Snapshot fehlgeschlagen"
    exit 1
fi

# ── 2. Nach OneDrive hochladen ──────────────────────────────
log "Lade nach $RCLONE_REMOTE/data/ ..."
if rclone copy "$DB_SNAP" "${RCLONE_REMOTE}/data/" \
        --log-file="$LOG_FILE" --log-level=WARNING 2>> "$LOG_FILE"; then
    log "  ✓ Upload erfolgreich"
    FINAL_STATUS="ok"
else
    log "  ✗ Upload fehlgeschlagen"
fi

# ── 3. Alte Backups bereinigen ──────────────────────────────
rclone delete "${RCLONE_REMOTE}/data/" --min-age "${RETENTION_DAYS}d" \
    --include "ev_tracker_*.db" 2>> "$LOG_FILE" \
    && log "  ✓ Backups älter als ${RETENTION_DAYS} Tage bereinigt"

# ── 4. Status-Datei schreiben ───────────────────────────────
REMOTE_FILES=$(rclone ls "${RCLONE_REMOTE}/data/" 2>/dev/null | wc -l)
cat > "$DATA_DIR/backup_status.json" << STATUS
{
  "last_backup": "$TIMESTAMP",
  "last_backup_iso": "$(date -Iseconds)",
  "status": "$FINAL_STATUS",
  "size": "$(du -h "$DB_SNAP" | cut -f1)",
  "remote_files": $REMOTE_FILES
}
STATUS

log "Backup abgeschlossen ($FINAL_STATUS)"
log "=========================================="
