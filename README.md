# Job Alert Service for Shir

Scrapes NVIDIA, KLA, Intel, Google, and Amazon career pages daily and emails new relevant job postings to alanskverer@gmail.com.

---

## Full Flow

### What happens on each run

1. GitHub Actions triggers the workflow daily at 8am Israel time (6:00 UTC)
2. `job_checker.py` runs and scrapes all 5 company career pages
3. Each job title is checked against the relevance filter (see below)
4. Found jobs are compared against `seen_jobs.json` — only jobs NOT in that file are considered new
5. If there are new relevant jobs, an HTML email is sent to alanskverer@gmail.com
6. The new job IDs are added to `seen_jobs.json` and committed back to the repo
7. Next run, those jobs are skipped — you never get the same job twice

### Company scrapers

| Company | Region | Method |
|---|---|---|
| NVIDIA | All of Israel | Workday JSON API (POST) — paginated, keyword search |
| KLA | All of Israel | Workday JSON API (POST) — paginated, keyword search |
| Intel | Israel | HTML page scrape — paginated by page number |
| Google | Tel Aviv / Israel | HTML page scrape — paginated by page number |
| Amazon | Israel | JSON API (GET) — paginated by offset |

**NVIDIA and KLA** use Workday's undocumented CXS API (`/wday/cxs/.../jobs`). The scraper runs multiple keyword searches (supply chain, analytics, SQL, etc.) and paginates through all results, deduplicating by job ID. Location is filtered locally by checking `locationsText` for Israeli cities.

**Intel** uses Phenom People ATS which blocks direct API calls, so we scrape the HTML search page and extract job data from the embedded `phApp.ddo` JSON object. Paginated via URL path (`/search-jobs/Israel/599/{page}`).

**Google** embeds job data as `application/ld+json` structured data in the HTML. We scrape the careers search page and extract `JobPosting` objects.

**Amazon** has a public JSON search endpoint (`/en/search.json`) that accepts country code and query string with offset-based pagination.

### Relevance filter — 3-tier logic

A job title passes if it matches **any** of these tiers:

**Tier 1 — Exact phrase match** (highest confidence):
`supply chain`, `business intelligence`, `demand planning`, `demand forecast`, `inventory planning`, `inventory management`, `logistics planning`, `procurement planning`, `operations analyst`, `operations planning`, `s&op`, `sales and operations`, `data analyst`, `data analytics`, `tableau`, `bi analyst`, `bi developer`, `bi engineer`, `bi manager`, `analytics developer`, `analytics engineer`

**Tier 2 — Whole-word short keyword + role**:
`\bBI\b` or `\bSQL\b` (regex word boundary to avoid matching "reliability", "sequel", etc.) AND any of: `analyst`, `planner`, `specialist`, `manager`, `developer`, `engineer`

**Tier 3 — Domain word AND role word**:
Domain: `analytics`, `analytical`, `planning`, `inventory`, `logistics`, `forecasting`, `procurement`, `sourcing`
Role: `analyst`, `planner`, `specialist`, `manager`

**Why so specific?**
Early versions used broad keywords (`data`, `operations`, `bi` as substring) which caused false positives:
- `"bi"` matched "relia**bi**lity"
- `"data"` matched "Data Center Security Specialist", "Data Engineer"
- `"operations"` matched "IT Lab Operations Engineer", "Chip Engineering Operations"
- `"engineer"` / `"developer"` / `"scientist"` as role words caught software/infra roles

The current 3-tier logic was validated against 17 known good/bad titles with 100% accuracy.

### Target profile (Shir's background)

- 7 years at Applied Materials in semiconductor supply chain
- Skills: SQL, Tableau, SAP, Databricks, spare parts planning, BI dashboards
- Looking for: Supply Chain Analytics, BI Analyst, Planning Analyst, Demand/Inventory roles
- Target companies: NVIDIA, KLA, Intel, Google, Amazon — all Israel

---

## Setup (one-time)

### 1. Create GitHub repo and push

```bash
gh repo create job-checker --private --source=. --remote=origin --push
```

### 2. Get a Gmail App Password

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Create one named "job-checker" — copy the 16-character password

### 3. Add GitHub Secrets via CLI

```bash
gh secret set GMAIL_ADDRESS --body "alanskverer@gmail.com"
gh secret set GMAIL_APP_PASSWORD --body "your_16_char_password"
```

### 4. Verify

```bash
gh workflow list          # should show "Daily Job Checker"
gh secret list            # should show GMAIL_ADDRESS and GMAIL_APP_PASSWORD
```

---

## Running manually

```bash
gh workflow run "Daily Job Checker"
gh run watch
```

Or locally:

```bash
GMAIL_ADDRESS=alanskverer@gmail.com GMAIL_APP_PASSWORD=your_app_password python3 job_checker.py
```

---

## Adding a new company

### If the company uses Workday

Add one line in `job_checker.py`:

```python
def fetch_companyname_jobs() -> list[dict]:
    return fetch_workday_jobs("tenant", "wd1", "BoardName", "companyname")
```

Then add `fetch_companyname_jobs` to the `fetchers` list in `main()`.

To find the Workday tenant/board, look at the company's careers URL:
`https://{tenant}.{instance}.myworkdayjobs.com/en-US/{board}`

### If the company uses a different ATS

Add a new `fetch_X_jobs()` function following the same pattern as `fetch_intel_jobs` or `fetch_amazon_jobs` — return a list of dicts with keys: `id`, `title`, `company`, `location`, `url`.

---

## Files

| File | Purpose |
|---|---|
| `job_checker.py` | Main script — all scraping, filtering, and email logic |
| `seen_jobs.json` | Tracks job IDs already emailed — committed back to repo after each run |
| `.github/workflows/check_jobs.yml` | GitHub Actions workflow — runs daily at 6:00 UTC (8am Israel) |
| `requirements.txt` | Python dependencies (`requests` only) |
