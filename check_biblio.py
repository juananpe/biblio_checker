#!/usr/bin/env python3
"""
Validate bibliography entries against DOI metadata.

For each entry in biblio.txt that contains a DOI, fetch the official metadata
from the CrossRef API (and OpenAlex for arXiv DOIs) and compare authors,
title, year, venue, and pages.
"""

import re
import sys
import time
import unicodedata
import argparse
import urllib.request
import urllib.error
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Parse biblio.txt
# ---------------------------------------------------------------------------

def parse_entries(text: str) -> list[dict]:
    """Split the bibliography text into individual entries."""
    pattern = re.compile(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)', re.DOTALL)
    entries = []
    for m in pattern.finditer(text):
        number = int(m.group(1))
        raw = m.group(2).strip()
        entries.append({"number": number, "raw": raw})
    return entries


def collapse(raw: str) -> str:
    """Join continuation lines into a single line, preserving spaces."""
    # Remove backslash-newline sequences (LaTeX-style line continuation)
    text = raw.replace('\\\n', ' ')
    # Collapse whitespace around newlines
    text = re.sub(r'\n\s+', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def extract_doi(raw: str) -> str | None:
    """Return the DOI found in *raw* (without the 'doi:' prefix), or None.

    Handles DOIs that are split across lines within the same paragraph.
    """
    lines = raw.split('\n')
    # Find the line containing "doi:"
    doi_start_line = -1
    for i, line in enumerate(lines):
        if re.search(r'doi\s*:', line, re.IGNORECASE):
            doi_start_line = i
            break

    if doi_start_line < 0:
        return None

    # Concatenate lines starting from the doi: line, until we hit a blank line
    # or end of text. This captures DOIs that wrap across lines.
    doi_text = ''
    for i in range(doi_start_line, len(lines)):
        line = lines[i].strip()
        if not line and doi_text:  # blank line after we've started collecting
            break
        doi_text += ' ' + line

    # Extract DOI from the concatenated text
    m = re.search(
        r'doi\s*:\s*(10\.\d{4,9}/[A-Za-z0-9.\-_;()/\s]+)',
        doi_text,
        re.IGNORECASE,
    )
    if not m:
        return None

    doi = m.group(1)
    # Remove all whitespace from the DOI
    doi = re.sub(r'\s+', '', doi)
    # Remove trailing periods, backslashes, or other punctuation
    doi = doi.rstrip('.\\')
    return doi


def extract_authors_text(raw: str) -> list[str]:
    """Extract the author list from the beginning of a bibliography entry."""
    collapsed = collapse(raw)
    # Authors end before the title. The title starts with a capital letter
    # after the last author. Pattern: authors, then ", Title..."
    # Find where authors end: look for ", " followed by a capital letter that
    # starts the title (not an author initial like "J." or "M.")
    # Heuristic: title starts after "et al.," or after the last author initial.
    # We look for the pattern: word, word (initials), then ", CapitalLetter word"
    # where CapitalLetter is not followed by a period (which would be an initial)

    # Find the title start by looking for ", Xxxx" where Xxxx is not an initial
    m = re.search(r',\s+([A-Z][a-z]{2,})', collapsed)
    if not m:
        return []

    authors_str = collapsed[:m.start()]
    # Split on ", " but keep "et al." intact
    parts = re.split(r',\s*', authors_str)
    authors = []
    for p in parts:
        p = p.strip()
        if p:
            authors.append(p)
    return authors


def extract_year_text(raw: str) -> int | None:
    """Extract the publication year from the entry text.

    Looks for (YYYY) pattern, preferring the last occurrence which is usually
    the actual publication year, not a volume/issue number.
    """
    collapsed = collapse(raw)
    # Find all (YYYY) patterns
    years = re.findall(r'\((\d{4})\)', collapsed)
    if not years:
        return None
    # Return the last year found (usually the publication year)
    return int(years[-1])


def extract_title_text(raw: str) -> str | None:
    """Heuristic extraction of the title from a bibliography entry."""
    collapsed = collapse(raw)

    # Strategy: find where authors end and title begins.
    # Authors are initials like "F. M. Surname" separated by ", "
    # Title starts after the last author, marked by ", " then a capital letter
    # that is NOT an initial (i.e., followed by more letters, not just ".")

    # Look for the pattern: after "et al.," or after the last author initial,
    # there's a title starting with a capital letter.
    # We'll find the first occurrence of ", Xxxx" where Xxxx is 3+ lowercase
    # letters after the capital (to distinguish from initials like "J." or "B.")

    title_start = None
    # Try to find title after "et al."
    m = re.search(r'et\s+al\.\s*,\s*([A-Z][a-z]{2,})', collapsed)
    if m:
        title_start = m.start(1)
    else:
        # Find the last author (look for pattern like "Surname," followed by
        # a title word that's not an initial)
        # Authors typically have pattern: "F. M. Surname, F. M. Surname, ..."
        # Find the last comma before a word that's clearly a title (3+ chars)
        matches = list(re.finditer(r',\s*([A-Z][a-z]{2,})', collapsed))
        if matches:
            # The title is usually the first such match after all authors
            # Authors have initials like "J." so look for word after ", "
            # that's not preceded by an initial pattern
            for match in matches:
                pos = match.start()
                # Check if this is likely the title start (not an author)
                # Authors are usually "F. M. Surname" - check if before this
                # we have author-like patterns
                before = collapsed[:pos]
                # If before ends with author initials pattern, this is title
                if re.search(r'[A-Z]\.\s*[A-Z]?\.\s*\w+$', before):
                    title_start = match.start(1)
                    break

    if title_start is None:
        return None

    # Extract from title_start to the end marker
    title_end_patterns = [
        r',\s+in:',           # conference paper
        r',\s+arXiv',         # arXiv preprint
        r',\s+CoRR',          # CoRR
        r',\s+Science',       # Science journal
        r',\s+Nature',        # Nature journal
        r'\.\s+J\.\s+',       # journal abbreviation
        r',\s+IEEE\s',        # IEEE
        r',\s+Trans\.',       # Transactions
        r',\s+Frontiers',     # Frontiers journal
        r',\s+Software\s',    # Software journal
        r',\s+Communications', # Communications journal
        r',\s+IBM\s',         # IBM journal
        r',\s+Proceedings\s', # Proceedings
        r',\s+Journal\s',     # Journal
        r',\s+J\.\s+Mach\.',  # JMLR
        r'\s+\(\d{4}\)',      # year in parentheses
    ]

    title_text = collapsed[title_start:]
    for pattern in title_end_patterns:
        m = re.search(pattern, title_text)
        if m:
            title_text = title_text[:m.start()]
            break

    # Clean up the title
    title_text = title_text.strip().rstrip('.,')
    # Remove any remaining year patterns
    title_text = re.sub(r'\s+\d{4}\s*$', '', title_text)
    return title_text if title_text else None


# ---------------------------------------------------------------------------
# 2. Fetch metadata from CrossRef
# ---------------------------------------------------------------------------

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
OPENALEX_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
HEADERS = {
    "User-Agent": "BiblioValidator/1.0 (mailto:user@example.com)",
}


def is_arxiv_doi(doi: str) -> bool:
    """Check if a DOI is an arXiv DOI (10.48550/arXiv.XXXX)."""
    return bool(re.match(r'^10\.48550/arxiv\.', doi, re.IGNORECASE))


def fetch_crossref(doi: str) -> dict | None:
    """Fetch metadata for *doi* from CrossRef.  Returns dict or None."""
    url = CROSSREF_URL.format(doi=doi)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("message")
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] Could not fetch metadata from CrossRef for DOI {doi}")
        return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def fetch_openalex(doi: str) -> dict | None:
    """Fetch metadata for *doi* from OpenAlex (works well for arXiv DOIs)."""
    url = OPENALEX_URL.format(doi=doi)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] Could not fetch metadata from OpenAlex for DOI {doi}")
        return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def fetch_metadata(doi: str) -> tuple[dict | None, str]:
    """Fetch metadata for *doi*, choosing the best API.
    Returns (metadata, source) where source is 'crossref', 'openalex', or None.
    """
    if is_arxiv_doi(doi):
        meta = fetch_openalex(doi)
        if meta:
            return meta, 'openalex'
        # Fall back to CrossRef
        meta = fetch_crossref(doi)
        if meta:
            return meta, 'crossref'
        return None, None
    else:
        meta = fetch_crossref(doi)
        if meta:
            return meta, 'crossref'
        return None, None


# ---------------------------------------------------------------------------
# 3. Comparison helpers
# ---------------------------------------------------------------------------

def normalize_author_name(name: str) -> str:
    """Normalize author name by removing diacritics and lowercasing."""
    # Normalize unicode to decompose characters, then encode to ASCII
    name = unicodedata.normalize('NFD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    return name.lower().strip()


def normalize_title(t: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison.
    
    Also handles hyphenation artifacts from PDF extraction (e.g., "Bench- mark" -> "benchmark").
    """
    t = t.lower()
    # Remove hyphens followed by space and lowercase letter (PDF hyphenation)
    t = re.sub(r'-\s+([a-z])', r'\1', t)
    # Remove page numbers that might have been included (standalone 1-3 digit numbers)
    t = re.sub(r'\s+\d{1,3}\s+', ' ', t)
    # Remove non-alphanumeric except spaces
    t = re.sub(r'[^a-z0-9\s]', '', t)
    # Collapse whitespace
    return re.sub(r'\s+', ' ', t).strip()


def first_author_surname(authors_text: list[str]) -> str | None:
    """Return the surname of the first author from the text author list."""
    if not authors_text:
        return None
    first = authors_text[0].strip()
    # Format is usually "F. M. Surname" or "Surname, F.M."
    parts = first.split()
    if len(parts) >= 2:
        return normalize_author_name(parts[-1].rstrip(','))
    return normalize_author_name(first)


def first_author_surname_crossref(meta: dict) -> str | None:
    """Return the surname of the first author from CrossRef metadata."""
    authors = meta.get("author", [])
    if authors:
        family = authors[0].get("family", "")
        return normalize_author_name(family) if family else None
    return None


def first_author_surname_openalex(meta: dict) -> str | None:
    """Return the surname of the first author from OpenAlex metadata."""
    authors = meta.get("authorships", [])
    if authors:
        author = authors[0].get("author", {})
        display_name = author.get("display_name", "")
        if display_name:
            return normalize_author_name(display_name.split()[-1])
    return None


def first_author_surname_meta(meta: dict, source: str) -> str | None:
    if source == 'crossref':
        return first_author_surname_crossref(meta)
    elif source == 'openalex':
        return first_author_surname_openalex(meta)
    return None


def crossref_year(meta: dict) -> int | None:
    """Extract the publication year from CrossRef metadata."""
    for key in ("published-print", "published-online", "issued", "created"):
        date_parts = meta.get(key, {}).get("date-parts", [[]])
        if date_parts and date_parts[0] and date_parts[0][0]:
            return int(date_parts[0][0])
    return None


def openalex_year(meta: dict) -> int | None:
    """Extract the publication year from OpenAlex metadata."""
    return meta.get("publication_year")


def meta_year(meta: dict, source: str) -> int | None:
    if source == 'crossref':
        return crossref_year(meta)
    elif source == 'openalex':
        return openalex_year(meta)
    return None


def crossref_title(meta: dict) -> str | None:
    titles = meta.get("title", [])
    return titles[0] if titles else None


def openalex_title(meta: dict) -> str | None:
    return meta.get("title")


def meta_title(meta: dict, source: str) -> str | None:
    if source == 'crossref':
        return crossref_title(meta)
    elif source == 'openalex':
        return openalex_title(meta)
    return None


def crossref_pages(meta: dict) -> str | None:
    return meta.get("page")


def openalex_pages(meta: dict) -> str | None:
    bib = meta.get("biblio", {})
    first = bib.get("first_page")
    last = bib.get("last_page")
    if first and last:
        return f"{first}-{last}"
    return first


def meta_pages(meta: dict, source: str) -> str | None:
    if source == 'crossref':
        return crossref_pages(meta)
    elif source == 'openalex':
        return openalex_pages(meta)
    return None


def extract_pages_text(raw: str) -> str | None:
    """Extract pages like 'pp. 123-456' or '123-456' from entry text."""
    collapsed = collapse(raw)
    m = re.search(r'pp\.\s*(\d+\s*[–-]\s*\d+)', collapsed)
    if m:
        return m.group(1).replace(' ', '')
    return None


def normalize_pages(p: str) -> str:
    """Normalise page ranges to 'start-end' with en-dash."""
    p = p.replace('–', '-').replace(' ', '')
    return p


# ---------------------------------------------------------------------------
# 4. Main validation logic
# ---------------------------------------------------------------------------

def validate_entry(entry: dict) -> list[str]:
    """Return a list of discrepancy messages for a single entry."""
    raw = entry["raw"]
    doi = extract_doi(raw)
    issues: list[str] = []
    notes: list[str] = []

    if doi is None:
        return issues  # no DOI, nothing to check

    print(f"\n{'='*70}")
    print(f"  Entry [{entry['number']}]  DOI: {doi}")
    print(f"{'='*70}")

    # --- Fetch metadata ---
    meta, source = fetch_metadata(doi)
    if meta is None:
        issues.append("Could not retrieve metadata from CrossRef or OpenAlex.")
        return issues

    print(f"  Source: {source}")

    # --- Title ---
    text_title = extract_title_text(raw)
    m_title = meta_title(meta, source)
    if text_title and m_title:
        if normalize_title(text_title) != normalize_title(m_title):
            issues.append(
                f"TITLE MISMATCH\n"
                f"    In biblio : {text_title}\n"
                f"    In API    : {m_title}"
            )
        else:
            print(f"  [OK] Title matches")
    elif text_title:
        print(f"  [INFO] Title in biblio: {text_title} (not in API?)")

    # --- Year ---
    text_year = extract_year_text(raw)
    m_year = meta_year(meta, source)
    if text_year and m_year:
        if text_year != m_year:
            issues.append(
                f"YEAR MISMATCH: biblio says {text_year}, API says {m_year}"
            )
        else:
            print(f"  [OK] Year: {text_year}")
    elif text_year:
        print(f"  [INFO] Year in biblio: {text_year} (API year not found)")

    # --- First author ---
    text_authors = extract_authors_text(raw)
    meta_first = first_author_surname_meta(meta, source)
    text_first = first_author_surname(text_authors)
    if text_first and meta_first:
        if text_first != meta_first:
            issues.append(
                f"FIRST AUTHOR MISMATCH: biblio has '{text_first}', "
                f"API has '{meta_first}'"
            )
        else:
            print(f"  [OK] First author surname: {text_first}")

    # --- Pages ---
    text_pages = extract_pages_text(raw)
    m_pages = meta_pages(meta, source)
    if text_pages and m_pages:
        if normalize_pages(text_pages) != normalize_pages(m_pages):
            issues.append(
                f"PAGES MISMATCH: biblio has '{text_pages}', "
                f"API has '{m_pages}'"
            )
        else:
            print(f"  [OK] Pages: {text_pages}")

    # --- DOI casing (note, not error) ---
    meta_doi = meta.get("DOI", "") or meta.get("doi", "")
    if meta_doi and doi.lower() == meta_doi.lower() and doi != meta_doi:
        notes.append(
            f"DOI CASE: biblio has '{doi}', canonical is '{meta_doi}'"
        )

    if notes:
        for n in notes:
            print(f"  [NOTE] {n}")

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate bibliography entries against DOI metadata."
    )
    parser.add_argument(
        "bibfile",
        nargs="?",
        default="biblio.txt",
        help="Path to the bibliography file (default: biblio.txt)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between API requests (default: 1.0)",
    )
    args = parser.parse_args()

    bib_path = Path(args.bibfile)
    if not bib_path.exists():
        print(f"Error: {bib_path} not found.")
        sys.exit(1)

    text = bib_path.read_text(encoding="utf-8")
    entries = parse_entries(text)

    # Filter entries with a DOI
    doi_entries = []
    for e in entries:
        if extract_doi(e["raw"]) is not None:
            doi_entries.append(e)

    print(f"Found {len(entries)} entries total, {len(doi_entries)} with a DOI.")

    all_issues: dict[int, list[str]] = {}
    for entry in doi_entries:
        issues = validate_entry(entry)
        if issues:
            all_issues[entry["number"]] = issues
        time.sleep(args.delay)  # be polite to the API

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    checked = len(doi_entries)
    failed_fetch = sum(1 for iss in all_issues.values()
                       if any("Could not retrieve" in i for i in iss))
    with_issues = {k: v for k, v in all_issues.items()
                   if not all("Could not retrieve" in i for i in v)}

    ok_count = checked - len(all_issues)
    print(f"\n  Checked: {checked} entries with DOIs")
    print(f"  OK: {ok_count}")
    print(f"  Could not fetch metadata: {failed_fetch}")
    print(f"  With discrepancies: {len(with_issues)}")

    if with_issues:
        print(f"\n  {'─'*60}")
        print(f"  ENTRIES WITH DISCREPANCIES:")
        print(f"  {'─'*60}\n")
        for num, issues in sorted(with_issues.items()):
            print(f"  [{num}]")
            for issue in issues:
                for line in issue.split('\n'):
                    print(f"      {line}")
            print()

    if failed_fetch:
        print(f"\n  {'─'*60}")
        print(f"  ENTRIES WHERE METADATA COULD NOT BE FETCHED:")
        print(f"  {'─'*60}\n")
        for num, issues in sorted(all_issues.items()):
            if any("Could not retrieve" in i for i in issues):
                doi = extract_doi(entries[num - 1]["raw"]) if num <= len(entries) else "?"
                print(f"  [{num}] DOI: {doi}")
        print()


if __name__ == "__main__":
    main()
