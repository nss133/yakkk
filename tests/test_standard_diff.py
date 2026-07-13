from search_app import App


def _std_row(score, text, title="보험금의 지급"):
    return {"score": score, "insurer": "생명보험 표준약관", "prod_nm_raw": "생명보험 표준약관",
            "doc_id": 1, "clause_id": 9, "clause_no": "제3조", "title": title,
            "version_label": "2026-01", "prod_group": "표준", "text": text, "member_cd": "STD_L"}


def test_top1_open_rest_collapsed():
    rows = [_std_row(0.8, "회사는 30일 이내에 지급합니다"),
            _std_row(0.5, "회사는 30일 이내에 지급합니다"),
            _std_row(0.4, "회사는 30일 이내에 지급합니다")]
    h = App.render_standard_diff(rows, "회사는 3영업일 이내에 지급합니다")
    assert h.count("<details open>") == 1
    assert h.count("<details>") == 2
    assert h.index("<details open>") < h.index("<details>")  # 1위가 펼침


def test_diff_and_stats_in_output():
    h = App.render_standard_diff([_std_row(0.8, "회사는 30일 이내에 지급합니다")],
                                 "회사는 3영업일 이내에 지급합니다")
    assert "<del>30일</del>" in h and "<ins>3영업일</ins>" in h
    assert "일치" in h and "초안 추가" in h and "표준약관 누락" in h
    assert "/clause?id=9" in h and "/doc?id=1" in h  # 기존 링크 유지


def test_low_score_falls_back_to_preview():
    h = App.render_standard_diff([_std_row(0.1, "완전히 다른 조문 본문")], "회사는 지급합니다")
    assert "<ins>" not in h and "<del>" not in h
    assert "유사도가 낮아" in h
    assert "완전히 다른 조문 본문"[:10] in h  # 미리보기 폴백


def test_empty_rows_message():
    assert "표준약관 대응 조문 없음" in App.render_standard_diff([], "x")


def test_similar_blocks_keeps_three_sections(monkeypatch):
    # _similar_blocks가 3섹션 순서를 유지하고 표준약관 섹션만 diff 렌더러를 쓰는지
    import search_app

    def fake_db_similar(c, q, idf, dflt, top_n=10, exclude_member=None,
                        query_title=None, doc_type="TERMS", **kw):
        return [_std_row(0.8, "회사는 30일 이내에 지급합니다")] if doc_type == "STANDARD" else []

    monkeypatch.setattr(search_app.simmatch, "db_similar", fake_db_similar)
    app = App.__new__(App)  # 핸들러 생성 없이 메서드만 사용
    h = app._similar_blocks(None, "회사는 3영업일 이내에 지급합니다")
    i_std = h.index("표준약관 대응 조문")
    i_reg = h.index("관련 감독규정·법령")
    i_terms = h.index("타사 유사 조문")
    assert i_std < i_reg < i_terms
    assert "<ins>3영업일</ins>" in h
    assert "관련 감독규정·법령 없음" in h and "타사 유사 조문 없음" in h
