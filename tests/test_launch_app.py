import socket

import launch_app


def test_pick_port_skips_busy_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    busy = s.getsockname()[1]
    try:
        got = launch_app._pick_port(start=busy, tries=5)
        assert got != busy and busy < got < busy + 5
    finally:
        s.close()


def test_pick_port_returns_start_when_free():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()  # 방금 확인한 빈 포트
    assert launch_app._pick_port(start=free, tries=1) == free


def test_find_db_dev_fallback_or_none():
    # 개발 환경: src/ 기준 상위 db/terms_dist_current.db 폴백을 찾거나,
    # (반입 DB가 없는 환경이면) None을 반환 — 예외 없이 동작해야 함
    db = launch_app._find_db()
    assert db is None or db.name == "terms_dist_current.db"
