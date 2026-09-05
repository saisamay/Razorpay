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
            "status": response.status,
            "headers": response.headers
        })

print("Starting browser verification script...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="/usr/bin/google-chrome",
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )

    # 1. Desktop Viewport Test
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("console", handle_console)
    page.on("response", handle_response)

    print("\n--- Step 1: Navigating to Dashboard (/) ---")
    page.goto("http://127.0.0.1:5173/")
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{ARTIFACT_DIR}/dashboard_desktop.png")
    dashboard_text = page.inner_text("body")
    print(f"Dashboard title: {page.title()}")

    print("\n--- Step 2: Navigating to Case Explorer (/cases) ---")
    # Click sidebar or navigation button for cases
    cases_nav = page.query_selector("text=Recovery Cases") or page.query_selector("text=Cases")
    if cases_nav:
        cases_nav.click()
    else:
        page.goto("http://127.0.0.1:5173/") # Fallback
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{ARTIFACT_DIR}/case_explorer_desktop.png")
    cases_text = page.inner_text("body")

    print("\n--- Step 3: Select Case rc_demo_2001 ---")
    case_row = page.query_selector("text=rc_demo_2001")
    if case_row:
        print("Found rc_demo_2001 in table, clicking...")
        case_row.click()
        page.wait_for_timeout(2500)
    else:
        print("rc_demo_2001 not directly visible in table, selecting first row if available...")
        rows = page.query_selector_all("tbody tr")
        if rows:
            rows[0].click()
            page.wait_for_timeout(2500)

    page.screenshot(path=f"{ARTIFACT_DIR}/case_detail_desktop.png")
    case_detail_text = page.inner_text("body")

    print("\n--- Step 4: Navigating to Experiments (/experiments) ---")
    exp_nav = page.query_selector("text=Experiments & F4") or page.query_selector("text=Experiments")
    if exp_nav:
        exp_nav.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{ARTIFACT_DIR}/experiments_desktop.png")

    print("\n--- Step 5: Navigating to Operations (/operations) ---")
    ops_nav = page.query_selector("text=Recovery Operations") or page.query_selector("text=Operations")
    if ops_nav:
        ops_nav.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{ARTIFACT_DIR}/operations_desktop.png")

    print("\n--- Step 6: Navigating to Governance (/governance) ---")
    gov_nav = page.query_selector("text=F5 Governance") or page.query_selector("text=Governance")
    if gov_nav:
        gov_nav.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{ARTIFACT_DIR}/governance_desktop.png")

    print("\n--- Step 7: Navigating to Evidence (/evidence) ---")
    ev_nav = page.query_selector("text=Audit & Evidence") or page.query_selector("text=Evidence")
    if ev_nav:
        ev_nav.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{ARTIFACT_DIR}/evidence_desktop.png")

    # 2. Tablet Viewport Test
    print("\n--- Step 8: Tablet Viewport Test (768x1024) ---")
    context_tablet = browser.new_context(viewport={"width": 768, "height": 1024})
    page_tablet = context_tablet.new_page()
    page_tablet.goto("http://127.0.0.1:5173/")
    page_tablet.wait_for_timeout(1500)
    page_tablet.screenshot(path=f"{ARTIFACT_DIR}/dashboard_tablet.png")

    cases_tab_nav = page_tablet.query_selector("text=Recovery Cases") or page_tablet.query_selector("text=Cases")
    if cases_tab_nav:
        cases_tab_nav.click()
        page_tablet.wait_for_timeout(1500)
        page_tablet.screenshot(path=f"{ARTIFACT_DIR}/case_explorer_tablet.png")

    browser.close()

# Save collected logs and evidence
evidence_report = {
    "console_logs": console_logs,
    "network_requests": network_requests,
    "dashboard_sample_text": dashboard_text[:2000],
    "cases_sample_text": cases_text[:2000],
    "case_detail_sample_text": case_detail_text[:3000]
}

with open(f"{ARTIFACT_DIR}/evidence.json", "w") as f:
    json.dump(evidence_report, f, indent=2)

print(f"\nVerification finished! Screenshots and evidence saved to {ARTIFACT_DIR}")
