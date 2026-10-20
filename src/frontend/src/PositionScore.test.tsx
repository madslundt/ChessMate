import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Chess } from 'chess.js';
import { materialScore, PositionScore } from './PositionScore';
import { LocaleContext } from './i18n';
import type { Candidate } from './types';

describe('position score', () => {
  it('counts remaining material, including en passant and promotion', () => {
    const board = new Chess();
    expect(materialScore(board)).toEqual({ w: 39, b: 39 });
    for (const move of ['e4', 'a6', 'e5', 'd5', 'exd6']) board.move(move);
    expect(materialScore(board)).toEqual({ w: 39, b: 38 });
    const promotion = new Chess('7k/P7/8/8/8/8/8/7K w - - 0 1');
    promotion.move('a8=N');
    expect(materialScore(promotion)).toEqual({ w: 3, b: 0 });
  });

  it('shows the winner instead of equal material after checkmate', () => {
    const board = new Chess();
    for (const move of ['f3', 'e5', 'g4', 'Qh4#']) board.move(move);
    const html = renderToStaticMarkup(<PositionScore chess={board} showEvaluation={false} />);
    expect(html).toContain('Black wins · 0–1');
    expect(html).not.toContain('Equal material');
  });

  it('uses saved draws instead of claiming a material lead', () => {
    const board = new Chess('7k/Q7/8/8/8/8/8/7K w - - 0 1');
    const html = renderToStaticMarkup(<PositionScore chess={board} result="1/2-1/2" showEvaluation={false} />);
    expect(html).toContain('Draw · ½–½');
    expect(html).not.toContain('leads in material');
  });

  it('uses White perspective regardless of side to move and keeps material distinct', () => {
    const board = new Chess();
    board.move('e4');
    const evaluation: Candidate = {
      uci: 'e7e5',
      san: 'e5',
      cp: 200,
      mate: null,
      white_cp: -200,
      white_mate: null,
      pv: [],
    };
    const html = renderToStaticMarkup(<PositionScore chess={board} evaluation={evaluation} showEvaluation />);
    expect(html).toContain('Equal material');
    expect(html).toContain('Black is ahead · -2.0');
    expect(
      renderToStaticMarkup(<PositionScore chess={board} evaluation={evaluation} showEvaluation={false} />),
    ).not.toContain('Black is ahead');
  });

  it('handles unavailable evaluations, mate predictions and Danish labels', () => {
    const board = new Chess();
    expect(renderToStaticMarkup(<PositionScore chess={board} showEvaluation />)).toContain('Awaiting evaluation');
    const evaluation: Candidate = { uci: 'e2e4', san: 'e4', cp: null, mate: 3, white_cp: null, white_mate: 3, pv: [] };
    expect(renderToStaticMarkup(<PositionScore chess={board} evaluation={evaluation} showEvaluation />)).toContain(
      'White has forced mate · M3',
    );
    expect(
      renderToStaticMarkup(
        <LocaleContext.Provider value="da">
          <PositionScore chess={board} showEvaluation={false} />
        </LocaleContext.Provider>,
      ),
    ).toContain('Lige materiale');
  });
});
