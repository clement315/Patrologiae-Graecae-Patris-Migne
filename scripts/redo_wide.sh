#!/usr/bin/env bash
# =====================================================================
#  PG OCR - read again the Greek set across the full page width   (redo_wide.sh)
#
#  Up to pg_ocr_volume.py 3.4 every "Greek" box wider than 60% of the page was taken
#  for Latin crossing text and left out.  In the Greek-Latin volumes, however, the Greek
#  often runs across the whole page where the Latin version is shorter (e.g. PG 44
#  p.166, p.222: the end of the De vita Moysis), so those lines were missing.
#  This script lays out again only the pages concerned, recognises them, merges the
#  runs as before and splits the volume into works again.
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/redo_wide.sh 44            one volume
#    bash /mnt/e/PG_OCR/scripts/redo_wide.sh all           every finished volume, one after another
#    bash /mnt/e/PG_OCR/scripts/redo_wide.sh 26 27 28      several volumes
#
#  Re-running continues where it stopped (finished pages are not redone).
#
#    TEXT_ONLY=1 bash .../redo_wide.sh all
#        only rebuild text, merge and works from the finished OCR (minutes per volume): needed once
#        after pg_ocr_volume 3.7, because 3.5/3.6 did not mark the full-width blocks for the text stage
# =====================================================================
set -uo pipefail

ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
SCRIPTS="$ROOT/scripts"
ALL=(25 26 27 28 29 30 31 32 33 35 36 37 38 44 45 94 95 96)
MARK="redo_wide.done"; MODE=(REDO_WIDE=1)
if [ -n "${TEXT_ONLY:-}" ]; then MARK="text37.done"; MODE=(STAGES=text); fi

# second run of each volume: "tag|source|alt pdf" and the merge spec
second() {
    case "$1" in
        25) echo "v6|pdf2|$ROOT/data/pdf/PG025_oxford.pdf" ;;
        95) echo "v6|pdf2|$ROOT/data/pdf/Patrologiae_cursus_completus_seu_Bibliot.pdf" ;;
        30) echo "" ;;                                   # one scan only (+ pages of other copies)
        *)  echo "v5|alt|" ;;
    esac
}
merge_spec() {
    case "$1" in
        25) echo "v4,v6" ;;
        30) echo "v4,v4+patch2" ;;
        95) echo "v4,v6+patch" ;;
        *)  echo "v4,v5" ;;
    esac
}

# first..last page already laid out in a run (a redo never adds pages)
range_of() {
    python3 - "$1" <<'PY'
import json, sys
ps = [json.loads(l)["page"] for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
ps = [p for p in ps if p < 10000]
print(f"{min(ps)}-{max(ps)}" if ps else "")
PY
}

one() {
    local vol="$1" tag run src apdf spec rng t0
    tag="$(printf 'PG%03d' "$vol")"
    t0=$(date +%s)
    printf '\n\033[1;36m===== %s: Greek across the full page width =====\033[0m\n' "$tag"
    [ -s "$ROOT/work/$tag/v4/layout.jsonl" ] || { echo "no v4 run for $tag - skipped"; return 0; }
    if [ -f "$ROOT/work/$tag/$MARK" ]; then
        echo "$tag already done ($(cat "$ROOT/work/$tag/$MARK")) - skipped (delete work/$tag/$MARK to redo)"
        return 0
    fi

    rng="$(range_of "$ROOT/work/$tag/v4/layout.jsonl")"
    NOTIFY=0 env "${MODE[@]}" RUN=v4 bash "$SCRIPTS/pg_ocr.sh" "$vol" "$rng" || return 1

    IFS='|' read -r run src apdf <<< "$(second "$vol")"
    if [ -n "$run" ] && [ -s "$ROOT/work/$tag/$run/layout.jsonl" ]; then
        rng="$(range_of "$ROOT/work/$tag/$run/layout.jsonl")"
        if [ "$src" = "pdf2" ]; then
            NOTIFY=0 env "${MODE[@]}" SOURCE=pdf2 ALT_PDF="$apdf" RUN="$run" bash "$SCRIPTS/pg_ocr.sh" "$vol" "$rng" || return 1
        else
            NOTIFY=0 env "${MODE[@]}" SOURCE=alt RUN="$run" bash "$SCRIPTS/pg_ocr.sh" "$vol" "$rng" || return 1
        fi
    fi

    spec="$(merge_spec "$vol")"
    bash "$SCRIPTS/pg_ocr.sh" "$vol" merge "$spec" || return 1
    bash "$SCRIPTS/pg_ocr.sh" "$vol" works || return 1
    date '+%Y-%m-%d %H:%M' > "$ROOT/work/$tag/$MARK"
    printf '\033[1;32m%s done in %d min\033[0m\n' "$tag" $(( ($(date +%s) - t0) / 60 ))
}

[ $# -gt 0 ] || { sed -n 2,19p "$0"; exit 2; }
vols=("$@")
[ "$1" = "all" ] && vols=("${ALL[@]}")
LOG="$ROOT/work/redo_wide_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
failed=()
for v in "${vols[@]}"; do
    one "$v" || { failed+=("$v"); echo "ERROR in PG $v - run 'bash $0 $v' again later"; }
done
echo
echo "finished: ${vols[*]}   failed: ${failed[*]:-none}"
echo "log: $LOG"
bash "$SCRIPTS/notify.sh" "PG OCR: full-width Greek" "Volumes ${vols[*]} done; failed: ${failed[*]:-none}" 2>/dev/null || true
