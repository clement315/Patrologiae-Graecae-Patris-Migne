#!/usr/bin/env python3
"""
pg_columns.py - column concordance for a recognised PG volume: scan slice, line-by-line
Greek text and Migne's section letters for every Migne column.

    python3 pg_columns.py --vol 11                       (after pg_ocr.sh N works)
    python3 pg_columns.py --vol 11 --no-images           text and tables only

Needs the finished OCR (output/PGxxx/best), the page/column table of pg_works.py
(output/PGxxx/works/pagecols.tsv) and the layout and line files of the runs
(work/PGxxx/v4, v5 ...).  For each page the run the merged text follows
(merge_report.tsv) supplies the image and the line positions.

Migne prints the letters A B C D in the gutter between the Greek and the Latin column
(A at the top, then a quarter, a half and three quarters down); a reference "PG 11, 13B"
means column 13 from the letter B on.  The letters are found on the page image (small
marks in the middle of the gutter), named by their height on the page and put before the
Greek line beside them as |ᴬ| |ᴮ| |ᶜ| |ᴰ|.  A letter that is printed but not found is
supplied from the quarter heights and written |ᴮ?|.

Output in output/PGxxx/columns/:
  PGxxx_columns.md     the Greek text column by column, printed lines kept, with the letters
  PGxxx_columns.tsv    one row per column: page, side, scan, image, box on the page, lines,
                       line numbers of A-D, mean confidence
  PGxxx_lines.jsonl    one row per line: column, line, section letter, text, confidence,
                       box in the column image, page and box on the page
  img/PGxxx_c0013.jpg  the Greek column as printed (grey JPEG, page-image resolution,
                       with the gutter and its letters)          [not uploaded to GitHub]
  check/               a few page images with the found letters drawn in (--check N)
"""
import argparse
import collections
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "1.0"
LETTERS = "ABCD"
SUP = {"A": "ᴬ", "B": "ᴮ", "C": "ᶜ", "D": "ᴰ"}
GREEK_CLASS, LATIN_CLASS = "MainText_ColGreek", "MainText_ColLatin"


# ----------------------------------------------------------------- input
def load_layout(path):
    out = {}
    if path.exists():
        for row in path.read_text(encoding="utf-8").splitlines():
            if row.strip():
                r = json.loads(row)
                out[r["page"]] = r
    return out


def load_best(path):
    pages = collections.defaultdict(list)
    for row in path.read_text(encoding="utf-8").splitlines()[1:]:
        f = row.split("\t")
        if len(f) >= 5 and f[0].isdigit():
            pages[int(f[0])].append((int(f[1]), int(f[2]), float(f[3] or 0), f[4]))
    return pages


def load_pagecols(path):
    order, cols = [], {}
    for row in path.read_text(encoding="utf-8").splitlines()[1:]:
        p, a, b = row.split("\t")
        p = int(p)
        order.append(p)
        if a != "None":
            cols[p] = (int(a), int(b))
    return order, cols


def page_lines(xml_path):
    """Lines of a kraken PageXML file: text, confidence, box (x0, y0, x1, y1) in the crop."""
    out = []
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return out
    for tl in root.iter():
        if not tl.tag.endswith("TextLine"):
            continue
        txt, conf, box = "", 0.0, None
        for ch in tl:
            if ch.tag.endswith("Coords") and ch.get("points"):
                pts = [tuple(map(float, p.split(","))) for p in ch.get("points").split()]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                box = [min(xs), min(ys), max(xs), max(ys)]
            elif ch.tag.endswith("TextEquiv"):
                for u in ch:
                    if u.tag.endswith("Unicode"):
                        txt = u.text or ""
                conf = float(ch.get("conf", 0) or 0)
        txt = unicodedata.normalize("NFC", txt).strip()
        if txt and box:
            out.append((txt, conf, box))
    return out


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if c.isalpha())


def align(best, alto):
    """For each line of the merged text the index of its line in the run's PageXML (or None):
    the lines of the run that the merge kept are in the same order."""
    if len(best) == len(alto):
        return list(range(len(best)))
    A, B = [norm(t) for t in best], [norm(t[0]) for t in alto]
    res, j = [], 0
    for a in A:
        bestk, bestr = None, 0.45
        for k in range(j, min(len(B), j + 4)):
            r = difflib.SequenceMatcher(None, a, B[k]).ratio()
            if r > bestr:
                bestk, bestr = k, r
        res.append(bestk)
        if bestk is not None:
            j = bestk + 1
    return res


# ----------------------------------------------------------------- page images
class Images:
    def __init__(self, root, vol, pdf):
        self.root, self.vol, self.pdf = root, vol, pdf
        self.docs = {}
        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz
            except ImportError:
                fitz = None
        self.fitz = fitz if fitz is not None and hasattr(fitz, "Matrix") else None

    def get(self, rec):
        from PIL import Image
        W, H = rec["size"]
        src = rec.get("source", "pdf")
        if src.startswith("alt leaf"):
            leaf = int(src.split()[-1])
            f = self.root / "data" / "alt" / f"PG{self.vol:03d}" / f"leaf_{leaf:04d}.jpg"
            return Image.open(f).convert("L").resize((W, H), Image.LANCZOS)
        path = rec.get("pdf") or str(self.pdf)
        pno = rec.get("pdf_page", rec["page"])
        if self.fitz:
            if path not in self.docs:
                self.docs[path] = self.fitz.open(path)
            page = self.docs[path][pno - 1]
            zoom = H / page.rect.height
            pix = page.get_pixmap(matrix=self.fitz.Matrix(zoom, zoom), colorspace=self.fitz.csGRAY, alpha=False)
            img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            return img if img.size == (W, H) else img.resize((W, H))
        with tempfile.TemporaryDirectory() as td:            # no PyMuPDF: poppler
            subprocess.run(["pdftoppm", "-f", str(pno), "-l", str(pno), "-scale-to-x", str(W),
                            "-scale-to-y", str(H), "-gray", "-png", path, f"{td}/p"], check=True)
            f = next(Path(td).glob("p*.png"))
            return Image.open(f).convert("L").copy()


# ----------------------------------------------------------------- section letters
def gutter(rec, gbox):
    """x range of the gutter beside a Greek column, and the y range of the text on the page."""
    W = rec["size"][0]
    gx0, gy0, gx1, gy1 = gbox
    left = (gx0 + gx1) / 2 < W / 2                     # Greek on the left half: gutter on its right
    lat = [d["box"] for d in rec.get("detections", []) if d["cls"] == LATIN_CLASS and d["conf"] >= 0.3]
    other = None
    for b in sorted(lat, key=lambda b: -(min(b[3], gy1) - max(b[1], gy0))):
        if min(b[3], gy1) - max(b[1], gy0) > 0 and ((b[0] > gx0) if left else (b[2] < gx1)):
            other = b
            break
    if left:
        a = gx1 - 12
        b = other[0] + 12 if other else gx1 + 80
    else:
        a = other[2] - 12 if other else gx0 - 80
        b = gx0 + 12
    ys = [gy0, gy1] + ([other[1], other[3]] if other else [])
    return int(a), int(b), int(min(ys)), int(max(ys)), other


def find_letters(img, rec, gbox, line_boxes):
    """Section letters in the gutter beside a Greek column: [(y_center, height, box), ...].
    A row belongs to the free gutter between the end of the Greek line beside it (from the
    line boxes) and the edge of the Latin column; dark pixels there in a band about as high
    as a capital, and narrow, are a letter."""
    import numpy as np
    a, b, top, bot, other = gutter(rec, gbox)
    W, H = img.size
    gx0, gy0, gx1, gy1 = gbox
    left = (gx0 + gx1) / 2 < W / 2
    x_lo, x_hi = (gx1 - 40, (other[0] + 6) if other else gx1 + 90) if left else \
                 ((other[2] - 6) if other else gx0 - 90, gx0 + 40)
    x_lo, x_hi = max(0, int(x_lo)), min(W, int(x_hi))
    if x_hi - x_lo < 20:
        return [], (top, bot)
    y_lo, y_hi = max(0, top - 10), min(H, bot + 10)
    strip = np.asarray(img.crop((x_lo, y_lo, x_hi, y_hi)), dtype=np.uint8) < 128
    # the end of the Greek text in every row (line boxes; between lines: the nearer line)
    edge = np.full(strip.shape[0], (gx1 if left else gx0) - x_lo, dtype=float)
    lb = sorted((b_ for b_ in line_boxes if b_), key=lambda b_: b_[1])
    for y in range(strip.shape[0]):
        yy = y + y_lo
        near = [b_ for b_ in lb if b_[1] - 12 <= yy <= b_[3] + 12]
        if near:
            edge[y] = (max(b_[2] for b_ in near) if left else min(b_[0] for b_ in near)) - x_lo
    w = strip.shape[1]
    zone = np.zeros_like(strip)
    for y in range(strip.shape[0]):
        e = int(edge[y])
        if left:
            lo, hi = e + 4, w - 4
        else:
            lo, hi = 4, e - 4
        if hi > lo:
            zone[y, lo:hi] = strip[y, lo:hi]
    rows = zone.any(axis=1)
    bands, start = [], None
    for y, v in enumerate(list(rows) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            bands.append((start, y))
            start = None
    marks = []
    for y0, y1 in bands:
        h = y1 - y0
        if not 16 <= h <= 70:
            continue
        cols_ = np.where(zone[y0:y1].any(axis=0))[0]
        l, r = int(cols_.min()), int(cols_.max())
        width = r - l + 1
        if not 8 <= width <= 55:
            continue
        if zone[y0:y1].sum() < 0.12 * h * width:
            continue                                               # specks
        yc = (y0 + y1) / 2 + y_lo
        if not top - 8 <= yc <= bot + 8:
            continue
        marks.append((yc, h, (x_lo + l, y0 + y_lo, x_lo + r + 1, y1 + y_lo)))
    if marks:
        hs = sorted(m[1] for m in marks)
        med = hs[len(hs) // 2]
        marks = [m for m in marks if 0.6 * med <= m[1] <= 1.5 * med]
    return marks, (top, bot)


def name_letters(marks, top, step):
    """Name the marks A-D.  Migne sets them a fixed distance apart (`step`, about a quarter
    of a full column), A beside the first line of the text (after a title: of the text below
    it).  The grid y = o + k*step (k = 0..3) that holds most marks gives the names; marks off
    the grid (Greek letters of a line that runs into the gutter, specks) are left out."""
    marks = sorted(marks)
    if not marks:
        return {}
    tol = 0.13 * step
    cands = set()
    for y, h, box in marks:
        for k in range(4):
            o = y - k * step
            if o >= top - 40:
                cands.add(round(o))
    if len(marks) == 1:
        y = marks[0][0]
        cands = {round(y - max(0, int(round((y - top) / step - 0.15))) * step)}
    best = None
    for o in cands:
        hit = {}
        for k in range(4):
            g = o + k * step
            near = [(abs(m[0] - g), m) for m in marks if abs(m[0] - g) <= tol]
            if near:
                hit[LETTERS[k]] = min(near)[1]
        err = sum(abs(m[0] - (o + LETTERS.index(L) * step)) for L, m in hit.items())
        key = (len(hit), -abs(o - top) if len(hit) == 1 else 0, -err)
        if best is None or key > best[0]:
            best = (key, hit)
    return {L: (m[0], m[2]) for L, m in best[1].items()}


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--text-tag", default="best")
    ap.add_argument("--no-images", action="store_true", help="text and tables only, no column images")
    ap.add_argument("--quality", type=int, default=85, help="JPEG quality of the column images")
    ap.add_argument("--check", type=int, default=6, help="page images with the letters drawn in")
    ap.add_argument("--pages", default="", help="only these PDF pages, e.g. 300-310 (for tests)")
    ap.add_argument("--mark-conf", type=float, default=0.80, help="lines below this get ⟦?⟧")
    args = ap.parse_args()
    tag = f"PG{args.vol:03d}"
    out_best = args.root / "output" / tag / args.text_tag
    work = args.root / "work" / tag
    cdir = args.root / "output" / tag / "columns"
    print(f"pg_columns.py version {VERSION}  {tag}", flush=True)

    best = load_best(out_best / f"{tag}_lines.tsv")
    pc = args.root / "output" / tag / "works" / "pagecols.tsv"
    if not pc.exists():
        sys.exit(f"missing {pc}: run  bash pg_ocr.sh {args.vol} works  first (pg_works.py 1.43 or later)")
    order, pagecols = load_pagecols(pc)
    base = {}
    rep = out_best / "merge_report.tsv"
    if rep.exists():
        for row in rep.read_text(encoding="utf-8").splitlines()[1:]:
            f = row.split("\t")
            base[int(f[0])] = f[1]
    layouts = {d.name: load_layout(d / "layout.jsonl") for d in sorted(work.glob("v*")) if d.is_dir()}
    images = Images(args.root, args.vol, args.root / "data" / "pdf" / f"{tag}.pdf")
    only = set()
    for part in filter(None, args.pages.split(",")):
        x, _, y = part.partition("-")
        only.update(range(int(x), int(y or x) + 1))

    if cdir.exists() and not args.pages:
        shutil.rmtree(cdir)
    (cdir / "img").mkdir(parents=True, exist_ok=True)
    (cdir / "check").mkdir(exist_ok=True)

    columns = collections.OrderedDict()          # Migne col -> list of pieces in reading order
    steps, step = [], None
    stats = collections.Counter()
    checks = 0
    for p in order:
        if only and p not in only:
            continue
        if p not in best or p not in pagecols:
            continue
        run = base.get(p) or next((r for r in ("v4", "v5", "v6") if p in layouts.get(r, {})), None)
        rec = layouts.get(run, {}).get(p)
        if rec is None:
            stats["pages without layout"] += 1
            continue
        W = rec["size"][0]
        if step is None or len(steps) < 5:
            step = 0.22 * rec["size"][1]
        greek = rec["greek"]
        bycol = collections.defaultdict(list)
        for col, ln, conf, txt in best[p]:
            bycol[col].append((ln, conf, txt))
        img = images.get(rec)                                  # the letters need the page image
        sides = collections.defaultdict(list)                  # 'L' / 'R' -> crops
        for k, g in enumerate(greek, 1):
            if k not in bycol:
                continue
            x0, y0, x1, y1 = g["box"]
            side = "W" if g.get("wide") else ("L" if (x0 + x1) / 2 < W / 2 else "R")
            sides["L" if side == "W" else side].append((k, g, side))
        nlines = {sd: sum(len(bycol[k]) for k, _, _ in pcs) for sd, pcs in sides.items()}
        for side, pieces in sides.items():
            col = pagecols[p][0 if side == "L" else 1]
            # a few Greek lines on the Latin side of the page (quotations, notes)
            minor = len(sides) > 1 and nlines[side] < 6 and max(nlines.values()) >= 20
            pieces.sort(key=lambda t: t[1]["box"][1])
            narrow = [t for t in pieces if t[2] != "W"] or pieces       # full-width Greek: not for the x range
            ux0 = min(t[1]["box"][0] for t in narrow)
            uy0 = min(t[1]["box"][1] for t in pieces)
            ux1 = max(t[1]["box"][2] for t in narrow)
            uy1 = max(t[1]["box"][3] for t in pieces)
            gb = (ux0, uy0, ux1, uy1)
            # the column image: the Greek column with the gutter and its letters
            ga, gbx, top, bot, _ = gutter(rec, gb)
            sx0, sx1 = (ux0, max(ux1, gbx)) if side == "L" else (min(ux0, ga), ux1)
            sx0, sx1 = max(0, sx0 - 8), min(W, sx1 + 8)
            sy0, sy1 = max(0, min(uy0, top) - 10), min(rec["size"][1], max(uy1, bot) + 10)
            lines = []
            for k, g, sd in pieces:
                cx0, cy0 = g["box"][0], g["box"][1]
                alto = page_lines(work / run / "crops" / f"{g['crop']}.xml")
                bl = sorted(bycol[k])
                idx = align([t[2] for t in bl], alto)
                for (ln, conf, txt), j in zip(bl, idx):
                    if j is not None:
                        b = alto[j][2]
                        pbox = [cx0 + b[0], cy0 + b[1], cx0 + b[2], cy0 + b[3]]
                    else:
                        pbox = None
                        stats["lines without position"] += 1
                    lines.append({"text": txt, "conf": round(conf, 4), "page_box": pbox, "piece": k})
            # positions of unplaced lines: between their neighbours
            for i, L in enumerate(lines):
                if L["page_box"] is None:
                    prev = next((lines[j]["page_box"] for j in range(i - 1, -1, -1) if lines[j]["page_box"]), None)
                    nxt = next((lines[j]["page_box"] for j in range(i + 1, len(lines)) if lines[j]["page_box"]), None)
                    if prev or nxt:
                        a_, b_ = prev or nxt, nxt or prev
                        L["page_box"] = [min(a_[0], b_[0]), (a_[3] + b_[1]) / 2 - 15, max(a_[2], b_[2]),
                                         (a_[3] + b_[1]) / 2 + 15]
                        L["estimated_box"] = True
            marks, (top, bot) = find_letters(img, rec, gb, [L["page_box"] for L in lines
                                                            if not L.get("estimated_box")])
            named = {} if minor else name_letters(marks, top, step)
            ys = sorted(m[0] for m in marks)
            for d_ in (y2 - y1 for y1, y2 in zip(ys, ys[1:])):
                if 0.15 * rec["size"][1] < d_ < 0.3 * rec["size"][1]:
                    steps.append(d_)
            if len(steps) >= 5:
                step = sorted(steps)[len(steps) // 2]
            # letters -> lines: the line whose band holds the middle of the letter (or the nearest)
            found = {}
            for letter, (y, box) in named.items():
                cand = [(abs((L["page_box"][1] + L["page_box"][3]) / 2 - y), i)
                        for i, L in enumerate(lines) if L["page_box"]]
                if not cand:
                    continue
                d, i = min(cand)
                if d > 70:
                    continue
                found[letter] = i
            # letters printed but not found: from the quarter heights, if the column runs there
            supplied = {}
            for k_, letter in enumerate(LETTERS):
                if letter in found or minor:
                    continue
                y = top + step * k_ + (12 if k_ == 0 else 0)
                cand = [(abs((L["page_box"][1] + L["page_box"][3]) / 2 - y), i)
                        for i, L in enumerate(lines) if L["page_box"]]
                if cand:
                    d, i = min(cand)
                    if d < 60 and all(abs(i - j) > 1 for j in list(found.values()) + list(supplied.values())):
                        supplied[letter] = i
            for letter, i in found.items():
                lines[i]["letter"] = letter
            for letter, i in supplied.items():
                lines[i].setdefault("letter", letter)
                if lines[i]["letter"] == letter:
                    lines[i]["letter_supplied"] = True
            stats["letters found"] += len(found)
            stats["letters supplied"] += len([1 for l in lines if l.get("letter_supplied")])
            stats["columns"] += 1
            # image
            img_name = f"{tag}_c{col:04d}{'' if col not in columns else '_' + str(p)}.jpg"
            if not args.no_images:
                img.crop((sx0, sy0, sx1, sy1)).save(cdir / "img" / img_name, quality=args.quality,
                                                    optimize=True)
            for L in lines:
                b = L["page_box"]
                L["box"] = None if b is None else [round(b[0] - sx0), round(b[1] - sy0),
                                                   round(b[2] - sx0), round(b[3] - sy0)]
            columns.setdefault(col, []).append({
                "page": p, "side": side, "run": run, "minor": minor, "source": rec.get("source", "pdf"),
                "image": img_name, "slice": [sx0, sy0, sx1, sy1], "lines": lines,
                "letters_found": {k: v[1] for k, v in named.items()}})
            if checks < args.check and len(found) >= 2 and not args.no_images:
                from PIL import ImageDraw
                chk = img.convert("RGB")
                dr = ImageDraw.Draw(chk)
                for letter, (y, box) in named.items():
                    dr.rectangle(box, outline=(255, 0, 0), width=4)
                    dr.text((box[2] + 6, box[1]), letter, fill=(255, 0, 0))
                for letter, i in found.items():
                    b = lines[i]["page_box"]
                    dr.rectangle(b, outline=(0, 160, 0), width=3)
                chk.resize((chk.width // 2, chk.height // 2)).save(cdir / "check" / f"p{p:05d}_{side}.jpg", quality=80)
                checks += 1

    # ---- write
    md = [f"# PG {args.vol}: Greek text column by column", "",
          f"pg_columns.py {VERSION}. Printed lines kept (hyphens as printed). "
          "|ᴬ| |ᴮ| |ᶜ| |ᴰ| = Migne's section letters in the gutter, before the line beside them; "
          "|ᴮ?| = letter not found on the image, placed from the quarter height. "
          "⟦?⟧ = uncertain line. Uncorrected OCR.", ""]
    tsv = ["migne_col\tpdf_page\tside\tscan\timage\tslice_box\tlines\tA\tB\tC\tD\tmean_conf"]
    jl = []
    for col, pieces in columns.items():
        n = 0
        for pc_ in pieces:
            src = "second scan" if pc_["source"].startswith("alt") or pc_["page"] > 10000 else "main scan"
            note = "; Greek on the Latin side" if pc_.get("minor") else ""
            md.append(f"## col. {col}  (PDF p. {pc_['page']}, {src}{note}; image {pc_['image']})" if n == 0 else
                      f"### col. {col} continued  (PDF p. {pc_['page']}, {src}{note}; image {pc_['image']})")
            md.append("")
            pos = {}
            confs = []
            for L in pc_["lines"]:
                n += 1
                confs.append(L["conf"])
                mark = ""
                if L.get("letter"):
                    mark = f"|{SUP[L['letter']]}{'?' if L.get('letter_supplied') else ''}| "
                    pos[L["letter"]] = n
                unc = "⟦?⟧ " if L["conf"] < args.mark_conf else ""
                md.append(f"{mark}{unc}{L['text']}")
                jl.append(json.dumps({"col": col, "line": n, "section": None, "letter": L.get("letter"),
                                      "letter_supplied": bool(L.get("letter_supplied")), "text": L["text"],
                                      "conf": L["conf"], "page": pc_["page"], "image": pc_["image"],
                                      "box": L["box"], "page_box": [round(v) for v in L["page_box"]]
                                      if L["page_box"] else None,
                                      **({"box_estimated": True} if L.get("estimated_box") else {})},
                                     ensure_ascii=False))
            md.append("")
            tsv.append("\t".join(map(str, [col, pc_["page"], pc_["side"], src, pc_["image"],
                                           ",".join(map(str, pc_["slice"])), len(pc_["lines"])]
                                 + [pos.get(x, "") for x in LETTERS]
                                 + [f"{sum(confs) / max(1, len(confs)):.4f}"])))
    # section letter of every line (the last letter at or before it in its column)
    cur, last_col = None, None
    rows = [json.loads(x) for x in jl]
    for r in rows:
        if r["col"] != last_col:
            cur, last_col = None, r["col"]
        if r["letter"]:
            cur = r["letter"]
        r["section"] = cur or "A"
    (cdir / f"{tag}_columns.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (cdir / f"{tag}_columns.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    (cdir / f"{tag}_lines.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                             encoding="utf-8")
    print(f"{stats['columns']} column pieces, {len(columns)} Migne columns; letters found "
          f"{stats['letters found']}, supplied {stats['letters supplied']}; "
          f"lines without position {stats['lines without position']}", flush=True)
    print(f"-> {cdir}", flush=True)


if __name__ == "__main__":
    main()
