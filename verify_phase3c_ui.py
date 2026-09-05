import asyncio
import json
import os
from playwright.async_api import async_playwright

ARTIFACTS_DIR = "/home/samay/.gemini/antigravity/brain/3ff58177-9b1b-4ec3-a411-d52ff22fd6cf/screenshots"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

async def verify():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True
        )

        # 1. Desktop Viewport (1440 x 900)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()

        console_logs = []
        network_transactions = []

        page.on("console", lambda msg: console_logs.append({
            "type": msg.type,
            "text": msg.text
        }))

        async def handle_response(response):
            if "localhost:8000" in response.url or "127.0.0.1:8000" in response.url:
                req = response.request
                network_transactions.append({
                    "url": response.url,
                    "method": req.method,
                    "status": response.status,
                    "merchant_id_header": req.headers.get("x-merchant-id"),
                    "ok": response.ok
                })

        page.on("response", handle_response)

        print("Navigating Desktop to http://127.0.0.1:5173/governance")
        await page.goto("http://127.0.0.1:5173/governance", wait_until="networkidle")
        await asyncio.sleep(2)

        # Desktop Screenshot
        desktop_shot = os.path.join(ARTIFACTS_DIR, "governance_desktop_3c.png")
        await page.screenshot(path=desktop_shot, full_page=True)
        print(f"Desktop screenshot saved to {desktop_shot}")

        # 2. Tablet Viewport (768 x 1024)
        context_tablet = await browser.new_context(
            viewport={"width": 768, "height": 1024}
        )
        page_tablet = await context_tablet.new_page()

        page_tablet.on("response", handle_response)

        print("Navigating Tablet to http://127.0.0.1:5173/governance")
        await page_tablet.goto("http://127.0.0.1:5173/governance", wait_until="networkidle")
        await asyncio.sleep(2)

        tablet_shot = os.path.join(ARTIFACTS_DIR, "governance_tablet_3c.png")
        await page_tablet.screenshot(path=tablet_shot, full_page=True)
        print(f"Tablet screenshot saved to {tablet_shot}")

        await context_tablet.close()
        await context.close()
        await browser.close()

        # Save evidence JSON
        evidence = {
            "chrome_executable": "/usr/bin/google-chrome",
            "playwright_version": "1.62.0",
            "desktop_viewport": "1440x900",
            "tablet_viewport": "768x1024",
            "console_logs": console_logs,
            "network_transactions": network_transactions,
        }

        evidence_path = os.path.join(ARTIFACTS_DIR, "governance_evidence_3c.json")
        with open(evidence_path, "w") as f:
            json.dump(evidence, f, indent=2)

        print(f"Evidence JSON saved to {evidence_path}")

if __name__ == "__main__":
    asyncio.run(verify())
