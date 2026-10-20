import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runAnalysis } from "./analysisJobs";
beforeEach(() => vi.stubGlobal("localStorage", { getItem: () => null }));
afterEach(() => vi.unstubAllGlobals());
describe("cancellable deep analysis", () => {
  it("cancels the server job even when the player leaves before creation returns its identity", async () => {
    let release: (response: Response) => void = () => undefined;
    const created = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options: RequestInit) => {
        requests.push({ url, method: options.method || "GET" });
        if (options.method === "POST") return created;
        return new Response(
          JSON.stringify({ id: "late-job", status: "cancelled" }),
        );
      }),
    );
    const controller = new AbortController();
    const result = runAnalysis(
      "position",
      { time_ms: 5000 },
      "deep",
      controller.signal,
      () => undefined,
    );
    controller.abort();
    release(
      new Response(
        JSON.stringify({ id: "late-job", status: "queued", fen: "position" }),
      ),
    );
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(requests).toEqual([
      { url: "/api/analysis/jobs", method: "POST" },
      { url: "/api/analysis/jobs/late-job", method: "DELETE" },
    ]);
  });
  it("never returns a result from a cancelled job", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (_url: string, options: RequestInit) =>
          new Response(
            JSON.stringify(
              options.method === "POST"
                ? { id: "cancelled-job", status: "queued", fen: "position" }
                : {
                    id: "cancelled-job",
                    status: "cancelled",
                    fen: "position",
                    result: { fen: "position", candidates: [] },
                  },
            ),
          ),
      ),
    );
    await expect(
      runAnalysis(
        "position",
        {},
        "deep",
        new AbortController().signal,
        () => undefined,
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
