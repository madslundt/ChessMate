import { describe, expect, it } from 'vitest';
import { Chess } from 'chess.js';
import { betterAlternatives } from './BlunderReview';
import type { Candidate } from './types';

const board = new Chess();
board.move('f3');
board.move('e5');
const before = board.fen();
function candidate(uci: string, cp: number | null, mate: number | null = null): Candidate {
  return { uci, san: uci, cp, mate, pv: [] };
}
describe('blunder alternatives', () => {
  it('caps legal, distinct, strictly better moves at three and omits the played move', () => {
    const played = candidate('g2g4', -500);
    const choices = [
      played,
      candidate('d2d4', 30),
      candidate('d2d4', 30),
      candidate('e2e5', 1000),
      candidate('a2a3', -600),
      candidate('e2e4', 20),
      candidate('g1h3', -100),
      candidate('b1c3', -200),
    ];
    expect(betterAlternatives(before, played.uci, choices, played).map((c) => c.uci)).toEqual(['d2d4', 'e2e4', 'g1h3']);
  });
  it('compares root-side scores for Black and handles forced mates', () => {
    const black = new Chess();
    black.move('e4');
    const played = candidate('f7f6', null, -2);
    expect(
      betterAlternatives(black.fen(), played.uci, [candidate('e7e5', -20), candidate('b8c6', null, -1)], played).map(
        (c) => c.uci,
      ),
    ).toEqual(['e7e5']);
  });
  it('does not recommend equal, unknown, or slower losing-mate alternatives', () => {
    const played = candidate('g2g4', -100);
    expect(betterAlternatives(before, played.uci, [candidate('d2d4', -100), candidate('e2e4', null)], played)).toEqual(
      [],
    );
  });
  it('uses a fresh played-move score when available, otherwise shows only the top engine choice', () => {
    expect(
      betterAlternatives(before, 'g2g4', [candidate('d2d4', 30), candidate('e2e4', 20), candidate('g2g4', -500)]).map(
        (c) => c.uci,
      ),
    ).toEqual(['d2d4', 'e2e4']);
    expect(
      betterAlternatives(before, 'g2g4', [candidate('d2d4', 30), candidate('e2e4', 20)]).map((c) => c.uci),
    ).toEqual(['d2d4']);
    expect(betterAlternatives(before, 'g2g4', [candidate('g2g4', 30), candidate('d2d4', 20)])).toEqual([]);
  });
});
