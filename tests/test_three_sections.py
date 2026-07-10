from search_app import App


def _row(insurer, member, title):
    return {"score": 0.8, "insurer": insurer, "prod_nm_raw": insurer, "doc_id": 1,
            "clause_id": 9, "clause_no": "제3조", "title": title, "version_label": "v",
            "prod_group": "x", "text": "…", "member_cd": member}


def test_render_sections_order_std_reg_terms():
    std = [_row("생명보험 표준약관", "STD_L", "보험금의 지급사유")]
    reg = [_row("보험업감독규정", "REG_GD", "보험금 지급")]
    terms = [_row("삼성생명", "L03", "보험금의 지급")]
    html = App.render_sections([
        ("📋 표준약관 대응 조문", std, "표준약관 대응 조문 없음"),
        ("📖 관련 감독규정·법령", reg, "관련 감독규정·법령 없음"),
        ("🏢 타사 유사 조문", terms, "타사 유사 조문 없음"),
    ], query="보험금 지급")
    assert html.index("표준약관 대응 조문") < html.index("관련 감독규정·법령") < html.index("타사 유사 조문")
    assert "보험업감독규정" in html


def test_render_sections_empty_message():
    html = App.render_sections([("📖 관련 감독규정·법령", [], "관련 감독규정·법령 없음")], query="x")
    assert "관련 감독규정·법령 없음" in html
