def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Fixed-size character chunks with overlap. Baseline chunker: swap for
    structure-aware chunking (headings/tables) once the golden set exists."""
    assert overlap < size, "overlap must be smaller than size"
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while True:
        chunks.append(text[start : start + size])
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks


def chunk_markdown(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Split on '## ' sections; prefix each chunk with the '# ' title so it stays
    self-describing. Oversized sections fall back to fixed-size chunks."""
    lines = text.strip().splitlines()
    title = lines[0] if lines and lines[0].startswith("# ") else ""
    sections, cur = [], []
    for ln in lines[1:] if title else lines:
        if ln.startswith("## ") and cur:
            sections.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        sections.append("\n".join(cur))
    prefix = f"{title}\n" if title else ""
    return [prefix + part
            for sec in sections if sec.strip()
            for part in chunk_text(sec, size - len(prefix), overlap)]
