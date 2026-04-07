#!/usr/bin/env bash
set -euo pipefail

# Cross-platform full rebuild of SQLite DB from CSVs (optimized for WSL/Linux)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$ROOT_DIR/data/financial_data.db"
CSV_DIR="$ROOT_DIR/data"
SQL_DIR="$ROOT_DIR/sql"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "[ERROR] sqlite3 CLI not found. Please install sqlite3." >&2
  exit 1
fi

echo "Rebuilding database at: $DB_PATH"
rm -f "$DB_PATH"

# Initialize DB and create share_prices schema with fast pragmas
sqlite3 "$DB_PATH" <<'SQL'
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-800000;
.read sql/schema_prices.sql
SQL

echo "Importing CSVs using sqlite3 .import (price data)..."

# Import price data (semicolon-separated)
sqlite3 "$DB_PATH" \
  ".mode csv" \
  ".separator ;" \
  ".import --skip 1 $CSV_DIR/us-shareprices-daily.csv share_prices"

# Index and optimize (centralized definitions)
sqlite3 "$DB_PATH" \
  ".read sql/indexes_prices.sql" \
  "ANALYZE;" \
  "VACUUM;"

echo "Importing financial statements via project CLI (with cleanup/renames)..."
# Prefer CLI with explicit flag; fall back to module exec if CLI not available
if command -v stockq >/dev/null 2>&1; then
  stockq load-data --skip-prices
else
  SKIP_PRICES=1 "$ROOT_DIR/.venv/bin/python" -c "from stock_analysis.load_data_to_db import main; main()"
fi

echo "Done. Database rebuilt at: $DB_PATH"
