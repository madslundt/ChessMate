import { useMemo } from "react";
import { Chess } from "chess.js";
import {
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
} from "lucide-react";
import { replayVariation } from "./exploration";
import { useT } from "./i18n";

export interface VariationPlayerProps {
  base: string;
  moves: string[];
  cursor: number;
  onCursor: (cursor: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
  speed: number;
  onSpeed: (speed: number) => void;
  label?: string;
  transportOnly?: boolean;
}
/** Controlled transport: its owner replays on an isolated board and owns the timer. */
export function VariationPlayer({
  base,
  moves,
  cursor,
  onCursor,
  playing,
  onPlaying,
  speed,
  onSpeed,
  label,
  transportOnly = false,
}: VariationPlayerProps) {
  const t = useT();
  const notation = useMemo(() => {
    const board = new Chess(base);
    return moves.map((move) => {
      const number = board.moveNumber();
      const side = board.turn();
      return `${number}${side === "w" ? "." : "…"} ${board.move(move).san}`;
    });
  }, [base, moves]);
  const current = replayVariation(base, moves.slice(0, cursor));
  const jump = (index: number) => {
    onPlaying(false);
    onCursor(index);
  };
  return (
    <section className="variation-player" aria-label={t("variationPlayback")}>
      {label && <strong>{label}</strong>}
      <div className="variation-transport">
        <button
          className="icon-button"
          aria-label={t("variationStart")}
          disabled={!cursor}
          onClick={() => jump(0)}
        >
          <ChevronFirst size={18} />
        </button>
        <button
          className="icon-button"
          aria-label={t("variationPrevious")}
          disabled={!cursor}
          onClick={() => jump(cursor - 1)}
        >
          <ChevronLeft size={18} />
        </button>
        {!transportOnly && (
          <>
            <button
              className="icon-button"
              aria-label={t(playing ? "pauseVariation" : "playVariation")}
              disabled={!moves.length}
              onClick={() => {
                if (!playing && cursor === moves.length) onCursor(0);
                onPlaying(!playing);
              }}
            >
              {playing ? <Pause size={18} /> : <Play size={18} />}
            </button>
          </>
        )}
        <button
          className="icon-button"
          aria-label={t("variationNext")}
          disabled={cursor === moves.length}
          onClick={() => jump(cursor + 1)}
        >
          <ChevronRight size={18} />
        </button>
        <button
          className="icon-button"
          aria-label={t("variationEnd")}
          disabled={cursor === moves.length}
          onClick={() => jump(moves.length)}
        >
          <ChevronLast size={18} />
        </button>
        {!transportOnly && (
          <>
            <label className="playback-speed">
              <span className="sr-only">{t("playbackSpeed")}</span>
              <select
                aria-label={t("playbackSpeed")}
                value={speed}
                onChange={(event) => onSpeed(Number(event.target.value))}
              >
                {![1800, 900, 450].includes(speed) && (
                  <option value={speed}>{(900 / speed).toFixed(1)}×</option>
                )}
                <option value={1800}>0.5×</option>
                <option value={900}>1×</option>
                <option value={450}>2×</option>
              </select>
            </label>{" "}
          </>
        )}
      </div>
      <p role="status" aria-live="polite">
        {cursor} / {moves.length} ·{" "}
        {cursor ? notation[cursor - 1] : t("variationStart")} ·{" "}
        {t(current.turn() === "w" ? "white" : "black")} {t("sideToMove")}
      </p>
      <div className="variation-moves">
        {notation.map((san, index) => (
          <button
            className="text-button"
            key={index}
            aria-current={cursor === index + 1 ? "step" : undefined}
            onClick={() => jump(index + 1)}
          >
            {san}
          </button>
        ))}
      </div>
    </section>
  );
}
