import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { recordAssistance, workspacePreferences } from './assistance';
import { defaults, type Game } from './types';
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
  it('temporarily hides automatic help in independent play without changing saved settings or analysis', () => {
    const saved = { ...defaults, show_evaluation: true, show_evaluation_bar: true, show_alternatives: true };
    const independent = workspacePreferences(saved, 'independent', false);
    expect(independent.show_evaluation || independent.show_evaluation_bar || independent.show_alternatives).toBe(false);
    expect(independent.coaching_mode).toBe('independent');
    expect(independent.feedback).toBe('none');
    expect(workspacePreferences(saved, 'automatic', false)).toBe(saved);
    expect(workspacePreferences(saved, 'independent', true)).toBe(saved);
    expect(saved.show_evaluation && saved.show_evaluation_bar && saved.show_alternatives).toBe(true);
  });
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
