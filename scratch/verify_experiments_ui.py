import os
import json
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = "/home/samay/.gemini/antigravity/brain/3ff58177-9b1b-4ec3-a411-d52ff22fd6cf/screenshots"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

console_logs = []
network_requests = []

def handle_console(msg):
    console_logs.append({
        "type": msg.type,
        "text": msg.text,
        "location": msg.location
    })

def handle_response(response):
    if "/api/" in response.url:
        network_requests.append({
            "url": response.url,
            "method": response.request.method,
            "status": response.status
        })

print("Starting Experiments & F4 UI verification script...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="/usr/bin/google-chrome",
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )

    # 1. Desktop Viewport (1440x900) - State A (NOT ESTABLISHED)
    print("\n--- Step 1: Desktop Viewport Test - State A (NOT ESTABLISHED) ---")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("console", handle_console)
    page.on("response", handle_response)

    page.goto("http://127.0.0.1:5173/")
    page.wait_for_timeout(1000)

    # Click on Experiments sidebar link
    exp_link = page.query_selector("text=Experiments & F4") or page.query_selector("text=Experiments")
    if exp_link:
        exp_link.click()
        page.wait_for_timeout(2000)

    page.screenshot(path=f"{ARTIFACT_DIR}/experiments_f4_desktop.png")
    page_text = page.inner_text("body")
    print("Experiments page header:", page_text[:400])

    # 2. Tablet Viewport (768x1024) - State A
    print("\n--- Step 2: Tablet Viewport Test (768x1024) ---")
    context_tab = browser.new_context(viewport={"width": 768, "height": 1024})
    page_tab = context_tab.new_page()
    page_tab.goto("http://127.0.0.1:5173/")
    page_tab.wait_for_timeout(1000)
    exp_link_tab = page_tab.query_selector("text=Experiments & F4") or page_tab.query_selector("text=Experiments")
    if exp_link_tab:
        exp_link_tab.click()
        page_tab.wait_for_timeout(2000)
    page_tab.screenshot(path=f"{ARTIFACT_DIR}/experiments_f4_tablet.png")

    browser.close()

evidence_report = {
    "console_logs": console_logs,
    "network_requests": network_requests,
    "page_text_sample": page_text[:2500]
}

with open(f"{ARTIFACT_DIR}/experiments_evidence.json", "w") as f:
    json.dump(evidence_report, f, indent=2)

print(f"\nState A verification finished! Artifacts saved to {ARTIFACT_DIR}")
