from scripts.import_kpis import read_rows


def test_long_and_wide(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("ts,cell_id,kpi,value\n2026-01-01T00:00:00Z,C1,prb,50\nbad,C1,prb,1\n")
    rows, bad = read_rows(p)
    assert len(rows) == 1 and bad == 1 and rows[0][0].tzinfo is not None
    w = tmp_path / "b.csv"
    w.write_text("time,cell,DL PRB\n2026-01-01 00:15:00,C2,61.5\n2026-01-01 00:30:00,C2,\n")
    rows, bad = read_rows(w, True, "time", "cell", ["prb"], {"DL PRB": "prb"})
    assert rows[0][1:] == ("C2", "prb", 61.5) and len(rows) == 1 and bad == 0
