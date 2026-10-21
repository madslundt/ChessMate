import { useState } from 'react';
import { useFullGameAnalysis } from './useFullGameAnalysis';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, ChevronRight } from 'lucide-react';
import { api } from './api';
import { BlunderReview } from './BlunderReview';
import { ConsequenceComparison } from './ConsequenceComparison';
import { ConfidenceBadge } from './ConfidenceBadge';
import { ActiveRecallReview } from './ActiveRecallReview';
import { ErrorNotice, Spinner } from './components';
import { useT } from './i18n';
import { analysisPath, Link } from './navigation';
import type { Candidate, Color, Game, Preferences, Review, VisualInsight } from './types';

const qualities = ['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder', 'forced', 'uncertain'] as const;
type Quality = (typeof qualities)[number];
function quality(value?: string): Quality | undefined {
  return qualities.find((q) => q === value?.toLowerCase());
}
function assessedMoves(game: Game) {
  // Imported games may not have ratings. Never treat an unassessed move as good.
  return game.moves.flatMap((move, index) => {
    const rating = quality(move.feedback?.classification);
    return rating ? [{ ...move, ply: index + 1, rating }] : [];
  });
}
function QualityCounts({ game }: { game: Game }) {
  const t = useT();
  const moves = assessedMoves(game);
  return (
    <div className="quality-summary">
      <small>
        {t('assessedMoves')} · {moves.length}
      </small>
      <dl className="quality-counts">
        {qualities.map((q) => (
          <div key={q} aria-label={`${t(q)}: ${moves.filter((m) => m.rating === q).length}`}>
            <dt>
              <span className={`move-quality ${q}`} />
              {t(q)}
            </dt>
            <dd>{moves.filter((m) => m.rating === q).length}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
export function PostGameSummary({ game }: { game: Game }) {
  const t = useT();
  const outcome =
    game.result === '1/2-1/2'
      ? 'draw'
      : game.result === (game.player_color === 'white' ? '1-0' : '0-1')
        ? 'victory'
        : 'defeat';
  return (
    <section className="post-game-summary panel" aria-label={t('gameOver')}>
      <h2>{t(outcome)}</h2>
      <QualityCounts game={game} />
      <Link className="primary-button" href={analysisPath(game.id)}>
        {t('analyzeGame')}
        <ArrowRight size={17} />
      </Link>
    </section>
  );
}
export function GameReview({
  orientation,
  game,
  ply,
  exploring,
  onNavigate,
  onExplore,
  onRetry,
  onPreview,
  onHoverMove,
  onToggleMove,
  onVisual,
  activeVisual,
  preferences,
}: {
  orientation?: Color;
  game: Game | null;
  ply: number;
  exploring: boolean;
  onNavigate: (ply: number) => void;
  onExplore: () => void;
  onRetry: (baseFen: string, rootPly?: number) => void;
  highlightedMove?: string | null;
  onPreview: (candidate: Candidate, baseFen?: string, rootPly?: number) => void;
  onHoverMove: (uci: string | null) => void;
  onToggleMove: (uci: string) => void;
  onVisual: (insight: VisualInsight) => void;
  activeVisual?: VisualInsight | null;
  preferences: Preferences;
}) {
  const t = useT();
  const client = useQueryClient();
  const [filter, setFilter] = useState<Quality | 'all'>('all');
  const [selected, setSelected] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<unknown>(null);
  const { analyzingGame, analysisProgress, analyzeGame, cancelAnalysis } = useFullGameAnalysis(game, preferences, setError);
  const review = useQuery({
    queryKey: ['game-review', game?.id, game?.revision],
    queryFn: ({ signal }) => api<Review>(`/games/${game!.id}/review`, undefined, undefined, signal),
    enabled: !!game?.moves.length,
    staleTime: 60000,
  });
  const moves = game ? assessedMoves(game) : [];
  const visible = moves.filter((m) => filter === 'all' || m.rating === filter);
  const current = moves.find((m) => m.ply === selected);
  const firstMove = Number(game?.initial_fen.split(' ')[5] || 1);
  const offset = game?.initial_fen.split(' ')[1] === 'b' ? 1 : 0;
  async function createExercises() {
    if (!game || creating) return;
    setCreating(true);
    setError(null);
    try {
      const result = await api<{ count: number }>(`/games/${game.id}/exercises`, {});
      setNotice(`${t('createdExercises')} (${result.count})`);
      void client.invalidateQueries({ queryKey: ['exercises'] });
    } catch (e) {
      setError(e);
    } finally {
      setCreating(false);
    }
  }
  return (
    <div className="game-review">
      <h3>{t('review')}</h3>
      <p className="muted">{t('reviewHelp')}</p>
      {game && <QualityCounts game={game} />}
      {!!game?.moves.length && <div className="review-decision-actions"><button className="outline-button" disabled={analyzingGame} onClick={() => void analyzeGame()}>{analyzingGame ? <Spinner /> : t('analyzeAllMoves')}</button>{analyzingGame && <button className="text-button" onClick={cancelAnalysis}>{t('cancelAnalysis')}</button>}<span role="status">{analysisProgress}</span></div>}
      {review.isFetching && <Spinner label={t('thinking')} />}
      <ErrorNotice error={review.error} />
      {review.isError && (
        <button className="text-button" onClick={() => void review.refetch()}>
          {t('load')}
        </button>
      )}
      {review.data?.summary && <p className="muted">{review.data.summary}</p>}
      {!!review.data?.topics?.length && (
        <p className="review-topics">
          {t('recommended')}: {review.data.topics.map((topic) => t(topic as 'opening')).join(' · ')}
        </p>
      )}
      {!moves.length ? (
        <p className="review-empty">{t('noAssessedMoves')}</p>
      ) : (
        <>
          <div className="review-filters" role="group" aria-label={t('review')}>
            {(['all', ...qualities] as const).map((q) => (
              <button
                key={q}
                aria-pressed={filter === q}
                onClick={() => {
                  setFilter(q);
                  if (current && q !== 'all' && current.rating !== q) setSelected(null);
                }}
              >
                {t(q === 'all' ? 'allMoves' : q)} ·{' '}
                {q === 'all' ? moves.length : moves.filter((m) => m.rating === q).length}
              </button>
            ))}
          </div>
          {current && (
            <ActiveRecallReview
              gameId={game!.id}
              ply={current.ply}
              san={current.san}
              language={preferences.language}
              positionFen={current.before_fen || (current.ply === 1 ? game!.initial_fen : game!.moves[current.ply - 2].fen)}
              engineFeedback={
                <div className={`review-decision feedback-note ${current.rating}`}>
                  <strong>{current.san} · {t(current.rating)}</strong>
                  <ConfidenceBadge mode={current.feedback?.analysis_mode} confidence={current.feedback?.confidence} />
                  {['blunder', 'mistake', 'inaccuracy'].includes(current.rating) && current.feedback && game ? (
                    <BlunderReview
                      onVisual={onVisual}
                      activeVisual={activeVisual}
                      key={`${game.id}-${current.ply}`}
                      beforeFen={current.before_fen || (current.ply === 1 ? game.initial_fen : game.moves[current.ply - 2].fen)}
                      uci={current.uci}
                      feedback={current.feedback}
                      preferences={preferences}
                      onPreview={(candidate) => onPreview(candidate, current.before_fen || (current.ply === 1 ? game.initial_fen : game.moves[current.ply - 2].fen), current.ply - 1)}
                    />
                  ) : (
                    <p>{current.feedback?.text || current.feedback?.explanation || current.feedback?.assessment}</p>
                  )}
                  {current.feedback?.takeaway && <p className="takeaway">{current.feedback.takeaway}</p>}
                  {current.feedback && game && <ConsequenceComparison feedback={current.feedback} base={current.before_fen || (current.ply === 1 ? game.initial_fen : game.moves[current.ply - 2].fen)} preferences={preferences} orientation={orientation || game.player_color} onPreview={onPreview} />}
                  <div className="review-decision-actions">
                    <button className="outline-button" aria-pressed={!exploring && ply === current.ply - 1} onClick={() => onNavigate(current.ply - 1)}>{t('beforeMove')}</button>
                    <button className="outline-button" aria-pressed={!exploring && ply === current.ply} onClick={() => onNavigate(current.ply)}>{t('afterMove')}</button>
                    <button className="text-button" onClick={() => onRetry(current.before_fen || (current.ply === 1 ? game!.initial_fen : game!.moves[current.ply - 2].fen), current.ply - 1)}>{t('retryPosition')}</button>
                    <button className="text-button" disabled={exploring || ply !== current.ply - 1} onClick={onExplore}>{t('tryAlternative')}</button>
                  </div>
                </div>
              }
            />
          )}
          <div className="review-moves">
            {visible.map((move) => (
              <button
                key={move.ply}
                className={`review-move ${selected === move.ply ? 'current' : ''}`}
                aria-pressed={selected === move.ply}
                onPointerEnter={() => onHoverMove(move.uci)}
                onPointerLeave={() => onHoverMove(null)}
                onClick={() => {
                  setSelected(move.ply);
                  onNavigate(move.ply - 1);
                  onToggleMove(move.uci);
                }}
              >
                <strong>
                  {firstMove + Math.floor((move.ply - 1 + offset) / 2)}
                  {(move.ply - 1 + offset) % 2 ? '…' : '.'} {move.san}
                </strong>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
          {moves.some((m) => ['inaccuracy', 'mistake', 'blunder'].includes(m.rating)) && (
            <button className="outline-button" disabled={creating} onClick={() => void createExercises()}>
              {creating ? <Spinner /> : t('createExercises')}
            </button>
          )}
          <small className="muted review-limitations">{t('reviewEstimates')}</small>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      <ErrorNotice error={error} onDismiss={() => setError(null)} />
    </div>
  );
}
