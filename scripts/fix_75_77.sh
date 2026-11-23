#!/usr/bin/env bash
# =====================================================================
#  PG OCR - fill the leaves missing in the main scans of PG 75 and PG 77
#  (fix_75_77.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/fix_75_77.sh
#
#  The Google scans used as main scans of PG 75 and PG 77 lack some leaves
#  (the text breaks off between two pages; the running heads jump).  The
#  leaves are recognised from the second scan (IA PatrologiaGraeca), the two
#  runs are merged again and the works are rebuilt; pg_works.py puts the
#  leaves in place (SCAN_FIXES "order").
#    PG 75: 10 leaves (Thesaurus, De Trinitate dialogi, De sancta Trinitate)
#    PG 77: 22 leaves (homilies, Theodotus Ancyranus, Paulus Emesenus)
#  A finished volume leaves work/PGxxx/fix.done and is skipped next time.
# =====================================================================
set -uo pipefail
ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
S="$ROOT/scripts"
LOG="$ROOT/work/fix_75_77_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
failed=()

declare -A LEAVES=(
  [75]="292,467,475,631,633,635,639,651,655,661"
  [77]="475,476,501,505,506,555,559,566,567,568,570,571,572,701,705,727,728,737,739,740,767,768"
)

for v in 75 77; do
    tag=$(printf 'PG%03d' "$v")
    mark="$ROOT/work/$tag/fix.done"
    if [ -f "$mark" ]; then echo "$tag already done ($(cat "$mark")) - skipped"; continue; fi
    printf '\n\033[1;36m===== %s: second-scan leaves %s =====\033[0m\n' "$tag" "${LEAVES[$v]}"
    if SOURCE=alt RUN=v5 NOTIFY=0 bash "$S/pg_ocr.sh" "$v" "leaf:${LEAVES[$v]}" \
       && bash "$S/pg_ocr.sh" "$v" merge v4,v5 \
       && bash "$S/pg_ocr.sh" "$v" works; then
        date '+%Y-%m-%d %H:%M' > "$mark"
    else
        failed+=("$v"); echo "ERROR in $tag - run this script again later"
    fi
done

echo
echo "finished $(date '+%Y-%m-%d %H:%M'); failed: ${failed[*]:-none}"
echo "log: $LOG"
bash "$S/notify.sh" "PG OCR: fix 75, 77" "failed: ${failed[*]:-none}" 2>/dev/null || true
