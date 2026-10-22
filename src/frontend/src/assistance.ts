import { api } from './api';
import type { Game } from './types';
export type AssistanceCategory =
  'general_guidance' | 'piece_revealed' | 'destination_revealed' | 'full_solution' | 'engine_assisted';
/** Persist an exposure before displaying it, so a failed write cannot silently inflate independence. */
export async function recordAssistance(
  game: Game | null,
  category: AssistanceCategory,
  source: string,
  suggested_move?: string,
  revealed?: Record<string, unknown>,
) {
  if (!game || game.mode === 'analysis' || (game.result && game.result !== '*')) return;
  const playerTurn = game.fen.split(' ')[1] === (game.player_color === 'white' ? 'w' : 'b');
  if (!playerTurn) return;
  await api(`/games/${game.id}/assistance`, {
    revision: game.revision,
    fen: game.fen,
    category,
    source,
    suggested_move,
    revealed,
  });
}
