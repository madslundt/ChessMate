import { useState } from 'react';
import { ErrorNotice, Field, Modal, PageHeading, Spinner } from './components';
import { useT } from './i18n';
import type { Color, Preferences } from './types';
import { Link } from './navigation';

export function GameSetup({
  analysisMode,
  preferences,
  onClose,
  onStart,
}: {
  analysisMode: boolean;
  preferences: Preferences;
  onClose: () => void;
  onStart: (body: Record<string, unknown>) => Promise<void>;
}) {
  const t = useT(),
    [color, setColor] = useState(preferences.player_color),
    [difficulty, setDifficulty] = useState(preferences.difficulty),
    [difficultyMode, setDifficultyMode] = useState(preferences.difficulty_mode || 'adaptive'),
    [mode, setMode] = useState(analysisMode ? 'analysis' : 'training'),
    [busy, setBusy] = useState(false);
  return (
    <Modal title={t('newGame')} onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onStart({
              mode,
              player_color: color,
              difficulty,
              difficulty_mode: difficultyMode,
            });
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label={t('mode')}>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="training">{t('training')}</option>
            <option value="computer">{t('computer')}</option>
            <option value="analysis">{t('freeAnalysis')}</option>
          </select>
        </Field>
        <Field label={t('color')}>
          <select value={color} onChange={(e) => setColor(e.target.value as Color)}>
            <option value="white">{t('white')}</option>
            <option value="black">{t('black')}</option>
          </select>
        </Field>
        <Field label={t('difficulty')}>
          <select
            aria-label={t('difficulty')}
            value={difficultyMode}
            onChange={(event) => setDifficultyMode(event.target.value as typeof difficultyMode)}
          >
            <option value="adaptive">{t('adaptiveDifficulty')}</option>
            <option value="manual">{t('manualDifficulty')}</option>
          </select>
          <small>{t('adaptiveDifficultyHelp')}</small>
        </Field>
        {difficultyMode === 'manual' && (
          <Field label={t('manualDifficulty')}>
            <input type="range" min="1" max="5" value={difficulty} onChange={(e) => setDifficulty(+e.target.value)} />
            <span>
              {difficulty} / 5 · {t(difficulty > 3 ? 'intermediate' : 'beginner')}
            </span>
          </Field>
        )}
        <div className="modal-footer">
          <button type="button" className="outline-button" onClick={onClose}>
            {t('cancel')}
          </button>
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? <Spinner /> : t('start')}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function ImportModal({
  onClose,
  onImport,
}: {
  onClose: () => void;
  onImport: (value: string) => Promise<void>;
}) {
  const t = useT(),
    [value, setValue] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal title={t('importPgn')} onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onImport(value);
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="muted">{t('importHelp')}</p>
        <textarea
          aria-label="FEN / PGN"
          className="import-area"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          maxLength={100000}
          required
        />
        <ErrorNotice error={error} />
        <button className="primary-button" disabled={busy}>
          {busy ? <Spinner /> : t('load')}
        </button>
      </form>
    </Modal>
  );
}

export function GameLoading({
  analysisMode,
  preferences,
  pending,
  error,
  onRetry,
}: {
  analysisMode: boolean;
  preferences: Preferences;
  pending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeading title={t(analysisMode ? 'analyze' : 'play')} />
      {pending ? (
        <Spinner label={t('thinking')} />
      ) : (
        <>
          <ErrorNotice
            error={
              error ||
              new Error(
                preferences.language === 'da'
                  ? 'Spillet hører til en anden side.'
                  : 'This game belongs to a different workspace.',
              )
            }
          />
          <button className="outline-button" onClick={onRetry}>
            {preferences.language === 'da' ? 'Prøv igen' : 'Try again'}
          </button>
          <Link className="primary-button" href={analysisMode ? '/analyze' : '/play'}>
            {t(analysisMode ? 'backGames' : 'newGame')}
          </Link>
        </>
      )}
    </>
  );
}
