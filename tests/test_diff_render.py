from diff_render import diff_html, diff_stats, MAX_DIFF_CHARS


def test_replace_word_marks_del_then_ins():
    h = diff_html("회사는 3영업일 이내에 지급합니다", "회사는 30일 이내에 지급합니다")
    assert "<del>30일</del>" in h
    assert "<ins>3영업일</ins>" in h
    assert h.index("<del>") < h.index("<ins>")  # replace는 del 먼저


def test_insert_only_in_draft():
    h = diff_html("회사는 다만 재해보상의 경우 지급합니다", "회사는 지급합니다")
    assert "<ins>다만 재해보상의 경우</ins>" in h
    assert "<del>" not in h


def test_delete_only_in_standard():
    h = diff_html("회사는 지급합니다", "회사는 지체없이 지급합니다")
    assert "<del>지체없이</del>" in h
    assert "<ins>" not in h


def test_equal_text_no_tags():
    h = diff_html("보험금을 지급합니다", "보험금을 지급합니다")
    assert "<ins>" not in h and "<del>" not in h
    assert "보험금을 지급합니다" in h


def test_whitespace_preserved_in_equal_segments():
    # 초안의 개행이 equal 구간에서 보존됨(pre-wrap 렌더 전제)
    h = diff_html("제1항 본문\n제2항 본문", "제1항 본문\n제2항 본문")
    assert "제1항 본문\n제2항 본문" in h


def test_xss_escaped():
    h = diff_html("회사는 <script>alert(1)</script> 지급", "회사는 지급")
    assert "<script>" not in h
    assert "&lt;script&gt;" in h


def test_empty_and_oversize_return_empty():
    assert diff_html("", "표준") == ""
    assert diff_html("초안", "  ") == ""
    assert diff_html("가 " * (MAX_DIFF_CHARS // 2 + 1), "표준 문구") == ""


def test_stats_counts():
    s = diff_stats("회사는 3영업일 이내에 지급합니다", "회사는 30일 이내에 지급합니다")
    assert s["n_ins"] == 1 and s["n_del"] == 1
    assert 0.0 < s["equal_ratio"] < 1.0
    same = diff_stats("동일 문장", "동일 문장")
    assert same == {"equal_ratio": 1.0, "n_ins": 0, "n_del": 0}
    assert diff_stats("", "표준") == {"equal_ratio": 0.0, "n_ins": 0, "n_del": 0}
