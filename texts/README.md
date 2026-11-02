# Texts

One folder per volume (`PG025`, …). Uncorrected OCR of the Greek text; the Latin translation,
prefaces and notes are not included.

| File | Contents |
|---|---|
| `works/<work>.md` | One work: title, PDF pages, sections or chapters, `[col. N]` = start of Migne column N, ⟦?⟧ = uncertain line |
| `works.tsv` | List of the works: slug, title, PDF pages, Migne columns, number of units, number of lines |
| `coverage.txt` | Checks of the volume: pages repeated in the scan, gaps in the Migne column sequence, pages of the second scan not found |
| `PGxxx_text.txt` | The whole merged Greek text of the volume, page by page |
| `summary.json` | Statistics of the merge (pages, lines, mean line confidence, words taken from the second scan) |

"PDF pages" refer to the main scan of each volume (named in `coverage.txt` and in
`scripts/pg_works.py`). For citation use the Migne column numbers, which are the same in every
copy.
