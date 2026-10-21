import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, streamCoach } from "./api";
import { useT } from "./i18n";
import { runAnalysis } from "./analysisJobs";
import { mergeConversationMessages, positionPly } from "./coachTimeline";
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
    controller.current?.abort();
    setMessages([]);
    setState(null);
  }, [game?.id]);
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
    setMessages((previous) => previous.filter((message) => message.role !== "assistant" || message.content));
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
    if (!game || busy || exploring || (reviewMode && tab !== "coach")) return;
    api<{ messages: ChatMessage[]; state?: CoachingState }>(
      `/games/${game.id}/conversation?timeline=true&fen=${encodeURIComponent(fen)}`,
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
          setMessages((previous) => mergeConversationMessages(previous, result.messages));
        }
      })
      .catch(() => {
        /* Gameplay remains available if saved conversations cannot be loaded. */
      });
    return () => {
      cancelled = true;
    };
  }, [game?.id, game?.revision, fen, exploring, reviewMode, tab, busy]);

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
    if (hintLevel >= 2 || analyzing) return;
    if (!preferences.progressive_hints) {
      setHint(t("hintDisabled"));
      return;
    }
    cancelAnalysis();
    const hintController = new AbortController();
    analysisController.current = hintController;
    const level = Math.min(hintLevel + 1, 2),
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
          game_id: game?.id,
          level,
          language: preferences.coach_language,
          question: [...messages].reverse().find((message) => message.role === "assistant" && message.fen === fen)?.hint_question
            || [...messages].reverse().find((message) => message.role === "user" && message.fen === fen)?.content || "",
          ...budget,
        },
        undefined,
        hintController.signal,
      );
      if (!hintController.signal.aborted && currentFen.current === requested) {
        setHint(result.text || result.hint || "");
        setHintMove(level === 2 ? result.highlight_move || null : null);
        setHintVisual((level === 1 ? result.highlight_square : result.highlight_move) ? {
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
      .map(({ role, content, fen }) => ({ role, content, fen }));
    const userId = `pending-${crypto.randomUUID()}`, answerId = `pending-${crypto.randomUUID()}`;
    const ply = positionPly(game, fen);
    setQuestion("");
    setHint("");
    setHintMove(null);
    setHintVisual(null);
    setHintLevel(0);
    setError(null);
    setBusy(true);
    setMessages((m) => [
      ...m,
      { id: userId, role: "user", content: text, fen, ply, timeline_revision: game?.revision },
      { id: answerId, role: "assistant", content: "", fen, ply, timeline_revision: game?.revision },
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
          if (abort.signal.aborted || currentFen.current !== requested) return;
          const content = String(data.text || data.content || "");
          if (event === "done" && data.state)
            setState(data.state as CoachingState);
          if (event === "error") {
            setError(new Error(String(data.message || data.detail || content)));
            return;
          }
          if (event === "token" || event === "message" || event === "done")
            setMessages((messages) => messages.map((message) => {
              if (message.id === userId && typeof data.user_message_id === "string")
                return { ...message, id: data.user_message_id, created_at: String(data.user_created_at || "") };
              if (message.id !== answerId) return message;
              return {
                  ...message,
                  ...(event === "done"
                    ? {
                        id: typeof data.message_id === "string" ? data.message_id : message.id,
                        created_at: String(data.created_at || ""),
                        hint_question: typeof data.hint_question === "string" ? data.hint_question : undefined,
                        ply: typeof data.ply === "number" ? data.ply : message.ply,
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
                      : message.content + content,
                  source: String(data.source || message.source || ""),
                  fallback_reason:
                    typeof data.fallback_reason === "string"
                      ? data.fallback_reason
                      : message.fallback_reason,
                };
            }));
          else if (event === "status" && data.source)
            setMessages((m) =>
              m.map((v) =>
                v.id === answerId ? { ...v, source: String(data.source) }
                  : v.id === userId && typeof data.user_message_id === "string" ? { ...v, id: data.user_message_id } : v,
              ),
            );
        },
        abort.signal,
      );
    } catch (e) {
      if (!abort.signal.aborted && currentFen.current === requested)
        setError(e);
    } finally {
      if (controller.current === abort && currentFen.current === requested) setBusy(false);
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
