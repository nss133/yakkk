#!/usr/bin/env python3
"""문자 n-gram TF-IDF 코사인 유사도 (표준 라이브러리 전용).

빌드 시점 산출 IDF(ngram_idf 테이블)를 dict로 받아, 런타임에 조문 두 개의
코사인을 계산한다. FTS 후보 검색은 db_similar()에서 결합(Task 6).
"""
import math
import re
import unicodedata
from collections import Counter

_KEEP = re.compile(r"[^가-힣a-z0-9]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower()
    return _KEEP.sub("", t)


def char_ngrams(text: str, sizes=(3, 4)):
    t = normalize(text)
    grams = []
    for nsz in sizes:
        if len(t) >= nsz:
            grams.extend(t[k:k + nsz] for k in range(len(t) - nsz + 1))
    return grams


def vectorize(text: str, idf: dict, default_idf: float) -> dict:
    tf = Counter(char_ngrams(text))
    vec = {g: (1.0 + math.log(c)) * idf.get(g, default_idf) for g, c in tf.items()}
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {g: w / norm for g, w in vec.items()}


def cosine(v1: dict, v2: dict) -> float:
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    return sum(w * v2.get(g, 0.0) for g, w in v1.items())
