import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Chess } from 'chess.js';
import { feedbackImprovement, FeedbackHighlights } from './FeedbackHighlights';
import { LocaleContext } from './i18n';
import type { Feedback } from './types';

const board = new Chess();
board.move('f3');
board.move('e5');
const beforeFen = board.fen();
const feedback: Feedback = { classification: 'Blunder', fen: beforeFen,
  improvement: { uci: 'd2d4', san: 'd4', fen: beforeFen } };

describe('feedback highlights', () => {
  it('rejects stale, illegal, or identical improvement moves', () => {
    expect(feedbackImprovement(feedback, beforeFen, 'g2g4')?.san).toBe('d4');
    expect(feedbackImprovement({ ...feedback, fen: new Chess().fen() }, beforeFen, 'g2g4')).toBeNull();
    expect(feedbackImprovement({ ...feedback, improvement: { uci: 'd2d4', san: 'd4', fen: new Chess().fen() } }, beforeFen, 'g2g4')).toBeNull();
    expect(feedbackImprovement({ ...feedback, improvement: { uci: 'e2e5', san: 'e5', fen: beforeFen } }, beforeFen, 'g2g4')).toBeNull();
    expect(feedbackImprovement(feedback, beforeFen, 'd2d4')).toBeNull();
  });

  it('renders a compact, keyboard-accessible improvement label in both languages', () => {
    const props = { feedback, beforeFen, playedUci: 'g2g4', onVisual: () => {} };
    const english = renderToStaticMarkup(createElement(FeedbackHighlights, props));
    expect(english).toContain('A better move was');
    expect(english).toContain('aria-pressed="false"');
    expect(english).toContain('>d4</button>.');
    const danish = renderToStaticMarkup(createElement(LocaleContext.Provider, { value: 'da' }, createElement(FeedbackHighlights, props)));
    expect(danish).toContain('Et bedre træk var');
    expect(danish).toContain('Klik for at fremhæve på brættet');
    expect(renderToStaticMarkup(createElement(FeedbackHighlights, { ...props, feedback: { ...feedback, classification: 'Good' } }))).toBe('');
  });
});
