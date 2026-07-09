import sqlite3

import build_simindex
import simmatch


def _fixture():
    c = sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE insurers(member_cd TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE documents(doc_id INTEGER PRIMARY KEY, member_cd TEXT, prod_nm_raw TEXT,
                             version_label TEXT, prod_group TEXT);
      CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY, doc_id INTEGER,
                           clause_no TEXT, title TEXT, text TEXT);
      INSERT INTO insurers VALUES ('L34','미래에셋'),('L03','삼성'),('L01','한화');
      INSERT INTO documents VALUES
        (1,'L34','자사종신','2024~','종신'),
        (2,'L03','삼성종신','2024~','종신'),
        (3,'L01','한화종신','2024~','종신');
      INSERT INTO clauses VALUES
        (10,1,'제3조','보험금의 지급','피보험자가 사망한 경우 회사는 사망보험금을 지급합니다 지급사유'),
        (20,2,'제3조','보험금의 지급','피보험자가 사망한 때에 회사는 사망보험금을 지급함 지급사유 명시'),
        (30,3,'제9조','보험료 납입','보험료의 납입을 연체하면 납입최고 후 계약이 해지됩니다');
      CREATE VIRTUAL TABLE clauses_fts USING fts5(text, title, content='clauses', content_rowid='clause_id');
      INSERT INTO clauses_fts(rowid,text,title)
        SELECT clause_id,text,COALESCE(title,'') FROM clauses WHERE length(text)>=30;
    """)
    c.row_factory = sqlite3.Row
    build_simindex.build(c, df_floor=1, df_ceil_ratio=1.0)
    return c


def test_db_similar_ranks_same_topic_first_and_excludes_self():
    c = _fixture()
    idf, d = simmatch.load_idf(c)
    q = "피보험자가 사망한 경우 회사는 사망보험금을 지급합니다"
    res = simmatch.db_similar(c, q, idf, d, top_n=5, exclude_member="L34")
    assert res, "결과가 있어야 함"
    assert all(r["member_cd"] != "L34" for r in res)     # 자사 제외
    assert res[0]["member_cd"] == "L03"                   # 같은 취지(삼성)가 최상위
    assert res[0]["score"] > 0


def test_fts_query_builds_or_terms():
    q = simmatch.fts_query("보험금의 지급 사유")
    assert "OR" in q and '"보험금의"' in q
