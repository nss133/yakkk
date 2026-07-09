import os
import sqlite3

import pytest

import simmatch

DB = "db/terms_dist_current.db"
pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason="반입 DB 없음")

# 초안측 쿼리(문장 살짝 변형) → 기대 상품군. top-5 안에 같은 취지 타사 조문이 들어오는지.
GOLDEN = [
    "피보험자가 보험기간 중 사망하였을 때 회사는 사망보험금을 지급합니다",
    "계약자가 보험료를 내지 아니하여 납입이 연체된 경우 회사는 납입최고를 하고 계약을 해지할 수 있습니다",
    "청약을 한 계약자는 보험증권을 받은 날부터 15일 이내에 청약을 철회할 수 있습니다",
]


def test_golden_queries_return_hits():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    idf, d = simmatch.load_idf(c)
    hit = 0
    for q in GOLDEN:
        rows = simmatch.db_similar(c, q, idf, d, top_n=5, exclude_member="L34")
        if rows and rows[0]["score"] > 0.1:
            hit += 1
    c.close()
    assert hit == len(GOLDEN), f"{hit}/{len(GOLDEN)}만 히트 — 엔진/인덱스 점검"
