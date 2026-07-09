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
