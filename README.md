# CPLEE Tracker — Ganas & Go!

A self-updating public dashboard of California CPLEE (California Psychology
Laws and Ethics Examination) pass rates, built for
[The Mindful EPPP Journey](https://www.mindfulepppjourney.com/).

**Live dashboard:** https://ganasandgo.github.io/cplee-tracker/

Sister project to [eppp-tracker](https://github.com/ganasandgo/eppp-tracker),
which does the same thing for the EPPP.

## What's here

| File | What it does |
| --- | --- |
| `index.html` | The whole dashboard — one self-contained file, hosted on GitHub Pages |
| `scripts/update_data.py` | Downloads the Board's yearly PDFs and parses them into JSON |
| `data/cplee_stats.json` | The parsed data the dashboard reads |
| `.github/workflows/update-data.yml` | The robot that runs the scraper every Monday |
| `requirements.txt` | The two Python packages the scraper needs |

## How it works

1. The California Board of Psychology publishes one PDF per year of monthly
   CPLEE statistics on its [examination statistics page](https://www.psychology.ca.gov/applicants/exams/statistics.shtml).
   There is no API.
2. `scripts/update_data.py` downloads each year's PDF, reads the
   month-by-month table out of it, and merges the result into
   `data/cplee_stats.json`. It only rewrites the file when the numbers
   actually changed, so the repo doesn't fill up with empty commits.
3. The GitHub Actions workflow runs that script every Monday at 13:00 UTC
   and commits any changes. You can also trigger it by hand from the
   **Actions** tab.
4. `index.html` fetches `data/cplee_stats.json` and draws the charts. It
   also carries a full copy of the data baked into the page, so it still
   renders if the fetch fails or an ad blocker eats the chart library.

## Notes on the data

- **Coverage is 2008–present.** The CPLEE launched in May 2008.
- **First-timer counts start in 2009.** 2008 uses an older layout with a
  "# Failed" column and no first-timer breakdown.
- **2008–June 2015 was a different exam regime.** For those years the CPLEE
  was a limited-use exam sat by only a handful of candidates a month. It
  became the exam every California applicant takes on **July 1, 2015**, when
  it replaced the California Psychology Supplemental Examination (CPSE).
  Percentages before that date rest on very small numbers and should not be
  compared casually to later years.
- **Repeat test-taker rates are derived, not published.** The Board prints
  overall and first-time figures only. Subtracting first-timers from the
  Board's own totals yields the repeat-taker rate the Board never prints.
- **The 2017 PDF is a scan** and extracts unreliably. That year's figures in
  `data/cplee_stats.json` were transcribed by hand and reconciled against the
  Board's own printed annual total row. The scraper is written so a bad parse
  can't overwrite good stored data.

Year-to-date figures are provisional and may be revised by the Board.

## Running the scraper yourself

```bash
pip install -r requirements.txt
python scripts/update_data.py
```

## Keeping it working

The repo must stay **Public** for the free GitHub Actions automation and
GitHub Pages hosting.
