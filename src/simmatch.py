#!/usr/bin/env python3
"""문자 n-gram TF-IDF 코사인 유사도 (표준 라이브러리 전용).

빌드 시점 산출 IDF(ngram_idf 테이블)를 dict로 받아, 런타임에 조문 두 개의
코사인을 계산한다. FTS 후보 검색은 db_similar()에서 결합(Task 6).
"""
import math
import re
import unicodedata
from collections import Counter

_KEEP = re.compile(r"[^가-힣a-z0-9]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower()
    return _KEEP.sub("", t)


def char_ngrams(text: str, sizes=(3, 4)):
    t = normalize(text)
    grams = []
    for nsz in sizes:
        if len(t) >= nsz:
            grams.extend(t[k:k + nsz] for k in range(len(t) - nsz + 1))
    return grams


def vectorize(text: str, idf: dict, default_idf: float) -> dict:
    tf = Counter(char_ngrams(text))
    vec = {g: (1.0 + math.log(c)) * idf.get(g, default_idf) for g, c in tf.items()}
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {g: w / norm for g, w in vec.items()}


def cosine(v1: dict, v2: dict) -> float:
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    return sum(w * v2.get(g, 0.0) for g, w in v1.items())


def load_idf(conn):
    """ngram_idf/simindex_meta → (idf dict, default_idf). 앱 시작 시 1회 로드."""
    idf = {g: v for g, v in conn.execute("SELECT ngram, idf FROM ngram_idf")}
    meta = dict(conn.execute("SELECT key, value FROM simindex_meta"))
    default_idf = float(meta.get("default_idf", 1.0))
    return idf, default_idf


def fts_query(text: str, max_terms: int = 15) -> str:
    """조문에서 변별력 있는 어절 상위 N개를 OR로 결합한 FTS5 질의."""
    toks = re.findall(r"[가-힣a-z0-9]{2,}", (text or "").lower())
    seen, terms = set(), []
    for t in sorted(toks, key=len, reverse=True):
        if t not in seen:
            seen.add(t)
            terms.append(t)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms)


_SQL = """SELECT c.clause_id, c.clause_no, c.title, c.text, d.doc_id, d.member_cd,
                 d.prod_nm_raw, d.version_label, d.prod_group, i.name AS insurer,
                 bm25(clauses_fts) AS bm
          FROM clauses_fts f JOIN clauses c ON c.clause_id=f.rowid
          JOIN documents d USING(doc_id) JOIN insurers i ON i.member_cd=d.member_cd
          WHERE clauses_fts MATCH ?"""


def db_similar(conn, query_text, idf, default_idf, top_n=10,
               exclude_member=None, prod_group=None, query_title=None, cand_limit=300):
    fq = fts_query(query_text)
    if not fq:
        return []
    sql, params = _SQL, [fq]
    if exclude_member:
        sql += " AND d.member_cd<>?"
        params.append(exclude_member)
    if prod_group:
        sql += " AND d.prod_group=?"
        params.append(prod_group)
    sql += " ORDER BY rank LIMIT ?"
    params.append(cand_limit)

    qv = vectorize(query_text, idf, default_idf)
    qtitle = normalize(query_title) if query_title else ""
    rows = list(conn.execute(sql, params))
    if not rows:
        return []

    cos_vals = [cosine(qv, vectorize(r["text"], idf, default_idf)) for r in rows]
    bms = [r["bm"] for r in rows]
    lo, hi = min(bms), max(bms)  # bm25(): 더 음수일수록(작을수록) 매칭 우수

    # BM25(단어 단위, 희귀어에 강함)를 코사인(char n-gram)에 블렌딩해
    # 상용구 표면형 과대보상을 완화한다. 가중치 0.7/0.3은 골든 진단으로 튜닝됨
    # (작업 리포트/골든셋 진단: Q2 "납입최고" 케이스가 top-5에서 밀려나는 문제 해결).
    BM25_W = 0.3
    out = []
    for r, cos, bm in zip(rows, cos_vals, bms):
        bm_norm = (hi - bm) / (hi - lo) if hi > lo else 0.0
        score = (1 - BM25_W) * cos + BM25_W * bm_norm
        if qtitle and normalize(r["title"] or "") == qtitle:
            score += 0.05           # 조문제목 일치 가산점
        out.append({"score": round(score, 4), **{k: r[k] for k in r.keys()}})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_n]
