#!/usr/bin/env bash
# Load every CSV in outputs/site_data into the OrthoParity database with psql, then run 07_after_import.sql.
# For people who prefer the command line to the Supabase dashboard importer.
#   Usage:  DATABASE_URL="postgresql://..." bash supabase/load_csv.sh [outputs/site_data]
# Uses the database password in DATABASE_URL. Keep that URL out of git (it is a secret).
set -euo pipefail
DIR="${1:-outputs/site_data}"
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${DATABASE_URL:?Set DATABASE_URL to your database connection string first}"
for f in "$DIR"/pc_*.csv; do
  t="$(basename "$f" .csv)"
  cols="$(head -1 "$f" | tr -d '\r\n\357\273\277')"   # load by header names (pc_op_research has an extra column)
  echo "Loading $t"
  psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -c "truncate $t" -c "\\copy $t ($cols) from '$f' csv header"
done
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$HERE/07_after_import.sql"
