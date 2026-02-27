"""
Indus Feedback Collector
~~~~~~~~~~~~~~~~~~~~~~~~
Scans @SarvamAI's tweets, opens each one, and collects all replies.
Classifies replies into: feedback / feature_request.

Usage:
  python collector.py                              # last 24 hours (default)
  python collector.py --since "2026-02-25"         # from a specific date
  python collector.py --since 7d                   # last 7 days
  python collector.py --since 2w                   # last 2 weeks
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import yaml
from playwright.async_api import async_playwright

from twikit import Client

from db import init_db, insert_tweet
from notifier import export_to_csv, send_email_digest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(BASE_DIR, "data", "collector.log")),
    ],
)
log = logging.getLogger("collector")


# ── since-filter parsing ─────────────────────────────────────────────

_RELATIVE_RE = re.compile(r"^(\d+)\s*(h|d|w|m)$", re.IGNORECASE)
_UNIT_MAP = {"h": "hours", "d": "days", "w": "weeks", "m": "days"}


def parse_since(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc) - timedelta(hours=24)
    value = value.strip()
    match = _RELATIVE_RE.match(value)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "m":
            amount *= 30
        return datetime.now(timezone.utc) - timedelta(**{_UNIT_MAP[unit]: amount})
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("Could not parse --since '%s', defaulting to last 24h", value)
    return datetime.now(timezone.utc) - timedelta(hours=24)


def tweet_is_after(created_at: str, since: datetime) -> bool:
    if not created_at:
        return True
    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(created_at, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= since
        except ValueError:
            continue
    return True


# ── classifier ───────────────────────────────────────────────────────

_FEATURE_REQUEST_SIGNALS = [
    "feature", "request", "add support", "please add", "should have",
    "would be nice", "wish it", "wish there", "missing", "needs to",
    "need to add", "can you add", "could you add", "want to see",
    "roadmap", "upcoming", "when will", "support for", "integrate",
    "integration", "add option", "option to", "ability to",
    "pls add", "plz add", "should add", "we need", "i need",
]

_PRODUCT_FEEDBACK_SIGNALS = [
    "bug", "buggy", "crash", "crashes", "crashing", "glitch", "laggy",
    "lag", "slow", "fast", "smooth", "broken", "error", "fix",
    "heating", "heats up", "heat up", "heatup", "hot", "overheat",
    "battery", "drain", "login", "log in", "sign in", "signin",
    "can't open", "cannot open", "not working", "doesn't work",
    "not loading", "loading", "stuck", "freeze", "froze",
    "ui", "interface", "dark mode", "font", "layout",
    "notification", "update", "version", "install", "uninstall",
    "accurate", "inaccurate", "wrong answer", "correct answer",
    "hallucin", "response", "speed", "latency", "timeout",
    "voice", "mic", "audio", "camera", "upload", "download",
    "app", "indus app", "the app", "this app", "your app",
    "tried it", "tried the", "using it", "used it", "tested",
    "experience", "usability", "performance", "quality",
    "underrated", "overrated", "impressed", "disappointing",
    "love the app", "love this app", "hate the app",
    "smooth experience", "bad experience", "good experience",
    "awesome app", "amazing app", "great app", "terrible app",
    "sucks", "fantastic", "solid app", "best app", "worst app",
    "playstore", "play store", "app store",
    "refinement", "polish", "improve",
]

_GENERAL_FEEDBACK_SIGNALS = [
    "proud", "congratulations", "congrats", "kudos", "bravo",
    "all the best", "best wishes", "good luck", "keep it up",
    "great initiative", "great work", "good work", "amazing work",
    "game changer", "game-changer", "revolutionary",
    "future", "potential", "promising", "exciting",
    "india", "bharat", "desi", "indigenous", "sovereign",
    "startup", "company", "team", "funding", "invest",
    "compete", "competition", "chatgpt", "grok", "gemini",
    "business", "market", "industry",
    "partnership", "partner", "collab",
]


def classify_bucket(text: str) -> str:
    lower = text.lower()
    fr = sum(1 for kw in _FEATURE_REQUEST_SIGNALS if kw in lower)
    pf = sum(1 for kw in _PRODUCT_FEEDBACK_SIGNALS if kw in lower)
    gf = sum(1 for kw in _GENERAL_FEEDBACK_SIGNALS if kw in lower)

    if fr > 0 and fr >= pf and fr >= gf:
        return "feature_request"
    if pf > 0 and pf >= gf:
        return "product_feedback"
    if gf > 0:
        return "general_feedback"
    return "general_feedback"


# ── helpers ──────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


# ── Step 1: get @SarvamAI tweets via twikit ──────────────────────────

async def get_sarvam_tweet_ids(cookies_path: str, handle: str, since: datetime) -> list[dict]:
    """Fetch recent tweets from @SarvamAI and return their IDs + metadata."""
    client = Client("en-US")
    client.load_cookies(cookies_path)

    log.info("Fetching tweets from @%s…", handle)
    user = await client.get_user_by_screen_name(handle)
    tweets = await client.get_user_tweets(user.id, "Tweets", count=40)

    results = []
    if tweets:
        for tweet in tweets:
            created = str(tweet.created_at) if tweet.created_at else ""
            if tweet_is_after(created, since):
                text_preview = (tweet.text or "")[:80].replace("\n", " ")
                results.append({
                    "tweet_id": str(tweet.id),
                    "handle": tweet.user.screen_name if tweet.user else handle,
                    "text_preview": text_preview,
                    "reply_count": getattr(tweet, "reply_count", 0) or 0,
                })

    log.info("  -> %d tweets from @%s in date range", len(results), handle)
    return results


# ── Step 2: scrape replies from each tweet via Playwright ────────────

_TWEET_LINK_RE = re.compile(r"/(\w+)/status/(\d+)")


async def _create_browser_context(pw, cookies_path: str):
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
    )

    with open(cookies_path, "r") as f:
        raw_cookies = json.load(f)

    pw_cookies = [
        {"name": n, "value": v, "domain": ".x.com", "path": "/"}
        for n, v in raw_cookies.items()
    ]
    await context.add_cookies(pw_cookies)
    return browser, context


async def search_keyword_tweets(
    context, query: str, exclude_terms: list[str],
    relevance_signals: list[str],
    since: datetime, max_scrolls: int = 5,
) -> list[dict]:
    """Search X for a query and collect matching tweets, with relevance filtering."""
    results = []
    seen_ids: set[str] = set()

    since_str = since.strftime("%Y-%m-%d")
    until_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    full_query = f"{query} since:{since_str} until:{until_str}"
    encoded = full_query.replace(" ", "%20").replace('"', "%22")
    search_url = f"https://x.com/search?q={encoded}&src=typed_query&f=latest"

    page = await context.new_page()
    try:
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        exclude_lower = [t.lower() for t in exclude_terms]
        signal_lower = [s.lower() for s in relevance_signals]

        for _ in range(max_scrolls):
            articles = await page.query_selector_all('article[data-testid="tweet"]')

            for article in articles:
                try:
                    link_el = await article.query_selector('a[href*="/status/"]')
                    if not link_el:
                        continue
                    href = await link_el.get_attribute("href") or ""
                    match = _TWEET_LINK_RE.search(href)
                    if not match:
                        continue

                    username = match.group(1)
                    tweet_id = match.group(2)
                    if tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)

                    text_el = await article.query_selector('[data-testid="tweetText"]')
                    text = await text_el.inner_text() if text_el else ""

                    text_lower = text.lower()
                    handle_lower = username.lower()

                    # drop if it contains an exclude term
                    if any(ex in text_lower for ex in exclude_lower):
                        continue

                    # must contain at least one relevance signal in text or handle
                    combined = text_lower + " " + handle_lower
                    if not any(sig in combined for sig in signal_lower):
                        continue

                    name_el = await article.query_selector(
                        '[data-testid="User-Name"] span'
                    )
                    display_name = await name_el.inner_text() if name_el else username

                    time_el = await article.query_selector("time")
                    created_at = ""
                    if time_el:
                        created_at = await time_el.get_attribute("datetime") or ""

                    results.append({
                        "tweet_id": tweet_id,
                        "author_name": display_name,
                        "author_handle": username,
                        "text": text,
                        "tweet_url": f"https://x.com/{username}/status/{tweet_id}",
                        "source_type": "keyword_mention",
                        "source_detail": query,
                        "parent_text": query,
                        "parent_url": f"https://x.com/search?q={encoded}&f=latest",
                        "likes": 0,
                        "retweets": 0,
                        "replies": 0,
                        "tweet_created_at": created_at,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    continue

            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)
    finally:
        await page.close()

    return results


async def scrape_replies(
    context, parent_tweet_id: str, parent_handle: str,
    parent_text: str = "", max_scrolls: int = 5,
) -> list[dict]:
    """Open a tweet and scrape all replies."""
    replies = []
    seen_ids = set()

    page = await context.new_page()
    try:
        url = f"https://x.com/{parent_handle}/status/{parent_tweet_id}"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        for _ in range(max_scrolls):
            articles = await page.query_selector_all('article[data-testid="tweet"]')

            for article in articles:
                try:
                    link_el = await article.query_selector('a[href*="/status/"]')
                    if not link_el:
                        continue
                    href = await link_el.get_attribute("href") or ""
                    match = _TWEET_LINK_RE.search(href)
                    if not match:
                        continue

                    username = match.group(1)
                    tweet_id = match.group(2)

                    # skip the parent tweet itself
                    if tweet_id == parent_tweet_id:
                        continue
                    if tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)

                    text_el = await article.query_selector('[data-testid="tweetText"]')
                    text = await text_el.inner_text() if text_el else ""

                    name_el = await article.query_selector(
                        '[data-testid="User-Name"] span'
                    )
                    display_name = await name_el.inner_text() if name_el else username

                    time_el = await article.query_selector("time")
                    created_at = ""
                    if time_el:
                        created_at = await time_el.get_attribute("datetime") or ""

                    replies.append({
                        "tweet_id": tweet_id,
                        "author_name": display_name,
                        "author_handle": username,
                        "text": text,
                        "tweet_url": f"https://x.com/{username}/status/{tweet_id}",
                        "source_type": "reply",
                        "source_detail": f"@{parent_handle}/{parent_tweet_id}",
                        "parent_text": parent_text,
                        "parent_url": f"https://x.com/{parent_handle}/status/{parent_tweet_id}",
                        "likes": 0,
                        "retweets": 0,
                        "replies": 0,
                        "tweet_created_at": created_at,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    continue

            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)
    finally:
        await page.close()

    return replies


# ── main pipeline ────────────────────────────────────────────────────

async def run(since: datetime, progress_cb=None) -> list[dict]:
    """Run the collection pipeline. Returns list of new tweets.

    Args:
        since: only collect tweets after this datetime
        progress_cb: optional callable(message: str) for live progress updates
    """
    config = load_config()
    init_db()

    def _progress(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    _progress(f"Collecting feedback since: {since.strftime('%Y-%m-%d %H:%M UTC')}")

    cookies_path = os.path.join(
        BASE_DIR, config["twitter"].get("cookies_file", "data/cookies.json")
    )
    if not os.path.exists(cookies_path):
        raise FileNotFoundError("No cookies found. Run login_helper.py first.")

    handle = config.get("monitor", {}).get("sarvam_handle", "SarvamAI")

    _progress(f"Fetching @{handle} tweet list…")
    parent_tweets = await get_sarvam_tweet_ids(cookies_path, handle, since)

    _progress(f"Found {len(parent_tweets)} tweets from @{handle}")

    all_replies: list[dict] = []

    indus_threads = config.get("monitor", {}).get("indus_threads", [])
    search_queries = config.get("search", {}).get("queries", [])

    async with async_playwright() as pw:
        browser, context = await _create_browser_context(pw, cookies_path)
        try:
            # Part 1: SarvamAI timeline replies
            total = len(parent_tweets) + len(indus_threads) + len(search_queries)
            idx = 0
            for pt in parent_tweets:
                idx += 1
                _progress(
                    f"[{idx}/{total}] Timeline: {pt['text_preview'][:60]}…"
                )
                replies = await scrape_replies(
                    context, pt["tweet_id"], pt["handle"],
                    parent_text=pt["text_preview"], max_scrolls=5,
                )
                for r in replies:
                    r["source_type"] = "timeline_reply"
                _progress(f"  -> {len(replies)} replies")
                all_replies.extend(replies)
                await asyncio.sleep(2)

            # Part 2: pinned Indus threads
            for thread in indus_threads:
                idx += 1
                label = thread.get("label", thread["tweet_id"])
                _progress(f"[{idx}/{total}] Thread: {label}…")
                replies = await scrape_replies(
                    context, thread["tweet_id"], thread["handle"],
                    parent_text=label, max_scrolls=8,
                )
                for r in replies:
                    r["source_type"] = "thread_reply"
                _progress(f"  -> {len(replies)} replies")
                all_replies.extend(replies)
                await asyncio.sleep(2)

            # Part 3: broader keyword search
            search_cfg = config.get("search", {})
            exclude_terms = search_cfg.get("exclude_terms", [])
            relevance_signals = search_cfg.get("relevance_signals", [])

            if search_queries:
                _progress(f"Searching X for {len(search_queries)} keyword queries…")
                for q in search_queries:
                    idx += 1
                    _progress(f"[{idx}/{total}] Search: {q}")
                    kw_tweets = await search_keyword_tweets(
                        context, q, exclude_terms, relevance_signals,
                        since, max_scrolls=3,
                    )
                    _progress(f"  -> {len(kw_tweets)} tweets")
                    all_replies.extend(kw_tweets)
                    await asyncio.sleep(2)
        finally:
            await browser.close()

    new_tweets: list[dict] = []
    seen_ids: set[str] = set()
    for td in all_replies:
        tid = td["tweet_id"]
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        if insert_tweet(td):
            new_tweets.append(td)

    _progress(f"Done! {len(new_tweets)} new replies collected.")

    notif_cfg = config.get("notification", {})
    if notif_cfg.get("email", {}).get("enabled"):
        try:
            send_email_digest(new_tweets, config)
        except Exception as e:
            log.error("Email failed: %s", e)

    csv_cfg = notif_cfg.get("csv", {})
    if csv_cfg.get("enabled", True):
        csv_path = os.path.join(BASE_DIR, csv_cfg.get("path", "data/feedback_latest.csv"))
        export_to_csv(new_tweets, csv_path)

    return new_tweets


def collect_feedback(since: datetime, progress_cb=None) -> list[dict]:
    """Sync wrapper for the async run() — safe to call from Streamlit."""
    return asyncio.run(run(since, progress_cb=progress_cb))


def main():
    parser = argparse.ArgumentParser(
        description="Collect Indus feedback from @SarvamAI tweet replies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python collector.py                            # last 24 hours
  python collector.py --since "2026-02-25"       # from Feb 25
  python collector.py --since 7d                 # last 7 days
  python collector.py --since 2w                 # last 2 weeks
""",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help='Collect replies since this date/time. '
             'Accepts: "2026-02-25", "2026-02-25 14:00", "3d", "12h", "2w". '
             "Defaults to last 24 hours.",
    )
    args = parser.parse_args()
    since = parse_since(args.since)
    asyncio.run(run(since))


if __name__ == "__main__":
    main()
