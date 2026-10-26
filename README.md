# Patrologiae Graecae Patris Migne

OCR pipeline for the Greek text of J.-P. Migne, *Patrologiae Cursus Completus, Series Graeca* (PG).
It trains a [kraken](https://kraken.re) recognition model on published PG ground truth,
recognises whole volumes from public-domain scans, combines two independent scans word by
word, and produces a structured, citable text (books, chapters, Migne column numbers).

First target: **PG 94, John of Damascus** — *Expositio fidei* (Ekdosis akribes tes orthodoxou
pisteos), *Dialectica*, *De haeresibus*, *Orationes de imaginibus I–III*, *Contra Jacobitas*,
*Dialogus contra Manichaeos* and the shorter works of the volume.

> Status: working research pipeline. The output is uncorrected OCR (see *Results*), meant as
> a reading and translation aid, not as an edition.

## Pipeline

```
PDF / page images
  └─ Calfa YOLO layout model (REG-YOLOv12s) → Greek main-text columns
       └─ crop, binarise (nlbin), pad → kraken baseline segmentation + our recognition model
            └─ PageXML → text, line and word confidences
                 ├─ run on the main scan (v4) and on a second scan (v5)
                 ├─ pg_merge.py: pair lines, choose each differing word by confidence/frequency
                 └─ pg_structure.py: books, chapters, Migne columns, paragraphs
```

| Script | Purpose |
|---|---|
| `setup/setup_pg_ocr.ps1` | Windows side: project folder, Python 3.11 (uv), ground-truth download, layout model |
| `setup/setup_kraken.sh` | WSL2 Ubuntu: kraken environment with CUDA PyTorch (`~/kraken-env`) |
| `scripts/prepare_gt.py` | Cleans the ground truth (NFC, whitespace), fixed train/val/test split |
| `scripts/pg_train.sh` | Compiles datasets and trains the recognition model; resumable, with a watchdog for NaN/no-learning runs and OOM fallback |
| `scripts/pg_ocr.sh` | Entry point for recognising a volume, merging and structuring; desktop notification at the end |
| `scripts/pg_ocr_volume.py` | Layout → crops → kraken → text, for one volume and one image source |
| `scripts/pg_merge.py` | Word-level combination of two runs |
| `scripts/pg_structure.py` | Chapter headings, book numbers, Migne columns, per-chapter files |
| `scripts/notify.sh` | Windows toast notification from WSL |

## Requirements

- Windows 10/11 with WSL2 (Ubuntu 24.04) and an NVIDIA GPU (developed on an RTX 4050 Laptop, 6 GB).
- About 10 GB of disk space per volume (scans, crops, PageXML).
- The project folder defaults to `E:\PG_OCR` (`/mnt/e/PG_OCR` in WSL); set `PG_ROOT` to use another one.
  The scripts expect to live in `<PG_ROOT>/scripts`, so the simplest set-up is to clone this repository
  as the project folder: data, models, work and output folders are ignored by git.

## Usage

```bash
# 1. environment (once)
powershell -ExecutionPolicy Bypass -File setup\setup_pg_ocr.ps1      # Windows
bash setup/setup_kraken.sh                                           # WSL

# 2. train the recognition model (prepare -> train -> test)
bash scripts/pg_train.sh            # --status | --resume | --new | --test

# 3. recognise a volume from the main scan (resumable)
bash scripts/pg_ocr.sh 94 all

# 4. second scan of the same volume (Internet Archive item "PatrologiaGraeca")
SOURCE=alt RUN=v5 bash scripts/pg_ocr.sh 94 215-834

# 5. combine both runs word by word -> output/PG094/best/
bash scripts/pg_ocr.sh 94 merge v4,v5

# 6. chapters, books, Migne columns -> output/PG094/structured/
bash scripts/pg_ocr.sh 94 structure
```

Useful options: `RUN=<folder>` (result folder), `STAGES=text` (rebuild text files only),
`MODEL=<file>` (recognition model), `PDF_URL=<url>` (other volumes), `NOTIFY=0`.

### Outputs (per volume)

| File | Content |
|---|---|
| `PGxxx_reading.txt` | Running text, line-end hyphens joined, `[PGxxx p.N]` page markers, `⟦?⟧` before uncertain lines |
| `PGxxx_text.txt` | Line-by-line text |
| `PGxxx_lines.tsv` | page, column, line, confidence, text |
| `PGxxx_words.jsonl` | word confidences (used by the merge) |
| `PGxxx_suspect.tsv` | lines set aside (mostly Latin read as Greek) |
| `summary.json` | statistics: duplicate scan pages, over-inked columns, low-confidence pages |
| `structured/PGxxx_structured.md` | books, chapters, paragraphs, `[col. N]` markers |
| `structured/chapters/chNNN.txt` | one file per chapter |

## Method notes

- **Recognition model.** kraken VGSL CNN-LSTM-CTC trained on the Calfa / GREgORI PG ground truth
  (266 pages, 11,058 lines; split 212 / 24 / 30 pages). Settings that worked on a 6 GB GPU:
  batch 8, fp32 (bf16 diverged), warm-up 1,000 steps, gradient clipping 1.0, lr 1e-3, early stopping.
  Test set: **CER 0.96 %, WER 4.66 %**.
- **Layout.** Greek boxes wider than 60 % of the page (Latin text crossing both columns) or weak
  boxes inside a stronger Latin box are rejected; nested Greek boxes are removed so that no text is
  read twice. Short crops are padded to 1,800 px height, otherwise the baseline segmenter breaks
  them into word fragments.
- **Over-inked scans.** The main scan of PG 94 is a 1-bit image in which some pages were thresholded
  too dark (filled letter counters). No binarisation can recover them, so the pipeline measures the
  stroke width of every column and uses a **second, independent scan** of the same volume
  (Internet Archive item `PatrologiaGraeca`). Pages are matched between the scans by comparing OCR
  words, because the leaf numbers differ (other front matter, duplicated leaves).
- **Merging two scans.** Lines are paired by global alignment on trigram similarity. Where the readings
  differ, the word with the higher kraken confidence is kept; a form that is frequent in the volume
  beats a similar form occurring at most twice (OCR errors rarely repeat). Lines that only one scan
  contains are added. Duplicated scan pages are detected and skipped.
- **Structure.** Migne column numbers come from the running heads in the Internet Archive OCR of the
  main scan, fitted to one consistent sequence. Chapter headings are detected by the layout model;
  their numbers are decided by dynamic programming over all available readings (our OCR, the IA OCR
  of both scans, the Latin `CAP.` numbers) under the constraint that chapters are consecutive.

## Results on PG 94

*Expositio fidei* (PDF pp. 412–633, cols. 789–1228), both scans merged:

| | main scan only | merged |
|---|---|---|
| lines | 7,765 | 7,779 |
| mean line confidence | 0.967 | 0.985 |
| lines below 0.80 | 116 | 37 |
| lines below 0.90 | ≈ 500 | 89 |

A manual check of a random sample gave a character error rate of about 0.5 %. The structuring step
finds 98 of the 100 chapters (books I–IV: 14 / 30 / 29 / 27 in Migne).

Whole volume, main scan: 24,548 Greek lines (about 1.09 million characters) on 839 pages.

Known remaining errors: italic scripture quotations, bold capital headings, lost paragraph initials,
superscript footnote letters read as Greek letters, rough/smooth breathing confusions.

## Data and credits

- Ground truth: Calfa / GREgORI transcriptions of Migne's PG (Zenodo record 20008699).
- Layout model: Calfa REG-YOLOv12s.
- Scans: Internet Archive (Google digitisations, public domain), items `patrologicursus53migngoog`
  and `PatrologiaGraeca`.
- OCR engine: [kraken](https://github.com/mittagessen/kraken); layout inference with
  [Ultralytics YOLO](https://github.com/ultralytics/ultralytics).

Ground truth, models, scans and OCR output are not included in this repository; please consult the
original records for their licence terms.
