"""Chainlit chat UI with per-user login. A user signs in with their API-key name and key
(username = key name, password = the key); the backend's /whoami decides who that is and
which role they hold, and every request the UI makes is sent with THAT user's key, so
approvals in the audit log are attributed to the real person, not to a shared UI account.

Plain text -> /ask.  '/incident <cell_id> <kpi> [description]' -> agent."""
import os
import re

import chainlit as cl
import httpx

API = os.getenv("API_URL", "http://api:8000")
# An incident makes several model calls; on a CPU-only 7B setup that takes minutes.
TIMEOUT_S = float(os.getenv("UI_TIMEOUT_S", "900"))
HELP = ("Ask a question about runbooks, or open an incident:\n\n"
        "`/incident CELL_002 rrc_setup_success_rate RRC setup success rate below 98.5%`")

# Keys live only in this process's memory (never in the browser's JWT). After a UI restart
# users simply sign in again.
_KEYS: dict[str, str] = {}


@cl.password_auth_callback
async def auth_callback(username: str, password: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{API}/whoami", headers={"X-API-Key": password})
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or r.json().get("name") != username:
        return None
    who = r.json()
    _KEYS[who["name"]] = password
    return cl.User(identifier=who["name"], metadata={"role": who["role"]})


def _key() -> str | None:
    user = cl.user_session.get("user")
    return _KEYS.get(user.identifier) if user else None


async def _post(path: str, payload: dict) -> dict:
    key = _key()
    if not key:
        raise PermissionError("session expired, please sign in again")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.post(f"{API}{path}", json=payload, headers={"X-API-Key": key})
        r.raise_for_status()
        return r.json()


@cl.set_starters
async def starters(_user=None):
    # Shown centred on the empty chat; a click sends the message. They replace the old
    # welcome message (a message would hide them).
    return [
        cl.Starter(label="RRC setup success below 98.5%",
                   message="/incident CELL_002 rrc_setup_success_rate RRC setup success rate below 98.5%"),
        cl.Starter(label="Handover success below 97%",
                   message="/incident CELL_003 handover_success_rate Handover success rate below 97%"),
        cl.Starter(label="Ask the runbooks",
                   message="What is the ping-pong handover threshold?"),
    ]


@cl.on_message
async def on_message(msg: cl.Message):
    text = msg.content.strip()
    try:
        if text.startswith("/incident"):
            await incident(text)
        else:
            out = await _post("/ask", {"question": text})
            src = ", ".join(sorted({f"{s['source']}#{s['chunk']}" for s in out["sources"]}))
            tail = f"\n\n_Sources: {src}_" if src else ""
            await cl.Message(content=out["answer"] + tail).send()
    except PermissionError as e:
        await cl.Message(content=str(e)).send()
    except httpx.HTTPStatusError as e:
        await cl.Message(content=f"API error {e.response.status_code}: {e.response.text[:300]}").send()
    except httpx.TransportError as e:
        await cl.Message(content=(
            f"No answer from the API ({type(e).__name__}) after at most {TIMEOUT_S:.0f}s. The model "
            "may be too slow on this hardware: try a smaller model or raise UI_TIMEOUT_S.")).send()


_SEV = re.compile(r"Severity:\s*(P[1-4][^\n]*|undetermined[^\n]*)", re.IGNORECASE)


def _severity(text: str) -> str:
    found = _SEV.findall(text or "")
    return found[-1].strip() if found else "not stated"


async def incident(text: str):
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        await cl.Message(content=HELP).send()
        return
    payload = {"cell_id": parts[1], "kpi": parts[2],
               "description": parts[3] if len(parts) > 3 else ""}
    out = await _post("/incident", payload)
    async with cl.Step(name="Investigation", type="tool") as step:
        step.output = "\n".join(f"- {t['tool']}: {t['outcome']}"
                                for t in out.get("investigation") or []) or "no tools recorded"
    await cl.Message(content=f"**KPI profile:** `{out['profile']}`\n\n"
                             f"**Diagnosis:**\n{out['diagnosis']}").send()
    if out["status"] != "awaiting_approval":
        return
    res = await cl.AskActionMessage(
        content=(f"### Approval needed\n"
                 f"**Proposed action:** create a ticket for `{parts[1]}` / `{parts[2]}` and draft "
                 f"the incident report\n\n**Severity:** {_severity(out['diagnosis'])}\n\n"
                 "Nothing is created until an approver confirms."),
        actions=[cl.Action(name="approve", payload={"approve": True}, label="Approve"),
                 cl.Action(name="reject", payload={"approve": False}, label="Reject")],
    ).send()
    approve = bool(res) and res.get("name") == "approve"
    try:
        done = await _post(f"/incident/{out['thread_id']}/decision", {"approve": approve})
    except httpx.HTTPStatusError as e:
        who = "approver role required" if e.response.status_code == 403 else e.response.text[:200]
        await cl.Message(content=f"Decision not recorded ({e.response.status_code}): {who}").send()
        return
    if not approve:
        await cl.Message(content="Rejected. No ticket created.").send()
        return
    tk = done["ticket"]
    await cl.Message(content=f"**Incident report**\n\n{done['report']}").send()
    # The card is the last thing on screen, so the outcome is visible without scrolling.
    await cl.Message(content=(
        f"### Ticket `{tk['id']}` created\n\n| Field | Value |\n|---|---|\n"
        f"| Cell / KPI | `{parts[1]}` / `{parts[2]}` |\n"
        f"| Severity | {_severity(out['diagnosis'])} |\n"
        f"| Approved by | {tk.get('approved_by') or 'n/a'} |\n"
        f"| Created | {tk.get('created_at', '')[:19].replace('T', ' ')} UTC |")).send()
