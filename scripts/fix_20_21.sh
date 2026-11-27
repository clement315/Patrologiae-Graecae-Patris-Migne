#!/usr/bin/env bash
# =====================================================================
#  PG OCR - fill the leaves missing in the main scans of PG 20 and PG 21
#  (fix_20_21.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/fix_20_21.sh
#
#  The Google scans used as main scans repeat and shuffle a few pages and
#  lack others (the text breaks off; the second scan has the leaves).  The
#  leaves are recognised from the second scan (IA PatrologiaGraeca), the two
#  runs are merged again, the works and the column concordance are rebuilt;
#  pg_works.py puts the leaves in place (SCAN_FIXES "order").
#    PG 20:  6 leaves (end of De laudibus Constantini / De martyribus Palaestinae)
#    PG 21: 11 leaves (Praeparatio evangelica II and IV)
#  Then PG 22: works and column concordance again (repeated pages dropped).
#  A finished volume leaves work/PGxxx/fix.done and is skipped next time.
# =====================================================================
set -uo pipefail
ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
S="$ROOT/scripts"
LOG="$ROOT/work/fix_20_21_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
failed=()

declare -A LEAVES=(
  [20]="605,608,609,610,612,613"
  [21]="88,95,96,97,98,183,184,185,186,187,188"
)

for v in 20 21; do
    tag=$(printf 'PG%03d' "$v")
    mark="$ROOT/work/$tag/fix.done"
    if [ -f "$mark" ]; then echo "$tag already done ($(cat "$mark")) - skipped"; continue; fi
    printf '\n\033[1;36m===== %s: second-scan leaves %s =====\033[0m\n' "$tag" "${LEAVES[$v]}"
    if SOURCE=alt RUN=v5 NOTIFY=0 bash "$S/pg_ocr.sh" "$v" "leaf:${LEAVES[$v]}" \
       && bash "$S/pg_ocr.sh" "$v" merge v4,v5 \
       && bash "$S/pg_ocr.sh" "$v" works \
       && bash "$S/pg_ocr.sh" "$v" columns; then
        date '+%Y-%m-%d %H:%M' > "$mark"
    else
        failed+=("$v"); echo "ERROR in $tag - run this script again later"
    fi
done

# PG 22: runs of repeated pages are now dropped (pg_works 1.48): column concordance again
if [ ! -f "$ROOT/work/PG022/fix.done" ]; then
    printf '\n\033[1;36m===== PG022: works and columns again =====\033[0m\n'
    if bash "$S/pg_ocr.sh" 22 works && bash "$S/pg_ocr.sh" 22 columns; then
        date '+%Y-%m-%d %H:%M' > "$ROOT/work/PG022/fix.done"
    else
        failed+=(22); echo "ERROR in PG022"
    fi
fi

echo
echo "finished $(date '+%Y-%m-%d %H:%M'); failed: ${failed[*]:-none}"
echo "log: $LOG"
bash "$S/notify.sh" "PG OCR: fix 20, 21" "failed: ${failed[*]:-none}" 2>/dev/null || true
