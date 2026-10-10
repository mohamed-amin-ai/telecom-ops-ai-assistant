"""Download real 3GPP specifications and convert them to Markdown for ingestion.

    python -m scripts.fetch_3gpp                      # default ops-relevant set, Rel-18
    python -m scripts.fetch_3gpp --specs 28.554 38.331 --release Rel-18
    python -m scripts.ingest --docs data/runbooks data/3gpp

Source: the public 3GPP archive (https://www.3gpp.org/ftp/Specs/latest/). The specs are free to
download but are copyright of 3GPP's organizational partners (ETSI, ARIB, ATIS, CCSA, TSDSI,
TTA, TTC); this repo does NOT redistribute them -- you fetch them yourself, into data/3gpp/
(git-ignored), and every converted file carries its spec number, version and source URL.

Run it where there is internet access to www.3gpp.org. Specs that ship only as legacy .doc
(not .docx) are skipped with a warning, not silently converted badly.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://www.3gpp.org/ftp/Specs/latest"

# Specs a NOC / RAN-ops assistant actually needs: KPI + counter definitions, performance
# management, RRC/handover procedures, architecture. (number: short purpose)
ALL_SPECS = {
    "28.554": "5G end-to-end KPIs",
    "28.552": "5G performance measurements (counters)",
    "32.450": "E-UTRAN KPI definitions",
    "32.425": "E-UTRAN performance measurements (counters)",
    "28.532": "Management services (generic provisioning)",
    "28.541": "5G NRM (network resource model)",
    "38.300": "NR overall description",
    "38.331": "NR RRC protocol",
    "36.300": "E-UTRA overall description",
    "36.331": "E-UTRA RRC protocol",
    "23.501": "5G system architecture",
    "38.133": "NR requirements for radio resource management",
}


# Embedding on CPU is ~10 chunks/s; the full list above is ~15k chunks (30+ min). The default
# is the KPI/PM/architecture core; pass --all (or --specs ...) for more.
CORE = ["28.554", "28.552", "32.450", "32.425", "38.300", "38.331", "36.300", "28.532"]
DEFAULT_SPECS = {k: ALL_SPECS[k] for k in CORE}


# TS 32.450 (E-UTRAN KPI definitions) is genuinely ~18k characters: both the docx path and an
# independent LibreOffice text extraction measured it (CI), so the floor must sit below that.
# Anything smaller than this has lost its body (an empty table-of-contents shell is ~1-3k).
MIN_CHARS = 10_000


def series_dir(spec: str) -> str:
    return f"{spec.split('.')[0]}_series"


def list_zip_names(client: httpx.Client, release: str, spec: str) -> list[str]:
    url = f"{BASE}/{release}/{series_dir(spec)}/"
    r = client.get(url)
    r.raise_for_status()
    return re.findall(r'href="[^"]*?(\d{5}-[a-z0-9]{3}\.zip)"', r.text)


def find_zip(names: list[str], spec: str) -> str | None:
    prefix = spec.replace(".", "") + "-"
    hits = sorted({n for n in names if n.startswith(prefix)})
    return hits[-1] if hits else None


def version_from_zip(name: str) -> str:
    """'28554-ia0.zip' -> '18.10.0': 3GPP encodes version digits in base-36-ish letters
    (0-9 then a-z = 10..35), one char each for major, minor, patch."""
    code = name.split("-")[1].split(".")[0]
    return ".".join(str(int(ch, 36)) for ch in code)


_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*(?:\t|\s)\s*(.+)$")


_WRAPPERS = {"sdt", "sdtContent", "customXml", "ins", "smartTag"}


def _block_elements(parent):
    """Paragraphs and tables in document order, looking inside content controls (w:sdt) and
    similar wrappers -- some specs wrap their whole body in one, which a direct-children walk
    sees as empty."""
    for el in parent.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("p", "tbl"):
            yield el
        elif tag in _WRAPPERS:
            yield from _block_elements(el)


def docx_to_markdown(data: bytes, spec: str, version: str, release: str, url: str) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    out = [f"# 3GPP TS {spec} {release} v{version} ({url})", ""]  # one title line: no junk chunk
    in_toc = False
    for el in _block_elements(doc.element.body):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            rows = [[c.text.strip().replace("\n", " ").replace("|", "/") for c in r.cells]
                    for r in Table(el, doc).rows]
            rows = [r for r in rows if any(r)]
            if rows:
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + "---|" * len(rows[0]))
                out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("")
            continue
        if tag != "p":
            continue
        p = Paragraph(el, doc)
        text = p.text.strip()
        style = (p.style.name if p.style is not None else "") or ""
        if not text:
            continue
        if style.upper().startswith("TOC") or style in ("TT",):
            in_toc = True
            continue
        m = re.match(r"Heading (\d)", style)
        if m:
            in_toc = False
            level = int(m.group(1))
            # '## ' is the chunk boundary (see app/chunking.py): clause levels 1-3 start
            # chunks; deeper clauses stay inside their parent as bold lines.
            out.append(f"\n## {text}" if level <= 3 else f"\n**{text}**")
            continue
        if in_toc:
            continue
        if style.startswith(("B1", "B2", "B3", "EX", "NO")):
            out.append(f"- {text}")
        else:
            out.append(text)
    return "\n".join(out) + "\n"


_CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\s+(\S.{0,120})$")


def text_to_markdown(text: str, spec: str, version: str, release: str, url: str) -> str:
    """Fallback when the structured conversion lost the body: plain text out of LibreOffice,
    with clause headings (1, 1.2, 1.2.3 + title) turned into chunk boundaries. Loses tables'
    structure and bullets, keeps the content searchable."""
    out = [f"# 3GPP TS {spec} {release} v{version} ({url})", ""]
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _CLAUSE.match(line)
        out.append(f"\n## {line}" if m and not line.endswith(".") else line)
    return "\n".join(out) + "\n"


def _soffice_text(raw: bytes, suffix: str) -> str | None:
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"in{suffix}"
        src.write_bytes(raw)
        subprocess.run([soffice, "--headless", "--convert-to", "txt:Text", "--outdir", d, str(src)],
                       check=False, capture_output=True, timeout=600)
        out = Path(d) / "in.txt"
        return out.read_text(encoding="utf-8", errors="ignore") if out.exists() else None


def _doc_to_docx(raw: bytes) -> bytes | None:
    """Legacy .doc -> .docx with LibreOffice if it is installed, else None (caller skips)."""
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.doc"
        src.write_bytes(raw)
        subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", d, str(src)],
                       check=False, capture_output=True, timeout=600)
        out = Path(d) / "in.docx"
        return out.read_bytes() if out.exists() else None


def fetch_spec(client: httpx.Client, spec: str, release: str, out_dir: Path) -> dict:
    names = list_zip_names(client, release, spec)
    zname = find_zip(names, spec)
    if not zname:
        return {"spec": spec, "status": "not_found"}
    url = f"{BASE}/{release}/{series_dir(spec)}/{zname}"
    r = client.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        docx = [n for n in z.namelist() if n.lower().endswith(".docx")]
        if docx:
            data = z.read(docx[0])
        else:
            legacy = [n for n in z.namelist() if n.lower().endswith(".doc")]
            data = _doc_to_docx(z.read(legacy[0])) if legacy else None
            if data is None:
                return {"spec": spec, "status": "no_docx", "url": url}
    version = version_from_zip(zname)
    md = docx_to_markdown(data, spec, version, release, url)
    method = "docx"
    if len(md) < MIN_CHARS:  # the structured conversion lost the body: try plain text via soffice
        text = _soffice_text(data, ".docx")
        if text and len(text) >= MIN_CHARS:
            md, method = text_to_markdown(text, spec, version, release, url), "text-fallback"
        else:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                members = z.namelist()
            return {"spec": spec, "status": "too_small", "url": url, "chars": len(md),
                    "fallback_chars": len(text or ""), "zip_members": members,
                    "docx_bytes": len(data)}
    fname = f"TS_{spec.replace('.', '_')}_{release}.md"
    (out_dir / fname).write_text(md, encoding="utf-8")
    return {"spec": spec, "status": "ok", "file": fname, "version": version, "url": url,
            "sha256": hashlib.sha256(r.content).hexdigest(), "chars": len(md),
            "method": method}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", nargs="*", default=None)
    ap.add_argument("--all", action="store_true", help="every spec in ALL_SPECS (slow to embed)")
    ap.add_argument("--release", default="Rel-18")
    ap.add_argument("--out", default="data/3gpp")
    a = ap.parse_args(argv)
    specs = a.specs or list(ALL_SPECS if a.all else DEFAULT_SPECS)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": "telecom-ops-assistant/1.0"}) as client:
        for spec in specs:
            for attempt in range(3):
                try:
                    res = fetch_spec(client, spec, a.release, out)
                    break
                except httpx.HTTPError as e:
                    res = {"spec": spec, "status": f"error: {type(e).__name__}: {e}"}
                    time.sleep(2 * (attempt + 1))
            results.append(res)
            print(f"{res['spec']}: {res['status']}"
                  + (f" v{res['version']} ({res['chars']:,} chars, {res['method']})"
                     if res["status"] == "ok" else f" {({k: v for k, v in res.items() if k != 'spec'})}"))
    (out / "MANIFEST.json").write_text(json.dumps(
        {"fetched": datetime.now(UTC).isoformat(timespec="seconds"), "release": a.release,
         "specs": results}, indent=2))
    ok = sum(r["status"] == "ok" for r in results)
    print(f"{ok}/{len(results)} specs converted into {out}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
