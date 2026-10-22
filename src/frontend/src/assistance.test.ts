import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { recordAssistance } from './assistance';
import type { Game } from './types';
vi.mock('./api', () => ({ api: vi.fn() }));
const game: Game = {
  id: 'game-1',
  mode: 'training',
  player_color: 'white',
  difficulty: 2,
  revision: 4,
  fen: '8/8/8/8/8/8/8/8 w - - 0 1',
  initial_fen: '',
  moves: [],
  status: 'active',
  result: '*',
};
describe('visual assistance disclosure', () => {
  beforeEach(() => vi.mocked(api).mockReset());
  it('persists exact exposure with position and timeline revision', async () => {
    await recordAssistance(game, 'full_solution', 'variation_preview', 'e2e4');
    expect(api).toHaveBeenCalledWith(
      '/games/game-1/assistance',
      expect.objectContaining({
        revision: 4,
        fen: game.fen,
        category: 'full_solution',
        source: 'variation_preview',
        suggested_move: 'e2e4',
      }),
    );
  });
  it('does not conflate postgame review or computer-turn analysis with player assistance', async () => {
    await recordAssistance({ ...game, result: '1-0' }, 'engine_assisted', 'exploration');
    await recordAssistance({ ...game, mode: 'analysis' }, 'engine_assisted', 'exploration');
    await recordAssistance({ ...game, player_color: 'black' }, 'engine_assisted', 'exploration');
    await recordAssistance(null, 'engine_assisted', 'exploration');
    expect(api).not.toHaveBeenCalled();
  });
  it('propagates persistence failures so callers can withhold the reveal', async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error('offline'));
    await expect(recordAssistance(game, 'engine_assisted', 'exploration')).rejects.toThrow('offline');
  });
});
