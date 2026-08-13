import { beforeEach, expect, test, vi } from "vitest";
import { getBrowserDeviceLocation } from "./geolocation";

beforeEach(() => {
  vi.unstubAllEnvs();
});

test("uses configured local test coordinates without requesting browser permission", async () => {
  vi.stubEnv("VITE_TEST_DEVICE_LOCATION", "37.5796,126.9769");
  const getCurrentPosition = vi.fn();
  vi.stubGlobal("navigator", { geolocation: { getCurrentPosition } });

  await expect(getBrowserDeviceLocation()).resolves.toBe("37.5796,126.9769");
  expect(getCurrentPosition).not.toHaveBeenCalled();
});
