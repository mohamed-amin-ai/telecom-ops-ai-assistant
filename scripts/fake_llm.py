"""Minimal fake LLM server (OpenAI-compatible chat-completions wire format) for CI. It lets the REAL LiteLLM code path
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
    ticket_history, then a text summary. Returns (text, tool_calls)."""
    done = sum(1 for m in req.get("messages", []) if m.get("role") == "tool")
    cell = (CELL.search(first_user) or [None, "CELL_001"])[1]
    kpi = (KPI.search(first_user) or [None, "prb_utilization_pct"])[1]
    plan = [("kpi_profile", {"cell_id": cell, "kpi": kpi}),
            ("search_runbooks", {"query": f"{kpi.replace('_', ' ')} high utilization"}),
            ("ticket_history", {"cell_id": cell})]
    if done < len(plan):
        name, args = plan[done]
        return "", [{"id": f"call_{done}", "type": "function",
                     "function": {"name": name, "arguments": json.dumps(args)}}]
    return ("Investigation summary: the KPI is abnormal; runbook and history reviewed.", [])


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
        msgs = req.get("messages", [])
        system = " ".join(_text(m.get("content") or "") for m in msgs if m.get("role") == "system")
        users = [m for m in msgs if m.get("role") == "user"]
        user = _text(users[-1]["content"]) if users else ""
        tool_calls = []
        if req.get("tools") and "investigation agent" in system:
            first = _text(users[0]["content"]) if users else ""
            text, tool_calls = tool_turn(req, first)
        else:
            text = reply(system, user)
        message = {"role": "assistant", "content": text or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        prompt_tokens, completion_tokens = max(1, len(user) // 4), max(1, len(text) // 4)
        self._send(200, {
            "id": "chatcmpl-fake", "object": "chat.completion", "created": 0,
            "model": req.get("model", "fake"),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        })

    def log_message(self, *a):  # keep CI logs quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
