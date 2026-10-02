import asyncio
from pathlib import Path
from datetime import datetime, timezone

async def capture_public_profile(username):
    # Screenshot is only attempted for an already-confirmed public ACTIVE transition.
    from playwright.async_api import async_playwright

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{username}_{stamp}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
        )
        page = await context.new_page()
        await page.goto(
            f"https://www.instagram.com/{username}/",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        await page.screenshot(path=str(path), full_page=True)
        await browser.close()

    return str(path)
