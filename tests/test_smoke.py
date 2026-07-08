"""테스트 환경 스모크."""
import importlib


def test_imports():
    # 빌드전용/런타임 핵심 모듈이 import 가능해야 함
    assert importlib.import_module("docx")
    assert importlib.import_module("sqlite3")
