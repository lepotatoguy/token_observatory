import { describe, expect, it } from "vitest";
import { DEV_API_TARGET, devProxyOrigin } from "./devProxy";

describe("development API proxy", () => {
  it("forwards the dev page's own origin to the backend origin", () => {
    expect(devProxyOrigin("http://127.0.0.1:5173", "127.0.0.1:5173")).toBe(
      DEV_API_TARGET,
    );
    expect(devProxyOrigin("http://localhost:5173", "localhost:5173")).toBe(
      DEV_API_TARGET,
    );
  });
  it("preserves foreign and missing origins for backend security checks", () => {
    expect(devProxyOrigin("https://foreign.example", "127.0.0.1:5173")).toBe(
      "https://foreign.example",
    );
    expect(devProxyOrigin("null", "127.0.0.1:5173")).toBe("null");
    expect(devProxyOrigin(undefined, "127.0.0.1:5173")).toBeUndefined();
  });
});
