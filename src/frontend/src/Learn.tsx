import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Chess } from 'chess.js';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Lightbulb,
  RotateCcw,
  Target,
} from 'lucide-react';
import { api } from './api';
import { Board } from './Board';
import { Repertoire } from './Repertoire';
import { Empty, ErrorNotice, PageHeading, Spinner } from './components';
import { useT, type TranslationKey } from './i18n';
import type { Attempt, Exercise, Preferences } from './types';
const categories = ['forks', 'pins', 'skewers', 'opening', 'middlegame', 'endgame'] as const;
export function Learn({ preferences }: { preferences: Preferences }) {
  const t = useT(),
    [category, setCategory] = useState('all'),
    [exercise, setExercise] = useState<Exercise | null>(null),
    [queue, setQueue] = useState<Exercise[]>([]),
    [sessionId, setSessionId] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null),
    [pending, setPending] = useState(false),
    [completed, setCompleted] = useState(false);
  const exercises = useQuery({
    queryKey: ['exercises', preferences.language],
    queryFn: () => api<Exercise[]>('/exercises'),
  });
  const filtered = exercises.data?.filter((x) => category === 'all' || x.category === category) || [];
  async function practice(kind: string, minutes: number) {
    setPending(true);
    setError(null);
    try {
      const session = await api<{ id: string; exercises: Exercise[] }>('/training/sessions', { kind, minutes });
      setSessionId(session.id);
      setQueue(session.exercises.slice(1));
      setExercise(session.exercises[0] || null);
      setCompleted(!session.exercises.length);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }
  if (exercise)
    return (
      <ExercisePlayer
        key={exercise.id}
        exercise={exercise}
        preferences={preferences}
        onBack={() => {
          setExercise(null);
          setQueue([]);
          setSessionId(null);
        }}
        session={!!sessionId}
        onNext={() => {
          if (queue.length) {
            setExercise(queue[0]);
            setQueue(queue.slice(1));
          } else if (sessionId) {
            setExercise(null);
            setSessionId(null);
            setCompleted(true);
          } else {
            const index = filtered.findIndex((x) => x.id === exercise.id);
            setExercise(filtered[(index + 1) % filtered.length] || null);
          }
        }}
      />
    );
  return (
    <>
      <PageHeading title={t('learn')} />
      <ErrorNotice error={error || exercises.error} />
      <div className="practice-band">
        <div className="practice-symbol">
          <Target size={30} />
        </div>
        <div>
          <h2>{completed ? t('practiceComplete') : t('startPractice')}</h2>
        </div>
        <div className="practice-actions">
          <button className="primary-button" disabled={pending} onClick={() => void practice('daily', 5)}>
            <Clock3 size={17} />
            {t('daily')}
          </button>
          <button className="outline-button" disabled={pending} onClick={() => void practice('mixed', 10)}>
            {t('mixed')}
          </button>
          <button className="text-button" disabled={pending} onClick={() => void practice('mistakes', 5)}>
            {t('mistakes')}
            <ArrowRight size={15} />
          </button>
          <details className="practice-more">
            <summary>{t('practiceMore')}</summary>
            <div>
              {(
                [
                  ['tactical', 'tacticalPractice'],
                  ['opening', 'opening'],
                  ['endgame', 'endgame'],
                  ['review', 'reviewLessons'],
                ] as const
              ).map(([kind, label]) => (
                <button type="button" key={kind} disabled={pending} onClick={() => void practice(kind, 5)}>
                  {t(label)}
                  <ArrowRight size={14} />
                </button>
              ))}
            </div>
          </details>
        </div>
      </div>
      <div className="category-tabs" role="tablist" aria-label={t('topics')}>
        {['all', ...categories].map((c) => (
          <button
            role="tab"
            aria-selected={category === c}
            key={c}
            onClick={() => setCategory(c)}
            className={category === c ? 'selected' : ''}
          >
            {t(c as TranslationKey)}
          </button>
        ))}
      </div>
      {category !== 'all' && (
        <button className="text-button topic-practice" disabled={pending} onClick={() => void practice(category, 5)}>
          {t('startPractice')} · {t(category as TranslationKey)}
          <ArrowRight size={14} />
        </button>
      )}
      {exercises.isPending ? (
        <Spinner label={t('thinking')} />
      ) : !filtered.length ? (
        <Empty>{t('noProgress')}</Empty>
      ) : (
        <div className="lesson-list">
          {filtered.map((item, i) => (
            <button
              className="lesson-row"
              key={item.id}
              onClick={() => {
                setExercise(item);
                setSessionId(null);
                setQueue([]);
              }}
            >
              <span className="lesson-number">{String(i + 1).padStart(2, '0')}</span>
              <span className="lesson-icon">
                <BookOpen size={21} />
              </span>
              <span className="lesson-copy">
                <small>
                  {t(item.category as TranslationKey)} ·{' '}
                  {Number(item.difficulty) > 1 ? t('intermediate') : t('beginner')}
                </small>
                <strong>{item.title}</strong>
                <span>{item.objective}</span>
              </span>
              {item.source_game_id && <small>{t('match')}</small>}
              <ChevronRight size={20} />
            </button>
          ))}
        </div>
      )}
      {category === 'opening' && (
        <Repertoire
          preferences={preferences}
          onPractice={(s) => {
            setSessionId(s.id);
            setQueue(s.exercises.slice(1));
            setExercise(s.exercises[0] || null);
          }}
        />
      )}
    </>
  );
}
function ExercisePlayer({
  exercise,
  preferences,
  onBack,
  onNext,
  session,
}: {
  exercise: Exercise;
  preferences: Preferences;
  onBack: () => void;
  onNext: () => void;
  session: boolean;
}) {
  const t = useT(),
    client = useQueryClient(),
    [fen, setFen] = useState(exercise.fen),
    [moves, setMoves] = useState<string[]>([]),
    [result, setResult] = useState<Attempt | null>(null),
    [busy, setBusy] = useState(false),
    [hint, setHint] = useState(''),
    [level, setLevel] = useState(0),
    [error, setError] = useState<unknown>(null);
  const side = exercise.fen.split(' ')[1] === 'w' ? 'white' : 'black';
  async function move(uci: string) {
    if (busy || result?.complete) return;
    setBusy(true);
    setError(null);
    try {
      const submitted = [...moves, uci],
        r = await api<Attempt>(`/exercises/${exercise.id}/attempt`, {
          moves: submitted,
          hint_level: level,
        });
      setResult(r);
      if (r.correct) {
        setFen(r.fen || fen);
        setMoves(r.reply ? [...submitted, r.reply] : submitted);
      } else {
        setFen(exercise.fen);
        setMoves([]);
      }
      client.invalidateQueries({ queryKey: ['progress'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function requestHint() {
    setBusy(true);
    try {
      const r = await api<{ text: string; level: number }>(`/exercises/${exercise.id}/hint`, {
        level: Math.min(level + 1, 4),
      });
      setHint(r.text);
      setLevel(r.level);
      client.invalidateQueries({ queryKey: ['progress'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const solutionSans = () => {
    const c = new Chess(exercise.fen);
    return result?.solution?.map((m) => c.move(m).san).join(' · ');
  };
  return (
    <>
      <button className="text-button back-button" onClick={onBack}>
        <ArrowLeft size={17} />
        {t('backLessons')}
      </button>
      <PageHeading
        title={exercise.title}
        subtitle={`${t(exercise.category as TranslationKey)} · ${session ? t('practiceQueue') : Number(exercise.difficulty) > 1 ? t('intermediate') : t('beginner')}`}
      />
      <div className="exercise-layout">
        <section className="board-panel panel">
          <div className="player-row">
            <span className="avatar">
              <Target size={22} />
            </span>
            <div>
              <strong>{t('objective')}</strong>
              <small>
                {t(side)} {t('sideToMove')}
              </small>
            </div>
          </div>
          <Board
            fen={fen}
            preferences={preferences}
            orientation={side}
            onMove={(m) => void move(m)}
            lastMove={moves.at(-1)}
            disabled={busy || !!result?.complete}
          />
          <div className="board-toolbar">
            <span className="muted">{t('hintsFirst')}</span>
            <button
              className="icon-button"
              title={t('reset')}
              aria-label={t('reset')}
              onClick={() => {
                setFen(exercise.fen);
                setMoves([]);
                setResult(null);
                setError(null);
              }}
            >
              <RotateCcw size={17} />
            </button>
          </div>
        </section>
        <section className="exercise-coach panel">
          <span className="round-icon">
            <BookOpen size={23} />
          </span>
          <h2>{t('objective')}</h2>
          <p className="objective-text">{exercise.objective}</p>
          {exercise.description && <p>{exercise.description}</p>}
          {busy && <Spinner label={t('thinking')} />}
          {result && (
            <div className={`exercise-feedback ${result.correct ? 'correct' : 'incorrect'}`} role="status">
              {result.complete && <CheckCircle2 size={24} />}
              <h3>{result.complete ? t('solved') : !result.correct ? t('tryAgain') : t('continue')}</h3>
              <p>{result.feedback}</p>
              {result.complete && (
                <>
                  <small>{t('solution')}</small>
                  <code>{solutionSans()}</code>
                </>
              )}
            </div>
          )}
          {hint && (
            <div className="hint-note">
              <span>
                {t('hint')} {level}/4
              </span>
              <p>{hint}</p>
            </div>
          )}
          <ErrorNotice error={error} />
          {result?.complete ? (
            <button className="primary-button" onClick={onNext}>
              {t('nextExercise')}
              <ArrowRight size={17} />
            </button>
          ) : (
            preferences.progressive_hints && (
              <button className="outline-button" disabled={busy || level >= 4} onClick={() => void requestHint()}>
                <Lightbulb size={19} />
                {t(level ? 'nextHint' : 'hint')}
              </button>
            )
          )}
        </section>
      </div>
    </>
  );
}
