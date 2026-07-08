#!/usr/bin/env python3
"""Phase 4: PDF → 텍스트 추출 + 조항 분할 + clauses 테이블 적재.

- documents(doc_type=TERMS)의 PDF를 PyMuPDF로 추출
- '제N조(제목)' 헤더(단독행·인라인 모두)와 '별표N' 헤더로 분할
- 문서 전체를 빠짐없이 청크로 보존(전문·목차·별표 포함) → concat하면 원문 복원
- 재실행 안전: 이미 clauses가 있는 doc_id는 스킵

사용법:
    .venv/bin/python src/extract_index.py            # 전체
    .venv/bin/python src/extract_index.py --member L34 --limit 5
"""
import argparse
import re

import fitz

from common import ROOT, open_db

CLAUSES_SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses (
    clause_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     INTEGER NOT NULL REFERENCES documents(doc_id),
    seq        INTEGER NOT NULL,          -- 문서 내 순번(원문 복원용)
    clause_no  TEXT,                      -- '제3조', '제3조의2', '별표4', NULL(전문/목차 등)
    title      TEXT,
    text       TEXT NOT NULL,
    UNIQUE(doc_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_clauses_doc ON clauses(doc_id);
"""

# 제N조 / 제N조의M — 행 시작에서만 (인라인 본문 시작 허용)
RE_JO = re.compile(r"^\s*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(?:\(([^)]{1,60})\))?\s*(.*)$")
# 별표 N (제목)
RE_BYULPYO = re.compile(r"^\s*[\[(【]?\s*(별\s*표\s*\d*)\s*[\])】]?\s*(.{0,60})$")


def norm_no(s: str) -> str:
    return re.sub(r"\s+", "", s)


def split_clauses(text: str):
    """문서 전체를 순차 청크로 분할. 반환: [(clause_no|None, title, text)]"""
    lines = text.split("\n")
    chunks = []
    cur_no, cur_title, cur_lines = None, "", []

    def flush():
        nonlocal cur_no, cur_title, cur_lines
        body = "\n".join(cur_lines).strip()
        if body or cur_no:
            chunks.append((cur_no, cur_title, body))
        cur_no, cur_title, cur_lines = None, "", []

    for ln in lines:
        m = RE_JO.match(ln)
        if m:
            flush()
            cur_no = norm_no(m.group(1))
            cur_title = (m.group(2) or "").strip()
            rest = (m.group(3) or "").strip()
            cur_lines = [rest] if rest else []
            continue
        mb = RE_BYULPYO.match(ln)
        if mb and len(ln.strip()) < 70:
            flush()
            cur_no = norm_no(mb.group(1))
            cur_title = mb.group(2).strip()
            cur_lines = []
            continue
        cur_lines.append(ln)
    flush()

    # 앞부분 전문(제1조 이전) 라벨
    out = []
    for i, (no, title, body) in enumerate(chunks):
        if no is None:
            title = title or ("[전문]" if i == 0 else "[본문외]")
        out.append((no, title, body))
    return out


def extract_pdf_text(path) -> str:
    doc = fitz.open(path)
    pages = []
    for pg in doc:
        pages.append(pg.get_text())
    doc.close()
    t = "\n".join(pages)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--member", default="", help="회사코드 한정(L34 등)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--doc-types", default="TERMS")
    args = ap.parse_args()

    conn = open_db()
    conn.executescript(CLAUSES_SCHEMA)

    q = ("SELECT doc_id, member_cd, prod_nm_raw, file_path FROM documents "
         f"WHERE doc_type IN ({','.join('?' * len(args.doc_types.split(',')))})")
    params = args.doc_types.split(",")
    if args.member:
        q += " AND member_cd=?"
        params.append(args.member)
    docs = conn.execute(q, params).fetchall()

    done_ids = {r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM clauses")}
    todo = [d for d in docs if d[0] not in done_ids]
    if args.limit:
        todo = todo[: args.limit]
    print(f"대상 {len(docs)}건 중 미처리 {len(todo)}건 처리 시작")

    n_ok = n_err = 0
    for doc_id, mcd, pnm, fpath in todo:
        p = ROOT / fpath
        if not p.exists():
            print(f"  ! 파일 없음: {fpath}")
            n_err += 1
            continue
        try:
            text = extract_pdf_text(p)
            chunks = split_clauses(text)
            jo_cnt = sum(1 for no, _, _ in chunks if no and no.startswith("제"))
            conn.executemany(
                "INSERT OR IGNORE INTO clauses(doc_id, seq, clause_no, title, text) VALUES(?,?,?,?,?)",
                [(doc_id, i, no, ti, tx) for i, (no, ti, tx) in enumerate(chunks)],
            )
            conn.commit()
            n_ok += 1
            if n_ok % 25 == 0 or args.limit:
                print(f"  [{n_ok}/{len(todo)}] {mcd} {pnm[:30]}: 청크 {len(chunks)} (조문 {jo_cnt})")
        except Exception as e:
            n_err += 1
            print(f"  ! 추출 실패 doc_id={doc_id} {pnm[:30]}: {str(e)[:80]}")

    total_clauses = conn.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
    print(f"\n완료: 성공 {n_ok}, 실패 {n_err} | 총 조항청크 {total_clauses:,}")
    conn.close()


if __name__ == "__main__":
    main()
