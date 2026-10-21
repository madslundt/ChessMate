import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Chess } from 'chess.js';
import { LastMoveFeedback } from './LastMoveFeedback';
import { LocaleContext } from './i18n';
import type { Game } from './types';

function game(initialFen = new Chess().fen()): Game {
  const chess = new Chess(initialFen);
  const moves = ['e4', 'e5', 'Nf3', 'Nc6'];
  return {
    id: 'feedback', mode: 'training', player_color: 'white', difficulty: 1,
    revision: 4, status: 'active', initial_fen: initialFen, fen: initialFen,
    moves: moves.slice(chess.turn() === 'b' ? 1 : 0).map((san, index) => {
      const move = chess.move(san);
      return { uci: move.from + move.to, san, fen: chess.fen(), feedback: {
        classification: index === 0 ? 'Good' : index === 1 ? 'Blunder' : 'Excellent', text: `Feedback for ${san}`,
      } };
    }),
  };
}

describe('last move feedback', () => {
  it('keeps each side’s latest move and its own classification', () => {
    const html = renderToStaticMarkup(<LastMoveFeedback game={game()} ply={3} />);
    expect(html).toContain('2. Nf3');
    expect(html).toContain('1... e5');
    expect(html).toContain('Feedback for Nf3');
    expect(html).toContain('Feedback for e5');
    expect(html).toContain('last-move-feedback-card excellent');
    expect(html).toContain('last-move-feedback-card blunder');
    expect(html).not.toContain('Feedback for e4');
    expect(html).not.toContain('Feedback for Nc6');
  });

  it('follows history and does not reuse older feedback for an ungraded move', () => {
    const saved = game();
    saved.moves[2].feedback = null;
    const html = renderToStaticMarkup(<LastMoveFeedback game={saved} ply={3} />);
    expect(html).toContain('2. Nf3');
    expect(html).toContain('No feedback available for this move.');
    expect(html).not.toContain('Feedback for e4');
    const first = renderToStaticMarkup(<LastMoveFeedback game={saved} ply={1} />);
    expect(first).toContain('1. e4');
    expect(first).toContain('No moves yet.');
    expect(first).not.toContain('Feedback for e5');
  });

  it('handles Black starting from a custom position and Danish labels', () => {
    const chess = new Chess();
    chess.move('e4');
    const saved = game(chess.fen().replace('0 1', '0 12'));
    const html = renderToStaticMarkup(<LocaleContext.Provider value="da"><LastMoveFeedback game={saved} ply={2} /></LocaleContext.Provider>);
    expect(html).toContain('12... e5');
    expect(html).toContain('13. Nf3');
    expect(html).toContain('Feedback på seneste træk');
    expect(html).toContain('Hvid');
    expect(html).toContain('Sort');
  });
});
