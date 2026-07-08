#!/usr/bin/env python3
"""협회 상품비교공시(pub.insure.or.kr) 카탈로그 수집 → SQLite products 적재.

파일럿 범위: 판매중 × (종신/질병/암) × (미래에셋 L34, 한화 L01, 삼성 L03, 교보 L05)
stdlib만 사용(폐쇄망 이식성). 요청 간 sleep으로 저빈도 유지.

사용법:
    python3 src/catalog_fetch.py            # 파일럿 기본 범위 수집
    python3 src/catalog_fetch.py --dry-run  # 1페이지만 받아 파싱 결과 출력
"""
import argparse
import datetime
import hashlib
import pathlib
import re
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request


def _ssl_context() -> ssl.SSLContext:
    # python.org 배포판은 certifi 미설치 시 CA 번들이 비어 있음 → macOS 기본 번들 폴백
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        for cafile in ("/etc/ssl/cert.pem",):
            if pathlib.Path(cafile).exists():
                return ssl.create_default_context(cafile=cafile)
        return ssl.create_default_context()


SSL_CTX = _ssl_context()

BASE = "https://pub.insure.or.kr"
LIST_URL = BASE + "/compareDis/prodCompare/assurance/listNew.do"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "terms.db"
SNAP_DIR = ROOT / "catalog" / "raw"

PROD_GROUPS = {
    "024400010001": "종신보험",
    "024400010003": "질병보험",
    "024400010004": "암보험",
}

INSURERS = {
    "L34": "미래에셋생명",
    "L01": "한화생명",
    "L03": "삼성생명",
    "L05": "교보생명",
    "L11": "신한라이프생명",
    "L42": "NH농협생명",
    "L61": "KB라이프생명",
    "L74": "동양생명",
    "L72": "메트라이프생명",
    "L04": "흥국생명",
}

PAGE_UNIT = 30
SLEEP_S = 2.0

# 상품 블록: 회사명 셀(js_spRspan_<prodCd>_2) ~ 다음 블록 직전
RE_BLOCK = re.compile(
    r'class="js_spRspan_([A-Za-z0-9]+)_2">\s*(.*?)\s*</td>(.*?)(?=class="js_spRspan_[A-Za-z0-9]+_2">|</table>)',
    re.S,
)
RE_PRODNM = re.compile(r'<a href="(http[^"]+)"[^>]*target="_blank"[^>]*>([^<]+)</a>')
RE_FILEDOWN = re.compile(r"fn_fileDown\('(\d+)'")
RE_SALEDATE = re.compile(r"(20\d{2}[.\-/]\d{2}[.\-/]\d{2})")


def http_post(url: str, data: dict, cookie: str = "") -> str:
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Referer", LIST_URL)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_get_cookie(url: str) -> str:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        resp.read()
        cookies = resp.headers.get_all("Set-Cookie") or []
    return "; ".join(c.split(";")[0] for c in cookies)


def parse_products(html: str):
    """페이지 HTML에서 상품 블록 추출 → dict 목록."""
    out = []
    for m in RE_BLOCK.finditer(html):
        prod_cd, member_nm, rest = m.group(1), m.group(2).strip(), m.group(3)
        a = RE_PRODNM.search(rest)
        ext_url, prod_nm = (a.group(1), a.group(2).strip()) if a else (None, None)
        f = RE_FILEDOWN.search(rest)
        d = RE_SALEDATE.search(rest)
        out.append({
            "prod_cd": prod_cd,
            "member_nm": member_nm,
            "prod_nm": prod_nm,
            "ext_url": ext_url,
            "summary_file_no": f.group(1) if f else None,
            "sale_start": d.group(1) if d else None,
        })
    return out


def fetch_group(group_cd: str, cookie: str, snapshot_prefix: str):
    """한 상품군을 페이지네이션 끝까지 수집. (prodCd 중복 등장 시 종료)"""
    seen = {}
    page = 1
    while page <= 30:  # 안전 상한
        data = {
            "pageIndex": page,
            "pageUnit": PAGE_UNIT,
            "search_prodGroup": group_cd,
            "search_memberCd": list(INSURERS.keys()),
        }
        html = http_post(LIST_URL, data, cookie)
        snap = SNAP_DIR / f"{snapshot_prefix}_{group_cd}_p{page}.html"
        snap.write_text(html, encoding="utf-8")
        rows = parse_products(html)
        new = [r for r in rows if r["prod_cd"] not in seen]
        print(f"  [{PROD_GROUPS[group_cd]}] page {page}: rows={len(rows)} new={len(new)}")
        if not new:
            break
        for r in new:
            r["snapshot_file"] = str(snap.relative_to(ROOT))
            seen[r["prod_cd"]] = r
        if len(rows) < PAGE_UNIT:
            break
        page += 1
        time.sleep(SLEEP_S)
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("세션 쿠키 취득...")
    cookie = http_get_cookie(LIST_URL)
    time.sleep(SLEEP_S)

    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stamp = datetime.datetime.now().strftime("%Y%m%d")

    if args.dry_run:
        gcd = next(iter(PROD_GROUPS))
        html = http_post(LIST_URL, {
            "pageIndex": 1, "pageUnit": PAGE_UNIT,
            "search_prodGroup": gcd,
            "search_memberCd": list(INSURERS.keys()),
        }, cookie)
        for r in parse_products(html):
            print(r)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.executescript((ROOT / "src" / "schema.sql").read_text())
    name2cd = {v: k for k, v in INSURERS.items()}
    for cd, nm in INSURERS.items():
        conn.execute("INSERT OR IGNORE INTO insurers(member_cd, name) VALUES(?,?)", (cd, nm))

    total = 0
    for gcd, gnm in PROD_GROUPS.items():
        rows = fetch_group(gcd, cookie, f"assurance_{stamp}")
        for r in rows:
            mcd = name2cd.get(r["member_nm"])
            if mcd is None:
                print(f"  ! 회사명 매핑 실패: {r['member_nm']!r} ({r['prod_cd']}) — 건너뜀")
                continue
            conn.execute(
                """INSERT INTO products(prod_cd, member_cd, prod_nm, prod_group_cd, prod_group_nm,
                       ext_url, sale_start, summary_file_no, fetched_at, snapshot_file)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(prod_cd) DO UPDATE SET
                       prod_nm=excluded.prod_nm, ext_url=excluded.ext_url,
                       sale_start=excluded.sale_start, summary_file_no=excluded.summary_file_no,
                       fetched_at=excluded.fetched_at, snapshot_file=excluded.snapshot_file""",
                (r["prod_cd"], mcd, r["prod_nm"], gcd, gnm, r["ext_url"],
                 r["sale_start"], r["summary_file_no"], now, r["snapshot_file"]),
            )
            # 회사 공시실 진입 URL을 insurers에도 반영(최신 것으로)
            if r["ext_url"]:
                conn.execute("UPDATE insurers SET disclosure_url=? WHERE member_cd=?", (r["ext_url"], mcd))
            total += 1
        conn.commit()
        time.sleep(SLEEP_S)

    print(f"완료: products {total}건 적재 → {DB_PATH}")
    for row in conn.execute(
        "SELECT i.name, p.prod_group_nm, COUNT(*) FROM products p JOIN insurers i USING(member_cd) GROUP BY 1,2 ORDER BY 1,2"
    ):
        print(f"  {row[0]} × {row[1]}: {row[2]}건")
    conn.close()


if __name__ == "__main__":
    main()
