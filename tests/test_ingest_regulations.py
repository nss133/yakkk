import sqlite3
import ingest_standards


def _db():
    c = sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE insurers(member_cd TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE documents(doc_id INTEGER PRIMARY KEY AUTOINCREMENT, member_cd TEXT,
        prod_nm_raw TEXT, doc_type TEXT, version_label TEXT, file_path TEXT,
        sha256 TEXT, prod_group TEXT);
      CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER,
        seq INTEGER, clause_no TEXT, title TEXT, text TEXT);
    """)
    return c


def test_ingest_uses_entry_doc_type_reg():
    c = _db()
    entry = {"key": "gamdok", "name": "보험업감독규정", "member_cd": "REG_GD",
             "version_label": "2024.8.7 시행", "source_path": "x.md", "source_type": "md",
             "doc_type": "REG"}
    txt = "제7-45조(해약환급금) 회사는 계약이 해지된 경우 해약환급금을 지급하여야 한다 세부기준."
    n = ingest_standards.ingest(c, entry, txt)
    assert n >= 1
    d = c.execute("SELECT doc_type FROM documents WHERE member_cd='REG_GD'").fetchone()[0]
    assert d == "REG"
    assert c.execute("SELECT title FROM clauses WHERE clause_no='제7-45조'").fetchone()[0] == "해약환급금"


def test_ingest_default_doc_type_still_standard():
    c = _db()
    entry = {"key": "life", "name": "생명보험 표준약관", "member_cd": "STD_L",
             "version_label": "v", "source_path": "y.md", "source_type": "md"}  # doc_type 없음
    txt = "제1조(목적) 이 약관은 목적을 정하며 최소 삼십자 이상 채웁니다 채웁니다."
    ingest_standards.ingest(c, entry, txt)
    assert c.execute("SELECT doc_type FROM documents WHERE member_cd='STD_L'").fetchone()[0] == "STANDARD"
