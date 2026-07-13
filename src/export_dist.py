#!/usr/bin/env python3
"""Phase 4: 폐쇄망 반입용 단일 SQLite 생성 (db/terms_dist.db).

포함: insurers / products / documents(메타) / clauses(전체 텍스트) / clauses_fts(FTS5 전문검색)
제외: PDF 원본(사외 보관). documents.file_path는 원본 참조용으로 유지.
FTS는 30자 미만 청크(목차 라인 등) 제외 — clauses 자체는 전량 보존(원문 복원 가능).

사용법: .venv/bin/python src/export_dist.py
"""
import argparse
import pathlib
import sqlite3

from common import DB_PATH, FTS_DDL, FTS_MIN_CHARS, ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-only", action="store_true",
                    help="현행 판매기간 문서만 포함(과거판 제외) — 반입 용량 축소")
    args = ap.parse_args()
    DIST_PATH = ROOT / "db" / ("terms_dist_current.db" if args.current_only else "terms_dist.db")
    if DIST_PATH.exists():
        DIST_PATH.unlink()
    src = sqlite3.connect(DB_PATH)
    src.execute(f"ATTACH DATABASE '{DIST_PATH}' AS dist")

    for tbl in ("insurers", "products", "documents", "clauses", "product_doc_map",
                "ngram_idf", "simindex_meta", "std_reg_map"):
        ddl_row = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
        if ddl_row is None:
            hint = "build_std_reg_map" if tbl == "std_reg_map" else "build_simindex"
            print(f"  (건너뜀: {tbl} 없음 — {hint} 먼저 실행 권장)")
            continue
        ddl = ddl_row[0]
        src.execute(ddl.replace(f"TABLE {tbl}", f"TABLE dist.{tbl}", 1)
                       .replace(f"TABLE IF NOT EXISTS {tbl}", f"TABLE IF NOT EXISTS dist.{tbl}", 1))
        if args.current_only and tbl == "documents":
            src.execute("INSERT INTO dist.documents SELECT * FROM main.documents "
                        "WHERE doc_type IN ('STANDARD','REG') OR TRIM(version_label) LIKE '%~' "
                        "OR version_label LIKE '%현재' OR version_label=''")
        elif args.current_only and tbl == "product_doc_map":
            src.execute("INSERT INTO dist.product_doc_map SELECT m.* FROM main.product_doc_map m "
                        "JOIN dist.documents d USING(doc_id)")
        elif args.current_only and tbl == "clauses":
            src.execute("INSERT INTO dist.clauses SELECT c.* FROM main.clauses c "
                        "JOIN dist.documents d USING(doc_id)")
        elif args.current_only and tbl == "std_reg_map":
            # 양끝 clause가 dist에 실재하는 행만(STANDARD·REG는 현행판에 항상 포함되므로 실질 전량).
            # none 행(reg_clause_id NULL)은 std 쪽만 확인.
            src.execute("INSERT INTO dist.std_reg_map SELECT m.* FROM main.std_reg_map m "
                        "JOIN dist.clauses cs ON cs.clause_id = m.std_clause_id "
                        "LEFT JOIN dist.clauses cr ON cr.clause_id = m.reg_clause_id "
                        "WHERE m.reg_clause_id IS NULL OR cr.clause_id IS NOT NULL")
        else:
            src.execute(f"INSERT INTO dist.{tbl} SELECT * FROM main.{tbl}")
    src.commit()
    src.execute("DETACH DATABASE dist")
    src.close()

    dist = sqlite3.connect(DIST_PATH)
    dist.executescript(f"""
        CREATE INDEX idx_documents_member ON documents(member_cd);
        CREATE INDEX idx_clauses_doc2 ON clauses(doc_id);
        {FTS_DDL};
    """)
    dist.execute(f"""
        INSERT INTO clauses_fts(rowid, text, title)
        SELECT clause_id, text, COALESCE(title,'') FROM clauses WHERE length(text) >= {FTS_MIN_CHARS}
    """)
    dist.commit()

    n_docs = dist.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_cl = dist.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
    n_fts = dist.execute("SELECT COUNT(*) FROM clauses_fts").fetchone()[0]
    dist.execute("VACUUM")
    dist.close()

    size = DIST_PATH.stat().st_size
    print(f"생성: {DIST_PATH}")
    print(f"  documents {n_docs:,} / clauses {n_cl:,} / FTS 인덱싱 {n_fts:,}")
    print(f"  파일 크기: {size/1048576:.1f}MB")
    print("\n검색 예시:")
    print("  SELECT d.prod_nm_raw, c.clause_no, c.title FROM clauses_fts f")
    print("  JOIN clauses c ON c.clause_id=f.rowid JOIN documents d USING(doc_id)")
    print("  WHERE clauses_fts MATCH '대장점막내암' LIMIT 10;")


if __name__ == "__main__":
    main()
