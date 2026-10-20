import { describe, it, expect } from 'vitest';
import { Chess } from 'chess.js';
import { committable, replayVariation } from './exploration';
import type { Game } from './types';
const game: Game = {
  id: 'test',
  fen: new Chess().fen(),
  initial_fen: new Chess().fen(),
  moves: [],
  revision: 2,
  mode: 'training',
  player_color: 'white',
  difficulty: 2,
  status: 'playing',
  result: '*',
};
describe('independent exploration', () => {
  it('replays several hypothetical plies without mutating the saved game', () => {
    const before = JSON.stringify(game);
    const c = replayVariation(game.fen, ['e2e4', 'e7e5', 'g1f3']);
    expect(c.history()).toEqual(['e4', 'e5', 'Nf3']);
    expect(JSON.stringify(game)).toBe(before);
  });
  it('rejects an illegal line and cannot affect the authoritative position', () => {
    expect(() => replayVariation(game.fen, ['e2e5'])).toThrow();
    expect(game.fen).toBe(new Chess().fen());
  });
  it('allows committing the first move regardless of the last hypothetical side to move', () => {
    expect(
      committable(game, {
        base: game.fen,
        moves: ['e2e4'],
        revision: 2,
        atLatest: true,
      }),
    ).toBe(true);
  });
  it('rejects stale games, historical branches, and branches rooted in the opponent turn', () => {
    expect(
      committable(game, {
        base: game.fen,
        moves: ['e2e4'],
        revision: 1,
        atLatest: true,
      }),
    ).toBe(false);
    expect(
      committable(game, {
        base: game.fen,
        moves: ['e2e4'],
        revision: 2,
        atLatest: false,
      }),
    ).toBe(false);
    expect(
      committable(game, {
        base: replayVariation(game.fen, ['e2e4']).fen(),
        moves: ['e7e5'],
        revision: 2,
        atLatest: true,
      }),
    ).toBe(false);
  });
});
