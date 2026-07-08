#!/usr/bin/env python3
"""신한라이프생명(L11) 판매중 상품공시 약관 수집기.

플로우(cdhi0030.do): #meta05 검색 → #GoodsList > tr 행 스캔 →
행 내 버튼 id 끝자리 _1=요약서/_2=사업방법서/_3=약관, data-ws-id·data-url 속성 →
/repo/<wsId>/… 경로를 /bizxpress/… 로 치환한 URL을 세션 쿠키로 GET (yakk 검증 방식).

사용법:
    .venv/bin/python src/collect_shinhan.py --limit 2 --keys "신한몸튼튼"
    .venv/bin/python src/collect_shinhan.py
"""
import argparse
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L11"
TAG = "shinhan"
LIST_URL = "https://www.shinhanlife.co.kr/hp/cdhi0030.do"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2


def encode_path(rel: str) -> str:
    if not rel.startswith("/"):
        rel = "/" + rel
    return "/" + "/".join(quote(p, safe="") for p in rel.split("/") if p)


def resolve_url(ws_id: str, repo_path: str, origin: str) -> str:
    path = repo_path
    needle = f"/repo/{ws_id}"
    if needle in path:
        path = path.replace(needle, "/bizxpress")
    return origin + encode_path(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--raw-keys", default="")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    entries = load_search_keys(TAG)
    if args.raw_keys:
        entries = [{"search_key": k.strip()} for k in args.raw_keys.split(",") if k.strip()]
    elif args.keys:
        wanted = [k.strip() for k in args.keys.split(",")]
        entries = [e for e in entries if any(w in e["search_key"] for w in wanted)]
    print(f"검색키 {len(entries)}개")

    conn = open_db()
    n_dl = n_fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context(user_agent=UA, locale="ko-KR")
        page = ctx.new_page()
        page.set_default_timeout(40000)

        for ent in entries:
            key = ent["search_key"]
            if args.limit and n_dl >= args.limit:
                break
            print(f"\n[검색] {key}")
            try:
                page.goto(LIST_URL, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("#meta05", timeout=25000)
            except Exception as e:
                print(f"  ! 목록 진입 실패: {str(e)[:60]}")
                continue
            page.wait_for_timeout(1500)
            page.fill("#meta05", key)
            page.locator("#btnSearch").click()
            page.wait_for_timeout(4000)

            rows = page.locator("#GoodsList > tr")
            n_rows = rows.count()
            key_n = key.replace(" ", "")
            matched = []
            for i in range(min(n_rows, 80)):
                t = (rows.nth(i).inner_text() or "").replace("\n", " ")
                if key_n in t.replace(" ", ""):
                    matched.append(i)
            print(f"  결과행 {n_rows} / 매칭 {len(matched)}")

            origin = page.evaluate("() => location.origin")
            for i in matched:
                if args.limit and n_dl >= args.limit:
                    break
                row = rows.nth(i)
                cells = row.locator("td")
                try:
                    raw = (row.inner_text(timeout=8000) or "")
                    lines = [l.strip() for l in raw.split("\n") if l.strip()]
                    # 상품명 = 검색키가 포함된 첫 줄(첫 줄은 채널>분류 카테고리일 수 있음)
                    prod_nm = next((l for l in lines if key_n in l.replace(" ", "")), lines[0] if lines else "")
                    for tag in ("상세내용", "펼치기"):
                        prod_nm = prod_nm.split(tag)[0].strip()
                    period = next((l.strip() for l in lines if "~" in l and any(c.isdigit() for c in l)), "")
                    period = period.split("\t")[0].strip()
                except Exception as e:
                    print(f"  ! 행 접근 실패 idx={i}: {str(e)[:60]}")
                    continue
                btn = row.locator('button[id$="_3"]')
                if btn.count() == 0:
                    print(f"  ! 약관 버튼 없음: {prod_nm[:40]}")
                    continue
                ws = btn.first.get_attribute("data-ws-id") or ""
                path = btn.first.get_attribute("data-url") or ""
                if not path:
                    print(f"  ! data-url 없음: {prod_nm[:40]}")
                    continue
                url = resolve_url(ws, path, origin)
                fname = safe_name(path.split("/")[-1]) or "terms.pdf"
                if not fname.lower().endswith(".pdf"):
                    fname += ".pdf"
                dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                if dest.exists():
                    continue
                try:
                    resp = page.request.get(url, timeout=120000)
                    blob = resp.body() if resp.ok else b""
                    if save_document(conn, MEMBER_CD, nfc(prod_nm), "TERMS", period,
                                     url, blob, dest, src_category=key):
                        n_dl += 1
                        print(f"  ✓ [{n_dl}] {prod_nm} | {period} | {fname[:50]} ({len(blob):,}B)")
                    else:
                        n_fail += 1
                        print(f"  ! PDF 검증 실패: {prod_nm} ({len(blob)}B, HTTP {resp.status})")
                except Exception as e:
                    n_fail += 1
                    print(f"  ! 실패 {prod_nm}: {str(e)[:80]}")
                time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
