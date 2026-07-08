#!/usr/bin/env python3
"""조문 분할 + 제목 파싱(회사별 레이아웃 대응). extract_index·docx_split 공용.

지원 제목 패턴:
- 같은 줄 괄호:  제3조 (보험금의 지급) 본문…
- 다음 줄 bare:  제1조 / 목적 / 31
- 다음 줄 브래킷: 제1조 / [목적] 또는 【목적】
- 다음 줄 여러 줄 괄호: 제29조 / (…납입최 / 고…해지)
"""
import re

RE_JO = re.compile(r"^\s*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(.*)$")
RE_BYULPYO = re.compile(r"^\s*[\[(【]?\s*(별\s*표\s*\d*)\s*[\])】]?\s*(.{0,60})$")
RE_PAGE = re.compile(r"^\s*(?:P\.?\s*)?\d{1,4}\s*$")            # 페이지번호/숫자만 행
RE_MARKER = re.compile(r"^\s*[①-⓿❶-❿]+\s*$")  # 원문자 마커 행

_OPEN = {"(": ")", "[": "]", "【": "】", "〔": "〕"}
_CLOSE = set(")]】〕")
_STRIP = "[]()【】〔〕 \t"


def norm_no(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip(_STRIP)).strip()


def _looks_title(s: str) -> bool:
    """짧은 한글 어구이며 본문 문장이 아닌 것만 제목 후보로."""
    s = s.strip()
    if not (0 < len(s) <= 40):
        return False
    if RE_JO.match(s) or RE_PAGE.match(s) or RE_MARKER.match(s):
        return False
    if s[0] in "①②③④⑤⑥⑦⑧⑨⑩0123456789":
        return False
    if s.endswith(("니다.", "니다", "습니다", "합니다")):   # 서술 문장 배제
        return False
    return bool(re.search(r"[가-힣]", s))


def _inline_title(rest: str):
    """같은 줄 '(제목) 본문' → (title, body). 괄호로 안 시작하면 ('', rest)."""
    rest = rest.strip()
    if rest and rest[0] in _OPEN:
        depth, end = 0, -1
        for idx, ch in enumerate(rest):
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end != -1:
            title = _clean_title(rest[:end + 1])
            if 0 < len(title) <= 60:
                return title, rest[end + 1:].strip()
    return "", rest


def _bracket_title(lines, i):
    """lines[i]가 여는 괄호로 시작하면 닫힐 때까지(최대 5행) 모아 (title, next_i)."""
    if i >= len(lines):
        return None, i
    s = lines[i].strip()
    if not s or s[0] not in _OPEN:
        return None, i
    depth, buf, j = 0, [], i
    while j < len(lines) and j < i + 5:
        seg = lines[j].strip()
        for ch in seg:
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                depth -= 1
        buf.append(seg)
        j += 1
        if depth <= 0:
            break
    title = _clean_title(" ".join(buf))
    return (title, j) if 0 < len(title) <= 60 else (None, i)


def split_clauses(text: str):
    """문서 전체를 순차 청크로 분할. 반환: [(clause_no|None, title, body)]"""
    lines = text.split("\n")
    chunks = []
    cur_no, cur_title, cur_lines = None, "", []

    def flush():
        nonlocal cur_no, cur_title, cur_lines
        body = "\n".join(cur_lines).strip()
        if body or cur_no:
            chunks.append((cur_no, cur_title, body))
        cur_no, cur_title, cur_lines = None, "", []

    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        m = RE_JO.match(ln)
        if m:
            flush()
            cur_no = norm_no(m.group(1))
            rest = (m.group(2) or "").strip()
            title, body_rest = _inline_title(rest)
            if title:
                cur_title, cur_lines, i = title, ([body_rest] if body_rest else []), i + 1
                continue
            # 같은 줄에 제목 없음 → 다음 줄에서 복구
            cur_lines = [rest] if rest else []
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            bt, nj = _bracket_title(lines, j)
            if bt:
                cur_title, i = bt, nj
                continue
            if j < n:
                cand = lines[j].strip()
                nxt = lines[j + 1].strip() if j + 1 < n else ""
                if _looks_title(cand) and (
                    not nxt or RE_PAGE.match(nxt) or RE_MARKER.match(nxt)
                    or nxt.startswith("제")
                ):
                    cur_title, i = cand, j + 1
                    continue
            i += 1
            continue
        mb = RE_BYULPYO.match(ln)
        if mb and len(ln.strip()) < 70:
            flush()
            cur_no, cur_title, cur_lines, i = norm_no(mb.group(1)), mb.group(2).strip(), [], i + 1
            continue
        cur_lines.append(ln)
        i += 1
    flush()

    out = []
    for k, (no, title, body) in enumerate(chunks):
        if no is None:
            title = title or ("[전문]" if k == 0 else "[본문외]")
        out.append((no, title, body))
    return out
