---
name: biblio-checker
description: "Validate bibliography entries against DOI metadata from CrossRef and OpenAlex APIs. Use when: checking bibliography accuracy, verifying DOI metadata, validating reference lists, comparing bibliography entries against official sources, or auditing academic citations. Trigger words — bibliography validation, DOI checker, reference verification, check biblio, validate citations, bibliography audit, CrossRef metadata, OpenAlex."
---

# Bibliography Checker

Validate bibliography entries against official DOI metadata from CrossRef and OpenAlex APIs. The script parses a bibliography file, extracts DOIs (including those split across lines), fetches metadata, and compares titles, years, authors, and pages.

## Usage

```bash
# Validate a bibliography file (defaults to biblio.txt in current directory)
python check_biblio.py

# Specify a custom file path
python check_biblio.py path/to/references.txt

# Adjust API request delay (default 1 second)
python check_biblio.py biblio.txt --delay 0.5
```

The script expects a bibliography file with entries in the format:

```
[N] Authors, Title, venue, year. doi:10.XXXX/...
```

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `bibfile` | `biblio.txt` | Path to the bibliography file |
| `--delay` | `1.0` | Delay in seconds between API requests |

## What It Checks

For each entry containing a DOI:

- **Title**: Compares extracted title with API metadata (handles PDF hyphenation artifacts like "Bench- mark" → "Benchmark")
- **Year**: Validates publication year
- **First author**: Compares surnames (handles diacritics like "balunović" → "balunovic")
- **Pages**: Validates page ranges where available
- **DOI format**: Notes case differences from canonical form (e.g., `10.18653/V1/...` vs `10.18653/v1/...`)

## APIs Used

- **CrossRef**: Primary API for most DOIs (journal articles, conference papers, books)
- **OpenAlex**: Used for arXiv DOIs (10.48550/arXiv.XXXX), falls back to CrossRef if unavailable

## Output Format

```
Found 76 entries total, 44 with a DOI.

======================================================================
  Entry [4]  DOI: 10.18653/v1/P16-1057
======================================================================
  Source: crossref
  [OK] Title matches
  [OK] First author surname: ling
  [OK] Pages: 599–609
  [NOTE] DOI CASE: biblio has '10.18653/v1/P16-1057', canonical is '10.18653/v1/p16-1057'

...

======================================================================
  SUMMARY
======================================================================

  Checked: 44 entries with DOIs
  OK: 42
  Could not fetch metadata: 0
  With discrepancies: 2

  ────────────────────────────────────────────────────────────
  ENTRIES WITH DISCREPANCIES:
  ────────────────────────────────────────────────────────────

  [59]
      FIRST AUTHOR MISMATCH: biblio has 'deepseek-ai', API has 'guo'

  [74]
      TITLE MISMATCH
          In biblio : Bugs in Large Language Models Generated Code: An Empirical Study, Empir. Softw. Eng. 30 (3)
          In API    : Bugs in large language models generated code: an empirical study
```

## Handling Edge Cases

### DOIs Split Across Lines

PDF extractions often split DOIs across lines:
```
doi:10.18653/v1/2023.
findings-emnlp.89.
```

The script concatenates lines until a blank line is encountered, correctly reconstructing: `10.18653/v1/2023.findings-emnlp.89`

### PDF Hyphenation Artifacts

Titles from PDF extractions may contain hyphenation breaks:
- "Bench- mark" → normalized to "Benchmark"
- "Scal- able" → normalized to "Scalable"
- "Mod- els" → normalized to "Models"

### Diacritics in Author Names

Author names with diacritics are normalized to ASCII for comparison:
- "balunović" → "balunovic"
- "Müller" → "muller"

### Corporate vs Individual Authors

Some entries list corporate authors (e.g., "DeepSeek-AI") while the API lists individual authors (e.g., "Guo"). The script reports these as mismatches for manual review.

## Limitations

- **Title extraction**: Heuristic-based; may fail on unusual bibliography formats
- **Page numbers**: Only extracted if in "pp. X–Y" format
- **Multiple authors**: Only first author is validated
- **API rate limits**: 1-second delay between requests to avoid overwhelming APIs
- **Entries without DOIs**: Skipped (no validation possible)

## Customization

To modify the script for different bibliography formats, adjust:

1. **Entry parsing**: `parse_entries()` function (regex for entry boundaries)
2. **DOI extraction**: `extract_doi()` function (handles line-wrapped DOIs)
3. **Title extraction**: `extract_title_text()` function (end patterns for title boundary)
4. **Year extraction**: `extract_year_text()` function (pattern for year in parentheses)

## Example Workflow

```bash
# 1. Extract bibliography from PDF
pdftotext -layout -nopgbrk document.pdf biblio.txt

# 2. Run validation
python check_biblio.py > validation_output.txt

# 3. Review discrepancies
grep -A 5 "DISCREPANCIES" validation_output.txt
```
