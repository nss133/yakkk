#!/usr/bin/env python3
"""흥국생명(L04) 판매상품 공시 약관 수집기.

플로우(saleProduct.do?searchFlgSale=Y): #searchText 입력 → doSearch ajax 자동완성
(saleProductAjax.do 응답 파싱) → 상품명 확정 → hidden(#searchCdPublicPrtType3) 설정
→ doSearch 재조회 → #productVoTr 기간별 행 → td2=약관 링크 expect_download.
⚠️ nppfs-loading-modal이 클릭을 가로챌 수 있어 제거 후 진행 (yakk 검증 방식).

사용법:
    .venv/bin/python src/collect_heungkuk.py --limit 2 --keys "다사랑"
    .venv/bin/python src/collect_heungkuk.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L04"
TAG = "heungkuk"
LIST_URL = "https://www.heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2


def parse_suggestions(body: str):
    names = []
    for part in (body or "").split("|"):
        if not part.startswith("%"):
            continue
        s = part.strip("%")
        s = s.replace("%,%%", "").replace("%,%", "").replace("%,", "").replace("%%", "").strip()
        if s and s != "null":
            names.append(s)
    return names


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

        ajax = {"body": None}
        page.on("response", lambda r: ajax.__setitem__("body", r.text())
                if r.url.endswith("/front/public/saleProductAjax.do") else None)

        # 빈 검색 1회로 판매중 전체 자동완성 목록 확보 → 카탈로그 키로 필터
        try:
            page.goto(LIST_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("#searchText", timeout=25000)
        except Exception as e:
            print(f"! 목록 진입 실패: {str(e)[:60]}")
            browser.close(); conn.close(); return
        page.wait_for_timeout(3000)
        ajax["body"] = None
        page.fill("#searchText", "")
        page.evaluate("() => doSearch('Y','','','','')")
        page.wait_for_timeout(5000)
        all_products = set(parse_suggestions(ajax["body"] or ""))
        print(f"판매중 전체(빈 검색) {len(all_products)}종")
        # 빈 검색 목록이 잘릴 수 있어 키 앞 4자로 자동완성 추가 조회·병합
        probes = {nfc(e["search_key"]).replace(" ", "")[:4] for e in entries}
        for pb in sorted(probes):
            if not pb:
                continue
            ajax["body"] = None
            page.fill("#searchText", pb)
            page.evaluate("() => doSearch('Y','','','','')")
            page.wait_for_timeout(2500)
            got = parse_suggestions(ajax["body"] or "")
            new_items = [g for g in got if g not in all_products]
            all_products.update(got)
            if new_items:
                print(f"  +probe {pb!r}: 신규 {len(new_items)}종")
        all_products = sorted(all_products)
        print(f"자동완성 병합 {len(all_products)}종")

        import re as _re
        def _norm(s):
            return _re.sub(r"[\s()\[\]〔〕·,無무배당]|흥국생명", "", nfc(s))
        keys_n = [_norm(e["search_key"]) for e in entries]
        picked_all = [pnm for pnm in all_products
                      if any(k and (k in _norm(pnm) or _norm(pnm) in k) for k in keys_n)]
        print(f"카탈로그 매칭 {len(picked_all)}종")

        for prod_nm in picked_all:
            if args.limit and n_dl >= args.limit:
                break
            page.evaluate("(v) => { document.querySelector('#searchCdPublicPrtType3').value = v; }", prod_nm)
            page.evaluate("(v) => doSearch('Y','','','', v)", prod_nm)
            page.wait_for_timeout(5000)
            page.evaluate("() => { const el = document.querySelector('#nppfs-loading-modal'); if (el) el.remove(); }")

            rows = page.locator("#productVoTr tr")
            n_rows = rows.count()
            if n_rows == 0:
                print(f"  ! 기간별 행 없음: {prod_nm}")
                continue
            for ri in range(n_rows):
                if args.limit and n_dl >= args.limit:
                    break
                row = rows.nth(ri)
                tds = row.locator("td")
                if tds.count() < 4:
                    continue
                period = (tds.nth(0).inner_text() or "").strip().replace("\n", " ")
                link = tds.nth(2).locator("a")
                if link.count() == 0:
                    continue
                fname = f"{safe_name(prod_nm)}_약관_{safe_name(period) or ri}.pdf"
                dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                if dest.exists():
                    continue
                try:
                    page.evaluate("() => { const el = document.querySelector('#nppfs-loading-modal'); if (el) el.remove(); }")
                    with page.expect_download(timeout=60000) as dl:
                        link.first.click()
                    d = dl.value
                    tmp = dest.parent / "_tmp_dl.pdf"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    d.save_as(tmp)
                    blob = tmp.read_bytes()
                    tmp.unlink()
                    if save_document(conn, MEMBER_CD, nfc(prod_nm), "TERMS", period,
                                     page.url, blob, dest, src_category="autocomplete-all"):
                        n_dl += 1
                        print(f"  ✓ [{n_dl}] {prod_nm} | {period} ({len(blob):,}B)")
                    else:
                        n_fail += 1
                        print(f"  ! PDF 검증 실패: {prod_nm} {period}")
                except Exception as e:
                    n_fail += 1
                    print(f"  ! 실패 {prod_nm} {period}: {str(e)[:80]}")
                time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
