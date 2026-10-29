"""
Turn the merged OCR text of a PG volume into a structured, translation-friendly text:
chapter headings, book numbers, Migne column numbers, paragraphs.

    python pg_structure.py --vol 94 --model .../best_0.9885.safetensors
    (normally:  bash pg_ocr.sh 94 structure)

What it does
  1. Migne column numbers: read from the running heads in the Internet Archive OCR of
     the main scan (e.g. "1005  DE FIDE ORTHODOXA LIB. III.  1006"), fitted to one
     consistent sequence (single OCR errors and duplicate scans do not matter).
  2. Book numbers: "LIB. III." in the same running heads (smoothed).
  3. Chapter headings: the layout model marks titles (MainText_Title).  The Greek ones
     (e.g. "ΚΕΦΑΛ. ΙΔʹ [ΚΗʹ]. / Περὶ λύπης.") are cut out of the page image of the run
     the page text came from and recognised with our kraken model.  Chapter numbers are
     read from the Greek numerals and checked against the expected sequence.
  4. Text: lines in reading order, hyphens joined across lines, columns and pages,
     paragraphs from short final lines, [col. 1006] markers where a Migne column starts.

Outputs (output/PG094/structured/):
  PG094_structured.md      whole work: books, chapters, paragraphs, column markers
  PG094_chapters.tsv       chapter list: no., book, title, PDF page, Migne column, checks
  chapters/ch028.txt       one file per chapter (convenient for translating)
  structure_report.txt     what was inferred or looks wrong
"""
import argparse
import collections
import gzip
import json
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "2.1 (headings checked against the IA OCR of both scans; unread subject lines at a column top)"
IA = "https://archive.org/download"
MAIN_ITEMS = {94: "patrologicursus53migngoog", 95: "patrologicursus50migngoog"}       # IA item of data/pdf/PGxxx.pdf
GREEK_NUM = {"Α": 1, "Β": 2, "Γ": 3, "Δ": 4, "Ε": 5, "Ϛ": 6, "Ϝ": 6, "Ζ": 7, "Η": 8, "Θ": 9,
             "Ι": 10, "Κ": 20, "Λ": 30, "Μ": 40, "Ν": 50, "Ξ": 60, "Ο": 70, "Π": 80, "Ϙ": 90, "Ϟ": 90,
             "Ρ": 100}
LATIN_LOOKALIKE = str.maketrans("ABEZHIKMNOPTXY", "ΑΒΕΖΗΙΚΜΝΟΡΤΧΥ")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
GREEK_ORD = {1: "Αʹ", 2: "Βʹ", 3: "Γʹ", 4: "Δʹ", 5: "Εʹ", 6: "Ϛʹ", 7: "Ζʹ", 8: "Ηʹ", 9: "Θʹ", 10: "Ιʹ"}


# ----------------------------------------------------------------- helpers
def plain(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def greek_number(token):
    """'ΙΔʹ' -> 14, 'ΚΗ' -> 28, 'ΣΤ' -> 6; None if not a numeral."""
    t = plain(token).upper().translate(LATIN_LOOKALIKE)
    t = re.sub(r"[^Α-ΩϚϜϘ]", "", t).replace("ΣΤ", "Ϛ").replace("Σ", "Ϛ")
    if not t or any(c not in GREEK_NUM for c in t):
        return None
    vals = [GREEK_NUM[c] for c in t]
    if vals != sorted(vals, reverse=True) or len(set(vals)) != len(vals):
        return None                      # not a well-formed numeral (e.g. OCR noise)
    return sum(vals)


def parse_heading(text):
    """'ΚΕΦΑΛ. ΙΔʹ [ΚΗʹ].' -> (14, 28); missing parts -> None."""
    m = re.search(r"ΚΕΦ\w*\.?\s*([^\s\[(]+)?\s*[\[(]?\s*([^\s\])]+)?", plain(text).upper())
    if not m:
        return None, None
    a = greek_number(m.group(1) or "")
    b = greek_number(m.group(2) or "")
    return a, b


def is_heading(text):
    """Chapter heading line: starts with capital ΚΕΦ (ΚΕΦΑΛ., ΚΕΦ.) - not the word κεφαλή."""
    return plain(text).translate(LATIN_LOOKALIKE).lstrip("«[( ⟦?⟧").startswith("ΚΕΦ")


def ia_get(url, dest):
    if dest.exists():
        return dest.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "pg-ocr/structure (research)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def roman_value(s):
    s = s.upper().replace("1", "I").replace("L", "I").replace("T", "I").replace("Ι", "I") \
         .replace("Y", "V").replace("Π", "II").replace("Η", "II")
    s = re.sub(r"[^IVX]", "", s)
    return ROMAN.get(s)


# ----------------------------------------------------------------- 1+2: columns, books
def running_heads(args, n_pages):
    """Per PDF page: numbers and book seen in the running head of the IA OCR."""
    item = args.main_item
    cache = args.root / "data" / "ia" / item
    st = gzip.decompress(ia_get(f"{IA}/{item}/{item}_hocr_searchtext.txt.gz",
                                cache / "searchtext.txt.gz")).decode("utf-8", "replace")
    idx = json.loads(gzip.decompress(ia_get(f"{IA}/{item}/{item}_hocr_pageindex.json.gz",
                                            cache / "pageindex.json.gz")))
    heads = {}
    for i, a in enumerate(idx[:n_pages]):
        head = st[a[0]:a[0] + 160]
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", head)]
        m = re.search(r"LIB\w*\.?\s*([IVXLlTtΠΗΙY1]{1,5})\b", head)
        heads[i + 1] = {"nums": nums, "book": roman_value(m.group(1)) if m else None}
    return heads


def fit_columns(heads, pages, dup_of, window=10):
    """Migne column of the left and right column of every page.

    Without duplicate scans the left column is 2*e + c (e = page index without the
    duplicates); c is taken as the most frequent value in a window of pages."""
    seq = [p for p in sorted(heads) if p not in dup_of]
    e = {p: k for k, p in enumerate(seq)}
    votes = {}
    for p in seq:
        v = collections.Counter()
        for n in heads[p]["nums"]:
            if 2 <= n <= 9999:
                v[n - 2 * e[p]] += 1          # n is the left column
                v[n - 1 - 2 * e[p]] += 1      # n is the right column
        votes[p] = v
    cols, quality = {}, {}
    for p in seq:
        k = e[p]
        tot = collections.Counter()
        for q in seq[max(0, k - window):k + window + 1]:
            tot.update(votes[q])
        if not tot:
            continue
        c, n = tot.most_common(1)[0]
        cols[p] = (2 * k + c, 2 * k + c + 1)
        quality[p] = n
    for p, orig in dup_of.items():
        if orig in cols:
            cols[p] = cols[orig]
    return cols, quality


def fit_books(heads, pages, window=4):
    raw = {p: heads[p]["book"] for p in heads if heads[p]["book"]}
    books, last = {}, None
    for p in sorted(heads):
        near = [raw[q] for q in range(p - window, p + window + 1) if q in raw]
        if near:
            b = collections.Counter(near).most_common(1)[0][0]
            last = b if last is None else max(last, b) if b - last <= 1 else last
        books[p] = last
    return books


# ----------------------------------------------------------------- 3: titles
def page_image(args, run, rec):
    from PIL import Image
    src = rec.get("source", "pdf")
    W, H = rec["size"]
    if src.startswith("alt leaf"):
        leaf = int(src.split()[-1])
        f = args.root / "data" / "alt" / f"PG{args.vol:03d}" / f"leaf_{leaf:04d}.jpg"
        img = Image.open(f).convert("L")
        return img.resize((W, H), Image.LANCZOS)
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    if not hasattr(page_image, "docs"):
        page_image.docs = {}
    path = rec.get("pdf") or str(args.pdf)       # a page taken from another copy (map:)
    if path not in page_image.docs:
        page_image.docs[path] = fitz.open(path)
    page = page_image.docs[path][rec.get("pdf_page", rec["page"]) - 1]
    zoom = H / page.rect.height
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    return img if img.size == (W, H) else img.resize((W, H))


def greek_titles(rec, iou, cover):
    """Title boxes on the Greek side of the page that are not inside a text column."""
    G = [g["box"] for g in rec["greek"]]
    T = sorted([d for d in rec["detections"] if d["cls"] == "MainText_Title"], key=lambda d: -d["conf"])
    keep = []
    for t in T:
        if all(iou(t["box"], k["box"]) < 0.3 for k in keep):
            keep.append(t)
    out = []
    for t in keep:
        b = t["box"]
        xc = (b[0] + b[2]) / 2
        if any(g[0] - 20 <= xc <= g[2] + 20 for g in G) and not any(cover(b, g) > 0.6 for g in G):
            out.append(b)
    return out


def ocr_titles(args, layouts, base, pages):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pg_ocr_volume import iou, cover, xml_complete, read_lines
    from PIL import Image
    tdir = args.root / "work" / f"PG{args.vol:03d}" / "titles"
    tdir.mkdir(parents=True, exist_ok=True)
    todo, boxes = [], {}
    for p in pages:
        run = base.get(p)
        rec = layouts.get(run, {}).get(p)
        if not rec:
            continue
        tb = greek_titles(rec, iou, cover)
        if not tb:
            continue
        img = None
        for k, b in enumerate(tb, 1):
            name = tdir / f"{run}_p{p:04d}_t{k}"
            boxes[(p, k)] = (run, b, rec["size"][0], name)
            if xml_complete(name.with_suffix(".xml")):
                continue
            if img is None:
                img = page_image(args, run, rec)
            x0, y0 = max(0, b[0] - 4), max(0, b[1] - 12)
            x1, y1 = min(img.width, b[2] + 4), min(img.height, b[3] + 12)
            crop = img.crop((x0, y0, x1, y1))
            from kraken.binarization import nlbin
            crop = nlbin(crop).convert("L")
            canvas = Image.new("L", (crop.width, max(1800, crop.height)), 255)
            canvas.paste(crop, (0, 0))
            canvas.save(name.with_suffix(".png"))
            todo.append(name)
    print(f"[titles] {len(boxes)} Greek title blocks, {len(todo)} to recognise", flush=True)
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        cmd = ["kraken", "-d", args.device, "-x"]
        for n in chunk:
            cmd += ["-i", str(n.with_suffix(".png")), str(n.with_suffix(".xml"))]
        cmd += ["segment", "-bl", "ocr", "-m", str(args.model), "-B", "8"]
        subprocess.run(cmd)
    titles = collections.defaultdict(list)
    for (p, k), (run, b, W, name) in boxes.items():
        xml = name.with_suffix(".xml")
        if not xml_complete(xml):
            continue
        lines = [(l[0], l[1]) for l in sorted(read_lines(xml), key=lambda l: l[3]) if l[0]]
        if lines:
            side = "L" if (b[0] + b[2]) / 2 < W / 2 else "R"
            titles[p].append({"side": side, "y": b[1], "lines": lines})
    return titles


# ----------------------------------------------------------------- 4: assemble
def load_best(path):
    pages = collections.defaultdict(list)
    for row in path.read_text(encoding="utf-8").splitlines()[1:]:
        f = row.split("\t")
        if len(f) >= 5:
            pages[int(f[0])].append((int(f[1]), int(f[2]), float(f[3]), f[4]))
    return pages


# ----------------------------------------------------------------- 4: headings
def roman_to_int(s):
    s = s.upper().replace("L", "I").replace("1", "I").replace("T", "I")
    if not s or re.sub(r"[IVX]", "", s):
        return None
    vals = {"I": 1, "V": 5, "X": 10}
    tot = 0
    for i, c in enumerate(s):
        v = vals[c]
        tot += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return tot if 0 < tot < 200 else None


def greek_ord(n):
    if not n:
        return "?"
    h, t, u = n // 100, n % 100 // 10, n % 10
    return ("Ρ" * h + " ΙΚΛΜΝΞΟΠϘ"[t].strip() + " ΑΒΓΔΕϚΖΗΘ"[u].strip()) + "ʹ"


def uppercase_share(text):
    letters = [c for c in plain(text) if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def heading_like(text):
    """A heading line like 'ΚΕΦΑΛ. ΙΕʹ [ΚΘʹ].' (our model reads it as 'ΚΕβΑΑ. ΙΕ.' etc.)."""
    t = text.strip()
    letters = [c for c in plain(t) if c.isalpha()]
    return 3 <= len(letters) <= 22 and uppercase_share(t) >= 0.5 and "." in t \
        and plain(t).lstrip(" .-«[(")[:1].isupper()


def numeral_after_kef(text):
    """In-book number of a heading line: first Greek numeral after the first word."""
    t = plain(text).translate(LATIN_LOOKALIKE).replace("1", "Ι").replace("l", "Ι")
    parts = [x for x in re.split(r"[\s.,:;·\[\]()]+", t) if x]
    nums = [greek_number(tok) for tok in parts[1:]]
    nums = [n for n in nums if n]
    if len(nums) >= 2 and nums[0] == 1 and len(parts) > 1 and parts[1] in ("Α", "Λ"):
        nums = nums[1:]                 # 'ΚΕΦΑ Α. Εʹ' = ΚΕΦΑΛ. Εʹ (letter split off)
    return nums[0] if nums else None


IA_HEAD = re.compile(r"[ΚK]\s?[ΕE]\s?Φ\s?[ΑΛA]{1,3}[ΛΔ]?\s?[.,]?\s*([^\s\[\(\]]{1,6})\s*"
                     r"(?:[\[\(]\s*([^\]\)\s]{0,6})[^\s]{0,3})?\s*[.:]?\s*([^\n]{0,160})")


def ia_headings(text):
    """Chapter headings in an IA OCR page text -> [{'inbook', 'subject'}]."""
    out = []
    for m in IA_HEAD.finditer(text):
        num = greek_number(m.group(1).replace("1", "Ι").replace("8", "Θ"))
        subj = m.group(3).strip()
        cut = re.search(r"^(.*?[.;])(\s|$)", subj)
        subj = cut.group(1) if cut else subj[:80]
        subj = re.sub(r"[«»“”\"]", "", subj).strip()
        if not re.match(r"^[Α-ΩἈ-Ὧ]", plain(subj)) or len(subj) < 5:
            subj = ""
        out.append({"inbook": num, "subject": subj})
    return out


def load_ia(args, tag):
    """IA OCR page texts: main item (by PDF page) and alt item (by alt leaf)."""
    item = args.main_item
    cache = args.root / "data" / "ia" / item
    st = gzip.decompress((cache / "searchtext.txt.gz").read_bytes()).decode("utf-8", "replace")
    idx = json.loads(gzip.decompress((cache / "pageindex.json.gz").read_bytes()))
    main = {i + 1: st[a[0]:a[1]] for i, a in enumerate(idx)}
    alt = {}
    acache = args.root / "data" / "alt" / tag
    amap_f = args.root / "work" / tag / "v5" / "altmap.json"
    if (acache / "searchtext.txt.gz").exists() and amap_f.exists():
        at = gzip.decompress((acache / "searchtext.txt.gz").read_bytes()).decode("utf-8", "replace")
        aidx = json.loads(gzip.decompress((acache / "pageindex.json.gz").read_bytes()))
        amap = json.loads(amap_f.read_text())
        for k, v in amap.items():
            if not k.startswith("_") and v["leaf"] < len(aidx):
                a = aidx[v["leaf"]]
                alt[int(k)] = at[a[0]:a[1]]
    return main, alt


def page_items(p, best, layouts, base, titles):
    """Lines and title blocks of a page in reading order (left column, then right)."""
    rec = layouts.get(base.get(p), {}).get(p)
    W = rec["size"][0] if rec else 2000
    cbox = {int(g["crop"].rsplit("_c", 1)[1]): g["box"] for g in rec["greek"]} if rec else {}
    items = []
    for col, n, cf, text in best.get(p, []):
        b = cbox.get(col, [0, 0, W, 0])
        items.append({"kind": "line", "side": "L" if (b[0] + b[2]) / 2 < W / 2 else "R",
                      "y": b[1], "col": col, "n": n, "text": text, "conf": cf})
    for t in titles.get(p, []):
        items.append({"kind": "block", "side": t["side"], "y": t["y"], "col": 0, "n": 0, "lines": t["lines"]})
    items.sort(key=lambda x: (x["side"] != "L", x["y"], x["col"], x["n"]))
    return items


def resolve_headings(pages, items_of, ia_main, ia_alt, report):
    """Decide which items are chapter headings and collect number/subject evidence."""
    heads = []
    for p in pages:
        items = items_of[p]
        A = ia_headings(ia_alt.get(p, ""))
        B = ia_headings(ia_main.get(p, ""))
        ia = A if len(A) >= len(B) else B
        other = B if ia is A else A
        caps = [roman_to_int(x) for x in re.findall(r"C\s?A\s?P\s?\.?\s*([IVXLl1T]{1,7})\b", ia_main.get(p, ""))]
        n_ia = max(len(A), len(B), len(caps))
        strong = [k for k, it in enumerate(items)
                  if (it["kind"] == "block" and any(heading_like(t) for t, _ in it["lines"]))
                  or (it["kind"] == "line" and heading_like(it["text"]) and it["conf"] < 0.995)]
        weak = [k for k, it in enumerate(items) if it["kind"] == "block" and k not in strong]
        cand = list(strong)
        if n_ia > len(cand):
            cand = sorted(cand + weak[:n_ia - len(cand)])
        found_by_subject = []
        if n_ia > len(cand):
            # heading printed inside the column and not recognised: find its subject line
            used = set(cand)
            for h in ia[len(cand):]:
                if not h["subject"]:
                    continue
                ks = key(h["subject"])
                g = grams(ks)
                scores, opening = [], []
                for k, it in enumerate(items):
                    if it["kind"] != "line" or k in used:
                        continue
                    kt = key(it["text"])
                    scores.append((jacc(g, grams(kt)), k))
                    if it["n"] == 1:      # subject at the top of a column: compare with the line's opening
                        opening.append((jacc(g, grams(kt[:len(ks) + 2])), k))
                scores.sort(reverse=True)
                opening.sort(reverse=True)
                best_s, best_k = scores[0] if scores else (0.0, None)
                if best_s < 0.35 and opening and opening[0][0] >= 0.3:
                    o_s, o_k = opening[0]
                    rest = max([sc for sc, kk in scores if kk != o_k] or [0.0])
                    if o_s - rest >= 0.1:
                        best_s, best_k = 0.35, o_k
                if best_k is not None and best_s >= 0.35:
                    cand.append(best_k)
                    used.add(best_k)
                    found_by_subject.append(best_k)
            cand.sort()
        if n_ia > len(cand):
            report.append(f"p{p}: {n_ia - len(cand)} heading(s) seen in the IA OCR could not be placed")
        for j, k in enumerate(cand):
            it = items[k]
            def pick(lst):
                if len(lst) == len(cand):
                    return lst[j]
                if 0 < len(lst) < len(cand) and j >= len(cand) - len(lst):
                    return lst[j - (len(cand) - len(lst))]     # extra blocks come first
                return None
            h_ia, h_ot = pick(ia), pick(other)
            if it["kind"] == "block":
                lines = it["lines"]
                hl = [t for t, _ in lines if heading_like(t)]
                ocr_num = numeral_after_kef(hl[0]) if hl else None
                subj = [(t, c) for t, c in lines if not heading_like(t) and c >= 0.9
                        and re.match(r"^[Α-ΩἈ-Ὧ]", plain(t.strip())) and len(t.strip()) >= 5]
            else:
                ocr_num = numeral_after_kef(it["text"]) if heading_like(it["text"]) else None
                subj = [(it["text"], it["conf"])] if k in found_by_subject else []
            page_nums = {h["inbook"] for h in A + B if h["inbook"]} | {c for c in caps if c}
            heads.append({"page": p, "k": k, "ocr_num": ocr_num, "ia": h_ia, "ia2": h_ot,
                          "page_nums": page_nums, "subj_ocr": " ".join(t for t, _ in subj).strip()})
    return heads


def evidence(h, v):
    """How strongly the readings support chapter number v for heading h."""
    sc = 0.0
    for x, w in ((h["ocr_num"], 1.0), ((h["ia"] or {}).get("inbook"), 1.0), ((h["ia2"] or {}).get("inbook"), 1.0)):
        if x == v:
            sc += w
    if v in h["page_nums"]:
        sc += 0.5                          # seen somewhere on the page (Greek or Latin CAP.)
    return sc


def number_book(seg, report, book):
    """Best numbering of one book: +1 per heading, a skipped number (heading not
    found) costs 1.2, each reading that agrees adds to the score (dynamic programming)."""
    n = len(seg)
    top = n + 6
    NEG = -1e9
    score = [[NEG] * (top + 1) for _ in range(n)]
    back = [[0] * (top + 1) for _ in range(n)]
    for v in range(1, 4):
        score[0][v] = evidence(seg[0], v) - 1.2 * (v - 1)
    for i in range(1, n):
        for v in range(2, top + 1):
            best, arg = NEG, 0
            for d, cost in ((1, 0.0), (2, 1.2), (3, 2.4)):
                u = v - d
                if u >= 1 and score[i - 1][u] > NEG and score[i - 1][u] - cost > best:
                    best, arg = score[i - 1][u] - cost, u
            if arg:
                score[i][v] = best + evidence(seg[i], v)
                back[i][v] = arg
    v = max(range(1, top + 1), key=lambda x: score[n - 1][x])
    nums = [0] * n
    for i in range(n - 1, -1, -1):
        nums[i] = v
        v = back[i][v]
    prev = 0
    for h, v in zip(seg, nums):
        h["inbook"] = v
        h["src"] = "read" if evidence(h, v) >= 1 else "inferred"
        if v > prev + 1:
            report.append(f"book {book}: heading of chapter(s) {prev + 1}-{v - 1} not found before "
                          f"PDF p. {h['page']} - its text is inside the previous chapter "
                              f"(place approximate; the numbers just before may be off by one)")
        prev = v


def number_headings(heads, books, report):
    """Split into books (a heading reading 1 where the running head shows the next
    book), then number each book with number_book()."""
    segs, book = [], None
    for h in heads:
        ones = [x for x in (h["ocr_num"], (h["ia"] or {}).get("inbook"), (h["ia2"] or {}).get("inbook")) if x == 1]
        page_book = books.get(h["page"])
        prev_n = len(segs[-1]) if segs else 0
        starts = book is None or (prev_n >= 5 and (
            (ones and ((page_book and page_book > book) or len(ones) >= 2)) or
            (page_book and page_book > book and 2 in {h["ocr_num"], (h["ia"] or {}).get("inbook")}
             and not ones)))
        if starts:
            book = (book + 1) if book is not None else (page_book or 1)
            segs.append([])
        h["book"] = book
        segs[-1].append(h)
    done = 0
    for seg in segs:
        number_book(seg, report, seg[0]["book"])
        for h in seg:
            h["overall"] = done + h["inbook"]
        done += seg[-1]["inbook"]
    return heads


def clean_subject(s):
    """A usable subject line: mostly Greek letters, no Latin/digit noise."""
    s = (s or "").strip()
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 5:
        return ""
    greek = sum(1 for c in letters if "\u0370" <= c <= "\u03ff" or "\u1f00" <= c <= "\u1fff")
    digits = sum(c.isdigit() for c in s)
    return s if greek / len(letters) >= 0.9 and digits <= 1 else ""


def subject_of(h):
    """Best available subject line ('Περὶ λύπης.')."""
    for s in (h["subj_ocr"], (h["ia"] or {}).get("subject"), (h["ia2"] or {}).get("subject")):
        s = clean_subject(s)
        if s:
            return s
    return ""


def build_chapters(pages, items_of, heads, cols, mark_conf):
    hk = {(h["page"], h["k"]): h for h in heads}
    chapters = []
    cur = {"head": None, "items": [], "page": None, "col": None, "book": None, "no": None,
           "no_book": None, "no_src": "front"}
    for p in pages:
        items = items_of[p]
        skip = set()
        for k, it in enumerate(items):
            col = None
            if p in cols:
                col = cols[p][0] if it["side"] == "L" else cols[p][1]
            if (p, k) in hk:
                h = hk[(p, k)]
                chapters.append(cur)
                head = f"ΚΕΦΑΛ. {greek_ord(h['inbook'])}"
                if h["book"] and h["book"] > 1:
                    head += f" [{greek_ord(h['overall'])}]"
                head += "."
                subj = subject_of(h)
                # an in-column heading: its subject line follows directly
                if it["kind"] == "line" and not h["subj_ocr"] and k + 1 < len(items) \
                        and items[k + 1]["kind"] == "line" and len(items[k + 1]["text"]) < 60 \
                        and re.search(r"[.·]\s*$", items[k + 1]["text"]):
                    subj = subj or items[k + 1]["text"]
                    skip.add(k + 1)
                cur = {"head": [head] + ([subj] if subj else []), "items": [], "page": p, "col": col,
                       "book": h["book"], "no": h["overall"], "no_book": h["inbook"], "no_src": h["src"]}
                continue
            if k in skip:
                continue
            if it["kind"] == "block":
                continue                    # other titles (book / work titles) are left out
            cur["items"].append({"kind": "line", "text": it["text"], "unsure": it["conf"] < mark_conf,
                                 "col": col, "page": p})
    chapters.append(cur)
    return [c for c in chapters if c["head"] is not None or c["items"]]


def grams(s, n=3):
    s = f" {s} "
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def key(s):
    return plain(s).lower()


def paragraphs(items, mark="⟦?⟧ "):
    """Join lines into paragraphs; hyphens joined; [col. N] where a column starts."""
    lens = sorted(len(it["text"]) for it in items if it["kind"] == "line")
    full = lens[int(len(lens) * 0.6)] if lens else 50
    paras, buf, last_col, carry = [], [], None, ""
    for it in items:
        if it["kind"] == "subtitle":
            if buf or carry:
                paras.append(" ".join(buf + ([carry] if carry else [])))
                buf, carry = [], ""
            paras.append(f"**{it['text']}**")
            continue
        text = it["text"].strip()
        if it.get("unsure"):
            buf.append(mark.strip())
        if it["col"] is not None and it["col"] != last_col:
            marker = f"[col. {it['col']}]"
            if carry:                       # word split over the column end: finish it first
                word, _, rest = text.partition(" ")
                buf.append(carry + word + " " + marker)
                carry, text = "", rest
            else:
                buf.append(marker)
            last_col = it["col"]
        if carry:
            text = carry + text
            carry = ""
        if text.endswith("-") and len(text) > 1 and text[-2].isalpha():
            words = text[:-1].split(" ")
            carry = words[-1]
            text = " ".join(words[:-1])
        if text:
            buf.append(text)
        if not carry and len(it["text"]) < 0.75 * full and re.search(r"[.·;:!»]\s*$", text):
            paras.append(" ".join(buf))
            buf = []
    if buf or carry:
        paras.append(" ".join(buf + ([carry] if carry else [])))
    return [re.sub(r"\s+", " ", p).strip() for p in paras if p.strip()]


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--text-tag", default="best", help="merged text to structure")
    ap.add_argument("--main-item", default=None, help="IA item of the PDF (for running heads)")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--work-title", default=None, help="title written at the top")
    ap.add_argument("--mark-conf", type=float, default=0.80)
    ap.add_argument("--mark", default="⟦?⟧ ")
    ap.add_argument("--no-titles", action="store_true", help="skip title recognition (no GPU)")
    args = ap.parse_args()
    tag = f"PG{args.vol:03d}"
    args.main_item = args.main_item or MAIN_ITEMS.get(args.vol)
    if not args.main_item:
        sys.exit(f"no IA item known for PG {args.vol}: give --main-item")
    args.pdf = args.root / "data" / "pdf" / f"{tag}.pdf"
    out = args.root / "output" / tag / args.text_tag
    print(f"pg_structure.py version {VERSION}")

    best = load_best(out / f"{tag}_lines.tsv")
    pages = sorted(best)
    base = {}
    rep = out / "merge_report.tsv"
    if rep.exists():
        for row in rep.read_text(encoding="utf-8").splitlines()[1:]:
            f = row.split("\t")
            base[int(f[0])] = f[1]
    runs = sorted(set(base.values())) or ["v4"]
    for p in pages:
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
    dup_of = {}
    for r in runs + [args.text_tag]:
        sf = args.root / "output" / tag / r / "summary.json"
        if sf.exists():
            for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
                a, b = d.split(" = ")
                dup_of[int(a[1:])] = int(b[1:])

    print(f"[columns] reading running heads of {args.main_item}", flush=True)
    heads = running_heads(args, max(pages) + 20)
    cols, quality = fit_columns(heads, pages, dup_of)
    books = fit_books(heads, pages)
    weak_cols = [p for p in pages if quality.get(p, 0) < 6]

    titles = {} if args.no_titles else ocr_titles(args, layouts, base, pages)
    ia_main, ia_alt = load_ia(args, tag)
    items_of = {p: page_items(p, best, layouts, base, titles) for p in pages}
    report = []
    heads = resolve_headings(pages, items_of, ia_main, ia_alt, report)
    number_headings(heads, books, report)
    chapters = build_chapters(pages, items_of, heads, cols, args.mark_conf)

    sdir = out.parent / "structured"
    (sdir / "chapters").mkdir(parents=True, exist_ok=True)
    md = [f"# {args.work_title or tag}", "",
          f"OCR of Migne, Patrologia Graeca {args.vol} (PDF pages {pages[0]}–{pages[-1]}). "
          f"[col. N] = start of Migne column N. ⟦?⟧ = uncertain line. Not proofread.", ""]
    rows = ["no\tbook\tno_in_book\ttitle\tpdf_page\tmigne_col\tnumber\twords"]
    last_book = None
    for c in chapters:
        body = paragraphs(c["items"], args.mark)
        if c["head"] is None:
            md += ["## (before the first chapter heading)", ""] + [p + "\n" for p in body]
            continue
        if c["book"] and c["book"] != last_book:
            md += [f"## Βιβλίον {GREEK_ORD.get(c['book'], greek_ord(c['book']))} (Liber {c['book']})", ""]
            last_book = c["book"]
        head = " ".join(h.strip() for h in c["head"])
        cite = f"PG {args.vol}, {c['col']}" if c["col"] else f"PDF p. {c['page']}"
        md += [f"### {head}  ({cite})", ""] + [p + "\n" for p in body]
        subject = " ".join(h.strip() for h in c["head"][1:]) or "-"
        nwords = sum(len(p.split()) for p in body)
        rows.append(f"{c['no']}\t{c['book']}\t{c['no_book']}\t{subject}\t{c['page']}\t{c['col']}\t{c['no_src']}\t{nwords}")
        if c["no"] is not None:
            (sdir / "chapters" / f"ch{c['no']:03d}.txt").write_text(
                f"{head}\n({cite}; book {c['book']}; PDF p. {c['page']})\n\n" + "\n\n".join(body) + "\n",
                encoding="utf-8")
    (sdir / f"{tag}_structured.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (sdir / f"{tag}_chapters.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    nums = [c["no"] for c in chapters if c.get("no")]
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums)) if nums else []
    lines = [f"pg_structure.py {VERSION}", f"chapters found: {len(nums)} (numbers {min(nums) if nums else '-'}–{max(nums) if nums else '-'})",
             f"chapter numbers read: {sum(1 for c in chapters if c.get('no_src') == 'read')}, inferred: "
             f"{sum(1 for c in chapters if str(c.get('no_src', '')).startswith('inferred'))}",
             f"numbers missing in the sequence: {missing or 'none'}"]
    if nums and min(nums) > 1:
        lines.append(f"NOTE: first chapter found is {min(nums)} - the pages before PDF p. {pages[0]} "
                     f"were not OCR'd (run them with pg_ocr.sh, then merge again)")
    lines.append(f"Migne columns: pages {pages[0]}-{pages[-1]} -> col. "
                 f"{cols.get(pages[0], ('?',))[0]}-{cols.get(pages[-1], ('?', '?'))[1]}; "
                 f"weakly supported pages: {weak_cols or 'none'}")
    lines.append(f"duplicate scans (same columns as original): {dup_of or 'none'}")
    per_book = collections.Counter(c["book"] for c in chapters if c.get("no"))
    lines.append("chapters per book: " + ", ".join(f"{b}: {n}" for b, n in sorted(per_book.items())))
    lines += ["", "Checks:"] + (report or ["all chapter numbers read and in sequence"])
    (sdir / "structure_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"-> {sdir}")


if __name__ == "__main__":
    main()
