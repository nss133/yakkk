#!/usr/bin/env python3
"""표준약관 소스(합본 md/초점 md/PDF) → 평문. 매니페스트 기반. (빌드 시점)

합본은 마크다운 표(| |) 래핑 + '######' 헤더를 씀 → 평문화 후 clause_split로 분할.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "catalog" / "standards.json"

_SEP_ROW = re.compile(r"^\s*\|[\s:|-]*\|\s*$")   # 표 구분행/빈 표행
_CELL = re.compile(r"^\s*\|(.*)\|\s*$")
_HDR = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BOLD = re.compile(r"\*\*(.+?)\*\*")             # **굵게** → 본문만
# 옵시디언 블록앵커(^6d2e06) — 항상 줄 끝에 붙는 관례라 줄末로 한정(본문 '^' 수식 오식 방지),
# 한 줄에 연속 2개(^hex ^hex) 실측 사례가 있어 반복 허용
_ANCHOR = re.compile(r"(?:[ \t]*\^[0-9a-f]{6})+[ \t]*$", re.M)
_WIKI_ALIAS = re.compile(r"\[\[[^\[\]|]+\|([^\[\]]+)\]\]")  # [[대상|별칭]] → 별칭
_WIKI = re.compile(r"\[\[([^\[\]]+)\]\]")                   # [[대상]] → 대상


def strip_md_table(text: str) -> str:
    out = []
    for ln in text.split("\n"):
        s = ln.rstrip()
        if _SEP_ROW.match(s):
            continue
        m = _CELL.match(s)
        if m:
            s = m.group(1).strip()
        out.append(s)
    return "\n".join(out)


def strip_md_headers(text: str) -> str:
    return _HDR.sub("", text)


def strip_md_inline(text: str) -> str:
    """옵시디언 md 인라인 아티팩트 제거 — 검색·유사도·diff 표시에 노이즈가 되는
    **굵게**, 블록앵커(^hex6), [[위키링크|별칭]]을 본문만 남기고 걷어냄."""
    text = _BOLD.sub(r"\1", text)
    text = text.replace("**", "")  # 짝 없는 여는/닫는 ** 잔재(원문 오탈자)도 제거
    text = _ANCHOR.sub("", text)
    text = _WIKI_ALIAS.sub(r"\1", text)
    return _WIKI.sub(r"\1", text)


def slice_section(text: str, start_pat: str, end_pat):
    lines = text.split("\n")
    si = ei = None
    for i, ln in enumerate(lines):
        if si is None and re.search(start_pat, ln):
            si = i
        elif si is not None and end_pat and re.search(end_pat, ln):
            ei = i
            break
    if si is None:
        raise ValueError(f"section_start 미매칭: {start_pat}")
    return "\n".join(lines[si:ei] if ei is not None else lines[si:])


def to_plaintext(entry: dict) -> str:
    p = pathlib.Path(entry["source_path"])
    if entry["source_type"] == "pdf":
        from extract_index import extract_pdf_text
        raw = extract_pdf_text(p)
    else:
        raw = p.read_text(encoding="utf-8")
        raw = strip_md_table(raw)
        raw = strip_md_headers(raw)
        raw = strip_md_inline(raw)
    if entry.get("section_start"):
        raw = slice_section(raw, entry["section_start"], entry.get("section_end"))
    return raw


def load_manifest(path=None):
    p = pathlib.Path(path) if path else MANIFEST
    return json.loads(p.read_text(encoding="utf-8"))
