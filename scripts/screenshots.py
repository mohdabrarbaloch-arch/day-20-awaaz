"""Capture real screenshots of the running app with Playwright."""

import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# Unique per run so re-running the script never hits a 409 on register.
EMAIL = f"shot{int(time.time())}@awaaz.app"
PASSWORD = "shotpass123"


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])

        # ---- Desktop -------------------------------------------------
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(600)
        await page.screenshot(path=OUT / "auth.png")
        print("auth.png")

        # Register through the real UI.
        await page.click('.tab[data-tab="register"]')
        await page.fill('#register-form input[name="display_name"]', "Abrar")
        await page.fill('#register-form input[name="email"]', EMAIL)
        await page.fill('#register-form input[name="password"]', PASSWORD)
        await page.click('#register-form button[type="submit"]')
        await page.wait_for_selector("#app:not(.is-hidden)", timeout=15000)
        await page.wait_for_timeout(1200)
        await page.screenshot(path=OUT / "upload.png")
        print("upload.png")

        # Seed one real transcript for this account so the history and the
        # detail drawer have something genuine to show.
        token = await page.evaluate("localStorage.getItem('awaaz.token')")
        sample = Path("/tmp/asrtest/sample.wav")
        if sample.exists():
            await page.evaluate(
                """async ([tok, b64]) => {
                    const bin = atob(b64);
                    const bytes = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                    const fd = new FormData();
                    fd.append('file', new Blob([bytes], {type: 'audio/wav'}), 'jfk-speech.wav');
                    await fetch('/api/transcriptions', {
                        method: 'POST',
                        headers: {Authorization: 'Bearer ' + tok},
                        body: fd,
                    });
                }""",
                [token, __import__("base64").b64encode(sample.read_bytes()).decode()],
            )
            # Wait for the background job to finish.
            for _ in range(40):
                await page.wait_for_timeout(1000)
                done = await page.evaluate(
                    """async (tok) => {
                        const r = await fetch('/api/transcriptions', {
                            headers: {Authorization: 'Bearer ' + tok},
                        });
                        const d = await r.json();
                        return d.items.some(i => i.status === 'completed');
                    }""",
                    token,
                )
                if done:
                    break
            await page.click("#refresh")
            await page.wait_for_timeout(1200)

        # Open the completed transcript from the history list.
        await page.wait_for_selector(".item", timeout=15000)
        await page.click(".item")
        await page.wait_for_selector(".seg", timeout=20000)
        await page.wait_for_timeout(700)
        await page.screenshot(path=OUT / "transcript.png")
        print("transcript.png")

        # ---- Mobile --------------------------------------------------
        m = await browser.new_page(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        await m.goto(BASE, wait_until="networkidle")
        await m.wait_for_timeout(500)
        await m.click('.tab[data-tab="login"]')
        await m.fill('#login-form input[name="email"]', EMAIL)
        await m.fill('#login-form input[name="password"]', PASSWORD)
        await m.click('#login-form button[type="submit"]')
        await m.wait_for_selector("#app:not(.is-hidden)", timeout=15000)
        await m.wait_for_timeout(1200)
        await m.screenshot(path=OUT / "mobile.png")
        print("mobile.png")

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
