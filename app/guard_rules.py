"""Deterministic guardrail rules. Pure Python (no heavy imports) so they are unit-testable."""
import re

INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    (r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|your|all|any|the)\b"
     r".{0,20}\b(instructions?|rules?|prompts?|guardrails?|guidelines?)\b"),
    (r"\b(reveal|show|print|repeat|output|leak)\b.{0,20}\b(system|hidden|initial|secret)\b"
     r".{0,10}\b(prompt|instructions?|message)\b"),
    r"\byou are now\b",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"\bpretend (to be|you are)\b",
    r"</?\s*(system|assistant|instructions?)\s*>",
    r"\bnew instructions?\s*:",
]]

PRIVACY_PATTERN = re.compile(
    r"\b(locate|track|geolocate|find the location of|where is)\b.{0,50}"
    r"\b(subscriber|imsi|msisdn|imei|customer|user)\b", re.IGNORECASE)

PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PHONE", re.compile(r"\+\d[\d\s\-()]{7,16}\d")),
    ("SUBSCRIBER_ID", re.compile(r"(?<!\d)\d{11,15}(?!\d)")),  # IMSI / IMEI / MSISDN
]

CITATION = re.compile(r"\[[\w.\-]+#\d+\]")
ABSTAIN = re.compile(
    r"(does not|doesn't|do not|don't|did not|didn't)\s+(cover|contain|include|say|specify|"
    r"mention|provide|address)|not (covered|specified|documented|available|mentioned)|"
    r"insufficient|no (information|documentation)", re.IGNORECASE)

REFUSALS = {
    "injection": "I can't follow instructions that try to change my rules or expose my "
                 "configuration. Ask me about network operations instead.",
    "off_topic": "I can only help with telecom network operations: KPIs, alarms, runbooks, "
                 "incidents and change procedures.",
    "harmful": "I can't help with attacking or disrupting networks or with tracking "
               "individual subscribers.",
    "privacy": "I can't help locate or identify individual subscribers.",
}


def redact(text: str) -> tuple[str, list[str]]:
    """Replace emails, phone numbers and subscriber identifiers with placeholders."""
    found = []
    for label, pat in PII_PATTERNS:
        if pat.search(text):
            found.append(label)
            text = pat.sub(f"[{label}]", text)
    return text, found


def rule_check(text: str) -> str | None:
    """Return a block label if a deterministic rule matches, else None."""
    if any(p.search(text) for p in INJECTION_PATTERNS):
        return "injection"
    if PRIVACY_PATTERN.search(text):
        return "privacy"
    return None


def has_grounding(text: str) -> bool:
    return bool(CITATION.search(text) or ABSTAIN.search(text))
