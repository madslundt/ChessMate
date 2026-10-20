import { useT } from "./i18n";
import { VisualExplanation } from "./VisualExplanation";
import type {
  Candidate,
  Preferences,
  VisualCoaching,
  VisualInsight,
} from "./types";
export function HintCard({
  hint,
  hintLevel,
  hintMove,
  hintVisual,
  preferences,
  highlightedMove,
  onHoverMove,
  onToggleMove,
  onVisual,
  onPreview,
}: {
  hint: string;
  hintLevel: number;
  hintMove: string | null;
  hintVisual: VisualCoaching | null;
  preferences: Preferences;
  highlightedMove?: string | null;
  onHoverMove: (uci: string | null) => void;
  onToggleMove: (uci: string) => void;
  onVisual: (insight: VisualInsight) => void;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  return (
    <div
      className={`hint-note hint-note-selectable${highlightedMove === hintMove ? " is-highlighted" : ""}`}
      data-testid="position-hint"
      role={hintMove ? "button" : undefined}
      tabIndex={hintMove ? 0 : undefined}
      aria-pressed={hintMove ? highlightedMove === hintMove : undefined}
      onPointerEnter={() => hintMove && onHoverMove(hintMove)}
      onPointerLeave={() => onHoverMove(null)}
      onClick={() => hintMove && onToggleMove(hintMove)}
      onKeyDown={(event) => {
        if (hintMove && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onToggleMove(hintMove);
        }
      }}
    >
      <span>
        {t("hint")} {hintLevel}/4
      </span>
      <p>{hint}</p>
      {hintVisual && preferences.explanation_mode !== "text" && (
        <VisualExplanation
          coaching={hintVisual}
          onVisual={onVisual}
          onPreview={onPreview}
        />
      )}
    </div>
  );
}
