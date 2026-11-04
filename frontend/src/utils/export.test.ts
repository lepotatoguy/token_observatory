import { it, expect } from "vitest";
import { buildCsvRows, csv, buildJsonPayload } from "./export";
import { chat, snapshot, now } from "../test/fixtures";
it("protects CSV cells from formulas, retains BOM and session identity", () => {
  const output = csv([chat({ title: "=1+1", session_id: "-danger" })]);
  expect(output.startsWith("\ufeff")).toBe(true);
  expect(output).toContain('"\'=1+1"');
  expect(output).toContain('"\'-danger"');
  expect(buildCsvRows([chat()])[0]).toContain("session_id");
  expect(buildCsvRows([chat()])[0]).not.toContain("project");
});
it("leaves missing token fields blank without inventing zeros", () => {
  expect(
    buildCsvRows([chat({ usage_source: "unavailable" })])[1].slice(4, 10),
  ).toEqual(["", "", "", "", "", ""]);
  const row = buildCsvRows([chat({ cache_unreported: true })])[1];
  expect(row[5]).toBe("");
  expect(row[6]).toBe("");
  expect(row[4]).toBe(1000);
});
it("builds JSON metadata and filtered totals without including unselected source sessions", () => {
  const selected = chat(),
    data = snapshot({
      sessions: [selected, chat({ id: "secret", title: "Not selected" })],
      accounting_version: 2,
    }),
    payload = buildJsonPayload(data, [selected], {
      provider: "claude",
      range: "all",
      day: null,
      agentsIncluded: false,
      search: "Alpha",
      historyDay: "2024-01-01",
      now,
    });
  expect(payload.sessions).toHaveLength(1);
  expect(payload.sessions[0]).toMatchObject({
    filtered_totals: selected.scope,
  });
  expect(payload.sessions[0]).not.toHaveProperty("scope");
  expect(payload.filters).toMatchObject({
    provider: "claude",
    search: "Alpha",
    include_subagents: false,
    saved_day: "2024-01-01",
  });
  expect(payload.accounting_version).toBe(2);
  expect(payload).not.toHaveProperty("providers");
});
