#!/usr/bin/env python3
"""Phase 5: 월 주기 갱신 오케스트레이터.

순서: ①협회 카탈로그 재수집 → ②검색키 재생성 → ③4사 수집(증분: 기존 파일 스킵+sha dedup)
→ ④신규 문서 텍스트 추출 → ⑤매칭 재구축 → ⑥반입용 DB 재생성 → ⑦커버리지 리포트

모든 단계가 멱등·증분이라 중단돼도 재실행하면 이어짐.
수집 단계는 회사별 순차 실행(사이트 부하 고려 — 월 1회 저빈도 원칙).

사용법:
    .venv/bin/python src/update_all.py            # 전체
    .venv/bin/python src/update_all.py --skip-collect   # 수집 제외(추출·매칭·반입만)
"""
import argparse
import datetime
import subprocess
import sys

from common import ROOT

PY = str(ROOT / ".venv" / "bin" / "python")
SRC = ROOT / "src"
LOG_DIR = ROOT / "logs"


def run(step: str, args_: list, log_name: str) -> bool:
    LOG_DIR.mkdir(exist_ok=True)
    log = LOG_DIR / f"{log_name}_{datetime.date.today():%Y%m%d}.log"
    print(f"\n[{step}] {' '.join(args_)} → {log.name}")
    with log.open("a") as f:
        r = subprocess.run([PY] + args_, cwd=SRC, stdout=f, stderr=subprocess.STDOUT)
    tail = log.read_text().strip().splitlines()[-2:]
    for ln in tail:
        print(f"   {ln}")
    if r.returncode != 0:
        print(f"   ! 실패(exit {r.returncode}) — 로그 확인: {log}")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-collect", action="store_true")
    args = ap.parse_args()

    ok = True
    ok &= run("1. 협회 카탈로그", ["catalog_fetch.py"], "catalog")
    ok &= run("2. 검색키 재생성", ["gen_search_keys.py"], "searchkeys")

    if not args.skip_collect:
        for name, script in [("미래에셋", "collect_mirae.py"), ("한화", "collect_hanwha.py"),
                             ("삼성", "collect_samsung.py"), ("교보", "collect_kyobo.py"),
                             ("신한", "collect_shinhan.py"), ("NH", "collect_nh.py"),
                             ("KB", "collect_kb.py"), ("동양", "collect_dongyang.py"),
                             ("메트라이프", "collect_metlife.py"), ("흥국", "collect_heungkuk.py")]:
            extra = ["--categories", "전체", "--targets-json", "../catalog/targets_L34_pilot.json"] \
                if script == "collect_mirae.py" else []
            ok &= run(f"3. 수집({name})", [script] + extra, f"collect_{script.split('_')[1].split('.')[0]}")

    ok &= run("4. 텍스트 추출", ["extract_index.py"], "extract")
    ok &= run("4a. 표준약관 적재", ["ingest_standards.py"], "standards")
    ok &= run("4a2. 규정 적재", ["ingest_regulations.py"], "regulations")
    ok &= run("4b. 유사인덱스", ["build_simindex.py"], "simindex")
    ok &= run("5. 매칭 재구축", ["build_matches.py"], "matches")
    ok &= run("5b. 섹션 태깅", ["enrich_sections.py"], "enrich")
    ok &= run("6a. 반입DB(전체판)", ["export_dist.py"], "export")
    ok &= run("6b. 반입DB(현행판)", ["export_dist.py", "--current-only"], "export")
    run("7. 커버리지", ["coverage_report.py"], "coverage")

    print("\n" + ("✅ 갱신 완료" if ok else "⚠️ 일부 단계 실패 — logs/ 확인"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
