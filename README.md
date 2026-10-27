# Patrologiae Graecae Patris Migne

OCR pipeline for the Greek text of J.-P. Migne, *Patrologia Graeca* (PG): a
[kraken](https://kraken.re) model trained on published PG ground truth, recognition of whole
volumes from public-domain scans, word-level merging of two independent scans, and a structured
text with books, chapters and Migne column numbers.

First volume: **PG 94, John of Damascus** (*Expositio fidei*, *Dialectica*, *De haeresibus*,
*Orationes de imaginibus*, *Contra Jacobitas*, *Dialogus contra Manichaeos*, …).
The output is uncorrected OCR, intended as a reading and translation aid.

## Usage

```bash
powershell -ExecutionPolicy Bypass -File setup\setup_pg_ocr.ps1   # Windows: data, layout model
bash setup/setup_kraken.sh                                        # WSL: kraken environment

bash scripts/pg_train.sh                                # train the recognition model
bash scripts/run_pg_volume.sh 95                        # a whole volume: both scans + merge, resumable
bash scripts/pg_ocr.sh 94 all                           # main scan
SOURCE=alt RUN=v5 bash scripts/pg_ocr.sh 94 215-834     # second scan (IA "PatrologiaGraeca")
bash scripts/pg_ocr.sh 94 merge v4,v5                   # word-level merge -> output/PG094/best/
bash scripts/pg_ocr.sh 94 works                         # split into works, check page order -> output/PG094/works/
SOURCE=alt RUN=v5 bash scripts/pg_ocr.sh 94 leaf:487,488  # add leaves missing from the main scan
```

Pages without Greek text (Latin prefaces, title pages, index) can be listed in
`work/PGxxx/exclude_pages.txt`; recognition and merge leave them out. All steps are resumable. The project folder defaults to `/mnt/e/PG_OCR` (set `PG_ROOT` to change it).

## Scripts

| Script | Purpose |
|---|---|
| `scripts/prepare_gt.py` | Normalise the ground truth and split it into train / val / test |
| `scripts/pg_train.sh` | Train the kraken recognition model (watchdog, OOM fallback) |
| `scripts/run_pg_volume.sh` | One volume start to finish: checks, download and title-page check, both scans, merge, report |
| `scripts/pg_ocr.sh` | Entry point: recognise, merge, structure |
| `scripts/pg_ocr_volume.py` | Layout → column crops → kraken → text with line and word confidences |
| `scripts/pg_merge.py` | Combine two runs word by word (confidence and in-volume frequency) |
| `scripts/pg_works.py` | Splits the volume into its works, restores the page order, finds pages missing from the main scan, structures each work (books / chapters / sections / orations / dialogue) |
| `scripts/pg_structure.py` | Chapter detection and numbering, Migne columns (used by `pg_works.py`) |

## Results (PG 94)

- Recognition model, test set: **CER 0.96 %**, WER 4.66 %.
- *Expositio fidei* (cols. 789–1228), two scans merged: mean line confidence 0.985,
  about 0.5 % character errors in a manual sample; 99 of 100 chapters detected.

Development notes: [`docs/NOTES.md`](docs/NOTES.md).

## Credits

Ground truth: Calfa / GREgORI (Zenodo record 20008699). Layout model: Calfa REG-YOLOv12s.
Scans: Internet Archive (`patrologicursus53migngoog`, `PatrologiaGraeca`). OCR: kraken;
layout inference: Ultralytics YOLO. Data, models, scans and OCR output are not included here.
