import pytest

import standards_prep as sp


def test_strip_md_table_unwraps_cells():
    t = "| ###### 제1조(목적) 이 계약은 …합니다. |\n| --- |\n| 본문 줄 |"
    out = sp.strip_md_table(t)
    assert "|" not in out
    assert "###### 제1조(목적)" in out
    assert "본문 줄" in out
    # 구분행(| --- |)은 제거
    assert "---" not in out


def test_strip_md_headers_keeps_body():
    assert sp.strip_md_headers("###### 제1조(목적) 본문") == "제1조(목적) 본문"
    assert sp.strip_md_headers("## 제1관 목적") == "제1관 목적"
    assert sp.strip_md_headers("일반 줄") == "일반 줄"


def test_strip_md_inline_removes_bold_keeps_text():
    assert sp.strip_md_inline("⑪ **다른 질병 또는 상해**로 인하여") == "⑪ 다른 질병 또는 상해로 인하여"


def test_strip_md_inline_removes_block_anchor():
    # 옵시디언 블록앵커(^ + hex 6자리)는 앞 공백째 제거, 줄 구조는 보존
    assert sp.strip_md_inline("사망보험금 ^6d2e06\n다음 줄") == "사망보험금\n다음 줄"


def test_strip_md_inline_removes_unpaired_bold_marker():
    # 원문 오탈자(여는 ** 만 있고 닫는 짝 없음) — 홑 ** 도 제거 (실측: 표준약관 제31조의2)
    assert sp.strip_md_inline("법위반사항이 있는 경우 **계약체결일부터 5년") == "법위반사항이 있는 경우 계약체결일부터 5년"


def test_strip_md_inline_unwraps_wikilink_alias():
    assert sp.strip_md_inline("[[상법(전문)|상법]]상 '고지의무'") == "상법상 '고지의무'"


def test_strip_md_inline_unwraps_wikilink_plain():
    assert sp.strip_md_inline("[[보험업법]] 참조") == "보험업법 참조"


def test_strip_md_inline_leaves_normal_text():
    # hex 6자리가 아닌 ^, 단일 * 등은 본문으로 보존
    t = "제3조(보험금) 3^2가 아닌 지급기일*을 지킵니다"
    assert sp.strip_md_inline(t) == t


def test_strip_md_inline_anchor_only_at_line_end():
    # 앵커는 줄末 한정 — 줄 중간의 ^수식(hex 6자리로 보여도)은 보존
    t = "면적은 3^100000 제곱미터입니다"
    assert sp.strip_md_inline(t) == t


def test_strip_md_inline_double_anchor_one_line():
    # 실측: 한 줄에 앵커 2개 연속 (질병상해 표준약관)
    assert sp.strip_md_inline("지급합니다 ^966e10 ^966e10\n다음") == "지급합니다\n다음"


def test_strip_md_inline_mangled_multi_asterisk_bold():
    # 실측: 표준약관+질병상해보험(전문).md 351행의 ****…** **…** 오식
    assert sp.strip_md_inline("****위험직종** **변경**시 통지") == "위험직종 변경시 통지"


def test_strip_md_inline_wikilink_internal_anchor():
    # 실측: [[#^hex|별칭]] 내부 앵커 링크 — 별칭만 남김
    assert sp.strip_md_inline("[[#^6d2e06|제3조(보험금의 지급사유) 제1호]]에 따라") \
        == "제3조(보험금의 지급사유) 제1호에 따라"


def test_to_plaintext_md_applies_inline_strip(tmp_path):
    src = tmp_path / "std.md"
    src.write_text("제1조(목적) **이 계약**은 [[상법(전문)|상법]]을 따릅니다 ^abc123\n본문", encoding="utf-8")
    out = sp.to_plaintext({"source_path": str(src), "source_type": "md"})
    assert out == "제1조(목적) 이 계약은 상법을 따릅니다\n본문"


def test_slice_section_between_markers():
    t = "머리말\n□ 생명보험\n제1조(목적)\n제2조(정의)\n□ 손해보험\n제1조(딴것)"
    out = sp.slice_section(t, r"□\s*생명보험", r"□\s*손해보험")
    assert "제1조(목적)" in out and "제2조(정의)" in out
    assert "딴것" not in out and "머리말" not in out


def test_slice_section_no_end_takes_to_eof():
    t = "□ 질병상해\n제1조(목적)\n제2조(정의)"
    out = sp.slice_section(t, r"□\s*질병상해", None)
    assert "제2조(정의)" in out


def test_slice_section_raises_when_start_missing():
    t = "머리말\n제1조(목적)\n제2조(정의)"
    with pytest.raises(ValueError):
        sp.slice_section(t, r"□\s*존재하지않는마커", None)
