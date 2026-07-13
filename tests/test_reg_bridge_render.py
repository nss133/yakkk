import sqlite3

from search_app import App


def _conn_with_map(rows):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE insurers(member_cd TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE documents(doc_id INTEGER PRIMARY KEY, member_cd TEXT, doc_type TEXT,
                               prod_nm_raw TEXT, version_label TEXT, prod_group TEXT);
        CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY, doc_id INTEGER, seq INTEGER,
                             clause_no TEXT, title TEXT, text TEXT);
        CREATE TABLE std_reg_map(std_clause_id INTEGER, reg_clause_id INTEGER, score REAL,
                                 source TEXT, note TEXT);
    """)
    c.execute("INSERT INTO insurers VALUES('REG_GD','보험업감독규정')")
    c.execute("INSERT INTO documents VALUES(2,'REG_GD','REG','보험업감독규정','2026-01','규정')")
    c.execute("INSERT INTO clauses VALUES(20,2,0,'제6-14조','계약자배당금의 산출 및 적립','규정본문')")
    c.executemany("INSERT INTO std_reg_map VALUES(?,?,?,?,?)", rows)
    return c


def _std_row(score=0.8, clause_id=10):
    return {"score": score, "clause_id": clause_id, "clause_no": "제34조", "title": "배당금의 지급",
            "text": "x", "doc_id": 1, "prod_nm_raw": "생명보험 표준약관", "version_label": "v",
            "insurer": "생명보험 표준약관", "member_cd": "STD_L"}


def _reg_row(clause_id=99):
    return {"score": 0.33, "clause_id": clause_id, "clause_no": "제1-1조", "title": "직접유사조문",
            "text": "y", "doc_id": 2, "prod_nm_raw": "보험업감독규정", "version_label": "v",
            "insurer": "보험업감독규정", "member_cd": "REG_GD"}


def test_bridge_rows_first_with_via_label_and_golden_mark():
    c = _conn_with_map([(10, 20, 1.0, "golden", None)])
    app = App.__new__(App)
    h = app._render_reg_section(c, [_std_row()], [_reg_row()], "질의")
    assert "표준약관" in h and "경유" in h
    assert h.index("제6-14조") < h.index("직접유사조문")   # 브릿지 우선, 직접 유사 보충
    assert "✓검수" in h                                     # golden 표시


def test_none_note_shown_direct_still_follows():
    c = _conn_with_map([(10, None, None, "none", "상법 제651조(고지의무위반으로 인한 계약해지) 소관")])
    app = App.__new__(App)
    h = app._render_reg_section(c, [_std_row()], [_reg_row()], "질의")
    assert "정면 대응 조문 없음" in h and "상법 제651조" in h
    assert "직접유사조문" in h


def test_direct_duplicate_of_bridge_removed():
    c = _conn_with_map([(10, 20, 0.5, "auto", None)])
    app = App.__new__(App)
    h = app._render_reg_section(c, [_std_row()], [_reg_row(clause_id=20)], "질의")
    assert "제6-14조" in h
    assert "직접 유사" not in h   # 유일한 직접 결과가 브릿지와 중복 → 블록 자체가 사라짐


def test_low_std_score_disables_bridge():
    c = _conn_with_map([(10, 20, 1.0, "golden", None)])
    app = App.__new__(App)
    h = app._render_reg_section(c, [_std_row(score=0.1)], [_reg_row()], "질의")
    assert "경유" not in h and "직접유사조문" in h


def test_missing_table_falls_back_to_direct_only():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    app = App.__new__(App)
    h = app._render_reg_section(c, [_std_row()], [_reg_row()], "질의")
    assert "직접유사조문" in h and "경유" not in h


def test_all_empty_message():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    app = App.__new__(App)
    assert "관련 감독규정·법령 없음" in app._render_reg_section(c, [], [], "질의")
