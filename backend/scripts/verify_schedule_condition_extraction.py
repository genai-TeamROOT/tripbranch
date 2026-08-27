""" "반나절" 같은 시간 표현과 일정 발화의 목적지가 실행마다 다르게 추출되는지
실 LLM으로 재서 후속 프롬프트 작업의 기준선을 만든다 (TP-177 1단계).

배경: 골드셋(test_results/agent_quality/evaluation_dev.csv)의 SCHEDULE 실패가
2026-08-20부터 같은 자리에서 반복된다 — DEV-008/023의 `time_available`,
DEV-008/033의 `search_center`. `prompts/recommend/HISTORY.md`는 이를 "기존
비결정성 케이스"로 기록하고 "1회 실행으로 회귀를 판정하지 않아야 하는 사례로
남긴다"고 적어뒀지만, 그 흔들림이 얼마나 큰지 재는 수단은 없었다. 기준선이
흔들리는 상태에서 프롬프트를 고치면 개선인지 실행 간 분산인지 구분할 수 없다.

그래서 이 스크립트는 세 가지를 따로 본다.
  (1) 흔들림 — 같은 발화·같은 설정에서 실행마다 값이 바뀌는가
  (2) 응답 모델 — 그 흔들림이 폴백 때문인가
  (3) 기대 일치 — 골드셋 라벨과 맞는가
(1)이 있으면 (3)의 개선을 판정할 수 없으므로 (1)을 먼저 닫아야 한다.

(2)를 따로 보는 이유: 조건 추출은 `llm_fast_model_name` 묶음을 쓰고, 현재 .env는
주 모델 gemini-3.5-flash에 폴백 gemini-2.5-flash-lite(구세대)를 걸어두고 있다.
주 모델이 타임아웃·오류로 실패하면 폴백으로 조용히 넘어가므로(gemini.py의 모델
루프), 같은 발화가 실행마다 다른 모델로 처리될 수 있다. `record_llm_call()`이
남기는 `served_model`을 읽어 실제로 어느 모델이 답했는지 함께 기록한다.

`--model`을 주면 그 모델 하나만 쓰고 폴백을 두지 않는다. 기본 실행(폴백 있음)과
`--model gemini-3.5-flash`(폴백 없음)를 비교하면 흔들림이 폴백에서 오는지
격리할 수 있다.

SCHEDULE 조건은 지금 전용 추출 슬롯이 없어 `extract_recommend_conditions()`가
그대로 추출한다(`services/interpret/orchestrator.py`). 이 스크립트도 현재 동작을
재는 것이 목적이므로 같은 경로를 호출한다.

입력: --model(기본: 설정값+폴백), --repeat(기본 3), --delay(기본 1.0), --strict
출력: 케이스별 실행값·흔들림 여부·응답 모델·기대 일치, 그룹별 요약
호출 시점: 로컬 수동 실행. 실 LLM 호출이 필요해 CI 대상이 아니다.

    cd backend
    python -m scripts.verify_schedule_condition_extraction --repeat 3
    python -m scripts.verify_schedule_condition_extraction --repeat 3 --model gemini-3.5-flash
"""

from __future__ import annotations

import argparse
import asyncio
import time

from app.config import Settings
from app.providers.gemini import RealGeminiProvider
from app.services.runtime.llm_execution import (
    get_llm_execution_metadata,
    reset_llm_execution_metadata,
)

# 기대값을 두지 않는 자리. 규칙이 아직 없어서 "무엇이 맞다"를 정할 수 없는 표현은
# 기대 일치를 판정하지 않고 관측만 한다 — 값 자체보다 흔들리는지가 먼저다.
ANY = "*"

# (그룹, 발화, 기대 search_center, 기대 time_available)
# None은 "null이어야 한다", ANY는 "판정하지 않는다".
CASES: tuple[tuple[str, str, str | None, int | str | None], ...] = (
    # --- ① 골드셋 실패 재현. 라벨은 evaluation_dev.csv 기대값이다 ---
    ("골드셋", "광화문 반나절 일정 짜줘", "광화문", 240),  # DEV-008 (단일 턴)
    ("골드셋", "반나절 일정 짜줘", None, 240),  # DEV-023 1턴
    ("골드셋", "경복궁 근처 반나절 일정 짜줘", "경복궁", 240),  # DEV-033 1턴
    ("골드셋", "경복궁 근처 3시간 코스 짜줘", "경복궁", 180),  # DEV-009
    # --- ② 시간 표현. "반나절" 외에도 규칙이 없는 표현이 어떻게 나오는지 관측 ---
    ("시간표현", "광화문 하루 종일 일정 짜줘", "광화문", ANY),
    ("시간표현", "광화문 오후 내내 일정 짜줘", "광화문", ANY),
    ("시간표현", "광화문 두세 시간 코스 짜줘", "광화문", ANY),
    # 숫자 표현은 규칙이 있다(extract.md "시간(hour)"→×60) — 대조군
    ("시간표현", "광화문 4시간 일정 짜줘", "광화문", 240),
    # --- ③ 위치 표현. location_rules.md가 일정 발화 형태를 커버하는지 ---
    ("위치표현", "경복궁 코스 짜줘", "경복궁", ANY),
    ("위치표현", "경복궁 일정 짜줘", "경복궁", ANY),
    ("위치표현", "경복궁 근처 일정 짜줘", "경복궁", ANY),
    ("위치표현", "북촌 반나절 코스", "북촌", 240),
    # --- ④ 대조군. RECOMMEND 발화는 흔들리지 않아야 한다 ---
    ("대조군", "경복궁 근처 카페 추천해줘", "경복궁", None),
    ("대조군", "종로에서 15분 이내 카페 추천해줘", "종로", None),
)


def _served_model() -> str | None:
    """직전 호출에 실제로 답한 모델. 폴백으로 넘어갔는지 여기서 드러난다."""
    metadata = get_llm_execution_metadata()
    if metadata is None or not metadata.calls:
        return None
    return metadata.calls[-1].served_model


async def _extract(
    provider: RealGeminiProvider, text: str
) -> tuple[str | None, int | None, str | None, str | None, int]:
    """(search_center, time_available, 응답 모델, 오류, ms)를 반환한다."""
    reset_llm_execution_metadata()
    started = time.perf_counter()
    try:
        result = await provider.extract_recommend_conditions(text)
        recommend = result.data.recommend
        conditions = recommend.conditions if recommend else None
        search_center = conditions.search_center if conditions else None
        time_available = conditions.time_available if conditions else None
        error = None
    except Exception as exc:  # noqa: BLE001 - 실 API 검증 스크립트
        search_center, time_available = None, None
        error = f"{type(exc).__name__}: {exc}"
    ms = round((time.perf_counter() - started) * 1000)
    return search_center, time_available, _served_model(), error, ms


async def run(model: str | None, repeat: int, delay: float) -> list[dict[str, object]]:
    settings = Settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY가 필요합니다.")

    fast = [model] if model else settings.resolved_llm_fast_models
    provider = RealGeminiProvider(
        api_key=settings.llm_api_key,
        fast_model_names=fast,
        generation_model_names=settings.resolved_llm_generation_models,
        timeout_seconds=60.0,
    )
    chain = " → ".join(fast) if len(fast) > 1 else f"{fast[0]} (폴백 없음)"
    print(f"모델 묶음: {chain} | 반복: {repeat}회 | 케이스: {len(CASES)}건")

    rows: list[dict[str, object]] = []
    for group, text, expected_center, expected_time in CASES:
        centers: list[str | None] = []
        times: list[int | None] = []
        models: list[str | None] = []
        errors: list[str] = []
        latencies: list[int] = []
        for _ in range(repeat):
            center, time_available, served, error, ms = await _extract(provider, text)
            centers.append(center)
            times.append(time_available)
            models.append(served)
            latencies.append(ms)
            if error:
                errors.append(error)
            print("." if error is None else "!", end="", flush=True)
            await asyncio.sleep(delay)
        rows.append(
            {
                "그룹": group,
                "발화": text,
                "기대_center": expected_center,
                "기대_time": expected_time,
                "centers": centers,
                "times": times,
                "models": models,
                "오류": errors,
                "ms_평균": round(sum(latencies) / len(latencies)),
            }
        )

    print(flush=True)
    return rows


def _fmt(values: list[object]) -> str:
    """실행값 목록을 표시용 문자열로 만든다. 전부 같으면 값 하나만 보여준다."""
    seen = ["null" if v is None else str(v) for v in values]
    unique = sorted(set(seen))
    return unique[0] if len(unique) == 1 else " / ".join(seen)


def _is_stable(values: list[object]) -> bool:
    return len({"null" if v is None else str(v) for v in values}) == 1


def _matches(values: list[object], expected: object) -> bool | None:
    """기대값과 전부 일치하면 True. ANY면 판정하지 않고 None."""
    if expected == ANY:
        return None
    return all(v == expected for v in values)


def _short_model(name: str | None) -> str:
    """gemini-3.5-flash-lite → 3.5-flash-lite. 표가 넘치지 않게 접두사만 뗀다."""
    if name is None:
        return "?"
    return name.removeprefix("gemini-")


def _report(rows: list[dict[str, object]], repeat: int) -> int:
    unstable: list[dict[str, object]] = []
    mismatched: list[dict[str, object]] = []
    fell_back: list[dict[str, object]] = []

    header = (
        f"{'흔들림':<8} {'일치':<6} {'search_center':<24} "
        f"{'time_available':<18} {'응답모델':<26} 발화"
    )
    print(f"\n{header}")
    print("-" * 140)
    current_group = None
    for r in rows:
        if r["그룹"] != current_group:
            current_group = r["그룹"]
            print(f"[{current_group}]")

        centers = r["centers"]  # type: ignore[assignment]
        times = r["times"]  # type: ignore[assignment]
        models = [_short_model(m) for m in r["models"]]  # type: ignore[union-attr]
        stable = _is_stable(centers) and _is_stable(times)
        center_ok = _matches(centers, r["기대_center"])
        time_ok = _matches(times, r["기대_time"])

        judged = [v for v in (center_ok, time_ok) if v is not None]
        if not judged:
            match_mark = "관측"
        elif all(judged):
            match_mark = "✅"
        else:
            match_mark = "❌"
            mismatched.append(r)

        if not stable:
            unstable.append(r)
        if not _is_stable(models):
            fell_back.append(r)

        print(
            f"{'⚠️  흔들림' if not stable else '  고정':<8} {match_mark:<5} "
            f"{_fmt(centers):<24} {_fmt(times):<18} {_fmt(models):<26} {r['발화']}"
        )
        for error in set(r["오류"]):  # type: ignore[arg-type]
            print(f"{'':>16} ⚠️  {error}")

    print(f"\n{'=' * 70}")
    print(f"반복 {repeat}회 기준")
    print(f"  흔들린 케이스        {len(unstable)}/{len(rows)}건")
    for r in unstable:
        print(f"    - {r['발화']}  center={_fmt(r['centers'])} time={_fmt(r['times'])}")
    print(f"  응답 모델이 바뀐 케이스 {len(fell_back)}/{len(rows)}건")
    for r in fell_back:
        print(f"    - {r['발화']}  {_fmt([_short_model(m) for m in r['models']])}")
    print(f"  기대 불일치 케이스     {len(mismatched)}/{len(rows)}건")
    for r in mismatched:
        print(f"    - {r['발화']}  기대(center={r['기대_center']}, time={r['기대_time']})")

    if fell_back:
        print(
            "\n응답 모델이 바뀐 케이스가 있다 — 흔들림의 원인이 프롬프트가 아니라 "
            "폴백일 수 있다. --model로 폴백을 없애고 다시 재서 갈라본다."
        )
    print(
        "\n흔들린 케이스가 남아 있으면 프롬프트 개선의 전후 비교가 성립하지 않는다 "
        "— 기대 불일치보다 이쪽을 먼저 닫는다."
    )
    return len(unstable)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=None, help="이 모델 하나만 쓰고 폴백을 두지 않는다(기본: 설정값+폴백)"
    )
    parser.add_argument("--repeat", type=int, default=3, help="발화당 반복 횟수(기본 3)")
    parser.add_argument("--delay", type=float, default=1.0, help="호출 간 대기(초)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="흔들림이 있으면 종료코드 1. 기본은 0 — 기준선 측정 자체는 실패가 아니다",
    )
    args = parser.parse_args()

    rows = asyncio.run(run(args.model, args.repeat, args.delay))
    unstable = _report(rows, args.repeat)
    raise SystemExit(1 if (args.strict and unstable) else 0)


if __name__ == "__main__":
    main()
