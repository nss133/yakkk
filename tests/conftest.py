"""테스트에서 src/ 모듈을 bare import 할 수 있도록 경로 추가."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
