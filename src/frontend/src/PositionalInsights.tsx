import { useT } from "./i18n";
import { VisualExplanation } from "./VisualExplanation";
import type { Analysis, Candidate, Preferences, VisualInsight } from "./types";
export function PositionalInsights({
  analysis,
  preferences,
  onVisual,
  onPreview,
}: {
  analysis: Analysis;
  preferences: Preferences;
  onVisual: (insight: VisualInsight) => void;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  const insights = analysis.strategic_insights;
  if (!insights?.length) return null;
  return (
    <details
      className="positional-insights"
      open={
        preferences.complexity === "advanced" &&
        preferences.explanation_mode !== "visual"
      }
    >
      <summary>
        {t("positionFeatures")} ·{" "}
        {t(analysis.fen.split(" ")[1] === "w" ? "white" : "black")}
      </summary>
      <p className="muted">{t("positionFeaturesSide")}</p>
      {insights
        .slice(0, preferences.complexity === "beginner" ? 2 : 8)
        .map((insight) => (
          <article key={insight.id}>
            <small>
              {t(
                insight.claim_type === "strategic_interpretation"
                  ? "strategicInterpretation"
                  : "verifiedGeometry",
              )}
            </small>
            <p>{insight.text}</p>
            {preferences.explanation_mode !== "text" && (
              <VisualExplanation
                coaching={{ insights: [insight] }}
                onVisual={onVisual}
                onPreview={onPreview}
              />
            )}
          </article>
        ))}
    </details>
  );
}
