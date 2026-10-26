# Development notes (October 2026)

Chronological notes on decisions, test runs and errors found while building the pipeline on PG 94.

## Environment (development machine: RTX 4050 Laptop, 6 GB)
- Windows: `E:\PG_OCR` (uv + Python 3.11, CPU torch, ultralytics, Calfa layout model `models\REG-YOLOv12s.pt`)
- WSL2 Ubuntu 24.04: `~/kraken-env` (kraken 7.x, CUDA torch, + ultralytics, PyMuPDF).
- Scripts in `E:\PG_OCR\scripts\`: `prepare_gt.py`, **`pg_train.sh`**, **`pg_ocr.sh` + `pg_ocr_volume.py` (v2.6) + `pg_merge.py` (2.2)**, **`notify.sh`** (Windows toast from WSL; both main scripts notify at the end, `NOTIFY=0` to switch off).

## Training (pg_train.sh)
- `bash /mnt/e/PG_OCR/scripts/pg_train.sh` (prepare → train → test), `--status`, `--resume`, `--new`, `--test`; watchdog (NaN / no learning) with one lr-3e-4 retry.
- **run_20261025_224654 (bf16-mixed): FAILED.**
- **run_20261025_233839 (batch 8, 32-true, warmup 1000, clip 1.0, lr 1e-3): current model** `best_0.9885.safetensors`. **Test CER 0.96 %, WER 4.66 %** (paper 1.05 % / 4.69 %).

## Volume recognition pipeline (pg_ocr.sh / pg_ocr_volume.py)
- `bash /mnt/e/PG_OCR/scripts/pg_ocr.sh 94 420-431` (or `all`). Resumable; finished stages are skipped.
- Steps: page image → ~3300 px gray → Calfa YOLO → Greek boxes → crop (pad x 4 / y 12) → nlbin binarisation → pad to ≥ 1800 px height → `kraken segment -bl ocr` → PageXML → text.
- Greek-box rule: reject if wider than 60 % of page or (conf < 0.6 AND ≥ 80 % inside a stronger Latin box); otherwise keep.
- Line rules: conf < 0.60 → `_suspect.tsv`; in a full-width Latin band and conf < 0.85 → suspect; **v2.5:** inside a Latin-column/footnote detection and conf < 0.85 → suspect ("in Latin/notes region").
- Titles are NOT read yet.

### Test results on PG 94 pp. 420–431 (tag v4 = v2.2)
- 23 columns, 0 failures, 415 lines, mean line conf 0.974.
- Remaining problems: italic Greek (scripture quotations), thin light print, paragraph-initial letter loss ('Ἐπὶ' → 'πὶ'), superscript footnote letters, stray ']', titles.

## Full run PG 94 pp. 414–634 (v4, script v2.4) – error analysis (2026-10-26)
- 221 pages, 409 columns, 0 OCR failures, 7,964 lines, 357,327 chars, mean line conf 0.967; 134 lines set aside.
- Lines < 0.80: 146; < 0.85: 253; < 0.90: 531 (these were still in the text).
- **Main error source = the scan, not the model.** The PDF (`patrologicursus53migngoog`) is 1-bit JBIG2 at 600 dpi. On ~23 columns (pp. 470–500 even pages, 444, 533, 615, 625) Google's threshold was too dark: strokes are 2× normal (median horizontal ink run ≥ 8 px at 3300 px page height, normal 5–7) and letter counters are filled. Erosion / thresholds cannot recover them. Stroke width separates bad from good columns almost perfectly.
- **Fix: second scan.** IA item `PatrologiaGraeca` has an independent Google scan of every volume ("Patrologia Graeca Vol. 094", other library copy, greyscale ~2380×3530, per-leaf JPG via `<prefix>_jp2.tar/<prefix>_jp2%2F<prefix>_NNNN.jp2&ext=jpg`). P. 533 is perfectly legible there. Leaf offsets vary (+62 … +100; the alt scan contains some pages twice) → pages are mapped by matching OCR words against the item's `_hocr_searchtext.txt.gz` + `_hocr_pageindex.json.gz` (PDF p. 522 = alt leaf 612, p. 533 = leaf 623).
- Other errors found:
  - **Duplicate scan:** PDF pp. 483–484 repeat pp. 481–482 → text appeared twice.
  - **Latin footnotes read as Greek:** p. 444 c2, ~31 lines.
  - The 4 "fragmented" columns (p467_c1, p548_c2, p588_c1, p606_c1) were false alarms (short paragraph ends).
  - Remaining model errors: italic scripture quotations, chapter headings (ΚΕΦ.), paragraph initials, accents/breathings (~1–2 % CER on clean pages).

## Script v2.5 (pg_ocr_volume.py) + pg_merge.py 1.0
- `SOURCE=alt RUN=v5 bash pg_ocr.sh 94 <pages>`: page images from the IA alt scan (cached in data/alt/PG094/, page map in work/PG094/v5/altmap.json; needs v4 lines as reference).
- Stroke width per column recorded (`stroke` in layout.jsonl); summary lists `columns_heavy_ink` (≥ 8 px).
- Duplicate pages (word Jaccard > 0.6 with one of the 3 previous pages) skipped → `duplicate_pages_skipped`.
- Fragment check only for columns with ≥ 5 lines.
- Lines with conf < 0.80 are marked `⟦?⟧` in the reading text.
- `bash pg_ocr.sh 94 merge v4,v5` → output/PG094/best (per page the run with higher mean conf; merge_report.tsv).

## Alt-scan test v5 (37 pages, 2026-10-26) and v2.6
- Over-inked pages fixed: p533 0.785 → 0.986, p494 0.839 → 0.983, p488/490/492/498 ~0.88 → 0.98; stroke 4–6 px on all alt columns. Overall merged lines < 0.80: 146 → 92.
- On clean pages the alt scan is not better (p499 v4 better, p539 v5 better; 30–40 of ~45 lines differ by 1–2 chars) → the two scans are complementary: combine word by word.
- Bugs found: (1) nested Greek boxes read twice (a weak box spanning a whole column pair contains the real ones): v4 pp. 444, 461, 466, 542, 557; v5 p. 491. (2) alt page map interpolated p625 → leaf 715 (= p615) because only requested pages were matched; p625 then dropped as duplicate.
- v2.6: drop_nested() (layout and text stage); page map from all reference pages, gaps interpolated from direct neighbours, stale alt pages redone; PGxxx_words.jsonl with word confidences; STAGES=text option.
- pg_merge 2.0: base run per page, lines paired by similarity, differing words chosen by kraken word confidence; known + detected duplicate pages skipped.

## Full v5 run + merge (2026-10-26, 13:00)
- v5 (alt scan, 414–634): 7,739 lines, mean conf 0.9815, 74 set aside, 0 heavy-ink columns; duplicates p483=p481, p484=p482 detected.
- v4 re-texted with 2.6: 7,765 lines (nested-box duplicates and p444 Latin notes removed).
- Both scans miss some lines (segmenter skips a line at column top/bottom; e.g. p521, p540, p487) → merge adds lines only the other run has (34 lines).
- pg_merge 2.2: global line alignment (trigram similarity), word choice by frequency-in-volume (rare form ≤ 2 occurrences vs frequent similar form; grave/acute left to confidence) else kraken word confidence. Sample check: ~88 % of 1:1 disagreements decided correctly by confidence alone; frequency rule fixes ~230 more.
- Merged: 218 pages, 7,779 lines, mean conf 0.985, lines < 0.80: 37, < 0.90: 89 (v4 alone: 146 / 531). Random sample of 30 lines: ~7 errors in ~1,400 chars (≈ 0.5 % CER). Remaining: footnote call letters read as letters (stray 'τ'), lost paragraph initials (λεύσεται for Ἐλεύσεται), ἑ/ἐ, italics.

## pg_structure.py (`bash pg_ocr.sh 94 structure`)
- Migne columns from the IA OCR running heads of the main item (patrologicursus53migngoog), fitted as left col = 2·e + c (e = page index without duplicate scans): PDF p.412 = col. 789/790, p.414 = 793, p.482 = 929, p.485 = 931, p.522 = 1005, p.633 = 1227/1228. Book from "LIB. III." in the heads (smoothed).
- Greek title boxes (MainText_Title on the Greek side, not inside a column) cropped from the base run's page image and OCR'd with kraken (work/PG094/titles/). Headings "ΚΕΦΑΛ. ΙΔʹ [ΚΗʹ]." parsed (Greek numerals), checked against the sequence; inferred numbers reported.
- Outputs output/PG094/structured/: PG094_structured.md (books, chapters, paragraphs, [col. N] markers, ⟦?⟧), PG094_chapters.tsv, chapters/chNNN.txt, structure_report.txt.
- **Expositio fidei starts at PDF p.412 (col. 789, ΚΕΦΑΛ. Αʹ), not 414 → pp. 412–413 still to OCR (v4 + v5, then merge).** v5 layout: 93 Greek title blocks + 6 inside columns ≈ 100 chapters.

## pg_structure.py 2.0 (2026-10-26 13:45)
- v1 failed: our model reads bold capitals badly ("ΚΕΦΑΛ. ΙΕʹ [ΚΘʹ]" → "ΚΕβΑΑ. ΙΕ."), so only 18 chapters were found.
- v2: heading candidates = Greek title blocks (+ weak blocks where the IA OCR expects headings, + in-column subject lines matched to IA subjects). Evidence for numbers: our OCR numeral, ABBYY headings in the IA OCR of both scans (alt item reads "ΚΕΦΑΛ. ΚΒ' [ΛϚ']. Περὶ πάθους…" well), Latin "CAP. XXI" in the main item. Books split where a heading reads 1 and the running head shows the next book; chapter numbers per book by dynamic programming (+1 per heading, skipped number costs 1.2, agreeing readings add score). Subject lines: our OCR (conf ≥ 0.9) else IA.
- Result on PG 94 Expositio: 98 of 100 chapters, books I 13(+1 missing) / II 30 / III 28(+1 missing) / IV 27 – matches Migne (14/30/29/27). Missing headings: I.4 (≈p416) and III.13 (≈p535, the DP puts the gap one chapter early → III.11–12 labels may be off by one). 69 numbers read, 29 inferred.

## PG 94 (John of Damascus vol. 1)
- Scan: archive.org `patrologicursus53migngoog` (839 leaves); Expositio fidei ≈ PDF pages 414–634. Alt scan: `PatrologiaGraeca` / "Patrologia Graeca Vol. 094" (957 leaves).
- Critical edition: Kotter, Die Schriften des Johannes von Damaskos.

## Zenodo ground truth (record 20008699)
- Use v2 only (266 pages with text, 11,058 lines; 34 layout-only). NFC unifies oxia/tonos. Footnote call numbers omitted in labels.
- Split (seed 42): train 212 / val 24 / test 30 pages.
