import sqlite3

import pytest

import build_std_reg_map as bm


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE insurers(member_cd TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE documents(doc_id INTEGER PRIMARY KEY, member_cd TEXT, doc_type TEXT,
                               prod_nm_raw TEXT);
        CREATE TABLE clauses(clause_id INTEGER PRIMARY KEY, doc_id INTEGER, seq INTEGER,
                             clause_no TEXT, title TEXT, text TEXT);
    """)
    c.execute("INSERT INTO documents VALUES(1,'STD_L','STANDARD','생명보험 표준약관')")
    c.execute("INSERT INTO documents VALUES(2,'REG_GD','REG','보험업감독규정')")
    c.execute("INSERT INTO clauses VALUES(10,1,0,'제34조','배당금의 지급','배당금 지급 본문')")
    c.execute("INSERT INTO clauses VALUES(11,1,1,'제32조','해약환급금','해약환급금 본문')")
    c.execute("INSERT INTO clauses VALUES(20,2,0,'제6-14조','계약자배당금의 산출 및 적립','규정본문')")
    c.execute("INSERT INTO clauses VALUES(21,2,1,'제7-66조','해약환급금의 계산','규정본문2')")
    return c


def test_auto_mapping_respects_threshold(monkeypatch):
    c = _db()
    monkeypatch.setattr(bm.simmatch, "db_similar",
        lambda conn, q, idf, d, top_n=3, query_title=None, doc_type="REG":
            [{"clause_id": 21, "score": 0.42}, {"clause_id": 20, "score": 0.10}])
    bm.build(c, {}, 1.0, golden=[])
    rows = c.execute("SELECT * FROM std_reg_map").fetchall()
    # 표준약관 2조문 × 임계 통과 1건씩 = 2행, 0.30 미만은 배제
    assert {(r["std_clause_id"], r["reg_clause_id"]) for r in rows} == {(10, 21), (11, 21)}
    assert all(r["source"] == "auto" and r["score"] >= bm.BRIDGE_MIN_SCORE for r in rows)


def test_golden_reg_override_replaces_auto(monkeypatch):
    c = _db()
    monkeypatch.setattr(bm.simmatch, "db_similar", lambda *a, **k: [{"clause_id": 21, "score": 0.9}])
    bm.build(c, {}, 1.0, golden=[{"std": "STD_L 제34조", "reg": ["REG_GD 제6-14조"]}])
    g = c.execute("SELECT * FROM std_reg_map WHERE std_clause_id=10").fetchall()
    assert len(g) == 1
    assert (g[0]["reg_clause_id"], g[0]["source"], g[0]["score"]) == (20, "golden", 1.0)


def test_golden_none_declares_gap(monkeypatch):
    c = _db()
    monkeypatch.setattr(bm.simmatch, "db_similar", lambda *a, **k: [{"clause_id": 21, "score": 0.9}])
    bm.build(c, {}, 1.0, golden=[{"std": "STD_L 제32조", "none": "상법 제651조(고지의무위반으로 인한 계약해지) 소관"}])
    n = c.execute("SELECT * FROM std_reg_map WHERE std_clause_id=11").fetchall()
    assert len(n) == 1
    assert n[0]["source"] == "none" and n[0]["reg_clause_id"] is None
    assert "상법 제651조" in n[0]["note"]


def test_idempotent_rebuild(monkeypatch):
    c = _db()
    monkeypatch.setattr(bm.simmatch, "db_similar", lambda *a, **k: [{"clause_id": 21, "score": 0.9}])
    bm.build(c, {}, 1.0, golden=[])
    bm.build(c, {}, 1.0, golden=[])
    assert c.execute("SELECT COUNT(*) FROM std_reg_map").fetchone()[0] == 2  # 누적 없음


def test_unresolved_golden_key_exits():
    c = _db()
    with pytest.raises(SystemExit):
        bm.build(c, {}, 1.0, golden=[{"std": "STD_L 제999조", "none": "x"}])


def test_duplicate_golden_std_key_exits():
    # 동일 "std" 키가 두 번 등장하면 dict comprehension이 마지막 항목으로 조용히
    # 덮어쓰므로(silent last-win), 빌드 전에 즉시 실패해야 한다.
    c = _db()
    with pytest.raises(SystemExit):
        bm.build(c, {}, 1.0, golden=[
            {"std": "STD_L 제34조", "none": "사유1"},
            {"std": "STD_L 제34조", "none": "사유2"},
        ])


def test_duplicate_clause_no_disambiguated_by_title(monkeypatch):
    # STD_S 실측 사례: 표 파싱 부산물로 동일 clause_no가 중복 존재 →
    # title 없이 실패(무결성 게이트 유지), title 지정 시 정확히 1건으로 해석.
    c = _db()
    c.execute("INSERT INTO clauses VALUES(12,1,2,'제34조','제1항제4호에','표 조각 부산물')")
    monkeypatch.setattr(bm.simmatch, "db_similar", lambda *a, **k: [])
    with pytest.raises(SystemExit):
        bm.build(c, {}, 1.0, golden=[{"std": "STD_L 제34조", "none": "x"}])
    bm.build(c, {}, 1.0, golden=[
        {"std": "STD_L 제34조", "title": "배당금의 지급", "none": "대응 없음 사유"}])
    n = c.execute("SELECT * FROM std_reg_map WHERE source='none'").fetchall()
    assert len(n) == 1 and n[0]["std_clause_id"] == 10


def test_ensure_fts_creates_and_populates():
    c = _db()
    c.execute("UPDATE clauses SET text = text || ' zzzpad" + "가" * 30 + "'")
    bm.ensure_fts(c)
    assert c.execute("SELECT COUNT(*) FROM clauses_fts WHERE clauses_fts MATCH 'zzzpad*'").fetchone()[0] > 0


def test_ensure_fts_rebuilds_when_stale():
    c = _db()
    c.execute("UPDATE clauses SET text = text || '" + "가" * 30 + "'")
    bm.ensure_fts(c)
    c.execute("INSERT INTO clauses VALUES(30,1,2,'제99조','신규조문','zzznewtoken77 " + "나" * 30 + "')")
    # 재인덱싱 전엔 MATCH가 신규 조문을 못 찾음(스테일 상태 문서화)
    assert c.execute("SELECT COUNT(*) FROM clauses_fts WHERE clauses_fts MATCH 'zzznewtoken77'").fetchone()[0] == 0
    bm.ensure_fts(c)  # 스테일 감지 → 전체 재구축
    assert c.execute("SELECT COUNT(*) FROM clauses_fts WHERE clauses_fts MATCH 'zzznewtoken77'").fetchone()[0] == 1


def test_ensure_fts_rebuilds_on_same_count_reingest():
    # 월 갱신 실측 시나리오: DELETE+재INSERT로 개수는 같고 rowid만 상승(AUTOINCREMENT)
    c = _db()
    c.execute("UPDATE clauses SET text = text || '" + "가" * 30 + "'")
    bm.ensure_fts(c)
    old = c.execute("SELECT clause_id, doc_id, seq, clause_no, title FROM clauses WHERE clause_id=10").fetchone()
    c.execute("DELETE FROM clauses WHERE clause_id=10")
    c.execute("INSERT INTO clauses VALUES(31,?,?,?,?, 'zzzreingest88 " + "다" * 30 + "')",
              (old["doc_id"], old["seq"], old["clause_no"], old["title"]))
    bm.ensure_fts(c)  # 개수 동일하지만 MAX 상승 → 재구축해야 함
    assert c.execute("SELECT COUNT(*) FROM clauses_fts WHERE clauses_fts MATCH 'zzzreingest88'").fetchone()[0] == 1
