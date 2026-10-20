import { Modal } from "./components";
import { CandidateDetails, equivalentCandidate } from "./CandidateDetails";
import { PositionalInsights } from "./PositionalInsights";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { ExplanationText } from "./ExplanationText";
import { lazy, Suspense, useState } from "react";
const CandidateComparison = lazy(() =>
  import("./CandidateComparison").then((module) => ({
    default: module.CandidateComparison,
  })),
);
import { ChevronRight } from "lucide-react";
import { evaluationText } from "./Board";
import { useT } from "./i18n";
import { VisualExplanation } from "./VisualExplanation";
import type {
  Analysis,
  Candidate,
  Color,
  Preferences,
  VisualInsight,
} from "./types";
export function CandidateList({
  orientation,
  analysis,
  fen,
  preferences,
  highlightedMove,
  onHoverMove,
  onToggleMove,
  onPreview,
  onVisual,
}: {
  orientation?: Color;
  analysis: Analysis;
  fen: string;
  preferences: Preferences;
  highlightedMove?: string | null;
  onHoverMove: (uci: string | null) => void;
  onToggleMove: (uci: string) => void;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
  onVisual: (insight: VisualInsight) => void;
}) {
  const t = useT();
  const [comparing, setComparing] = useState(false);
  return (
    <div className="candidate-list">
      <small className="muted">
        {t(fen.split(" ")[1] === "w" ? "white" : "black")} {t("sideToMove")}
      </small>
      <ConfidenceBadge mode={analysis.mode} confidence={analysis.confidence} />
      {analysis.candidates.length > 1 && (
        <button
          className="outline-button"
          aria-expanded={comparing}
          onClick={() => setComparing(!comparing)}
        >
          {t("comparePositions")}
        </button>
      )}
      {comparing && (
        <Modal
          title={t("comparePositions")}
          onClose={() => setComparing(false)}
        >
          <Suspense fallback={null}>
            <CandidateComparison
              base={fen}
              candidates={analysis.candidates}
              preferences={preferences}
              orientation={orientation || preferences.player_color}
              onPreview={(candidate, base) => {
                setComparing(false);
                onPreview(candidate, base);
              }}
            />
          </Suspense>
        </Modal>
      )}
      <PositionalInsights
        analysis={analysis}
        preferences={preferences}
        onVisual={onVisual}
        onPreview={onPreview}
      />
      {!analysis.candidates.length && <p>{t("noCandidates")}</p>}
      {analysis.candidates.map((c, i) => (
        <div className="candidate" key={c.uci}>
          <button
            className={`candidate-title${highlightedMove === c.uci ? " is-highlighted" : ""}`}
            aria-pressed={highlightedMove === c.uci}
            onPointerEnter={() => onHoverMove(c.uci)}
            onPointerLeave={() => onHoverMove(null)}
            onClick={() => onToggleMove(c.uci)}
          >
            <span className="candidate-rank">{i + 1}</span>
            <strong>{c.san}</strong>
            {preferences.show_evaluation && (
              <span className="eval-score">{evaluationText(c.cp, c.mate)}</span>
            )}
          </button>
          {preferences.explanation_mode !== "text" && (
            <VisualExplanation
              coaching={{ insights: c.insights }}
              onVisual={onVisual}
              onPreview={onPreview}
            />
          )}
          <ExplanationText mode={preferences.explanation_mode}>
            <p>
              {c.explanation || c.idea || `${t("candidatePreview")}: ${c.san}`}
            </p>
          </ExplanationText>
          {preferences.show_pv && (
            <>
              <code>{c.pv?.slice(0, 6).join(" ")}</code>
            </>
          )}
          <CandidateDetails
            candidate={c}
            preferences={preferences}
            similar={i > 0 && equivalentCandidate(c, analysis.candidates[0])}
          />
          {preferences.show_evaluation &&
            i > 0 &&
            !equivalentCandidate(c, analysis.candidates[0]) &&
            c.cp !== null &&
            analysis.candidates[0].cp !== null && (
              <small className="muted">
                Δ {((c.cp - analysis.candidates[0].cp) / 100).toFixed(2)}
              </small>
            )}
          <button className="text-button" onClick={() => onPreview(c)}>
            {t("candidatePreview")}
            <ChevronRight size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
