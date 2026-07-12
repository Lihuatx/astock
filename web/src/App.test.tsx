import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { expect, test } from "vitest";
import App from "./App";

vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ bundle: null, live_status: [], alerts: [] }) })));

test("renders private observer overview", async () => {
  render(<MemoryRouter><App /></MemoryRouter>);
  expect(screen.getByText("运行总览")).toBeTruthy();
  expect(await screen.findByText("尚未接收到 ReviewBundle")).toBeTruthy();
  expect(screen.getAllByText(/不构成投资建议/).length).toBeGreaterThan(0);
});
