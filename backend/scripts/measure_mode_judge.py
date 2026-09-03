"""구간 이동수단 판정(TP-227)의 조건 반응·일관성·지연을 실제 Gemini로 측정한다.

역할: 같은 구간 표에 조건만 바꿔가며 `judge_travel_modes()`를 부르고, 기존 거리
      규칙과 얼마나 갈리는지 잰다. 프롬프트와 응답 스키마는 실제 경로 그대로 쓴다.

**정확도를 재지 않는다.** 같은 구간을 걸어도 되고 타도 되는 경우가 많아 "정답"이
하나가 아니다. 대신 네 가지를 본다.

1. 무반응 — 맑고 동행·무장애가 없으면 기존 규칙과 같은 판정을 내는가.
   여기서 갈리면 근거 없이 바뀐 것이다.
2. 반응 — 같은 구간에 비를 얹으면 전환이 늘어나는가.
3. 일관 — 같은 거리·조건이면 일정(순차)과 추천(독립)이 같은 수단을 말하는가.
   두 임계값이 환산 관계라(D-118) 여기서 갈리면 한 앱이 두 말을 하게 된다.

   **첫 줄끼리 비교한다.** 같은 표를 양쪽에 넣고 통째로 비교하면 안 된다 — 일정의
   3번째 구간은 앞서 21분을 걸은 뒤이고 추천의 3번째 후보는 처음 가는 곳이라,
   같은 거리라도 상황이 다르다. 답이 달라야 맞는다(2026-09-03에 이 비교를 잘못해
   정상 동작을 결함으로 읽은 적이 있다). 첫 줄에는 앞서 걸은 것이 없으므로 여기만
   같은 상황이다.
4. 지연 — 이 호출은 SCHEDULE·RECOMMEND 턴의 지연에 그대로 더해진다.

입력: `.env`의 LLM_API_KEY. 서버는 띄우지 않아도 된다.
출력: 표준 출력 + `test_results/mode_judge_<날짜>/measure_mode_judge.json`
호출 시점: `python -m scripts.measure_mode_judge`로 수동 실행한다. 실제 API를
          부르므로 pytest 스위트에는 넣지 않는다.

재측정이 필요한 시점: `prompts/mode_judge/`를 고쳤을 때, 임계값(D-118)을 바꿀 때,
모델을 교체할 때.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import date
from pathlib import Path

from app.config import settings
from app.domain.schedule_travel import (
    ModeJudgmentContext,
    SegmentModeInput,
    SegmentWeather,
)
from app.domain.travel_route import TravelMode
from app.place_search_policy import WALKING_SPEED_KM_PER_MINUTE
from app.providers.gemini import RealGeminiProvider
from app.schemas import UserConditions
from app.services.runtime.recommendation_transform import to_measured_travel_modes

RESULTS_DIR = Path(__file__).resolve().parent.parent / "test_results"

# 임계(직선 0.85km) 아래·근처·위를 고루 담는다. 근처를 넣는 이유는 판정이 임계를
# 그대로 흉내 내는지, 아니면 조건에 따라 흔들리는지가 거기서 갈리기 때문이다.
_DISTANCES_KM: tuple[float, ...] = (0.3, 0.6, 0.85, 1.2, 2.0, 3.5)

# 조건 축. 이름은 결과 표에 그대로 쓴다.
_CONDITIONS: dict[str, ModeJudgmentContext] = {
    "없음": ModeJudgmentContext(transport=None),
    "비": ModeJudgmentContext(
        transport=None,
        weather=SegmentWeather(precipitation="rain", sky="overcast", temperature_celsius=12.0),
    ),
    "맑음": ModeJudgmentContext(
        transport=None,
        weather=SegmentWeather(precipitation="none", sky="clear", temperature_celsius=21.0),
    ),
    "노인동행": ModeJudgmentContext(transport=None, companion="parent"),
    "유모차": ModeJudgmentContext(
        transport=None, accessibility_needs=("stroller_access",)
    ),
    "휠체어": ModeJudgmentContext(
        transport=None, accessibility_needs=("wheelchair_access",)
    ),
    "비+유모차": ModeJudgmentContext(
        transport=None,
        companion="parent",
        accessibility_needs=("stroller_access",),
        weather=SegmentWeather(precipitation="rain", sky="overcast", temperature_celsius=8.0),
    ),
}

# D-118의 임계. 규칙 기준선을 만들 때 쓴다.
_SWITCH_THRESHOLD_KM = 0.85


def _segments() -> tuple[SegmentModeInput, ...]:
    return tuple(
        SegmentModeInput(
            from_place_id=f"p{index}",
            to_place_id=f"p{index + 1}",
            order=index,
            distance_m=round(km * 1000),
            walk_minutes=round(km / WALKING_SPEED_KM_PER_MINUTE, 1),
        )
        for index, km in enumerate(_DISTANCES_KM, start=1)
    )


def _rule_baseline() -> tuple[str, ...]:
    """판정 도입 전 결과. 임계를 넘으면 대중교통을 함께 재므로 transit으로 본다."""

    return tuple(
        "transit"
        if TravelMode.TRANSIT
        in to_measured_travel_modes(
            UserConditions(),
            straight_line_km=km,
            switch_threshold_km=_SWITCH_THRESHOLD_KM,
        )
        else "walking"
        for km in _DISTANCES_KM
    )


async def _run_once(
    provider: RealGeminiProvider,
    segments: tuple[SegmentModeInput, ...],
    context: ModeJudgmentContext,
) -> tuple[tuple[str, ...], float]:
    started = time.perf_counter()
    result = await provider.judge_travel_modes(segments, context)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return tuple(result.data or ()), elapsed_ms


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="조건당 반복 횟수")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else RESULTS_DIR / f"mode_judge_{date.today()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    provider = RealGeminiProvider(
        api_key=settings.llm_api_key,
        fast_model_names=settings.resolved_llm_fast_models,
        # 판정은 생성 모델 묶음을 쓴다(gemini.py::judge_travel_modes).
        generation_model_names=settings.resolved_llm_generation_models,
    )
    segments = _segments()
    baseline = _rule_baseline()
    print(f"거리(km): {_DISTANCES_KM}")
    print(f"규칙 기준선: {baseline}\n")

    rows: list[dict[str, object]] = []
    latencies: list[float] = []

    for name, base_context in _CONDITIONS.items():
        for sequential in (True, False):
            label = f"{name}/{'일정' if sequential else '추천'}"
            context = ModeJudgmentContext(
                transport=base_context.transport,
                companion=base_context.companion,
                accessibility_needs=base_context.accessibility_needs,
                weather=base_context.weather,
                sequential=sequential,
            )
            for attempt in range(args.repeat):
                try:
                    modes, elapsed_ms = await _run_once(provider, segments, context)
                except Exception as exc:  # 측정 도구라 한 건 실패로 멈추지 않는다
                    print(f"  {label} #{attempt + 1} 실패: {exc}")
                    rows.append({"조건": label, "시도": attempt + 1, "실패": str(exc)})
                    continue
                latencies.append(elapsed_ms)
                same = sum(1 for a, b in zip(modes, baseline, strict=False) if a == b)
                first = modes[0] if modes else None
                transit = sum(1 for mode in modes if mode == "transit")
                rows.append(
                    {
                        "조건": label,
                        "시도": attempt + 1,
                        "판정": list(modes),
                        "규칙과_같은_구간": same,
                        "전체_구간": len(baseline),
                        "전환_수": transit,
                        "첫_줄": first,
                        "지연ms": round(elapsed_ms, 1),
                    }
                )
                print(
                    f"  {label} #{attempt + 1}: {modes}"
                    f"  규칙일치 {same}/{len(baseline)}"
                    f"  전환 {transit}  {elapsed_ms:.0f}ms"
                )

    summary: dict[str, object] = {"거리_km": list(_DISTANCES_KM), "규칙_기준선": list(baseline)}
    if latencies:
        ordered = sorted(latencies)
        summary["지연_p50_ms"] = round(statistics.median(ordered), 1)
        summary["지연_p95_ms"] = round(ordered[int(len(ordered) * 0.95) - 1], 1)
        summary["호출_수"] = len(latencies)

    out_path = out_dir / "measure_mode_judge.json"
    out_path.write_text(
        json.dumps({"요약": summary, "행": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n요약: {summary}")
    print(f"원자료: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
