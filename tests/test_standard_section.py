from search_app import App


def test_two_sections_renders_standard_on_top():
    std = [{"score": 0.9, "insurer": "생명보험 표준약관", "prod_nm_raw": "생명보험 표준약관",
            "doc_id": 1, "clause_id": 5, "clause_no": "제3조", "title": "보험금의 지급사유",
            "version_label": "2024.12.20 개정", "prod_group": "life", "text": "…", "member_cd": "STD_L"}]
    terms = [{"score": 0.8, "insurer": "삼성생명", "prod_nm_raw": "삼성종신", "doc_id": 2,
              "clause_id": 9, "clause_no": "제3조", "title": "보험금의 지급", "version_label": "2024~",
              "prod_group": "종신", "text": "…", "member_cd": "L03"}]
    html = App.render_two_sections(std, terms, query="사망 보험금")
    assert "표준약관 대응 조문" in html
    assert "타사" in html
    # 표준약관 섹션이 타사 섹션보다 먼저
    assert html.index("표준약관 대응 조문") < html.index("타사")
    assert "생명보험 표준약관" in html and "삼성생명" in html


def test_two_sections_standard_empty_message():
    html = App.render_two_sections([], [], query="x")
    assert "표준약관 대응 조문 없음" in html
