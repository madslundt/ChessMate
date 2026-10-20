import { useMemo, useState } from "react";
import { Board, evaluationText } from "./Board";
import { legalVariation, replayVariation } from "./exploration";
import { useT } from "./i18n";
import type { Candidate, Color, Preferences } from "./types";

/** Compare resulting positions at the same ply; every board has its own legal replay. */
export function CandidateComparison({
  base,
  candidates,
  preferences,
  orientation,
  onPreview,
  labels,
}: {
  labels?: string[];
  base: string;
  candidates: Candidate[];
  preferences: Preferences;
  orientation: Color;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  const [depth, setDepth] = useState(1);
  const lines = useMemo(
    () =>
      candidates
        .slice(0, 3)
        .map((candidate) => ({
          candidate,
          moves: legalVariation(
            base,
            candidate.pv_uci?.length
              ? candidate.pv_uci
              : candidate.pv?.length
                ? candidate.pv
                : [candidate.uci],
          ),
        })),
    [base, candidates],
  );
  const maximum = Math.max(1, ...lines.map((line) => line.moves.length));
  return (
    <section
      className="candidate-comparison"
      aria-label={t("comparePositions")}
    >
      <label>
        {t("compareAfterPlies")}: {depth}
        <input
          aria-label={t("compareAfterPlies")}
          type="range"
          min={1}
          max={maximum}
          value={depth}
          onChange={(event) => setDepth(Number(event.target.value))}
        />
      </label>
      <div className="comparison-boards">
        {lines.map(({ candidate, moves }, index) => {
          const board = replayVariation(base, moves.slice(0, depth));
          return (
            <article key={candidate.uci}>
              <h4>
                {labels?.[index] && <small>{labels[index]} · </small>}
                {candidate.san}
              </h4>
              <Board
                boardId={`comparison-${index}`}
                fen={board.fen()}
                preferences={preferences}
                orientation={orientation}
                disabled
                onMove={() => undefined}
                lastMove={moves[Math.min(depth, moves.length) - 1]}
                animate={false}
              />
              <small>
                {Math.min(depth, moves.length)} {t("plies")} ·{" "}
                {t(board.turn() === "w" ? "white" : "black")} {t("sideToMove")}
              </small>
              {preferences.show_evaluation && (
                <small>
                  {t("rootEstimate")}:{" "}
                  {evaluationText(candidate.cp, candidate.mate)}
                </small>
              )}
              <p>{candidate.explanation || candidate.idea}</p>
              <button
                className="text-button"
                onClick={() => onPreview(candidate, base)}
              >
                {t("candidatePreview")}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
