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

VERSION = "1.1"

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
    ]
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


def head_numbers(text):
    return [int(x) for x in re.findall(r"(?<!\d)(\d{3,4})(?!\d)", text[:160])]


# ----------------------------------------------------------------- 1: order and duplicates
def page_words(lines):
    return set(re.findall(r"\w{5,}", " ".join(l[3] for l in lines)))


def order_pages(pages, best, altmap, report, max_jump=20, dup_jaccard=0.7, known_dups=None):
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


def fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap, window=5, confirm=3):
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
    cur, cols, steps = None, {}, []
    for k, p in enumerate(order):
        if cur is None:
            vals = [x for x in own[k:k + 2 * window] if x is not None]
            cur = collections.Counter(vals).most_common(1)[0][0] if vals else 0
        elif own[k] is not None and own[k] != cur:
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

    S.running_heads(args, max(best) + 20)          # makes sure the IA OCR of the main scan is cached
    mcache = args.root / "data" / "ia" / args.main_item
    main_text, main_index = gz_text(mcache / "searchtext.txt.gz"), gz_json(mcache / "pageindex.json.gz")
    acache = args.root / "data" / "alt" / tag
    alt_text, alt_index = gz_text(acache / "searchtext.txt.gz"), gz_json(acache / "pageindex.json.gz")

    report = []
    # the whole volume is ordered (also pages without Greek), so that column numbers
    # can be counted page by page; the works then take their pages from this order
    n_pdf = len(main_index)
    known = {}
    for r in [args.text_tag]:               # pages the merge itself left out as copies
        sf = args.root / "output" / tag / r / "summary.json"
        if sf.exists():
            for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
                a, b = d.split(" = ")
                known[int(a[1:])] = int(b[1:])
    extra = sorted(p for p in best if p > n_pdf)        # leaves added from the second scan
    order, dropped = order_pages(list(range(1, n_pdf + 1)) + extra, best, altmap, report, known_dups=known)
    cols, steps = fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap)
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
    for w in works:
        wp = work_pages[w["slug"]]
        if not wp:
            report.append(f"{w['slug']}: no pages")
            continue
        wrep = []
        kind = w["kind"]
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

    (wdir / "works.tsv").write_text("\n".join(summary) + "\n", encoding="utf-8")
    cov = [f"pg_works.py {VERSION}", ""] + report + ["",
           "Gaps in the Migne column sequence (running heads):"]
    for before, after, n, leaves in gaps:
        cov.append(f"  between p{before} and p{after}: {n} page(s) missing in the main scan; "
                   f"second-scan leaves to add: {','.join(map(str, leaves))}")
    if not gaps:
        cov.append("  none")
    if corrections:
        cov.append("  (column count re-synchronised without missing text at: "
                   + ", ".join(f"p{a}/p{b} ({n:+d})" for a, b, n in corrections) + ")")
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
