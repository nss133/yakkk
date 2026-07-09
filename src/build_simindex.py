#!/usr/bin/env python3
"""문자 n-gram IDF를 코퍼스에서 산출해 ngram_idf 테이블에 적재(빌드 시점).

- 대상: clauses.text 중 length>=30 (FTS 인덱싱 대상과 동일)
- df_floor 미만(희귀) / df_ceil_ratio 초과(너무 흔함) n-gram은 제외
- 미등재 n-gram의 런타임 기본 idf(default_idf)를 simindex_meta에 저장
사용법: .venv/bin/python src/build_simindex.py
"""
import argparse
import math
from collections import defaultdict

from common import open_db
from simmatch import char_ngrams

SCHEMA = """
CREATE TABLE IF NOT EXISTS ngram_idf(ngram TEXT PRIMARY KEY, idf REAL);
CREATE TABLE IF NOT EXISTS simindex_meta(key TEXT PRIMARY KEY, value TEXT);
"""


def build(conn, df_floor: int = 3, df_ceil_ratio: float = 0.4):
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM ngram_idf")
    conn.execute("DELETE FROM simindex_meta")

    rows = conn.execute("SELECT text FROM clauses WHERE length(text) >= 30")
    df = defaultdict(int)
    n_docs = 0
    for (text,) in rows:
        n_docs += 1
        for g in set(char_ngrams(text)):
            df[g] += 1
    if n_docs == 0:
        raise SystemExit("clauses가 비어 있음 — 먼저 extract_index 실행")

    ceil = max(df_floor, int(n_docs * df_ceil_ratio))
    kept = [(g, math.log((n_docs + 1) / (d + 1)) + 1.0)
            for g, d in df.items() if df_floor <= d <= ceil]
    conn.executemany("INSERT OR REPLACE INTO ngram_idf(ngram, idf) VALUES(?,?)", kept)

    default_idf = math.log((n_docs + 1) / (max(1, df_floor - 1) + 1)) + 1.0
    conn.executemany("INSERT OR REPLACE INTO simindex_meta(key, value) VALUES(?,?)",
                     [("n_docs", str(n_docs)), ("default_idf", f"{default_idf:.6f}")])
    conn.commit()
    return len(kept), n_docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--df-floor", type=int, default=3)
    ap.add_argument("--df-ceil-ratio", type=float, default=0.4)
    args = ap.parse_args()
    conn = open_db()
    n_kept, n_docs = build(conn, args.df_floor, args.df_ceil_ratio)
    size = conn.execute("SELECT COUNT(*) FROM ngram_idf").fetchone()[0]
    conn.close()
    print(f"완료: n-gram {n_kept:,}개 적재 (문서 {n_docs:,}) — ngram_idf {size:,}행")


if __name__ == "__main__":
    main()
