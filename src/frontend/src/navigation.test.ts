import { describe, expect, it } from 'vitest';
import { gamePath, learnPath, parseRoute } from './navigation';

describe('deep links', () => {
  it('round-trips saved game and analysis links', () => {
    for (const mode of ['training', 'computer', 'analysis']) {
      const path = gamePath({ mode, id: 'game-123' });
      expect(parseRoute(path)).toMatchObject({
        page: mode === 'analysis' ? 'analyze' : 'play',
        gameId: 'game-123',
        found: true,
      });
    }
    expect(parseRoute('/play')).toMatchObject({ page: 'play', gameId: null });
  });

  it('restores learning categories, exercises and practice sessions', () => {
    const url = new URL(learnPath('opening', 'repertoire-123-0', 'session-123'), 'http://localhost');
    expect(parseRoute(url.pathname, url.search)).toMatchObject({
      page: 'learn',
      category: 'opening',
      exerciseId: 'repertoire-123-0',
      sessionId: 'session-123',
      found: true,
    });
    expect(learnPath()).toBe('/learn');
    expect(parseRoute('/learn/forks')).toMatchObject({
      category: 'forks',
      exerciseId: null,
    });
  });

  it('rejects unknown pages and unsafe or malformed resource paths', () => {
    for (const path of [
      '/missing',
      '/settings/extra',
      '/learn/unknown',
      '/learn/forks/exercises',
      '/play/a/extra',
      '/play/%2Fapi',
      '/play/%ZZ',
      '/learn/forks/exercises/..',
    ]) {
      expect(parseRoute(path).found, path).toBe(false);
    }
  });
});
