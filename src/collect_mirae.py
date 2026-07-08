#!/usr/bin/env python3
"""미래에셋생명 상품공시실 약관 PDF 수집기 (Playwright).

공시실 페이지(PC-HO-080301-000000.do)는 WAF 봇차단 스크립트가 있어 실브라우저 렌더링 필요.
분류 필터는 커스텀 드롭다운(#select01_list)이 숨겨져 있어 UI 클릭 대신
#select01 값 설정 + selectList(pageNum) 직접 호출로 재조회한다.

페이지네이션 주의: 데이터 없는 페이지 호출 시 테이블 전체가 비워짐
→ 페이지별로 행을 수집·누적한 뒤 다음 페이지를 호출하고, 새 행이 없으면 중단.

한 상품이 판매기간별로 여러 tr(버전 행)을 가짐 → version_label로 보존.

사용법:
    .venv/bin/python src/collect_mirae.py --limit 3                      # e2e 검증
    .venv/bin/python src/collect_mirae.py --categories "보장성▷종신/정기,보장성▷건강/암,보장성▷간편고지/간편심사"
    .venv/bin/python src/collect_mirae.py --categories 전체 --doc-types TERMS,METHODS
"""
import argparse
import base64
import datetime
import hashlib
import pathlib
import re
import sqlite3
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "terms.db"
RAW_DIR = ROOT / "data" / "raw" / "L34"
MEMBER_CD = "L34"
URL = "https://life.miraeasset.com/micro/disclosure/product/PC-HO-080301-000000.do"
SLEEP_S = 1.2

DEFAULT_CATEGORIES = "보장성▷종신/정기,보장성▷건강/암,보장성▷간편고지/간편심사"

COLLECT_ROWS_JS = """
() => {
  const rows = [];
  document.querySelectorAll('#tbl_contents tr').forEach(tr => {
    const th = tr.querySelector('th');
    if (!th) return;
    const tds = tr.querySelectorAll('td');
    const period = tds.length > 1 ? tds[1].innerText.trim() : '';
    // 셀 순서(판매중): 판매상태 | 판매기간 | 상품요약서 | 약관 | 사업방법서
    const docCells = [['SUMMARY', 2], ['TERMS', 3], ['METHODS', 4]];
    const files = [];
    for (const [dtype, idx] of docCells) {
      if (tds.length <= idx) continue;
      tds[idx].querySelectorAll('a[data-fileNm], a[data-filenm]').forEach(a => {
        files.push({
          doc_type: dtype,
          fileNm: a.getAttribute('data-fileNm') || a.getAttribute('data-filenm'),
          fpath: a.getAttribute('data-fpath'),
        });
      });
    }
    rows.push({ prod_nm: th.innerText.trim(), period, files });
  });
  return rows;
}
"""

DOWNLOAD_JS = """
async ({fileNm, fpath}) => {
  const body = new URLSearchParams();
  body.set('pathType', 'gongci_u1');
  body.set('fileName', fileNm);
  body.set('orgFileName', fileNm);
  body.set('filePath', '/uploadwas/life/' + fpath);
  const resp = await fetch('/micro/cmmnFileDown.do', {method: 'POST', body});
  if (!resp.ok) return {ok: false, status: resp.status};
  const buf = await resp.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return {ok: true, status: resp.status, size: bytes.length,
          contentType: resp.headers.get('content-type'), b64: btoa(bin)};
}
"""


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")[:120]


def ensure_schema(conn):
    conn.executescript((ROOT / "src" / "schema.sql").read_text())
    cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    if "src_category" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN src_category TEXT")


def query_category(page, category: str):
    """분류를 지정해 재조회하고, 페이지네이션을 누적 수집해 행 목록을 돌려준다."""
    sel_val = "" if category == "전체" else category
    page.evaluate(
        """(selVal) => { $("#tbl_contents").empty(); $('#select01').val(selVal); selectList(1, 'first'); }""",
        sel_val,
    )
    page.wait_for_timeout(2500)

    all_rows = {}
    for pg in range(1, 40):  # 안전 상한
        rows = page.evaluate(COLLECT_ROWS_JS)
        new = 0
        for r in rows:
            key = (r["prod_nm"], r["period"], tuple(f["fileNm"] for f in r["files"]))
            if key not in all_rows:
                all_rows[key] = r
                new += 1
        print(f"  [{category}] page {pg}: tr={len(rows)} 누적상품행={len(all_rows)} (신규 {new})")
        if not rows or new == 0:
            break
        page.evaluate(f"selectList({pg + 1}, 'first')")
        page.wait_for_timeout(2500)
    return list(all_rows.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="다운로드 상한(0=무제한)")
    ap.add_argument("--categories", default=DEFAULT_CATEGORIES,
                    help="쉼표구분 분류값(#select01 옵션값 또는 '전체')")
    ap.add_argument("--doc-types", default="TERMS", help="쉼표구분: TERMS,METHODS,SUMMARY")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="행 수집만, 다운로드 안 함")
    ap.add_argument("--targets-json", default="", help="수집 대상 상품명(JSON 배열) — 지정 시 해당 상품만 다운로드")
    args = ap.parse_args()
    want_types = set(args.doc_types.split(","))
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    targets = None
    if args.targets_json:
        import json as _json
        import unicodedata as _ud
        targets = {_ud.normalize("NFC", t) for t in _json.load(open(args.targets_json))}
        print(f"대상 필터: {len(targets)}종")

    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    n_dl = n_skip = n_fail = 0
    seen_files = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ko-KR",
        )
        page = ctx.new_page()
        print(f"페이지 로드: {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("#tbl_contents tr", timeout=30000)

        for cat in categories:
            rows = query_category(page, cat)
            if targets is not None:
                import unicodedata as _ud
                rows = [r for r in rows if _ud.normalize("NFC", r["prod_nm"]) in targets]
                print(f"[{cat}] 대상 필터 적용 후 {len(rows)}행")
            print(f"[{cat}] 상품행 {len(rows)}건 (상품 {len(set(r['prod_nm'] for r in rows))}종)")
            if args.dry_run:
                continue

            for r in rows:
                for f in r["files"]:
                    if f["doc_type"] not in want_types or not f["fileNm"]:
                        continue
                    fkey = (f["fileNm"], f["fpath"])
                    if fkey in seen_files:
                        continue
                    seen_files.add(fkey)
                    if args.limit and n_dl >= args.limit:
                        break
                    dest_dir = RAW_DIR / safe_name(r["prod_nm"]) / f["doc_type"]
                    dest = dest_dir / f["fileNm"]
                    if dest.exists():
                        n_skip += 1
                        continue
                    res = page.evaluate(DOWNLOAD_JS, {"fileNm": f["fileNm"], "fpath": f["fpath"]})
                    if not res.get("ok") or res.get("size", 0) < 1000:
                        print(f"  ! 실패 {r['prod_nm']} / {f['fileNm']}: {res.get('status')} {res.get('size')}B")
                        n_fail += 1
                        continue
                    blob = base64.b64decode(res["b64"])
                    if not blob.startswith(b"%PDF"):
                        print(f"  ! PDF 아님 {f['fileNm']} ({res.get('contentType')})")
                        n_fail += 1
                        continue
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(blob)
                    sha = hashlib.sha256(blob).hexdigest()
                    conn.execute(
                        """INSERT OR IGNORE INTO documents(member_cd, prod_nm_raw, doc_type, version_label,
                               source_url, file_path, sha256, file_size, fetched_at, src_category)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (MEMBER_CD, r["prod_nm"], f["doc_type"], r["period"],
                         URL + "#" + f["fileNm"], str(dest.relative_to(ROOT)), sha, len(blob), now, cat),
                    )
                    conn.commit()
                    n_dl += 1
                    print(f"  ✓ [{n_dl}] {r['prod_nm']} | {r['period']} | {f['fileNm']} ({len(blob):,}B)")
                    time.sleep(SLEEP_S)

        browser.close()

    print(f"\n완료: 다운로드 {n_dl}건, 기존보유 스킵 {n_skip}건, 실패 {n_fail}건")
    conn.close()


if __name__ == "__main__":
    main()
