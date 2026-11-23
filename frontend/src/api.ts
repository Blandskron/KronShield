import { useInfiniteQuery } from "@tanstack/react-query";
import type { components } from "./api.generated";

export type Models = components["schemas"];
export type Page<T> = { items: T[]; next_cursor: string | null };

export class ApiError extends Error {
  constructor(readonly status: number, readonly code = "request_failed") {
    super("API " + status);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api/v1" + path, { ...init, credentials: "same-origin" });
  if (!response.ok) {
    const result = await response.json().catch(() => null) as { code?: string } | null;
    throw new ApiError(response.status, result?.code);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export async function listOptions<T>(path: string, filters: Record<string, string>, signal: AbortSignal): Promise<T[]> {
  const params = new URLSearchParams({ ...filters, limit: "100" });
  const items: T[] = [];
  const cursors = new Set<string>();
  for (;;) {
    const page = await api<Page<T>>(path + "?" + params, { signal });
    items.push(...page.items);
    if (!page.next_cursor) return items;
    if (cursors.has(page.next_cursor)) throw new Error("Repeated page cursor");
    cursors.add(page.next_cursor);
    params.set("after", page.next_cursor);
  }
}

export function usePages<T>(user: string, org: string, project: string, segment: string) {
  return useInfiniteQuery({
    queryKey: ["project-data", user, org, project, segment],
    enabled: Boolean(project),
    initialPageParam: "",
    queryFn: ({ signal, pageParam }) => {
      const params = new URLSearchParams({ org_id: org, limit: "25" });
      if (pageParam) params.set("after", pageParam);
      return api<Page<T>>("/projects/" + project + "/" + segment + "?" + params, { signal });
    },
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}
