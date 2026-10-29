#!/usr/bin/env bash
# =====================================================================
#  PG OCR - one whole volume, start to finish        (run_pg_volume.sh)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/run_pg_volume.sh 95
#
#  Stages (each can be resumed; finished pages are never redone):
#    check   GPU free, disk space, model files
#    pdf     download the main scan, show its title page, check the volume number
#    v4      recognise the main scan (all pages)
#    v5      recognise the second scan (IA "PatrologiaGraeca") on the Greek pages
#    merge   combine v4 and v5 word by word -> output/PGxxx/best/
#    report  short summary -> output/PGxxx/run_report.txt
#
#  Options:
#    --from STAGE       start at this stage (e.g. --from merge)
#    --pages A-B|all    pages of the main scan for v4 (default all)
#    --alt-pages A-B    pages for v5 (default: first..last page with Greek text in v4)
#    --pdf-url URL      main scan to download (default: known address for the volume)
#    --yes              do not stop when the title-page check is doubtful
#
#  After a crash (e.g. WSL out of memory) just run the same command again.
# =====================================================================
set -euo pipefail

ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
SCRIPTS="$ROOT/scripts"
STAGES=(check pdf v4 v5 merge report)

VOL=""; FROM="check"; PAGES="all"; ALT_PAGES=""; PDF_URL_ARG=""; YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --from)      FROM="$2"; shift 2 ;;
        --pages)     PAGES="$2"; shift 2 ;;
        --alt-pages) ALT_PAGES="$2"; shift 2 ;;
        --pdf-url)   PDF_URL_ARG="$2"; shift 2 ;;
        --yes)       YES=1; shift ;;
        -h|--help)   sed -n 2,25p "$0"; exit 0 ;;
        *)           if [ -z "$VOL" ]; then VOL="$1"; shift; else echo "unknown argument: $1" >&2; exit 2; fi ;;
    esac
done
[ -n "$VOL" ] || { echo "usage: bash run_pg_volume.sh <volume> [--from STAGE] [--pages A-B] [--alt-pages A-B] [--pdf-url URL]" >&2; exit 2; }
[[ "$VOL" =~ ^[0-9]+$ ]] || { echo "volume must be a number, e.g. 95" >&2; exit 2; }
printf '%s\n' "${STAGES[@]}" | grep -qx "$FROM" || { echo "--from must be one of: ${STAGES[*]}" >&2; exit 2; }

TAG="$(printf 'PG%03d' "$VOL")"
PDF="$ROOT/data/pdf/$TAG.pdf"
OUT="$ROOT/output/$TAG"
mkdir -p "$ROOT/work/$TAG" "$OUT"
LOG="$ROOT/work/$TAG/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
export PATH="$HOME/.local/bin:$PATH:/usr/lib/wsl/lib"
export PYTHONUNBUFFERED=1
# shellcheck disable=SC1091
source "$HOME/kraken-env/bin/activate"

ts()   { date '+%Y-%m-%d %H:%M:%S'; }
step() { printf '\n\033[1;36m=== [%s] %s ===\033[0m\n' "$(ts)" "$*"; }
ok()   { printf '\033[1;32m[%s] %s\033[0m\n' "$(ts)" "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
run_stage() {   # true if this stage is at or after --from
    local s seen=0
    for s in "${STAGES[@]}"; do
        [ "$s" = "$FROM" ] && seen=1
        [ "$s" = "$1" ] && { [ $seen -eq 1 ]; return; }
    done
    return 1
}

echo "PG OCR volume run: $TAG   from stage: $FROM   log: $LOG"

# ------------------------------------------------------------------ check
if run_stage check; then
    step "check"
    if pgrep -af 'pg_ocr_volume.py' >/dev/null 2>&1; then
        pgrep -af 'pg_ocr_volume.py' || true
        die "another OCR run is still going - only one at a time (GPU memory, WSL memory)"
    fi
    if pgrep -af 'ketos .* train' >/dev/null 2>&1; then
        die "a model training is running - wait until it has finished"
    fi
    free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
    echo "free space on $(df --output=target "$ROOT" | tail -1): ${free_gb} GB"
    [ "$free_gb" -lt 20 ] && warn "less than 20 GB free - a whole volume needs about 10-15 GB of work files"
    model=$(ls -1t "$ROOT"/models/rec/run_*/best_*.safetensors 2>/dev/null | grep -v '_failed' | head -n1 || true)
    [ -n "$model" ] || die "no recognition model in $ROOT/models/rec/run_*/"
    echo "recognition model: $model"
    [ -f "$ROOT/models/REG-YOLOv12s.pt" ] || die "layout model $ROOT/models/REG-YOLOv12s.pt missing"
    for f in pg_ocr.sh pg_ocr_volume.py pg_merge.py; do
        [ -f "$SCRIPTS/$f" ] || die "$SCRIPTS/$f missing"
    done
    nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null \
        || warn "nvidia-smi not available - the OCR will be slow if the GPU is not seen"
    ok "checks passed"
fi

# ------------------------------------------------------------------ pdf
if run_stage pdf; then
    step "pdf  (main scan)"
    if [ ! -s "$PDF" ]; then
        url="$PDF_URL_ARG"
        if [ -z "$url" ]; then
            # the known addresses are listed in pg_ocr.sh (function default_url)
            url="$(grep -E "^ *$VOL\) echo" "$SCRIPTS/pg_ocr.sh" | sed -E 's/.*echo "([^"]+)".*/\1/' | head -n1)"
        fi
        [ -n "$url" ] || die "no download address known for PG $VOL.
  Find the volume on archive.org (search: Patrologiae cursus completus series graeca $VOL),
  then run:  bash $0 $VOL --pdf-url https://archive.org/download/<id>/<id>.pdf"
        echo "downloading $url"
        mkdir -p "$(dirname "$PDF")"
        curl -L --fail --retry 3 -C - -o "$PDF.part" "$url"
        mv "$PDF.part" "$PDF"
    fi
    ls -lh "$PDF" | awk '{print "PDF:", $NF, $5}'
    set +e
    python - "$PDF" "$VOL" <<'PY'
import sys, re
try:
    import pymupdf as fitz
except ImportError:
    import fitz
pdf, vol = sys.argv[1], int(sys.argv[2])
def roman(n):
    out = ""
    for v, s in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s; n -= v
    return out
doc = fitz.open(pdf)
print(f"pages in PDF: {doc.page_count}")
R = roman(vol)
hits, others = [], set()
for i in range(min(15, doc.page_count)):
    for line in doc[i].get_text().splitlines():
        L = line.strip()
        if re.search(r"\bTOM(US|\.)", L, re.I) or re.search(r"\bX[CL][IVX]*\b", L):
            print(f"  p{i + 1}: {L[:100]}")
        if re.search(rf"\b{R}\b", L.upper()):
            hits.append(i + 1)
        for m in re.findall(r"\bTOMUS\s+([CXLVI]+)\b", L.upper()):
            others.add(m)
chars = sum(len(doc[i].get_text().strip()) for i in range(1, min(15, doc.page_count)))
if chars < 200:
    print("this scan has no text layer on its first pages (usual for Google scans) - the volume number cannot be checked automatically")
    sys.exit(4)
print(f"volume {vol} = TOMUS {R}: found on page(s) {sorted(set(hits)) or 'none'}")
wrong = sorted(o for o in others if o != R)
if wrong:
    print(f"other volume numbers on the title pages: {wrong}")
sys.exit(0 if hits and not wrong else 3)
PY
    rc=$?
    set -e
    if [ $rc -ne 0 ]; then
        if [ $YES -eq 1 ]; then
            warn "title-page check is doubtful (the text layer of the scan may be poor) - continuing because of --yes"
        else
            [ $rc -eq 4 ] && die "open $PDF and look at the title page (usually PDF page 5-10, 'PATROLOGIAE GRAECAE TOMUS ...').
  If it is volume $VOL, continue with:
    bash $0 $VOL --from pdf --yes"
            die "could not confirm on the title pages that this PDF is volume $VOL.
  Look at the lines above (or open $PDF). If it is the right volume, run again with --yes:
    bash $0 $VOL --from pdf --yes
  If it is the wrong volume, delete $PDF and give the right one with --pdf-url."
        fi
    else
        ok "PDF is volume $VOL"
    fi
fi

# ------------------------------------------------------------------ v4
if run_stage v4; then
    step "v4  (main scan, pages $PAGES)"
    RUN=v4 SOURCE=pdf bash "$SCRIPTS/pg_ocr.sh" "$VOL" "$PAGES"
    [ -s "$OUT/v4/${TAG}_lines.tsv" ] || die "v4 produced no text ($OUT/v4/${TAG}_lines.tsv)"
    ok "v4 finished"
fi

# ------------------------------------------------------------------ v5
ALT_OK=1
if run_stage v5; then
    step "v5  (second scan)"
    if [ -z "$ALT_PAGES" ]; then
        ALT_PAGES="$(python - "$OUT/v4/${TAG}_lines.tsv" <<'PY'
import sys, collections
n, c = collections.Counter(), collections.defaultdict(list)
for row in open(sys.argv[1], encoding="utf-8").read().splitlines()[1:]:
    f = row.split("\t")
    if len(f) >= 5 and f[0].isdigit() and int(f[0]) < 10000:
        n[int(f[0])] += 1
        c[int(f[0])].append(float(f[3]))
# pages with a real Greek text column: at least 15 lines, mean confidence >= 0.93
good = sorted(p for p in n if n[p] >= 15 and sum(c[p]) / len(c[p]) >= 0.93)
# blocks of such pages (gaps of up to 12 pages: plates, Latin prefaces, blanks); a
# volume can hold several works separated by a long Latin text, so every block of at
# least 10 pages counts, and the range runs from the first to the last of them
blocks, cur = [], []
for p in good:
    if cur and p - cur[-1] > 12:
        blocks.append(cur); cur = []
    cur.append(p)
if cur:
    blocks.append(cur)
big = [b for b in blocks if len(b) >= 10] or sorted(blocks, key=len)[-1:]
for b in big:
    print(f"  block of Greek pages {b[0]}-{b[-1]} ({len(b)} pages)", file=sys.stderr)
print(f"{max(1, big[0][0] - 2)}-{big[-1][-1] + 3}" if big else "")
PY
)"
        [ -n "$ALT_PAGES" ] || die "could not find pages with Greek text in v4 - give --alt-pages A-B"
        echo "Greek text in v4 runs over pages $ALT_PAGES"
    fi
    set +e
    SOURCE=alt RUN=v5 bash "$SCRIPTS/pg_ocr.sh" "$VOL" "$ALT_PAGES"
    rc=$?
    set -e
    if [ $rc -ne 0 ] || [ ! -s "$OUT/v5/${TAG}_lines.tsv" ]; then
        ALT_OK=0
        warn "the second scan could not be read for $TAG (exit $rc) - perhaps the IA item has no volume $VOL.
  The main-scan text in $OUT/v4/ is still complete; v5 and merge are skipped.
  To try again later:  bash $0 $VOL --from v5"
    else
        ok "v5 finished"
    fi
fi

# ------------------------------------------------------------------ merge
if run_stage merge; then
    if [ $ALT_OK -eq 1 ] && [ -s "$OUT/v5/${TAG}_lines.tsv" ]; then
        step "merge  (v4 + v5)"
        bash "$SCRIPTS/pg_ocr.sh" "$VOL" merge v4,v5
        ok "merged text in $OUT/best/"
    else
        warn "merge skipped (no v5 result)"
    fi
fi

# ------------------------------------------------------------------ report
if run_stage report; then
    step "report"
    python - "$OUT" "$TAG" <<'PY' | tee "$OUT/run_report.txt"
import json, sys
from pathlib import Path
out, tag = Path(sys.argv[1]), sys.argv[2]
rows = []
for run in ("v4", "v5", "best"):
    f = out / run / "summary.json"
    if not f.exists():
        continue
    d = json.loads(f.read_text())
    rows.append((run, d))
print(f"{tag} - OCR summary")
print(f"{'run':6} {'pages':>6} {'lines':>7} {'mean conf':>9} {'<0.80':>6}  pages to check / duplicates")
for run, d in rows:
    pages = d.get("pages", d.get("pages_processed", "?"))
    low = d.get("lines_below_0.80", d.get("lines_marked_uncertain", "?"))
    check = ", ".join(d.get("pages_to_check_low_conf", [])[:8])
    dups = ", ".join(d.get("duplicate_pages_skipped", [])[:8])
    print(f"{run:6} {pages!s:>6} {d.get('lines', '?')!s:>7} {d.get('mean_line_conf', '?')!s:>9} {low!s:>6}  {check}")
    if dups:
        print(f"{'':6} duplicates: {dups}{' ...' if len(d.get('duplicate_pages_skipped', [])) > 8 else ''}")
    if run == "best" and d.get("pages_read_differently_by_the_runs"):
        print(f"{'':6} pages read differently by v4/v5: {d['pages_read_differently_by_the_runs']}")
best = out / "best" / f"{tag}_reading.txt"
main = best if best.exists() else out / "v4" / f"{tag}_reading.txt"
print(f"\nreading text: {main}")
PY
    echo
    echo "Next: send output/$TAG/best/ (summary.json, merge_report.tsv) and the volume's table of contents"
    echo "      to set up the works table, then:  bash $SCRIPTS/pg_ocr.sh $VOL works"
    bash "$SCRIPTS/notify.sh" "PG OCR: $TAG complete" "All stages finished. Report: output/$TAG/run_report.txt" 2>/dev/null || true
    ok "done - log: $LOG"
fi
