import { useT, type TranslationKey } from "./i18n";
import { ChessText } from "./ChessText";
import { ExplanationText } from "./ExplanationText";
import { Spinner } from "./components";
import { VisualExplanation } from "./VisualExplanation";
import type {
  Candidate,
  ChatMessage,
  Preferences,
  VisualInsight,
} from "./types";
const fallbackLabels: Record<string, TranslationKey> = {
  not_configured: "coachNotConfigured",
  timeout: "coachTimeout",
  authentication: "coachAuthentication",
  tls_certificate: "coachCertificate",
  connection: "coachConnection",
  server_error: "coachServerError",
  busy: "coachBusy",
  invalid_response: "coachInvalidResponse",
};
export function CoachMessages({
  messages,
  busy,
  fen,
  preferences,
  onVisual,
  onPreview,
  activeVisual,
  onResolve,
}: {
  messages: ChatMessage[];
  busy: boolean;
  fen: string;
  preferences: Preferences;
  onVisual: (insight: VisualInsight) => void;
  activeVisual?: VisualInsight | null;
  onResolve: (uci: string) => void;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  return (
    <>
      {messages.map((m, i) => (
        <div className={`chat-message ${m.role}`} key={i}>
          <span>
            {m.role === "user" ? t("you") : t("coach")}
            {m.fen !== fen && <small> · {t("viewing")}</small>}
          </span>
          <ExplanationText
            mode={
              m.role === "assistant" ? preferences.explanation_mode : "text"
            }
          >
            <p>
              {m.content ? <ChessText text={m.content} fen={m.fen || fen} coaching={m} onVisual={onVisual} activeVisual={activeVisual} /> :
                (busy && i === messages.length - 1 ? (
                  <Spinner
                    label={t(
                      m.source === "analyzing" ? "thinking" : "coachThinking",
                    )}
                  />
                ) : (
                  t("offline")
                ))}
            </p>
          </ExplanationText>
          {m.role === "assistant" &&
            preferences.explanation_mode !== "text" && (
              <VisualExplanation
                coaching={m}
                onVisual={onVisual}
                onPreview={onPreview}
              />
            )}
          {m.fen === fen &&
            m.ambiguous_moves?.map((reference) => (
              <div
                className="visual-explanation-actions"
                key={reference.reference}
              >
                <span>
                  {reference.reference} · {t("selectIntendedPiece")}
                </span>
                {reference.choices.map((choice) => (
                  <button
                    className="outline-button"
                    key={choice.uci}
                    disabled={busy}
                    onPointerEnter={() =>
                      onVisual({
                        id: choice.uci,
                        text: `${choice.san}: ${choice.from} → ${choice.to}`,
                        fen,
                        squares: [choice.from, choice.to],
                        arrows: [{ from: choice.from, to: choice.to }],
                      })
                    }
                    onClick={() => onResolve(choice.uci)}
                  >
                    {choice.san} · {choice.from} → {choice.to}
                  </button>
                ))}
              </div>
            ))}
          {m.source &&
            !["analyzing", "explaining"].includes(m.source) &&
            m.role === "assistant" && (
              <small className="message-source">
                {[
                  "llm",
                  "local_llm_verified",
                  "local_llm_grounded_corrected",
                ].includes(m.source)
                  ? t("sourceLlm")
                  : t("sourceFallback")}
                {m.fallback_reason &&
                  ` · ${t(fallbackLabels[m.fallback_reason] || "coachInvalidResponse")}`}
              </small>
            )}
        </div>
      ))}
    </>
  );
}
