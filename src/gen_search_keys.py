#!/usr/bin/env python3
"""협회 카탈로그(products) → 회사별 검색키 JSON 생성.

키 = 상품명 head(무배당/괄호 앞, 회사 접두어 제거). 같은 head의 유형 분화 상품은 묶임.
variants: 사이트 검색 실패 대비 변형(공백 제거 등) — 수집기 --raw-keys 보완 시 참고.
※ 교훈(2026-07-07): 삼성은 상품명이 공백 없이 연결되어 공백 포함 키가 0건 반환될 수 있고,
   exact 명칭("The(더)Dream")이 통하는 경우도 있음. 커버리지 미달 키는 변형으로 재시도할 것.

사용법: .venv/bin/python src/gen_search_keys.py
"""
import json
import re
import unicodedata

from common import ROOT, open_db

TAGS = {"L03": "samsung", "L01": "hanwha", "L05": "kyobo", "L11": "shinhan",
        "L42": "nh", "L61": "kb", "L74": "dongyang", "L72": "metlife", "L04": "heungkuk"}


def head(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"^\s*\((무|無)\)\s*", "", s)  # 선두 (무) 제거(동양 등)
    s = re.sub(r"^\s*무배당\s*", "", s)          # 선두 무배당 제거
    s = re.sub(r"\((간편가입|간편|일반가입)\)", "", s)  # 중간 (간편가입) 토큰 제거(신한 등)
    s = re.sub(r"_(간편|일반)심사형$", "", s.strip())  # 말미 심사형 접미(동양)
    m = re.split(r"무배당|\[|\(", s)[0]
    m = re.sub(r"^(삼성생명|삼성|교보생명|교보|한화생명|미래에셋생명|신한라이프|신한|NH농협생명|농협|KB라이프|KB|동양생명|동양|메트라이프생명|메트라이프|흥국생명|흥국)\s*", "", m.strip())
    return re.sub(r"\s+", " ", m).strip()


def main():
    conn = open_db()
    for mcd, tag in TAGS.items():
        rows = conn.execute(
            "SELECT prod_cd, prod_nm, prod_group_nm FROM products WHERE member_cd=?", (mcd,)
        ).fetchall()
        keys = {}
        for pcd, pnm, grp in rows:
            k = head(pnm)
            if len(k.replace(" ", "")) < 3:
                k = pnm.strip()  # head가 너무 짧으면 전체명 사용
            keys.setdefault(k, []).append({"prod_cd": pcd, "prod_nm": pnm, "grp": grp})
        out = [
            {"search_key": k, "variants": sorted({k.replace(" ", "")} - {k}), "members": v}
            for k, v in sorted(keys.items())
        ]
        path = ROOT / "catalog" / f"searchkeys_{tag}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"{tag}({mcd}): 상품 {len(rows)}건 → 검색키 {len(keys)}개 → {path.name}")
    conn.close()


if __name__ == "__main__":
    main()
