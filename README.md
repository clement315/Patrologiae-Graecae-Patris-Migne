# Patrologiae Graecae Patris Migne

OCR pipeline for the Greek text of J.-P. Migne, *Patrologia Graeca* (PG): a
[kraken](https://kraken.re) model trained on published PG ground truth, recognition of whole
volumes from public-domain scans, word-level merging of two independent scans, and a structured
text with books, chapters and Migne column numbers.

## Texts

Greek text of 55 volumes, split into 1349 works with Migne column numbers, in
[`texts/`](texts) (format described in [`texts/README.md`](texts/README.md)):

| Volume | Contents | Works | PDF pages | Lines | Mean line confidence |
|---|---|---|---|---|---|
| [PG 8](texts/PG008) | Clement of Alexandria I: Protrepticus, Paedagogus, Stromata I–IV | 3 | 667 | 23,173 | 0.9888 |
| [PG 9](texts/PG009) | Clement of Alexandria II: Stromata V–VIII, Quis dives salvetur, Excerpta ex Theodoto, Eclogae propheticae, fragments | 5 | 379 | 14,334 | 0.9861 |
| [PG 11](texts/PG011) | Origen I: On First Principles (Greek excerpts), On Prayer, Exhortation to Martyrdom, Against Celsus, other works | 7 | 786 | 33,597 | 0.9854 |
| [PG 12](texts/PG012) | Origen II: Greek Old Testament exegesis, from Genesis to the Psalms | 16 | 397 | 19,261 | 0.9761 |
| [PG 13](texts/PG013) | Origen III: Greek Old Testament fragments, Commentary on Matthew, and Luke material printed in this volume | 11 | 645 | 27,726 | 0.9839 |
| [PG 14](texts/PG014) | Origen IV: Commentary on John, Acts fragments and Philocalia (Latin Romans commentary excluded) | 3 | 410 | 20,074 | 0.9839 |
| [PG 17](texts/PG017) | Origen VII: exegetical supplements and fragments, including Greek quotations in Huet's Origeniana | 7 | 349 | 11,498 | 0.9624 |
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
| [PG 51](texts/PG051) | John Chrysostom III/3 (homilies on Scripture passages: De mutatione nominum, In principium Actorum, Habentes eundem spiritum, De eleemosyna) | 34 | 185 | 20,783 | 0.9780 |
| [PG 52](texts/PG052) | John Chrysostom III/4 (In Eutropium, homilies on the exile, Quod nemo laeditur, Ad eos qui scandalizati sunt, Epistolae; spuria) | 24 | 212 | 22,713 | 0.9821 |
| [PG 53](texts/PG053) | John Chrysostom IV/1 (Homiliae in Genesim I-XLI) | 41 | 182 | 22,526 | 0.9757 |
| [PG 54](texts/PG054) | John Chrysostom IV/2 (Homiliae in Genesim XLII-LXVII, Sermones in Genesim, De Anna, De Davide et Saule) | 43 | 162 | 19,766 | 0.9769 |
| [PG 55](texts/PG055) | John Chrysostom V/1 (Expositio in Psalmos; spuria) | 45 | 377 | 46,251 | 0.9756 |
| [PG 56](texts/PG056) | John Chrysostom VI/1 (Interpretatio in Isaiam, homilies In illud Vidi Dominum, other homilies, Synopsis Scripturae; spuria) | 34 | 280 | 32,031 | 0.9762 |
| [PG 57](texts/PG057) | John Chrysostom VII/1 (Homiliae in Matthaeum I-XLIV) | 44 | 187 | 21,657 | 0.9819 |
| [PG 58](texts/PG058) | John Chrysostom VII/2 (Homiliae in Matthaeum XLV-XC) | 46 | 162 | 18,903 | 0.9832 |
| [PG 59](texts/PG059) | John Chrysostom VIII (Homiliae in Joannem I-LXXXVIII; spuria) | 83 | 373 | 47,685 | 0.9776 |
| [PG 60](texts/PG060) | John Chrysostom IX (Homiliae in Acta Apostolorum, in Epistolam ad Romanos; spuria) | 74 | 382 | 47,275 | 0.9786 |
| [PG 61](texts/PG061) | John Chrysostom X (Homiliae in I-II ad Corinthios, Commentarius in Galatas; spuria) | 57 | 396 | 48,230 | 0.9775 |
| [PG 62](texts/PG062) | John Chrysostom XI (Homiliae in Eph., Phil., Col., I-II Thess., I-II Tim., Tit., Philem.; spuria) | 92 | 386 | 45,455 | 0.9773 |
| [PG 63](texts/PG063) | John Chrysostom XII (Homiliae in Hebraeos, Homiliae XI, Eclogae, Liturgia) | 33 | 353 | 41,982 | 0.9798 |
| [PG 64](texts/PG064) | John Chrysostom XIII (supplementary and appendix homilies, Testimonia, fragments on the OT, Meletius De natura hominis) | 20 | 477 | 27,971 | 0.9776 |
| [PG 67](texts/PG067) | Socrates Scholasticus and Sozomenus, Historiae ecclesiasticae (books I-VII, I-IX) | 17 | 767 | 30,029 | 0.9841 |
| [PG 68](texts/PG068) | Cyril of Alexandria I: De adoratione et cultu in spiritu et veritate (books I-XVII) | 17 | 501 | 27,099 | 0.9733 |
| [PG 69](texts/PG069) | Cyril of Alexandria II: Glaphyra in Pentateuchum, In Regum libros, Explanatio in Psalmos | 15 | 636 | 34,112 | 0.9801 |
| [PG 70](texts/PG070) | Cyril of Alexandria III: Commentarius in Isaiam (books I-V) | 5 | 727 | 41,016 | 0.9853 |
| [PG 71](texts/PG071) | Cyril of Alexandria IV: Commentarius in XII prophetas minores (Osee - Aggaeus) | 10 | 573 | 31,940 | 0.9825 |
| [PG 72](texts/PG072) | Cyril of Alexandria V: In Zachariam, In Malachiam, In Matthaeum (fragments), In Lucam | 4 | 503 | 27,134 | 0.9792 |
| [PG 73](texts/PG073) | Cyril of Alexandria VI: Commentarius in Joannem I-VI | 6 | 552 | 30,890 | 0.9789 |
| [PG 74](texts/PG074) | Cyril of Alexandria VII: In Joannem VII-XII; fragments on Acts and the Epistles | 11 | 518 | 28,519 | 0.9866 |
| [PG 75](texts/PG075) | Cyril of Alexandria VIII: Thesaurus, De Trinitate dialogi I-VII, De incarnatione Unigeniti, Quod unus sit Christus, Scholia | 15 | 715 | 37,752 | 0.9819 |
| [PG 76](texts/PG076) | Cyril of Alexandria IX: Adversus Nestorium, the Twelve Chapters, Contra Julianum I-X, De recta fide | 27 | 742 | 38,551 | 0.9866 |
| [PG 77](texts/PG077) | Cyril of Alexandria X: Epistolae, Homiliae paschales, Homiliae diversae; Theodotus of Ancyra, Paul of Emesa, John of Antioch, Acacius, Memnon, Firmus | 13 | 701 | 35,605 | 0.9808 |
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
