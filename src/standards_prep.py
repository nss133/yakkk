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
        return text
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
    if entry.get("section_start"):
        raw = slice_section(raw, entry["section_start"], entry.get("section_end"))
    return raw


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))
