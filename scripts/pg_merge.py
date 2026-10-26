"""
Combine two OCR runs of the same volume (e.g. v4 = PDF scan, v5 = second scan).

1. Page level: for every page the run with the higher mean line confidence is the
   base (it must have at least --min-share of the lines of the other run, so a run
   that lost a column cannot win just because its remaining lines are clean).
2. Word level: each base line is paired with the matching line of the other run.
   Where the two readings differ, the word with the higher recognition confidence
   is taken (needs PGxxx_words.jsonl, written by pg_ocr_volume.py >= 2.6;
   without it whole lines are compared).
3. Pages scanned twice (same text as one of the 3 previous pages) are left out.

    python pg_merge.py --vol 94 --tags v4,v5          -> output/PG094/best/

Outputs: PG094_lines.tsv, PG094_reading.txt, PG094_text.txt,
         merge_report.tsv (page, base run, words taken from the other run), summary.json
"""
import argparse
import collections
import difflib
import json
import unicodedata
from pathlib import Path

VERSION = "2.3 (word-level combination; different pages and false copies detected)"


def load(outdir, tag):
    pages = collections.defaultdict(list)
    wf = outdir / f"{tag}_words.jsonl"
    if wf.exists():
        for row in wf.read_text(encoding="utf-8").splitlines():
            if row.strip():
                r = json.loads(row)
                words = [(w, c) for w, c in r["words"]] or [(t, r["conf"]) for t in []]
                text = " ".join(w for w, _ in words)
                pages[r["page"]].append({"col": r["col"], "line": r["line"], "conf": r["conf"],
                                         "text": text, "words": words})
        return pages, True
    for row in (outdir / f"{tag}_lines.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        f = row.split("\t")
        if len(f) >= 5:
            cf = float(f[3])
            pages[int(f[0])].append({"col": int(f[1]), "line": int(f[2]), "conf": cf, "text": f[4],
                                     "words": [(w, cf) for w in f[4].split()]})
    return pages, False


def key(s):
    """Comparison form: no accents/breathings, lower case (alignment only)."""
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def grams(s, n=3):
    s = f" {s} "
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def pair_lines(a, b, min_sim=0.3):
    """Order-preserving pairing of two line lists (global alignment on trigram
    similarity) -> {i: j}.  Lines without a counterpart stay unpaired."""
    ga = [grams(key(l["text"])) for l in a]
    gb = [grams(key(l["text"])) for l in b]
    n, m = len(a), len(b)
    sim = [[(len(x & y) / len(x | y)) if x and y else 0.0 for y in gb] for x in ga]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(score[i + 1][j], score[i][j + 1])
            if sim[i][j] >= min_sim:
                best = max(best, sim[i][j] + score[i + 1][j + 1])
            score[i][j] = best
    pairs, i, j = {}, 0, 0
    while i < n and j < m:
        if sim[i][j] >= min_sim and abs(score[i][j] - (sim[i][j] + score[i + 1][j + 1])) < 1e-9:
            pairs[i] = j
            i, j = i + 1, j + 1
        elif score[i][j] == score[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


FREQ = collections.Counter()
PUNCT = "·.,;:!?()[]«»\"'´`-—"


def norm(w):
    return w.strip(PUNCT)


def grave_to_acute(w):
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", w).replace("\u0300", "\u0301"))


def better(x, y):
    """True if reading y should replace x.  Normally the higher recognition
    confidence wins.  Exception: if one form is frequent in the volume and the other
    (similar-looking) form occurs at most twice, the frequent one wins - OCR errors
    are rarely repeated.  Grave/acute differences are left to the confidence (they
    depend on the following word)."""
    nx, ny = norm(x[0]), norm(y[0])
    if nx != ny and grave_to_acute(nx) != grave_to_acute(ny) \
            and difflib.SequenceMatcher(None, key(nx), key(ny)).ratio() >= 0.6:
        fx, fy = FREQ[nx], FREQ[ny]
        if fy >= 3 * fx + 2 and fx <= 2:
            return True
        if fx >= 3 * fy + 2 and fy <= 2:
            return False
    return y[1] > x[1]


def merge_words(wa, wb, min_insert=0.95):
    """Word-by-word choice by frequency / confidence; returns (words, number taken from b)."""
    sm = difflib.SequenceMatcher(None, [w for w, _ in wa], [w for w, _ in wb], autojunk=False)
    out, taken = [], 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        A, B = wa[i1:i2], wb[j1:j2]
        if op == "equal":
            out += [(w, max(c, B[k][1])) for k, (w, c) in enumerate(A)]
        elif op == "replace" and len(A) == len(B):
            for x, y in zip(A, B):
                if better(x, y):
                    out.append(y)
                    taken += 1
                else:
                    out.append(x)
        elif op == "replace":
            ma = sum(c for _, c in A) / len(A)
            mb = sum(c for _, c in B) / len(B)
            if mb > ma:
                out += B
                taken += len(B)
            else:
                out += A
        elif op == "delete":
            out += A
        elif op == "insert":
            # a word only the other scan has (e.g. a lost paragraph initial)
            if all(c >= min_insert for _, c in B):
                out += B
                taken += len(B)
    return out, taken


def join_hyphens(lines):
    out, buf = [], ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if buf:
            ln, buf = buf + ln, ""
        if ln.endswith("-") and len(ln) > 1 and ln[-2].isalpha():
            buf = ln[:-1]
        else:
            out.append(ln)
    if buf:
        out.append(buf)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--tags", default="v4,v5", help="two runs to combine")
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--out-tag", default="best")
    ap.add_argument("--min-share", type=float, default=0.85)
    ap.add_argument("--dup-jaccard", type=float, default=0.6)
    ap.add_argument("--min-add-conf", type=float, default=0.90,
                    help="a line only the other run has is added if its confidence is at least this")
    ap.add_argument("--mark-conf", type=float, default=0.80)
    ap.add_argument("--mark", default="⟦?⟧ ")
    args = ap.parse_args()

    tag = f"PG{args.vol:03d}"
    tags = args.tags.split(",")
    if len(tags) != 2:
        raise SystemExit("give exactly two runs, e.g. --tags v4,v5")
    runs, has_words = {}, {}
    for t in tags:
        d = args.root / "output" / tag / t
        if not (d / f"{tag}_lines.tsv").exists():
            raise SystemExit(f"missing {d / (tag + '_lines.tsv')}")
        runs[t], has_words[t] = load(d, tag)
        if not has_words[t]:
            print(f"note: {t} has no {tag}_words.jsonl (re-run its text stage with script >= 2.6 "
                  f"for word-level merging) - whole lines are compared there")

    # word frequencies of the whole volume (both runs, confident words only)
    for t in tags:
        for lines in runs[t].values():
            for l in lines:
                FREQ.update(norm(w) for w, c in l["words"] if c >= 0.9)

    # pages a run already recognised as a second scan of an earlier page
    known_dups = {}
    for t in tags:
        sf = args.root / "output" / tag / t / "summary.json"
        if sf.exists():
            for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
                a, b = d.split(" = ")
                known_dups[int(a[1:])] = int(b[1:])

    outdir = args.root / "output" / tag / args.out_tag
    outdir.mkdir(parents=True, exist_ok=True)
    tsv, txt, reading = ["page\tcolumn\tline\tconf\ttext"], [], []
    report = ["page\tbase\t" + "\t".join(f"{t}_lines\t{t}_conf" for t in tags) + "\tlines_paired\twords_from_other\tlines_added_from_other"]
    wins, recent, dups = collections.Counter(), [], []
    total_taken = total_added = 0
    different, page_words_of = [], {}
    for p in sorted(set(runs[tags[0]]) | set(runs[tags[1]])):
        stats = {t: (len(runs[t].get(p, [])),
                     sum(l["conf"] for l in runs[t].get(p, [])) / max(1, len(runs[t].get(p, []))))
                 for t in tags}
        most = max(n for n, _ in stats.values())
        ok = [t for t in tags if stats[t][0] >= args.min_share * most]
        base = max(ok, key=lambda t: stats[t][1])
        other = tags[1] if base == tags[0] else tags[0]
        A, B = runs[base].get(p, []), runs[other].get(p, [])
        pairs = pair_lines(A, B) if B else {}
        if A and B and min(len(A), len(B)) >= 5 and len(pairs) < 0.4 * min(len(A), len(B)):
            # the two runs read different pages (the second scan was matched to the wrong
            # leaf): the main scan (first run) is the page itself, nothing is combined
            base, other = tags[0], tags[1]
            A, B, pairs = runs[base].get(p, []), [], {}
            different.append(p)
        merged, taken = [], 0
        for i, la in enumerate(A):
            if i in pairs:
                ws, n = merge_words(la["words"], B[pairs[i]]["words"])
                taken += n
                cf = sum(c for _, c in ws) / max(1, len(ws)) if n else la["conf"]
                merged.append([la["col"], cf, " ".join(w for w, _ in ws)])
            else:
                merged.append([la["col"], la["conf"], la["text"]])
        # lines that only the other scan has (a line the segmenter missed in the base
        # scan, e.g. PG 94 p.540): insert them after the line that precedes them there
        inv = {j: i for i, j in pairs.items()}
        inserts = collections.defaultdict(list)
        kA = [key(l["text"]) for l in A]
        last_i = -1
        for j, lb in enumerate(B):
            if j in inv:
                last_i = inv[j]
                continue
            if lb["conf"] < args.min_add_conf or len(lb["text"]) < 3:
                continue
            kb = key(lb["text"])
            if any(difflib.SequenceMatcher(None, kb, x, autojunk=False).ratio() >= 0.5 for x in kA):
                continue
            inserts[last_i].append(lb)
        added = sum(len(v) for v in inserts.values())
        if added:
            out = [[m[0], l["conf"], l["text"]] for l in inserts.get(-1, []) for m in merged[:1]]
            for i, m in enumerate(merged):
                out.append(m)
                out += [[m[0], l["conf"], l["text"]] for l in inserts.get(i, [])]
            merged = out
        total_added += added
        # renumber lines per column
        num, merged2 = collections.Counter(), []
        for c, cf, t in merged:
            num[c] += 1
            merged2.append((c, num[c], cf, t))
        merged = merged2
        # duplicate scans of the same page
        words = {w for _, _, c, s in merged if c >= 0.9 for w in s.split()}
        dup = next((q for q, w in recent if words and len(words & w) / len(words | w) > args.dup_jaccard), None)
        if dup is None and p in known_dups:
            # a run said 'copy of an earlier page': accept only if the texts agree
            q = known_dups[p]
            w = page_words_of.get(q, set())
            if words and w and len(words & w) / len(words | w) > 0.4:
                dup = q
        page_words_of[p] = words
        recent = (recent + [(p, words)])[-3:]
        if dup is not None:
            dups.append(f"p{p} = p{dup}")
            continue
        wins[base] += 1
        total_taken += taken
        report.append(f"{p}\t{base}\t" + "\t".join(f"{stats[t][0]}\t{stats[t][1]:.3f}" for t in tags)
                      + f"\t{len(pairs)}\t{taken}\t{added}")
        col = None
        for c, n, cf, s in merged:
            if c != col:
                txt.append(f"$0={args.vol} $8={p} $9={n}")
                col = c
            txt.append(s)
            tsv.append(f"{p}\t{c}\t{n}\t{cf:.3f}\t{s}")
        reading.append(f"[{tag} p.{p}]")
        reading += join_hyphens([(args.mark + s) if cf < args.mark_conf else s for _, _, cf, s in merged])

    (outdir / f"{tag}_lines.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    (outdir / f"{tag}_text.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    (outdir / f"{tag}_reading.txt").write_text("\n".join(reading) + "\n", encoding="utf-8")
    (outdir / "merge_report.tsv").write_text("\n".join(report) + "\n", encoding="utf-8")
    confs = [float(r.split("\t")[3]) for r in tsv[1:]]
    summary = {"version": VERSION, "runs": tags, "word_level": all(has_words.values()),
               "pages": sum(wins.values()), "base_run_per_page": dict(wins),
               "words_taken_from_other_run": total_taken,
               "lines_added_from_other_run": total_added,
               "pages_read_differently_by_the_runs": different, "duplicate_pages_skipped": dups,
               "lines": len(confs), "mean_line_conf": round(sum(confs) / max(1, len(confs)), 4),
               "lines_below_0.80": sum(c < 0.8 for c in confs),
               "lines_below_0.90": sum(c < 0.9 for c in confs)}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"-> {outdir}")


if __name__ == "__main__":
    main()
