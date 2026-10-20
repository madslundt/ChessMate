import { useEffect, useMemo, useState } from "react";
import { Board } from "./Board";
import { legalVariation, replayVariation } from "./exploration";
import { useT } from "./i18n";
import { VariationPlayer } from "./VariationPlayer";
import type { Color, Preferences } from "./types";

/** Player-entered prediction branches never reach the saved-game move endpoint. */
export function CalculationBoard({
  orientation,
  base,
  notation,
  onLine,
  preferences,
  disabled,
}: {
  orientation?: Color;
  base: string;
  notation: string;
  onLine: (line: string[]) => void;
  preferences: Preferences;
  disabled: boolean;
}) {
  const t = useT();
  const moves = useMemo(
    () =>
      legalVariation(
        base,
        notation
          .replace(/\d+\.(?:\.\.)?/g, "")
          .trim()
          .split(/\s+/)
          .filter(Boolean),
      ),
    [base, notation],
  );
  const signature = moves.join(" ");
  const [cursor, setCursor] = useState(moves.length);
  const [branches, setBranches] = useState<string[][]>([]);
  useEffect(() => {
    setCursor(moves.length);
  }, [signature]);
  const at = Math.min(cursor, moves.length);
  const board = replayVariation(base, moves.slice(0, at));
  return (
    <section className="calculation-board" aria-label={t("buildLineOnBoard")}>
      <strong>
        {t(
          at === 0
            ? "chooseCandidate"
            : at % 2
              ? "predictOpponent"
              : "predictContinuation",
        )}
      </strong>
      <Board
        boardId="calculation-board"
        fen={board.fen()}
        orientation={
          orientation || (base.split(" ")[1] === "w" ? "white" : "black")
        }
        preferences={preferences}
        disabled={disabled || at >= 32 || board.isGameOver()}
        onMove={(move) => onLine([...moves.slice(0, at), move])}
        lastMove={moves[at - 1]}
        animate={preferences.animate_variations !== false}
      />
      <VariationPlayer
        base={base}
        moves={moves}
        cursor={at}
        onCursor={setCursor}
        playing={false}
        onPlaying={() => undefined}
        speed={preferences.variation_speed_ms || 900}
        onSpeed={() => undefined}
        transportOnly
      />
      <div className="visual-explanation-actions">
        <button
          className="text-button"
          disabled={!moves.length || disabled}
          onClick={() => onLine(moves.slice(0, Math.max(0, at - 1)))}
        >
          {t("undo")}
        </button>
        <button
          className="text-button"
          disabled={!moves.length || disabled}
          onClick={() => onLine([])}
        >
          {t("reset")}
        </button>
        <button
          className="text-button"
          disabled={
            !moves.length ||
            disabled ||
            branches.some((line) => line.join(" ") === signature)
          }
          onClick={() => setBranches([...branches, [...moves]])}
        >
          {t("saveCalculationBranch")}
        </button>
      </div>
      {!!branches.length && (
        <div
          className="calculation-branches"
          role="group"
          aria-label={t("calculationBranches")}
        >
          {branches.map((line, index) => (
            <button
              key={index}
              className="outline-button"
              disabled={disabled}
              aria-pressed={line.join(" ") === signature}
              onClick={() => onLine(line)}
            >
              {t("branch")} {index + 1} ·{" "}
              {replayVariation(base, line).history().join(" ")}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
