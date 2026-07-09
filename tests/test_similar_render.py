from search_app import App


def test_render_similar_groups_by_insurer():
    rows = [
        {"score": 0.81, "insurer": "삼성생명", "prod_nm_raw": "삼성종신", "clause_id": 20,
         "clause_no": "제3조", "title": "보험금의 지급", "version_label": "2024~",
         "prod_group": "종신", "text": "…", "doc_id": 1},
        {"score": 0.77, "insurer": "한화생명", "prod_nm_raw": "한화종신", "clause_id": 30,
         "clause_no": "제3조", "title": "보험금의 지급", "version_label": "2024~",
         "prod_group": "종신", "text": "…", "doc_id": 2},
    ]
    html = App.render_similar(rows)
    assert "삼성생명" in html and "한화생명" in html
    assert "81" in html          # 유사도 % 표기
    assert "/clause?id=20" in html


def test_render_similar_empty():
    assert "없" in App.render_similar([])


def test_render_similar_highlights_overlapping_query_words():
    rows = [
        {"score": 0.81, "insurer": "삼성생명", "prod_nm_raw": "삼성종신", "clause_id": 20,
         "clause_no": "제3조", "title": "보험금의 지급", "version_label": "2024~",
         "prod_group": "종신", "text": "피보험자가 사망한 경우 보험금을 지급합니다", "doc_id": 1},
    ]
    html = App.render_similar(rows, query="보험금 지급")
    assert "<mark>보험금</mark>" in html
    assert "<mark>지급" in html  # "지급합니다" 내 "지급" 부분매치


def test_render_similar_no_query_still_escapes():
    rows = [
        {"score": 0.5, "insurer": "한화생명", "prod_nm_raw": "한화종신", "clause_id": 30,
         "clause_no": "제3조", "title": "보험금의 지급", "version_label": "2024~",
         "prod_group": "종신", "text": "<script>alert(1)</script> 보험금 지급", "doc_id": 2},
    ]
    html = App.render_similar(rows)
    assert "<mark>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
