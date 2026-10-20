import { lazy, Suspense, useState } from "react";
const CandidateComparison = lazy(() =>
  import("./CandidateComparison").then((module) => ({
    default: module.CandidateComparison,
  })),
);
import { Modal } from "./components";
import { useT } from "./i18n";
import type { Candidate, Color, Feedback, Preferences } from "./types";
export function ConsequenceComparison({
  feedback,
  base,
  preferences,
  orientation,
  onPreview,
}: {
  feedback: Feedback;
  base: string;
  preferences: Preferences;
  orientation: Color;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const better =
    feedback.best ||
    feedback.alternatives?.find(
      (candidate) => candidate.uci !== feedback.played?.uci,
    );
  if (
    !feedback.played ||
    !better ||
    better.uci === feedback.played.uci ||
    preferences.hide_best_moves
  )
    return null;
  return (
    <div className="consequence-comparison">
      <button
        className="outline-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {t("compareConsequences")}
      </button>
      {open && (
        <Modal title={t("compareConsequences")} onClose={() => setOpen(false)}>
          <Suspense fallback={null}>
            <CandidateComparison
              base={base}
              candidates={[feedback.played, better]}
              preferences={preferences}
              orientation={orientation}
              labels={[t("playedMove"), t("betterAlternative")]}
              onPreview={(candidate, root) => {
                setOpen(false);
                onPreview(candidate, root);
              }}
            />
          </Suspense>
        </Modal>
      )}
    </div>
  );
}
