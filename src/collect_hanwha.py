#!/usr/bin/env python3
"""한화생명(L01) 상품공시실 약관 수집기.

플로우: 판매중 상품목록(P10000) → 검색키 입력 → 상품 링크 클릭 →
#LIST_GRID3 판매기간별 행 → 약관 버튼(button.ck-fileDownload[data-file*='약관'])
→ expect_download 저장.

사용법:
    .venv/bin/python src/collect_hanwha.py --limit 2          # e2e
    .venv/bin/python src/collect_hanwha.py                    # 전체 검색키
    .venv/bin/python src/collect_hanwha.py --keys "상속H종신보험"
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L01"
TAG = "hanwha"
LIST_URL = ("https://www.hanwhalife.com/main/disclosure/goods/disclosurenotice/"
            "DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000")
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="다운로드 상한(0=무제한)")
    ap.add_argument("--keys", default="", help="쉼표구분 검색키(기본: catalog/searchkeys_hanwha.json 전체)")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--max-versions", type=int, default=0, help="상품당 판매기간 행 상한(0=전체)")
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
            ok = False
            for attempt in range(3):
                try:
                    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_selector("#schText", timeout=25000)
                    ok = True
                    break
                except Exception as e:
                    print(f"  (목록 진입 재시도 {attempt+1}: {str(e)[:60]})")
                    page.wait_for_timeout(5000)
            if not ok:
                print(f"  ! 목록 진입 실패 — 키 건너뜀: {key}")
                continue
            page.wait_for_timeout(1200)
            page.fill("#schText", key)
            page.get_by_text("검색하기", exact=False).first.click()
            page.wait_for_timeout(2000)

            # 검색결과 상품 링크는 a.ck-search2 (클릭 시 페이지 이동 없이 GRID3 갱신)
            links = page.locator("a.ck-search2")
            n_links = links.count()
            if n_links == 0:
                print(f"  ! 검색 결과 없음: {key}")
                continue
            texts = []
            for i in range(min(n_links, 20)):
                t = (links.nth(i).inner_text() or "").strip()
                if t:
                    texts.append((i, t))
            print(f"  상품 링크 {len(texts)}개: {[t for _, t in texts]}")

            for idx, ptext in texts:
                if args.limit and n_dl >= args.limit:
                    break
                page.locator("a.ck-search2").nth(idx).click()
                page.wait_for_timeout(1800)

                rows = page.locator("#LIST_GRID3 tbody tr")
                n_rows = rows.count()
                if n_rows == 0:
                    print(f"  ! 판매기간 그리드 없음: {ptext}")
                    continue
                n_take = n_rows if not args.max_versions else min(n_rows, args.max_versions)
                for ri in range(n_take):
                    if args.limit and n_dl >= args.limit:
                        break
                    row = rows.nth(ri)
                    period = (row.locator("td").first.inner_text() or "").strip()
                    btn = row.locator("button.ck-fileDownload[data-file*='약관']")
                    if btn.count() == 0:
                        continue
                    # data-file은 파일 경로가 아니므로 판매기간 기반 결정적 파일명 사용
                    fname = f"{safe_name(ptext)}_약관_{safe_name(period)}.pdf"
                    dest = RAW_DIR / safe_name(ptext) / "TERMS" / fname
                    if dest.exists():
                        continue
                    try:
                        with page.expect_download(timeout=60000) as dl:
                            btn.first.click()
                        d = dl.value
                        tmp = dest.parent / ("_tmp_dl.pdf")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        d.save_as(tmp)
                        blob = tmp.read_bytes()
                        tmp.unlink()
                        final = dest
                        if save_document(conn, MEMBER_CD, nfc(ptext), "TERMS", period,
                                         page.url, blob, final, src_category=key):
                            n_dl += 1
                            print(f"  ✓ [{n_dl}] {ptext} | {period} | {final.name} ({len(blob):,}B)")
                        else:
                            n_fail += 1
                            print(f"  ! PDF 검증 실패: {ptext} {period}")
                    except Exception as e:
                        n_fail += 1
                        print(f"  ! 다운로드 실패 {ptext} {period}: {str(e)[:80]}")
                    time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
