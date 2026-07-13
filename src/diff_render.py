"""초안 vs 표준약관 인라인 diff HTML — 표준 라이브러리만 사용(반입물).

기준 방향은 초안(draft): 표준약관에만 있는 어절=<del>, 초안에만 있는 어절=<ins>.
어절(공백 토큰) 단위 SequenceMatcher — 한국어 약관에서 "30일→3영업일" 같은
교체가 어절로 잡히고, 문자 단위의 산탄 노이즈를 피함. 출력은 escape 완료 상태.
"""
import difflib
import html
import re

MAX_DIFF_CHARS = 20_000  # 초과 시 diff 생략(별표 등 초장문 지연·화면 폭주 방지)


def _tokens_ws(text):
    """어절 목록 + 각 어절 뒤 공백(초안 원문 공백 복원용). 기본 공백은 ' '."""
    words, trail = [], []
    for p in re.split(r"(\s+)", text or ""):
        if not p:
            continue
        if p.isspace():
            if trail:
                trail[-1] = p
        else:
            words.append(p)
            trail.append(" ")
    return words, trail


def _ops(a_words, b_words):
    return difflib.SequenceMatcher(None, a_words, b_words, autojunk=False).get_opcodes()


def diff_html(draft, std):
    """인라인 통합 diff. 빈 입력·MAX_DIFF_CHARS 초과면 ''(호출부 폴백)."""
    draft, std = draft or "", std or ""
    if not draft.strip() or not std.strip():
        return ""
    if len(draft) > MAX_DIFF_CHARS or len(std) > MAX_DIFF_CHARS:
        return ""
    b_words, b_trail = _tokens_ws(draft)   # b=초안(공백 보존)
    a_words = std.split()                  # a=표준약관(삭제분은 단일 공백 연결)
    out = []
    for tag, i1, i2, j1, j2 in _ops(a_words, b_words):
        if tag != "equal" and i2 > i1:     # delete·replace: 표준약관에만 있는 문구
            out.append("<del>" + html.escape(" ".join(a_words[i1:i2])) + "</del> ")
        if j2 > j1:                        # equal·insert·replace: 초안 문구(원문 공백)
            seg = "".join(html.escape(w) + t for w, t in zip(b_words[j1:j2], b_trail[j1:j2]))
            if tag == "equal":
                out.append(seg)
            else:
                core = seg.rstrip()
                out.append("<ins>" + core + "</ins>" + seg[len(core):])
    return "".join(out).rstrip()


def diff_stats(draft, std):
    """<summary> 요약용 지표. 어절 기준 일치율·초안 추가/표준약관 누락 구간 수."""
    a, b = (std or "").split(), (draft or "").split()
    if not a or not b:
        return {"equal_ratio": 0.0, "n_ins": 0, "n_del": 0}
    ops = _ops(a, b)
    n_ins = sum(1 for t, i1, i2, j1, j2 in ops if t in ("insert", "replace") and j2 > j1)
    n_del = sum(1 for t, i1, i2, j1, j2 in ops if t in ("delete", "replace") and i2 > i1)
    eq = sum(i2 - i1 for t, i1, i2, _, _ in ops if t == "equal")
    return {"equal_ratio": eq / max(len(a), len(b)), "n_ins": n_ins, "n_del": n_del}
