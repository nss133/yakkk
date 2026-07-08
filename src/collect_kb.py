#!/usr/bin/env python3
"""KB라이프생명(L61) 상품목록 약관 수집기.

구조(productList.do): tr = 구분 + 아코디언(상품 head행 + 과거 판매기간 panel행),
각 행에 a.downFile[data-fileno='product-terms'](약관), title=상품명, cell-2=판매기간.
다운로드 = GET /api/archive/archives/download/product-terms/{seqno}/{boxno}.
페이지네이션 숫자 링크 클릭으로 전 페이지 순회 후 키 필터.

사용법:
    .venv/bin/python src/collect_kb.py --limit 3
    .venv/bin/python src/collect_kb.py
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from common import ROOT, UA, load_search_keys, nfc, open_db, safe_name, save_document

MEMBER_CD = "L61"
TAG = "kb"
LIST_URL = "https://www.kblife.co.kr/customer-common/productList.do"
RAW_DIR = ROOT / "data" / "raw" / MEMBER_CD
SLEEP_S = 1.2

COLLECT_JS = """
() => [...document.querySelectorAll("a.downFile[data-fileno='product-terms']")].map(a => {
  const row = a.closest('.row');
  const item = a.closest('.prd-item, li');
  const head = item ? item.querySelector('.head .cell-1') : null;
  return {
    prod: (head ? head.textContent : (a.getAttribute('title')||'').replace(/ 약관 다운로드$/,''))
          .replace(/닫힘|열림/g,'').trim(),
    period: row ? (row.querySelector('.cell-2')?.textContent || '').trim() : '',
    seqno: a.getAttribute('data-seqno'),
    boxno: a.getAttribute('data-boxno'),
  };
})
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--raw-keys", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    entries = load_search_keys(TAG)
    if args.raw_keys:
        entries = [{"search_key": k.strip()} for k in args.raw_keys.split(",") if k.strip()]
    elif args.keys:
        wanted = [k.strip() for k in args.keys.split(",")]
        entries = [e for e in entries if any(w in e["search_key"] for w in wanted)]
    keys_n = [nfc(e["search_key"]).replace(" ", "") for e in entries]
    print(f"검색키 {len(keys_n)}개" + (" (전 상품 모드)" if args.all else ""))

    conn = open_db()
    n_dl = n_fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context(user_agent=UA, locale="ko-KR")
        page = ctx.new_page()
        print(f"페이지 로드: {LIST_URL}")
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 전 페이지 순회하며 앵커 수집 (seqno 중복 = 순회 종료)
        items = {}
        for pg_no in range(1, 60):
            batch = page.evaluate(COLLECT_JS)
            new = 0
            for it in batch:
                k = (it["seqno"], it["boxno"])
                if k not in items and it["seqno"]:
                    items[k] = it
                    new += 1
            print(f"  page {pg_no}: 앵커 {len(batch)} (신규 {new}, 누적 {len(items)})")
            moved = page.evaluate(
                """(target) => {
                    const links = [...document.querySelectorAll('[class*=pag] a, [class*=pag] button')];
                    const el = links.find(l => l.textContent.trim() === String(target));
                    if (el) { el.click(); return true; }
                    const nxt = links.find(l => /다음|next|›|>/i.test(l.textContent.trim()) || /next/i.test(l.className));
                    if (nxt) { nxt.click(); return true; }
                    return false;
                }""", pg_no + 1)
            if not moved or new == 0:
                if not moved:
                    break
            page.wait_for_timeout(3000)
        print(f"약관 앵커 총 {len(items)}건")

        for (seqno, boxno), it in items.items():
            if args.limit and n_dl >= args.limit:
                break
            prod = nfc(it["prod"]).strip()
            pn = prod.replace(" ", "")
            if not args.all and not any(k and (k in pn or pn in k) for k in keys_n):
                continue
            url = f"https://www.kblife.co.kr/api/archive/archives/download/product-terms/{seqno}/{boxno}"
            fname = f"{safe_name(prod)}_약관_{safe_name(it['period']) or seqno}.pdf"
            dest = RAW_DIR / safe_name(prod) / "TERMS" / fname
            if dest.exists():
                continue
            try:
                resp = page.request.get(url, timeout=120000)
                blob = resp.body() if resp.ok else b""
                if save_document(conn, MEMBER_CD, prod, "TERMS", it["period"],
                                 url, blob, dest, src_category="kb-list"):
                    n_dl += 1
                    print(f"  ✓ [{n_dl}] {prod} | {it['period']} ({len(blob):,}B)")
                else:
                    n_fail += 1
                    print(f"  ! PDF 검증 실패: {prod} ({len(blob)}B)")
            except Exception as e:
                n_fail += 1
                print(f"  ! 실패 {prod}: {str(e)[:80]}")
            time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
