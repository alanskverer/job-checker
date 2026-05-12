"""
Job alert checker for Shir's job search.
Scrapes NVIDIA, KLA, Intel, Google, Amazon career pages and emails new relevant postings.
"""

import json
import os
import re
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

# A job matches if its title contains any DOMAIN word AND any ROLE word.
# This catches "Supply Chain Analyst", "BI Planner", "Data Specialist", etc.
# while blocking unrelated roles like "Salesforce Analyst" or "HR Manager".
DOMAIN_KEYWORDS = [
    "supply chain",
    "business intelligence",
    "bi",
    "data",
    "analytics",
    "analytical",
    "operations",
    "demand",
    "planning",
    "inventory",
    "logistics",
    "forecasting",
    "sql",
    "tableau",
]

ROLE_KEYWORDS = [
    "analyst",
    "planner",
    "specialist",
    "engineer",
    "manager",
    "developer",
    "scientist",
]

# Search terms passed to each company's search engine
SEARCH_QUERY = "supply chain analytics business intelligence SQL Tableau planning inventory logistics forecasting"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

ISRAEL_LOCATIONS = [
    "israel", "tel aviv", "herzliya", "petah tikva", "haifa",
    "beer sheva", "rehovot", "ra'anana", "raanana", "kiryat gat",
    "yokneam", "yokne'am", "migdal haemek", "migdal ha'emek",
]


def load_seen_jobs() -> set:
    if SEEN_JOBS_FILE.exists():
        return set(json.loads(SEEN_JOBS_FILE.read_text()))
    return set()


def save_seen_jobs(seen: set) -> None:
    SEEN_JOBS_FILE.write_text(json.dumps(sorted(seen), indent=2))


def is_relevant(title: str) -> bool:
    t = title.lower()
    has_domain = any(kw in t for kw in DOMAIN_KEYWORDS)
    has_role = any(kw in t for kw in ROLE_KEYWORDS)
    return has_domain and has_role


def is_in_israel(location: str) -> bool:
    loc = location.lower()
    return any(place in loc for place in ISRAEL_LOCATIONS)


# ---------------------------------------------------------------------------
# Workday scraper (NVIDIA and KLA)
# Passes keywords as searchText so Workday searches its full database,
# then paginates through all matching results and filters by Israel locally.
# ---------------------------------------------------------------------------

def fetch_workday_jobs(tenant: str, instance: str, board: str, company_key: str) -> list[dict]:
    url = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs"
    headers = {"Content-Type": "application/json"}
    seen_ids: set = set()
    jobs = []

    # Run one search per major keyword group to maximize coverage
    search_terms = [
        "supply chain",
        "analytics",
        "business intelligence",
        "SQL",
        "tableau",
        "planning",
        "inventory",
        "logistics",
        "forecasting",
        "data analyst",
        "operations",
    ]

    for term in search_terms:
        offset = 0
        while True:
            payload = {"limit": 20, "offset": offset, "searchText": term, "locations": []}
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [{company_key}] search '{term}' failed at offset {offset}: {e}")
                break

            job_postings = data.get("jobPostings", [])
            if not job_postings:
                break

            for job in job_postings:
                title = job.get("title", "")
                location = job.get("locationsText", "") or job.get("primaryLocation", "")
                url_path = job.get("externalPath", "")
                job_id = url_path or title

                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                full_url = f"https://{tenant}.{instance}.myworkdayjobs.com/en-US/{board}{url_path}"

                if is_in_israel(location) and is_relevant(title):
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
            time.sleep(0.3)

    return jobs


def fetch_nvidia_jobs() -> list[dict]:
    return fetch_workday_jobs("nvidia", "wd5", "NVIDIAExternalCareerSite", "nvidia")


def fetch_kla_jobs() -> list[dict]:
    return fetch_workday_jobs("kla", "wd1", "Search", "kla")


# ---------------------------------------------------------------------------
# Intel scraper — paginates through all Israel jobs pages
# ---------------------------------------------------------------------------

def fetch_intel_jobs() -> list[dict]:
    jobs = []
    page = 1

    while True:
        url = f"https://jobs.intel.com/en/search-jobs/{SEARCH_QUERY}/Israel/599/{page}"
        headers = {
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [intel] page {page} failed: {e}")
            break

        # Intel embeds job data as JSON in phApp.ddo
        match = re.search(r'phApp\.ddo\s*=\s*(\{.+?\});\s*(?:phApp|</script>)', resp.text, re.DOTALL)
        if not match:
            if page == 1:
                print("  [intel] Could not parse job data from page")
            break

        try:
            data = json.loads(match.group(1))
            search_data = data.get("eagerLoadRefineSearch", {}).get("data", {})
            job_list = search_data.get("jobs", [])
            total = search_data.get("totalJobsCount", 0)
        except Exception:
            break

        if not job_list:
            break

        for job in job_list:
            title = job.get("title", "")
            location = f"{job.get('city', '')}, {job.get('country', '')}"
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

        jobs_per_page = len(job_list)
        if page * jobs_per_page >= total:
            break
        page += 1
        time.sleep(0.5)

    return jobs


# ---------------------------------------------------------------------------
# Google scraper — paginates through all results pages
# ---------------------------------------------------------------------------

def fetch_google_jobs() -> list[dict]:
    jobs = []
    page = 1

    while True:
        url = "https://careers.google.com/jobs/results/"
        params = {
            "location": "Israel",
            "q": SEARCH_QUERY,
            "page": page,
        }
        headers = {
            **BROWSER_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://careers.google.com/",
        }

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [google] page {page} failed: {e}")
            break

        matches = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL
        )

        found_any = False
        for raw in matches:
            try:
                data = json.loads(raw)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") != "JobPosting":
                    continue
                found_any = True
                title = item.get("title", "")
                loc_data = item.get("jobLocation", {})
                if isinstance(loc_data, list):
                    loc_data = loc_data[0] if loc_data else {}
                address = loc_data.get("address", {})
                location_str = f"{address.get('addressLocality', '')}, {address.get('addressCountry', '')}"
                job_url = item.get("url", "")
                job_id = job_url.split("/")[-1] if job_url else title.replace(" ", "_")

                if is_in_israel(location_str) and is_relevant(title):
                    jobs.append({
                        "id": f"google_{job_id}",
                        "title": title,
                        "company": "Google",
                        "location": location_str,
                        "url": job_url,
                    })

        if not found_any:
            break
        page += 1
        time.sleep(0.5)

    return jobs


# ---------------------------------------------------------------------------
# Amazon scraper — paginates using offset
# ---------------------------------------------------------------------------

def fetch_amazon_jobs() -> list[dict]:
    jobs = []
    offset = 0
    page_size = 10

    while True:
        url = "https://www.amazon.jobs/en/search.json"
        params = {
            "normalized_country_code[]": "ISR",
            "result_limit": page_size,
            "offset": offset,
            "query": SEARCH_QUERY,
        }

        try:
            resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [amazon] offset {offset} failed: {e}")
            break

        job_list = data.get("jobs", [])
        if not job_list:
            break

        for job in job_list:
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

        total = data.get("hits", 0)
        offset += len(job_list)
        if offset >= total:
            break
        time.sleep(0.3)

    return jobs


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(new_jobs: list[dict]) -> None:
    if not GMAIL_APP_PASSWORD:
        print("No GMAIL_APP_PASSWORD set — skipping email.")
        return

    subject = f"Job Alert: {len(new_jobs)} new relevant job(s) found for Shir"

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
      <h2 style="color:#4f46e5">Job Alert for Shir</h2>
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
