import math

import simmatch


def test_normalize_strips_space_and_punct():
    assert simmatch.normalize("보험금의  지급(사유)!") == "보험금의지급사유"


def test_char_ngrams_sizes():
    g = simmatch.char_ngrams("보험금지", sizes=(3,))
    assert g == ["보험금", "험금지"]


def test_cosine_identical_is_one():
    idf = {}
    v = simmatch.vectorize("보험금의 지급사유", idf, default_idf=1.0)
    assert abs(simmatch.cosine(v, v) - 1.0) < 1e-9


def test_cosine_similar_higher_than_dissimilar():
    idf, d = {}, 1.0
    q = simmatch.vectorize("피보험자가 사망한 경우 보험금을 지급합니다", idf, d)
    near = simmatch.vectorize("피보험자가 사망한 때에 보험금을 지급함", idf, d)
    far = simmatch.vectorize("보험료의 납입을 연체하면 계약이 해지됩니다", idf, d)
    assert simmatch.cosine(q, near) > simmatch.cosine(q, far)


def test_idf_weights_rare_grams_more():
    q = simmatch.vectorize("가나다라", {"가나다": 5.0, "나다라": 1.0}, default_idf=1.0)
    assert q["가나다"] > q["나다라"]


def test_has_negation_detects_markers():
    assert simmatch.has_negation("보험금을 지급하지 않는 사유")
    assert simmatch.has_negation("보험금을 지급하지 아니하는 경우")
    assert not simmatch.has_negation("보험금의 지급사유")
    assert not simmatch.has_negation("청약의 철회")
