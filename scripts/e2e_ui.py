"""Drive the Chainlit UI in a headless browser: ask a question, open an incident, approve.
Env: UI_URL, UI_EXPECT (text that must appear in the answer)."""
import os
import sys

from playwright.sync_api import sync_playwright

UI = os.getenv("UI_URL", "http://localhost:8080")
# Per-user logins: the approver runs the happy path; the operator (optional) proves that a
# user without the approver role cannot approve; a wrong key must not get in.
APPROVER = (os.getenv("UI_USER", "ci-approver"), os.getenv("UI_KEY", ""))
OPERATOR = (os.getenv("UI_OPERATOR_USER", ""), os.getenv("UI_OPERATOR_KEY", ""))
EXPECT = os.getenv("UI_EXPECT", "")  # optional extra text to require in the answer


def send(page, box, text: str, attempts: int = 5) -> None:
    """Type into the composer and submit, verifying the text actually landed first.
    Right after page load Chainlit is still finishing its socket.io handshake; text typed
    during that window gets silently wiped when the session settles, so retry until the
    composer holds what we typed before clicking submit."""
    for i in range(attempts):
        box.click()
        box.fill("")
        box.press_sequentially(text, delay=15)
        page.wait_for_timeout(400)
        if box.input_value() == text:
            page.locator("#chat-submit").click()
            return
        if i == attempts - 1:
            raise AssertionError(f"composer would not hold text after {attempts} attempts "
                                 f"(last value: {box.input_value()!r})")
        page.wait_for_timeout(600)




def login(page, user: str, key: str) -> bool:
    """Sign in through the real login form. Returns True if we reach the chat."""
    page.goto(UI, wait_until="domcontentloaded")
    page.locator("#email").wait_for(timeout=60000)
    page.locator("#email").fill(user)
    page.locator("#password").fill(key)
    page.get_by_role("button", name="Sign In").click()
    try:
        page.locator("#chat-input").wait_for(timeout=15000)
        return True
    except Exception:  # noqa: BLE001 -- staying on the login page is the expected "no"
        return False


def settle(page):
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)  # let the socket.io session finish settling

with sync_playwright() as p:
    browser = p.chromium.launch()
    diag = []

    def new_page():
        # Force a well-formed locale. Headless Chromium can otherwise inherit a POSIX locale
        # like "en-US@posix" from the OS, which fails Chainlit's own language validation.
        pg = browser.new_page(locale="en-US")
        pg.on("console", lambda m: diag.append(f"[console:{m.type}] {m.text[:300]}"))
        pg.on("pageerror", lambda e: diag.append(f"[pageerror] {e}"))
        pg.on("response", lambda r: diag.append(f"[http {r.status}] {r.url}") if r.status >= 400 else None)
        return pg

    page = new_page()

    def dump_diagnostics(label: str) -> None:
        print(f"--- diagnostics: {label} ---")
        print("url:", page.url)
        counts: dict[str, int] = {}
        for line in diag:
            counts[line] = counts.get(line, 0) + 1
        print(f"console/network events ({len(diag)} total, {len(counts)} unique):")
        for line, n in list(counts.items())[-30:]:
            print(f"  x{n}" if n > 1 else "  ", line)
        print("--- page text (tail) ---")
        try:
            print(page.inner_text("body")[-2500:])
        except Exception as e:  # noqa: BLE001
            print("(could not read body text:", e, ")")

    try:
        # 1) a wrong key must not get in
        assert not login(page, APPROVER[0], "definitely-not-the-key"), "bad key was accepted"
        print("PASS  UI rejects a wrong key")

        # 2) approver: question, incident, approve, ticket
        assert login(page, *APPROVER), "approver could not sign in"
        box = page.locator("#chat-input")
        settle(page)
        send(page, box, "What is the ping-pong handover threshold?")
        page.get_by_text("Sources:").first.wait_for(timeout=90000)
        if EXPECT:
            page.get_by_text(EXPECT).first.wait_for(timeout=10000)
        print("PASS  UI question answered with sources")

        send(page, box, "/incident CELL_001 prb_utilization_pct PRB above 85%")
        page.get_by_text("Create a ticket and draft the incident report?").wait_for(timeout=120000)
        page.get_by_role("button", name="Approve").click()
        page.locator("text=/Ticket .* created/").wait_for(timeout=120000)
        print("PASS  UI incident flow: diagnosis, approval, ticket (as the approver)")

        # 3) operator: can open an incident but the approval is refused by the API
        if OPERATOR[0] and OPERATOR[1]:
            page = new_page()
            assert login(page, *OPERATOR), "operator could not sign in"
            box = page.locator("#chat-input")
            settle(page)
            send(page, box, "/incident CELL_002 rrc_setup_success_rate RRC failures")
            page.get_by_text("Create a ticket and draft the incident report?").wait_for(timeout=120000)
            page.get_by_role("button", name="Approve").click()
            page.get_by_text("approver role required").wait_for(timeout=60000)
            print("PASS  UI: an operator cannot approve (403 from the API, surfaced to the user)")
    except Exception as e:  # noqa: BLE001
        print("FAIL:", repr(e)[:500])
        dump_diagnostics("failure")
        sys.exit(1)
    finally:
        browser.close()
