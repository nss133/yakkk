#!/usr/bin/env python3
"""삼성생명(L03) 상품공시 약관 수집기.

플로우: 판매상품 목록(PDO-PRPRI010110M) → #keywordSearch 검색 → 결과 행에서
약관 컬럼 링크 클릭 → 팝업(iframe 문서뷰어, XView.do)에서 PDF 응답을 네트워크 캡처.
※ content-type이 pdf가 아닐 수 있어 magic bytes(%PDF)로 판정 (yakk 검증 방식).

표 컬럼: 0번호 1분류 2상품명 3판매기간 4요약서 5방법서 6약관

사용법:
    .venv/bin/python src/collect_samsung.py --limit 2 --keys "가족대표건강보험"
    .venv/bin/python src/collect_samsung.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L03"
TAG = "samsung"
LIST_URL = "https://www.samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.5


def capture_pdf_from_popup(popup, timeout_ms=90000):
    """뷰어가 Range 스트리밍하므로 %PDF 응답의 URL을 잡아 전체 재요청한다."""
    hits = []  # (url, body)

    def on_response(resp):
        if hits:
            return
        try:
            url = resp.url or ""
            ct = (resp.headers or {}).get("content-type", "")
            hint = ("XView.do" in url) or ("docID=" in url) or ("contenttype" in url.lower())
            if ("pdf" not in ct.lower()) and not hint:
                return
            b = resp.body()
            if len(b) > 1024 and b[:4] == b"%PDF":
                hits.append((url, b))
        except Exception:
            pass

    popup.on("response", on_response)
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        if hits:
            break
        popup.wait_for_timeout(250)
    if not hits:
        return None
    url, first_body = hits[0]
    if b"%%EOF" in first_body[-2048:]:
        return first_body  # 이미 전체
    try:
        full = popup.context.request.get(url, timeout=120000).body()
        if full[:4] == b"%PDF" and b"%%EOF" in full[-2048:]:
            return full
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--headful", action="store_true")
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
        ctx = browser.new_context(user_agent=UA, locale="ko-KR", accept_downloads=False)
        page = ctx.new_page()
        page.set_default_timeout(60000)

        for ent in entries:
            key = ent["search_key"]
            if args.limit and n_dl >= args.limit:
                break
            print(f"\n[검색] {key}")
            page.goto(LIST_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#keywordSearch", timeout=30000)
            page.wait_for_selector("table tbody tr", timeout=30000)
            page.wait_for_timeout(3000)

            # SPA 하이드레이션 전 Enter가 무시될 수 있어 검색 적용 확인 + 재시도
            matched = []
            n_rows = 0
            for attempt in range(3):
                page.fill("#keywordSearch", key)
                page.locator("#keywordSearch").press("Enter")
                page.wait_for_timeout(4000)
                rows = page.locator("table tbody tr")
                n_rows = rows.count()
                matched = []
                for i in range(min(n_rows, 120)):
                    t = (rows.nth(i).inner_text() or "").replace("\n", " ")
                    if key.replace(" ", "") in t.replace(" ", ""):
                        matched.append(i)
                if matched:
                    break
                print(f"  (재시도 {attempt+1}: 결과행 {n_rows}, 매칭 0)")
            print(f"  결과행 {n_rows} / 매칭 {len(matched)}")

            for i in matched:
                if args.limit and n_dl >= args.limit:
                    break
                try:
                    row = page.locator("table tbody tr").nth(i)
                    tds = row.locator("td")
                    if tds.count() < 7:
                        print(f"  ! 행 구조 변경(스킵): idx={i}")
                        continue
                    prod_nm = (tds.nth(2).inner_text(timeout=8000) or "").strip()
                    period = (tds.nth(3).inner_text(timeout=8000) or "").strip()
                except Exception as e:
                    print(f"  ! 행 접근 실패(스킵) idx={i}: {str(e)[:60]}")
                    continue
                terms_link = tds.nth(6).locator("a")
                if terms_link.count() == 0:
                    print(f"  ! 약관 링크 없음: {prod_nm}")
                    continue
                fname = f"{safe_name(prod_nm)}_약관_{safe_name(period)}.pdf"
                dest = RAW_DIR / safe_name(prod_nm) / "TERMS" / fname
                if dest.exists():
                    continue
                try:
                    with ctx.expect_page(timeout=30000) as np:
                        terms_link.first.click()
                    popup = np.value
                    popup.wait_for_load_state("domcontentloaded")
                    blob = capture_pdf_from_popup(popup)
                    popup.close()
                    if blob and save_document(conn, MEMBER_CD, nfc(prod_nm), "TERMS", period,
                                              LIST_URL, blob, dest, src_category=key):
                        n_dl += 1
                        print(f"  ✓ [{n_dl}] {prod_nm} | {period} ({len(blob):,}B)")
                    else:
                        n_fail += 1
                        print(f"  ! PDF 캡처 실패: {prod_nm} | {period}")
                except Exception as e:
                    n_fail += 1
                    print(f"  ! 실패 {prod_nm}: {str(e)[:80]}")
                time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
