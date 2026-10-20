import { useContext, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Save } from 'lucide-react';
import { api } from './api';
import { LocaleContext } from './i18n';
import { ErrorNotice, Field, Spinner, Toggle } from './components';
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
  verify_tls: boolean;
  has_stt_api_key: boolean;
  has_tts_api_key: boolean;
}

const QUERY_KEY = ['speech-settings'];
/** Self-loading settings form; mount this component inside the Settings page. */
export function SpeechSettings() {
  const lang = useContext(LocaleContext);
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

  useEffect(() => {
    if (query.data) setDraft((current) => current || query.data);
  }, [query.data]);

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
                        <input
                          value={draft.stt_model}
                          placeholder="whisper-1"
                          maxLength={200}
                          onChange={(event) => change({ stt_model: event.target.value })}
                        />
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
                        <input
                          value={draft.tts_model}
                          placeholder="tts-1"
                          maxLength={200}
                          onChange={(event) => change({ tts_model: event.target.value })}
                        />
                      </Field>
                      <Field label={label('Voice', 'Stemme')}>
                        <input
                          value={draft.tts_voice}
                          placeholder="alloy"
                          maxLength={100}
                          onChange={(event) => change({ tts_voice: event.target.value })}
                        />
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
                <button className="primary-button" type="submit" disabled={busy}>
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
