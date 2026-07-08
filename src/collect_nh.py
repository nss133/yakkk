#!/usr/bin/env python3
"""NH농협생명(L42) 전체상품공시 약관 수집기.

플로우(HOON0004M00.nhl): #proName 검색 → 행 '확인'(goAnonm) → #prodPopup 모달
(판매기간|상품요약서|사업방법서|보험약관) → 보험약관 셀(td3) 링크 expect_download.
모달 기간별 페이지네이션은 goAnonm(상품명, pageNo) 재호출로 순회.

사용법:
    .venv/bin/python src/collect_nh.py --limit 2 --keys "유니버셜종신"
    .venv/bin/python src/collect_nh.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L42"
TAG = "nh"
LIST_URL = "https://www.nhlife.co.kr/ho/on/HOON0004M00.nhl"
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
                page.wait_for_selector("#proName", timeout=25000)
            except Exception as e:
                print(f"  ! 목록 진입 실패: {str(e)[:60]}")
                continue
            page.wait_for_timeout(2000)
            page.fill("#proName", key)
            page.get_by_text("검 색", exact=False).first.click()
            page.wait_for_timeout(3000)

            # 행에서 '확인' 버튼 value = 상품명(사이트 표기)
            prods = page.evaluate("""() => [...document.querySelectorAll('table tbody tr')]
                .map(tr => { const b = tr.querySelector("[onclick*='goAnonm']");
                             return b ? b.getAttribute('value') || b.value : null; })
                .filter(Boolean)""")
            key_n = key.replace(" ", "")
            prods = [pn for pn in prods if key_n in pn.replace(" ", "")]
            print(f"  매칭 상품 {len(prods)}종")

            for prod_nm in prods:
                if args.limit and n_dl >= args.limit:
                    break
                for pg_no in range(1, 15):  # 모달 기간별 페이지네이션
                    page.evaluate("([v, pg]) => goAnonm(v, String(pg))", [prod_nm, pg_no])
                    page.wait_for_timeout(3000)
                    rows = page.locator("#prodPopup table tbody tr")
                    n_rows = rows.count()
                    if n_rows == 0:
                        break
                    got_new = False
                    for ri in range(n_rows):
                        if args.limit and n_dl >= args.limit:
                            break
                        row = rows.nth(ri)
                        tds = row.locator("td")
                        if tds.count() < 4:
                            continue
                        period = (tds.nth(0).inner_text() or "").strip().replace("\n", " ")
                        link = tds.nth(3).locator("a, button")
                        if link.count() == 0:
                            continue
                        # onclick="popupPdfViewer('FILE_xxx','2')" → /pdfViewer.nhl 직접 GET
                        onclick = link.first.get_attribute("onclick") or ""
                        import re as _re
                        m = _re.search(r"popupPdfViewer\('([^']+)'\s*,\s*'(\d+)'\)", onclick)
                        if not m:
                            print(f"  ! onclick 파싱 실패: {onclick[:60]}")
                            continue
                        url = f"https://www.nhlife.co.kr/pdfViewer.nhl?apdFlid={m.group(1)}&fileSeqn={m.group(2)}"
                        fname = f"{safe_name(prod_nm)}_약관_{safe_name(period) or ri}.pdf"
                        dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                        if dest.exists():
                            continue
                        try:
                            resp = page.request.get(url, timeout=120000)
                            blob = resp.body() if resp.ok else b""
                            if save_document(conn, MEMBER_CD, nfc(prod_nm), "TERMS", period,
                                             url, blob, dest, src_category=key):
                                n_dl += 1
                                got_new = True
                                print(f"  ✓ [{n_dl}] {prod_nm} | {period} ({len(blob):,}B)")
                            else:
                                n_fail += 1
                                print(f"  ! PDF 검증 실패: {prod_nm} {period}")
                        except Exception as e:
                            n_fail += 1
                            print(f"  ! 실패 {prod_nm} {period}: {str(e)[:80]}")
                        time.sleep(SLEEP_S)
                    if n_rows < 3 or (not got_new and pg_no > 1):
                        break
                # 모달 닫기
                page.evaluate("() => { const el = document.querySelector('#prodPopup'); if (el) el.style.display='none'; }")

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
