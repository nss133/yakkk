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


def test_slice_section_between_markers():
    t = "머리말\n□ 생명보험\n제1조(목적)\n제2조(정의)\n□ 손해보험\n제1조(딴것)"
    out = sp.slice_section(t, r"□\s*생명보험", r"□\s*손해보험")
    assert "제1조(목적)" in out and "제2조(정의)" in out
    assert "딴것" not in out and "머리말" not in out


def test_slice_section_no_end_takes_to_eof():
    t = "□ 질병상해\n제1조(목적)\n제2조(정의)"
    out = sp.slice_section(t, r"□\s*질병상해", None)
    assert "제2조(정의)" in out
