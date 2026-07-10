import os
import sqlite3

import pytest

import simmatch

DB = "db/terms_dist_current.db"
pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason="반입 DB 없음")

# 초안측 쿼리(문장 살짝 변형) → 기대 상품군. top-N 안에 같은 취지 타사 조문이
# "제목/본문 키워드" 기준으로 실제로 들어오는지 검증한다(단순 score>0.1이 아님).
Q1 = "피보험자가 보험기간 중 사망하였을 때 회사는 사망보험금을 지급합니다"
Q2 = "계약자가 보험료를 내지 아니하여 납입이 연체된 경우 회사는 납입최고를 하고 계약을 해지할 수 있습니다"
Q3 = "청약을 한 계약자는 보험증권을 받은 날부터 15일 이내에 청약을 철회할 수 있습니다"


def _rows(c, idf, d, q, top_n=5):
    return simmatch.db_similar(c, q, idf, d, top_n=top_n, exclude_member="L34")


def test_golden_q1_사망보험금_지급():
    # "사망보험금 지급" 계열 조항이면 title에 "보험금"이 있고, title 또는 text에
    # "지급"이 있어야 한다(예: "보험금의 지급사유"). 위법계약해지 등 무관 조항 배제.
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    rows = _rows(c, idf, d, Q1, top_n=5)
    c.close()
    assert rows, "결과 없음"
    assert any(
        "보험금" in (r["title"] or "") and ("지급" in (r["title"] or "") or "지급" in (r["text"] or ""))
        for r in rows
    ), f"top-5에 '보험금 지급' 계열 조항 없음: {[r['title'] for r in rows]}"


def test_golden_q2_납입최고_해지_top3():
    # 핵심 회귀 방지 테스트: 순수 char-ngram 코사인만 쓰면 "계약자가...회사는...
    # 계약을 해지할 수 있습니다" 골격을 공유하는 "위법계약의 해지" 조항이
    # top-5를 전부 차지해 정작 "납입최고(독촉)와 계약의 해지" 조항이 밀려난다
    # (BM25 블렌딩 전 실측: 전부 0.147, 위법계약의 해지). 블렌딩 후에는
    # "납입"+"해지" 관련 조항이 top-3 안에 들어와야 하고, top-3에 "위법계약"만
    # 있어서는 안 된다.
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    rows = _rows(c, idf, d, Q2, top_n=5)
    c.close()
    assert rows, "결과 없음"
    top3 = rows[:3]

    def is_납입관련(r):
        blob = (r["title"] or "") + (r["text"] or "")
        return "납입최고" in blob or ("납입" in blob and "연체" in blob)

    def is_해지관련(r):
        blob = (r["title"] or "") + (r["text"] or "")
        return "해지" in blob

    assert any(is_납입관련(r) and is_해지관련(r) for r in top3), (
        f"top-3에 '납입최고/납입연체·해지' 조항이 없음: {[r['title'] for r in top3]}"
    )
    # top-3 전부가 "위법계약"류 조항이면 회귀 — 최소 하나는 위법계약이 아닌
    # 납입최고 계열이어야 한다(위 assert가 이미 이를 함의하지만 명시적으로 재확인).
    assert not all("위법계약" in (r["title"] or "") for r in top3), (
        f"top-3이 전부 '위법계약의 해지' 조항 — BM25 블렌딩 회귀: {[r['title'] for r in top3]}"
    )


def test_golden_q3_청약철회():
    # "청약의 철회" 계열이면 title에 "청약"과 "철회"가 함께 있어야 한다.
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    rows = _rows(c, idf, d, Q3, top_n=5)
    c.close()
    assert rows, "결과 없음"
    assert any(
        "청약" in (r["title"] or "") and "철회" in (r["title"] or "")
        for r in rows
    ), f"top-5에 '청약의 철회' 계열 조항 없음: {[r['title'] for r in rows]}"


def test_golden_standard_life_보험금지급사유():
    # 초안 조문(사망보험금 지급) → doc_type=STANDARD로 좁히면 생명보험 표준약관의
    # 대응 조문이 최상위로 잡혀야 한다(member_cd가 STD로 시작).
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    q = "피보험자가 보험기간 중 사망하였을 때 회사는 사망보험금을 지급합니다"
    std = simmatch.db_similar(c, q, idf, d, top_n=3, doc_type="STANDARD")
    c.close()
    assert std, "표준약관 대응 조문이 있어야 함"
    top = std[0]
    # 생명보험 표준약관의 보험금 지급사유 조문이 최상위
    assert top["member_cd"].startswith("STD")
    assert "보험금" in (top["title"] or "") or "지급" in (top["title"] or "")
    # 회귀 방지: 부정어 페널티 적용 후에도 top-1은 부지급 조문이 아니라
    # 긍정(지급사유) 조문이어야 한다(랭킹정밀도 개선 핵심 목표).
    assert "지급사유" in (top["title"] or "") or not simmatch.has_negation(top["title"] or ""), (
        f"top-1이 부지급 조문으로 잘못 상위 랭크됨: {top['title']}"
    )


# --- REG(감독규정·법령) 매핑 골든 (Task 5) --------------------------------
# 매핑 품질 게이트 실측(.superpowers/sdd/reg-mapping-eval.md, 6개 주제 2/6 PASS)에서
# 확인된, 유사도 매핑이 안정적으로 정답을 찾는 2개 주제만 회귀 테스트로 고정한다.
# 나머지 주제(보험금 지급/청약철회/계약전 알릴의무/배당)는 코퍼스 공백 또는 랭킹
# 미스로 실패 — 주제사전 보강이 후속 과제(별도 spec).

def test_golden_reg_해약환급금():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    q = "회사는 계약이 해지된 경우 해약환급금을 계약자에게 지급합니다"
    reg = simmatch.db_similar(c, q, idf, d, top_n=3, doc_type="REG")
    c.close()
    assert reg, "관련 규정 결과가 있어야 함"
    assert any(r["member_cd"].startswith("REG") for r in reg)
    # 해약환급금 관련 규정이 top-3에 (제목/본문에 '해약환급금' 포함)
    assert any("해약환급금" in ((r["title"] or "") + r["text"]) for r in reg)


def test_golden_reg_특별계정():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    q = "회사는 변액보험 자산을 특별계정으로 설정하여 운용합니다"
    reg = simmatch.db_similar(c, q, idf, d, top_n=3, doc_type="REG")
    c.close()
    assert reg, "관련 규정 결과가 있어야 함"
    assert any(r["member_cd"].startswith("REG") for r in reg)
    top = reg[0]
    # top-1이 특별계정 설정·운용 조문이어야 한다(보험업감독규정 제5-6조)
    assert "특별계정" in (top["title"] or ""), (
        f"top-1이 특별계정 조문이 아님: {top['title']}"
    )
