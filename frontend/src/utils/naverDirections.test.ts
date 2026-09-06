import { describe, expect, it, vi } from "vitest";

import { buildNaverDirections, openNaverDirections, openNaverMapSearch } from "./naverDirections";

describe("buildNaverDirections", () => {
  it("출발·도착 좌표로 대중교통 앱 딥링크와 웹 폴백을 만든다", () => {
    const urls = buildNaverDirections({
      deviceLocation: "37.5665,126.9780",
      destLat: 37.5796,
      destLng: 126.977,
      destName: "경복궁",
    });

    expect(urls).not.toBeNull();
    expect(urls?.appUrl).toContain("nmap://route/public");
    expect(urls?.appUrl).toContain("slat=37.5665");
    expect(urls?.appUrl).toContain("slng=126.978");
    expect(urls?.appUrl).toContain("dlat=37.5796");
    expect(urls?.appUrl).toContain("dlng=126.977");
    // 출발점 라벨 "내 위치"(인코딩)
    expect(urls?.appUrl).toContain(`sname=${encodeURIComponent("내 위치")}`);
    // appname은 호출 호스트명(jsdom: localhost)
    expect(urls?.appUrl).toContain("appname=localhost");
    // 웹 폴백은 경도,위도 순 + 대중교통
    expect(urls?.webUrl).toContain("map.naver.com/p/directions");
    expect(urls?.webUrl).toContain("/-/transit");
  });

  it("도보 모드는 앱·웹 모두 walk로 연다 — 화장실처럼 걸어가는 목적지용", () => {
    const urls = buildNaverDirections({
      deviceLocation: "37.5739,126.9852",
      destLat: 37.5743,
      destLng: 126.9856,
      destName: "인사동마루 신관 개방화장실",
      mode: "walk",
    });

    expect(urls?.appUrl).toContain("nmap://route/walk");
    expect(urls?.webUrl).toContain("/-/walk");
    expect(urls?.webUrl).not.toContain("/-/transit");
  });

  it("mode를 생략하면 기존 동작인 대중교통을 유지한다", () => {
    const urls = buildNaverDirections({
      deviceLocation: "37.5,127.0",
      destLat: 37.6,
      destLng: 127.1,
      destName: "장소",
    });

    expect(urls?.appUrl).toContain("nmap://route/public");
    expect(urls?.webUrl).toContain("/-/transit");
  });

  it("장소명을 URL 인코딩해 링크가 깨지지 않게 한다", () => {
    const urls = buildNaverDirections({
      deviceLocation: "37.5,127.0",
      destLat: 37.6,
      destLng: 127.1,
      destName: "카페 & 정원",
    });

    // 공백·&가 그대로 들어가면 뒤 파라미터가 잘린다 → 인코딩 확인
    expect(urls?.appUrl).toContain(encodeURIComponent("카페 & 정원"));
    expect(urls?.appUrl).not.toContain("dname=카페 & 정원");
  });

  it.each(["", "abc", "37.5", "37.5,127.0,1", "37.5,nope"])(
    "출발 좌표가 잘못되면 null (%s)",
    (bad) => {
      expect(
        buildNaverDirections({
          deviceLocation: bad,
          destLat: 37.6,
          destLng: 127.1,
          destName: "장소",
        }),
      ).toBeNull();
    },
  );
});

describe("openNaverDirections (데스크톱)", () => {
  it("데스크톱(jsdom)에서는 웹 길찾기를 새 탭으로 연다", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    const ok = openNaverDirections({
      deviceLocation: "37.5,127.0",
      destLat: 37.6,
      destLng: 127.1,
      destName: "장소",
    });

    expect(ok).toBe(true);
    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining("map.naver.com/p/directions"),
      "_blank",
      "noopener",
    );
    openSpy.mockRestore();
  });

  it("출발 좌표가 없으면 아무것도 열지 않고 false", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    expect(
      openNaverDirections({ deviceLocation: "", destLat: 37.6, destLng: 127.1, destName: "장소" }),
    ).toBe(false);
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("openNaverMapSearch", () => {
  it("주소만으로 네이버지도 검색을 연다 — 이름을 함께 넘기면 검색이 안 된다(2026-09-02 실사용)", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    expect(openNaverMapSearch("서울특별시 종로구 세종대로 189")).toBe(true);
    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining("map.naver.com/p/search/"),
      "_blank",
      "noopener",
    );
    expect(openSpy.mock.calls[0]?.[0]).toBe(
      `https://map.naver.com/p/search/${encodeURIComponent("서울특별시 종로구 세종대로 189")}`,
    );
    openSpy.mockRestore();
  });

  it("주소가 없으면 지도를 열지 않는다", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    expect(openNaverMapSearch("   ")).toBe(false);
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});
