import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, RefreshCw, Save } from 'lucide-react';
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
  const [customModel, setCustomModel] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState(false);
  const [refreshModels, setRefreshModels] = useState(0);
  const endpoint = draft?.base_url.trim().replace(/\/+$/, '') || '';
  useEffect(() => {
    const controller = new AbortController();
    setModels([]);
    setModelsError(false);
    setModelsLoading(!!endpoint);
    if (!endpoint) return;
    // Debounce edits; secrets are sent only in the request body, never query/cache keys.
    const timer = window.setTimeout(async () => {
      try {
        const result = await api<{ models: string[] }>('/settings/llm/models', {
          base_url: endpoint,
          ...(apiKey ? { api_key: apiKey } : {}),
          clear_api_key: clearKey,
        }, 'POST', controller.signal);
        if (!controller.signal.aborted) setModels(result.models);
      } catch {
        if (!controller.signal.aborted) setModelsError(true);
      } finally {
        if (!controller.signal.aborted) setModelsLoading(false);
      }
    }, 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [endpoint, apiKey, clearKey, refreshModels]);
  const useCustomModel = customModel || (!!draft?.model && !models.includes(draft.model));
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
                  <select value={useCustomModel ? 'custom' : draft.model ? `model:${draft.model}` : ''}
                    onChange={(event) => {
                      const custom = event.target.value === 'custom';
                      setCustomModel(custom);
                      change({ model: custom ? '' : event.target.value.slice(6) });
                    }}>
                    <option value="" disabled>{t('llmSelectModel')}</option>
                    {models.map((model) => <option key={model} value={`model:${model}`}>{model}</option>)}
                    <option value="custom">{t('llmCustomModel')}</option>
                  </select>
                </Field>
                {useCustomModel && <Field label={t('llmCustomModelName')}>
                  <input value={draft.model} placeholder="your-served-model" maxLength={200}
                    onChange={(event) => change({ model: event.target.value })} />
                </Field>}
                <div className="llm-model-status">
                  <span role="status">
                    {t(modelsLoading ? 'llmModelsLoading' : modelsError ? 'llmModelsError'
                      : !endpoint ? 'llmModelsEndpoint' : models.length ? 'llmModelsLoaded' : 'llmModelsEmpty')}
                  </span>
                  <button className="text-button" type="button" disabled={!endpoint || modelsLoading}
                    onClick={() => setRefreshModels((current) => current + 1)}>
                    <RefreshCw size={14} />{t('llmRefreshModels')}
                  </button>
                </div>
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
