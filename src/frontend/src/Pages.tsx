import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Clock3,
  Flame,
  Gamepad2,
  Lightbulb,
  Save,
  Target,
} from 'lucide-react';
import { api } from './api';
import { Empty, ErrorNotice, Field, PageHeading, Spinner, Toggle } from './components';
import { useT, type TranslationKey } from './i18n';
import type { Game, Preferences, Progress } from './types';
import { LlmConnection } from './LlmConnection';
export function History({ onResume }: { onResume: (g: Game) => void }) {
  const t = useT(),
    games = useQuery({
      queryKey: ['games'],
      queryFn: () => api<Game[]>('/games'),
    });
  return (
    <>
      <PageHeading title={t('history')} />
      <ErrorNotice error={games.error} />
      {games.isPending ? (
        <Spinner />
      ) : !games.data?.length ? (
        <Empty>
          <Clock3 size={32} />
          <p>{t('emptyGames')}</p>
        </Empty>
      ) : (
        <div className="history-list panel">
          {games.data.map((g) => (
            <button className="history-row" key={g.id} onClick={() => onResume(g)}>
              <span className="history-piece">{g.player_color === 'white' ? '♔' : '♚'}</span>
              <div>
                <strong>
                  {t(g.mode === 'analysis' ? 'freeAnalysis' : g.mode === 'training' ? 'training' : 'computer')}
                </strong>
                <small>
                  {g.created_at &&
                    new Date(g.created_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}{' '}
                  · {Math.ceil(g.moves.length / 2)} {t('moves').toLowerCase()}
                </small>
              </div>
              <span className="history-result">{g.result === '*' ? t('active') : g.result}</span>
              <span className="history-resume">{t('resume')}</span>
              <ChevronRight size={18} />
            </button>
          ))}
        </div>
      )}
    </>
  );
}
export function ProgressPage({ onLearn }: { onLearn: () => void }) {
  const t = useT(),
    progress = useQuery({
      queryKey: ['progress'],
      queryFn: () => api<Progress>('/progress'),
    }),
    p = progress.data;
  return (
    <>
      <PageHeading title={t('progress')} />
      <ErrorNotice error={progress.error} />
      {progress.isPending ? (
        <Spinner />
      ) : (
        p && (
          <>
            <div className="progress-stats">
              {[
                [Gamepad2, 'games', p.games_played],
                [Target, 'attempts', p.attempts],
                [Check, 'accuracy', `${Math.round(p.accuracy * 100)}%`],
                [Lightbulb, 'hintsUsed', p.hints_used],
              ].map(([Icon, key, value]) => {
                const I = Icon as typeof Target;
                return (
                  <div className="stat" key={String(key)}>
                    <I size={21} />
                    <span>{t(key as TranslationKey)}</span>
                    <strong>{String(value)}</strong>
                  </div>
                );
              })}
            </div>
            <div className="progress-layout">
              <section className="panel topic-panel">
                <h2>{t('topics')}</h2>
                {!p.attempts && <p className="muted">{t('noProgress')}</p>}
                {p.topics.map((topic) => (
                  <div className="topic-row" key={topic.topic}>
                    <div>
                      <strong>{t(topic.topic as TranslationKey)}</strong>
                      <span>
                        {topic.attempts} {t('attempts').toLowerCase()}
                        <b>{Math.round(topic.accuracy * 100)}%</b>
                      </span>
                    </div>
                    <div className="topic-track">
                      <span style={{ width: `${topic.accuracy * 100}%` }} />
                    </div>
                  </div>
                ))}
              </section>
              <section className="practice-recommendations">
                <span className="round-icon">
                  <Flame size={23} />
                </span>
                <h2>{t('recommended')}</h2>
                {p.recommendations.map((r, i) => (
                  <button className="recommendation" key={i} onClick={onLearn}>
                    <BookOpen size={20} />
                    <div>
                      <strong>{typeof r === 'string' ? r : t((r.topic || 'learn') as TranslationKey)}</strong>
                      {typeof r !== 'string' && r.reason && <p>{r.reason}</p>}
                    </div>
                    <ChevronRight size={18} />
                  </button>
                ))}
                <button className="primary-button" onClick={onLearn}>
                  {t('startPractice')}
                  <ArrowRight size={16} />
                </button>
              </section>
            </div>
            {Array.isArray(p.timeline) && p.timeline.length > 0 && (
              <section className="panel timeline-panel">
                <h2>{t('progress')}</h2>
                <div className="progress-timeline">
                  {(
                    p.timeline as {
                      date: string;
                      attempts: number;
                      correct: number;
                    }[]
                  )
                    .slice(-20)
                    .map((x) => (
                      <div key={x.date} title={`${x.correct}/${x.attempts}`}>
                        <span
                          style={{
                            height: `${Math.max(5, (100 * x.correct) / x.attempts)}px`,
                          }}
                        />
                        <small>{x.date.slice(5)}</small>
                      </div>
                    ))}
                </div>
              </section>
            )}
          </>
        )
      )}
    </>
  );
}
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
  useEffect(() => {
    setDraft((current) => ({ ...current, theme: preferences.theme }));
  }, [preferences.theme]);
  function set<K extends keyof Preferences>(k: K, v: Preferences[K]) {
    setDraft((d) => ({ ...d, [k]: v }));
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
      <form
        className="settings-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const p = await api<Preferences>('/settings', draft, 'PATCH');
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
            {toggle('auto_computer', 'autoComputer')}
          </div>
        </section>
        <section className="settings-section">
          <div>
            <h2>{t('coaching')}</h2>
          </div>
          <div className="settings-fields">
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
