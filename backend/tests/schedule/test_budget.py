"""예산 산수 단위 테스트. (TP-238)

`fit_durations_to_budget()`이 지켜야 하는 것은 넷이다 — 정책 범위를 안 넘고,
조절하면 안 되는 자리는 안 건드리고, 이미 허용 오차 안이면 아무것도 안 하고,
상대 크기를 유지한다.
"""

from __future__ import annotations

from app.schedule.budget import (
    SCHEDULE_TIME_TOLERANCE_MIN,
    DurationSlot,
    classify_budget,
    fit_durations_to_budget,
)
from app.schedule.duration import VisitDurationPolicy
from app.schemas import ScheduleBudgetStatus

_ATTRACTION = VisitDurationPolicy(60, 90, 120)


def _slots(*durations: int, policy: VisitDurationPolicy | None = _ATTRACTION) -> list[DurationSlot]:
    return [DurationSlot(current_min=d, policy=policy) for d in durations]


class TestClassifyBudget:
    def test_시간을_말하지_않았으면_판정하지_않는다(self) -> None:
        """None은 "지켰다"도 "넘었다"도 아니다. 0으로 뭉개면 화면이 지키지도 않은
        약속을 말하게 된다."""

        assert classify_budget(300, None) is None

    def test_허용_오차_경계는_지킨_것으로_친다(self) -> None:
        """딱 30분 초과까지는 WITHIN이다. 이 경계가 "3시간에 3곳"을 통과시키는
        지점이라 한 칸만 밀려도 곳 수가 줄어든다."""

        assert classify_budget(180 + SCHEDULE_TIME_TOLERANCE_MIN, 180) is (
            ScheduleBudgetStatus.WITHIN
        )
        assert classify_budget(180 + SCHEDULE_TIME_TOLERANCE_MIN + 1, 180) is (
            ScheduleBudgetStatus.OVER
        )

    def test_모자란_쪽도_같은_오차로_판정한다(self) -> None:
        assert classify_budget(180 - SCHEDULE_TIME_TOLERANCE_MIN, 180) is (
            ScheduleBudgetStatus.WITHIN
        )
        assert classify_budget(180 - SCHEDULE_TIME_TOLERANCE_MIN - 1, 180) is (
            ScheduleBudgetStatus.UNDER
        )


class TestFitDurationsToBudget:
    def test_초과하면_최소값_방향으로_줄인다(self) -> None:
        """관광지 3곳 90분씩 + 이동 30분 = 300분을 180분 예산에 맞춘다.

        여유는 곳당 30분(90 -> 60)뿐이라 210분까지만 줄어든다. 그 210분이
        허용 오차 안이고, 이것이 "3시간에 3곳"이 성립하는 경로다.
        """

        fitted = fit_durations_to_budget(_slots(90, 90, 90), overhead_min=30, budget_min=180)

        assert fitted == [60, 60, 60]
        assert sum(fitted) + 30 == 210
        assert classify_budget(210, 180) is ScheduleBudgetStatus.WITHIN

    def test_예산에_한참_못_미치면_최대값_방향으로_늘린다(self) -> None:
        fitted = fit_durations_to_budget(_slots(60, 60), overhead_min=15, budget_min=300)

        assert fitted == [120, 120]

    def test_이미_허용_오차_안이면_아무것도_바꾸지_않는다(self) -> None:
        """**이 가드가 없으면 밴드 안의 일정까지 예산에 딱 맞게 늘어난다.**

        60+60+이동 15 = 135분은 150분 요청의 오차 안이다. 여기서 굳이 늘리는 것은
        "사용자가 말한 시간은 꽉 채워 다니겠다는 뜻"이라고 가정하는 것인데 팀이
        그렇게 정한 적이 없다. 실제로 이 가드를 빼면 자정 넘김 편성 테스트가
        깨진다(도착 시각이 8분 밀린다).
        """

        fitted = fit_durations_to_budget(_slots(60, 60), overhead_min=15, budget_min=150)

        assert fitted == [60, 60]

    def test_정책_범위를_넘기면서까지_예산을_맞추지_않는다(self) -> None:
        """여유를 다 써도 남는 차이는 그대로 둔다 — "관광지 10분"을 만들지 않는다."""

        fitted = fit_durations_to_budget(_slots(90, 90, 90), overhead_min=30, budget_min=60)

        assert fitted == [60, 60, 60]
        assert all(minutes >= _ATTRACTION.minimum_min for minutes in fitted)

    def test_여유에_비례해_나눠_상대_크기가_유지된다(self) -> None:
        """균등하게 깎으면 "이 곳은 더 오래"라는 판단이 사라진다.

        120/90/60은 줄일 여유가 60/30/0이다. 50분을 줄여야 하므로 여유 비율대로
        34/16/0을 걷는다(정수 나눗셈에서 남는 1분은 여유가 가장 큰 자리로).
        여유가 없는 셋째 자리는 안 줄어들고, 순서는 그대로 남는다.
        """

        fitted = fit_durations_to_budget(_slots(120, 90, 60), overhead_min=30, budget_min=250)

        assert fitted == [86, 74, 60]
        assert fitted[0] > fitted[1] > fitted[2]
        assert sum(fitted) + 30 == 250

    def test_여유를_다_써도_모자라면_전부_최소값까지_간다(self) -> None:
        """줄여야 할 양이 여유와 같거나 크면 상대 크기는 유지되지 않는다 —
        모두 자기 최소값에서 멈추기 때문이다. 이것이 정상이다."""

        fitted = fit_durations_to_budget(_slots(120, 90, 60), overhead_min=30, budget_min=210)

        assert fitted == [60, 60, 60]

    def test_정책이_없는_자리는_조절하지_않는다(self) -> None:
        """부분 재편성에서 사용자가 유지하기로 한 자리(pinned)가 이 경우다."""

        slots = [
            DurationSlot(current_min=90, policy=None),
            DurationSlot(current_min=90, policy=_ATTRACTION),
        ]

        fitted = fit_durations_to_budget(slots, overhead_min=15, budget_min=120)

        assert fitted[0] == 90
        assert fitted[1] == 60

    def test_시간을_말하지_않았으면_그대로_둔다(self) -> None:
        assert fit_durations_to_budget(_slots(90, 90), overhead_min=15, budget_min=None) == [
            90,
            90,
        ]

    def test_조절할_자리가_없으면_그대로_둔다(self) -> None:
        assert fit_durations_to_budget([], overhead_min=0, budget_min=180) == []
