export interface SpeechSettings {
  stt_mode: 'browser' | 'server';
  tts_mode: 'browser' | 'server';
  stt_base_url: string;
  stt_model: string;
  tts_base_url: string;
  tts_model: string;
  tts_voice: string;
  verify_tls: boolean;
  has_stt_api_key: boolean;
  has_tts_api_key: boolean;
}

function profileHeaders() {
  const profileId = localStorage.getItem('chessmate.profile');
  return profileId ? { 'X-Profile-ID': profileId } : {};
}

async function responseError(response: Response) {
  try {
    const data = await response.json();
    if (data.detail && typeof data.detail === 'object' && typeof data.detail.message === 'string') return data.detail.message;
    if (typeof data.detail === 'string') return data.detail;
  } catch {
    // Keep upstream response bodies private; only return a generic local error.
  }
  return `Speech request failed (${response.status})`;
}

export async function transcribeAudio(audio: Blob, mimeType = audio.type): Promise<string> {
  const form = new FormData();
  const extension = mimeType.includes('wav') ? 'wav' : mimeType.includes('mp4') ? 'mp4' : 'webm';
  form.append('file', audio, `question.${extension}`);
  const response = await fetch('/api/speech/transcribe', {
    method: 'POST',
    credentials: 'same-origin',
    headers: profileHeaders(),
    body: form,
  });
  if (!response.ok) throw new Error(await responseError(response));
  const payload = (await response.json()) as { text?: unknown };
  if (typeof payload.text !== 'string' || !payload.text.trim()) throw new Error('No speech was recognized. Try again.');
  return payload.text.trim();
}

export async function synthesizeSpeech(text: string, language: string): Promise<Blob> {
  const response = await fetch('/api/speech/synthesize', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...profileHeaders() },
    body: JSON.stringify({ text, language }),
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.blob();
}
