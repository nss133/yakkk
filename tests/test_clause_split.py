from clause_split import split_clauses


def _titles(text):
    return {no: ti for no, ti, _ in split_clauses(text) if no}


def test_inline_paren_title_kept():   # 교보·미래·한화 (기존 동작)
    t = "제3조 (보험금의 지급) 회사는 보험금을 지급합니다.\n다음 각 호를 따릅니다."
    out = split_clauses(t)
    no, ti, body = [c for c in out if c[0] == "제3조"][0]
    assert ti == "보험금의 지급"
    assert body.startswith("회사는 보험금을 지급합니다.")


def test_next_line_bare_title():   # 신한·KB: 제1조 / 목적 / 31
    t = "제1조\n목적\n31\n이 약관은 목적을 정합니다.\n제2조\n용어의 정의\n31"
    assert _titles(t)["제1조"] == "목적"
    assert _titles(t)["제2조"] == "용어의 정의"


def test_next_line_bracket_title():   # 삼성 [목적], NH 【목적】
    assert _titles("제1조\n[목적]\n6\n본문")["제1조"] == "목적"
    assert _titles("제1조\n【목적】\n39\n본문")["제1조"] == "목적"


def test_next_line_multiline_paren_title():   # NH 여러 줄 괄호
    t = ("제29조\n(보험료의 납입이 연체되는 경우 납입최\n고(독촉)와 계약의 해지)\n"
         "P.70\n계약자는 …")
    ti = _titles(t)["제29조"]
    assert "계약의 해지" in ti and ti.startswith("보험료의 납입")


def test_byulpyo_still_works():
    out = split_clauses("[별표 4] 장해분류표\n내용")
    assert any(no == "별표4" and "장해분류표" in ti for no, ti, _ in out)


def test_body_line_not_stolen_as_title():   # 오검출 방지: 문장은 제목 아님
    t = "제5조\n계약자는 보험료를 납입하여야 합니다.\n제6조"
    assert _titles(t)["제5조"] == ""   # 문장은 제목으로 안 잡힘


def test_bare_inline_title_shinhan():   # 신한: 제N조와 제목이 같은 줄, 괄호 없음
    t1 = "제12조 대표자의 지정\n43\n제3관 계약자의 계약 전 알릴 의무 등\n44"
    assert _titles(t1)["제12조"] == "대표자의 지정"

    t2 = "제15조 사기에 의한 계약\n46\n제4관 계약의 성립과 유지"
    assert _titles(t2)["제15조"] == "사기에 의한 계약"


def test_inline_multiline_paren_hanwha():   # 한화: 같은 줄에서 괄호가 열리고 다음 줄에서 닫힘
    t = ("제31조 (보험료의 납입이 연체되는 경우\n"
         "납입최고(독촉)와 계약의 해지)\n"
         "해지된 계약을 살리고 싶어요")
    ti = _titles(t)["제31조"]
    assert "납입최고(독촉)와 계약의 해지" in ti
    assert ti.startswith("보험료의 납입")


def test_inline_multiline_paren_met():   # 메트: 여러 줄에 걸쳐 괄호가 닫힘
    t = "제3조 (“암”등의\n정의\n및\n진단확정) 제1항에서 정한"
    ti = _titles(t)["제3조"]
    assert "정의" in ti and "진단확정" in ti


def test_bare_inline_title_body_next_line():   # 한화/메트 제1조: 제목 뒤 바로 본문
    t = "제1조 목적\n이 보험계약(이하 ‘계약’이라 합니다)은"
    assert _titles(t)["제1조"] == "목적"


def test_bare_inline_no_overrecovery():   # 과다복구 방지: rest가 서술문이면 제목 아님
    t = "제5조 회사는 보험금을 지급합니다\n본문"
    assert _titles(t)["제5조"] == ""


def test_bare_inline_stray_char_rejected():   # 과다복구 방지: 1글자는 제목 아님
    t = "제3조 제\n6항에서 정한 내용"
    assert _titles(t)["제3조"] == ""
