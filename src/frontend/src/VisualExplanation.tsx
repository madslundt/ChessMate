import { useT } from "./i18n";
import type { Candidate, VisualCoaching, VisualInsight } from "./types";
export function VisualExplanation({
  coaching,
  onVisual,
  onPreview,
}: {
  coaching: VisualCoaching;
  onVisual: (insight: VisualInsight) => void;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  return (
    <div className="visual-explanation-actions">
      {coaching.insights?.map((insight) => (
        <button
          key={insight.id}
          className="text-button"
          onClick={() => onVisual(insight)}
          title={insight.text}
        >
          {t("showOnBoard")}
          {coaching.insights!.length > 1 ? ` · ${insight.text}` : ""}
        </button>
      ))}
      {coaching.variations
        ?.filter((variation) => variation.moves.length > 0)
        .map((variation) => (
          <button
            key={variation.id}
            className="outline-button"
            onClick={() =>
              onPreview(
                {
                  uci: variation.moves[0],
                  san: variation.label,
                  cp: null,
                  mate: null,
                  pv: [],
                  pv_uci: variation.moves,
                },
                variation.base_fen,
              )
            }
          >
            {variation.label}
          </button>
        ))}
    </div>
  );
}
