#!/usr/bin/env python3
"""표준약관 평문 → DB 적재(doc_type=STANDARD). 재실행 안전(발행처별 기존 STANDARD 교체).

사용법: .venv/bin/python src/ingest_standards.py
"""
import datetime
import hashlib
import re

from clause_split import split_clauses
from common import open_db
from standards_prep import load_manifest, to_plaintext

_RE_JO_NO = re.compile(r"^제\d+조(의\d+)?$")


def _clean_standard_chunks(chunks):
    """실손 5세대 PDF 등에서 clause_split이 PDF 교차참조(예: '제2조 제2호에따른…')를
    조문 헤더로 오탐하는 노이즈를 정리.

    실제 표준약관 조문은 전부 괄호 제목(`제N조(제목)`)을 가지므로 title이 채워짐.
    title이 빈 '제N조' 청크는 오탐으로 간주해 clause_no=None으로 강등하고, 텍스트는
    버리지 않고 직전 청크(실제 조문 본문)에 이어붙여 병합한다. 별표/전문 등 그 외
    청크는 그대로 통과시킨다.
    """
    cleaned = []
    for no, title, text in chunks:
        is_fake_jo = bool(no) and _RE_JO_NO.match(no) and not (title or "").strip()
        if is_fake_jo:
            if cleaned:
                prev_no, prev_title, prev_text = cleaned[-1]
                merged = f"{prev_text}\n{text}".strip() if prev_text else text
                cleaned[-1] = (prev_no, prev_title, merged)
            else:
                cleaned.append((None, title, text))
            continue
        cleaned.append((no, title, text))
    return cleaned


def ingest(conn, entry: dict, plaintext: str) -> int:
    mcd, name = entry["member_cd"], entry["name"]
    dt = entry.get("doc_type", "STANDARD")
    conn.execute("INSERT OR REPLACE INTO insurers(member_cd, name) VALUES(?,?)", (mcd, name))
    # 발행처의 기존 동일 doc_type 문서·조문 제거(멱등)
    old = [r[0] for r in conn.execute(
        "SELECT doc_id FROM documents WHERE member_cd=? AND doc_type=?", (mcd, dt))]
    if old:
        conn.executemany("DELETE FROM clauses WHERE doc_id=?", [(x,) for x in old])
        conn.executemany("DELETE FROM documents WHERE doc_id=?", [(x,) for x in old])
    sha = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    # documents 스키마는 환경별로 다를 수 있음(테스트 인메모리 스키마 vs. 실 schema.sql —
    # 실 스키마는 source_url/fetched_at NOT NULL, prod_group은 ALTER로 추가됨).
    # 대상 테이블에 실재하는 컬럼만 골라 INSERT — 둘 다 안전하게 동작.
    doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    candidates = {
        "member_cd": mcd,
        "prod_nm_raw": name,
        "doc_type": dt,
        "version_label": entry["version_label"],
        "file_path": entry["source_path"],
        "sha256": sha,
        "prod_group": entry["key"],
        "source_url": f"file://{entry['source_path']}",
        "fetched_at": now,
    }
    fields = [(k, v) for k, v in candidates.items() if k in doc_cols]
    col_sql = ", ".join(k for k, _ in fields)
    ph_sql = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO documents({col_sql}) VALUES({ph_sql})",
        [v for _, v in fields],
    )
    doc_id = cur.lastrowid
    chunks = _clean_standard_chunks(split_clauses(plaintext))
    conn.executemany(
        "INSERT INTO clauses(doc_id, seq, clause_no, title, text) VALUES(?,?,?,?,?)",
        [(doc_id, i, no, ti, tx) for i, (no, ti, tx) in enumerate(chunks)])
    conn.commit()
    return sum(1 for no, _, _ in chunks if no and no.startswith("제"))


def main():
    conn = open_db()
    for e in load_manifest():
        txt = to_plaintext(e)
        n = ingest(conn, e, txt)
        print(f"  [{e['key']}] {e['name']} ({e['version_label']}) — 조문 {n}개 적재")
    total = conn.execute("SELECT COUNT(*) FROM documents WHERE doc_type='STANDARD'").fetchone()[0]
    print(f"완료: STANDARD 문서 {total}건")
    conn.close()


if __name__ == "__main__":
    main()
