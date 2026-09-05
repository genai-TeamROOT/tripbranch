/*
 * 역할: 상단 위치 칩이 무엇을 몇 칸으로 보여줄지 정하는 규칙을 검증한다.
 * 호출 시점: vitest 실행 시.
 *
 * **이 파일의 핵심은 "언제 두 칸인가"다.** 하나로 줄이면 카드의 이동시간을 어디서
 * 쟀는지가 화면에서 사라지고(D-067), 늘 두 칸이면 같은 이름을 두 번 쓰는 자리가
 * 생긴다. 그 경계를 여기서 못 박는다.
 */

import { expect, test } from "vitest";
import {
  buildLocationChipModel,
  MAX_CHIP_NAME_LENGTH,
  truncateName,
} from "./locationChip";

test("출발지를 정하지 않으면 기기 좌표에서 출발한다고 말한다", () => {
  /* 출발지가 "없는" 상태는 없다 — 안 정했으면 기기 좌표가 출발지다. */
  const model = buildLocationChipModel({ origin: null, center: "광화문역" });

  expect(model).toMatchObject({
    kind: "pair",
    origin: "현재 위치",
    center: "광화문역",
    isDeviceLocation: true,
    description: "현재 위치에서 출발, 광화문역 주변에서 검색",
  });
});

test("출발지를 따로 정하면 깜빡이는 점 대신 출발지 아이콘을 쓴다", () => {
  /* 그 점의 뜻은 "지금 GPS를 쓰는 중" 하나여야 한다. 사용자가 고른 장소 옆에서
     실시간을 흉내 내면 거기 있는 것처럼 읽힌다. */
  const model = buildLocationChipModel({ origin: "안국역", center: "광화문역" });

  expect(model).toMatchObject({
    kind: "pair",
    origin: "안국역",
    center: "광화문역",
    isDeviceLocation: false,
  });
});

test("출발지와 검색 기준이 같으면 한 칸으로 접는다", () => {
  const model = buildLocationChipModel({ origin: "안국역", center: "안국역" });

  expect(model).toMatchObject({ kind: "single", name: "안국역", isDeviceLocation: false });
});

test("검색 기준을 비워두면 출발지가 검색 중심이 되어 한 칸이 된다", () => {
  /* agent_context/service.py의 사다리와 같은 판단이다 — 검색 기준이 없으면
     출발지가 중심이므로, 두 칸으로 나눠 봐야 같은 이름이 두 번 나온다. */
  const model = buildLocationChipModel({ origin: "안국역", center: null });

  expect(model).toMatchObject({ kind: "single", name: "안국역" });
});

test("아무것도 정하지 않았고 대화도 없으면 현재 위치 한 칸이다", () => {
  const model = buildLocationChipModel({ origin: null, center: null });

  expect(model).toMatchObject({ kind: "single", name: "현재 위치", isDeviceLocation: true });
});

test("설정이 비어 있을 때만 대화가 해석한 위치로 떨어진다", () => {
  /* 대화가 이미 있으면 서버가 그 위치를 들고 있어서 다음 발화도 거기서 찾는다. */
  const fallback = buildLocationChipModel({ origin: null, center: null }, "성수동");
  const setting = buildLocationChipModel({ origin: null, center: "광화문역" }, "성수동");

  expect(fallback).toMatchObject({ kind: "pair", origin: "현재 위치", center: "성수동" });
  expect(setting).toMatchObject({ kind: "pair", center: "광화문역" });
});

test("긴 이름은 잘라도 낭독 문구에는 원래 이름이 남는다", () => {
  /* 화면에서 잘린 이름이 낭독까지 잘리면 그 사용자는 어디인지 알 방법이 없다. */
  const long = "서울특별시립미술관서소문본관";
  const model = buildLocationChipModel({ origin: null, center: long });

  expect(model.kind).toBe("pair");
  if (model.kind !== "pair") return;
  expect(model.center).toBe("서울특별시립미술관서…");
  expect(Array.from(model.center)).toHaveLength(MAX_CHIP_NAME_LENGTH + 1);
  expect(model.description).toContain(long);
});

test("상한 이하면 자르지 않는다", () => {
  expect(truncateName("국립중앙박물관")).toBe("국립중앙박물관");
  expect(truncateName("가".repeat(MAX_CHIP_NAME_LENGTH))).toBe(
    "가".repeat(MAX_CHIP_NAME_LENGTH),
  );
});

test("이모지가 섞인 이름을 반쪽으로 자르지 않는다", () => {
  /* .length는 UTF-16 단위라 이모지 하나가 2로 세어져, 경계에 걸리면 깨진 글자가
     남는다. 코드포인트로 세야 한다. */
  const name = "🎨".repeat(MAX_CHIP_NAME_LENGTH + 2);

  const cut = truncateName(name);

  expect(cut).toBe("🎨".repeat(MAX_CHIP_NAME_LENGTH) + "…");
  expect(cut).not.toContain("�");
});
