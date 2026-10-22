import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ImprovementTrend, type GamePerformance } from './ImprovementTrend';
function games(count: number, assessed = 10): GamePerformance[] {
  return Array.from({ length: count }, (_, index) => ({ game_id: `game-${index}`, date: '2026-10-22', assessed_moves: assessed, sound_moves: index < count - 5 ? 5 : 8, errors: 0, sound_rate: .8 }));
}
describe('independent move-quality comparisons', () => {
  it('does not infer improvement by comparing five games against one', () => {
    const markup = renderToStaticMarkup(<ImprovementTrend games={games(6)} />);
    expect(markup).not.toContain('improvement-comparison');
    expect(markup).toContain('at least three games');
    expect(markup).toContain('Assisted decisions, unknown history and position drills are excluded.');
  });
  it('requires sufficient independent moves in each period', () => {
    const markup = renderToStaticMarkup(<ImprovementTrend games={games(10, 2)} />);
    expect(markup).not.toContain('improvement-comparison');
    expect(markup).toContain('twenty independent assessed decisions');
  });
  it('shows a descriptive comparison after sufficient repeated independent evidence', () => {
    const markup = renderToStaticMarkup(<ImprovementTrend games={games(10)} />);
    expect(markup).toContain('improvement-comparison');
    expect(markup).toContain('30');
    expect(markup).toContain('percentage points');
    expect(markup).toContain('50');
    expect(markup).toContain('independent assessed decisions across');
  });
});
