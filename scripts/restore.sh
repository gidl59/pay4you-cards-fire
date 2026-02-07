#!/usr/bin/env bash
set -euo pipefail

# =========================
# Pay4You - Restore
# Ripristino DB (SQLite) + uploads da backup creati con backup.sh
# - Fa un "safety backup" prima di sovrascrivere
# - Ripristina DB e cartella uploads
# - Supporta .tar.gz o .tar
# =========================

APP_NAME="${APP_NAME:-pay4you-cards}"

DB_PATH="${DB_PATH:-/var/data/data.db}"
UPLOADS_DIR="${UPLOADS_DIR:-/var/data/uploads}"
BACKUP_DIR="${BACKUP_DIR:-/var/data/backups}"

# Dove mettere copie di sicurezza prima di sovrascrivere
SAFETY_DIR="${SAFETY_DIR:-/var/data/restore_safety}"
mkdir -p "$SAFETY_DIR"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: comando mancante: $1" >&2; exit 1; }; }
need_cmd tar
need_cmd ls
need_cmd mkdir
need_cmd cp
need_cmd mv
need_cmd rm
need_cmd date
need_cmd awk
need_cmd sed

log(){ echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
die(){ echo "ERROR: $*" >&2; exit 1; }

usage(){
  cat <<EOF
USO:
  ./scripts/restore.sh --ts YYYYMMDD-HHMMSS
  oppure
  ./scripts/restore.sh --db /var/data/backups/<file>.db

ESEMPI:
  ./scripts/restore.sh --ts 20260207-120000
  ./scripts/restore.sh --db /var/data/backups/pay4you-cards_host_20260207-120000.db

NOTE IMPORTANTI:
- Su Render è consigliato fare restore quando l'app NON sta scrivendo sul DB (idealmente stop/restart).
- Questo script sovrascrive DB e uploads dopo aver creato una copia di sicurezza.
EOF
}

TS=""
DB_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ts) TS="${2:-}"; shift 2 ;;
    --db) DB_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Argomento non riconosciuto: $1" ;;
  esac
done

if [[ -z "$TS" && -z "$DB_FILE" ]]; then
  usage
  exit 1
fi

if [[ -n "$TS" ]]; then
  # trova DB e uploads con quel timestamp (host può variare)
  DB_FILE_FOUND="$(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_"${TS}.db" 2>/dev/null | head -n 1 || true)"
  [[ -n "$DB_FILE_FOUND" ]] || die "Non trovo DB backup per TS=$TS in $BACKUP_DIR"
  DB_FILE="$DB_FILE_FOUND"

  UP_GZ="$(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_"${TS}"_uploads.tar.gz 2>/dev/null | head -n 1 || true)"
  UP_TAR="$(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_"${TS}"_uploads.tar 2>/dev/null | head -n 1 || true)"
else
  [[ -f "$DB_FILE" ]] || die "DB backup non trovato: $DB_FILE"
  base="$(basename "$DB_FILE")"
  TS="$(echo "$base" | sed -E 's/^'"$APP_NAME"'_([^_]+)_([0-9]{8}-[0-9]{6})\.db$/\2/')"
  [[ "$TS" =~ ^[0-9]{8}-[0-9]{6}$ ]] || die "Impossibile estrarre TS dal nome file DB: $base"

  UP_GZ="$(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_"${TS}"_uploads.tar.gz 2>/dev/null | head -n 1 || true)"
  UP_TAR="$(ls -1 "$BACKUP_DIR"/"${APP_NAME}"_*_"${TS}"_uploads.tar 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "$UP_GZ" && -z "$UP_TAR" ]]; then
  die "Non trovo archivio uploads per TS=$TS (tar.gz o tar) in $BACKUP_DIR"
fi

UPLOAD_ARCHIVE="${UP_GZ:-$UP_TAR}"

log "Ripristino da:"
log "  DB:      $DB_FILE"
log "  UPLOADS: $UPLOAD_ARCHIVE"

# 1) Safety backup prima di sovrascrivere
SAFETY_TS="$(date -u '+%Y%m%d-%H%M%S')"
SAFETY_DB="$SAFETY_DIR/data.db.before_${SAFETY_TS}"
SAFETY_UP="$SAFETY_DIR/uploads.before_${SAFETY_TS}.tar.gz"

log "Creo SAFETY backup (prima di sovrascrivere)..."
if [[ -f "$DB_PATH" ]]; then
  cp -f "$DB_PATH" "$SAFETY_DB"
  log "  Safety DB: $SAFETY_DB"
else
  log "  DB corrente non trovato, salto safety DB."
fi

if [[ -d "$UPLOADS_DIR" ]]; then
  tar -C "$(dirname "$UPLOADS_DIR")" -czf "$SAFETY_UP" "$(basename "$UPLOADS_DIR")"
  log "  Safety uploads: $SAFETY_UP"
else
  log "  Uploads correnti non trovati, salto safety uploads."
fi

# 2) Ripristina DB (sovrascrive)
log "Ripristino DB..."
mkdir -p "$(dirname "$DB_PATH")"
cp -f "$DB_FILE" "$DB_PATH"
log "DB ripristinato in: $DB_PATH"

# 3) Ripristina uploads in modo pulito (estrai in tmp poi sostituisci)
log "Ripristino uploads..."
TMP_DIR="/tmp/restore_${APP_NAME}_${TS}_$$"
mkdir -p "$TMP_DIR"

tar -C "$TMP_DIR" -xf "$UPLOAD_ARCHIVE"

# L'archivio contiene la cartella "uploads"
if [[ ! -d "$TMP_DIR/uploads" ]]; then
  die "Archivio uploads non contiene la cartella 'uploads' (trovato: $(ls -1 "$TMP_DIR" || true))"
fi

# Sostituzione atomica: rinomina vecchia e sposta nuova
OLD_DIR="${UPLOADS_DIR}.old_${SAFETY_TS}"
if [[ -d "$UPLOADS_DIR" ]]; then
  mv "$UPLOADS_DIR" "$OLD_DIR"
  log "Uploads correnti spostati in: $OLD_DIR"
fi

mv "$TMP_DIR/uploads" "$UPLOADS_DIR"
rm -rf "$TMP_DIR"

log "Uploads ripristinati in: $UPLOADS_DIR"

log "✅ Restore completato."
log "Ora RIAVVIA il servizio su Render (o fai redeploy/restart) per essere sicuro che ricarichi tutto."
