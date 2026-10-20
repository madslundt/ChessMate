import { useContext, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Mic, RefreshCw, Save, Square } from 'lucide-react';
import { api, ApiError } from './api';
import { LocaleContext, useT, type TranslationKey } from './i18n';
import { ErrorNotice, Field, Spinner, Toggle } from './components';
import { synthesizeSpeech, transcribeAudio } from './speechClient';
import './styles/speech-settings.css';

/** Settings returned by GET /settings/speech. API keys are represented only by presence flags. */
export interface SpeechSettingsValue {
  stt_mode: 'browser' | 'server';
  tts_mode: 'browser' | 'server';
  stt_base_url: string;
  stt_model: string;
  tts_base_url: string;
  tts_model: string;
  tts_voice: string;
  tts_format: 'mp3' | 'wav';
  verify_tls: boolean;
  has_stt_api_key: boolean;
  has_tts_api_key: boolean;
}

const QUERY_KEY = ['speech-settings'];
const TTS_VOICES = ['alloy', 'ash', 'ballad', 'cedar', 'coral', 'echo', 'fable', 'marin', 'nova', 'onyx', 'sage', 'shimmer', 'verse'];
const MODEL_ERRORS: Record<string, TranslationKey> = {
  tls_certificate: 'llmModelsTlsError',
  timeout: 'llmModelsTimeout',
  connection: 'llmModelsConnectError',
  authentication: 'llmModelsAuthError',
  not_found: 'llmModelsNotFound',
  invalid_response: 'llmModelsFormatError',
};

function useSpeechModels(
  provider: 'stt' | 'tts',
  endpoint: string,
  apiKey: string,
  clearKey: boolean,
  verifyTls: boolean,
  refresh: number,
) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<TranslationKey | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setModels([]);
    setError(null);
    setLoading(!!endpoint);
    if (!endpoint) return () => controller.abort();
    const timer = window.setTimeout(async () => {
      try {
        const result = await api<{ models: string[] }>(
          '/settings/speech/models',
          { provider, base_url: endpoint, ...(apiKey ? { api_key: apiKey } : {}), clear_api_key: clearKey, verify_tls: verifyTls },
          'POST',
          controller.signal,
        );
        if (!controller.signal.aborted) setModels(result.models);
      } catch (err) {
        if (!controller.signal.aborted)
          setError(err instanceof ApiError ? MODEL_ERRORS[err.code || ''] || 'llmModelsError' : 'llmModelsError');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [provider, endpoint, apiKey, clearKey, verifyTls, refresh]);
  return { models, loading, error };
}

function ModelStatus({
  models,
  loading,
  error,
  endpoint,
  label,
  refreshLabel,
  onRefresh,
}: {
  models: string[];
  loading: boolean;
  error: TranslationKey | null;
  endpoint: string;
  label: (en: string, danish: string) => string;
  refreshLabel: string;
  onRefresh: () => void;
}) {
  const t = useT();
  return (
    <div className="speech-model-status">
      <span role="status">
        {t(loading ? 'llmModelsLoading' : error || (!endpoint ? 'llmModelsEndpoint' : models.length ? 'llmModelsLoaded' : 'llmModelsEmpty'))}
      </span>
      <button className="text-button" type="button" disabled={!endpoint || loading} onClick={onRefresh}>
        <RefreshCw size={14} />
        {refreshLabel || label('Refresh models', 'Opdater modeller')}
      </button>
    </div>
  );
}
/** Self-loading settings form; mount this component inside the Settings page. */
export function SpeechSettings() {
  const lang = useContext(LocaleContext);
  const t = useT();
  const da = lang === 'da';
  const label = (en: string, danish: string) => (da ? danish : en);
  const client = useQueryClient();
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => api<SpeechSettingsValue>('/settings/speech'),
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<SpeechSettingsValue | null>(null);
  const [sttKey, setSttKey] = useState('');
  const [ttsKey, setTtsKey] = useState('');
  const [clearSttKey, setClearSttKey] = useState(false);
  const [clearTtsKey, setClearTtsKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [refreshSttModels, setRefreshSttModels] = useState(0);
  const [refreshTtsModels, setRefreshTtsModels] = useState(0);
  const [testRecording, setTestRecording] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState('');
  const [testError, setTestError] = useState('');
  const [ttsTestBusy, setTtsTestBusy] = useState(false);
  const [ttsTestUrl, setTtsTestUrl] = useState('');
  const [ttsTestError, setTtsTestError] = useState('');
  const testRecorder = useRef<MediaRecorder | null>(null);
  const testStream = useRef<MediaStream | null>(null);
  const testChunks = useRef<Blob[]>([]);
  const sttModels = useSpeechModels('stt', draft?.stt_base_url.trim().replace(/\/+$/, '') || '', sttKey, clearSttKey, draft?.verify_tls ?? true, refreshSttModels);
  const ttsModels = useSpeechModels('tts', draft?.tts_base_url.trim().replace(/\/+$/, '') || '', ttsKey, clearTtsKey, draft?.verify_tls ?? true, refreshTtsModels);
  const useCustomSttModel = !sttModels.models.includes(draft?.stt_model || '');
  const useCustomTtsModel = !ttsModels.models.includes(draft?.tts_model || '');
  const useCustomTtsVoice = !TTS_VOICES.includes(draft?.tts_voice || '');

  useEffect(() => {
    if (query.data) setDraft((current) => current || query.data);
  }, [query.data]);

  useEffect(() => () => {
    if (testRecorder.current?.state === 'recording') testRecorder.current.stop();
    testStream.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => () => {
    if (ttsTestUrl) URL.revokeObjectURL(ttsTestUrl);
  }, [ttsTestUrl]);

  const sttConfigSaved = !!query.data && !!draft && query.data.stt_mode === 'server' && draft.stt_mode === 'server'
    && draft.stt_base_url === query.data.stt_base_url
    && draft.stt_model === query.data.stt_model
    && draft.verify_tls === query.data.verify_tls
    && !sttKey && !clearSttKey;
  const ttsConfigSaved = !!query.data && !!draft && query.data.tts_mode === 'server' && draft.tts_mode === 'server'
    && draft.tts_base_url === query.data.tts_base_url
    && draft.tts_model === query.data.tts_model
    && draft.tts_voice === query.data.tts_voice
    && draft.tts_format === query.data.tts_format
    && draft.verify_tls === query.data.verify_tls
    && !ttsKey && !clearTtsKey;

  async function testTts() {
    setTtsTestBusy(true);
    setTtsTestError('');
    setTtsTestUrl('');
    try {
      const audio = await synthesizeSpeech(
        da ? 'Dette er en test af talesyntesen.' : 'This is a test of speech synthesis.',
        da ? 'da' : 'en',
      );
      setTtsTestUrl(URL.createObjectURL(audio));
    } catch (error) {
      setTtsTestError(error instanceof Error ? error.message : label('TTS test failed.', 'TTS-test mislykkedes.'));
    } finally {
      setTtsTestBusy(false);
    }
  }

  async function startSttTest() {
    setTestError('');
    setTestResult('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        throw new Error(label('Audio recording is not supported in this browser.', 'Lydoptagelse understøttes ikke i denne browser.'));
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      testStream.current = stream;
      const recorder = new MediaRecorder(stream);
      testChunks.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) testChunks.current.push(event.data);
      };
      recorder.onstop = async () => {
        setTestRecording(false);
        setTestBusy(true);
        stream.getTracks().forEach((track) => track.stop());
        testStream.current = null;
        try {
          const mimeType = recorder.mimeType || testChunks.current[0]?.type || 'audio/webm';
          const audio = new Blob(testChunks.current, { type: mimeType });
          const result = await transcribeAudio(audio, mimeType);
          setTestResult(result);
        } catch (error) {
          setTestError(error instanceof Error ? error.message : label('STT test failed.', 'STT-test mislykkedes.'));
        } finally {
          setTestBusy(false);
          testRecorder.current = null;
        }
      };
      testRecorder.current = recorder;
      recorder.start();
      setTestRecording(true);
    } catch (error) {
      testStream.current?.getTracks().forEach((track) => track.stop());
      testStream.current = null;
      setTestRecording(false);
      setTestError(error instanceof Error ? error.message : label('Could not start the STT test.', 'STT-testen kunne ikke startes.'));
    }
  }

  function stopSttTest() {
    if (testRecorder.current?.state === 'recording') testRecorder.current.stop();
  }

  function change(values: Partial<SpeechSettingsValue>) {
    setDraft((current) => (current ? { ...current, ...values } : current));
    setSaved(false);
  }

  return (
    <section className="settings-section speech-settings" aria-labelledby="speech-settings-title">
      <div>
        <h2 id="speech-settings-title">{label('Speech providers', 'Taleudbydere')}</h2>
        <p>
          {label(
            'Choose browser speech or configure compatible speech services independently for recognition and replies. API keys are stored on this server and never shown again.',
            'Vælg tale i browseren, eller konfigurér kompatible tjenester uafhængigt for genkendelse og svar. API-nøgler gemmes på denne server og vises ikke igen.',
          )}
        </p>
      </div>
      <div className="speech-settings-fields">
        <ErrorNotice error={query.error || saveError} />
        {query.isPending ? (
          <Spinner />
        ) : draft ? (
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              setBusy(true);
              setSaved(false);
              setSaveError(null);
              try {
                const result = await api<SpeechSettingsValue>(
                  '/settings/speech',
                  {
                    stt_mode: draft.stt_mode,
                    tts_mode: draft.tts_mode,
                    stt_base_url: draft.stt_base_url,
                    stt_model: draft.stt_model,
                    tts_base_url: draft.tts_base_url,
                    tts_model: draft.tts_model,
                    tts_voice: draft.tts_voice,
                    tts_format: draft.tts_format,
                    verify_tls: draft.verify_tls,
                    ...(sttKey ? { stt_api_key: sttKey } : {}),
                    ...(ttsKey ? { tts_api_key: ttsKey } : {}),
                    clear_stt_api_key: clearSttKey,
                    clear_tts_api_key: clearTtsKey,
                  },
                  'PATCH',
                );
                client.setQueryData(QUERY_KEY, result);
                setDraft(result);
                setSttKey('');
                setTtsKey('');
                setClearSttKey(false);
                setClearTtsKey(false);
                setSaved(true);
              } catch (error) {
                setSaveError(error);
              } finally {
                setBusy(false);
              }
            }}
          >
            <fieldset disabled={busy}>
              <div className="speech-provider-grid">
                <section className="speech-provider" aria-labelledby="speech-stt-title">
                  <h3 id="speech-stt-title">{label('Speech recognition (STT)', 'Talegenkendelse (STT)')}</h3>
                  <Field label={label('Speech recognition provider', 'Udbyder af talegenkendelse')}>
                    <select
                      value={draft.stt_mode}
                      onChange={(event) => change({ stt_mode: event.target.value as SpeechSettingsValue['stt_mode'] })}
                    >
                      <option value="browser">{label('Browser', 'Browser')}</option>
                      <option value="server">{label('OpenAI-compatible server', 'OpenAI-kompatibel server')}</option>
                    </select>
                  </Field>
                  {draft.stt_mode === 'server' && (
                    <>
                      <Field label={label('Endpoint URL', 'Endpoint-URL')}>
                        <input
                          type="url"
                          value={draft.stt_base_url}
                          placeholder="https://speech.example.com/v1"
                          maxLength={2000}
                          onChange={(event) => change({ stt_base_url: event.target.value })}
                        />
                      </Field>
                      <Field label={label('STT model', 'STT-model')}>
                        <select
                          value={useCustomSttModel ? 'custom' : draft.stt_model ? `model:${draft.stt_model}` : ''}
                          onChange={(event) => change({ stt_model: event.target.value === 'custom' || !event.target.value ? '' : event.target.value.slice(6) })}
                        >
                          <option value="" disabled>{t('llmSelectModel')}</option>
                          {sttModels.models.map((model) => <option key={model} value={`model:${model}`}>{model}</option>)}
                          <option value="custom">{label('Custom…', 'Brugerdefineret…')}</option>
                        </select>
                        {useCustomSttModel && <input
                          value={draft.stt_model}
                          placeholder={label('Enter model name', 'Indtast modelnavn')}
                          maxLength={200}
                          onChange={(event) => change({ stt_model: event.target.value })}
                        />}
                        <ModelStatus models={sttModels.models} loading={sttModels.loading} error={sttModels.error} endpoint={draft.stt_base_url} label={label} refreshLabel={t('llmRefreshModels')} onRefresh={() => setRefreshSttModels((value) => value + 1)} />
                      </Field>
                      <Field label={label('API key', 'API-nøgle')}>
                        <input
                          type="password"
                          value={sttKey}
                          autoComplete="new-password"
                          maxLength={4096}
                          placeholder={draft.has_stt_api_key && !clearSttKey ? label('Saved; leave blank to keep', 'Gemt; lad feltet være tomt for at beholde') : label('Optional', 'Valgfri')}
                          onChange={(event) => {
                            setSttKey(event.target.value);
                            setClearSttKey(false);
                            setSaved(false);
                          }}
                        />
                        <small>{label('Leave blank to keep the saved key. Enter a new key to replace it.', 'Lad feltet være tomt for at beholde den gemte nøgle. Indtast en ny for at erstatte den.')}</small>
                      </Field>
                      {draft.has_stt_api_key && (
                        <Toggle
                          label={label('Remove saved STT key', 'Fjern gemt STT-nøgle')}
                          checked={clearSttKey}
                          onChange={(value) => {
                            setClearSttKey(value);
                            setSttKey('');
                            setSaved(false);
                          }}
                        />
                      )}
                      <div className="speech-provider-test">
                        <button
                          className="text-button"
                          type="button"
                          disabled={testBusy || (!testRecording && !sttConfigSaved)}
                          onClick={testRecording ? stopSttTest : () => void startSttTest()}
                        >
                          {testBusy ? <Spinner /> : testRecording ? <Square size={15} /> : <Mic size={15} />}
                          {testBusy
                            ? label('Transcribing…', 'Transskriberer…')
                            : testRecording
                              ? label('Stop and transcribe', 'Stop og transskriber')
                              : label('Test STT', 'Test STT')}
                        </button>
                        {!sttConfigSaved && <small>{label('Save the STT settings before testing.', 'Gem STT-indstillingerne før testen.')}</small>}
                        {testResult && <p role="status">{label('Recognized:', 'Genkendt:')} {testResult}</p>}
                        {testError && <p role="alert" className="speech-provider-test-error">{testError}</p>}
                      </div>
                    </>
                  )}
                </section>

                <section className="speech-provider" aria-labelledby="speech-tts-title">
                  <h3 id="speech-tts-title">{label('Speech synthesis (TTS)', 'Talesyntese (TTS)')}</h3>
                  <Field label={label('Speech synthesis provider', 'Udbyder af talesyntese')}>
                    <select
                      value={draft.tts_mode}
                      onChange={(event) => change({ tts_mode: event.target.value as SpeechSettingsValue['tts_mode'] })}
                    >
                      <option value="browser">{label('Browser', 'Browser')}</option>
                      <option value="server">{label('OpenAI-compatible server', 'OpenAI-kompatibel server')}</option>
                    </select>
                  </Field>
                  {draft.tts_mode === 'server' && (
                    <>
                      <Field label={label('Endpoint URL', 'Endpoint-URL')}>
                        <input
                          type="url"
                          value={draft.tts_base_url}
                          placeholder="https://speech.example.com/v1"
                          maxLength={2000}
                          onChange={(event) => change({ tts_base_url: event.target.value })}
                        />
                      </Field>
                      <Field label={label('TTS model', 'TTS-model')}>
                        <select
                          value={useCustomTtsModel ? 'custom' : draft.tts_model ? `model:${draft.tts_model}` : ''}
                          onChange={(event) => change({ tts_model: event.target.value === 'custom' || !event.target.value ? '' : event.target.value.slice(6) })}
                        >
                          <option value="" disabled>{t('llmSelectModel')}</option>
                          {ttsModels.models.map((model) => <option key={model} value={`model:${model}`}>{model}</option>)}
                          <option value="custom">{label('Custom…', 'Brugerdefineret…')}</option>
                        </select>
                        {useCustomTtsModel && <input
                          value={draft.tts_model}
                          placeholder={label('Enter model name', 'Indtast modelnavn')}
                          maxLength={200}
                          onChange={(event) => change({ tts_model: event.target.value })}
                        />}
                        <ModelStatus models={ttsModels.models} loading={ttsModels.loading} error={ttsModels.error} endpoint={draft.tts_base_url} label={label} refreshLabel={t('llmRefreshModels')} onRefresh={() => setRefreshTtsModels((value) => value + 1)} />
                      </Field>
                      <Field label={label('Voice', 'Stemme')}>
                        <select
                          value={useCustomTtsVoice ? 'custom' : draft.tts_voice}
                          onChange={(event) => change({ tts_voice: event.target.value === 'custom' ? '' : event.target.value })}
                        >
                          {TTS_VOICES.map((voice) => <option key={voice} value={voice}>{voice}</option>)}
                          <option value="custom">{label('Custom…', 'Brugerdefineret…')}</option>
                        </select>
                        {useCustomTtsVoice && <input
                          value={draft.tts_voice}
                          placeholder={label('Enter voice name', 'Indtast stemmenavn')}
                          maxLength={200}
                          onChange={(event) => change({ tts_voice: event.target.value })}
                        />}
                      </Field>
                      <Field label={label('Audio format', 'Lydformat')}>
                        <select
                          value={draft.tts_format}
                          onChange={(event) => change({ tts_format: event.target.value as SpeechSettingsValue['tts_format'] })}
                        >
                          <option value="mp3">MP3</option>
                          <option value="wav">WAV</option>
                        </select>
                      </Field>
                      <Field label={label('API key', 'API-nøgle')}>
                        <input
                          type="password"
                          value={ttsKey}
                          autoComplete="new-password"
                          maxLength={4096}
                          placeholder={draft.has_tts_api_key && !clearTtsKey ? label('Saved; leave blank to keep', 'Gemt; lad feltet være tomt for at beholde') : label('Optional', 'Valgfri')}
                          onChange={(event) => {
                            setTtsKey(event.target.value);
                            setClearTtsKey(false);
                            setSaved(false);
                          }}
                        />
                        <small>{label('Leave blank to keep the saved key. Enter a new key to replace it.', 'Lad feltet være tomt for at beholde den gemte nøgle. Indtast en ny for at erstatte den.')}</small>
                      </Field>
                      {draft.has_tts_api_key && (
                        <Toggle
                          label={label('Remove saved TTS key', 'Fjern gemt TTS-nøgle')}
                          checked={clearTtsKey}
                          onChange={(value) => {
                            setClearTtsKey(value);
                            setTtsKey('');
                            setSaved(false);
                          }}
                        />
                      )}
                      <div className="speech-provider-test">
                        <button className="text-button" type="button" disabled={!ttsConfigSaved || ttsTestBusy} onClick={() => void testTts()}>
                          {ttsTestBusy ? <Spinner /> : <Mic size={15} />}
                          {ttsTestBusy ? label('Testing…', 'Tester…') : label('Test TTS', 'Test TTS')}
                        </button>
                        {!ttsConfigSaved && <small>{label('Save the TTS settings before testing.', 'Gem TTS-indstillingerne før testen.')}</small>}
                        {ttsTestUrl && <audio controls src={ttsTestUrl}>{label('Audio playback is not supported in this browser.', 'Lydafspilning understøttes ikke i denne browser.')}</audio>}
                        {ttsTestError && <p role="alert" className="speech-provider-test-error">{ttsTestError}</p>}
                      </div>
                    </>
                  )}
                </section>
              </div>
              {(draft.stt_mode === 'server' || draft.tts_mode === 'server') && (
                <div className="speech-security">
                  <Field label={label('TLS certificate verification', 'Kontrol af TLS-certifikat')}>
                    <select
                      value={draft.verify_tls ? 'verify' : 'ignore'}
                      onChange={(event) => change({ verify_tls: event.target.value === 'verify' })}
                    >
                      <option value="verify">{label('Verify certificates', 'Kontrollér certifikater')}</option>
                      <option value="ignore">{label('Ignore certificate errors', 'Ignorér certifikatfejl')}</option>
                    </select>
                    <small>{label('Keep verification enabled unless you use a trusted private certificate.', 'Lad kontrollen være aktiveret, medmindre du bruger et betroet privat certifikat.')}</small>
                  </Field>
                  {!draft.verify_tls && (
                    <p role="status" className="speech-security-warning">
                      {label('Certificate checks are disabled. Use this only with a trusted server.', 'Certifikatkontrol er slået fra. Brug kun dette med en betroet server.')}
                    </p>
                  )}
                </div>
              )}
              <div className="speech-settings-actions">
                {saved && <span role="status"><Check size={16} />{label('Saved', 'Gemt')}</span>}
                <button className="primary-button" type="submit" disabled={busy || testRecording || testBusy || ttsTestBusy}>
                  {busy ? <Spinner /> : <Save size={17} />}
                  {label('Save speech settings', 'Gem taleindstillinger')}
                </button>
              </div>
            </fieldset>
          </form>
        ) : null}
      </div>
    </section>
  );
}
