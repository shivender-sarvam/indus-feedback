import sys
import os
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db, query_tweets
from collector import collect_feedback

st.set_page_config(
    page_title="Indus Feedback Dashboard",
    page_icon="🔍",
    layout="wide",
)

_VALID_USER = st.secrets.get("DASH_USER", os.environ.get("DASH_USER", "indus2026"))
_VALID_PASS = st.secrets.get("DASH_PASS", os.environ.get("DASH_PASS", "adminindus2026"))

_RANGE_OPTIONS = [
    "Last 2 hours",
    "Last 6 hours",
    "Last 8 hours",
    "Last 24 hours",
    "Last 3 days",
    "Last 7 days",
    "Last 14 days",
    "Last 30 days",
    "Custom",
]

_RANGE_HOURS = {
    "Last 2 hours": 2,
    "Last 6 hours": 6,
    "Last 8 hours": 8,
    "Last 24 hours": 24,
    "Last 3 days": 72,
    "Last 7 days": 168,
    "Last 14 days": 336,
    "Last 30 days": 720,
}


# ── auth ─────────────────────────────────────────────────────────────

def _check_login():
    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        """
        <div style="display:flex;justify-content:center;margin-top:80px;">
            <div style="max-width:380px;width:100%;text-align:center;">
                <h1 style="font-size:28px;margin-bottom:4px;">Indus Feedback</h1>
                <p style="color:#888;margin-bottom:32px;">Sign in to continue</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

            if submitted:
                if username == _VALID_USER and password == _VALID_PASS:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    return False


# ── fetch logic ──────────────────────────────────────────────────────

def _run_fetch(since_dt: datetime):
    st.session_state["fetch_log"] = []
    st.session_state["fetch_error"] = None

    def _progress(msg: str):
        st.session_state["fetch_log"].append(msg)

    try:
        new = collect_feedback(since_dt, progress_cb=_progress)
        st.session_state["fetch_result_count"] = len(new)
    except Exception as e:
        st.session_state["fetch_error"] = str(e)


# ── main dashboard ───────────────────────────────────────────────────

def _dashboard():
    init_db()

    st.markdown(
        '<h1 style="margin-bottom:0;">Indus Feedback Dashboard</h1>'
        '<p style="color:#888;margin-top:0;">Replies on @SarvamAI tweets + broader Indus mentions</p>',
        unsafe_allow_html=True,
    )

    # ── sidebar
    with st.sidebar:
        st.markdown("### Time Range")

        selected_range = st.selectbox(
            "Show replies from",
            _RANGE_OPTIONS,
            index=5,
        )

        now = datetime.now(timezone.utc)

        if selected_range == "Custom":
            today = now.date()
            week_ago = today - timedelta(days=7)

            col_from, col_to = st.columns(2)
            with col_from:
                date_from = st.date_input("From date", value=week_ago)
            with col_to:
                date_to = st.date_input("To date", value=today)

            col_tf, col_tt = st.columns(2)
            with col_tf:
                time_from = st.time_input("From time", value=time(0, 0))
            with col_tt:
                time_to = st.time_input("To time", value=time(23, 59))

            since_dt = datetime.combine(date_from, time_from).replace(tzinfo=timezone.utc)
            until_dt = datetime.combine(date_to, time_to).replace(tzinfo=timezone.utc)
        else:
            hours = _RANGE_HOURS[selected_range]
            since_dt = now - timedelta(hours=hours)
            until_dt = now

        # show the active window
        fmt = "%b %d, %I:%M %p"
        st.caption(f"{since_dt.strftime(fmt)}  →  {until_dt.strftime(fmt)} UTC")

        st.divider()

        st.markdown("### Fetch New Data")
        st.caption("Scrape fresh replies from X for this range")

        if st.button("Fetch from X", use_container_width=True, type="primary"):
            with st.spinner("Scraping replies from X… this takes ~2 min"):
                _run_fetch(since_dt)
            st.rerun()

        if st.session_state.get("fetch_error"):
            st.error(st.session_state["fetch_error"])
        elif st.session_state.get("fetch_result_count") is not None:
            n = st.session_state["fetch_result_count"]
            if n > 0:
                st.success(f"Fetched {n} new replies!")
            else:
                st.info("No new replies (all already in DB)")
            st.session_state["fetch_result_count"] = None

        if st.session_state.get("fetch_log"):
            with st.expander("Fetch log", expanded=False):
                for line in st.session_state["fetch_log"]:
                    st.text(line)

    # ── query DB for the selected window
    tweets = query_tweets(
        since_iso=since_dt.isoformat(),
        until_iso=until_dt.isoformat(),
    )

    # split by source
    timeline_tweets = [t for t in tweets if t.get("source_type") == "timeline_reply"]
    thread_tweets = [t for t in tweets if t.get("source_type") == "thread_reply"]
    keyword_tweets = [t for t in tweets if t.get("source_type") == "keyword_mention"]

    # ── metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(tweets))
    c2.metric("@SarvamAI Timeline", len(timeline_tweets))
    c3.metric("Indus Threads", len(thread_tweets))
    c4.metric("Broader Mentions", len(keyword_tweets))

    if not tweets:
        st.info(
            "No replies found in this window. "
            "Try a wider range or click **Fetch from X** to scrape new data."
        )
        return

    # ── three tabs
    tab_timeline, tab_threads, tab_mentions = st.tabs([
        f"@SarvamAI Timeline ({len(timeline_tweets)})",
        f"Indus Threads ({len(thread_tweets)})",
        f"Broader Mentions ({len(keyword_tweets)})",
    ])

    with tab_timeline:
        if not timeline_tweets:
            st.caption("No timeline replies in this window.")
        else:
            _render_grouped(timeline_tweets, "@SarvamAI")

    with tab_threads:
        if not thread_tweets:
            st.caption("No thread replies in this window.")
        else:
            _render_grouped(thread_tweets, "Indus")

    with tab_mentions:
        if not keyword_tweets:
            st.caption(
                "No broader mentions in this window. "
                "Click **Fetch from X** to search for keyword mentions."
            )
        else:
            _render_mentions(keyword_tweets)


def _render_grouped(tweets: list[dict], source_label: str):
    threads = defaultdict(list)
    for t in tweets:
        key = t.get("parent_text") or t.get("source_detail") or "Unknown thread"
        threads[key].append(t)

    for thread_name, replies in threads.items():
        parent_url = replies[0].get("parent_url", "")
        preview = thread_name[:140] + ("…" if len(thread_name) > 140 else "")

        source_detail = replies[0].get("source_detail", "")
        thread_author = source_detail.split("/")[0] if "/" in source_detail else f"@{source_label}"

        thread_link = ""
        if parent_url:
            thread_link = (
                f' &nbsp;<a href="{parent_url}" target="_blank" '
                f'style="color:#1d9bf0;text-decoration:none;font-size:13px;">'
                f'Open thread →</a>'
            )

        st.markdown(
            f'<div style="margin-top:24px;margin-bottom:8px;padding:10px 14px;'
            f'background:#16213e;border-radius:8px;border-left:4px solid #1d9bf0;">'
            f'<span style="color:#aaa;font-size:12px;">THREAD by {_esc(thread_author)}'
            f' · {len(replies)} replies</span>{thread_link}<br>'
            f'<span style="color:#ddd;font-size:14px;">{_esc(preview)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        for t in replies:
            _render_reply(t)


def _render_mentions(tweets: list[dict]):
    """Render keyword-search results grouped by search query."""
    by_query = defaultdict(list)
    for t in tweets:
        key = t.get("source_detail") or t.get("parent_text") or "search"
        by_query[key].append(t)

    for query, items in by_query.items():
        st.markdown(
            f'<div style="margin-top:24px;margin-bottom:8px;padding:10px 14px;'
            f'background:#1e3a2f;border-radius:8px;border-left:4px solid #2ecc71;">'
            f'<span style="color:#aaa;font-size:12px;">SEARCH QUERY'
            f' · {len(items)} results</span><br>'
            f'<span style="color:#ddd;font-size:14px;">{_esc(query)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        for t in items:
            _render_reply(t)


def _render_reply(t: dict):
    tweet_url = t.get("tweet_url", "")
    created = t.get("tweet_created_at", "")[:16].replace("T", " ")

    st.markdown(
        f"""
        <div style="
            border:1px solid #333;
            border-left:4px solid #555;
            border-radius:10px;
            padding:14px 18px;
            margin-bottom:8px;
            margin-left:16px;
            background:#1a1a2e;
            color:#e0e0e0;
        ">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <strong style="color:#fff;">{_esc(t.get('author_name', ''))}</strong>
                    <span style="color:#999;">@{_esc(t.get('author_handle', ''))}</span>
                </div>
                <span style="color:#777;font-size:12px;">{created}</span>
            </div>
            <p style="margin:8px 0 6px 0;line-height:1.5;color:#ccc;">{_esc(t.get('text', ''))}</p>
            <a href="{tweet_url}" target="_blank"
               style="color:#1d9bf0;font-size:13px;text-decoration:none;">
                View on X →
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


if _check_login():
    _dashboard()
