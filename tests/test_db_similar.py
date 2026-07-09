import sqlite3

import build_simindex
import simmatch


def _fixture():
    c = sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE insurers(member_cd TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE documents(doc_id INTEGER PRIMARY KEY, member_cd TEXT, prod_nm_raw TEXT,
                             version_label TEXT, prod_group TEXT, doc_type TEXT);
      CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY, doc_id INTEGER,
                           clause_no TEXT, title TEXT, text TEXT);
      INSERT INTO insurers VALUES ('L34','미래에셋'),('L03','삼성'),('L01','한화'),('STD_L','표준약관');
      INSERT INTO documents VALUES
        (1,'L34','자사종신','2024~','종신','TERMS'),
        (2,'L03','삼성종신','2024~','종신','TERMS'),
        (3,'L01','한화종신','2024~','종신','TERMS'),
        (4,'L01','한화배당형종신','2024~','종신','TERMS'),
        (5,'STD_L','생명보험 표준약관','2024~','종신','STANDARD');
      INSERT INTO clauses VALUES
        (10,1,'제3조','보험금의 지급','피보험자가 사망한 경우 회사는 사망보험금을 지급합니다 지급사유'),
        (20,2,'제3조','보험금의 지급','피보험자가 사망한 때에 회사는 사망보험금을 지급함 지급사유 명시'),
        (30,3,'제9조','보험료 납입','보험료의 납입을 연체하면 납입최고 후 계약이 해지됩니다'),
        (40,4,'제12조','배당금의 지급','회사는 계약이 유지되는 동안 매년 배당금을 계산하여 계약자에게 지급합니다 배당금 지급 기준'),
        (50,5,'제3조','보험금의 지급사유','회사는 피보험자가 보험기간 중에 사망한 경우 사망보험금을 수익자에게 지급합니다');
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
    # distractor(배당금 지급, L01)도 FTS 후보 풀에 들어와야 코사인 변별이 의미 있음
    assert len(res) >= 2, "distractor가 후보 풀에 들어와 다중 후보가 되어야 함"
    assert res[0]["member_cd"] == "L03"                   # 같은 취지(삼성)가 최상위
    assert res[0]["score"] > 0

    distractor_rows = [r for r in res if r["member_cd"] == "L01"]
    assert distractor_rows, "distractor(한화 배당금 조항)가 후보로 포함되어야 함"
    assert res[0]["score"] > distractor_rows[0]["score"]  # 코사인이 실제로 변별함


def test_fts_query_builds_or_terms():
    q = simmatch.fts_query("보험금의 지급 사유")
    assert "OR" in q and '"보험금의"' in q


def test_db_similar_doc_type_standard_only():
    c = _fixture()
    idf, d = simmatch.load_idf(c)
    q = "피보험자가 사망한 경우 회사는 사망보험금을 지급합니다"
    std = simmatch.db_similar(c, q, idf, d, top_n=5, doc_type="STANDARD")
    assert std and all(r["member_cd"] == "STD_L" for r in std)
    terms = simmatch.db_similar(c, q, idf, d, top_n=5, doc_type="TERMS", exclude_member="L34")
    assert terms and all(r["member_cd"] != "STD_L" for r in terms)
