#!/usr/bin/env python3
"""파일럿 커버리지 검증: 협회 카탈로그(products) 대비 수집 문서(documents) 대조.

- 가족 단위 매칭: 상품명 head(무배당/괄호 앞, 회사접두어·공백 제거) 비교
- 검색키 커버리지: searchkeys_<tag>.json 대비 documents.src_category
"""
import json
import re
import sqlite3
import unicodedata

from common import DB_PATH, ROOT

INSURERS = {
    "L34": ("미래에셋생명", None),        # 미래에셋은 targets_L34_pilot.json 방식
    "L01": ("한화생명", "hanwha"),
    "L03": ("삼성생명", "samsung"),
    "L05": ("교보생명", "kyobo"),
    "L11": ("신한라이프생명", "shinhan"),
    "L42": ("NH농협생명", "nh"),
    "L61": ("KB라이프생명", "kb"),
    "L74": ("동양생명", "dongyang"),
    "L72": ("메트라이프생명", "metlife"),
    "L04": ("흥국생명", "heungkuk"),
}


def head(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"^\s*\((무|無)\)\s*", "", s)
    m = re.split(r"무배당|\[|\(", s)[0]
    m = re.sub(r"^(삼성생명|삼성|교보생명|교보|한화생명|미래에셋생명|신한라이프|신한|NH농협생명|농협|NH|KB라이프|KB|동양생명|동양|메트라이프생명|메트라이프|흥국생명|흥국)\s*", "", m.strip())
    m = re.sub(r"\s+", "", m)
    m = re.sub(r"[_\-]?\d{4,6}$", "", m)  # 말미 버전코드(_2601 등)
    return m.rstrip("_-")


def main():
    conn = sqlite3.connect(DB_PATH)
    grand = {"cat": 0, "cov": 0, "docs": 0, "size": 0}

    for mcd, (name, tag) in INSURERS.items():
        cat = conn.execute(
            "SELECT prod_cd, prod_nm, prod_group_nm FROM products WHERE member_cd=?", (mcd,)
        ).fetchall()
        docs = conn.execute(
            "SELECT prod_nm_raw, src_category, COUNT(*), SUM(file_size) FROM documents "
            "WHERE member_cd=? AND doc_type='TERMS' GROUP BY prod_nm_raw", (mcd,)
        ).fetchall()
        n_docs, size = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(file_size),0) FROM documents WHERE member_cd=?", (mcd,)
        ).fetchone()

        doc_heads = {}
        for pn, sc, c, sz in docs:
            h = head(pn)
            if len(h) >= 4:
                doc_heads.setdefault(h, []).append(pn)

        def full_norm(s):
            s = unicodedata.normalize("NFC", s or "")
            # 단어 제거를 괄호 제거보다 먼저 — "(무)"가 괄호 제거 후 "무"로 남는 것 방지
            s = re.sub(r"\(무\)|무배당|삼성생명|삼성|교보생명|교보|한화생명|미래에셋생명|신한라이프|신한|NH농협생명|농협|NH|KB라이프|KB|동양생명|동양|메트라이프생명|메트라이프|흥국생명|흥국", "", s)
            s = re.sub(r"[\s\[\]【】()〔〕·,_]", "", s)
            return s

        doc_fulls = [full_norm(pn) for pn, _, _, _ in docs]
        covered, missing = [], []
        for pcd, pnm, grp in cat:
            h = head(pnm)
            hit = len(h) >= 4 and any(h in dh or dh in h for dh in doc_heads)
            if not hit:
                # head가 짧은 상품(올백·곰두리·암보험 등)은 전체명 정규화 substring 매칭 폴백
                f = full_norm(pnm)
                core = re.split(r"보험", f)[0] + "보험" if "보험" in f else f
                hit = len(core) >= 4 and any(core in df for df in doc_fulls)
            (covered if hit else missing).append((grp, pnm))

        pct = 100 * len(covered) / len(cat) if cat else 0
        print(f"\n{'='*70}\n[{name} {mcd}] 카탈로그 {len(cat)}건 중 커버 {len(covered)}건 ({pct:.0f}%) | "
              f"문서 {n_docs}건 / {size/1048576:.0f}MB / 수집상품 {len(docs)}종")
        if missing:
            print("  미커버 상품:")
            for grp, pnm in missing:
                print(f"   ✗ [{grp}] {pnm}")

        if tag:
            keys = {e["search_key"] for e in json.loads((ROOT / "catalog" / f"searchkeys_{tag}.json").read_text())}
            got = {r[0] for r in conn.execute(
                "SELECT DISTINCT src_category FROM documents WHERE member_cd=?", (mcd,))}
            nk = keys - got
            print(f"  검색키: {len(keys)}개 중 수집 {len(keys & got)}개" + (f", 미수집 {sorted(nk)}" if nk else ""))

        grand["cat"] += len(cat); grand["cov"] += len(covered)
        grand["docs"] += n_docs; grand["size"] += size

    print(f"\n{'='*70}\n[총계] 카탈로그 {grand['cat']}건 중 커버 {grand['cov']}건 "
          f"({100*grand['cov']/grand['cat']:.0f}%) | 문서 {grand['docs']}건 / {grand['size']/1073741824:.2f}GB")
    conn.close()


if __name__ == "__main__":
    main()
