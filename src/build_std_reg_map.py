#!/usr/bin/env python3
"""표준약관→감독규정 브릿지 매핑(std_reg_map) 빌드. (빌드 시점, 유사인덱스 이후 실행)

- STANDARD 조문별 db_similar(doc_type='REG') top-3 중 BRIDGE_MIN_SCORE 이상 자동 채택
- catalog/std_reg_golden.json 이 자동 매핑을 오버라이드:
    {"std": "STD_L 제34조", "reg": ["REG_GD 제6-14조"]}      # 정답 강제(검수됨)
    {"std": "STD_L 제13조", "none": "상법 제651조 ... 소관"}  # 대응 없음 선언
  키는 "member_cd clause_no" — clause_id는 재적재마다 변하므로 골든에 쓰지 않음.
- 멱등(전체 삭제 후 재삽입). 미해석 골든 키는 exit 1(조문번호 개정 감지 게이트).
사용법: .venv/bin/python src/build_std_reg_map.py
"""
import json
import pathlib
import sqlite3

import simmatch
from common import open_db

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "catalog" / "std_reg_golden.json"
BRIDGE_MIN_SCORE = 0.30

SCHEMA = """CREATE TABLE IF NOT EXISTS std_reg_map(
    std_clause_id INTEGER NOT NULL,
    reg_clause_id INTEGER,
    score REAL,
    source TEXT NOT NULL,
    note TEXT
)"""


def ensure_fts(conn):
    """terms.db(작업 원본)에는 clauses_fts가 없음(export_dist.py에서만 생성).
    db_similar()가 FTS MATCH·BM25를 요구하므로, 빌드 시점에 여기서 1회 만들어 둔다
    (export_dist.py와 동일 DDL 재사용 — 반입 DB와 동일한 검색 후보/스코어 보장).
    이미 있으면 스킵(멱등)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='clauses_fts'").fetchone()
    if row:
        return
    conn.executescript("""
        CREATE VIRTUAL TABLE clauses_fts USING fts5(
            text, title, content='clauses', content_rowid='clause_id'
        );
    """)
    conn.execute("""
        INSERT INTO clauses_fts(rowid, text, title)
        SELECT clause_id, text, COALESCE(title,'') FROM clauses WHERE length(text) >= 30
    """)
    conn.commit()


def resolve_clause(conn, key: str) -> int:
    """'STD_L 제34조' → clause_id. 0건/복수건이면 SystemExit(골든 무결성 게이트)."""
    member, no = key.split(None, 1)
    rows = conn.execute(
        "SELECT clause_id FROM clauses c JOIN documents d USING(doc_id) "
        "WHERE d.member_cd=? AND c.clause_no=?", (member, no)).fetchall()
    if len(rows) != 1:
        raise SystemExit(f"골든 키 해석 실패: {key!r} — {len(rows)}건 매칭(조문번호 개정 여부 확인)")
    return rows[0][0]


def build(conn, idf, default_idf, golden):
    conn.execute(SCHEMA)
    conn.execute("DELETE FROM std_reg_map")
    overrides = {resolve_clause(conn, e["std"]): e for e in golden}
    stds = conn.execute(
        "SELECT c.clause_id, c.clause_no, c.title, c.text FROM clauses c "
        "JOIN documents d USING(doc_id) WHERE d.doc_type='STANDARD' ORDER BY c.clause_id"
    ).fetchall()
    out, n_auto, n_golden, n_none = [], 0, 0, 0
    for r in stds:
        e = overrides.get(r["clause_id"])
        if e and "none" in e:
            out.append((r["clause_id"], None, None, "none", e["none"]))
            n_none += 1
        elif e and "reg" in e:
            for key in e["reg"]:
                out.append((r["clause_id"], resolve_clause(conn, key), 1.0, "golden", None))
                n_golden += 1
        else:
            for m in simmatch.db_similar(conn, r["text"], idf, default_idf, top_n=3,
                                         query_title=r["title"], doc_type="REG"):
                if m["score"] >= BRIDGE_MIN_SCORE:
                    out.append((r["clause_id"], m["clause_id"], m["score"], "auto", None))
                    n_auto += 1
    conn.executemany("INSERT INTO std_reg_map VALUES(?,?,?,?,?)", out)
    conn.commit()
    return n_auto, n_golden, n_none


def main():
    conn = open_db()
    conn.row_factory = sqlite3.Row  # db_similar가 키 접근 사용
    ensure_fts(conn)
    idf, default_idf = simmatch.load_idf(conn)
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else []
    n_auto, n_golden, n_none = build(conn, idf, default_idf, golden)
    total = conn.execute("SELECT COUNT(DISTINCT std_clause_id) FROM std_reg_map").fetchone()[0]
    print(f"완료: std_reg_map — 표준약관 {total}조문 (auto {n_auto}행 · golden {n_golden}행 · none {n_none}행)")
    conn.close()


if __name__ == "__main__":
    main()
