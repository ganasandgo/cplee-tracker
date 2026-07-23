#!/usr/bin/env python3
"""
Pulls the latest CA Board of Psychology CPLEE statistics and rebuilds
data/cplee_stats.json.

What it does, in plain terms:
1. Downloads each year's "Monthly CPLEE Statistics" PDF from
   psychology.ca.gov (one PDF per year, e.g. 2026_monthly_cplee.pdf).
2. Reads the month-by-month table out of each PDF.
3. Merges that into data/cplee_stats.json, only rewriting the file if
   something actually changed (so we don't spam commits with a bare
   timestamp bump).

This is meant to be run by the GitHub Actions workflow in
.github/workflows/update-data.yml on a schedule, but you can also run
it by hand any time:

    pip install -r requirements.txt
    python scripts/update_data.py

Notes specific to the CPLEE (vs. the EPPP tracker):
- CPLEE PDFs start in 2008, not 2006. The exam launched in May 2008.
- 2008 uses an older layout with a "# Failed" column and no first-timer
  counts. First-timer data starts in 2009.
- The 2017 PDF is a scan and extracts badly. If a year parses to fewer
  than 12 months, the script keeps whatever is already in the JSON
  rather than overwriting good data with a bad parse.
- Annual total rows appear as "Total", "Totals", "CPLEE - Total" or
  "Overall - Total" depending on the year.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import pdfplumber
from io import BytesIO

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "cplee_stats.json"

SOURCE_URL = "https://www.psychology.ca.gov/applicants/exams/statistics.shtml"
PDF_URL_TEMPLATE = "https://www.psychology.ca.gov/applicants/exams/{year}_monthly_cplee.pdf"

# The Board's CPLEE PDFs go back to 2008.
EARLIEST_YEAR = 2008

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_PATTERN = "|".join(MONTHS)

# Matches a month row like: "January 57 48 84.21% 34 28 82.35%"
# The trailing "%" is optional because some years' PDFs extract the
# percent sign and some don't. The final percentage is also optional -
# in 2013 the Board printed "November 7 6 85.71 0 0" with no first-time
# percentage at all, because there were no first-timers that month.
MONTH_ROW_RE = re.compile(
    rf"({MONTH_PATTERN})\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%?"
    rf"\s+([\d,]+)\s+([\d,]+)(?:\s+([\d.]+)%?)?",
)

# Matches the older 2008 format, which has no first-timer data:
# "June 9 5 4 55.56" (Month, candidates, passed, FAILED, pct)
OLD_MONTH_ROW_RE = re.compile(
    rf"({MONTH_PATTERN})\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%?",
)

# Matches whatever the Board calls the annual total row that year -
# observed variants: "Total", "Totals", "CPLEE - Total", "Overall - Total".
# \s+ spans newlines, which matters because 2025 wraps "Overall -" and
# "Total" onto separate lines.
TOTAL_ROW_RE = re.compile(
    r"(?:Overall\s*-?\s*Total|CPLEE\s*-?\s*Total|Totals?)\s+"
    r"([\d,]+)\s+([\d,]+)\s+([\d.]+)%?\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%?",
    re.IGNORECASE,
)


def to_int(s):
    return int(s.replace(",", ""))


def to_float(s):
    return float(s)


def safe_pct(numerator, denominator):
    """Percentage, or None when the denominator is zero (which happens -
    e.g. November 2013 had zero first-time takers)."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def fetch_pdf_text(year):
    """Download a year's PDF and return its full extracted text, or
    None if that year hasn't been published (404) or fails to fetch."""
    url = PDF_URL_TEMPLATE.format(year=year)
    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (CPLEE pass-rate tracker; contact via GitHub repo)"},
        )
    except requests.RequestException as exc:
        print(f"  [{year}] request failed: {exc}", file=sys.stderr)
        return None

    if resp.status_code == 404:
        print(f"  [{year}] not published yet (404)")
        return None
    if resp.status_code != 200:
        print(f"  [{year}] unexpected status {resp.status_code}", file=sys.stderr)
        return None

    try:
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return text
    except Exception as exc:  # noqa: BLE001 - genuinely want to catch anything pdfplumber throws
        print(f"  [{year}] PDF parse failed: {exc}", file=sys.stderr)
        return None


def parse_year(text, year, current_year):
    """Parse one year's extracted PDF text into our JSON shape, or
    None if nothing usable was found."""
    months_found = MONTH_ROW_RE.findall(text)
    has_ft = True

    if not months_found:
        # Fall back to the old 2008 format (no first-timer data).
        old_found = OLD_MONTH_ROW_RE.findall(text)
        if old_found:
            has_ft = False
            months_found = old_found
        else:
            print(f"  [{year}] no month rows matched - skipping", file=sys.stderr)
            return None

    months = []
    for m in months_found:
        if has_ft:
            name, candidates, passed, pct_passed, first_timers, first_time_passed, pct_ft = m
            ft = to_int(first_timers)
            ftp = to_int(first_time_passed)
            months.append({
                "month": name,
                "candidates": to_int(candidates),
                "passed": to_int(passed),
                "pct_passed": to_float(pct_passed),
                "first_timers": ft,
                "first_time_passed": ftp,
                # The Board sometimes omits this cell entirely; recompute it.
                "pct_first_time_passed": to_float(pct_ft) if pct_ft else safe_pct(ftp, ft),
            })
        else:
            # Old format: Month, candidates, passed, failed, pct
            name, candidates, passed, _failed, pct_passed = m
            months.append({
                "month": name,
                "candidates": to_int(candidates),
                "passed": to_int(passed),
                "pct_passed": to_float(pct_passed),
                "first_timers": None,
                "first_time_passed": None,
                "pct_first_time_passed": None,
            })

    # De-duplicate while preserving order, just in case a PDF repeats
    # a header/table across pages.
    seen = set()
    deduped = []
    for entry in months:
        if entry["month"] in seen:
            continue
        seen.add(entry["month"])
        deduped.append(entry)
    months = deduped

    # Keep the Board's own calendar order rather than whatever order the
    # text happened to extract in.
    months.sort(key=lambda e: MONTHS.index(e["month"]))

    total_match = TOTAL_ROW_RE.search(text) if has_ft else None
    if total_match:
        candidates, passed, pct_passed, first_timers, first_time_passed, pct_ft = total_match.groups()
        total = {
            "candidates": to_int(candidates),
            "passed": to_int(passed),
            "pct_passed": round(to_float(pct_passed), 2),
            "first_timers": to_int(first_timers),
            "first_time_passed": to_int(first_time_passed),
            "pct_first_time_passed": round(to_float(pct_ft), 2),
        }
    else:
        # Compute the total from the months ourselves - either because
        # we couldn't find a clean total row (2009 and 2010 have none),
        # or because this is an old-format year that doesn't have one.
        if has_ft:
            print(f"  [{year}] no total row matched - computing from months", file=sys.stderr)
        cand = sum(m["candidates"] for m in months)
        passed = sum(m["passed"] for m in months)
        ft_vals = [m["first_timers"] for m in months if m["first_timers"] is not None]
        ftp_vals = [m["first_time_passed"] for m in months if m["first_time_passed"] is not None]
        ft = sum(ft_vals) if ft_vals else None
        ftp = sum(ftp_vals) if ftp_vals else None
        total = {
            "candidates": cand,
            "passed": passed,
            "pct_passed": safe_pct(passed, cand) or 0,
            "first_timers": ft,
            "first_time_passed": ftp,
            "pct_first_time_passed": safe_pct(ftp, ft) if ft else None,
        }

    # A year counts as finished once all 12 months are in, or once the
    # calendar has moved past it. The second condition matters for 2008,
    # where the exam only launched in May, so the year will never have
    # 12 rows and would otherwise be re-fetched forever.
    complete = len(months) == 12 or year < current_year

    return {
        "complete": complete,
        "months": months,
        "total": total,
    }


def main():
    existing = {"source_url": SOURCE_URL, "last_updated": None, "years": {}}
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            existing = json.load(f)

    current_year = datetime.now(timezone.utc).year
    years_data = dict(existing.get("years", {}))

    for year in range(EARLIEST_YEAR, current_year + 1):
        key = str(year)
        already_complete = years_data.get(key, {}).get("complete", False)

        # Only years that are already fully closed out don't need to be
        # re-fetched. Anything in progress, or missing entirely, gets
        # fetched fresh.
        if already_complete:
            print(f"[{year}] already complete, skipping re-fetch")
            continue

        print(f"[{year}] fetching...")
        text = fetch_pdf_text(year)
        if text is None:
            continue

        parsed = parse_year(text, year, current_year)
        if parsed is None:
            continue

        # Guard against a bad parse wiping out good data. Some of the
        # Board's older PDFs are scans that extract unreliably, so if we
        # already hold more months for this year than we just parsed,
        # keep what we have.
        held = len(years_data.get(key, {}).get("months", []))
        if held > len(parsed["months"]):
            print(
                f"  [{year}] parsed only {len(parsed['months'])} month(s) but we already "
                f"hold {held} - keeping existing data",
                file=sys.stderr,
            )
            continue

        years_data[key] = parsed
        print(f"  [{year}] parsed {len(parsed['months'])} month(s), complete={parsed['complete']}")

    new_data = {
        "source_url": SOURCE_URL,
        "last_updated": existing.get("last_updated"),
        "years": years_data,
    }

    # Only bump last_updated (and therefore only trigger a commit) if
    # the actual data changed.
    old_comparable = {"source_url": existing.get("source_url"), "years": existing.get("years", {})}
    new_comparable = {"source_url": new_data["source_url"], "years": new_data["years"]}

    if old_comparable == new_comparable:
        print("No data changes detected - leaving file untouched.")
        return

    new_data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(new_data, f, indent=2)
        f.write("\n")
    print(f"Wrote updated data to {DATA_PATH}")


if __name__ == "__main__":
    main()
