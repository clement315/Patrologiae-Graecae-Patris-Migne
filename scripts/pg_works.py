"""
Split a merged PG volume into its individual works and structure each of them.

    python pg_works.py --vol 94 --model .../best_0.9885.safetensors
    (normally:  bash pg_ocr.sh 94 works)

Steps
  1. Page order.  Some stretches of the main scan are out of order and contain re-scanned
     pages (PG 94: the Dialectica, PDF pp. 297-344).  The second scan is in the right
     order, so every page is placed by the leaf of the second scan it was matched to;
     two pages matched to the same leaf are the same page scanned twice (one is dropped).
  2. Coverage check.  Every leaf of the second scan that carries Greek text must be covered
     by a page of the volume; uncovered leaves are listed (a page missing from the main scan).
  3. Migne columns from the running heads of both scans, fitted in the corrected order.
  4. Each work (table WORKS) is structured according to its kind:
       books     books and numbered chapters (Expositio fidei)
       chapters  numbered chapters, one book (Dialectica)
       sections  titled sections, not numbered (De haeresibus, Contra Jacobitas, ...)
       orations  orations from the running heads, titled sections inside (De imaginibus)
       numbered  sections numbered in the text ('βʹ. Σκυθισμός') (De haeresibus, Contra Jacobitas)
       dialogue  speaker turns (MAN. / ORTH.) start new paragraphs (numbered_dialogue: also numbered)

Outputs: output/PG094/works/<work>/<work>.md, sections/NNN.txt, report.txt;
         output/PG094/works/works.tsv, coverage.txt
"""
import argparse
import collections
import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pg_structure as S  # noqa: E402

VERSION = "1.3"

WORKS = {
    94: [
        {"slug": "vita_joannis", "title": "Vita Joannis Damasceni (auctore Joanne Hierosolymitano)",
         "pages": [215, 256], "kind": "sections"},
        {"slug": "dialectica", "title": "Dialectica (Capita philosophica)",
         "pages": [264, 355], "kind": "chapters"},
        {"slug": "de_haeresibus", "title": "De haeresibus", "pages": [356, 407], "kind": "numbered"},
        {"slug": "expositio_fidei", "title": "Expositio fidei (Ekdosis akribes tes orthodoxou pisteos)",
         "pages": [412, 633], "kind": "books"},
        {"slug": "orationes_de_imaginibus", "title": "Orationes de imaginibus I-III",
         "pages": [634, 739], "kind": "orations", "run_key": "ORATIO"},
        {"slug": "de_recta_sententia", "title": "De recta sententia", "pages": [740, 745], "kind": "sections"},
        {"slug": "contra_jacobitas", "title": "Contra Jacobitas", "pages": [746, 780], "kind": "numbered"},
        {"slug": "contra_manichaeos", "title": "Dialogus contra Manichaeos", "pages": [781, 823],
         "kind": "numbered_dialogue", "speakers": {"ΜΑΝ.": r"Μ[ΑΛ][ΝΒΕ]|ΚΑΝ|ΜΝ", "ΟΡΘ.": r"ΟΡ?Θ|Ο[ΕΞ]Θ|ΟΘΟΟΖ|ΟΕ"}},
        {"slug": "disputatio_saraceni", "title": "Disputatio Christiani et Saraceni", "pages": [824, 831],
         "kind": "dialogue", "speakers": {}},
        {"slug": "de_draconibus", "title": "De draconibus et strygibus", "pages": [832, 834], "kind": "sections"},
    ],
    95: [
        # "col": first Migne column (table of contents, checked on the page images)
        # "cut": the work starts under its title in the middle of the page (the text above
        # belongs to the previous work or is a Latin preface); a page shared with the next
        # work is split at the same title
        {"slug": "de_sancta_trinitate", "title": "De sancta Trinitate", "col": 9, "pages": [10, 14], "kind": "sections"},
        {"slug": "de_hymno_trisagio", "title": "Epistola de hymno Trisagio (ad Jordanem archimandritam)",
         "pages": [16, 36], "kind": "sections"},
        {"slug": "de_sacris_jejuniis", "title": "De sacris jejuniis", "col": 63, "pages": [37, 44], "kind": "sections",
         "cut": True},
        {"slug": "de_octo_spiritibus_nequitiae", "title": "De octo spiritibus nequitiae", "col": 79, "pages": [45, 48],
         "kind": "sections"},
        {"slug": "de_virtutibus_et_vitiis", "title": "De virtutibus et vitiis", "pages": [48, 54],
         "kind": "sections", "cut": True},
        {"slug": "institutio_elementaris", "title": "Institutio elementaris ad dogmata", "col": 99, "pages": [55, 61],
         "kind": "chapters"},
        {"slug": "contra_acephalos", "title": "De natura composita contra Acephalos", "col": 111, "pages": [61, 68],
         "kind": "sections", "cut": True},
        {"slug": "de_duabus_voluntatibus", "title": "De duabus in Christo voluntatibus", "col": 127, "pages": [69, 98],
         "kind": "chapters", "cut": True},
        {"slug": "contra_nestorianos", "title": "Dissertatio adversus Nestorianorum haeresim", "col": 187, "pages": [99, 123],
         "kind": "numbered"},
        {"slug": "fragmenta", "title": "Fragmenta (e codice S. Hilarii)", "col": 226, "pages": [124, 130], "kind": "sections"},
        {"slug": "epistola_quid_est_homo", "title": "Epistola de hoc: Quid est homo?", "col": 243, "pages": [133, 134],
         "kind": "sections"},
        {"slug": "de_his_qui_in_fide_dormierunt", "title": "Oratio de his qui in fide dormierunt",
         "col": 250, "pages": [135, 152], "kind": "sections"},
        {"slug": "epistola_de_confessione", "title": "Epistola de confessione", "col": 283, "pages": [155, 164],
         "kind": "sections"},
        {"slug": "adversus_constantinum_cabalinum", "title": "De sacris imaginibus adversus Constantinum Cabalinum",
         "col": 310, "pages": [168, 185], "kind": "sections"},
        {"slug": "epistola_ad_theophilum", "title": "Epistola ad Theophilum imperatorem de sacris imaginibus",
         "col": 346, "pages": [186, 206], "kind": "sections"},
        {"slug": "de_azymis", "title": "De azymis", "col": 387, "pages": [207, 211], "kind": "sections"},
        {"slug": "de_corpore_et_sanguine", "title": "De corpore et sanguine Christi (ad Zachariam)",
         "col": 402, "pages": [214, 219], "kind": "sections", "cut": True},
        {"slug": "fragmenta_dogmatica", "title": "Fragmenta dogmatica", "pages": [220, 221], "kind": "sections"},
        # Expositio in Epistolas Pauli (cols. 441-1034), one work per epistle
        {"slug": "in_romanos", "title": "Expositio in Epistolam ad Romanos", "col": 441, "pages": [236, 302],
         "kind": "chapters", "cut": True},
        {"slug": "in_1_corinthios", "title": "Expositio in Epistolam I ad Corinthios", "pages": [302, 372],
         "kind": "chapters", "cut": True},
        {"slug": "in_2_corinthios", "title": "Expositio in Epistolam II ad Corinthios", "pages": [372, 407],
         "kind": "chapters", "cut": True},
        {"slug": "in_galatas", "title": "Expositio in Epistolam ad Galatas", "pages": [407, 430],
         "kind": "chapters", "cut": True},
        {"slug": "in_ephesios", "title": "Expositio in Epistolam ad Ephesios", "pages": [430, 447],
         "kind": "chapters", "cut": True},
        {"slug": "in_philippenses", "title": "Expositio in Epistolam ad Philippenses", "pages": [447, 461],
         "kind": "chapters", "cut": True},
        {"slug": "in_colossenses", "title": "Expositio in Epistolam ad Colossenses", "pages": [461, 471],
         "kind": "chapters", "cut": True},
        {"slug": "in_thessalonicenses", "title": "Expositio in Epistolas I-II ad Thessalonicenses",
         "pages": [472, 484], "kind": "chapters"},
        {"slug": "in_hebraeos", "title": "Expositio in Epistolam ad Hebraeos", "pages": [484, 513],
         "kind": "chapters", "cut": True},
        {"slug": "in_timotheum_titum_philemonem", "title": "Expositio in Epistolas I-II ad Timotheum, ad Titum, ad Philemonem",
         "pages": [513, 531], "kind": "chapters", "cut": True},
        {"slug": "sacra_parallela", "title": "Sacra Parallela (pars prima, PG 95)", "pages": [534, 825],
         "kind": "sections", "cut": True},
    ],
}


# Corrections of the main scan read from the running heads on the page images, where no
# independent second scan exists (PG 95: the IA "second scan" is the same digitisation).
#   order:   stretches of shuffled pages, each in its true sequence
#   cols:    left Migne column of single pages (anchors for the column count)
#   missing: Migne columns not contained in the scan (reported in coverage.txt)
#   same_scan: the second scan is the same digitisation (copies found by their text; column
#            numbers from sparse running heads of 2-4 digits, single changes confirmed by 3 of 4)
SCAN_FIXES = {
    95: {
        "same_scan": True,      # no independent second scan: sparse running heads, copies by text
        "order": [[490, 491, 501, 493, 494, 495, 492, 497, 498, 502],
                  [325, 326, 327, 330],
                  [655, 656, 657, 654]],         # p654 holds cols. 1265-6 (p658 is its copy)
        "cols": {326: 621, 490: 941, 501: 945, 492: 953, 497: 965, 502: 975,
                 620: 1211, 621: 1213, 622: 1215, 624: 1219, 626: 1223, 655: 1259, 654: 1265},
        "missing": ["617-620 (In I Cor.)", "955-964 (In Hebr.)", "969-974 (In Hebr.)",
                    "1209-1210 (Sacra Parallela)", "1213-1214 (Sacra Parallela; page photographed blank)",
                    "1217-1218 (Sacra Parallela)", "1221-1222 (Sacra Parallela)", "1257-1258 (Sacra Parallela)"],
    },
}


# ----------------------------------------------------------------- helpers
def gz_text(f):
    return gzip.decompress(f.read_bytes()).decode("utf-8", "replace")


def gz_json(f):
    return json.loads(gzip.decompress(f.read_bytes()))


def greek_words(text, n=7):
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("ς", "σ")
    return set(re.findall(r"[α-ω]{%d,}" % n, t))


HEAD_DIGITS = "3,4"


def head_numbers(text):
    """Column numbers in the running head (3-4 digits; 2-4 when the heads are sparse, so that
    the first columns of a volume (< 100) count too)."""
    return [int(x) for x in re.findall(r"(?<!\d)(\d{%s})(?!\d)" % HEAD_DIGITS, text[:160])]


def pdf_pages(args, best):
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        return len(fitz.open(str(args.pdf)))
    except Exception:
        return max(p for p in best if p < 10000)


def main_scan_ocr(args, best):
    """IA OCR (running heads) of the main scan; empty if the item has none.

    Some Google scans on the Internet Archive (PG 95: patrologicursus50migngoog) carry no
    OCR; the column numbers then come from the running heads of the second scan alone."""
    try:
        S.running_heads(args, max(best) + 20)      # downloads and caches the IA OCR
        mcache = args.root / "data" / "ia" / args.main_item
        return gz_text(mcache / "searchtext.txt.gz"), gz_json(mcache / "pageindex.json.gz")
    except Exception as e:
        print(f"[works] no IA OCR for the main scan {args.main_item} ({e}) - "
              f"column numbers from the second scan only", flush=True)
        return "", [[0, 0]] * pdf_pages(args, best)


def title_gap(rec, min_gap=300):
    """Where a new work starts on a page: (gap start, gap end) in page pixels, or None.

    Works that begin in mid-page start under a title that the layout model often does not
    see as a whole, but the Greek text always breaks there: the text above and below the
    title are separate Greek boxes.  The gap chosen is the first one (also the one above
    the first box) that contains a detected title; else the largest gap between Greek
    boxes, if it is at least `min_gap` px."""
    if not rec or not rec.get("greek"):
        return None
    boxes = sorted((g["box"] for g in rec["greek"]), key=lambda b: b[1])
    titles = [d["box"] for d in rec.get("detections", []) if d["cls"] == "MainText_Title" and d["conf"] >= 0.25]
    gaps, prev = [], 0
    for b in boxes:
        gaps.append((prev, b[1]))
        prev = max(prev, b[3])
    gaps.append((prev, rec["size"][1]))          # a title below the last box: nothing follows it
    for a, b in gaps:
        if any(a - 20 <= (t[1] + t[3]) / 2 <= b + 20 for t in titles):
            return (a, b)
    inner = [(b - a, a, b) for a, b in gaps[1:-1] if b - a >= min_gap]
    return (max(inner)[1], max(inner)[2]) if inner else None


# ----------------------------------------------------------------- 1: order and duplicates
def page_words(lines):
    return set(re.findall(r"\w{5,}", " ".join(l[3] for l in lines)))


def order_pages(pages, best, altmap, report, max_jump=20, dup_jaccard=0.7, known_dups=None, text_jaccard=None):
    """Sort pages by their leaf in the second scan; drop second copies of a page.

    A page's own leaf is trusted only if it lies within max_jump leaves of what its
    neighbours predict (a wrongly matched page keeps its PDF position)."""
    matched = sorted((p, v["leaf"] - p) for p, v in altmap.items() if v["how"] == "matched")

    def expected_leaf(p):
        near = sorted(matched, key=lambda x: abs(x[0] - p))[:9]
        if not near:
            return p
        offs = sorted(o for _, o in near)
        return p + offs[len(offs) // 2]

    keyleaf, dropped, distrusted = {}, dict(known_dups or {}), []
    for p in pages:
        v = altmap.get(p)
        exp = expected_leaf(p)
        if v and v["how"] == "extra":
            keyleaf[p] = v["leaf"]              # a leaf added from the second scan
        elif v and v["how"] == "matched" and abs(v["leaf"] - exp) <= max_jump:
            keyleaf[p] = v["leaf"]
        else:
            keyleaf[p] = exp
            if v and v["how"] == "matched":
                distrusted.append(p)
    # second copies: same leaf and (nearly) the same text
    by_leaf = collections.defaultdict(list)
    for p in pages:
        if p not in dropped:
            by_leaf[keyleaf[p]].append(p)
    for leaf, ps in by_leaf.items():
        ps = sorted(ps, key=lambda p: (-len(best.get(p, [])), p))
        for p in ps[1:]:
            a, b = page_words(best.get(ps[0], [])), page_words(best.get(p, []))
            # same leaf and same text, or an empty page (a copy the merge already removed)
            trusted = altmap.get(p, {}).get("how") == "matched" and p not in distrusted
            if a and ((b and len(a & b) / len(a | b) >= dup_jaccard) or (not b and trusted)):
                dropped[p] = ps[0]
    # copies the second scan cannot show (PG 95: the "second scan" is the same digitisation,
    # with the same re-scanned pages): a page whose text largely repeats a page 2-14 pages
    # before it is a second copy; the first occurrence stands in the right place
    kept = [p for p in pages if p not in dropped] if text_jaccard else []
    words = {p: page_words(best.get(p, [])) for p in kept}
    for i, p in enumerate(kept):
        if p in dropped or len(words[p]) < 40:
            continue
        for q in kept[i + 1:i + 15]:
            if q in dropped or len(words[q]) < 40 or not 2 <= q - p <= 14:
                continue
            if len(words[p] & words[q]) / len(words[p] | words[q]) >= text_jaccard:
                dropped[q] = p
    order = sorted((p for p in pages if p not in dropped), key=lambda p: (keyleaf[p], p))
    moved = sum(1 for a, b in zip(order, order[1:]) if b < a)
    report.append(f"page order: {moved} places where the scan order was corrected; "
                  f"{len(distrusted)} page(s) kept in PDF position (doubtful match: "
                  f"{', '.join('p%d' % p for p in distrusted) or '-'})")
    report.append(f"{len(dropped)} second copies of a page dropped: "
                  + (", ".join(f"p{a}=p{b}" for a, b in sorted(dropped.items())) or "-"))
    return order, dropped


# ----------------------------------------------------------------- 2: coverage
def coverage(best, altmap, alt_text, alt_index, lo, hi):
    """Greek leaves of the second scan whose words are not found on any page."""
    vocab = collections.Counter()
    page_words = {}
    for p, lines in best.items():
        w = greek_words(" ".join(l[3] for l in lines))
        page_words[p] = w
        vocab.update(w)
    inv = collections.defaultdict(set)
    for p, w in page_words.items():
        for x in w:
            inv[x].add(p)
    used = {v["leaf"] for v in altmap.values()}
    missing = []
    for leaf in range(lo, min(hi, len(alt_index) - 1) + 1):
        a = alt_index[leaf]
        real = [x for x in greek_words(alt_text[a[0]:a[1]]) if vocab[x] >= 2]
        if len(real) < 80:
            continue                        # Latin page, plate or little Greek
        hits = collections.Counter()
        for x in real:
            for p in inv[x]:
                hits[p] += 1
        p, n = hits.most_common(1)[0]
        if n / len(real) < 0.4:
            missing.append((leaf, leaf in used, len(real), round(n / len(real), 2)))
    return missing


# ----------------------------------------------------------------- 3: columns
def page_votes(p, k, main_text, main_index, alt_text, alt_index, altmap):
    """Votes for the offset c in 'left column = 2k + c' from the running heads of page p."""
    nums = []
    if p - 1 < len(main_index):
        a = main_index[p - 1]
        nums += head_numbers(main_text[a[0]:a[1]])
    v = altmap.get(p)
    if v and v["leaf"] < len(alt_index):
        a = alt_index[v["leaf"]]
        nums += head_numbers(alt_text[a[0]:a[1]])
    c = collections.Counter()
    for n in nums:
        for m in ([n, n + 600] if 100 <= n < 200 else [n]):   # ABBYY often reads the 7 of 7xx as 1
            c[m - 2 * k] += 1
            c[m - 1 - 2 * k] += 1
    return c


def fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap, window=5, confirm=3, reach=60,
                        anchors=None, exact=(), sparse=False):
    """Left Migne column of every page, from the running heads of both scans.

    The offset c in 'left column = 2k + c' (k = position in the corrected order) is
    constant while no page is missing; a page missing from the scan raises c by 2.
    Such steps are accepted when `confirm` following pages agree on the new value.
    Returns (columns, steps) with steps = [(page before, page after, pages missing)]."""
    own = []
    for k, p in enumerate(order):
        v = page_votes(p, k, main_text, main_index, alt_text, alt_index, altmap)
        best = v.most_common(2)
        # a page's own value counts if it is supported twice (left+right number, or both scans)
        own.append(best[0][0] if best and best[0][1] >= 2 and (len(best) == 1 or best[0][1] > best[1][1]) else None)
    # starting value: the first value that `confirm` successive readable heads agree on
    # (front matter and plates before the text have no usable running heads)
    seen = [x for x in own if x is not None]
    start = next((seen[i] for i in range(len(seen) - confirm + 1)
                  if all(x == seen[i] for x in seen[i:i + confirm])), seen[0] if seen else 0)
    cur, cols, steps = None, {}, []
    anchors = anchors or {}
    for k, p in enumerate(order):
        if cur is None:
            if sparse:
                cur = start
            else:
                vals = [x for x in own[k:k + 2 * window] if x is not None]
                cur = collections.Counter(vals).most_common(1)[0][0] if vals else 0
            if p in anchors:
                cur = anchors[p] - 2 * k
        elif p in anchors:
            # a work's first column from the volume's table of contents (the left or the
            # right column of its first page), or a page's left column read on the image
            c = min((anchors[p] - 2 * k, anchors[p] - 1 - 2 * k), key=lambda x: abs(x - cur)) \
                if p not in exact else anchors[p] - 2 * k
            if c != cur:
                steps.append((order[k - 1] if k else p, p, (c - cur) // 2))
                cur = c
        elif sparse and own[k] is not None and own[k] != cur and abs(own[k] - cur) <= 60:
            # `confirm` of the next confirm+1 readable heads (within `reach` pages; heads are
            # sparse when only one scan has OCR) must agree on the new value; misread
            # numbers far from the current value are ignored
            ahead = [x for x in own[k:k + reach] if x is not None and abs(x - cur) <= 60][:confirm + 1]
            if ahead.count(own[k]) >= confirm:
                steps.append((order[k - 1], p, (own[k] - cur) // 2))
                cur = own[k]
        elif not sparse and own[k] is not None and own[k] != cur:
            ahead = [x for x in own[k:k + confirm + 2] if x is not None][:confirm]
            if len(ahead) == confirm and all(x == own[k] for x in ahead):
                steps.append((order[k - 1], p, (own[k] - cur) // 2))
                cur = own[k]
        cols[p] = (2 * k + cur, 2 * k + cur + 1)
    return cols, steps


def gap_leaves(steps, altmap, used, is_copy):
    """Split column steps into real gaps (unused, non-duplicate leaves of the second scan
    lie between the two pages) and mere corrections of the column count."""
    gaps, corrections = [], []
    for before, after, n in steps:
        la, lb = altmap.get(before, {}).get("leaf"), altmap.get(after, {}).get("leaf")
        cand = [l for l in range(la + 1, lb) if l not in used and not is_copy(l)] \
            if n > 0 and la is not None and lb is not None and lb > la + 1 else []
        if cand:
            gaps.append((before, after, n, cand[:n]))
        else:
            corrections.append((before, after, n))
    return gaps, corrections


# ----------------------------------------------------------------- 4: works
def section_heads(order, items_of):
    """Title blocks on the Greek side as section headings (not numbered)."""
    heads = []
    for p in order:
        for k, it in enumerate(items_of[p]):
            if it["kind"] != "block":
                continue
            good = [t.strip() for t, c in it["lines"] if c >= 0.85 and len(t.strip()) >= 4]
            if good:                            # unreadable title blocks are left out
                heads.append({"page": p, "k": k, "text": " ".join(good)})
    return heads


NUM_RX = re.compile(r"^(?:⟦\?⟧\s*)?[«(\[]?\s*([α-ωϛϟ]{1,3})\s?[ʹ'΄´]\s?[.,·]\s*(.*)$")


def numbered_heads(order, items_of, report, max_step=4, gap_cost=0.6):
    """Sections numbered in the text ('βʹ. Σκυθισμός ...', 'ιʹ. Εἰ μερικὰς ...').

    Every line that starts with a Greek numeral is a candidate; the longest increasing
    chain with small steps is kept (dynamic programming), so OCR-garbled numerals and
    sub-lists that restart at 1 (e.g. the Messalian propositions) do not break it."""
    cand = []
    for p in order:
        for k, it in enumerate(items_of[p]):
            if it["kind"] != "line":
                continue
            m = NUM_RX.match(it["text"].strip())
            if m:
                v = S.greek_number(m.group(1))
                if v:
                    cand.append((p, k, v, m.group(2)))
    n = len(cand)
    if not n:
        return []
    score, back = [1.0] * n, [-1] * n
    for j in range(n):
        for i in range(max(0, j - 60), j):
            d = cand[j][2] - cand[i][2]
            if 1 <= d <= max_step and score[i] + 1 - gap_cost * (d - 1) > score[j]:
                score[j], back[j] = score[i] + 1 - gap_cost * (d - 1), i
    j = max(range(n), key=lambda x: score[x])
    chain = []
    while j >= 0:
        chain.append(cand[j])
        j = back[j]
    chain.reverse()
    heads, prev = [], 0
    for p, k, v, rest in chain:
        if v > prev + 1:
            report.append(f"number(s) {prev + 1}-{v - 1} not found before PDF p. {p}")
        name = re.split(r"(?<=[^\s]{3})[·.,;:]", rest, maxsplit=1)[0][:60].strip()
        heads.append({"page": p, "k": k, "text": f"{S.greek_ord(v)}. {name}".strip(), "no": v,
                      "keep_line": True})
        prev = v
    report.append(f"{len(heads)} numbered sections (1-{prev}) out of {n} numeral-like line starts")
    return heads


def oration_of_page(main_text, main_index, key, pages):
    """Oration number per page from running heads such as 'DE IMAGINIBUS ORATIO III.'"""
    raw = {}
    for p in pages:
        if p - 1 < len(main_index):
            a = main_index[p - 1]
            m = re.search(key + r"\s*([IVXLlT1H]{1,4})\b", main_text[a[0]:a[0] + 160])
            if m:
                v = S.roman_to_int(m.group(1).replace("H", "II"))
                if v:
                    raw[p] = v
    out, last = {}, 1
    for p in pages:
        near = [raw[q] for q in pages if abs(q - p) <= 4 and q in raw]
        if near:
            v = collections.Counter(near).most_common(1)[0][0]
            if v >= last:
                last = v
        out[p] = last
    return out


def build_sections(order, items_of, heads, cols, mark_conf, oration=None):
    hk = {(h["page"], h["k"]): h for h in heads}
    secs = []
    cur = {"head": None, "items": [], "page": order[0] if order else None, "col": None, "book": None}
    last_or = None
    for p in order:
        for k, it in enumerate(items_of[p]):
            col = cols.get(p, (None, None))[0 if it["side"] == "L" else 1]
            if oration and oration.get(p) != last_or:
                secs.append(cur)
                last_or = oration.get(p)
                cur = {"head": None, "items": [], "page": p, "col": col, "book": last_or}
            if (p, k) in hk:
                h = hk[(p, k)]
                secs.append(cur)
                cur = {"head": h["text"], "items": [], "page": p, "col": col,
                       "book": last_or, "no": h.get("no")}
                if not h.get("keep_line"):
                    continue
            if it["kind"] == "block":
                continue
            cur["items"].append({"kind": "line", "text": it["text"], "unsure": it["conf"] < mark_conf,
                                 "col": col, "page": p})
    secs.append(cur)
    return [s for s in secs if s["head"] is not None or s["items"]]


def speaker_breaks(paras, speakers):
    """Start a new paragraph at every speaker label (MAN. / ORTH.), normalised."""
    if not speakers:
        return paras
    alts = "|".join(f"(?P<s{i}>{pat})" for i, pat in enumerate(speakers.values()))
    names = list(speakers)
    rx = re.compile(r"(?:(?<=\s)|^)(?:" + alts + r")\.\s")
    out = []
    for para in paras:
        pieces, last = [], 0
        for m in rx.finditer(para):
            name = names[[i for i in range(len(names)) if m.group(f"s{i}")][0]]
            if m.start() > last:
                pieces.append(para[last:m.start()].strip())
            pieces.append(f"**{name}**")
            last = m.end()
        pieces.append(para[last:].strip())
        merged, buf = [], ""
        for x in pieces:
            if x.startswith("**") and x.endswith("**"):
                if buf:
                    merged.append(buf)
                buf = x + " "
            else:
                buf += x
        if buf.strip():
            merged.append(buf.strip())
        out += [m for m in merged if m]
    return out


def write_work(w, units, outdir, vol, mark, mode):
    d = outdir / w["slug"]
    (d / "sections").mkdir(parents=True, exist_ok=True)
    for f in (d / "sections").glob("*.txt"):
        f.unlink()
    md = [f"# {w['title']}", "",
          f"Migne, PG {vol}, PDF pp. {w['pages'][0]}-{w['pages'][1]}. [col. N] = start of Migne column N. "
          f"⟦?⟧ = uncertain line. Uncorrected OCR.", ""]
    rows = ["no\tbook\theading\tpdf_page\tmigne_col\twords"]
    last_book, n = None, 0
    for u in units:
        paras = S.paragraphs(u["items"], mark)
        paras = speaker_breaks(paras, w.get("speakers"))
        if u.get("book") and u["book"] != last_book:
            label = {"books": "Liber", "orations": "Oratio"}.get(mode, "Pars")
            md += [f"## {label} {u['book']}", ""]
            last_book = u["book"]
        head = u["head"] if isinstance(u["head"], str) else (" ".join(u["head"]) if u["head"] else None)
        cite = f"PG {vol}, {u['col']}" if u.get("col") else f"PDF p. {u['page']}"
        if head:
            n += 1
            md += [f"### {head}  ({cite})", ""]
        elif paras:
            md += [f"### [{'beginning' if n == 0 else 'continued'}]  ({cite})", ""]
        md += [p + "\n" for p in paras]
        words = sum(len(p.split()) for p in paras)
        no = u.get("no") or n
        rows.append(f"{no}\t{u.get('book') or ''}\t{head or ''}\t{u['page']}\t{u.get('col') or ''}\t{words}")
        if paras:
            (d / "sections" / f"{len(rows) - 1:03d}.txt").write_text(
                (head or "[untitled]") + f"\n({cite})\n\n" + "\n\n".join(paras) + "\n", encoding="utf-8")
    (d / f"{w['slug']}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (d / "sections.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows) - 1


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--text-tag", default="best")
    ap.add_argument("--works", type=Path, default=None, help="JSON list of works (default: built-in table)")
    ap.add_argument("--only", default=None, help="comma-separated work slugs")
    ap.add_argument("--main-item", default=None)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--mark-conf", type=float, default=0.80)
    ap.add_argument("--mark", default="⟦?⟧ ")
    ap.add_argument("--no-titles", action="store_true")
    args = ap.parse_args()
    tag = f"PG{args.vol:03d}"
    args.main_item = args.main_item or S.MAIN_ITEMS.get(args.vol)
    args.pdf = args.root / "data" / "pdf" / f"{tag}.pdf"
    works = json.loads(args.works.read_text()) if args.works else WORKS.get(args.vol)
    if not works:
        sys.exit(f"no table of works for PG {args.vol}: give --works")
    all_table = list(works)
    if args.only:
        keep = set(args.only.split(","))
        works = [w for w in works if w["slug"] in keep]
    print(f"pg_works.py version {VERSION}", flush=True)

    out = args.root / "output" / tag / args.text_tag
    best = S.load_best(out / f"{tag}_lines.tsv")
    base = {}
    rep = out / "merge_report.tsv"
    if rep.exists():
        for row in rep.read_text(encoding="utf-8").splitlines()[1:]:
            f = row.split("\t")
            base[int(f[0])] = f[1]
    runs = sorted(set(base.values())) or ["v4"]
    for p in best:
        base.setdefault(p, runs[0])
    layouts = {}
    for r in runs:
        lf = args.root / "work" / tag / r / "layout.jsonl"
        layouts[r] = {}
        if lf.exists():
            for l in lf.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    d = json.loads(l)
                    layouts[r][d["page"]] = d
    amf = args.root / "work" / tag / "v5" / "altmap.json"
    altmap = {int(k): v for k, v in json.loads(amf.read_text()).items() if not k.startswith("_")} \
        if amf.exists() else {}

    main_text, main_index = main_scan_ocr(args, best)
    acache = args.root / "data" / "alt" / tag
    alt_text, alt_index = gz_text(acache / "searchtext.txt.gz"), gz_json(acache / "pageindex.json.gz")

    report = []
    # the whole volume is ordered (also pages without Greek), so that column numbers
    # can be counted page by page; the works then take their pages from this order
    n_pdf = len(main_index)
    fixes = SCAN_FIXES.get(args.vol, {})
    same = bool(fixes.get("same_scan"))
    global HEAD_DIGITS
    HEAD_DIGITS = "2,4" if same else "3,4"
    known = {}
    # pages left out as copies: by the merge, or (one digitisation only) by one of the runs
    # for a page that has no text in the merged result either
    for r in [args.text_tag] + (runs if same else []):
        sf = args.root / "output" / tag / r / "summary.json"
        if sf.exists():
            for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
                a, b = d.split(" = ")
                a, b = int(a[1:]), int(b[1:])
                if r == args.text_tag or a not in best:
                    known.setdefault(a, b)
    extra = sorted(p for p in best if p > n_pdf)        # leaves added from the second scan
    order, dropped = order_pages(list(range(1, n_pdf + 1)) + extra, best, altmap, report, known_dups=known,
                                 text_jaccard=0.25 if same else None)
    for seq in fixes.get("order", []):
        seq = [p for p in seq if p in order]
        if seq:
            at = min(order.index(p) for p in seq)
            rest = [p for p in order if p not in seq]
            order = rest[:at] + seq + rest[at:]
            report.append(f"page order fixed from the running heads: {', '.join('p%d' % p for p in seq)}")
    anchors = {w["pages"][0]: w["col"] for w in all_table if w.get("col")}
    anchors.update(fixes.get("cols", {}))
    cols, steps = fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap, anchors=anchors,
                                      exact=set(fixes.get("cols", {})), sparse=same)
    vocab_pages = collections.defaultdict(set)
    for p, lines in best.items():
        for x in greek_words(" ".join(l[3] for l in lines)):
            vocab_pages[x].add(p)

    def is_copy(leaf):
        """True if most Greek words of this leaf are found together on one of our pages."""
        a = alt_index[leaf]
        w = [x for x in greek_words(alt_text[a[0]:a[1]]) if x in vocab_pages]
        if len(w) < 10:
            return True                     # hardly any Greek: not a missing Greek page
        hits = collections.Counter(p for x in w for p in vocab_pages[x])
        return hits.most_common(1)[0][1] / len(w) >= 0.4
    gaps, corrections = gap_leaves(steps, altmap, {v["leaf"] for v in altmap.values()}, is_copy)
    # a work runs from the position of its first page to the position of its last page in
    # the corrected order (a page misplaced in the scan goes with the work it belongs to)
    pos = {p: i for i, p in enumerate(order)}

    def position(p, last=False):
        cand = [q for q in pos if (q >= p if not last else q <= p)]
        q = min(cand) if not last else max(cand)
        return pos[q]
    work_pages = {}
    for w in works:
        a, b = position(w["pages"][0]), position(w["pages"][1], last=True)
        work_pages[w["slug"]] = [p for p in order[a:b + 1] if p in best]
    order = [p for p in order if p in best and any(p in v for v in work_pages.values())]
    leaves = [altmap[p]["leaf"] for p in order if p in altmap]
    missing = coverage({p: best[p] for p in order}, {p: altmap[p] for p in order if p in altmap},
                       alt_text, alt_index, min(leaves), max(leaves)) if leaves else []

    titles = {} if args.no_titles else S.ocr_titles(args, layouts, base, order)
    items_of = {p: S.page_items(p, best, layouts, base, titles) for p in order}
    ia_main = {i + 1: main_text[a[0]:a[1]] for i, a in enumerate(main_index)}
    ia_alt = {p: alt_text[alt_index[v["leaf"]][0]:alt_index[v["leaf"]][1]]
              for p, v in altmap.items() if v["leaf"] < len(alt_index)}

    wdir = out.parent / "works"
    wdir.mkdir(parents=True, exist_ok=True)
    summary = ["slug\ttitle\tpdf_pages\tmigne_cols\tunits\tlines"]
    all_works = all_table
    for w in works:
        wp = work_pages[w["slug"]]
        if not wp:
            report.append(f"{w['slug']}: no pages")
            continue
        wrep = []
        kind = w["kind"]
        # a work that starts under its title in mid-page, and a page shared with the next work
        items_w = dict(items_of)
        first, last = w["pages"]
        if w.get("cut") and first in items_w:
            g = title_gap(layouts.get(base.get(first), {}).get(first))
            if g:
                # the text below the title; title blocks inside the gap are section headings
                # of a work in sections, but not chapter headings
                lo = g[1] if kind in ("books", "chapters") else g[0]
                items_w[first] = [it for it in items_of[first] if it["y"] >= lo]
            elif len(layouts.get(base.get(first), {}).get(first, {}).get("greek", [])) > 1:
                wrep.append(f"p{first}: no break before the work's title found - whole page kept")
        i = next((j for j, x in enumerate(all_works) if x["slug"] == w["slug"]), None)
        nxt = all_works[i + 1] if i is not None and i + 1 < len(all_works) else None
        if nxt and nxt.get("cut") and nxt["pages"][0] == last and last in items_w:
            g = title_gap(layouts.get(base.get(last), {}).get(last))
            if g:
                items_w[last] = [it for it in items_of[last] if it["y"] < g[0]]
            else:
                wrep.append(f"p{last}: shared with the next work, no break found - whole page kept in both")
        items_of_all, items_of = items_of, items_w
        if kind in ("books", "chapters"):
            books = S.fit_books(S.running_heads(args, max(best) + 20), wp) if kind == "books" else {p: 1 for p in wp}
            heads = S.resolve_headings(wp, items_of, ia_main, ia_alt, wrep)
            S.number_headings(heads, books, wrep)
            units = S.build_chapters(wp, items_of, heads, cols, args.mark_conf)
            if kind == "chapters":
                for u in units:
                    u["book"] = None
        elif kind in ("numbered", "numbered_dialogue"):
            heads = numbered_heads(wp, items_of, wrep)
            units = build_sections(wp, items_of, heads, cols, args.mark_conf)
        else:
            heads = section_heads(wp, items_of)
            oration = oration_of_page(main_text, main_index, w.get("run_key", "ORATIO"), wp) \
                if kind == "orations" else None
            units = build_sections(wp, items_of, heads, cols, args.mark_conf, oration)
        n = write_work(w, units, wdir, args.vol, args.mark, kind)
        c0 = cols.get(wp[0], ("?",))[0]
        c1 = cols.get(wp[-1], ("?", "?"))[1]
        nlines = sum(len(best[p]) for p in wp)
        summary.append(f"{w['slug']}\t{w['title']}\t{w['pages'][0]}-{w['pages'][1]}\t{c0}-{c1}\t{n}\t{nlines}")
        (wdir / w["slug"] / "report.txt").write_text(
            f"{w['title']}\nPDF pp. {w['pages'][0]}-{w['pages'][1]}, Migne cols. {c0}-{c1}\n"
            f"{n} {'chapters' if kind in ('books', 'chapters') else 'sections'}\n\n" + "\n".join(wrep or ["-"]) + "\n",
            encoding="utf-8")
        print(f"[works] {w['slug']:26s} pp. {w['pages'][0]}-{w['pages'][1]}  cols. {c0}-{c1}  {n} units", flush=True)
        items_of = items_of_all

    (wdir / "works.tsv").write_text("\n".join(summary) + "\n", encoding="utf-8")
    cov = [f"pg_works.py {VERSION}", ""] + report + ["",
           "Gaps in the Migne column sequence (running heads):"]
    for before, after, n, leaves in gaps:
        cov.append(f"  between p{before} and p{after}: {n} page(s) missing in the main scan; "
                   f"second-scan leaves to add: {','.join(map(str, leaves))}")
    if not gaps:
        cov.append("  none")
    if corrections:
        cov.append("  (column count re-synchronised at: "
                   + ", ".join(f"p{a}/p{b} ({n:+d})" for a, b, n in corrections) + ";"
                   + " + = pages missing in the scan, or a page without running head; - = an extra"
                   " page, e.g. a plate or table)")
    if fixes.get("missing"):
        cov += ["", "Migne columns missing in the scan (checked on the page images; another copy of",
                f"PG {args.vol} is needed for them):"] + [f"  cols. {m}" for m in fixes["missing"]]
    add = [l for _, _, _, leaves in gaps for l in leaves]
    if add:
        cov += ["", "To add them, then merge and run this step again:",
                f"  SOURCE=alt RUN=v5 bash pg_ocr.sh {args.vol} leaf:" + ",".join(map(str, add)),
                f"  bash pg_ocr.sh {args.vol} merge v4,v5"]
    cov += ["", "Greek leaves of the second scan whose words are found on no page (check):"]
    cov += [f"  alt leaf {l} (matched to a page: {u}; {n} Greek words; best overlap {o})"
            for l, u, n, o in missing] or ["  none"]
    (wdir / "coverage.txt").write_text("\n".join(cov) + "\n", encoding="utf-8")
    print("\n".join(cov))
    print(f"-> {wdir}")


if __name__ == "__main__":
    main()
