#!/usr/bin/env python3
"""Phase 3: 협회 카탈로그(products) ↔ 수집 문서(documents) 정식 매칭.

협회는 유형 단위(기본형/무해약환급금형 등), 사이트 문서는 통합약관 단위라
1:1이 아닌 N:M — 별도 매핑 테이블 product_doc_map으로 연결한다.

매칭 방법(우선순위):
  head   — 상품명 머리(무배당/괄호 앞) 상호 substring
  full   — 전체명 정규화(공백·괄호류·무배당·회사명 제거) 후 core substring
매칭 결과는 method 컬럼에 기록. 재실행 시 테이블 재구축(멱등).

사용법: .venv/bin/python src/build_matches.py
"""
import re
import unicodedata

from common import open_db

MAP_SCHEMA = """
DROP TABLE IF EXISTS product_doc_map;
CREATE TABLE product_doc_map (
    prod_cd   TEXT NOT NULL REFERENCES products(prod_cd),
    doc_id    INTEGER NOT NULL REFERENCES documents(doc_id),
    method    TEXT NOT NULL,          -- head / full
    PRIMARY KEY (prod_cd, doc_id)
);
CREATE INDEX idx_pdm_doc ON product_doc_map(doc_id);
"""

RE_COMPANY = r"삼성생명|삼성|교보생명|교보|한화생명|미래에셋생명|신한라이프|신한|NH농협생명|농협|NH|KB라이프|KB|동양생명|동양|메트라이프생명|메트라이프|흥국생명|흥국|New\s|\(무\)"


def head(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"^\s*\((무|無)\)\s*", "", s)
    m = re.split(r"무배당|\[|\(", s)[0]
    m = re.sub(RE_COMPANY, "", m.strip())
    m = re.sub(r"\s+", "", m)
    return re.sub(r"[_\-]?\d{4,6}$", "", m).rstrip("_-")


def full_norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\(무\)|무배당|" + RE_COMPANY, "", s)
    return re.sub(r"[\s\[\]【】()〔〕·,_]", "", s)


def core(s: str) -> str:
    f = full_norm(s)
    return f.split("보험")[0] + "보험" if "보험" in f else f


def main():
    conn = open_db()
    conn.executescript(MAP_SCHEMA)

    products = conn.execute("SELECT prod_cd, member_cd, prod_nm FROM products").fetchall()
    documents = conn.execute("SELECT doc_id, member_cd, prod_nm_raw FROM documents").fetchall()

    docs_by_member = {}
    for doc_id, mcd, pn in documents:
        docs_by_member.setdefault(mcd, []).append((doc_id, head(pn), full_norm(pn)))

    n_pairs = 0
    matched_products = set()
    matched_docs = set()
    for prod_cd, mcd, pnm in products:
        ph, pc = head(pnm), core(pnm)
        for doc_id, dh, df in docs_by_member.get(mcd, []):
            if len(ph) >= 4 and dh and (ph in dh or dh in ph):
                method = "head"
            elif len(pc) >= 4 and pc in df:
                method = "full"
            else:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO product_doc_map(prod_cd, doc_id, method) VALUES(?,?,?)",
                (prod_cd, doc_id, method),
            )
            n_pairs += 1
            matched_products.add(prod_cd)
            matched_docs.add(doc_id)
    conn.commit()

    n_prod = len(products)
    n_docs = len(documents)
    print(f"매핑 {n_pairs:,}쌍 생성")
    print(f"  카탈로그 상품 {n_prod}건 중 문서 연결 {len(matched_products)}건")
    print(f"  문서 {n_docs}건 중 카탈로그 연결 {len(matched_docs)}건 "
          f"(미연결 {n_docs - len(matched_docs)}건 = 비파일럿 인접상품·과거명칭)")
    for row in conn.execute("""
        SELECT i.name, COUNT(DISTINCT m.prod_cd), COUNT(DISTINCT m.doc_id)
        FROM product_doc_map m JOIN products p USING(prod_cd) JOIN insurers i ON i.member_cd=p.member_cd
        GROUP BY 1 ORDER BY 1"""):
        print(f"  {row[0]}: 상품 {row[1]} ↔ 문서 {row[2]}")
    conn.close()


if __name__ == "__main__":
    main()
