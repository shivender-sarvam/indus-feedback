"""
Login Helper
~~~~~~~~~~~~
Opens a real Chrome browser so you can log in to X manually.
Automatically detects when login succeeds and saves cookies.

Run:  python login_helper.py
"""

import asyncio
import json
import os

from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "data", "cookies.json")


async def main():
    os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=50,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        """)

        page = await context.new_page()

        print("\n" + "=" * 55)
        print("  Chrome window is open.")
        print("  Log in to X normally.")
        print("  I'll auto-detect when you're logged in.")
        print("=" * 55 + "\n")

        await page.goto("https://x.com", wait_until="domcontentloaded")

        # Poll cookies every 3 seconds for up to 5 minutes
        print("Waiting for login...")
        for attempt in range(100):
            await asyncio.sleep(3)
            pw_cookies = await context.cookies()
            cookie_names = {c["name"] for c in pw_cookies}

            if "auth_token" in cookie_names and "ct0" in cookie_names:
                print("Login detected!")
                await asyncio.sleep(2)  # let cookies settle
                break

            if attempt % 10 == 9:
                print(f"  Still waiting... ({(attempt+1)*3}s elapsed)")
        else:
            print("Timed out waiting for login.")

        # Final cookie grab
        pw_cookies = await context.cookies()
        twikit_cookies = {c["name"]: c["value"] for c in pw_cookies}

        auth_token = twikit_cookies.get("auth_token")
        ct0 = twikit_cookies.get("ct0")

        if auth_token and ct0:
            with open(COOKIES_PATH, "w") as f:
                json.dump(twikit_cookies, f, indent=2)
            print(f"\nCookies saved to {COOKIES_PATH}")
            print(f"  auth_token: {auth_token[:10]}...")
            print(f"  ct0: {ct0[:10]}...")
            print(f"  ({len(twikit_cookies)} total cookies)")
            print("\nRun:  python collector.py --since 7d")
        else:
            print("\nWARNING: auth_token or ct0 not found.")
            print(f"Cookies found: {list(twikit_cookies.keys())}")
            if twikit_cookies:
                with open(COOKIES_PATH, "w") as f:
                    json.dump(twikit_cookies, f, indent=2)
                print("Saved what we have — might still work.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
