"""
OCR of one Patrologia Graeca volume (Greek text only).

  PDF page --(PyMuPDF)--> page image --(Calfa YOLO layout)--> Greek main-text columns
      --(kraken: line segmentation + our recognition model)--> lines --> text files

Every stage is resumable: re-running skips what already exists.

Run inside WSL with the kraken environment (normally via pg_ocr.sh):
    python pg_ocr_volume.py --vol 94 --pdf /mnt/e/PG_OCR/data/pdf/PG094.pdf --pages 500-511
    python pg_ocr_volume.py --vol 94 --pdf ... --pages all

Outputs
  (all paths below are inside a version folder, default v2: work/PG094/v2/...)
  work/PG094/crops/p0500_c1.png  + .xml   binarised Greek column image and kraken PageXML
                                           (the PageXML can be corrected in eScriptorium)
  work/PG094/previews/p0500.jpg           page with regions (green = Greek read, orange = rejected)
  work/PG094/layout.jsonl                 one record per page (boxes, kept columns)
  output/PG094/PG094_text.txt             Calfa-style text: $0=volume $8=PDF page $9=first line
  output/PG094/PG094_lines.tsv            page / column / line / text  (for analysis)
  output/PG094/PG094_reading.txt          same text with line-end hyphens joined
  output/PG094/summary.json
"""
import argparse
import collections
import gzip
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "2.9 (second scan: _jp2.tar or _jp2.zip; excluded pages: work/PGxxx/exclude_pages.txt; extra leaves from the second scan; word confidences)"
GREEK_CLASS = "MainText_ColGreek"
LATIN_CLASS = "MainText_ColLatin"
NOTE_CLASSES = ("MainText_ColLatin", "Marginalia_Footnote")
IA = "https://archive.org/download"
PREVIEW_COLOURS = {"MainText_ColGreek": (0, 170, 0), "MainText_ColLatin": (220, 0, 0)}


# ----------------------------------------------------------------- helpers
EXTRA_BASE = 10000      # 'leaf:487' = leaf 487 of the second scan, stored as page 10487


def parse_pages(spec: str, n_pages: int):
    if spec.startswith("leaf:"):
        # pages missing from the main scan, taken directly from the second scan
        return sorted(EXTRA_BASE + int(x) for x in spec[5:].split(",") if x.strip())
    if spec in ("all", ""):
        return list(range(1, n_pages + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= n_pages)


def excluded_pages(root, tag):
    """Pages left out of the text (Latin prefaces, title pages, index): work/PGxxx/exclude_pages.txt.

    One page or range per line, e.g. "222-235  # Declaratio fidei (Latin only)".
    """
    f = Path(root) / "work" / tag / "exclude_pages.txt"
    out = set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            for part in filter(None, (x.strip() for x in line.split(","))):
                if "-" in part:
                    a, b = part.split("-")
                    out.update(range(int(a), int(b) + 1))
                else:
                    out.add(int(part))
    return out


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / float(area(a) + area(b) - inter)


def cover(a, b):
    """Share of box a that lies inside box b."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def order_columns(boxes, page_width):
    """Reading order of Greek boxes: left half top->bottom, then right half."""
    mid = page_width / 2.0
    left = sorted([b for b in boxes if (b["box"][0] + b["box"][2]) / 2 < mid], key=lambda b: b["box"][1])
    right = sorted([b for b in boxes if (b["box"][0] + b["box"][2]) / 2 >= mid], key=lambda b: b["box"][1])
    return left + right


def dedupe(boxes, thr=0.5):
    """Drop a Greek box that mostly overlaps a larger one (YOLO duplicates)."""
    boxes = sorted(boxes, key=lambda b: -(b["box"][2] - b["box"][0]) * (b["box"][3] - b["box"][1]))
    kept = []
    for b in boxes:
        if all(iou(b["box"], k["box"]) < thr for k in kept):
            kept.append(b)
    return kept


# ----------------------------------------------------------------- alternative scan
# The Internet Archive item "PatrologiaGraeca" holds a second, independent Google scan
# of every volume (different library copy, greyscale, ~2400x3500 px).  Our default PDF
# (patrologicursus53migngoog for PG 94) is a 1-bit scan in which some pages were
# thresholded too dark: letters are filled black and cannot be read by any model.
# With --source alt the page images come from the other copy.  The leaf numbers differ
# (other front matter, duplicated pages), so each PDF page is matched to an alt leaf by
# comparing the words of an earlier OCR run (--ref-lines) with the alt item's own OCR.
def ia_get(url, dest=None, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "pg-ocr/2.5 (research; kraken)"})
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if dest is not None:
                tmp = Path(str(dest) + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
            return data
        except Exception as e:          # network hiccup / rate limit -> wait and retry
            if k == tries - 1 or getattr(e, "code", None) == 404:      # 404: no point retrying
                raise
            print(f"[alt] retry {k + 1} for {url.rsplit('/', 1)[-1]}: {e}")
            time.sleep(5 * (k + 1))


def plain_words(text, min_len=7):
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("ς", "σ")
    return set(re.findall(r"[α-ω]{%d,}" % min_len, t))


def alt_prefix(args):
    return args.alt_prefix or f"Patrologia Graeca Vol. {args.vol:03d}"


def build_altmap(args, pages, work):
    """PDF page -> leaf number in the alternative scan (cached in work/altmap.json).

    Every page of the reference run is matched (not only the requested ones), so a
    page that cannot be matched itself (over-inked, no Greek) is interpolated from its
    direct neighbours on both sides.
    """
    MAP_VERSION = 3
    mf = work / "altmap.json"
    amap = json.loads(mf.read_text()) if mf.exists() else {}
    if amap.get("_version") == MAP_VERSION and all(str(p) in amap for p in pages):
        return {int(k): v for k, v in amap.items() if not k.startswith("_")}
    work.mkdir(parents=True, exist_ok=True)
    cache = args.root / "data" / "alt" / f"PG{args.vol:03d}"
    cache.mkdir(parents=True, exist_ok=True)
    pre = alt_prefix(args)
    q = urllib.parse.quote(pre)
    st, pi = cache / "searchtext.txt.gz", cache / "pageindex.json.gz"
    for f, suffix in ((st, "_hocr_searchtext.txt.gz"), (pi, "_hocr_pageindex.json.gz")):
        if not f.exists():
            print(f"[alt] downloading {pre}{suffix}")
            ia_get(f"{IA}/{args.alt_item}/{q}{suffix}", f)
    text = gzip.decompress(st.read_bytes()).decode("utf-8", "replace")
    index = json.loads(gzip.decompress(pi.read_bytes()))
    leaf_words = [plain_words(text[a[0]:a[1]]) for a in index]

    ref = collections.defaultdict(set)
    if args.ref_lines and args.ref_lines.exists():
        for row in args.ref_lines.read_text(encoding="utf-8").splitlines()[1:]:
            f = row.split("\t")
            if len(f) >= 5 and float(f[3]) >= 0.9:
                ref[int(f[0])] |= plain_words(f[4])
    else:
        sys.exit(f"[alt] reference OCR {args.ref_lines} not found - run the normal source first "
                 f"(it is needed to find the matching pages of the other scan)")

    found = {}
    for p in sorted(ref):
        w = ref[p]
        if len(w) < 8:
            continue
        sc = [len(w & lw) for lw in leaf_words]
        best = max(sc)
        if best >= max(4, 0.12 * len(w)):
            # the alt scan contains some pages twice: keep all near-equal candidates
            found[p] = [i for i, v in enumerate(sc) if v >= 0.9 * best]
    if not found:
        sys.exit("[alt] no page could be matched - wrong --alt-prefix?")
    first = {p: c[0] - p for p, c in found.items()}
    matched = sorted(found)
    result = {}
    for p in [p for p in pages if p >= EXTRA_BASE]:
        result[p] = {"leaf": p - EXTRA_BASE, "how": "extra"}
    for p in sorted(set(p for p in pages if p < EXTRA_BASE) | set(found)):
        near = sorted(matched, key=lambda x: abs(x - p))[:7]
        local = sorted(first[x] for x in near)[len(near) // 2]
        if p in found:
            leaf = min(found[p], key=lambda c: abs((c - p) - local))
            result[p] = {"leaf": leaf, "how": "matched"}
    # a page the reference run skipped as a second scan (PG 94: p483 = p481) gets the
    # leaf of its original, so it is recognised as a duplicate again
    ref_dups = {}
    sf = args.ref_lines.parent / "summary.json"
    if sf.exists():
        for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
            a, b = d.split(" = ")
            ref_dups[int(a[1:])] = int(b[1:])
    for p, orig in ref_dups.items():
        if orig in result:
            result[p] = {"leaf": result[orig]["leaf"], "how": f"duplicate of p{orig}"}
    for p in pages:
        if p in result:
            continue
        before = [x for x in matched if x < p]
        after = [x for x in matched if x > p]
        ob = result[before[-1]]["leaf"] - before[-1] if before else None
        oa = result[after[0]]["leaf"] - after[0] if after else None
        off = ob if ob is not None else oa
        result[p] = {"leaf": p + off, "how": "interpolated" + ("" if ob == oa else " (uncertain)")}
    old = amap if amap.get("_version") == MAP_VERSION else {}
    amap = dict(old)                    # keep pages mapped in earlier calls
    amap.update({str(k): v for k, v in result.items()})
    amap["_version"] = MAP_VERSION
    mf.write_text(json.dumps(amap, indent=1))
    req = [result[p] for p in pages]
    n_int = sum(v["how"].startswith("interpolated") for v in req)
    print(f"[alt] page map: {len(req) - n_int} matched, {n_int} interpolated -> {mf}", flush=True)
    for p in pages:
        if "uncertain" in result[p]["how"]:
            print(f"[alt]   p{p} -> leaf {result[p]['leaf']} is a guess (offset changes here) - check the preview")
    return {int(k): v for k, v in amap.items() if not k.startswith("_")}


def alt_image(args, leaf):
    """One leaf of the second scan as a greyscale page image (cached as data/alt/PGxxx/leaf_NNNN.jpg).

    The page images of a volume sit in "<prefix>_jp2.tar" (PG 94) or "<prefix>_jp2.zip"
    (other uploads); the first form that answers is remembered for the rest of the run.
    """
    from PIL import Image
    import urllib.error
    cache = args.root / "data" / "alt" / f"PG{args.vol:03d}"
    f = cache / f"leaf_{leaf:04d}.jpg"
    if not f.exists():
        pre = alt_prefix(args)
        inner = urllib.parse.quote(f"{pre}_jp2/{pre}_{leaf:04d}.jp2", safe="")
        kinds = [args._jp2_kind] if getattr(args, "_jp2_kind", None) else ["tar", "zip"]
        for kind in kinds:
            try:
                ia_get(f"{IA}/{args.alt_item}/{urllib.parse.quote(pre)}_jp2.{kind}/{inner}&ext=jpg", f)
                args._jp2_kind = kind
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        else:
            if getattr(args, "_jp2_kind", None):
                raise SystemExit(f"[alt] leaf {leaf} of {pre} not found in the second scan")
            # neither form exists: show what the item has for this volume
            names = []
            try:
                meta = json.loads(ia_get(f"https://archive.org/metadata/{args.alt_item}/files"))
                names = [x["name"] for x in meta.get("result", []) if x["name"].startswith(pre)]
            except Exception as e:
                names = [f"(file list not available: {e})"]
            raise SystemExit(f"[alt] no page images for {pre!r} in {args.alt_item} (tried _jp2.tar and _jp2.zip).\n"
                             f"Files of this volume in the item:\n  " + "\n  ".join(names or ["(none)"]))
        time.sleep(args.alt_delay)
    img = Image.open(f).convert("L")
    h = args.target_height
    return img.resize((round(img.width * h / img.height), h), Image.LANCZOS)


def stroke_width(bw):
    """Median length of horizontal ink runs (px) of a black/white image."""
    import numpy as np
    a = np.asarray(bw) < 128
    if not a.any():
        return 0.0
    d = np.diff(np.pad(a.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    runs = np.where(d == -1)[1] - np.where(d == 1)[1]
    return float(np.median(runs))


def drop_nested(boxes, inside=0.8, covered=0.8):
    """Greek boxes lying inside another Greek box would be read twice.

    If the inner boxes fill most of the outer box (it is a weak box spanning several
    columns, e.g. PG 94 p.444), the outer box is dropped; otherwise the inner ones.
    """
    drop = set()
    for i, outer in enumerate(boxes):
        inner = [j for j, b in enumerate(boxes) if j != i and cover(b["box"], outer["box"]) > inside]
        if not inner:
            continue
        o = outer["box"]
        spans = sorted((max(o[1], boxes[j]["box"][1]), min(o[3], boxes[j]["box"][3])) for j in inner)
        filled, end = 0, o[1]
        for y0, y1 in spans:
            y0 = max(y0, end)
            if y1 > y0:
                filled += y1 - y0
                end = y1
        if filled / max(1, o[3] - o[1]) >= covered:
            drop.add(i)
        else:
            drop.update(inner)
    return [b for k, b in enumerate(boxes) if k not in drop]


# ----------------------------------------------------------------- stage 1: layout
def stage_layout(args, pages, work):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    import numpy as np
    from PIL import Image, ImageDraw
    from ultralytics import YOLO
    from kraken.binarization import nlbin

    crops_dir = work / "crops"
    prev_dir = work / "previews"
    crops_dir.mkdir(parents=True, exist_ok=True)
    prev_dir.mkdir(parents=True, exist_ok=True)
    layout_file = work / "layout.jsonl"
    done = set()
    if layout_file.exists():
        for line in layout_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["page"])
    if args.source == "alt" and done:
        altmap = build_altmap(args, pages, work)
        recs = [json.loads(l) for l in layout_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        req = set(pages)                # only pages of this run can be redone
        stale = {r["page"] for r in recs if r["page"] in req and r["page"] in altmap
                 and r.get("source") != f"alt leaf {altmap[r['page']]['leaf']}"}
        if stale:
            print(f"[layout] page map changed for {sorted(stale)} -> these pages are redone")
            layout_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                           for r in recs if r["page"] not in stale), encoding="utf-8")
            for p in stale:
                for f in crops_dir.glob(f"p{p:04d}_c*.*"):
                    f.unlink()
            done -= stale
    todo = [p for p in pages if p not in done]
    print(f"[layout] {len(pages)} pages requested, {len(done & set(pages))} already done, {len(todo)} to do")
    if not todo:
        return

    model = YOLO(str(args.layout_model))
    names = model.names
    doc = fitz.open(str(args.pdf))
    altmap = build_altmap(args, todo, work) if args.source == "alt" else {}
    t0 = time.time()
    with open(layout_file, "a", encoding="utf-8") as out:
        for i, pno in enumerate(todo, 1):
            if args.source == "alt":
                img = alt_image(args, altmap[pno]["leaf"])
            else:
                page = doc[pno - 1]
                zoom = args.target_height / page.rect.height
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
                img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            rgb = np.stack([np.asarray(img)] * 3, axis=-1)

            res = model.predict(rgb, conf=args.layout_conf, device=args.yolo_device, verbose=False)[0]
            dets = []
            for xyxy, c, cf in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()):
                dets.append({"cls": names[int(c)], "conf": round(float(cf), 3),
                             "box": [int(round(v)) for v in xyxy]})
            latin = [d for d in dets if d["cls"] == LATIN_CLASS]
            greek, rejected = [], []
            for d in dets:
                if d["cls"] != GREEK_CLASS:
                    continue
                w = d["box"][2] - d["box"][0]
                if w > args.max_width_frac * img.width:
                    # full-width bands are Latin text running across both columns
                    d["why"] = "full width (Latin crossing text)"
                    rejected.append(d)
                elif d["conf"] < args.greek_conf and any(
                        lt["conf"] > d["conf"] and cover(d["box"], lt["box"]) > 0.8 for lt in latin):
                    # weak 'Greek' guess lying (almost) entirely inside a stronger Latin box
                    d["why"] = "inside a Latin column"
                    rejected.append(d)
                else:
                    # narrow boxes with low confidence are usually short Greek pieces
                    # next to Latin crossing text (e.g. the first lines of a column)
                    greek.append(d)
            greek = order_columns(drop_nested(dedupe(greek)), img.width)

            kept = []
            for k, d in enumerate(greek, 1):
                x0, y0, x1, y1 = d["box"]
                x0, y0 = max(0, x0 - args.pad_x), max(0, y0 - args.pad_y)
                x1, y1 = min(img.width, x1 + args.pad_x), min(img.height, y1 + args.pad_y)
                name = f"p{pno:04d}_c{k}"
                crop = img.crop((x0, y0, x1, y1))
                if args.binarize:
                    # faded grey scan areas -> clean black/white like the training data
                    crop = nlbin(crop).convert("L")
                # thick strokes = over-inked scan (letters filled in); ~6 px is normal
                sw = stroke_width(crop if args.binarize else crop.point(lambda v: 0 if v < 128 else 255))
                if crop.height < args.min_seg_height:
                    # kraken's line segmenter rescales every image to ~1800 px height;
                    # a short block would be blown up several times and split into
                    # word fragments -> put it on a white canvas of normal height
                    canvas = Image.new("L", (crop.width, args.min_seg_height), 255)
                    canvas.paste(crop, (0, 0))
                    crop = canvas
                crop.save(crops_dir / f"{name}.png")
                kept.append({"crop": name, "box": [x0, y0, x1, y1], "conf": d["conf"], "stroke": sw})

            # small preview for visual checking
            scale = 1000.0 / img.height
            pv = img.convert("RGB").resize((int(img.width * scale), 1000))
            dr = ImageDraw.Draw(pv)
            for d in dets:
                col = PREVIEW_COLOURS.get(d["cls"], (150, 150, 150))
                b = [v * scale for v in d["box"]]
                dr.rectangle(b, outline=col, width=1)
            for d in rejected:
                dr.rectangle([v * scale for v in d["box"]], outline=(255, 140, 0), width=3)
            for k in kept:
                dr.rectangle([v * scale for v in k["box"]], outline=(0, 170, 0), width=3)
            pv.save(prev_dir / f"p{pno:04d}.jpg", quality=80)

            rec = {"page": pno, "size": [img.width, img.height], "greek": kept,
                   "source": (f"alt leaf {altmap[pno]['leaf']}" if altmap else "pdf"),
                   "rejected_greek": rejected, "detections": dets}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"[layout] {i}/{len(todo)} pages  ({el / i:.1f} s/page)  last: p{pno} -> {len(kept)} Greek column(s)")


# ----------------------------------------------------------------- stage 2: kraken
def xml_complete(path):
    """True if kraken finished writing this PageXML (an interrupted write is redone)."""
    try:
        if path.stat().st_size < 200:
            return False
        with open(path, "rb") as fh:
            fh.seek(-200, 2)
            return b"</PcGts>" in fh.read()
    except OSError:
        return False

def stage_ocr(args, pages, work):
    crops_dir = work / "crops"
    page_set = set(pages)
    crops = sorted(c for c in crops_dir.glob("p*_c*.png") if int(c.stem[1:].split("_c")[0]) in page_set)
    todo = [c for c in crops if not xml_complete(c.with_suffix(".xml"))]
    print(f"[ocr] {len(crops)} column images, {len(todo)} still to recognise")
    t0 = time.time()
    for i in range(0, len(todo), args.chunk):
        chunk = todo[i:i + args.chunk]
        cmd = ["kraken", "-d", args.device, "-x"]
        for c in chunk:
            cmd += ["-i", str(c), str(c.with_suffix(".xml"))]
        cmd += ["segment", "-bl", "ocr", "-m", str(args.model), "-B", str(args.ocr_batch)]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"[ocr] kraken returned {r.returncode} for chunk starting {chunk[0].name}", file=sys.stderr)
        n = min(i + args.chunk, len(todo))
        el = time.time() - t0
        print(f"[ocr] {n}/{len(todo)} columns  ({el / max(n, 1):.1f} s/column)")
    missing = [c.name for c in crops if not xml_complete(c.with_suffix(".xml"))]
    if missing:
        print(f"[ocr] WARNING: {len(missing)} column(s) failed: {missing[:5]} ...")


# ----------------------------------------------------------------- stage 3: text
def read_lines(xml_path):
    from lxml import etree
    tree = etree.parse(str(xml_path))
    lines = []
    for tl in tree.iterfind(".//{*}TextLine"):
        txt, conf, x, y = "", 0.0, 0.0, 0.0
        eqs = tl.findall("{*}TextEquiv")          # direct children only (not words)
        if eqs:
            txt = eqs[-1].findtext("{*}Unicode") or ""
            conf = float(eqs[-1].get("conf", 0) or 0)
        bl = tl.find("{*}Baseline")
        if bl is not None and bl.get("points"):
            pts = [tuple(map(float, p.split(","))) for p in bl.get("points").split()]
            x = sum(p[0] for p in pts) / len(pts)
            y = sum(p[1] for p in pts) / len(pts)
        txt = unicodedata.normalize("NFC", txt).strip()
        words = []
        for w in tl.findall("{*}Word"):
            we = w.findall("{*}TextEquiv")
            if we:
                wt = unicodedata.normalize("NFC", we[-1].findtext("{*}Unicode") or "").strip()
                if wt:
                    words.append([wt, round(float(we[-1].get("conf", 0) or 0), 4)])
        if txt:
            lines.append((txt, conf, x, y, words))
    return lines


def join_hyphens(lines):
    out, buf = [], ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if buf:
            ln = buf + ln
            buf = ""
        if ln.endswith("-") and len(ln) > 1 and ln[-2].isalpha():
            buf = ln[:-1]
        else:
            out.append(ln)
    if buf:
        out.append(buf)
    return out


def stage_text(args, pages, work, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    layout = {}
    lf = work / "layout.jsonl"
    if lf.exists():
        for line in lf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                layout[r["page"]] = r
    vol = args.vol
    tag = f"PG{vol:03d}"
    all_pages = sorted(layout)          # whole volume processed so far, in page order
    txt_parts, tsv_rows, reading = [], ["page\tcolumn\tline\tconf\ttext"], []
    suspect = ["page\tcolumn\tconf\treason\ttext"]
    word_rows = []
    n_lines = n_chars = 0
    no_greek, failed = [], []
    page_conf = {}
    fragmented, heavy, duplicates = [], [], []
    recent = []                          # word sets of the last pages (duplicate scans)
    excluded = getattr(args, "excluded", set())
    skipped_excl = [p for p in all_pages if p in excluded]
    all_pages = [p for p in all_pages if p not in excluded]
    for pno in all_pages:
        rec = layout[pno]
        if not rec["greek"]:
            no_greek.append(pno)
            continue
        # the same page scanned twice (e.g. PG 94 p.483-484 = p.481-482) -> keep once
        words = set()
        for g in drop_nested(rec["greek"]):
            xml = work / "crops" / f"{g['crop']}.xml"
            if xml_complete(xml):
                words |= {t for l in read_lines(xml) if l[1] >= 0.9 for t in l[0].split()}
        dup_of = next((q for q, w in recent
                       if words and len(words & w) / len(words | w) > args.dup_jaccard), None)
        recent = (recent + [(pno, words)])[-4:]
        if dup_of is not None:
            duplicates.append(f"p{pno} = p{dup_of}")
            continue
        line_no = 1
        page_lines = []
        width = rec["size"][0]
        bands = [d["box"] for d in rec.get("rejected_greek", []) if d.get("why", "").startswith("full width")]
        bands += [d["box"] for d in rec.get("detections", [])
                  if d["cls"] == LATIN_CLASS and d["box"][2] - d["box"][0] > 0.6 * width]
        # Latin columns and footnote blocks: a Greek box sometimes reaches into them
        notes = [d["box"] for d in rec.get("detections", []) if d["cls"] in NOTE_CLASSES]
        for g in drop_nested(rec["greek"]):       # older layouts may still contain nested boxes
            col_idx = int(g["crop"].rsplit("_c", 1)[1])
            if g.get("stroke", 0) >= args.heavy_stroke:
                heavy.append(f"{g['crop']} (stroke {g['stroke']:.0f})")
            xml = work / "crops" / f"{g['crop']}.xml"
            if not xml_complete(xml):
                failed.append(g["crop"])
                continue
            good = []
            col_lines = read_lines(xml)
            # (short paragraph ends of 2-4 lines are normal, not fragmentation)
            if len(col_lines) >= 5 and sum(len(l[0]) < 6 for l in col_lines) / len(col_lines) > 0.3:
                fragmented.append(g["crop"])
            for txt, conf, x, y, words in col_lines:
                page_x, page_y = g["box"][0] + x, g["box"][1] + y
                in_band = any(b[1] <= page_y <= b[3] for b in bands)
                in_notes = any(b[0] <= page_x <= b[2] and b[1] <= page_y <= b[3] for b in notes)
                if conf < args.drop_conf:
                    # very uncertain: usually Latin or noise read as Greek -> kept aside
                    suspect.append(f"{pno}\t{col_idx}\t{conf:.3f}\tlow confidence\t{txt}")
                elif in_band and conf < args.band_conf:
                    # line sits in a Latin text band running across the page
                    suspect.append(f"{pno}\t{col_idx}\t{conf:.3f}\tin Latin band\t{txt}")
                elif in_notes and conf < args.band_conf:
                    # line lies in a Latin column / footnote block (Latin read as Greek)
                    suspect.append(f"{pno}\t{col_idx}\t{conf:.3f}\tin Latin/notes region\t{txt}")
                else:
                    good.append((txt, conf, words))
            if not good:
                continue
            txt_parts.append(f"$0={vol} $8={pno} $9={line_no}")
            for j, (l, cf, ws) in enumerate(good):
                txt_parts.append(l)
                tsv_rows.append(f"{pno}\t{col_idx}\t{line_no + j}\t{cf:.3f}\t{l}")
                word_rows.append(json.dumps({"page": pno, "col": col_idx, "line": line_no + j,
                                             "conf": round(cf, 4), "words": ws}, ensure_ascii=False))
                page_conf.setdefault(pno, []).append(cf)
            lines = [l for l, _, _ in good]
            # uncertain lines are marked in the reading text so they can be checked
            page_lines += [(args.mark + l) if cf < args.mark_conf else l for l, cf, _ in good]
            line_no += len(lines)
            n_lines += len(lines)
            n_chars += sum(len(l) for l in lines)
        if page_lines:
            reading.append(f"[{tag} p.{pno}]")
            reading += join_hyphens(page_lines)
    (outdir / f"{tag}_text.txt").write_text("\n".join(txt_parts) + "\n", encoding="utf-8")
    (outdir / f"{tag}_lines.tsv").write_text("\n".join(tsv_rows) + "\n", encoding="utf-8")
    (outdir / f"{tag}_reading.txt").write_text("\n".join(reading) + "\n", encoding="utf-8")
    (outdir / f"{tag}_words.jsonl").write_text("\n".join(word_rows) + "\n", encoding="utf-8")
    (outdir / f"{tag}_suspect.tsv").write_text("\n".join(suspect) + "\n", encoding="utf-8")
    means = {p: sum(v) / len(v) for p, v in page_conf.items()}
    weak_pages = sorted((p for p, m in means.items() if m < args.weak_page_conf), key=lambda p: means[p])
    summary = {
        "volume": vol, "pdf": str(args.pdf), "model": str(args.model),
        "pages_processed": len(all_pages), "pages_excluded": len(skipped_excl),
        "pages_without_greek_column": len(no_greek),
        "greek_columns": sum(len(layout[p]["greek"]) for p in all_pages),
        "columns_failed_ocr": len(failed), "lines": n_lines, "characters": n_chars,
        "lines_set_aside_low_conf": len(suspect) - 1,
        "columns_fragmented": fragmented[:100],
        "columns_heavy_ink": heavy[:200],
        "duplicate_pages_skipped": duplicates,
        "lines_marked_uncertain": sum(1 for r in tsv_rows[1:] if float(r.split("\t")[3]) < args.mark_conf),
        "mean_line_conf": round(sum(means.values()) / max(1, len(means)), 4),
        "pages_to_check_low_conf": [f"p{p} ({means[p]:.3f})" for p in weak_pages[:100]],
        "pages_without_greek_list": no_greek[:200],
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[text] {n_lines} lines, {n_chars} characters -> {outdir}")
    print(json.dumps({k: v for k, v in summary.items() if k != 'pages_without_greek_list'}, indent=2, ensure_ascii=False))


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--pages", default="all", help="e.g. 500-511,700 or all (PDF page numbers, 1-based)")
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--model", type=Path, required=True, help="recognition model (.safetensors)")
    ap.add_argument("--layout-model", type=Path, default=None)
    ap.add_argument("--target-height", type=int, default=3300,
                    help="page height in px after rendering (training pages were ~3150-3300 px)")
    ap.add_argument("--layout-conf", type=float, default=0.25)
    ap.add_argument("--greek-conf", type=float, default=0.60,
                    help="below this a Greek box is dropped only if it lies inside a stronger Latin box")
    ap.add_argument("--max-width-frac", type=float, default=0.60,
                    help="reject 'Greek' boxes wider than this share of the page (Latin crossing text)")
    ap.add_argument("--pad-x", type=int, default=4, help="horizontal padding (keeps margin letters A-D out)")
    ap.add_argument("--pad-y", type=int, default=12)
    ap.add_argument("--min-seg-height", type=int, default=1800,
                    help="shorter column images are padded with white to this height before segmentation")
    ap.add_argument("--no-binarize", dest="binarize", action="store_false",
                    help="skip kraken nlbin binarisation of the column images")
    ap.add_argument("--tag", default="v4", help="version folder for work/output (keeps earlier test runs)")
    ap.add_argument("--drop-conf", type=float, default=0.60,
                    help="lines below this recognition confidence go to _suspect.tsv instead of the text")
    ap.add_argument("--band-conf", type=float, default=0.85,
                    help="lines inside a full-width Latin band are set aside below this confidence")
    ap.add_argument("--weak-page-conf", type=float, default=0.93,
                    help="pages whose mean line confidence is below this are listed for checking")
    ap.add_argument("--source", choices=["pdf", "alt"], default="pdf",
                    help="pdf = --pdf file; alt = second scan in the Internet Archive item --alt-item")
    ap.add_argument("--alt-item", default="PatrologiaGraeca")
    ap.add_argument("--alt-prefix", default=None, help='default "Patrologia Graeca Vol. 094"')
    ap.add_argument("--alt-delay", type=float, default=1.0, help="pause between image downloads (s)")
    ap.add_argument("--ref-lines", type=Path, default=None,
                    help="lines.tsv of an earlier run, used to match pages (default output/PGxxx/v4)")
    ap.add_argument("--heavy-stroke", type=float, default=8.0,
                    help="columns whose median stroke width (px) is at least this are reported as over-inked")
    ap.add_argument("--dup-jaccard", type=float, default=0.6,
                    help="a page whose words overlap this much with one of the 3 previous pages is a duplicate scan")
    ap.add_argument("--mark-conf", type=float, default=0.80,
                    help="lines below this confidence are marked in the reading text")
    ap.add_argument("--mark", default="⟦?⟧ ", help="marker put before uncertain lines in the reading text")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--yolo-device", default="0")
    ap.add_argument("--ocr-batch", type=int, default=8)
    ap.add_argument("--chunk", type=int, default=40, help="column images per kraken call")
    ap.add_argument("--stages", default="layout,ocr,text")
    args = ap.parse_args()
    if args.layout_model is None:
        args.layout_model = args.root / "models" / "REG-YOLOv12s.pt"

    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    n_pages = len(fitz.open(str(args.pdf)))
    pages = parse_pages(args.pages, n_pages)
    tag = f"PG{args.vol:03d}"
    args.excluded = excluded_pages(args.root, tag)
    if args.excluded:
        before = len(pages)
        pages = [p for p in pages if p not in args.excluded]
        print(f"{before - len(pages)} page(s) skipped as listed in work/{tag}/exclude_pages.txt")
        if not pages:
            raise SystemExit("all requested pages are excluded")
    if args.ref_lines is None:
        args.ref_lines = args.root / "output" / tag / "v4" / f"{tag}_lines.tsv"
    work = args.root / "work" / tag / args.tag
    outdir = args.root / "output" / tag / args.tag
    print(f"pg_ocr_volume.py version {VERSION}")
    print(f"{tag}: {n_pages} PDF pages, processing {len(pages)} ({pages[0]}-{pages[-1]}) -> work/{tag}/{args.tag}"
          f"  [image source: {args.source}{' / ' + args.alt_item if args.source == 'alt' else ''}]")
    stages = set(args.stages.split(","))
    if "layout" in stages:
        stage_layout(args, pages, work)
    if "ocr" in stages:
        stage_ocr(args, pages, work)
    if "text" in stages:
        stage_text(args, pages, work, outdir)


if __name__ == "__main__":
    main()
