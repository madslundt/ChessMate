import { afterEach, describe, it, expect, vi } from 'vitest';
import { api, ApiError, streamCoach } from './api';
afterEach(() => vi.unstubAllGlobals());
describe('API transport', () => {
  it('retains a structured validation error and status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'This game changed' }), {
            status: 409,
          }),
      ),
    );
    await expect(api('/games/x/moves', { revision: 1 })).rejects.toMatchObject({
      message: 'This game changed',
      status: 409,
    });
  });
  it('parses SSE JSON correctly across UTF-8 and event boundaries', async () => {
    const bytes = new TextEncoder().encode(
      'event: token\r\ndata: {"text":"Rokadé"}\r\n\r\nevent: done\ndata: {"source":"deterministic"}\n\n',
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            new ReadableStream({
              start(c) {
                for (let i = 0; i < bytes.length; i += 1) c.enqueue(bytes.slice(i, i + 1));
                c.close();
              },
            }),
          ),
      ),
    );
    const events: unknown[] = [];
    await streamCoach({}, (e, d) => events.push([e, d]));
    expect(events).toEqual([
      ['token', { text: 'Rokadé' }],
      ['done', { source: 'deterministic' }],
    ]);
  });
  it('does not conceal authentication failures as coach text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'Sign in to continue' }), {
            status: 401,
          }),
      ),
    );
    await expect(streamCoach({}, () => {})).rejects.toBeInstanceOf(ApiError);
  });
});
