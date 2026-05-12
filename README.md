# Job Alert Service for Shir

Scrapes NVIDIA, KLA, Intel, Google, and Amazon career pages daily and emails new relevant job postings.

## What it checks

| Company | Region | Keywords |
|---|---|---|
| NVIDIA | All of Israel | supply chain, BI, analytics, SQL, Tableau, business analyst, planning |
| KLA | All of Israel | same |
| Intel | Kiryat Gat / Israel | same |
| Google | Tel Aviv | same |
| Amazon | Israel | same |

---

## Setup (one-time)

### 1. Create a GitHub repo

```bash
cd /home/alan/projects/job-checker
git init
git add .
git commit -m "init: job alert service"
# Create a new repo on GitHub (e.g. job-checker), then:
git remote add origin https://github.com/YOUR_USERNAME/job-checker.git
git push -u origin main
```

### 2. Get a Gmail App Password

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"** → create one named "job-checker"
4. Copy the 16-character password

### 3. Add GitHub Secrets

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `GMAIL_ADDRESS` | `alanskverer@gmail.com` |
| `GMAIL_APP_PASSWORD` | the 16-char app password from step 2 |

### 4. Enable GitHub Actions

Go to your repo → **Actions** tab → click **"I understand my workflows, go ahead and enable them"**

---

## Running manually

To trigger a check immediately (without waiting for 8am):

1. Go to GitHub repo → **Actions**
2. Click **"Daily Job Checker"**
3. Click **"Run workflow"**

---

## Running locally

```bash
cd /home/alan/projects/job-checker
GMAIL_ADDRESS=alanskverer@gmail.com GMAIL_APP_PASSWORD=your_app_password python3 job_checker.py
```
