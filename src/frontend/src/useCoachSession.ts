import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, streamCoach } from "./api";
import { useT } from "./i18n";
import { runAnalysis } from "./analysisJobs";
import type {
  Analysis,
  ChatMessage,
  Game,
  Preferences,
  VisualInsight,
  VisualCoaching,
  CoachingState,
} from "./types";
export function useCoachSession({
  fen,
  game,
  preferences,
  exploring,
  reviewMode,
  tab,
  positionPending,
  onAnalysis,
}: {
  fen: string;
  game: Game | null;
  preferences: Preferences;
  exploring: boolean;
  reviewMode: boolean;
  tab: string;
  positionPending: boolean;
  onAnalysis: (analysis: Analysis) => void;
}) {
  const t = useT(),
    [messages, setMessages] = useState<ChatMessage[]>([]),
    [question, setQuestion] = useState(""),
    [busy, setBusy] = useState(false),
    [analyzing, setAnalyzing] = useState(false),
    [showCandidates, setShowCandidates] = useState(false),
    [hintLevel, setHintLevel] = useState(0),
    [hint, setHint] = useState(""),
    [hintMove, setHintMove] = useState<string | null>(null),
    [hintVisual, setHintVisual] = useState<VisualCoaching | null>(null),
    [calculating, setCalculating] = useState(false),
    [error, setError] = useState<unknown>(null),
    [teachingMode, setTeachingMode] = useState<"guided" | "direct">(
      preferences.guided_questions ? "guided" : "direct",
    ),
    [state, setState] = useState<CoachingState | null>(null);
  const analysisController = useRef<AbortController | null>(null);
  const analysisJob = useRef<string | null>(null);
  function cancelAnalysis() {
    analysisController.current?.abort();
    const id = analysisJob.current;
    analysisJob.current = null;
    if (id)
      void api(`/analysis/jobs/${id}`, undefined, "DELETE").catch(
        () => undefined,
      );
    setAnalyzing(false);
  }
  const controller = useRef<AbortController | null>(null),
    currentFen = useRef(fen),
    scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    currentFen.current = fen;
    controller.current?.abort();
    cancelAnalysis();
    setState(null);
    setBusy(false);
    setAnalyzing(false);
    setShowCandidates(false);
    setHint("");
    setHintMove(null);
    setHintVisual(null);
    setCalculating(false);
    setHintLevel(0);
    setError(null);
  }, [fen]);
  useEffect(
    () => () => {
      controller.current?.abort();
      cancelAnalysis();
    },
    [],
  );
  useEffect(() => {
    let cancelled = false;
    if (!game || exploring || (reviewMode && tab !== "coach")) return;
    api<{ messages: ChatMessage[]; state?: CoachingState }>(
      `/games/${game.id}/conversation?fen=${encodeURIComponent(fen)}`,
    )
      .then((result) => {
        if (!cancelled && currentFen.current === fen) {
          if (result.state) {
            setState(result.state);
            if (
              result.state.mode === "guided" ||
              result.state.mode === "direct"
            )
              setTeachingMode(result.state.mode);
          }
          setMessages((previous) =>
            previous.some((m) => m.fen === fen)
              ? previous
              : [...previous, ...result.messages],
          );
        }
      })
      .catch(() => {
        /* Gameplay remains available if saved conversations cannot be loaded. */
      });
    return () => {
      cancelled = true;
    };
  }, [game?.id, fen, exploring, reviewMode, tab]);

  useLayoutEffect(() => {
    const container = scroll.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, busy, hint, game?.revision, fen]);
  const budget = {
    time_ms: preferences.analysis_time_ms,
    depth: preferences.analysis_depth,
    candidates: preferences.candidate_count,
  };
  async function compare(mode: "quick" | "deep" = "quick") {
    cancelAnalysis();
    const requested = fen;
    const controller = new AbortController();
    analysisController.current = controller;
    setAnalyzing(true);
    setError(null);
    try {
      const result = await runAnalysis(
        fen,
        mode === "deep"
          ? { ...budget, time_ms: preferences.deep_analysis_time_ms || 5000 }
          : budget,
        mode,
        controller.signal,
        (id) => {
          if (
            analysisController.current === controller &&
            !controller.signal.aborted
          )
            analysisJob.current = id;
          else
            void api(`/analysis/jobs/${id}`, undefined, "DELETE").catch(
              () => undefined,
            );
        },
      );
      if (
        !controller.signal.aborted &&
        currentFen.current === requested &&
        result.fen === requested
      ) {
        onAnalysis(result);
        setShowCandidates(true);
      }
    } catch (failure) {
      if (
        !controller.signal.aborted &&
        currentFen.current === requested &&
        !(failure instanceof DOMException && failure.name === "AbortError")
      )
        setError(failure);
    } finally {
      if (analysisController.current === controller) {
        analysisJob.current = null;
        if (currentFen.current === requested) setAnalyzing(false);
      }
    }
  }
  async function requestHint() {
    if (!preferences.progressive_hints) {
      setHint(t("hintDisabled"));
      return;
    }
    cancelAnalysis();
    const hintController = new AbortController();
    analysisController.current = hintController;
    const level = Math.min(hintLevel + 1, 4),
      requested = fen;
    setAnalyzing(true);
    try {
      const result = await api<
        {
          text?: string;
          hint?: string;
          fen?: string;
          highlight_move?: string;
          highlight_square?: string;
        } & VisualCoaching
      >(
        "/hint",
        {
          fen,
          level,
          language: preferences.coach_language,
          ...budget,
        },
        undefined,
        hintController.signal,
      );
      if (!hintController.signal.aborted && currentFen.current === requested) {
        setHint(result.text || result.hint || "");
        setHintMove(level >= 3 ? result.highlight_move || null : null);
        setHintVisual(level >= 3 ? result : (level === 1 ? result.highlight_square : result.highlight_move) ? {
          insights: [{
            id: "hint-guide",
            fen: requested,
            text: result.text || result.hint || "",
            squares: level === 1 && result.highlight_square ? [result.highlight_square] : [],
            arrows: level === 2 && result.highlight_move ? [{
              from: result.highlight_move.slice(0, 2),
              to: result.highlight_move.slice(2, 4),
              color: "#378466",
            }] : [],
          }],
        } : null);
        setHintLevel(level);
        if (level === 4) await compare();
      }
    } catch (e) {
      if (!hintController.signal.aborted && currentFen.current === requested)
        setError(e);
    } finally {
      if (
        analysisController.current === hintController &&
        currentFen.current === requested
      )
        setAnalyzing(false);
    }
  }
  async function send(text = question) {
    if (!text.trim() || busy || positionPending) return;
    const requested = fen;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const history = messages
      .filter((m) => m.fen === fen)
      .slice(-10)
      .map(({ role, content }) => ({ role, content }));
    setQuestion("");
    setError(null);
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", content: text, fen },
      { role: "assistant", content: "", fen },
    ]);
    try {
      await streamCoach(
        {
          fen,
          ...budget,
          question: text,
          game_id: game?.id,
          revision: game?.revision,
          explore: exploring,
          language: preferences.coach_language,
          history,
          teaching_mode: teachingMode,
        },
        (event, data) => {
          if (currentFen.current !== requested) return;
          const content = String(data.text || data.content || "");
          if (event === "done" && data.state)
            setState(data.state as CoachingState);
          if (event === "error") {
            setError(new Error(String(data.message || data.detail || content)));
            return;
          }
          if (event === "token" || event === "message" || event === "done")
            setMessages((m) => {
              const last = m[m.length - 1];
              if (last?.role !== "assistant" || last.fen !== requested)
                return m;
              return [
                ...m.slice(0, -1),
                {
                  ...last,
                  ...(event === "done"
                    ? {
                        ambiguous_moves:
                          data.ambiguous_moves as ChatMessage["ambiguous_moves"],
                        insights: data.insights as VisualInsight[] | undefined,
                        variations:
                          data.variations as ChatMessage["variations"],
                      }
                    : {}),
                  content:
                    event === "done" && content
                      ? content
                      : last.content + content,
                  source: String(data.source || last.source || ""),
                  fallback_reason:
                    typeof data.fallback_reason === "string"
                      ? data.fallback_reason
                      : last.fallback_reason,
                },
              ];
            });
          else if (event === "status" && data.source)
            setMessages((m) =>
              m.map((v, i) =>
                i === m.length - 1 ? { ...v, source: String(data.source) } : v,
              ),
            );
        },
        abort.signal,
      );
    } catch (e) {
      if (!abort.signal.aborted && currentFen.current === requested)
        setError(e);
    } finally {
      if (currentFen.current === requested) setBusy(false);
    }
  }
  return {
    messages,
    question,
    setQuestion,
    busy,
    analyzing,
    showCandidates,
    hintLevel,
    hint,
    hintMove,
    hintVisual,
    calculating,
    setCalculating,
    error,
    setError,
    scroll,
    compare,
    requestHint,
    send,
    cancelAnalysis,
    teachingMode,
    setTeachingMode,
    state,
  };
}
