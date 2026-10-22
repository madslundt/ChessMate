import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { CalendarGrid, DiaryEvidence } from './Diary';
import { LocaleContext } from './i18n';
import { defaults } from './types';
import { GameSetup } from './GameDialogs';
const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

describe('diary and adaptive setup rendering', () => {
  it('shows activity counts, selection and one keyboard entry point', () => {
    const markup = renderToStaticMarkup(
      <CalendarGrid
        month="2026-10"
        selected="2026-10-22"
        weekdays={weekdays}
        language="en"
        activity={
          new Map([
            ['2026-10-22', { game_count: 4, status: 'ready' }],
            ['2026-10-01', { game_count: 1, status: 'partial' }],
          ])
        }
        onSelect={() => undefined}
      />,
    );
    expect(markup).toContain('2026-10-22: 4 games');
    expect(markup).toContain('2026-10-02: 0 games');
    expect(markup).toContain('data-intensity="4"');
    expect(markup).toContain('aria-pressed="true"');
    expect(markup.match(/tabindex="0"/g)).toHaveLength(1);
    expect(markup.match(/class="diary-weekday"/g)).toHaveLength(7);
  });
  it('renders empty historical months and Danish activity labels', () => {
    const markup = renderToStaticMarkup(
      <LocaleContext.Provider value="da">
        <CalendarGrid
          month="2001-02"
          selected={null}
          weekdays={weekdays}
          language="da"
          activity={new Map()}
          onSelect={() => undefined}
        />
      </LocaleContext.Provider>,
    );
    expect(markup).toContain('Kalender for skakaktivitet');
    expect(markup).toContain('2001-02-28: 0 partier');
    expect(markup).not.toContain('2001-02-29');
    expect(markup).not.toContain('tabindex="0"');
  });
  it('qualifies partial analysis, separates assistance, links positions and escapes narrative HTML', () => {
    const markup = renderToStaticMarkup(
      <DiaryEvidence
        preferences={defaults}
        content={{
          status: 'partial',
          summary: '<script>bad()</script>\n\nCheck opponent replies.',
          statistics: {
            games: 2,
            wins: 1,
            draws: 0,
            losses: 1,
            independent: 5,
            assisted: 8,
            unknown: 3,
          },
          observations: [
            {
              game_id: 'game-123',
              ply: 9,
              fen: '',
              san: 'Nf3',
              text: 'Develop a piece.',
            },
          ],
          recommendations: [],
        }}
      />,
    );
    expect(markup).toContain('This reflection is incomplete.');
    expect(markup).toContain('Independent decisions: 5');
    expect(markup).toContain('Assisted decisions: 8');
    expect(markup).toContain('Unknown assistance: 3');
    expect(markup).toContain('/analyze/game-123?ply=8');
    expect(markup).toContain('&lt;script&gt;');
    expect(markup).not.toContain('<script>');
  });
  it('qualifies period comparisons with insufficient independent samples', () => {
    const statistics = { games: 1, wins: 0, draws: 0, losses: 1, independent: 3, assisted: 4, unknown: 0 };
    const markup = renderToStaticMarkup(
      <DiaryEvidence
        preferences={defaults}
        content={{
          status: 'completed',
          summary: 'One game.',
          statistics,
          observations: [],
          recommendations: [],
          comparison: {
            start_date: '2026-10-01',
            end_date: '2026-10-07',
            statistics,
            sufficient_evidence: false,
            independent_sound_rate_change: null,
            qualification: 'Descriptive comparison.',
          },
        }}
      />,
    );
    expect(markup).toContain('not yet enough independent observations');
    expect(markup).not.toContain('percentage points');
    expect(markup).toContain('Descriptive comparison.');
  });

  it('shows descriptive rate changes only when the backend confirms sufficient evidence', () => {
    const statistics = { games: 5, wins: 3, draws: 0, losses: 2, independent: 30, assisted: 4, unknown: 0 };
    const markup = renderToStaticMarkup(
      <DiaryEvidence
        preferences={defaults}
        content={{
          status: 'completed',
          summary: 'Five games.',
          statistics,
          observations: [],
          recommendations: [],
          comparison: {
            start_date: '2026-10-01',
            end_date: '2026-10-07',
            statistics,
            sufficient_evidence: true,
            independent_sound_rate_change: 0.125,
            qualification: 'Opponent strength may differ.',
          },
        }}
      />,
    );
    expect(markup).toContain('12.5');
    expect(markup).toContain('percentage points');
    expect(markup).toContain('Opponent strength may differ.');
  });

  it('keeps position training and imports visible separately from complete-game evidence', () => {
    const statistics = { games: 3, wins: 1, draws: 0, losses: 2, independent: 14, assisted: 5, unknown: 20 };
    const markup = renderToStaticMarkup(<DiaryEvidence preferences={defaults} content={{ status: 'completed', summary: 'Activity summary.', statistics, observations: [], recommendations: [], source_statistics: {
      game: { ...statistics, games: 1, independent: 4, assisted: 2, unknown: 0 }, training: { ...statistics, games: 1, independent: 10, assisted: 3, unknown: 0 }, import: { ...statistics, games: 1, independent: 0, assisted: 0, unknown: 20 },
    } }} />);
    expect(markup).toContain('Complete games');
    expect(markup).toContain('Position training');
    expect(markup).toContain('Imported games');
    expect(markup).toContain('Independent decisions: 4');
    expect(markup).toContain('Independent decisions: 10');
    expect(markup).toContain('Unknown assistance: 20');
    expect(markup).toContain('Period comparisons use complete games only.');
  });

  it('defaults new games to adaptive and preserves manual preference', () => {
    const render = (preferences = defaults) =>
      renderToStaticMarkup(
        <GameSetup
          analysisMode={false}
          preferences={preferences}
          onClose={() => undefined}
          onStart={async () => undefined}
        />,
      );
    expect(render()).toContain('<option value="adaptive" selected="">');
    expect(render()).not.toContain('type="range"');
    const manual = render({
      ...defaults,
      difficulty_mode: 'manual',
      difficulty: 4,
    });
    expect(manual).toContain('<option value="manual" selected="">');
    expect(manual).toContain('type="range"');
    expect(manual).toContain('value="4"');
  });
});
