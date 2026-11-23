#!/usr/bin/env bash
# =====================================================================
#  PG OCR - PG 8, 9 (Clement), 11-14, 17 (Origen)          (batch_clem_orig.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/batch_clem_orig.sh
#    VOLS="11 12" bash /mnt/e/PG_OCR/scripts/batch_clem_orig.sh     only some volumes
#
#  For each volume: full run (check, pdf, v4, v5, merge, report), works, columns;
#  then, if the page check (works/coverage.txt) names leaves of the second
#  scan that fill gaps of the main scan, they are recognised, merged and
#  the works are built again.
#
#  Second scans: PatrologiaGraeca (PG 8, 9); PG 11-14 and 17 are not in that item - another
#  Internet Archive copy is read instead (pg_ocr.sh, function alt_item).
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
VOLS="${VOLS:-8 9 11 12 13 14 17}"
LOG="$ROOT/work/batch_clem_orig_$(date +%Y%m%d_%H%M%S).log"
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
bash "$S/notify.sh" "PG OCR: batch Clement, Origen" "failed: ${failed[*]:-none}" 2>/dev/null || true
