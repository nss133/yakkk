#!/usr/bin/env python3
"""표준약관→감독규정 브릿지 매핑(std_reg_map) 빌드. (빌드 시점, 유사인덱스 이후 실행)

- STANDARD 조문별 db_similar(doc_type='REG') top-3 중 BRIDGE_MIN_SCORE 이상 자동 채택
- catalog/std_reg_golden.json 이 자동 매핑을 오버라이드:
    {"std": "STD_L 제34조", "reg": ["REG_GD 제6-14조"]}      # 정답 강제(검수됨)
    {"std": "STD_L 제13조", "none": "상법 제651조 ... 소관"}  # 대응 없음 선언
  키는 "member_cd clause_no" — clause_id는 재적재마다 변하므로 골든에 쓰지 않음.
  조문번호가 파싱 부산물로 중복되는 경우 선택적 "title" 필드로 좁힘(예: STD_S 제42조).
- 멱등(전체 삭제 후 재삽입). 미해석 골든 키는 exit 1(조문번호 개정 감지 게이트).
사용법: .venv/bin/python src/build_std_reg_map.py
"""
import json
import pathlib
import sqlite3

import simmatch
from common import FTS_DDL, FTS_MIN_CHARS, open_db

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
    db_similar()가 FTS MATCH·BM25를 요구하므로, 빌드 시점에 여기서 만들어 둔다
    (export_dist.py와 동일 DDL 재사용 — 반입 DB와 동일한 검색 후보/스코어 보장).

    이 함수는 db/terms.db 안에 clauses 전문의 FTS 섀도(약 +30% 용량)를 만들며,
    조문 집합이 바뀌면(월 갱신) 전체 재구축한다.

    clauses_fts는 content='clauses' 외부 콘텐츠 테이블이라 COUNT(*) FROM clauses_fts는
    clauses 신규 행이 늘어난 만큼 그대로 따라 움직인다(항등식 — content 테이블의 rowid
    집합을 반영할 뿐 섀도 인덱스가 실제로 그 문서를 색인했는지는 말해주지 않는다).
    그래서 존재 여부·COUNT(*) 단독 비교가 아니라, 실제로 색인된 문서 수를 세는 섀도 테이블
    clauses_fts_docsize(문서당 1행 — DDL에 columnsize=0을 주지 않아 생성됨)의 (행수, 최대 id)와
    clauses(길이 30자 이상)의 (행수, 최대 clause_id)를 함께 비교해 불일치 시 DROP 후 재생성한다.

    (COUNT, MAX)를 함께 보는 이유: 월 갱신(update_all)이 STANDARD/REG 조문을 DELETE 후
    재INSERT하는데(ingest_standards.py), clauses.clause_id가 AUTOINCREMENT라 재삽입 행은
    항상 더 높은 id를 받는다. 총 개수가 그대로인 경우(예: --skip-collect 재실행, 신규
    TERMS 문서가 없는 달) COUNT만 비교하면 통과하지만 FTS rowid는 이미 삭제된
    clause_id를 가리키는 상태가 된다 — MAX가 함께 일치해야 동일 rowset임이 보장된다."""
    expected = conn.execute(
        f"SELECT COUNT(*), COALESCE(MAX(clause_id),0) FROM clauses WHERE length(text) >= {FTS_MIN_CHARS}"
    ).fetchone()
    expected = tuple(expected)
    try:
        indexed = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0) FROM clauses_fts_docsize").fetchone()
        indexed = tuple(indexed)
    except sqlite3.OperationalError:
        indexed = None  # FTS 자체가 없음
    if indexed == expected:
        return
    conn.execute("DROP TABLE IF EXISTS clauses_fts")
    conn.executescript(f"{FTS_DDL};")
    conn.execute(f"""
        INSERT INTO clauses_fts(rowid, text, title)
        SELECT clause_id, text, COALESCE(title,'') FROM clauses WHERE length(text) >= {FTS_MIN_CHARS}
    """)
    conn.commit()


def resolve_clause(conn, key: str, title: str | None = None) -> int:
    """'STD_L 제34조' → clause_id. 0건/복수건이면 SystemExit(골든 무결성 게이트).

    동일 조문번호가 파싱 부산물(표 조각 등)로 중복 존재하는 문서(예: STD_S 제42조)는
    골든 엔트리의 선택적 "title" 필드로 좁힌다 — 좁힌 뒤에도 1건이 아니면 동일하게 실패."""
    member, no = key.split(None, 1)
    sql = ("SELECT clause_id FROM clauses c JOIN documents d USING(doc_id) "
           "WHERE d.member_cd=? AND c.clause_no=?")
    params = [member, no]
    if title:
        sql += " AND c.title=?"
        params.append(title)
    rows = conn.execute(sql, params).fetchall()
    if len(rows) != 1:
        raise SystemExit(f"골든 키 해석 실패: {key!r} — {len(rows)}건 매칭(조문번호 개정 여부 확인)")
    return rows[0][0]


def build(conn, idf, default_idf, golden):
    conn.execute(SCHEMA)
    conn.execute("DELETE FROM std_reg_map")
    seen, dups = set(), []
    for e in golden:
        if e["std"] in seen:
            dups.append(e["std"])
        seen.add(e["std"])
    if dups:
        raise SystemExit(f"골든 리스트에 중복된 std 키 존재(마지막 항목이 조용히 덮어씀): {sorted(set(dups))}")
    overrides = {resolve_clause(conn, e["std"], e.get("title")): e for e in golden}
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
