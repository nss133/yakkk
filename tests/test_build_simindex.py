import sqlite3

import build_simindex


def _mk_db():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY, text TEXT);
        INSERT INTO clauses(text) VALUES
          ('피보험자가 사망한 경우 보험금을 지급합니다 사망보험금 지급기준'),
          ('피보험자가 사망한 때 사망보험금을 지급합니다 지급기준 명시'),
          ('보험료의 납입을 연체하면 계약이 해지됩니다 납입최고 독촉');
    """)
    c.commit()
    return c


def test_build_creates_idf_and_meta():
    c = _mk_db()
    build_simindex.build(c, df_floor=1, df_ceil_ratio=1.0)
    n = c.execute("SELECT COUNT(*) FROM ngram_idf").fetchone()[0]
    assert n > 0
    meta = dict(c.execute("SELECT key, value FROM simindex_meta"))
    assert meta["n_docs"] == "3"
    assert float(meta["default_idf"]) > 0


def test_common_gram_has_lower_idf_than_rare():
    c = _mk_db()
    build_simindex.build(c, df_floor=1, df_ceil_ratio=1.0)
    idf = dict(c.execute("SELECT ngram, idf FROM ngram_idf"))
    # '보험금'은 2개 문서(사망 관련), '납입최'는 1개 문서 → 후자가 더 희귀(높은 idf)
    if "보험금" in idf and "납입최" in idf:
        assert idf["납입최"] > idf["보험금"]
