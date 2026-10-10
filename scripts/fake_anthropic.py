"""Minimal fake of the Anthropic Messages API for CI. It lets the REAL LiteLLM code path
(request formation, response parsing, guardrail classifier JSON, judge JSON, Langfuse
callbacks) run without an API key. It does not test model quality."""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TAG = re.compile(r"\[([\w.\-]+#\d+)\]")
OFF_TOPIC = ("poem", "pizza", "python script", "world cup", "koshari")
HARMFUL = ("jam the cell", "take down the core")


def _text(x) -> str:
    if isinstance(x, str):
        return x
    return " ".join(b.get("text", "") for b in x if isinstance(b, dict))


CELL = re.compile(r"'cell_id':\s*'([^']+)'")
KPI = re.compile(r"'kpi':\s*'([^']+)'")


def tool_turn(req: dict, first_user: str):
    """Scripted tool use for the investigation agent: kpi_profile, search_runbooks,
    ticket_history, then a text summary. Returns Anthropic content blocks."""
    done = sum(1 for m in req.get("messages", []) if isinstance(m.get("content"), list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result")
    cell = (CELL.search(first_user) or [None, "CELL_001"])[1]
    kpi = (KPI.search(first_user) or [None, "prb_utilization_pct"])[1]
    plan = [("kpi_profile", {"cell_id": cell, "kpi": kpi}),
            ("search_runbooks", {"query": f"{kpi.replace('_', ' ')} high utilization"}),
            ("ticket_history", {"cell_id": cell})]
    if done < len(plan):
        name, args = plan[done]
        return [{"type": "tool_use", "id": f"toolu_{done}", "name": name, "input": args}], "tool_use"
    return [{"type": "text", "text": "Investigation summary: the KPI is abnormal; "
                                     "runbook and history reviewed."}], "end_turn"


def reply(system: str, user: str) -> str:
    low = user.lower()
    if "investigation agent" in system:
        return "Investigation summary: tool budget reached; evidence gathered so far reviewed."
    if system.startswith("You are an input filter"):
        label = ("off_topic" if any(w in low for w in OFF_TOPIC)
                 else "harmful" if any(w in low for w in HARMFUL) else "on_topic")
        return json.dumps({"label": label})
    if system.startswith("You grade a RAG answer"):
        ans = user.split("Answer:", 1)[-1].split("Context:", 1)[0].lower()
        abstained = "does not cover" in ans
        return json.dumps({"correct": not abstained, "faithful": True, "abstained": abstained})
    tag = TAG.search(user)
    if "incident report" in system:
        return "Summary: capacity incident. Root cause per runbook. Follow-ups: capacity review."
    if "NOC engineer" in system:
        return f"Likely capacity issue on the cell. Next actions per [{tag.group(1)}]." if tag \
            else "Insufficient data."
    if "network operations assistant" in system:
        return (f"Based on the runbook [{tag.group(1)}], follow the documented steps." if tag
                else "The documentation does not cover this.")
    return "OK"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, {"ok": True})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        system = _text(req.get("system", ""))
        users = [m for m in req.get("messages", []) if m.get("role") == "user"]
        user = _text(users[-1]["content"]) if users else ""
        if req.get("tools") and "investigation agent" in system:
            first = _text(users[0]["content"]) if users else ""
            blocks, stop = tool_turn(req, first)
            text = " ".join(b.get("text", "") for b in blocks)
        else:
            text, stop = reply(system, user), "end_turn"
            blocks = [{"type": "text", "text": text}]
        self._send(200, {
            "id": "msg_fake", "type": "message", "role": "assistant",
            "model": req.get("model", "fake"), "stop_reason": stop, "stop_sequence": None,
            "content": blocks,
            "usage": {"input_tokens": max(1, len(user) // 4), "output_tokens": max(1, len(text) // 4)},
        })

    def log_message(self, *a):  # keep CI logs quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
