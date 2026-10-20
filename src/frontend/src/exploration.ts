import { Chess } from "chess.js";
import type { Game } from "./types";
export interface Exploration {
  base: string;
  moves: string[];
  revision: number;
  atLatest: boolean;
  cursor?: number;
  returnPly?: number | null;
  previewOnly?: boolean;
  label?: string;
}
/** Every variation is replayed on a new board. The saved game is immutable. */
export function replayVariation(base: string, moves: readonly string[]): Chess {
  const board = new Chess(base);
  for (const move of moves) board.move(move);
  return board;
}
export function committable(
  game: Game | null,
  explore: Exploration | null,
): boolean {
  if (
    !explore ||
    explore.previewOnly ||
    !explore.moves.length ||
    !explore.atLatest
  )
    return false;
  if (game && game.revision !== explore.revision) return false;
  if (game?.mode === "analysis") return true;
  return (
    new Chess(explore.base).turn() ===
    (game?.player_color === "black" ? "b" : "w")
  );
}

/** Accept only the legal prefix of external engine/coach data; never render an invented continuation. */
export function legalVariation(
  base: string,
  moves: readonly string[],
): string[] {
  const board = new Chess(base);
  const legal: string[] = [];
  for (const move of moves) {
    try {
      legal.push(board.move(move).lan);
    } catch {
      break;
    }
  }
  return legal;
}
export function variationCursor(explore: Exploration): number {
  return Math.max(
    0,
    Math.min(explore.cursor ?? explore.moves.length, explore.moves.length),
  );
}
