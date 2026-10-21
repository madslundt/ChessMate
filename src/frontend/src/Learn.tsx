import { useEffect, useState } from 'react';
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
import { VariationPlayer } from './VariationPlayer';
import { replayVariation } from './exploration';
import { Empty, ErrorNotice, PageHeading, Spinner } from './components';
import { useT, type TranslationKey } from './i18n';
import type { Attempt, Exercise, Preferences } from './types';
import { categories, learnPath, Link, navigate, type Route } from './navigation';
export function Learn({ preferences, route }: { preferences: Preferences; route: Route }) {
  const t = useT(),
    [error, setError] = useState<unknown>(null),
    [pending, setPending] = useState(false),
    [completed, setCompleted] = useState(false);
  const exercises = useQuery({
    queryKey: ['exercises', preferences.language],
    queryFn: () => api<Exercise[]>('/exercises'),
  });
  const { category, exerciseId, sessionId } = route;
  const exerciseQuery = useQuery({
    queryKey: ['exercise', exerciseId, preferences.language],
    queryFn: () => api<Exercise>(`/exercises/${exerciseId}`),
    enabled: !!exerciseId,
    retry: false,
  });
  const sessionQuery = useQuery({
    queryKey: ['training-session', sessionId, preferences.language],
    queryFn: () => api<{ id: string; exercises: Exercise[] }>(`/training/sessions/${sessionId}`),
    enabled: !!sessionId,
    retry: false,
  });
  const exercise = exerciseQuery.data;
  const filtered = exercises.data?.filter((x) => category === 'all' || x.category === category) || [];
  async function practice(kind: string, minutes: number) {
    setPending(true);
    setError(null);
    try {
      const session = await api<{ id: string; exercises: Exercise[] }>('/training/sessions', {
        kind,
        minutes,
      });
      if (session.exercises[0]) navigate(learnPath(category, session.exercises[0].id, session.id));
      setCompleted(!session.exercises.length);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }
  if (exerciseId) {
    const loading = exerciseQuery.isPending || (!!sessionId && sessionQuery.isPending);
    const loadError = exerciseQuery.error || sessionQuery.error;
    return (
      <>
        <Link className="text-button back-button" href={learnPath(category)}>
          <ArrowLeft size={17} />
          {t('backLessons')}
        </Link>
        {loading ? (
          <Spinner label={t('thinking')} />
        ) : loadError ? (
          <ErrorNotice error={loadError} />
        ) : (
          exercise && (
            <ExercisePlayer
              key={exercise.id}
              exercise={exercise}
              preferences={preferences}
              session={!!sessionId}
              onNext={() => {
                if (sessionId) {
                  const items = sessionQuery.data?.exercises || [];
                  const index = items.findIndex((item) => item.id === exercise.id);
                  const next = items[index + 1];
                  if (next) navigate(learnPath(category, next.id, sessionId));
                  else {
                    setCompleted(true);
                    navigate(learnPath(category));
                  }
                } else {
                  const index = filtered.findIndex((item) => item.id === exercise.id);
                  const next = filtered[(index + 1) % filtered.length];
                  navigate(learnPath(category, next?.id));
                }
              }}
            />
          )
        )}
      </>
    );
  }
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
          <Link
            role="tab"
            aria-selected={category === c}
            key={c}
            href={learnPath(c)}
            className={category === c ? 'selected' : ''}
          >
            {t(c as TranslationKey)}
          </Link>
        ))}
      </div>
      {category !== 'all' && (
        <button
          className="text-button topic-practice"
          disabled={pending}
          onClick={() => void practice(category, 5)}
        >
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
            <Link className="lesson-row" key={item.id} href={learnPath(category, item.id)}>
              <span className="lesson-number">{String(i + 1).padStart(2, '0')}</span>
              <span className="lesson-icon">
                <BookOpen size={21} />
              </span>
              <span className="lesson-copy">
                <small>
                  {t(item.category as TranslationKey)} ·{' '}
                  {Number(item.difficulty) >= 3
                    ? preferences.language === 'da'
                      ? 'Øvet'
                      : 'Advanced'
                    : Number(item.difficulty) > 1
                      ? t('intermediate')
                      : t('beginner')}
                </small>
                <strong>{item.title}</strong>
                <span>{item.objective}</span>
              </span>
              {item.source_game_id && <small>{t('match')}</small>}
              <ChevronRight size={20} />
            </Link>
          ))}
        </div>
      )}
      {category === 'opening' && (
        <Repertoire
          preferences={preferences}
          onPractice={(s) => {
            if (s.exercises[0]) navigate(learnPath(category, s.exercises[0].id, s.id));
          }}
        />
      )}
    </>
  );
}
function ExercisePlayer({
  exercise,
  preferences,
  onNext,
  session,
}: {
  exercise: Exercise;
  preferences: Preferences;
  onNext: () => void;
  session: boolean;
}) {
  const t = useT(),
    client = useQueryClient(),
    [fen, setFen] = useState(exercise.fen),
    [moves, setMoves] = useState<string[]>([]),
    [branchId, setBranchId] = useState<string | null>(null),
    [result, setResult] = useState<Attempt | null>(null),
    [busy, setBusy] = useState(false),
    [hint, setHint] = useState(''),
    [hintMove, setHintMove] = useState<string | null>(null),
    [hintSquare, setHintSquare] = useState<string | null>(null),
    [preview, setPreview] = useState<number | null>(null),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(preferences.variation_speed_ms || 1000),
    [level, setLevel] = useState(0),
    [error, setError] = useState<unknown>(null);
  const side = exercise.fen.split(' ')[1] === 'w' ? 'white' : 'black';
  const solution = result?.solution || [];
  const boardFen = preview === null ? fen : replayVariation(exercise.fen, solution.slice(0, preview)).fen();
  useEffect(() => {
    if (!playing || preview === null) return;
    if (preview >= solution.length) {
      setPlaying(false);
      if (preferences.return_after_playback) setPreview(null);
      return;
    }
    const timer = window.setTimeout(() => setPreview(preview + 1), speed);
    return () => window.clearTimeout(timer);
  }, [playing, preview, solution.length, speed, preferences.return_after_playback]);
  async function move(uci: string) {
    if (busy || result?.complete) return;
    setBusy(true);
    setError(null);
    try {
      const submitted = [...moves, uci],
        r = await api<Attempt>(`/exercises/${exercise.id}/attempt`, {
          moves: submitted,
          hint_level: level,
          branch_id: branchId,
        });
      setResult(r);
      if (r.correct) {
        setBranchId(typeof r.branch_id === 'string' ? r.branch_id : null);
        setFen(r.fen || fen);
        setMoves(r.reply ? [...submitted, r.reply] : submitted);
        setHint('');
        setHintMove(null);
        setHintSquare(null);
        if (!r.complete) setLevel(0);
      } else {
        setBranchId(null);
        setFen(exercise.fen);
        setMoves([]);
        setHint('');
        setHintMove(null);
        setHintSquare(null);
        setLevel(0);
      }
      client.invalidateQueries({ queryKey: ['progress'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function requestHint() {
    if (level >= 2 || busy) return;
    setBusy(true);
    try {
      const r = await api<{ text: string; level: number; move?: string; highlight_square?: string }>(`/exercises/${exercise.id}/hint`, {
        level: Math.min(level + 1, 2),
        moves,
        branch_id: branchId,
      });
      setHint(r.text);
      setLevel(r.level);
      setHintMove(r.move || null);
      setHintSquare(r.highlight_square || null);
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
            fen={boardFen}
            preferences={preferences}
            orientation={side}
            onMove={(m) => void move(m)}
            lastMove={preview === null ? moves.at(-1) : solution[preview - 1]}
            highlightedMove={preview === null ? hintMove || (hintSquare ? null : undefined) : undefined}
            targets={preview === null && hintSquare ? [hintSquare] : []}
            arrows={
              preview === null && hintMove
                ? [
                    {
                      startSquare: hintMove.slice(0, 2),
                      endSquare: hintMove.slice(2, 4),
                      color: '#3a8066',
                    },
                  ]
                : []
            }
            disabled={busy || !!result?.complete || preview !== null}
          />
          <div className="board-toolbar">
            <span className="muted">{t('hintsFirst')}</span>
            <button
              className="icon-button"
              title={t('reset')}
              aria-label={t('reset')}
              disabled={busy || preview !== null}
              onClick={() => {
                setFen(exercise.fen);
                setMoves([]);
                setBranchId(null);
                setResult(null);
                setError(null);
                setHint('');
                setHintMove(null);
                setHintSquare(null);
                setLevel(0);
                setPreview(null);
                setPlaying(false);
              }}
            >
              <RotateCcw size={17} />
            </button>
          </div>
          {preview !== null && (
            <>
              <VariationPlayer
                base={exercise.fen}
                moves={solution}
                cursor={preview}
                onCursor={setPreview}
                playing={playing}
                onPlaying={setPlaying}
                speed={speed}
                onSpeed={setSpeed}
                label={t('solution')}
              />
              <button
                className="text-button"
                onClick={() => {
                  setPreview(null);
                  setPlaying(false);
                }}
              >
                {preferences.language === 'da' ? 'Tilbage til øvelsen' : 'Return to exercise'}
              </button>
            </>
          )}
        </section>
        <section className="exercise-coach panel">
          <span className="round-icon">
            <BookOpen size={23} />
          </span>
          <h2>{t('objective')}</h2>
          <p className="objective-text">{exercise.objective}</p>
          {exercise.source_game_id && (
            <Link className="text-button" href={`/analyze/${exercise.source_game_id}`}>
              {preferences.language === 'da' ? 'Tilbage til dit parti' : 'Return to your game'}
            </Link>
          )}
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
                  <button
                    className="outline-button"
                    onClick={() => {
                      setPreview(0);
                      setPlaying(false);
                    }}
                  >
                    {preferences.language === 'da' ? 'Vis på brættet' : 'Show on board'}
                  </button>
                  <small>
                    {preferences.language === 'da'
                      ? result.independent
                        ? 'Løst selvstændigt'
                        : 'Løst med hjælp eller efter et nyt forsøg'
                      : result.independent
                        ? 'Solved independently'
                        : 'Solved with help or after a retry'}
                  </small>
                </>
              )}
            </div>
          )}
          {hint && (
            <div className="hint-note">
              <span>
                {t('hint')} {level}/2
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
              <button
                className="outline-button"
                disabled={busy || level >= 2}
                onClick={() => void requestHint()}
              >
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
