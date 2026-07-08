#!/usr/bin/env python3
"""조항 후처리: 섹션(주계약/특약) 태깅 + 문서 상품군 라벨.

통합약관 PDF는 [주계약 약관][특약1 약관][특약2 약관]…이 이어지는 구조.
'제1조' 재시작 = 새 섹션 시작으로 보고 섹션 번호를 매긴 뒤,
섹션 앞머리 조문의 특약 표지("특약의 내용/적용범위" 제목, "이 특약은…" 본문)로
주계약/특약을 판정한다. 섹션명은 특약 제1조 본문의 "이 특약(…)" 괄호에서 추출(실패 시 공백).

documents.prod_group: product_doc_map 다수결로 협회 상품군(종신/질병/암…) 라벨 부여.

멱등: 재실행 시 전체 재계산. extract_index 이후·export_dist 이전에 실행.
"""
import re

from common import open_db

RIDER_TITLE = re.compile(r"특약의\s*(내용|적용범위|체결|목적)|특약\s*의\s*보장개시")
RIDER_BODY = re.compile(r"^\s*이\s*특약")
NAME_IN_BODY = re.compile(r"이\s*특약\s*[(（]\s*([^)）]{3,60})\s*[)）]")


def ensure_columns(conn):
    for tbl, col, ddl in [
        ("clauses", "section_no", "ALTER TABLE clauses ADD COLUMN section_no INTEGER"),
        ("clauses", "is_rider", "ALTER TABLE clauses ADD COLUMN is_rider INTEGER"),
        ("clauses", "section_title", "ALTER TABLE clauses ADD COLUMN section_title TEXT"),
        ("documents", "prod_group", "ALTER TABLE documents ADD COLUMN prod_group TEXT"),
    ]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        if col not in cols:
            conn.execute(ddl)


def jo_num(clause_no):
    m = re.match(r"제(\d+)조", clause_no or "")
    return int(m.group(1)) if m else None


def tag_document(rows):
    """rows: [(clause_id, seq, clause_no, title, text)] seq순.
    반환: {clause_id: (section_no, is_rider, section_title)}"""
    out = {}
    section_no = 0
    seen_jo_in_section = False
    prev_jo = 0
    sections = []  # [(section_no, [row_idx...])]
    cur_idxs = []

    for idx, (cid, seq, cno, title, text) in enumerate(rows):
        n = jo_num(cno)
        if n == 1 and seen_jo_in_section and prev_jo != 1:
            # 새 섹션 시작 (제1조 중복 청크(목차 잔재, prev_jo==1)는 제외)
            sections.append((section_no, cur_idxs))
            section_no += 1
            cur_idxs = []
            seen_jo_in_section = False
        cur_idxs.append(idx)
        if n is not None:
            seen_jo_in_section = True
            prev_jo = n
    sections.append((section_no, cur_idxs))

    for sno, idxs in sections:
        # 특약 판정: 섹션 앞머리 조문 8개의 제목·본문 검사
        is_rider = 0
        s_title = ""
        checked = 0
        for idx in idxs:
            cid, seq, cno, title, text = rows[idx]
            if jo_num(cno) is None:
                continue
            checked += 1
            if RIDER_TITLE.search(title or "") or RIDER_BODY.search(text or ""):
                is_rider = 1
            m = NAME_IN_BODY.search(text or "")
            if m and not s_title:
                s_title = m.group(1).strip()
            if checked >= 8:
                break
        # 본문에 "특약" 언급이 제목 수준에서 지속되면 특약으로 보정
        if not is_rider:
            rider_hits = sum(1 for idx in idxs[:20]
                             if "특약" in ((rows[idx][3] or "") + (rows[idx][4] or "")[:80]))
            if rider_hits >= 6:
                is_rider = 1
        for idx in idxs:
            out[rows[idx][0]] = (sno, is_rider, s_title)
    return out


def main():
    conn = open_db()
    ensure_columns(conn)

    doc_ids = [r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM clauses")]
    print(f"섹션 태깅 대상 문서 {len(doc_ids)}건")
    n_riders = 0
    for i, did in enumerate(doc_ids, 1):
        rows = conn.execute(
            "SELECT clause_id, seq, clause_no, title, text FROM clauses WHERE doc_id=? ORDER BY seq",
            (did,)).fetchall()
        tags = tag_document(rows)
        conn.executemany(
            "UPDATE clauses SET section_no=?, is_rider=?, section_title=? WHERE clause_id=?",
            [(s, r, t, cid) for cid, (s, r, t) in tags.items()])
        n_riders += sum(1 for v in tags.values() if v[1])
        if i % 100 == 0:
            conn.commit()
            print(f"  {i}/{len(doc_ids)}")
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
    riders = conn.execute("SELECT COUNT(*) FROM clauses WHERE is_rider=1").fetchone()[0]
    print(f"조항 {total:,}개 중 특약 소속 {riders:,}개 ({100*riders/total:.0f}%)")

    # 문서 상품군 라벨 (product_doc_map 다수결)
    conn.execute("""
        UPDATE documents SET prod_group = (
            SELECT p.prod_group_nm FROM product_doc_map m JOIN products p USING(prod_cd)
            WHERE m.doc_id = documents.doc_id
            GROUP BY p.prod_group_nm ORDER BY COUNT(*) DESC LIMIT 1)
    """)
    conn.commit()
    for row in conn.execute(
            "SELECT COALESCE(prod_group,'(미분류)'), COUNT(*) FROM documents GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  상품군 {row[0]}: {row[1]}건")
    conn.close()


if __name__ == "__main__":
    main()
