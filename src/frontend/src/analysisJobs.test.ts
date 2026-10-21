import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runAnalysis } from "./analysisJobs";
beforeEach(() => vi.stubGlobal("localStorage", { getItem: () => null }));
afterEach(() => vi.unstubAllGlobals());
describe("practice move comparison", () => {
  it("requests three practice candidates even with the beginner one-candidate budget", async () => {
    const analysis = {
      fen: "position",
      candidates: [
        { uci: "e2e4", san: "e4", cp: 20, mate: null, pv: ["e4"] },
        { uci: "a2a3", san: "a3", cp: -30, mate: null, pv: ["a3"] },
        { uci: "h2h4", san: "h4", cp: -80, mate: null, pv: ["h4"] },
      ],
    };
    const fetch = vi.fn(async (_url: string, _options: RequestInit) =>
      new Response(JSON.stringify(analysis)),
    );
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const onJob = vi.fn();

    await expect(
      runAnalysis(
        "position",
        { time_ms: 350, depth: 12, candidates: 1 },
        "quick",
        controller.signal,
        onJob,
      ),
    ).resolves.toEqual(analysis);

    expect(fetch).toHaveBeenCalledOnce();
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("/api/analysis");
    expect(JSON.parse(String(options.body))).toEqual({
      fen: "position",
      time_ms: 350,
      depth: 12,
      mode: "quick",
      candidates: 3,
      candidate_selection: "practice",
    });
    expect(options.signal).toBe(controller.signal);
    expect(onJob).not.toHaveBeenCalled();
  });
});
describe("cancellable deep analysis", () => {
  it("cancels the server job even when the player leaves before creation returns its identity", async () => {
    let release: (response: Response) => void = () => undefined;
    const created = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const requests: { url: string; method: string }[] = [];
    let creationBody: unknown;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options: RequestInit) => {
        requests.push({ url, method: options.method || "GET" });
        if (options.method === "POST") {
          creationBody = JSON.parse(String(options.body));
          return created;
        }
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
    expect(creationBody).toEqual({
      fen: "position",
      time_ms: 5000,
      mode: "deep",
      candidates: 3,
    });
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
