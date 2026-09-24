"""Chainlit chat UI. Plain text -> /ask.  '/incident <cell_id> <kpi> [description]' -> agent."""
import os

import chainlit as cl
import httpx

API = os.getenv("API_URL", "http://api:8000")
HEADERS = {"X-API-Key": os.getenv("API_KEY", "")}
HELP = ("Ask a question about runbooks, or open an incident:\n\n"
        "`/incident CELL_001 prb_utilization_pct PRB above 85%`")


async def _post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{API}{path}", json=payload, headers=HEADERS)
        r.raise_for_status()
        return r.json()


@cl.on_chat_start
async def start():
    await cl.Message(content=HELP).send()


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
    except httpx.HTTPStatusError as e:
        await cl.Message(content=f"API error {e.response.status_code}: {e.response.text[:300]}").send()


async def incident(text: str):
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        await cl.Message(content=HELP).send()
        return
    payload = {"cell_id": parts[1], "kpi": parts[2],
               "description": parts[3] if len(parts) > 3 else ""}
    out = await _post("/incident", payload)
    await cl.Message(content=f"**KPI profile:** `{out['profile']}`\n\n"
                             f"**Diagnosis:**\n{out['diagnosis']}").send()
    if out["status"] != "awaiting_approval":
        return
    res = await cl.AskActionMessage(
        content="Create a ticket and draft the incident report?",
        actions=[cl.Action(name="approve", payload={"approve": True}, label="Approve"),
                 cl.Action(name="reject", payload={"approve": False}, label="Reject")],
    ).send()
    approve = bool(res) and res.get("name") == "approve"
    done = await _post(f"/incident/{out['thread_id']}/decision", {"approve": approve})
    if approve:
        await cl.Message(content=f"Ticket `{done['ticket']['id']}` created.\n\n{done['report']}").send()
    else:
        await cl.Message(content="Rejected. No ticket created.").send()
