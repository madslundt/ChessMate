import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { pollAnalysisJob } from "./analysisJobs";
import { useT } from "./i18n";
import type { Game, Preferences } from "./types";
interface Result {
  revision: number;
  next_ply: number;
  total: number;
  complete: boolean;
  critical_verified: number;
}
/** Cancellable game analysis resumes bounded jobs, preserving the authoritative revision between them. */
export function useFullGameAnalysis(
  game: Game | null,
  preferences: Preferences,
  onError: (error: unknown) => void,
) {
  const client = useQueryClient();
  const t = useT();
  const [analyzingGame, setAnalyzingGame] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState("");
  const controller = useRef<AbortController | null>(null);
  const activeJob = useRef<string | null>(null);
  function cancel() {
    controller.current?.abort();
    const id = activeJob.current;
    activeJob.current = null;
    setAnalyzingGame(false);
    if (id)
      void api(`/analysis/jobs/${id}`, undefined, "DELETE").catch(
        () => undefined,
      );
  }
  useEffect(() => () => cancel(), []);
  async function analyzeGame() {
    if (!game || analyzingGame) return;
    const abort = new AbortController();
    controller.current = abort;
    setAnalyzingGame(true);
    onError(null);
    let revision = game.revision,
      start = 0;
    try {
      while (!abort.signal.aborted) {
        const job = await api<{ id: string }>(
          `/games/${game.id}/analysis-jobs`,
          {
            revision,
            start_ply: start,
            time_ms: Math.min(500, preferences.analysis_time_ms),
            critical_time_ms: preferences.deep_analysis_time_ms || 5000,
            refresh: false,
          },
        );
        if (controller.current !== abort || abort.signal.aborted) {
          await api(`/analysis/jobs/${job.id}`, undefined, "DELETE");
          break;
        }
        activeJob.current = job.id;
        let published = start;
        const result = await pollAnalysisJob<Result>(
          job.id,
          abort.signal,
          (progress) => {
            if (!progress || abort.signal.aborted) return;
            const completed = Number(progress.completed ?? start);
            if (completed - published >= 8) {
              published = completed;
              void client.invalidateQueries({ queryKey: ["game", game.id] });
              void client.invalidateQueries({
                queryKey: ["game-review", game.id],
              });
            }
            setAnalysisProgress(
              `${progress.completed ?? start} / ${progress.total ?? game.moves.length} · ${t("criticalVerified")}: ${progress.critical_verified ?? 0}`,
            );
          },
        );
        if (abort.signal.aborted || controller.current !== abort) break;
        activeJob.current = null;
        revision = result.revision;
        setAnalysisProgress(
          `${result.next_ply} / ${result.total} · ${t("criticalVerified")}: ${result.critical_verified}`,
        );
        if (result.complete) break;
        if (result.next_ply <= start) throw new Error(t("analysisNoProgress"));
        start = result.next_ply;
      }
    } catch (failure) {
      if (!abort.signal.aborted) onError(failure);
    } finally {
      if (controller.current === abort) {
        activeJob.current = null;
        setAnalyzingGame(false);
      }
      void client.invalidateQueries({ queryKey: ["game", game.id] });
      void client.invalidateQueries({ queryKey: ["game-review", game.id] });
      void client.invalidateQueries({ queryKey: ["games"] });
    }
  }
  return {
    analyzingGame,
    analysisProgress,
    analyzeGame,
    cancelAnalysis: cancel,
  };
}
