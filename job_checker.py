"""
Job alert checker for Shir's job search.
Scrapes NVIDIA, KLA, Intel, Google, Amazon career pages and emails new relevant postings.
"""

import json
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

SEEN_JOBS_FILE = Path(__file__).parent / "seen_jobs.json"
RECIPIENT_EMAIL = "alanskverer@gmail.com"
SENDER_EMAIL = os.environ.get("GMAIL_ADDRESS", "alanskverer@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

KEYWORDS = [
    "supply chain",
    "business intelligence",
    "bi analyst",
    "data analyst",
    "planning analyst",
    "analytics specialist",
    "operations analyst",
    "demand planning",
    "sql",
    "tableau",
    "business analyst",
]

# Companies where we filter to Israel-only specific locations
LOCATION_FILTERED = {"intel", "google", "amazon"}

# Companies where we search all of Israel (NVIDIA, KLA)
ISRAEL_WIDE = {"nvidia", "kla"}


def load_seen_jobs() -> set:
    if SEEN_JOBS_FILE.exists():
        return set(json.loads(SEEN_JOBS_FILE.read_text()))
    return set()


def save_seen_jobs(seen: set) -> None:
    SEEN_JOBS_FILE.write_text(json.dumps(sorted(seen), indent=2))


def is_relevant(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw in text for kw in KEYWORDS)


def is_in_israel(location: str, company: str) -> bool:
    if company in ISRAEL_WIDE:
        return "israel" in location.lower()
    # For other companies, accept any Israeli city
    israel_locations = ["israel", "tel aviv", "herzliya", "petah tikva", "haifa",
                        "beer sheva", "rehovot", "ra'anana", "raanana", "kiryat gat"]
    return any(loc in location.lower() for loc in israel_locations)


# ---------------------------------------------------------------------------
# Workday scraper (used by NVIDIA and KLA)
# ---------------------------------------------------------------------------

def fetch_workday_jobs(tenant: str, instance: str, board: str, company_key: str) -> list[dict]:
    """
    Fetches jobs from Workday's undocumented CXS API.
    tenant: e.g. 'nvidia'
    instance: e.g. 'wd5'
    board: e.g. 'NVIDIAExternalCareerSite'
    """
    url = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs"
    headers = {"Content-Type": "application/json"}
    payload = {"limit": 20, "offset": 0, "searchText": "", "locations": []}
    jobs = []
    offset = 0

    while True:
        payload["offset"] = offset
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[{company_key}] Request failed at offset {offset}: {e}")
            break

        job_postings = data.get("jobPostings", [])
        if not job_postings:
            break

        for job in job_postings:
            title = job.get("title", "")
            location = job.get("locationsText", "") or job.get("primaryLocation", "")
            job_id = job.get("externalPath", "") or job.get("bulletFields", [""])[0]
            url_path = job.get("externalPath", "")
            full_url = f"https://{tenant}.{instance}.myworkdayjobs.com/en-US/{board}{url_path}"

            if is_in_israel(location, company_key) and is_relevant(title):
                jobs.append({
                    "id": f"{company_key}_{job_id}",
                    "title": title,
                    "company": company_key.upper(),
                    "location": location,
                    "url": full_url,
                })

        total = data.get("total", 0)
        offset += len(job_postings)
        if offset >= total:
            break
        time.sleep(0.5)

    return jobs


def fetch_nvidia_jobs() -> list[dict]:
    return fetch_workday_jobs("nvidia", "wd5", "NVIDIAExternalCareerSite", "nvidia")


def fetch_kla_jobs() -> list[dict]:
    return fetch_workday_jobs("kla", "wd1", "Search", "kla")


# ---------------------------------------------------------------------------
# Intel scraper — HTML scrape (Phenom People blocks direct API calls)
# ---------------------------------------------------------------------------

def fetch_intel_jobs() -> list[dict]:
    import re
    # Scrape Intel's jobs search page and extract embedded JSON
    url = "https://jobs.intel.com/en/search-jobs/Israel/599/1"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    jobs = []

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[intel] Request failed: {e}")
        return jobs

    # Intel embeds job data as JSON inside a <script> tag
    matches = re.findall(r'phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.ddo', resp.text, re.DOTALL)
    if not matches:
        # Fallback: look for jobs in the HTML as structured data
        matches = re.findall(r'"eagerLoadRefineSearch"\s*:\s*(\{.*?\})\s*,\s*"', resp.text, re.DOTALL)

    if not matches:
        print("[intel] Could not parse job data from page")
        return jobs

    try:
        data = json.loads(matches[0])
        job_list = (data.get("eagerLoadRefineSearch", {})
                        .get("data", {})
                        .get("jobs", []))
    except Exception:
        job_list = []

    for job in job_list:
        title = job.get("title", "")
        location = job.get("city", "") + ", " + job.get("country", "")
        job_id = str(job.get("jobId", ""))
        job_url = f"https://jobs.intel.com/en/detail/job/{job_id}"

        if is_relevant(title):
            jobs.append({
                "id": f"intel_{job_id}",
                "title": title,
                "company": "Intel",
                "location": location,
                "url": job_url,
            })

    return jobs


# ---------------------------------------------------------------------------
# Google scraper — HTML scrape with structured data extraction
# ---------------------------------------------------------------------------

def fetch_google_jobs() -> list[dict]:
    import re
    # Scrape Google Careers search page — API requires internal tokens
    url = "https://careers.google.com/jobs/results/"
    params = {
        "location": "Israel",
        "q": "supply chain analytics SQL Tableau business intelligence",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://careers.google.com/",
    }
    jobs = []

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[google] Request failed: {e}")
        return jobs

    # Google embeds job data as JSON-LD in <script type="application/ld+json">
    matches = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL
    )
    for raw in matches:
        try:
            data = json.loads(raw)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") != "JobPosting":
                continue
            title = item.get("title", "")
            location = item.get("jobLocation", {})
            if isinstance(location, list):
                location = location[0] if location else {}
            address = location.get("address", {})
            location_str = address.get("addressLocality", "") + ", " + address.get("addressCountry", "")
            job_url = item.get("url", "")
            job_id = job_url.split("/")[-1] if job_url else title.replace(" ", "_")

            if is_in_israel(location_str, "google") and is_relevant(title):
                jobs.append({
                    "id": f"google_{job_id}",
                    "title": title,
                    "company": "Google",
                    "location": location_str,
                    "url": job_url,
                })

    return jobs


# ---------------------------------------------------------------------------
# Amazon scraper
# ---------------------------------------------------------------------------

def fetch_amazon_jobs() -> list[dict]:
    url = "https://www.amazon.jobs/en/search.json"
    params = {
        "normalized_country_code[]": "ISR",
        "result_limit": 20,
        "offset": 0,
        "query": "supply chain analytics business intelligence SQL Tableau",
    }
    jobs = []

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[amazon] Request failed: {e}")
        return jobs

    for job in data.get("jobs", []):
        title = job.get("title", "")
        location = job.get("normalized_location", "") or job.get("location", "")
        job_id = str(job.get("id_icims", "") or job.get("job_id", ""))
        job_path = job.get("job_path", "")
        job_url = f"https://www.amazon.jobs{job_path}"

        if is_relevant(title):
            jobs.append({
                "id": f"amazon_{job_id}",
                "title": title,
                "company": "Amazon",
                "location": location,
                "url": job_url,
            })

    return jobs


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(new_jobs: list[dict]) -> None:
    if not GMAIL_APP_PASSWORD:
        print("No GMAIL_APP_PASSWORD set — skipping email.")
        return

    subject = f"Job Alert: {len(new_jobs)} new relevant job(s) found"

    rows = ""
    for job in new_jobs:
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">{job['company']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{job['title']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{job['location']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">
            <a href="{job['url']}" style="color:#4f46e5">View Job</a>
          </td>
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:auto">
      <h2 style="color:#4f46e5">Job Alert for Shir 🎯</h2>
      <p>Found <strong>{len(new_jobs)}</strong> new relevant job(s):</p>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#f3f4f6">
            <th style="padding:8px;text-align:left">Company</th>
            <th style="padding:8px;text-align:left">Title</th>
            <th style="padding:8px;text-align:left">Location</th>
            <th style="padding:8px;text-align:left">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="color:#888;font-size:12px;margin-top:24px">
        Powered by GitHub Actions · Checks daily at 8am Israel time
      </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    print(f"Email sent with {len(new_jobs)} job(s).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    seen = load_seen_jobs()
    print(f"Loaded {len(seen)} previously seen jobs.")

    fetchers = [
        fetch_nvidia_jobs,
        fetch_kla_jobs,
        fetch_intel_jobs,
        fetch_google_jobs,
        fetch_amazon_jobs,
    ]

    all_found = []
    for fetcher in fetchers:
        company = fetcher.__name__.replace("fetch_", "").replace("_jobs", "").upper()
        print(f"Checking {company}...")
        try:
            jobs = fetcher()
            print(f"  → {len(jobs)} relevant job(s) found")
            all_found.extend(jobs)
        except Exception as e:
            print(f"  → Error: {e}")

    new_jobs = [j for j in all_found if j["id"] not in seen]
    print(f"\n{len(new_jobs)} new job(s) since last check.")

    if new_jobs:
        send_email(new_jobs)
        for job in new_jobs:
            seen.add(job["id"])
        save_seen_jobs(seen)
        print("seen_jobs.json updated.")
    else:
        print("No new jobs — no email sent.")


if __name__ == "__main__":
    main()
