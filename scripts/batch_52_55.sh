#!/usr/bin/env bash
# =====================================================================
#  PG OCR - finish PG 52, then PG 53, 54, 55 in one go   (batch_52_55.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/batch_52_55.sh
#
#  1. PG 52: the leaf of the second scan that fills the gap p364/p374 is
#     recognised, the two runs are merged again and the works are rebuilt.
#  2. PG 53, 54, 55: full run (check, pdf, v4, v5, merge, report), then works.
#
#  Each finished step leaves a marker work/PGxxx/batch.done; running the
#  script again skips finished volumes and continues with the rest.  A volume
#  that stops (e.g. archive.org errors) is resumed with --from v5 on the
#  next run, the others go on.
# =====================================================================
set -uo pipefail
ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
S="$ROOT/scripts"
LOG="$ROOT/work/batch_52_55_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
failed=()

done_mark() { [ -f "$ROOT/work/$(printf 'PG%03d' "$1")/batch.done" ]; }
set_mark()  { date '+%Y-%m-%d %H:%M' > "$ROOT/work/$(printf 'PG%03d' "$1")/batch.done"; }

# ---- PG 52: fill the gap from the second scan -----------------------------
if done_mark 52; then
    echo "PG052 already done - skipped"
else
    printf '\n\033[1;36m===== PG052: second-scan leaf 364, merge, works =====\033[0m\n'
    if SOURCE=alt RUN=v5 NOTIFY=0 bash "$S/pg_ocr.sh" 52 leaf:364 \
       && bash "$S/pg_ocr.sh" 52 merge v4,v5 \
       && bash "$S/pg_ocr.sh" 52 works; then
        set_mark 52
    else
        failed+=(52); echo "ERROR in PG 52"
    fi
fi

# ---- PG 53-55 --------------------------------------------------------------
for v in 53 54 55; do
    tag=$(printf 'PG%03d' "$v")
    if done_mark "$v"; then echo "$tag already done - skipped"; continue; fi
    printf '\n\033[1;36m===== %s =====\033[0m\n' "$tag"
    from=()
    # a volume whose v4 run is complete but stopped later: continue with the second scan
    if [ -s "$ROOT/output/$tag/v4/summary.json" ]; then from=(--from v5); fi
    if bash "$S/run_pg_volume.sh" "$v" --yes "${from[@]}" && bash "$S/pg_ocr.sh" "$v" works; then
        set_mark "$v"
    else
        failed+=("$v"); echo "ERROR in $tag - run this script again later (it resumes)"
    fi
done

echo
echo "finished; failed: ${failed[*]:-none}"
echo "log: $LOG"
bash "$S/notify.sh" "PG OCR: batch 52-55" "failed: ${failed[*]:-none}" 2>/dev/null || true
