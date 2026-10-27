#!/usr/bin/env bash
# =====================================================================
#  PG OCR - recognise one Patrologia Graeca volume        (pg_ocr.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/pg_ocr.sh 94 500-511     test on 12 pages
#    bash /mnt/e/PG_OCR/scripts/pg_ocr.sh 94 all         whole volume
#
#  Second scan (Internet Archive item "PatrologiaGraeca": another library copy,
#  greyscale; readable where our PDF is over-inked):
#    SOURCE=alt RUN=v5 bash pg_ocr.sh 94 470-500      needs the normal run (v4) first
#    bash pg_ocr.sh 94 merge v4,v5                    best version of every page
#                                                     -> output/PG094/best/
#    bash pg_ocr.sh 94 works                          split into works, page check, chapters
#                                                     -> output/PG094/works/
#    SOURCE=alt RUN=v5 bash pg_ocr.sh 94 leaf:487,488 add leaves missing from the main scan
#    bash pg_ocr.sh 94 structure                      (older: one work only)
#  Optional:
#    RUN=v6 ...      name of the result folder (default v4)
#    STAGES=text ... only rebuild the text files from finished OCR (seconds)
#    MODEL=/mnt/e/PG_OCR/models/rec/run_xxx/best_0.9885.safetensors bash pg_ocr.sh 94 all
#    PDF_URL=https://archive.org/download/<id>/<id>.pdf bash pg_ocr.sh 95 1-20
#
#  First run installs two extra packages (ultralytics, PyMuPDF) into the
#  kraken environment and downloads the volume PDF into data/pdf/.
#  Re-running continues where it stopped.
# =====================================================================
set -euo pipefail

main() {
    export PATH="$HOME/.local/bin:$PATH:/usr/lib/wsl/lib"
    ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
    VOL="${1:-}"; PAGES="${2:-}"
    [ -n "$VOL" ] && [ -n "$PAGES" ] || die "usage: bash pg_ocr.sh <volume> <pages|all>   e.g.  bash pg_ocr.sh 94 500-511"
    TAG="$(printf 'PG%03d' "$VOL")"
    RUN="${RUN:-v4}"
    SOURCE="${SOURCE:-pdf}"
    PDF="$ROOT/data/pdf/$TAG.pdf"
    START_TS=$(date +%s)

    # shellcheck disable=SC1091
    source "$HOME/kraken-env/bin/activate"

    if [ "$PAGES" = "merge" ]; then            # combine finished runs, no GPU needed
        python "$ROOT/scripts/pg_merge.py" --vol "$VOL" --tags "${3:-v4,v5}" --root "$ROOT"
        echo "reading text: $ROOT/output/$TAG/best/${TAG}_reading.txt"
        echo "which run each page came from: $ROOT/output/$TAG/best/merge_report.tsv"
        return 0
    fi

    if [ "$PAGES" = "works" ]; then            # split into works, check page order/gaps, structure each
        MODEL="${MODEL:-$(ls -1t "$ROOT"/models/rec/run_*/best_*.safetensors 2>/dev/null | grep -v '_failed' | head -n1 || true)}"
        PYTHONUNBUFFERED=1 python "$ROOT/scripts/pg_works.py" --vol "$VOL" --root "$ROOT" --model "$MODEL" \
            --text-tag "${3:-best}" ${ONLY:+--only "$ONLY"}
        echo "works:          $ROOT/output/$TAG/works/   (one folder per work)"
        echo "page check:     $ROOT/output/$TAG/works/coverage.txt"
        return 0
    fi

    if [ "$PAGES" = "structure" ]; then        # chapters, books, Migne columns -> output/PGxxx/structured
        MODEL="${MODEL:-$(ls -1t "$ROOT"/models/rec/run_*/best_*.safetensors 2>/dev/null | grep -v '_failed' | head -n1 || true)}"
        PYTHONUNBUFFERED=1 python "$ROOT/scripts/pg_structure.py" --vol "$VOL" --root "$ROOT" --model "$MODEL" \
            --text-tag "${3:-best}" ${WORK_TITLE:+--work-title "$WORK_TITLE"}
        echo "structured text: $ROOT/output/$TAG/structured/${TAG}_structured.md"
        echo "chapter list:    $ROOT/output/$TAG/structured/${TAG}_chapters.tsv"
        echo "check report:    $ROOT/output/$TAG/structured/structure_report.txt"
        return 0
    fi

    trap 'notify_end $?' EXIT      # Windows notification when the run ends (NOTIFY=0 to switch off)
    export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

    step "1/4  Checks and extra packages"
    if pgrep -af 'kraken-env/bin/ketos .* train' >/dev/null 2>&1; then
        die "a training is running - wait until it has finished (both need the GPU)"
    fi
    if ! python -c "import ultralytics, fitz" >/dev/null 2>&1; then
        echo "installing ultralytics + PyMuPDF into the kraken environment ..."
        uv pip install --python "$HOME/kraken-env/bin/python" ultralytics pymupdf
    fi
    if ! python -c "import cv2" >/dev/null 2>&1; then
        echo "OpenCV needs two system libraries (asks for your Ubuntu password once):"
        sudo apt-get install -y libgl1 libglib2.0-0
    fi
    python -c "import ultralytics, pymupdf, cv2; print('ultralytics', ultralytics.__version__, '| PyMuPDF', pymupdf.VersionBind)"

    MODEL="${MODEL:-$(ls -1t "$ROOT"/models/rec/run_*/best_*.safetensors 2>/dev/null | grep -v '_failed' | head -n1 || true)}"
    [ -n "$MODEL" ] && [ -f "$MODEL" ] || die "no recognition model found - train one first (pg_train.sh)"
    echo "recognition model: $MODEL"
    [ -f "$ROOT/models/REG-YOLOv12s.pt" ] || die "layout model $ROOT/models/REG-YOLOv12s.pt missing"
    echo "image source: $SOURCE   result folder: $RUN"
    if [ "$SOURCE" = "alt" ] && [ "$RUN" = "v4" ]; then
        die "SOURCE=alt needs its own result folder, e.g.  SOURCE=alt RUN=v5 bash pg_ocr.sh $VOL $PAGES"
    fi

    step "2/4  Volume PDF"
    mkdir -p "$ROOT/data/pdf"
    if [ ! -s "$PDF" ]; then
        local url="${PDF_URL:-$(default_url "$VOL")}"
        [ -n "$url" ] || die "no download address known for PG $VOL - set PDF_URL=... or put the file at $PDF"
        echo "downloading $url"
        curl -L --fail --retry 3 -o "$PDF.part" "$url"
        mv "$PDF.part" "$PDF"
    fi
    ls -lh "$PDF" | awk '{print "PDF:", $NF, $5}'

    step "3/4  Layout -> line segmentation -> recognition  ($TAG, pages $PAGES)"
    mkdir -p "$ROOT/work/$TAG"
    local log="$ROOT/work/$TAG/ocr_${RUN}_$(date +%Y%m%d_%H%M%S).log"
    PYTHONUNBUFFERED=1 python "$ROOT/scripts/pg_ocr_volume.py" --vol "$VOL" --pdf "$PDF" --pages "$PAGES" \
        --root "$ROOT" --model "$MODEL" --tag "$RUN" --source "$SOURCE" --stages "${STAGES:-layout,ocr,text}" 2>&1 | tee "$log"

    step "4/4  Done"
    echo "text:      $ROOT/output/$TAG/$RUN/${TAG}_text.txt"
    echo "reading:   $ROOT/output/$TAG/$RUN/${TAG}_reading.txt   (⟦?⟧ = uncertain line)"
    echo "set aside: $ROOT/output/$TAG/$RUN/${TAG}_suspect.tsv   (very uncertain lines, usually Latin)"
    echo "previews:  $ROOT/work/$TAG/$RUN/previews/   (green = Greek read, orange = rejected Latin)"
    echo "log:       $log"
}

# archive.org scans (Google/Harvard digitisations, public domain); add more as needed
default_url() {
    case "$1" in
        94) echo "https://archive.org/download/patrologicursus53migngoog/patrologicursus53migngoog.pdf" ;;
        95) echo "https://archive.org/download/patrologicursus50migngoog/patrologicursus50migngoog.pdf" ;;
        *)  echo "" ;;
    esac
}

# desktop notification at the end of a run (success, error or Ctrl+C)
notify_end() {
    set +e                               # the notification itself must never fail
    local rc="$1" mins summary lines
    [ "${NOTIFY:-1}" = "0" ] && return 0
    mins=$(( ( $(date +%s) - ${START_TS:-$(date +%s)} ) / 60 ))
    [ "$mins" -lt 1 ] && [ "$rc" -ne 0 ] && return 0      # instant usage errors: no popup
    summary="$ROOT/output/$TAG/$RUN/summary.json"
    if [ "$rc" -eq 0 ]; then
        lines="$(python -c "import json;d=json.load(open('$summary'));print(d['lines'],'lines,',d['lines_set_aside_low_conf'],'set aside')" 2>/dev/null || echo '')"
        bash "$ROOT/scripts/notify.sh" "PG OCR finished: $TAG $RUN" "Pages $PAGES done in ${mins} min. $lines"
    elif [ "$rc" -eq 130 ] || [ "$rc" -eq 143 ]; then
        bash "$ROOT/scripts/notify.sh" "PG OCR paused: $TAG $RUN" "Stopped after ${mins} min. Finished pages are kept - run the same command to continue."
    else
        bash "$ROOT/scripts/notify.sh" "PG OCR stopped: $TAG $RUN" "Pages $PAGES ended with an error (exit $rc) after ${mins} min - see the log."
    fi
}

step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

main "$@"; exit $?
