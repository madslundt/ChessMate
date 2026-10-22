import { describe, expect, it } from 'vitest';
import { monthDays, positionPath, presetRange, shiftMonth, todayInTimezone } from './diaryCalendar';
import { parseRoute } from './navigation';

describe('calendar dates and report boundaries', () => {
  it('builds Monday-first leap-year months without fabricating dates', () => {
    const days = monthDays('2024-02');
    expect(days.slice(0, 4)).toEqual([null, null, null, '2024-02-01']);
    expect(days.filter(Boolean)).toHaveLength(29);
    expect(days).toHaveLength(35);
    expect(monthDays('2026-02').filter(Boolean)).toHaveLength(28);
    expect(monthDays('2026-03').filter(Boolean)).toHaveLength(31);
  });
  it('crosses year boundaries in both directions', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-02', 12)).toBe('2027-02');
  });
  it('uses the configured timezone around midnight and daylight saving time', () => {
    const midnight = new Date('2026-10-21T22:30:00Z');
    expect(todayInTimezone('Europe/Copenhagen', midnight)).toBe('2026-10-22');
    expect(todayInTimezone('America/New_York', midnight)).toBe('2026-10-21');
    expect(todayInTimezone('Europe/Copenhagen', new Date('2026-03-29T22:30:00Z'))).toBe('2026-03-30');
  });
  it('includes today in rolling ranges and handles previous leap-year months', () => {
    expect(presetRange('7', '2026-01-03')).toEqual({
      start_date: '2025-12-28',
      end_date: '2026-01-03',
    });
    expect(presetRange('30', '2026-10-22')).toEqual({
      start_date: '2026-09-23',
      end_date: '2026-10-22',
    });
    expect(presetRange('month', '2026-10-22')).toEqual({
      start_date: '2026-10-01',
      end_date: '2026-10-22',
    });
    expect(presetRange('previous', '2024-03-05')).toEqual({
      start_date: '2024-02-01',
      end_date: '2024-02-29',
    });
  });
  it('opens the exact game position and parses bounded position links', () => {
    const path = new URL(positionPath('game-123', 17), 'https://example.test');
    expect(parseRoute(path.pathname, path.search)).toMatchObject({
      page: 'analyze',
      gameId: 'game-123',
      ply: 17,
      found: true,
    });
    expect(parseRoute('/analyze/game-123', '?ply=-1').ply).toBeNull();
    expect(parseRoute('/analyze/game-123', '?ply=100000000').ply).toBeNull();
    expect(parseRoute('/diary')).toMatchObject({ page: 'diary', found: true });
  });
});
