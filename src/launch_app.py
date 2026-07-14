#!/usr/bin/env python3
"""폐쇄망 PC용 실행 진입점 — 서버 기동 + 브라우저 자동 오픈.

PyInstaller onefile 빌드 대상(.exe): 실행파일과 같은 폴더의 terms_dist_current.db를
찾아 검색앱을 띄우고 기본 브라우저를 연다. 개발 환경에서는 저장소의 db/ 경로 폴백.
포트는 8765부터 10개를 훑어 비어 있는 것을 사용(사내 PC 포트 선점 대비).
"""
import pathlib
import socket
import sys
import threading
import webbrowser

import search_app


def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):          # PyInstaller onefile
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def _find_db() -> pathlib.Path | None:
    base = _base_dir()
    for cand in (base / "terms_dist_current.db",
                 base.parent / "db" / "terms_dist_current.db"):  # 개발 폴백
        if cand.exists():
            return cand
    return None


def _pick_port(start: int = 8765, tries: int = 10) -> int:
    for p in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def main() -> int:
    db = _find_db()
    if db is None:
        print(f"DB 파일이 없습니다: {_base_dir() / 'terms_dist_current.db'}")
        print("실행파일과 같은 폴더에 terms_dist_current.db 를 두고 다시 실행하세요.")
        try:
            input("Enter 를 누르면 종료합니다...")
        except (EOFError, ValueError, OSError):   # 헤드리스(stdin 없음/닫힘) — CI 스모크 등
            pass
        return 1
    port = _pick_port()
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print("약관 검색·비교심사 도구를 시작합니다... (종료: 이 창 닫기)")
    sys.argv = ["search_app", "--db", str(db), "--port", str(port)]
    search_app.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
