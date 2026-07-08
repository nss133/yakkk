#!/usr/bin/env python3
"""폐쇄망용 약관 검색 웹앱 — Python 표준 라이브러리만 사용(단일 파일).

terms_dist*.db 하나와 이 파일만 반입하면 동작:
    python3 search_app.py --db terms_dist_current.db --port 8765

기능:
- FTS 조문 검색: 본문+제목 / 제목만 (AND·"구문"·접두어* 지원)
- 필터: 회사 / 상품군(종신·질병·암…) / 주계약·특약 / 상품명 포함어
- 조문 전문 보기, 문서(약관) 조문 목록(섹션 구분 표시)
"""
import argparse
import html
import http.server
import pathlib
import sqlite3
import urllib.parse

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>약관 DB 검색</title>
<style>
 body{font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#222}
 h1{font-size:20px} input[type=text]{padding:8px;font-size:15px}
 #q{width:380px} #pn{width:170px}
 select,button{padding:8px;font-size:14px} table{border-collapse:collapse;width:100%;margin-top:14px}
 th,td{border:1px solid #ddd;padding:6px 8px;font-size:13px;vertical-align:top}
 th{background:#f5f5f7} mark{background:#ffe38f} .meta{color:#777;font-size:12px}
 .tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;background:#eef;color:#336}
 .tag.rider{background:#fee;color:#933}
 pre{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:14px;font-size:13px;line-height:1.6}
 a{color:#0a58ca;text-decoration:none} form{line-height:2.2}
</style></head><body>
<h1>약관 DB 검색 <span class="meta">__DBNAME__ · 문서 __NDOCS__건 · 조문 __NCLS__건</span></h1>
<form method="get" action="/">
 <input type="text" id="q" name="q" value="__Q__" placeholder="검색어 (공백=AND, &quot;구문&quot;, 접두어*)">
 <select name="scope">__SCOPE__</select>
 <select name="m"><option value="">전체 회사</option>__MEMBERS__</select>
 <select name="g"><option value="">전체 상품군</option>__GROUPS__</select>
 <select name="r">__RIDER__</select>
 <input type="text" id="pn" name="pn" value="__PN__" placeholder="상품명 포함어">
 <button>검색</button>
</form>
__BODY__
</body></html>"""

SCOPE_OPTS = [("", "본문+제목"), ("title", "제목(조문명)만")]
RIDER_OPTS = [("", "주계약+특약"), ("main", "주계약만"), ("rider", "특약만")]


def opts(pairs, sel):
    return "".join(f'<option value="{v}"{" selected" if v == sel else ""}>{html.escape(t)}</option>'
                   for v, t in pairs)


class App(http.server.BaseHTTPRequestHandler):
    db_path = None

    def conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def send_page(self, body, qs=None):
        qs = qs or {}
        c = self.conn()
        nd = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        nc = c.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
        members = "".join(
            f'<option value="{r[0]}"{" selected" if r[0] == qs.get("m","") else ""}>{html.escape(r[1])}</option>'
            for r in c.execute("SELECT member_cd, name FROM insurers ORDER BY name"))
        groups = "".join(
            f'<option value="{html.escape(r[0])}"{" selected" if r[0] == qs.get("g","") else ""}>{html.escape(r[0])}</option>'
            for r in c.execute("SELECT DISTINCT prod_group FROM documents WHERE prod_group IS NOT NULL ORDER BY 1"))
        c.close()
        out = (PAGE.replace("__DBNAME__", pathlib.Path(self.db_path).name)
               .replace("__NDOCS__", f"{nd:,}").replace("__NCLS__", f"{nc:,}")
               .replace("__MEMBERS__", members).replace("__GROUPS__", groups)
               .replace("__SCOPE__", opts(SCOPE_OPTS, qs.get("scope", "")))
               .replace("__RIDER__", opts(RIDER_OPTS, qs.get("r", "")))
               .replace("__Q__", html.escape(qs.get("q", "")))
               .replace("__PN__", html.escape(qs.get("pn", "")))
               .replace("__BODY__", body))
        data = out.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        raw = urllib.parse.parse_qs(u.query)
        qs = {k: v[0] for k, v in raw.items()}
        try:
            if u.path == "/clause":
                self.view_clause(int(qs["id"]))
            elif u.path == "/doc":
                self.view_doc(int(qs["id"]))
            else:
                self.search(qs)
        except Exception as e:
            self.send_page(f"<p>오류: {html.escape(str(e))}</p>", qs)

    def search(self, qs):
        q = qs.get("q", "").strip()
        if not q:
            self.send_page("<p class='meta'>검색어를 입력하세요. 필터만으로 찾으려면 검색어에 * 를 넣으세요(예: 보험금*).</p>", qs)
            return
        match = f"title:({q})" if qs.get("scope") == "title" else q
        sql = """SELECT c.clause_id, c.clause_no, c.title, c.is_rider, c.section_title,
                        d.doc_id, d.prod_nm_raw, d.version_label, d.prod_group,
                        i.name AS insurer,
                        snippet(clauses_fts, 0, '<mark>', '</mark>', ' … ', 18) AS snip
                 FROM clauses_fts f JOIN clauses c ON c.clause_id = f.rowid
                 JOIN documents d USING(doc_id) JOIN insurers i ON i.member_cd = d.member_cd
                 WHERE clauses_fts MATCH ?"""
        params = [match]
        if qs.get("m"):
            sql += " AND d.member_cd = ?"; params.append(qs["m"])
        if qs.get("g"):
            sql += " AND d.prod_group = ?"; params.append(qs["g"])
        if qs.get("r") == "main":
            sql += " AND c.is_rider = 0"
        elif qs.get("r") == "rider":
            sql += " AND c.is_rider = 1"
        if qs.get("pn"):
            sql += " AND replace(d.prod_nm_raw,' ','') LIKE '%'||replace(?, ' ','')||'%'"
            params.append(qs["pn"])
        sql += " ORDER BY rank LIMIT 150"
        c = self.conn()
        try:
            rows = c.execute(sql, params).fetchall()
        finally:
            c.close()
        if not rows:
            self.send_page("<p>결과 없음</p>", qs)
            return
        trs = ""
        for r in rows:
            tag = ("<span class='tag rider'>특약</span>" if r["is_rider"] else "<span class='tag'>주계약</span>")
            st = f" <span class='meta'>{html.escape(r['section_title'])}</span>" if r["section_title"] else ""
            trs += (f"<tr><td>{html.escape(r['insurer'])}<div class='meta'>{html.escape(r['prod_group'] or '')}</div></td>"
                    f"<td><a href='/doc?id={r['doc_id']}'>{html.escape(r['prod_nm_raw'])}</a>"
                    f"<div class='meta'>{html.escape(r['version_label'] or '')}</div></td>"
                    f"<td>{tag}{st}<br><a href='/clause?id={r['clause_id']}'>{html.escape(r['clause_no'] or '')} "
                    f"{html.escape(r['title'] or '')}</a></td>"
                    f"<td>{r['snip']}</td></tr>")
        self.send_page(f"<p class='meta'>{len(rows)}건 (상위 150)</p>"
                       f"<table><tr><th>회사/상품군</th><th>상품(판매기간)</th><th>구분/조문</th><th>내용</th></tr>{trs}</table>", qs)

    def view_clause(self, cid):
        c = self.conn()
        r = c.execute("""SELECT c.*, d.prod_nm_raw, d.version_label, d.prod_group, i.name AS insurer
                         FROM clauses c JOIN documents d USING(doc_id)
                         JOIN insurers i ON i.member_cd=d.member_cd WHERE clause_id=?""", (cid,)).fetchone()
        c.close()
        if not r:
            self.send_page("<p>없음</p>")
            return
        tag = "특약" if r["is_rider"] else "주계약"
        st = f" · 섹션: {html.escape(r['section_title'])}" if r["section_title"] else ""
        body = (f"<p><a href='/doc?id={r['doc_id']}'>← 이 약관의 조문 목록</a></p>"
                f"<h2>{html.escape(r['clause_no'] or '')} {html.escape(r['title'] or '')}</h2>"
                f"<p class='meta'>{html.escape(r['insurer'])} · {html.escape(r['prod_nm_raw'])} · "
                f"{html.escape(r['version_label'] or '')} · [{tag}]{st}</p><pre>{html.escape(r['text'])}</pre>")
        self.send_page(body)

    def view_doc(self, did):
        c = self.conn()
        d = c.execute("""SELECT d.*, i.name AS insurer FROM documents d
                         JOIN insurers i USING(member_cd) WHERE doc_id=?""", (did,)).fetchone()
        rows = c.execute("""SELECT clause_id, clause_no, title, section_no, is_rider, section_title,
                                   length(text) L FROM clauses WHERE doc_id=? ORDER BY seq""", (did,)).fetchall()
        c.close()
        if not d:
            self.send_page("<p>없음</p>")
            return
        trs, prev_sec = "", None
        for r in rows:
            if r["L"] <= 30:
                continue
            if r["section_no"] != prev_sec:
                prev_sec = r["section_no"]
                label = "특약" if r["is_rider"] else "주계약"
                st = html.escape(r["section_title"] or "")
                trs += (f"<tr><td colspan='3' style='background:#f0f4ff'><b>섹션 {r['section_no']+1} "
                        f"[{label}]</b> {st}</td></tr>")
            trs += (f"<tr><td><a href='/clause?id={r['clause_id']}'>{html.escape(r['clause_no'] or '·')}</a></td>"
                    f"<td>{html.escape(r['title'] or '')}</td><td class='meta'>{r['L']:,}자</td></tr>")
        body = (f"<h2>{html.escape(d['prod_nm_raw'])}</h2>"
                f"<p class='meta'>{html.escape(d['insurer'])} · {html.escape(d['prod_group'] or '')} · "
                f"판매기간 {html.escape(d['version_label'] or '')} · sha256 {d['sha256'][:12]}…</p>"
                f"<table><tr><th>조문</th><th>제목</th><th>분량</th></tr>{trs}</table>")
        self.send_page(body)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(pathlib.Path(__file__).resolve().parent.parent / "db" / "terms_dist_current.db"))
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    App.db_path = args.db
    print(f"약관 DB 검색: http://localhost:{args.port}  (DB: {args.db})")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), App).serve_forever()


if __name__ == "__main__":
    main()
