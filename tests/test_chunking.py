from app.chunking import chunk_text


def test_empty():
    assert chunk_text("   ") == []


def test_overlap_and_count():
    text = "".join(chr(97 + i % 26) for i in range(2500))
    chunks = chunk_text(text, size=1200, overlap=200)
    assert len(chunks) == 3
    assert chunks[0][1000:] == chunks[1][:200]


def test_markdown_sections_keep_title():
    from app.chunking import chunk_markdown

    doc = "# Runbook X\n\n## Trigger\nAlpha.\n\n## Actions\nBeta."
    chunks = chunk_markdown(doc)
    assert len(chunks) == 2
    assert all(c.startswith("# Runbook X") for c in chunks)
    assert "Alpha." in chunks[0] and "Beta." in chunks[1]
