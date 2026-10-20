import { Chess } from 'chess.js';
import type { Game } from './types';
export interface Exploration {
  base: string;
  moves: string[];
  revision: number;
  atLatest: boolean;
}
/** Every variation is replayed on a new board. The saved game is immutable. */
export function replayVariation(base: string, moves: readonly string[]): Chess {
  const board = new Chess(base);
  for (const move of moves) board.move(move);
  return board;
}
export function committable(game: Game | null, explore: Exploration | null): boolean {
  if (!explore || !explore.moves.length || !explore.atLatest) return false;
  if (game && game.revision !== explore.revision) return false;
  if (game?.mode === 'analysis') return true;
  return new Chess(explore.base).turn() === (game?.player_color === 'black' ? 'b' : 'w');
}
