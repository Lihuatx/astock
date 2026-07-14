import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { expect, test } from "vitest";
import App from "./App";

vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
  ok: true,
  json: async () => String(input).includes("/api/v1/research")
    ? []
    : ({ bundle: null, live_status: [], alerts: [], research: [] }),
})));

test("renders private observer overview", async () => {
  render(<MemoryRouter><App /></MemoryRouter>);
  expect(screen.getByText("运行总览")).toBeTruthy();
  expect(await screen.findByText(/尚未接收到 ReviewBundle/)).toBeTruthy();
  expect(screen.getAllByText(/不构成投资建议/).length).toBeGreaterThan(0);
});

test.each([
  ["/trade-plan", "明日交易计划"],
  ["/account", "账户总览"],
  ["/execution", "当日执行复盘"],
  ["/research", "研究报告库"],
  ["/system", "系统运行状态"],
])("renders route %s", async (path, title) => {
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
  expect(screen.getByText(title)).toBeTruthy();
});
