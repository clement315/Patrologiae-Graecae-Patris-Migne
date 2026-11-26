#!/usr/bin/env bash
# =====================================================================
#  PG OCR - PG 20, 21, 22 (Eusebius)                       (batch_20_22.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/batch_20_22.sh
#    VOLS="21 22" bash /mnt/e/PG_OCR/scripts/batch_20_22.sh     only some volumes
#
#  For each volume: full run (check, pdf, v4, v5, merge, report), works, columns;
#  then, if the page check (works/coverage.txt) names leaves of the second
#  scan that fill gaps of the main scan, they are recognised, merged and
#  the works are built again.
#
#  Second scan: IA item PatrologiaGraeca ("Patrologia Graeca Vol. 020" etc., another copy).
#  Columns (output/PGxxx/columns/): img/ holds one Greek scan slice per Migne column
#  (about 0.5-1 GB per volume, kept on this disk only).
#
#  Finished volumes leave work/PGxxx/batch.done and are skipped when the
#  script runs again; a volume that stopped is resumed (--from v5 when its
#  first run is complete).  One volume failing does not stop the others.
# =====================================================================
set -uo pipefail
ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
S="$ROOT/scripts"
VOLS="${VOLS:-20 21 22}"
LOG="$ROOT/work/batch_20_22_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$ROOT/work"
exec > >(tee -a "$LOG") 2>&1
failed=()

for v in $VOLS; do
    tag=$(printf 'PG%03d' "$v")
    mark="$ROOT/work/$tag/batch.done"
    if [ -f "$mark" ]; then echo "$tag already done ($(cat "$mark")) - skipped"; continue; fi
    printf '\n\033[1;36m===== %s  (%s) =====\033[0m\n' "$tag" "$(date '+%H:%M')"
    from=()
    [ -s "$ROOT/output/$tag/v4/summary.json" ] && from=(--from v5)
    if ! bash "$S/run_pg_volume.sh" "$v" --yes "${from[@]}"; then
        failed+=("$v"); echo "ERROR in $tag (OCR) - run this script again later, it resumes"; continue
    fi
    if ! bash "$S/pg_ocr.sh" "$v" works; then
        failed+=("$v"); echo "ERROR in $tag (works)"; continue
    fi
    # leaves of the second scan that fill gaps of the main scan
    leaves=$(grep -oE "leaf:[0-9][0-9,]*" "$ROOT/output/$tag/works/coverage.txt" 2>/dev/null | head -1)
    if [ -n "$leaves" ]; then
        echo "$tag: adding second-scan $leaves"
        SOURCE=alt RUN=v5 NOTIFY=0 bash "$S/pg_ocr.sh" "$v" "$leaves" \
          && bash "$S/pg_ocr.sh" "$v" merge v4,v5 \
          && bash "$S/pg_ocr.sh" "$v" works \
          || { failed+=("$v"); echo "ERROR in $tag (gap leaves)"; continue; }
    fi
    # column concordance: Greek scan slice, Greek text line by line, Migne's letters A-D
    if ! bash "$S/pg_ocr.sh" "$v" columns; then
        failed+=("$v"); echo "ERROR in $tag (columns)"; continue
    fi
    date '+%Y-%m-%d %H:%M' > "$mark"
done

echo
echo "finished $(date '+%Y-%m-%d %H:%M'); failed: ${failed[*]:-none}"
echo "log: $LOG"
bash "$S/notify.sh" "PG OCR: batch 20-22" "failed: ${failed[*]:-none}" 2>/dev/null || true
