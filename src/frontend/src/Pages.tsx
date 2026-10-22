import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronRight, Clock3, Save, Upload } from 'lucide-react';
import { api } from './api';
import { Empty, ErrorNotice, Field, PageHeading, Spinner, Toggle } from './components';
import { useT, type TranslationKey } from './i18n';
import type { Game, Preferences } from './types';
import { LlmConnection } from './LlmConnection';
import { SpeechSettings } from './SpeechSettings';
import { CoachingPreferences } from './CoachingPreferences';
import { ImportModal } from './GameDialogs';
import { gamePath, Link } from './navigation';
export function History({
  onResume,
  preferences,
  analysisMode = false,
}: {
  onResume: (g: Game) => void;
  preferences: Preferences;
  analysisMode?: boolean;
}) {
  const t = useT(),
    client = useQueryClient(),
    [importing, setImporting] = useState(false),
    games = useQuery({
      queryKey: ['games'],
      queryFn: ({ signal }) => api<Game[]>('/games', undefined, undefined, signal),
      retry: false,
    });
  return (
    <>
      <PageHeading
        title={t(analysisMode ? 'analyze' : 'history')}
        subtitle={analysisMode ? t('analysisListHelp') : undefined}
      >
        {analysisMode && (
          <button className="primary-button" onClick={() => setImporting(true)}>
            <Upload size={19} />
            {t('importPgn')}
          </button>
        )}
      </PageHeading>
      <ErrorNotice error={games.error} />
      {games.isError && (
        <button className="outline-button" onClick={() => void games.refetch()}>
          {t('retryAnalysis')}
        </button>
      )}
      {games.isPending ? (
        <Spinner />
      ) : !games.data?.length ? (
        !games.isError && (
          <Empty>
            <Clock3 size={32} />
            <p>{t(analysisMode ? 'emptyAnalysis' : 'emptyGames')}</p>
            {analysisMode && (
              <Link className="primary-button" href="/play">
                {t('playGame')}
              </Link>
            )}
          </Empty>
        )
      ) : (
        <section className="history-list panel" aria-label={t('savedGames')}>
          {games.data.map((g) => (
            <Link
              className="history-row"
              key={g.id}
              href={analysisMode ? `/analyze/${encodeURIComponent(g.id)}` : gamePath(g)}
              onClick={(event) => {
                if (
                  !analysisMode &&
                  event.button === 0 &&
                  !event.metaKey &&
                  !event.ctrlKey &&
                  !event.shiftKey &&
                  !event.altKey
                ) {
                  event.preventDefault();
                  onResume(g);
                }
              }}
            >
              <span className="history-piece">{g.player_color === 'white' ? '♔' : '♚'}</span>
              <div>
                <strong>
                  {t(g.mode === 'analysis' ? 'freeAnalysis' : g.mode === 'training' ? 'training' : 'computer')}
                </strong>
                <small>
                  {g.created_at && (
                    <>
                      {new Date(g.created_at).toLocaleDateString(preferences.language === 'da' ? 'da-DK' : 'en-GB', {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}{' '}
                      ·{' '}
                    </>
                  )}
                  {Math.ceil(g.moves.length / 2)} {t('moves').toLowerCase()}
                  {analysisMode && <> · {t(g.player_color)}</>}
                </small>
              </div>
              <span className="history-result">
                {!g.result || g.result === '*'
                  ? t('active')
                  : analysisMode
                    ? t(
                        g.result === '1/2-1/2'
                          ? 'draw'
                          : g.result === (g.player_color === 'white' ? '1-0' : '0-1')
                            ? 'victory'
                            : 'defeat',
                      )
                    : g.result}
              </span>
              <span className="history-resume">{t(analysisMode ? 'review' : 'resume')}</span>
              <ChevronRight size={18} />
            </Link>
          ))}
        </section>
      )}
      {importing && (
        <ImportModal
          onClose={() => setImporting(false)}
          onImport={async (value) => {
            const isFen = value.trim().split(/\s+/).length === 6 && !value.includes('[');
            const game = await api<Game>('/games', {
              mode: 'analysis',
              player_color: preferences.player_color,
              difficulty: preferences.difficulty,
              ...(isFen ? { fen: value.trim() } : { pgn: value.trim() }),
            });
            void client.invalidateQueries({ queryKey: ['games'] });
            setImporting(false);
            onResume(game);
          }}
        />
      )}
    </>
  );
}
export { ProgressPage } from './LearningProgress';
export function SettingsPage({
  preferences,
  onSaved,
}: {
  preferences: Preferences;
  onSaved: (p: Preferences) => void;
}) {
  const t = useT(),
    [draft, setDraft] = useState(preferences),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [saved, setSaved] = useState(false);
  const previousPreferences = useRef(preferences);
  const dirtyFields = useRef(new Set<keyof Preferences>());
  useEffect(() => {
    const previous = previousPreferences.current;
    previousPreferences.current = preferences;
    // Profiles hydrate after the first render; merge external changes without losing unrelated drafts.
    const changes = Object.fromEntries(
      Object.entries(preferences).filter(
        ([key, value]) =>
          !dirtyFields.current.has(key as keyof Preferences) && value !== previous[key as keyof Preferences],
      ),
    );
    setDraft((current) => ({ ...current, ...changes }));
  }, [preferences]);
  function set<K extends keyof Preferences>(k: K, v: Preferences[K]) {
    dirtyFields.current.add(k);
    const manual = ['feedback', 'max_explanation_length', 'show_pv', 'candidate_count'].includes(k);
    if (manual) dirtyFields.current.add('skill_defaults');
    setDraft((d) => ({
      ...d,
      [k]: v,
      ...(manual ? { skill_defaults: false } : {}),
    }));
    setSaved(false);
  }
  const select = <K extends keyof Preferences>(
    key: K,
    label: TranslationKey,
    options: [string, TranslationKey | string][],
  ) => (
    <Field label={t(label)}>
      <select
        value={String(draft[key])}
        onChange={(e) =>
          set(key, (typeof draft[key] === 'number' ? Number(e.target.value) : e.target.value) as Preferences[K])
        }
      >
        {options.map(([v, l]) => (
          <option value={v} key={v}>
            {t(l as TranslationKey) || l}
          </option>
        ))}
      </select>
    </Field>
  );
  const toggle = (key: keyof Preferences, label: TranslationKey) => (
    <Toggle label={t(label)} checked={!!draft[key]} onChange={(v) => set(key, v as never)} />
  );
  return (
    <>
      <PageHeading title={t('settings')} />
      <LlmConnection />
      <SpeechSettings />
      <form
        className="settings-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const p = await api<Preferences>('/settings', draft, 'PATCH');
            dirtyFields.current.clear();
            setDraft(p);
            onSaved(p);
            setSaved(true);
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <section className="settings-section">
          <div>
            <h2>{t('appearance')}</h2>
          </div>
          <div className="settings-fields">
            {select('theme', 'theme', [
              ['light', 'light'],
              ['dark', 'dark'],
              ['system', 'system'],
            ])}
            {select('language', 'language', [
              ['en', 'English'],
              ['da', 'Dansk'],
            ])}
            {select('board_theme', 'boardTheme', [
              ['sage', 'sage'],
              ['wood', 'wood'],
              ['blue', 'blue'],
            ])}
            {select('piece_style', 'pieces', [
              ['classic', 'classic'],
              ['modern', 'modern'],
            ])}
          </div>
        </section>
        <section className="settings-section">
          <div>
            <h2>{t('gameplay')}</h2>
          </div>
          <div className="settings-fields">
            {select('player_color', 'color', [
              ['white', 'white'],
              ['black', 'black'],
            ])}
            {select('difficulty_mode', 'difficulty', [
              ['adaptive', 'adaptiveDifficulty'],
              ['manual', 'manualDifficulty'],
            ])}
            {select(
              'difficulty',
              'difficulty',
              Array.from({ length: 5 }, (_, i) => [String(i + 1), `${i + 1} / 5`]),
            )}
            {select('orientation', 'orientation', [
              ['player', 'you'],
              ['white', 'white'],
              ['black', 'black'],
            ])}
            {toggle('show_legal_moves', 'legalMoves')}
            {toggle('show_evaluation_bar', 'evaluationBar')}
          </div>
        </section>
        <section className="settings-section">
          <div>
            <h2>{t('coaching')}</h2>
          </div>
          <div className="settings-fields">
            <CoachingPreferences
              value={draft}
              onChange={(changes) => {
                Object.keys(changes).forEach((key) => dirtyFields.current.add(key as keyof Preferences));
                setDraft((current) => ({ ...current, ...changes }));
                setSaved(false);
              }}
            />
            {select('coaching_mode', 'coachingMode', [
              ['independent', 'independent'],
              ['guided', 'guided'],
              ['learning', 'learning'],
              ['socratic', 'socratic'],
            ])}
            {select('feedback', 'feedback', [
              ['none', 'none'],
              ['short', 'short'],
              ['detailed', 'detailed'],
            ])}
            {select('feedback_frequency', 'onlyMistakes', [
              ['all', 'allMoves'],
              ['mistakes', 'mistakesOnly'],
            ])}
            {select('coach_language', 'coachLanguage', [
              ['en', 'English'],
              ['da', 'Dansk'],
            ])}
            {select('complexity', 'complexity', [
              ['beginner', 'beginner'],
              ['intermediate', 'intermediate'],
              ['advanced', draft.language === 'da' ? 'Øvet' : 'Advanced'],
            ])}
            <Field label={t('maxLength')}>
              <input
                type="number"
                min="30"
                max="400"
                value={draft.max_explanation_length}
                onChange={(e) => set('max_explanation_length', +e.target.value)}
              />
            </Field>
            {toggle('show_alternatives', 'betterMoves')}
            {toggle('hide_best_moves', 'hideBest')}
            {toggle('guided_questions', 'guidedQuestions')}
            {toggle('progressive_hints', 'progressive')}
          </div>
        </section>
        <section className="settings-section">
          <div>
            <h2>{t('analysis')}</h2>
          </div>
          <div className="settings-fields">
            {toggle('automatic_analysis', 'automaticAnalysis')}
            {toggle('automatic_diary', 'automaticDiary')}
            <Field label={t('timezone')}>
              <input
                type="text"
                required
                maxLength={64}
                value={draft.timezone || 'UTC'}
                placeholder="Europe/Copenhagen"
                onChange={(event) => set('timezone', event.target.value)}
              />
            </Field>
            <Field label={t('analysisTime')}>
              <input
                type="number"
                min="50"
                max="3000"
                step="50"
                value={draft.analysis_time_ms}
                onChange={(e) => set('analysis_time_ms', +e.target.value)}
              />
            </Field>
            <Field label={t('depth')}>
              <input
                type="number"
                min="1"
                max="24"
                value={draft.analysis_depth || ''}
                onChange={(e) => set('analysis_depth', e.target.value ? +e.target.value : null)}
              />
            </Field>
            {select('candidate_count', 'candidates', [
              ['1', '1'],
              ['2', '2'],
              ['3', '3'],
            ])}
            {toggle('show_evaluation', 'engineEval')}
            {toggle('show_pv', 'variations')}
          </div>
        </section>
        <ErrorNotice error={error} />
        <div className="settings-footer">
          {saved && (
            <span role="status">
              <Check size={16} />
              {t('preferencesSaved')}
            </span>
          )}
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? <Spinner /> : <Save size={17} />} {t('save')}
          </button>
        </div>
      </form>
    </>
  );
}
