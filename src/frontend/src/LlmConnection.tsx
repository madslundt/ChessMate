import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Save } from 'lucide-react';
import { api } from './api';
import { useT } from './i18n';
import { ErrorNotice, Field, Spinner, Toggle } from './components';

interface Connection {
  base_url: string;
  model: string;
  has_api_key: boolean;
  configured: boolean;
}

export function LlmConnection() {
  const t = useT();
  const client = useQueryClient();
  const connection = useQuery({
    queryKey: ['llm-connection'],
    queryFn: () => api<Connection>('/settings/llm'),
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<Connection | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (connection.data) setDraft((current) => current || connection.data);
  }, [connection.data]);
  function change(values: Partial<Connection>) {
    setDraft((current) => (current ? { ...current, ...values } : current));
    setSaved(false);
  }
  return (
    <form
      className="settings-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!draft) return;
        setBusy(true);
        setError(null);
        setSaved(false);
        try {
          const result = await api<Connection>(
            '/settings/llm',
            {
              base_url: draft.base_url,
              model: draft.model,
              ...(apiKey ? { api_key: apiKey } : {}),
              clear_api_key: clearKey,
            },
            'PATCH',
          );
          client.setQueryData(['llm-connection'], result);
          setDraft(result);
          setApiKey('');
          setClearKey(false);
          setSaved(true);
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      <section className="settings-section" aria-labelledby="llm-connection-title">
        <div>
          <h2 id="llm-connection-title">{t('llmConnection')}</h2>
          <p>{t('llmAccountHelp')}</p>
          {connection.data && <p>{t(connection.data.configured ? 'llmConfigured' : 'llmNotConfigured')}</p>}
        </div>
        <div className="llm-connection">
          <ErrorNotice error={connection.error || error} />
          {connection.isPending ? (
            <Spinner />
          ) : (
            draft && (
              <fieldset disabled={busy}>
                <Field label={t('llmEndpoint')}>
                  <input
                    type="url"
                    value={draft.base_url}
                    placeholder="http://host.docker.internal:8000/v1"
                    maxLength={2000}
                    onChange={(e) => change({ base_url: e.target.value })}
                  />
                  <small>{t('llmEndpointHelp')}</small>
                </Field>
                <Field label={t('llmModel')}>
                  <input
                    value={draft.model}
                    placeholder="your-served-model"
                    maxLength={200}
                    onChange={(e) => change({ model: e.target.value })}
                  />
                </Field>
                <Field label={t('llmApiKey')}>
                  <input
                    type="password"
                    value={apiKey}
                    autoComplete="new-password"
                    maxLength={4096}
                    placeholder={draft.has_api_key && !clearKey ? t('llmKeySaved') : t('optional')}
                    onChange={(e) => {
                      setApiKey(e.target.value);
                      setClearKey(false);
                      setSaved(false);
                    }}
                  />
                  <small>{t('llmKeyHelp')}</small>
                </Field>
                {draft.has_api_key && (
                  <Toggle
                    label={t('llmRemoveKey')}
                    checked={clearKey}
                    onChange={(value) => {
                      setClearKey(value);
                      setApiKey('');
                      setSaved(false);
                    }}
                  />
                )}
                {draft.has_api_key && draft.base_url.trim().replace(/\/+$/, '') !== connection.data?.base_url && (
                  <p>{t('llmEndpointKeyHelp')}</p>
                )}
                <p>{t('llmFallbackHelp')}</p>
                <div className="llm-actions">
                  {saved && (
                    <span role="status">
                      <Check size={16} />
                      {t('llmSaved')}
                    </span>
                  )}
                  <button className="primary-button" type="submit" disabled={!draft || busy}>
                    {busy ? <Spinner /> : <Save size={17} />}
                    {t('llmSave')}
                  </button>
                </div>
              </fieldset>
            )
          )}
        </div>
      </section>
    </form>
  );
}
