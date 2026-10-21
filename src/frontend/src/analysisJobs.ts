import { api } from "./api";
import type { Analysis } from "./types";
export interface AnalysisJob<T = Analysis> {
  id: string;
  status: string;
  fen: string;
  result?: T;
  progress?: Record<string, unknown>;
  error?: string;
}
export async function runAnalysis(
  fen: string,
  budget: Record<string, unknown>,
  mode: "quick" | "deep",
  signal: AbortSignal,
  onJob: (id: string) => void,
): Promise<Analysis> {
  if (mode === "quick")
    return api<Analysis>(
      "/analysis",
      { fen, ...budget, mode, candidates: 3, candidate_selection: "practice" },
      undefined,
      signal,
    );
  // Obtain the job identity even if the user leaves while the creation response is in flight.
  const job = await api<AnalysisJob>("/analysis/jobs", {
    fen,
    ...budget,
    mode: "deep",
    time_ms: Math.max(5000, Number(budget.time_ms) || 5000),
    candidates: 3,
  });
  onJob(job.id);
  if (signal.aborted) {
    await api(`/analysis/jobs/${job.id}`, undefined, "DELETE");
    throw new DOMException("Canceled", "AbortError");
  }
  return pollAnalysisJob<Analysis>(job.id, signal);
}
export async function pollAnalysisJob<T>(
  id: string,
  signal: AbortSignal,
  onProgress?: (progress?: Record<string, unknown>) => void,
): Promise<T> {
  while (!signal.aborted) {
    const state = await api<AnalysisJob<T>>(
      `/analysis/jobs/${id}`,
      undefined,
      undefined,
      signal,
    );
    onProgress?.(state.progress);
    if (state.status === "completed" && state.result) return state.result;
    if (state.status === "failed")
      throw new Error(state.error || "Analysis failed");
    if (state.status === "cancelled")
      throw new DOMException("Canceled", "AbortError");
    await new Promise<void>((resolve, reject) => {
      const cancel = () => {
        clearTimeout(timer);
        reject(new DOMException("Canceled", "AbortError"));
      };
      const timer = setTimeout(() => {
        signal.removeEventListener("abort", cancel);
        resolve();
      }, 300);
      signal.addEventListener("abort", cancel, { once: true });
    });
  }
  throw new DOMException("Canceled", "AbortError");
}
