#!/usr/bin/env bash
set -euo pipefail

# =========================
# Pay4You - Backup automatico
# DB (SQLite) + uploads
# - Rotazione backup
# - WAL checkpoint
# - Timeout/busy handling
# - Lock per evitare esecuzioni sovrapposte
# =========================

# ---- Config (puoi cambiare) ----
DB_PATH="${DB_PATH:-/var/data/data.db}"
UPLOADS_DIR="${UPLOADS_DIR:-/var/data/uploads}"
BACKUP_DIR="${BACKUP_DIR:-/var/data/backups}"

# Quanti backup tenere (rotazione)
KEEP="${KEEP:-20}"

# Timeout SQLite (ms) e tentativi
SQLITE_BUSY_TIMEOUT_MS="${SQLITE_BUSY_TIMEOUT_MS:-10000}"

# Nome app (per i nomi file)
APP_NAME="${APP_NAME:-pay4you-cards}"

# Lock file
LOCK_FILE="${LOCK_FILE:-/var/data/.backup.lock}"

# Compressione: "gzip" o "none"
COMPRESS="${COMPRESS:-gzip}"

# ---- Helpers ----
log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"
}

# ---- Check requisiti ----
need_cmd sqlite3
need_cmd tar
need_cmd find
need_cmd awk
need_cmd sed
need_cmd date

# ---- Check percorsi ----
[ -f "$DB_PATH" ] || die "DB non trovato: $DB_PATH"
[ -d "$UPLOADS_DIR" ] || die "Uploads non trovati: $UPLOADS_DIR"

mkdir -p "$BACKUP_DIR"

# ---- Lock (evita doppio backup contemporaneo) ----
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Backup già in esecuzione (lock attivo). Esco."
  exit 0
fi

# ---- Timestamp ----
TS="$(date -u '+%Y%m%d-%H%M%S')"
HOST="$(hostname || echo 'host')"

DB_BAK="${BACKUP_DIR}/${APP_NAME}_${HOST}_${TS}.db"
META_TXT="${BACKUP_DIR}/${APP_NAME}_${HOST}_${TS}.meta.txt"

# Archivio uploads
if [ "$COMPRESS" = "gzip" ]; then
  UP_TAR="${BACKUP_DIR}/${APP_NAME}_${HOST}_${TS}_uploads.tar.gz"
else
  UP_TAR="${BACKUP_DIR}/${APP_NAME}_${HOST}_${TS}_uploads.tar"
fi

# ---- Funzione SQLite: checkpoint + backup consistente ----
sqlite_safe_backup() {
  local src="$1"
  local dst="$2"

  log "SQLite busy_timeout=${SQLITE_BUSY_TIMEOUT_MS}ms"
  log "WAL checkpoint (TRUNCATE) + backup DB..."

  # Nota:
  # - busy_timeout per evitare errori 'database is locked'
  # - wal_checkpoint(TRUNCATE) prova a compattare wal
  # - .backup fa una copia consistente anche se DB è in uso
  sqlite3 "$src" <<SQL
PRAGMA busy_timeout=${SQLITE_BUSY_TIMEOUT_MS};
PRAGMA journal_mode=WAL;
PRAGMA wal_checkpoint(TRUNCATE);
.backup '${dst}'
PRAGMA integrity_check;
SQL
}

# ---- Backup DB ----
sqlite_safe_backup "$DB_PATH" "$DB_BAK"
log "DB salvato: $DB_BAK ($(du -h "$DB_BAK" | awk '{print $1}'))"

# ---- Backup uploads (tar) ----
log "Creo archivio uploads..."
if [ "$COMPRESS" = "gzip" ]; then
  # -C per mantenere path puliti
  tar -C "$(dirname "$UPLOADS_DIR")" -czf "$UP_TAR" "$(basename "$UPLOADS_DIR")"
else
  tar -C "$(dirname "$UPLOADS_DIR")" -cf "$UP_TAR" "$(basename "$UPLOADS_DIR")"
fi
log "Uploads salvati: $UP_TAR ($(du -h "$UP_TAR" | awk '{print $1}'))"

# ---- Meta info (utile per verifiche) ----
{
  echo "timestamp_utc=$TS"
  echo "host=$HOST"
  echo "db_path=$DB_PATH"
  echo "uploads_dir=$UPLOADS_DIR"
  echo "db_backup_file=$(basename "$DB_BAK")"
  echo "uploads_backup_file=$(basename "$UP_TAR")"
  echo "db_backup_size=$(du -b "$DB_BAK" 2>/dev/null | awk '{print $1}' || true)"
  echo "uploads_backup_size=$(du -b "$UP_TAR" 2>/dev/null | awk '{print $1}' || true)"
  echo "keep=$KEEP"
  echo "compress=$COMPRESS"
} > "$META_TXT"

log "Meta salvata: $META_TXT"

# ---- Rotazione (tieni ultimi KEEP) ----
log "Rotazione: tengo gli ultimi $KEEP backup."

# Raggruppiamo per timestamp: ogni backup ha 3 file (db + uploads + meta)
# Qui facciamo rotazione semplice:
# - ordiniamo i file DB per data (sono nel nome)
# - per quelli oltre KEEP, cancelliamo DB + uploads + meta con stesso TS
mapfile -t db_files < <(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_*.db 2>/dev/null | sort || true)

total="${#db_files[@]}"
if [ "$total" -gt "$KEEP" ]; then
  to_delete=$(( total - KEEP ))
  log "Backup presenti: $total. Da eliminare: $to_delete."

  for ((i=0; i<to_delete; i++)); do
    f="${db_files[$i]}"
    base="$(basename "$f")"

    # Estraiamo TS dal nome: APP_HOST_TS.db  -> TS è la penultima parte dopo _
    # Esempio: pay4you-cards_host_20260207-101500.db
    ts_part="$(echo "$base" | sed -E 's/^'"$APP_NAME"'_([^_]+)_([0-9]{8}-[0-9]{6})\.db$/\2/')"
    host_part="$(echo "$base" | sed -E 's/^'"$APP_NAME"'_([^_]+)_([0-9]{8}-[0-9]{6})\.db$/\1/')"

    if [[ "$ts_part" =~ ^[0-9]{8}-[0-9]{6}$ ]]; then
      old_db="$BACKUP_DIR/${APP_NAME}_${host_part}_${ts_part}.db"
      old_meta="$BACKUP_DIR/${APP_NAME}_${host_part}_${ts_part}.meta.txt"
      old_up_gz="$BACKUP_DIR/${APP_NAME}_${host_part}_${ts_part}_uploads.tar.gz"
      old_up_tar="$BACKUP_DIR/${APP_NAME}_${host_part}_${ts_part}_uploads.tar"

      rm -f "$old_db" "$old_meta" "$old_up_gz" "$old_up_tar"
      log "Eliminato set backup TS=$ts_part (host=$host_part)"
    else
      # fallback: elimina solo il db se parsing fallisce
      rm -f "$f"
      log "Eliminato file (fallback): $f"
    fi
  done
else
  log "Rotazione: nulla da eliminare (presenti $total)."
fi

log "✅ Backup completato con successo."

