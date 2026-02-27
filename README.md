# Indus Feedback

Automated feedback collection dashboard for **Indus by Sarvam AI**. Scrapes Twitter/X for replies to @SarvamAI tweets, specific Indus threads, and broader keyword mentions — then displays everything in a Streamlit dashboard.

## What it collects

| Source | How |
|---|---|
| **@SarvamAI Timeline** | Fetches recent tweets from @SarvamAI, then scrapes all replies |
| **Indus Threads** | Monitors specific tweet threads about Indus (configurable) |
| **Broader Mentions** | Keyword search across X for "indus + sarvam" with noise filtering |

## Setup

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USER/indus-feedback.git
cd indus-feedback
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your X credentials

cp .streamlit/secrets.example.toml .streamlit/secrets.toml
# Edit secrets.toml with your dashboard login

# 3. Login to X (one-time — saves cookies)
python login_helper.py

# 4. Run the dashboard
streamlit run app.py
```

## Usage

1. Open `http://localhost:8501`
2. Log in with your dashboard credentials
3. Select a time range (Last 2h, 6h, 8h, 24h, etc.)
4. Click **Fetch from X** to scrape fresh data
5. Browse replies across three tabs: Timeline, Threads, Broader Mentions

## CLI collector

```bash
python collector.py --since 7d      # last 7 days
python collector.py --since 24h     # last 24 hours
python collector.py --since "2026-02-25"  # from a specific date
```

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard |
| `collector.py` | Scraping pipeline (twikit + Playwright) |
| `db.py` | SQLite storage |
| `notifier.py` | Email digest + CSV export |
| `login_helper.py` | One-time X login via browser |
| `config.example.yaml` | Configuration template |
