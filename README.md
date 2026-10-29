# Bibliography Checker

An agent skill and standalone Python script for checking bibliography entries against DOI metadata from CrossRef and OpenAlex.

## Requirements

- Python 3.10 or newer (standard library only).
- Internet access to retrieve DOI metadata.

## Install the skill

Clone this repository into your agent’s skills directory, using the skill name `biblio-checker`. For agents that read `~/.agents/skills`:

```bash
git clone https://github.com/juananpe/biblio_checker.git ~/.agents/skills/biblio-checker
```

See [SKILL.md](SKILL.md) for the full skill instructions and supported bibliography format.

## Standalone usage

```bash
python3 check_biblio.py path/to/references.txt
python3 check_biblio.py path/to/references.txt --delay 1.0
```

Without a file argument, the script reads `biblio.txt` in the current directory. Entries should be numbered and include a `doi:` field; use a parenthesized year for year validation:

```text
[1] A. B. Author, Example article title, Journal (2024), pp. 1–10. doi:10.1234/example
```

The script compares titles, publication years, first-author surnames, and page ranges where it can extract them. It handles line-wrapped DOIs and common PDF extraction artifacts, and prints a discrepancy summary.

Parsing is heuristic: review reported discrepancies manually. Entries without DOIs are skipped, and unavailable API metadata is reported separately.
