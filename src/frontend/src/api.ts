export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  const profileId = localStorage.getItem('chessmate.profile');
  const response = await fetch(`/api${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    credentials: 'same-origin',
    headers: {
      ...(body === undefined && method !== 'DELETE' ? {} : { 'Content-Type': 'application/json' }),
      ...(profileId ? { 'X-Profile-ID': profileId } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let code: string | undefined;
    try {
      const d = await response.json();
      if (typeof d.detail?.message === 'string') {
        message = d.detail.message;
        code = typeof d.detail.code === 'string' ? d.detail.code : undefined;
      } else {
        message = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d);
      }
    } catch {
      /* plain upstream failure */
    }
    if (code === 'authentication_required' && path !== '/profiles' && typeof window !== 'undefined')
      window.dispatchEvent(new Event('chessmate-auth-required'));
    throw new ApiError(message, response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export async function streamCoach(
  body: unknown,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const profileId = localStorage.getItem('chessmate.profile');
  const response = await fetch('/api/coach', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(profileId ? { 'X-Profile-ID': profileId } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let message = 'Coach request failed';
    let code: string | undefined;
    try {
      const detail = (await response.json()).detail;
      message = typeof detail === 'string' ? detail : detail?.message || message;
      code = typeof detail?.code === 'string' ? detail.code : undefined;
    } catch {}
    if (code === 'authentication_required' && typeof window !== 'undefined')
      window.dispatchEvent(new Event('chessmate-auth-required'));
    throw new ApiError(message, response.status, code);
  }
  if (!response.body) throw new Error('Streaming is unavailable in this browser');
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = '';
  function parse(frame: string) {
    let event = 'message';
    const lines: string[] = [];
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
    }
    const raw = lines.join('\n');
    if (!raw || raw === '[DONE]') return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(raw);
    } catch {
      data = { text: raw };
    }
    onEvent(event, data);
  }
  while (true) {
    const { done, value } = await reader.read();
    buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, '\n');
    let end;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      parse(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
    }
    if (done) {
      if (buffer.trim()) parse(buffer);
      break;
    }
  }
}
