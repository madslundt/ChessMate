export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    credentials: 'same-origin',
    headers: body === undefined && method !== 'DELETE' ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const d = await response.json();
      message = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d);
    } catch {
      /* plain upstream failure */
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export async function streamCoach(
  body: unknown,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/coach', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let message = 'Coach request failed';
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new ApiError(message, response.status);
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
