#!/usr/bin/env python3
"""동양생명(L74) 판매상품 공시 약관 수집기.

플로우(pbano.myangel.co.kr — www 도메인은 404): #productSearchLbl 검색+Enter →
결과 테이블 행 매칭 → 행 내 링크(0=요약서, 1=사업방법서, 2=보험약관) expect_download.
행이 판매기간별로 나뉘어 있으면 각 행을 버전으로 수집.

사용법:
    .venv/bin/python src/collect_dongyang.py --limit 2 --keys "수호천사"
    .venv/bin/python src/collect_dongyang.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L74"
TAG = "dongyang"
LIST_URL = "https://pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2


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
        ctx = browser.new_context(user_agent=UA, locale="ko-KR", accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(40000)

        for ent in entries:
            key = ent["search_key"]
            if args.limit and n_dl >= args.limit:
                break
            print(f"\n[검색] {key}")
            try:
                page.goto(LIST_URL, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("#productSearchLbl", timeout=25000)
            except Exception as e:
                print(f"  ! 목록 진입 실패: {str(e)[:60]}")
                continue
            page.wait_for_timeout(2500)
            page.fill("#productSearchLbl", key)
            page.locator("#productSearchLbl").press("Enter")
            page.wait_for_timeout(3500)

            rows = page.locator("table tbody tr")
            n_rows = rows.count()
            key_n = key.replace(" ", "")
            matched = []
            for i in range(min(n_rows, 80)):
                t = (rows.nth(i).inner_text() or "").replace("\n", " ")
                if key_n in t.replace(" ", ""):
                    matched.append(i)
            print(f"  결과행 {n_rows} / 매칭 {len(matched)}")

            for i in matched:
                if args.limit and n_dl >= args.limit:
                    break
                row = page.locator("table tbody tr").nth(i)
                try:
                    raw = (row.inner_text(timeout=8000) or "")
                    lines = [l.strip() for l in raw.split("\n") if l.strip()]
                    prod_nm = next((l for l in lines if key_n in l.replace(" ", "")),
                                   lines[0] if lines else "")
                    # 판매기간은 시작/종료 별도 컬럼(td 4,5)
                    tds = row.locator("td")
                    p_start = (tds.nth(4).inner_text() or "").strip() if tds.count() > 5 else ""
                    p_end = (tds.nth(5).inner_text() or "").strip() if tds.count() > 5 else ""
                    period = f"{p_start}~{p_end}".strip("~")
                except Exception as e:
                    print(f"  ! 행 접근 실패 idx={i}: {str(e)[:60]}")
                    continue
                links = row.locator("a")
                if links.count() < 3:
                    print(f"  ! 링크 부족({links.count()}): {prod_nm[:40]}")
                    continue
                fname = f"{safe_name(prod_nm)}_약관_{safe_name(period) or i}.pdf"
                dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                if dest.exists():
                    continue
                try:
                    with page.expect_download(timeout=60000) as dl:
                        links.nth(2).click()
                    d = dl.value
                    tmp = dest.parent / "_tmp_dl.pdf"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    d.save_as(tmp)
                    blob = tmp.read_bytes()
                    tmp.unlink()
                    if save_document(conn, MEMBER_CD, nfc(prod_nm), "TERMS", period,
                                     page.url, blob, dest, src_category=key):
                        n_dl += 1
                        print(f"  ✓ [{n_dl}] {prod_nm} | {period} ({len(blob):,}B)")
                    else:
                        n_fail += 1
                        print(f"  ! PDF 검증 실패: {prod_nm}")
                except Exception as e:
                    n_fail += 1
                    print(f"  ! 실패 {prod_nm}: {str(e)[:80]}")
                time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
