#!/usr/bin/env python3
"""메트라이프생명(L72) 주보험 판매상품목록 약관 수집기.

특징: 목록 페이지 1장에 전 상품(708행)+이전 판매기간 행이 모두 렌더되고
약관 PDF가 직링크(a[href*='mcvrgProdDownloadFile'])로 노출 → 페이지 1회 로드 후
앵커 수집·필터·request.get 다운로드. 가장 단순한 구조.

사용법:
    .venv/bin/python src/collect_metlife.py --limit 3
    .venv/bin/python src/collect_metlife.py            # 검색키 필터 전체
    .venv/bin/python src/collect_metlife.py --all      # 카탈로그 무관 전 상품
"""
import argparse
import re
import time
import unicodedata

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L72"
TAG = "metlife"
LIST_URL = "https://brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdMain.do"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2

COLLECT_JS = """
() => {
  // fnum=01 사업방법서 / 02 상품요약서 / 03 약관. title 속성 = 상품명
  const out = [];
  document.querySelectorAll("a[href*='DownloadFile'][href*='fnum=03']").forEach(a => {
    const tr = a.closest('tr');
    const txt = tr ? (tr.textContent || '') : '';
    const dm = txt.match(/\\d{4}[.\\-/]\\d{2}[.\\-/]\\d{2}\\s*~\\s*(\\d{4}[.\\-/]\\d{2}[.\\-/]\\d{2})?/);
    out.push({
      prod: (a.getAttribute('title') || '').trim() || (a.textContent || '').trim().split('_')[0],
      period: dm ? dm[0].replace(/\\s+/g, '') : '',
      label: (a.textContent || '').trim(),
      href: a.getAttribute('href'),
    });
  });
  return out;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--raw-keys", default="")
    ap.add_argument("--all", action="store_true", help="카탈로그 무관 전 상품 수집")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    entries = load_search_keys(TAG)
    if args.raw_keys:
        entries = [{"search_key": k.strip()} for k in args.raw_keys.split(",") if k.strip()]
    elif args.keys:
        wanted = [k.strip() for k in args.keys.split(",")]
        entries = [e for e in entries if any(w in e["search_key"] for w in wanted)]
    keys_norm = [nfc(e["search_key"]).replace(" ", "") for e in entries]
    print(f"검색키 {len(keys_norm)}개" + (" (전 상품 모드)" if args.all else ""))

    conn = open_db()
    n_dl = n_fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context(user_agent=UA, locale="ko-KR")
        page = ctx.new_page()
        print(f"페이지 로드: {LIST_URL}")
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        items = page.evaluate(COLLECT_JS)
        print(f"약관 앵커 {len(items)}건 수집")

        for it in items:
            if args.limit and n_dl >= args.limit:
                break
            prod = nfc(it["prod"]).strip()
            pn = prod.replace(" ", "")
            if not args.all and not any(k in pn for k in keys_norm):
                continue
            href = it["href"]
            url = href if href.startswith("http") else "https://brand.metlife.co.kr" + href
            fname = safe_name(it["label"]) or "terms.pdf"
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            dest = RAW_DIR / safe_name(prod) / "TERMS" / fname
            if dest.exists():
                continue
            try:
                resp = page.request.get(url, timeout=120000)
                blob = resp.body() if resp.ok else b""
                if save_document(conn, MEMBER_CD, prod, "TERMS", it["period"],
                                 url, blob, dest, src_category="metlife-direct"):
                    n_dl += 1
                    print(f"  ✓ [{n_dl}] {prod} | {it['period']} | {fname} ({len(blob):,}B)")
                else:
                    n_fail += 1
                    print(f"  ! PDF 검증 실패: {prod} {it['label']} ({len(blob)}B)")
            except Exception as e:
                n_fail += 1
                print(f"  ! 실패 {prod}: {str(e)[:80]}")
            time.sleep(SLEEP_S)
        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
