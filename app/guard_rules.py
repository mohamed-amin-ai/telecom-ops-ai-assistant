"""Deterministic guardrail rules. Pure Python (no heavy imports) so they are unit-testable.

Attackers rarely type "ignore all previous instructions" verbatim, so every input is checked
in several normalized forms as well as as-written: Unicode-normalized with zero-width
characters removed and lookalike letters mapped to Latin, leetspeak-decoded, letters-only
(catches "i g n o r e"), reversed, ROT13, and any base64 segments decoded. These are
heuristics, not a proof of safety: a determined attacker can still phrase something the
patterns miss, which is why an LLM classifier and a human-approval gate sit behind them."""
import base64
import binascii
import codecs
import itertools
import re
import unicodedata

# ---------------------------------------------------------------- normalization
_CONFUSABLES = str.maketrans({
    # Cyrillic and Greek letters that render like Latin ones
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0445": "x",
    "\u0443": "y", "\u0456": "i", "\u0458": "j", "\u0455": "s", "\u04bb": "h", "\u0501": "d",
    "\u0410": "A", "\u0415": "E", "\u041e": "O", "\u0420": "P", "\u0421": "C", "\u0425": "X",
    "\u03bf": "o", "\u03b1": "a", "\u03b5": "e", "\u03c1": "p", "\u03b9": "i", "\u03bd": "v",
    "\u039f": "O", "\u0391": "A", "\u0395": "E", "\u0399": "I",
})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s"})


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")  # zero-width etc.


def normalize(text: str) -> str:
    text = _clean(text).translate(_CONFUSABLES)
    return re.sub(r"\s+", " ", text).strip()


def _b64_segments(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"[A-Za-z0-9+/]{16,}={0,2}", text):
        seg = m.group(0)
        try:
            raw = base64.b64decode(seg + "=" * (-len(seg) % 4), validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and sum(c.isprintable() for c in decoded) / len(decoded) > 0.9:
            out.append(normalize(decoded))
    return out


def variants(text: str) -> tuple[list[str], str]:
    """(texts to run the regexes over, letters-only form for the phrase check)."""
    base = normalize(text)
    # Confusable mapping turns genuine Cyrillic/Greek text into Latin gibberish, which is
    # right for catching "ign\u043ere" but makes native-script patterns (Russian, Greek)
    # unmatchable -- so the script-preserving form is checked as well.
    native = re.sub(r"\s+", " ", _clean(text)).strip()
    forms = [base, native, base.translate(_LEET), base[::-1], codecs.encode(base, "rot13"),
             *_b64_segments(base)]
    squashed = re.sub(r"[^a-z]", "", base.translate(_LEET).lower())
    return list(dict.fromkeys(forms)), squashed


# ---------------------------------------------------------------- injection rules
_VERBS = r"(?:ignore|disregard|forget|override|bypass|discard|neglect|skip|drop)"
_QUAL = r"(?:previous|prior|above|earlier|preceding|your|all|any|the|these|those)"
_OBJ = r"(?:instructions?|rules?|prompts?|guardrails?|guidelines?|polic(?:y|ies)|directives?)"
_SENS = r"(?:system|hidden|initial|secret|original|internal|developer)"

INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    rf"\b{_VERBS}\b.{{0,30}}\b{_QUAL}\b.{{0,20}}\b{_OBJ}\b",
    (rf"\b(?:reveal|show|print|repeat|output|leak|display|share|expose|dump|tell me)\b.{{0,25}}"
    rf"\b(?:your|the)\s+{_SENS}\s+(?:prompt|instructions?|rules)\b"),
    rf"\b(?:reveal|show|print|leak|expose|dump)\b.{{0,15}}\byour\s+{_SENS}\s+message\b",
    (r"\byour\b.{0,20}\b(?:initial|original|exact|full|complete)\b.{0,15}"
    r"\b(?:instructions?|prompt|rules)\b"),
    r"\b(?:you|your)\b.{0,30}\b(?:given|told|gave)\b.{0,40}\b(?:before|earlier|initially|at the start)\b",
    r"\brepeat\b.{0,15}\b(?:everything|all|the text|the words)\b.{0,20}\b(?:above|before|prior)\b",
    r"\bstarting with\s+['\"]?you are\b",
    r"\bdo anything now\b",
    (r"\b(?:without|no)\s+(?:any\s+)?(?:restrictions|limitations|limits|rules|filters|guardrails|"
    r"censorship)\b"),
    r"\byou(?:'re| are)\s+(?:now\s+)?(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken)\b",
    (r"\b(?:pretend|imagine|assume|suppose|act as if)\b.{0,40}\b(?:rules?|polic(?:y|ies)|"
    r"guardrails?|restrictions?|safety)\b.{0,30}\b(?:does not|do not|don't|doesn't|no longer|"
    r"aren't|isn't|off|disabled)\b"),
    (r"\byou (?:must|will|shall)\s+(?:now\s+)?(?:obey|follow)\b.{0,40}\b(?:following|these|my)\s+"
    r"(?:commands?|instructions?|orders?)\b"),
    rf"\binstead of your\s+{_OBJ}\b",
    (r"\b(?:disable|turn off|deactivate|remove)\b.{0,20}\b(?:the |your )?(?:safety|guardrails?|"
    r"filters?|content polic(?:y|ies))\b"),
    r"<\|(?:im_start|im_end|system|endoftext)\|>|\[/?inst\]|<<\s*/?sys\s*>>",
    r"(?m)^\s*#{2,}\s*(?:system|instructions?)\b",
    r"</?\s*(?:system|assistant|instructions?)\s*>",
    r"\bnew instructions?\s*:",
    (r"\b(?:developer|god|debug|maintenance) mode\b.{0,40}\b(?:guardrails?|safety|restrictions?|"
    r"disabled)\b"),
    r"\bdeveloper mode\b|\bjailbreak\b|\bpretend (?:to be|you are)\b|\byou are now\b",
    # exfiltration: getting secrets or the prompt into output, tickets, or messages
    (r"\b(?:append|include|add|attach|paste|put|send|post|email|mail|forward|upload|leak|write)\b"
    r".{0,50}\b(?:system prompt|your (?:instructions|rules|prompt))\b"),
    (r"\b(?:any|all|the|your|its)\s+(?:api[ _-]?keys?|secrets?|credentials|passwords|access tokens?)"
    r"\b.{0,30}\b(?:you (?:can )?see|you have|available to you|in your|from your|stored)\b"),
    (r"\b(?:send|email|post|forward)\b.{0,40}\b(?:all|every|any)\b.{0,20}\b(?:credentials|"
    r"passwords|secrets|api[ _-]?keys?)\b"),
    # any reference to the assistant's OWN prompt/configuration is an extraction attempt
    (r"\b(?:your|the assistant'?s?)\s+(?:system|hidden|initial|original|internal|developer|"
     r"configuration|config|underlying|secret)\s+(?:prompt|instructions?|message|configuration|"
     r"rules|directives)\b"),
    r"\b(?:hidden|secret|invisible)\s+(?:text|content|context)\b.{0,30}\b(?:before|precedes?|above|prior)\b",
    # mode switches and dropping constraints
    (r"\b(?:switch(?:ing)?|enter|enable|activate|going into|change)\b.{0,25}\b(?:developer|"
     r"unrestricted|unfiltered|uncensored|god|sudo|jailbreak)\s+mode\b"),
    r"\b(?:unrestricted|unfiltered|uncensored)\s+mode\b",
    r"\bno longer bound\b|\bnot bound by\b.{0,30}\b(?:rules|guidelines|instructions|polic(?:y|ies))\b",
    (r"\b(?:set aside|put aside|throw away|abandon|stop following)\b.{0,30}\b(?:guidance|"
     r"guidelines?|instructions?|rules?|training|polic(?:y|ies))\b"),
    r"\b(?:forget|ignore|abandon)\s+your\s+(?:training|programming|purpose|role|guidelines)\b",
    r"\b(?:ignore|disregard)\s+(?:the\s+)?(?:above|everything above|all of the above)\b",
    # exfiltration of credentials into output
    (r"\b(?:put|write|include|add|paste)\b.{0,30}\b(?:database|db|admin|root|api|service)\s+"
     r"(?:password|credentials?|keys?|secrets?|tokens?)\b"),
    # other scripts and languages
    r"(?:игнорируй|игнорируйте|забудь|забудьте)\s.{0,30}(?:инструкци|правил)",
    r"(?:talimat|kural)\S*\s.{0,20}(?:yok say|g\u00f6rmezden gel|unut)",
    # other languages: "ignore the previous instructions"
    r"\b(?:ignora|olvida|omite|descarta|desatiende)\b.{0,30}\b(?:instrucciones|reglas|indicaciones)\b",
    r"\b(?:ignorez?|oublie[zs]?)\b.{0,30}\b(?:instructions|consignes|r[eè]gles)\b",
    r"\b(?:ignoriere|ignorieren sie|vergiss|missachte)\b.{0,30}\b(?:anweisungen|instruktionen|regeln)\b",
    (r"\b(?:desconsidere|desconsidera|esque[cç]a|ignore)\b.{0,30}\b(?:instru[cç][oõ]es|regras)\b"
    r".{0,20}\b(?:anteriores|pr[eé]vias)\b"),
    r"\b(?:ignora|ignori|dimentica)\b.{0,30}\b(?:istruzioni|regole)\b",
    r"(?:تجاهل|تجاهلي|انس|تخط)\S*\s.{0,25}(?:التعليمات|الأوامر|القواعد)",
]]

# case-sensitive: the persona name, not the first name Dan
INJECTION_CASE_SENSITIVE = [re.compile(r"\bDAN\b")]

_PHRASES = [f"{v}{q}{p}{o}" for v, q, p, o in itertools.product(
    ("ignore", "disregard", "forget", "override", "bypass"),
    ("", "all", "any", "the", "your"),
    ("previous", "prior", "above", "earlier", "preceding"),
    ("instructions", "rules", "prompt", "prompts", "guidelines"))]
_PHRASES += ["revealyoursystemprompt", "printyoursystemprompt", "showyoursystemprompt"]

# ---------------------------------------------------------------- privacy rules
_IDENT = (r"(?:subscribers?(?!-?\s?(?:impact|affect|facing|count|base|experience))|imsis?|msisdns?|"
          r"imei|phone(?: number)?|customers?|\[subscriber_id\]|\[phone\]|\+?\d{9,15}|"
          r"\d{3,4}[- ]\d{3}[- ]\d{4}|\bsim\b)")
PRIVACY_PATTERN = re.compile(
    r"\b(?:locat\w*|track\w*|trac(?:e|ing)|geolocat\w*|whereabouts|movements?|camped|"
    r"where(?: exactly)? is|which cell)\b.{0,60}\b" + _IDENT
    + r"|\b(?:list|enumerate|dump|export|show)\b.{0,30}\b(?:all|every)\b.{0,30}\b(?:imsis?|msisdns?|imeis?|subscribers?)\b"
    + r"|\b(?:call (?:history|records?|log|details?)|who owns|owner of|look ?up|identify|"
    r"name of|address of)\b.{0,40}\b" + _IDENT, re.IGNORECASE)

# ---------------------------------------------------------------- PII redaction
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
    """Return a block label if a deterministic rule matches (in any normalized form)."""
    forms, squashed = variants(text)
    if any(p in squashed for p in _PHRASES):
        return "injection"
    for form in forms:
        if any(p.search(form) for p in INJECTION_PATTERNS) or any(
                p.search(form) for p in INJECTION_CASE_SENSITIVE):
            return "injection"
        if PRIVACY_PATTERN.search(form):
            return "privacy"
    return None


def injection_evidence(text: str) -> str:
    """Which rule fired and on what text, for the ingest log (so a false positive on a real
    document can be diagnosed from CI output instead of guessed at)."""
    forms, squashed = variants(text)
    for p in _PHRASES:
        if p in squashed:
            return f"squashed phrase {p!r}"
    for i, form in enumerate(forms):
        for p in [*INJECTION_PATTERNS, *INJECTION_CASE_SENSITIVE]:
            m = p.search(form)
            if m:
                return f"form#{i} pattern {p.pattern[:60]!r} matched {m.group(0)[:100]!r}"
    return "unknown"


# "no filters" / "without restrictions" is a jailbreak when it addresses the model, but real
# 3GPP text says it constantly ("no Filters", "transmitted without restrictions"). In a
# DOCUMENT it only counts if something addressing the model sits right before it.
_BARE_RESTRICTION = re.compile(
    r"\b(?:without|no)\s+(?:any\s+)?(?:restrictions|limitations|limits|rules|filters|"
    r"guardrails|censorship)\b", re.IGNORECASE)
_ADDRESSES_MODEL = re.compile(
    r"\b(?:you|your|you're|answer|respond|reply|behave|assistant|chatbot|act as|from now on)\b",
    re.IGNORECASE)


def _drop_technical_restrictions(text: str) -> str:
    def repl(m: re.Match) -> str:
        window = text[max(0, m.start() - 80):m.start()]
        return m.group(0) if _ADDRESSES_MODEL.search(window) else "[x]"
    return _BARE_RESTRICTION.sub(repl, text)


def scan_document(text: str) -> str | None:
    """Ingest-time check for indirect prompt injection: a retrieved runbook chunk that tries
    to instruct the model. Only the injection rules apply (runbooks legitimately discuss
    subscribers and identifiers)."""
    label = rule_check(_drop_technical_restrictions(text))
    return label if label == "injection" else None


def answer_outcome(text: str) -> str:
    """cited | abstained | unverified. A citation wins: an answer that cites a runbook AND
    hedges is still grounded."""
    if CITATION.search(text):
        return "cited"
    return "abstained" if ABSTAIN.search(text) else "unverified"


def has_grounding(text: str) -> bool:
    return answer_outcome(text) != "unverified"
