"""Drive the Chainlit UI in a headless browser: ask a question, open an incident, approve.
Env: UI_URL, UI_EXPECT (text that must appear in the answer)."""
import os
import sys

from playwright.sync_api import sync_playwright

UI = os.getenv("UI_URL", "http://localhost:8080")
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


with sync_playwright() as p:
    browser = p.chromium.launch()
    # Force a well-formed locale. Headless Chromium can otherwise inherit a POSIX locale
    # like "en-US@posix" from the OS, which fails Chainlit's own language validation on
    # /project/settings and /project/translations (422), so the composer never renders.
    page = browser.new_page(locale="en-US")

    diag = []
    page.on("console", lambda m: diag.append(f"[console:{m.type}] {m.text[:300]}"))
    page.on("pageerror", lambda e: diag.append(f"[pageerror] {e}"))
    page.on("requestfailed", lambda r: diag.append(f"[reqfailed] {r.url} {r.failure}"))
    page.on("response", lambda r: diag.append(f"[http {r.status}] {r.url}") if r.status >= 400 else None)

    def dump_diagnostics(label: str) -> None:
        print(f"--- diagnostics: {label} ---")
        print("url:", page.url)
        html = page.content()
        print("html length:", len(html))
        print("html head:", html[:800].replace("\n", " "))
        # Dedupe: a single repeated warning (browser console spam, a noisy retried
        # request) can otherwise fill the entire output and push the one thing that
        # actually matters -- the page text tail below -- out of any reasonable
        # tail-slice a CI log viewer applies.
        counts: dict[str, int] = {}
        for line in diag:
            counts[line] = counts.get(line, 0) + 1
        unique = list(counts.items())
        print(f"console/network events ({len(diag)} total, {len(unique)} unique):")
        for line, n in unique[-30:]:
            print(f"  x{n}" if n > 1 else "  ", line)
        print("--- page text (tail) ---")
        try:
            print(page.inner_text("body")[-2500:])
        except Exception as e:  # noqa: BLE001
            print("(could not read body text:", e, ")")

    try:
        resp = page.goto(UI, wait_until="domcontentloaded", timeout=30000)
        print("goto status:", resp.status if resp else None, "url:", page.url)
        box = page.locator("#chat-input")
        box.wait_for(timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(1500)  # let the socket.io session finish settling

        send(page, box, "What is the ping-pong handover threshold?")
        page.get_by_text("Sources:").first.wait_for(timeout=90000)
        if EXPECT:
            page.get_by_text(EXPECT).first.wait_for(timeout=10000)
        print("PASS  UI question answered with sources")

        send(page, box, "/incident CELL_001 prb_utilization_pct PRB above 85%")
        page.get_by_text("Create a ticket and draft the incident report?").wait_for(timeout=120000)
        page.get_by_role("button", name="Approve").click()
        page.locator("text=/Ticket .* created/").wait_for(timeout=120000)
        print("PASS  UI incident flow: diagnosis, approval, ticket")
    except Exception as e:  # noqa: BLE001
        print("FAIL:", repr(e)[:500])
        dump_diagnostics("failure")
        sys.exit(1)
    finally:
        browser.close()
