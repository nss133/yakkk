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


def test_ingest_creates_insurer_doc_and_clauses():
    c = _db()
    entry = {"key": "life", "name": "생명보험 표준약관", "member_cd": "STD_L",
             "version_label": "2024.12.20 개정", "source_path": "x.md", "source_type": "md"}
    txt = ("제1조(목적) 이 계약은 위험을 보장합니다.\n"
           "제3조(보험금의 지급사유) 회사는 피보험자가 사망한 경우 보험금을 지급합니다.")
    n = ingest_standards.ingest(c, entry, txt)
    assert n >= 2
    assert c.execute("SELECT name FROM insurers WHERE member_cd='STD_L'").fetchone()[0] == "생명보험 표준약관"
    d = c.execute("SELECT doc_type, version_label FROM documents WHERE member_cd='STD_L'").fetchone()
    assert d == ("STANDARD", "2024.12.20 개정")
    titles = [r[0] for r in c.execute("SELECT title FROM clauses WHERE clause_no LIKE '제%조%'")]
    assert "목적" in titles and "보험금의 지급사유" in titles


def test_ingest_idempotent_replaces():
    c = _db()
    entry = {"key": "health", "name": "질병상해 표준약관", "member_cd": "STD_H",
             "version_label": "v", "source_path": "y.md", "source_type": "md"}
    txt = "제1조(목적) 본문입니다 최소 삼십자 이상이 되도록 채웁니다 채웁니다."
    ingest_standards.ingest(c, entry, txt)
    ingest_standards.ingest(c, entry, txt)  # 재적재
    assert c.execute("SELECT COUNT(*) FROM documents WHERE member_cd='STD_H'").fetchone()[0] == 1


def test_clean_standard_chunks_merges_false_positive_into_previous():
    """§A: 빈 제목 '제N조' 청크(PDF 교차참조 오탐)는 clause_no=None으로 강등되어
    직전 실제 조문 청크의 본문 뒤에 병합됨(텍스트 유실 없음)."""
    chunks = [
        ("제3조", "보험금의 지급사유", "회사는 피보험자가 사망한 경우 보험금을 지급합니다."),
        ("제2조", "", "제2호에 따른 전자서명 등 필요한 조치를 취합니다."),
    ]
    cleaned = ingest_standards._clean_standard_chunks(chunks)
    jo_chunks = [c for c in cleaned if c[0]]
    assert len(jo_chunks) == 1
    assert jo_chunks[0][0] == "제3조"
    assert "제2호에 따른 전자서명" in jo_chunks[0][2]
    assert "회사는 피보험자가 사망한 경우" in jo_chunks[0][2]


def test_clean_standard_chunks_keeps_real_articles_and_byulpyo():
    chunks = [
        ("제1조", "목적", "이 계약은 위험을 보장합니다."),
        ("별표1", "장해분류표", "내용"),
        (None, "[전문]", "머리말"),
    ]
    cleaned = ingest_standards._clean_standard_chunks(chunks)
    assert cleaned == chunks
