#!/usr/bin/env python3
"""폐쇄망용 약관 검색 웹앱 — Python 표준 라이브러리만 사용(단일 파일).

terms_dist*.db + simmatch.py + diff_render.py와 이 파일을 반입하면 동작:
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
import re
import sqlite3
import urllib.parse

import simmatch
import diff_render

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB — docx 초안은 소용량, 넉넉히 상한선만 방어

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
 ins{background:#d7f5d7;text-decoration:none} del{background:#fdd;color:#933}
 .diff{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:14px;font-size:13px;line-height:1.8}
 details{margin:8px 0;border:1px solid #eee;padding:6px 10px} summary{cursor:pointer}
 a{color:#0a58ca;text-decoration:none} form{line-height:2.2}
</style></head><body>
<h1>약관 DB 검색 <span class="meta">__DBNAME__ · 문서 __NDOCS__건 · 조문 __NCLS__건</span></h1>
<p><a href="/review">📄 초안 docx 일괄 심사</a> · <a href="/similar_text">✍️ 조문 붙여넣기 비교</a></p>
<form method="get" action="/">
 <input type="text" id="q" name="q" value="__Q__" placeholder="검색어 (공백=AND, &quot;구문&quot;, 접두어*)">
 <select name="scope">__SCOPE__</select>
 <select name="dt">__DOCTYPE__</select>
 <select name="m"><option value="">전체 회사</option>__MEMBERS__</select>
 <select name="g"><option value="">전체 상품군</option>__GROUPS__</select>
 <select name="r">__RIDER__</select>
 <input type="text" id="pn" name="pn" value="__PN__" placeholder="상품명 포함어">
 <button>검색</button>
 <a href="/" style="margin-left:8px;padding:8px;border:1px solid #ccc;border-radius:4px;color:#555">초기화</a>
</form>
__BODY__
</body></html>"""

SCOPE_OPTS = [("", "본문+제목"), ("title", "제목(조문명)만")]
RIDER_OPTS = [("", "주계약+특약"), ("main", "주계약만"), ("rider", "특약만")]
# 검색 대상 코퍼스: 기본은 타사 약관(TERMS)만. 규범은 선택 시에만.
DOCTYPE_OPTS = [("TERMS", "타사 약관"), ("STANDARD", "표준약관"), ("REG", "감독규정·법령"), ("", "전체")]


def opts(pairs, sel):
    return "".join(f'<option value="{v}"{" selected" if v == sel else ""}>{html.escape(t)}</option>'
                   for v, t in pairs)


def _highlight_words(query, max_words=30):
    """검색어에서 변별력 있는 어절을 추출 — simmatch.fts_query와 동일한 토큰화 방식.
    유사조문 결과가 '왜 닮았는지' 근거로 겹친 표현을 하이라이트하는 데 사용."""
    toks = re.findall(r"[가-힣a-z0-9]{2,}", (query or "").lower())
    seen, words = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            words.append(t)
        if len(words) >= max_words:
            break
    return words


def _highlight(text, words):
    """text를 먼저 html.escape한 뒤, 이스케이프된 words와 대소문자 무시 매칭해 <mark>로 감쌈.
    순서 중요: escape 먼저 → 매칭/wrap 나중(XSS·이중이스케이프 방지)."""
    esc = html.escape(text or "")
    for w in sorted(words, key=len, reverse=True):  # 긴 단어 먼저 — 중첩 부분매치 방지
        if not w:
            continue
        ew = html.escape(w)
        esc = re.sub(re.escape(ew), lambda m: f"<mark>{m.group(0)}</mark>", esc, flags=re.IGNORECASE)
    return esc


def _parse_multipart(headers, body: bytes):
    """multipart/form-data → {필드명: 값(bytes)}. cgi 미사용(3.13+ 대응)."""
    ctype = headers.get("Content-Type", "")
    if "boundary=" not in ctype:
        return {}
    boundary = ("--" + ctype.split("boundary=", 1)[1].strip().strip('"')).encode()
    fields = {}
    for part in body.split(boundary):
        if not part.strip() or part.strip() == b"--":
            continue
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        head_txt = head.decode("utf-8", "replace")
        name = None
        for tok in head_txt.split(";"):
            tok = tok.strip()
            if tok.startswith("name="):
                name = tok.split("=", 1)[1].strip().strip('"')
        if name:
            fields[name] = data[:-2] if data.endswith(b"\r\n") else data
    return fields


class App(http.server.BaseHTTPRequestHandler):
    db_path = None
    idf = {}
    default_idf = 1.0
    self_member = "L34"   # 자사(미래에셋) — 유사비교에서 제외
    DIFF_MIN_SCORE = 0.25  # 미만이면 diff 대신 미리보기(오판 유도 방지)

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
               .replace("__DOCTYPE__", opts(DOCTYPE_OPTS, qs.get("dt", "TERMS")))
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

    @staticmethod
    def render_similar(rows, query=""):
        if not rows:
            return "<p>유사한 타사 조문이 없음</p>"
        hlwords = _highlight_words(query)
        by = {}
        for r in rows:
            by.setdefault(r["insurer"], []).append(r)
        out = []
        for insurer, items in by.items():
            out.append(f"<h3>{html.escape(insurer)}</h3><table>"
                       "<tr><th>유사도</th><th>상품(판매기간)</th><th>조문</th><th>내용</th></tr>")
            for r in items:
                pct = int(round(r["score"] * 100))
                out.append(
                    f"<tr><td><b>{pct}%</b></td>"
                    f"<td><a href='/doc?id={r['doc_id']}'>{html.escape(r['prod_nm_raw'])}</a>"
                    f"<div class='meta'>{html.escape(r['version_label'] or '')}</div></td>"
                    f"<td><a href='/clause?id={r['clause_id']}'>{html.escape(r['clause_no'] or '')} "
                    f"{html.escape(r['title'] or '')}</a></td>"
                    f"<td class='meta'>{_highlight((r['text'] or '')[:120], hlwords)}…</td></tr>")
            out.append("</table>")
        return "".join(out)

    @staticmethod
    def render_sections(sections, query=""):
        parts = []
        for label, rows, empty in sections:
            body = App.render_similar(rows, query) if rows else f"<p>{empty}</p>"
            parts.append(f"<h2>{label}</h2>{body}")
        return "<hr>".join(parts)

    @staticmethod
    def render_standard_diff(rows, draft_text):
        """표준약관 섹션: 매치별 <details> 인라인 diff. 1위만 펼침,
        저유사도(<DIFF_MIN_SCORE)·빈 본문·초장문은 미리보기 폴백."""
        if not rows:
            return "<p>표준약관 대응 조문 없음</p>"
        out = []
        for i, r in enumerate(rows):
            pct = int(round(r["score"] * 100))
            head = (f"<b>{pct}%</b> <a href='/doc?id={r['doc_id']}'>{html.escape(r['prod_nm_raw'])}</a>"
                    f" <span class='meta'>{html.escape(r['version_label'] or '')}</span> · "
                    f"<a href='/clause?id={r['clause_id']}'>{html.escape(r['clause_no'] or '')} "
                    f"{html.escape(r['title'] or '')}</a>")
            dh = (diff_render.diff_html(draft_text, r["text"])
                  if r["score"] >= App.DIFF_MIN_SCORE else "")
            if dh:
                s = diff_render.diff_stats(draft_text, r["text"])
                head += (f" <span class='meta'>일치 {int(round(s['equal_ratio'] * 100))}% · "
                         f"초안 추가 {s['n_ins']}곳 · 표준약관 누락 {s['n_del']}곳</span>")
                body = f"<div class='diff'>{dh}</div>"
            else:
                reason = ("유사도가 낮아 차이 표시 생략(대응 조문이 아닐 수 있음)"
                          if r["score"] < App.DIFF_MIN_SCORE
                          else "본문 또는 초안이 비어 있거나 길어 차이 표시 생략")
                body = (f"<p class='meta'>{reason}</p>"
                        f"<p class='meta'>{html.escape((r['text'] or '')[:120])}…</p>")
            out.append(f"<details{' open' if i == 0 else ''}><summary>{head}</summary>{body}</details>")
        return "".join(out)

    def _bridge_reg(self, c, std_clause_id):
        """top-1 표준약관 조문의 사전 매핑 조회 → (none사유|None, 매핑 rows|None).
        std_reg_map 부재(구버전 반입 DB)·연결 없음(c=None)이면 (None, None) — 브릿지 비활성 폴백."""
        if c is None:
            return None, None
        try:
            none_row = c.execute(
                "SELECT note FROM std_reg_map WHERE std_clause_id=? AND source='none'",
                (std_clause_id,)).fetchone()
            if none_row:
                return none_row["note"] or "", []
            rows = c.execute(
                """SELECT m.score, m.source, cl.clause_id, cl.clause_no, cl.title, cl.text,
                          d.doc_id, d.prod_nm_raw, d.version_label, i.name AS insurer
                   FROM std_reg_map m
                   JOIN clauses cl ON cl.clause_id = m.reg_clause_id
                   JOIN documents d ON d.doc_id = cl.doc_id
                   JOIN insurers i ON i.member_cd = d.member_cd
                   WHERE m.std_clause_id=? ORDER BY m.score DESC""",
                (std_clause_id,)).fetchall()
            return None, [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return None, None

    def _render_reg_section(self, c, std, reg, query):
        """감독규정 섹션: 브릿지(top-1 표준약관의 사전 매핑) 우선 + 직접 유사도 보충(중복 제거).
        골든 '대응 없음' 조문은 오매핑 노출 대신 공백 사유를 안내."""
        parts, bridge_ids = [], set()
        if std and std[0]["score"] >= App.DIFF_MIN_SCORE:
            note, bridge = self._bridge_reg(c, std[0]["clause_id"])
            via = html.escape(f"{std[0]['clause_no'] or ''} {std[0]['title'] or ''}".strip())
            if note is not None:
                parts.append(f"<p class='meta'>📎 표준약관 {via} 경유 — 감독규정 정면 대응 조문 없음: "
                             f"{html.escape(note)}</p>")
            elif bridge:
                for b in bridge:
                    if b["source"] == "golden":
                        b["version_label"] = ((b["version_label"] or "") + " · ✓검수").strip(" ·")
                parts.append(f"<p class='meta'>📎 표준약관 {via} 경유(사전 매핑)</p>"
                             + self.render_similar(bridge, query))
                bridge_ids = {b["clause_id"] for b in bridge}
        direct = [r for r in reg if r["clause_id"] not in bridge_ids]
        if direct:
            label = "<p class='meta'>직접 유사</p>" if parts else ""
            parts.append(label + self.render_similar(direct, query))
        return "".join(parts) or "<p>관련 감독규정·법령 없음</p>"

    def _similar_blocks(self, c, query, query_title=None):
        """표준약관(diff)·감독규정(브릿지+직접)·타사 3섹션을 한 번에 조회·렌더."""
        std = simmatch.db_similar(c, query, self.idf, self.default_idf, top_n=3,
                                  query_title=query_title, doc_type="STANDARD")
        reg = simmatch.db_similar(c, query, self.idf, self.default_idf, top_n=3,
                                  query_title=query_title, doc_type="REG")
        terms = simmatch.db_similar(c, query, self.idf, self.default_idf, top_n=10,
                                    exclude_member=self.self_member,
                                    query_title=query_title, doc_type="TERMS")
        std_html = f"<h2>📋 표준약관 대응 조문</h2>{self.render_standard_diff(std, query)}"
        reg_html = f"<h2>📖 관련 감독규정·법령</h2>{self._render_reg_section(c, std, reg, query)}"
        terms_html = self.render_sections([
            ("🏢 타사 유사 조문", terms, "타사 유사 조문 없음"),
        ], query)
        return f"{std_html}<hr>{reg_html}<hr>{terms_html}"

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        raw = urllib.parse.parse_qs(u.query)
        qs = {k: v[0] for k, v in raw.items()}
        try:
            if u.path == "/clause":
                self.view_clause(int(qs["id"]))
            elif u.path == "/doc":
                self.view_doc(int(qs["id"]))
            elif u.path == "/similar":
                self.similar_by_clause(int(qs["id"]))
            elif u.path == "/similar_text":
                self.similar_by_text(qs.get("t", ""))
            elif u.path == "/review":
                self.review_form()
            else:
                self.search(qs)
        except Exception as e:
            self.send_page(f"<p>오류: {html.escape(str(e))}</p>", qs)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD_BYTES:
            self.send_page("<p>업로드 크기 초과</p>")
            return
        raw = self.rfile.read(length)
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/review":
                self.review_post(raw)
            elif u.path == "/similar_text":
                qs = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
                self.similar_by_text(qs.get("t", ""))
            else:
                self.send_page("<p>알 수 없는 요청</p>")
        except Exception as e:
            self.send_page(f"<p>오류: {html.escape(str(e))}</p>")

    def similar_by_clause(self, cid):
        c = self.conn()
        r = c.execute("SELECT c.text, c.title FROM clauses c "
                      "JOIN documents d USING(doc_id) WHERE clause_id=?", (cid,)).fetchone()
        if not r:
            c.close(); self.send_page("<p>조문 없음</p>"); return
        html_body = self._similar_blocks(c, r["text"], r["title"])
        c.close()
        self.send_page(f"<p class='meta'>이 조문의 표준약관·감독규정·타사 대응 조문</p>{html_body}")

    def similar_by_text(self, text):
        text = (text or "").strip()
        form = ("<form method='post' action='/similar_text'>"
                "<p class='meta'>초안 조문 텍스트를 붙여넣으세요(여러 조문 가능).</p>"
                f"<textarea name='t' rows='8' style='width:100%'>{html.escape(text)}</textarea>"
                "<br><button>유사 타사 조문 찾기</button></form>")
        if not text:
            self.send_page(form); return
        from clause_split import split_clauses
        c = self.conn()
        blocks = [(no, ti, body) for no, ti, body in split_clauses(text) if (body or "").strip()]
        if not blocks:
            blocks = [(None, "", text)]
        parts = []
        for no, ti, body in blocks:
            head = f"{no or ''} {ti or ''}".strip() or "(붙여넣은 조문)"
            parts.append(f"<h2>{html.escape(head)}</h2>{self._similar_blocks(c, body)}")
        c.close()
        self.send_page(form + "".join(parts))

    def review_form(self, msg=""):
        try:
            import docx  # noqa: F401
            avail = ""
        except Exception:
            avail = "<p style='color:#933'>python-docx 미설치 — 업로드 비활성(붙여넣기는 /similar_text 사용)</p>"
        self.send_page(
            f"{avail}{msg}<form method='post' action='/review' enctype='multipart/form-data'>"
            "<p class='meta'>심사할 초안 약관(.docx)을 올리면 조문별 유사 타사 조문을 붙여줍니다.</p>"
            "<input type='file' name='f' accept='.docx'> <button>일괄 심사</button></form>")

    def review_post(self, raw):
        fields = _parse_multipart(self.headers, raw)
        blob = fields.get("f")
        if not blob or len(blob) < 100:
            self.review_form("<p>파일이 비어 있음</p>"); return
        import io
        from docx_split import docx_to_text
        try:
            text = docx_to_text(io.BytesIO(blob))
        except Exception as e:
            self.review_form(f"<p>docx 파싱 실패: {html.escape(str(e))}</p>"); return
        from clause_split import split_clauses
        blocks = [(no, ti, body) for no, ti, body in split_clauses(text)
                  if no and (body or "").strip()]
        c = self.conn()
        parts = [f"<p class='meta'>초안 조문 {len(blocks)}건 심사</p>"]
        for no, ti, body in blocks:
            head = f"{no} {ti}".strip()
            parts.append(f"<h2>{html.escape(head)}</h2>"
                         f"<pre>{html.escape(body[:400])}</pre>{self._similar_blocks(c, body)}")
        c.close()
        self.send_page("".join(parts))

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
        dt = qs.get("dt", "TERMS")   # 기본: 타사 약관만. 빈값이면 전체(규범 포함)
        if dt:
            sql += " AND d.doc_type = ?"; params.append(dt)
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
        body = (f"<p><a href='/doc?id={r['doc_id']}'>← 이 약관의 조문 목록</a> · "
                f"<a href='/similar?id={r['clause_id']}'>🔍 닮은 타사 조문</a></p>"
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
    _c = sqlite3.connect(args.db)
    try:
        App.idf, App.default_idf = simmatch.load_idf(_c)
        print(f"유사도 인덱스 로드: n-gram {len(App.idf):,}")
    except Exception as e:
        print(f"(유사도 인덱스 없음: {e} — 검색만 가능)")
    finally:
        _c.close()
    print(f"약관 DB 검색: http://localhost:{args.port}  (DB: {args.db})")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), App).serve_forever()


if __name__ == "__main__":
    main()
