#!/usr/bin/env python3
"""교보생명(L05) 전체상품조회 약관 수집기.

플로우: 전체상품조회 → #input-01 검색 → 결과 행의 '확인' 버튼 → 기간별 다운로드 모달
(판매기간|약관|사업방법서) → 약관 링크 expect_download → 모달 닫기 → 다음.

사용법:
    .venv/bin/python src/collect_kyobo.py --limit 3 --keys "상속든든종신보험"
    .venv/bin/python src/collect_kyobo.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L05"
TAG = "kyobo"
LIST_URL = "https://www.kyobo.com/dgt/web/product-official/all-product/search"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2


def close_modal(page):
    for sel in ("#pop-period-down button.btn-pop-close",):
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(600)
                return
            except Exception:
                pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    try:
        page.wait_for_selector("#pop-period-down.on", state="hidden", timeout=3000)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--max-versions", type=int, default=0)
    ap.add_argument("--raw-keys", default="", help="카탈로그 무관 임의 검색키(쉼표구분) — 보완 수집용")
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
        page.set_default_timeout(30000)

        for ent in entries:
            key = ent["search_key"]
            if args.limit and n_dl >= args.limit:
                break
            print(f"\n[검색] {key}")
            page.goto(LIST_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#input-01", timeout=20000)
            page.wait_for_timeout(1500)
            page.fill("#input-01", key)
            page.locator("#searchBtn").click()
            page.wait_for_timeout(2500)

            rows = page.locator("table tbody tr")
            n_rows = rows.count()
            # 상품명에 검색키가 들어간 행만
            matched = []
            for i in range(min(n_rows, 120)):
                t = (rows.nth(i).inner_text() or "").replace("\n", " ")
                if key.replace(" ", "") in t.replace(" ", ""):
                    matched.append((i, t.strip()[:80]))
            print(f"  결과행 {n_rows} / 매칭 {len(matched)}")
            if not matched:
                continue

            for i, rowtext in matched:
                if args.limit and n_dl >= args.limit:
                    break
                row = page.locator("table tbody tr").nth(i)
                prod_nm = (row.locator("td").nth(1).inner_text() or rowtext).strip()
                btn = row.locator("button:has-text('확인')")
                if btn.count() == 0:
                    print(f"  ! 확인 버튼 없음: {rowtext[:50]}")
                    continue
                btn.first.click()
                page.wait_for_timeout(1500)

                page.wait_for_selector("#pop-period-down.on", timeout=10000)
                try:
                    page.wait_for_selector("#pop-period-down tbody tr", timeout=8000)
                except Exception:
                    pass
                tbl = page.locator("#pop-period-down table:has(th:has-text('판매기간'))").first
                if tbl.count() == 0:
                    print(f"  ! 기간별 테이블 없음: {prod_nm}")
                    close_modal(page)
                    continue
                prows = tbl.locator("tbody tr")
                n_p = prows.count()
                n_take = n_p if not args.max_versions else min(n_p, args.max_versions)
                for ri in range(n_take):
                    if args.limit and n_dl >= args.limit:
                        break
                    prow = prows.nth(ri)
                    period = (prow.locator("td").first.inner_text() or "").strip()
                    link = prow.locator("a[href*='약관']")
                    if link.count() == 0:
                        print(f"  ! 약관 링크 없음: {prod_nm} | {period} | 셀수={prow.locator('td').count()}")
                        continue
                    fname = f"{safe_name(prod_nm)}_약관_{safe_name(period)}.pdf"
                    dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                    if dest.exists():
                        continue
                    try:
                        with page.expect_download(timeout=60000) as dl:
                            link.first.click()
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
                            print(f"  ! PDF 검증 실패: {prod_nm} {period}")
                    except Exception as e:
                        n_fail += 1
                        print(f"  ! 다운로드 실패 {prod_nm} {period}: {str(e)[:80]}")
                    time.sleep(SLEEP_S)
                close_modal(page)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
