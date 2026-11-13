# Patrologiae Graecae Patris Migne

OCR pipeline for the Greek text of J.-P. Migne, *Patrologia Graeca* (PG): a
[kraken](https://kraken.re) model trained on published PG ground truth, recognition of whole
volumes from public-domain scans, word-level merging of two independent scans, and a structured
text with books, chapters and Migne column numbers.

## Texts

Greek text of 23 volumes, split into 487 works with Migne column numbers, in
[`texts/`](texts) (format described in [`texts/README.md`](texts/README.md)):

| Volume | Contents | Works | PDF pages | Lines | Mean line confidence |
|---|---|---|---|---|---|
| [PG 25](texts/PG025) | Athanasius I | 15 | 458 | 21,799 | 0.9897 |
| [PG 26](texts/PG026) | Athanasius II | 22 | 637 | 26,518 | 0.9885 |
| [PG 27](texts/PG027) | Athanasius III | 5 | 669 | 33,355 | 0.9734 |
| [PG 28](texts/PG028) | Athanasius IV (dubia et spuria) | 50 | 749 | 38,037 | 0.9860 |
| [PG 29](texts/PG029) | Basil I | 3 | 455 | 20,474 | 0.9892 |
| [PG 30](texts/PG030) | Basil II (dubia et spuria; Eunomius) | 6 | 426 | 20,463 | 0.9785 |
| [PG 31](texts/PG031) | Basil III | 47 | 761 | 35,014 | 0.9848 |
| [PG 32](texts/PG032) | Basil IV (De Spiritu sancto, Epistolae) | 3 | 657 | 29,106 | 0.9896 |
| [PG 33](texts/PG033) | Cyril of Jerusalem; Peter II and Timothy of Alexandria; Apollinaris; Diodorus of Tarsus | 12 | 600 | 23,526 | 0.9825 |
| [PG 35](texts/PG035) | Gregory of Nazianzus I (Vita; Orationes I-XXVI) | 27 | 451 | 17,844 | 0.9913 |
| [PG 36](texts/PG036) | Gregory of Nazianzus II (Orationes XXVII-XLV; commentators) | 27 | 588 | 29,029 | 0.9714 |
| [PG 37](texts/PG037) | Gregory of Nazianzus III (Epistolae, Testamentum, Carmina I-II) | 6 | 790 | 23,434 | 0.9789 |
| [PG 38](texts/PG038) | Gregory of Nazianzus IV (Epitaphia, Epigrammata, Christus patiens); Cosmas, Nicetas David; Caesarius | 5 | 585 | 29,309 | 0.9754 |
| [PG 44](texts/PG044) | Gregory of Nyssa I (Hexaemeron, De hominis opificio, De vita Moysis, exegetical homilies) | 12 | 642 | 35,176 | 0.9854 |
| [PG 45](texts/PG045) | Gregory of Nyssa II (Oratio catechetica, Contra Eunomium I-XIIb, anti-Apollinarian works) | 26 | 660 | 35,352 | 0.9878 |
| [PG 46](texts/PG046) | Gregory of Nyssa III (De anima et resurrectione, De virginitate, homilies, Lives, Epistolae) | 35 | 576 | 28,534 | 0.9887 |
| [PG 47](texts/PG047) | John Chrysostom I (Palladius' Dialogus; Ad Theodorum, Adversus oppugnatores, De compunctione, Ad Stagirium, subintroductae) | 14 | 177 | 20,176 | 0.9820 |
| [PG 48](texts/PG048) | John Chrysostom II (De virginitate, De sacerdotio, Contra Anomoeos, Adversus Judaeos, De Lazaro; spuria) | 49 | 278 | 31,898 | 0.9782 |
| [PG 49](texts/PG049) | John Chrysostom III/1 (Ad populum Antiochenum, Catecheses, De diabolo tentatore, De poenitentia, festal homilies) | 12 | 198 | 22,256 | 0.9766 |
| [PG 50](texts/PG050) | John Chrysostom III/2 (festal and panegyric homilies: S. Paul, Babylas, martyrs; spuria) | 55 | 202 | 21,549 | 0.9737 |
| [PG 94](texts/PG094) | John of Damascus I | 11 | 664 | 24,875 | 0.9763 |
| [PG 95](texts/PG095) | John of Damascus II | 29 | 785 | 39,875 | 0.9755 |
| [PG 96](texts/PG096) | John of Damascus III | 16 | 743 | 37,148 | 0.9803 |

The texts are **uncorrected OCR** (about 0.5–1 % character errors on clean pages; lines marked
⟦?⟧ in the works files are uncertain). They are meant as a searchable reading and translation
aid, not as a critical text. Corrections are welcome (issues or pull requests).

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
SOURCE=pdf2 ALT_PDF=other_copy.pdf RUN=v6 bash scripts/pg_ocr.sh 95 10-825  # second scan from a local PDF (e.g. Google Books)
bash scripts/pg_ocr.sh 95 merge v4,v6+patch             # '+patch': pages taken from another copy (map:)
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

## Results

- Recognition model, test set: **CER 0.96 %**, WER 4.66 %.
- Most volumes are read from two independent scans, merged word by word (PG 30 from one scan,
  with two missing leaves taken from a microfilm copy); pages missing from or repeated in the
  scans are found from the Migne running heads and fixed (see each volume's `coverage.txt`).
- PG 94, *Expositio fidei* (cols. 789–1228): about 0.5 % character errors in a manual sample;
  99 of 100 chapters detected.

Development notes: [`docs/NOTES.md`](docs/NOTES.md).

## Credits

Ground truth: Calfa / GREgORI, CGPG project (Zenodo record 20008699, CC BY 4.0). Layout model:
Calfa REG-YOLOv12s. Scans: Google Books and Internet Archive (`patrologiae_cursus_completus_gr_vol_0NN`,
`patrologicursus53migngoog`, `PatrologiaGraeca`). OCR: kraken; layout inference: Ultralytics YOLO.
Scans, models and intermediate data are not included here.

## License

- Code (`scripts/`, `setup/`): MIT, see [`LICENSE`](LICENSE).
- Texts (`texts/`): the edition of J.-P. Migne is in the public domain; the OCR, merging, page
  repairs and division into works are released under CC BY-SA 4.0, see
  [`texts/LICENSE.md`](texts/LICENSE.md).
