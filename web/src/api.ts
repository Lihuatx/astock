import type { Alert, Overview, ResearchBundle, ResearchSummary, ReviewBundle } from "./types";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`接口请求失败：${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/api/v1/overview"),
  reviews: () => request<Array<Record<string, string>>>("/api/v1/reviews"),
  review: (id: string) => request<ReviewBundle>(`/api/v1/reviews/${encodeURIComponent(id)}`),
  health: () => request<{ sources: Overview["live_status"]; alerts: Alert[] }>("/api/v1/health"),
  alerts: () => request<Alert[]>("/api/v1/alerts"),
  research: () => request<ResearchSummary[]>("/api/v1/research"),
  researchDetail: (id: string) => request<ResearchBundle>(`/api/v1/research/${encodeURIComponent(id)}`),
};
