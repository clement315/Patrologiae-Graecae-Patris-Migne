"""
Prepare the Calfa / CGPG ground truth (Zenodo v2) for kraken recognition training.

What it does
  1. reads every PageXML in data/zenodo/v2
  2. keeps only pages that actually contain transcribed lines
     (34 "PGxx_col_*" pages are layout-only -> listed separately for later)
  3. fixes the image link (158 grna pages point to a .tif that does not exist)
  4. Unicode-normalises every line to NFC
       -> unifies oxia/tonos (e.g. U+1F71 and U+03AC both become U+03AC),
          the main error source reported in the paper
     and collapses whitespace
  5. writes cleaned copies to work/gt/xml/ (originals are never modified)
  6. splits pages into train / val / test (fixed seed, stratified by source)
  7. writes a character inventory (work/gt/charset.tsv) and a summary

Run inside WSL (kraken environment):
    python prepare_gt.py            # defaults to /mnt/e/PG_OCR
    python prepare_gt.py --root /mnt/e/PG_OCR --test-pages 30 --val-frac 0.1
"""
import argparse
import collections
import json
import random
import re
import unicodedata
from pathlib import Path

from lxml import etree

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
NS = {"p": PAGE_NS}
WS = re.compile(r"\s+")


def source_group(stem: str) -> str:
    if stem.startswith("grc_grna"):
        return "grna"          # Gregory of Nazianzus, Orations
    if stem.startswith("grc_tlg"):
        return "tlg"           # PG pages aligned with TLG text
    return "pgcol"             # full PG double-column pages (layout only)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return WS.sub(" ", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/mnt/e/PG_OCR")
    ap.add_argument("--test-pages", type=int, default=30)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(args.root)
    src = root / "data" / "zenodo" / "v2"
    out = root / "work" / "gt"
    xml_out = out / "xml"
    xml_out.mkdir(parents=True, exist_ok=True)

    pages = collections.defaultdict(list)   # group -> [(stem, n_lines)]
    layout_only = []
    chars = collections.Counter()
    changed_lines = 0
    total_lines = 0

    for xml in sorted(src.glob("*.xml")):
        stem = xml.stem
        img = src / f"{stem}.jpg"
        if not img.exists():
            print(f"  skip {xml.name}: image {img.name} missing")
            continue

        tree = etree.parse(str(xml))
        page = tree.find(".//p:Page", NS)
        page.set("imageFilename", str(img))          # absolute link -> kraken finds it

        n_text = 0
        for reg in tree.iterfind(".//p:TextRegion", NS):
            # unify odd region labels such as  structure {type:''}
            custom = reg.get("custom") or ""
            if "type:''" in custom or not custom:
                reg.set("custom", "structure {type:text;}")
            for line in reg.iterfind("p:TextLine", NS):
                uni = line.find("p:TextEquiv/p:Unicode", NS)
                raw = (uni.text if uni is not None else "") or ""
                if not raw.strip():
                    continue
                clean = normalise(raw)
                if clean != raw:
                    changed_lines += 1
                uni.text = clean
                chars.update(clean)
                n_text += 1
        total_lines += n_text

        if n_text == 0:
            layout_only.append(stem)
            continue
        tree.write(str(xml_out / xml.name), encoding="utf-8", xml_declaration=True)
        pages[source_group(stem)].append((stem, n_text))

    # ---- split (stratified by source group, page level -> no line leakage)
    rnd = random.Random(args.seed)
    n_all = sum(len(v) for v in pages.values())
    split = {"train": [], "val": [], "test": []}
    for group, items in sorted(pages.items()):
        items = sorted(items)
        rnd.shuffle(items)
        n_test = round(args.test_pages * len(items) / n_all)
        rest = items[n_test:]
        n_val = max(1, round(args.val_frac * len(rest)))
        split["test"] += items[:n_test]
        split["val"] += rest[:n_val]
        split["train"] += rest[n_val:]

    for name, items in split.items():
        with open(out / f"{name}.lst", "w", encoding="utf-8") as fh:
            for stem, _ in sorted(items):
                fh.write(str(xml_out / f"{stem}.xml") + "\n")
    with open(out / "layout_only.lst", "w", encoding="utf-8") as fh:
        fh.write("\n".join(str(src / f"{s}.xml") for s in layout_only) + "\n")

    # ---- character inventory
    with open(out / "charset.tsv", "w", encoding="utf-8") as fh:
        fh.write("codepoint\tchar\tcount\tname\n")
        for ch, n in chars.most_common():
            fh.write(f"U+{ord(ch):04X}\t{ch}\t{n}\t{unicodedata.name(ch, '?')}\n")

    summary = {
        "pages_with_text": n_all,
        "pages_by_source": {g: len(v) for g, v in pages.items()},
        "layout_only_pages": len(layout_only),
        "text_lines": total_lines,
        "lines_changed_by_normalisation": changed_lines,
        "distinct_characters": len(chars),
        "rare_characters(<5)": "".join(c for c, n in chars.items() if n < 5),
        "split_pages": {k: len(v) for k, v in split.items()},
        "split_lines": {k: sum(n for _, n in v) for k, v in split.items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
