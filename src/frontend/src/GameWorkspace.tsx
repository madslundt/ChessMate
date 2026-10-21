import { useEffect, useState } from 'react';
import { Chess } from 'chess.js';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  Download,
  FlaskConical,
  GraduationCap,
  Plus,
  RotateCcw,
  ScanEye,
  Repeat2,
  Redo2,
  Undo2,
  Upload,
  UserRound,
} from 'lucide-react';
import { api, ApiError } from './api';
import { Board, evaluationText } from './Board';
import { PositionScore } from './PositionScore';
import { LastMoveFeedback } from './LastMoveFeedback';
import { CoachPanel } from './CoachPanel';
import { committable, variationCursor } from './exploration';
import { VariationPlayer } from './VariationPlayer';
import { ErrorNotice, PageHeading, Spinner } from './components';
import { GameLoading, GameSetup, ImportModal } from './GameDialogs';
import { useGameWorkspace, type WorkspaceProps } from './useGameWorkspace';
import { BoardVisualPreviewContext, useBoardVisuals } from './useBoardVisuals';
import { PostGameSummary } from './GameReview';
import type { Exercise, Game, VisualInsight } from './types';
import { analysisPath, learnPath, navigate, Link } from './navigation';
export function GameWorkspace(props: WorkspaceProps) {
  const { preferences, analysisMode, selectGame } = props;
  const {
    t,
    setup,
    setSetup,
    importing,
    setImporting,
    setPly,
    flipped,
    setFlipped,
    explore,
    setExplore,
    playing, setPlaying, speed, setSpeed, playMode, setPlayMode, retryPosition,
    error,
    setError,
    busy,
    setAnalysis,
    notice,
    setNotice,
    game,
    gameQuery,
    at,
    fen,
    boardFen,
    atLatest,
    isPlayerTurn,
    finished,
    displayOrientation,
    analysisRequest,
    displayedAnalysis,
    whiteCp,
    rootCp,
    create,
    save,
    mutate,
    play,
    computerReady,
    computer,
    enterExplore,
    preview,
    commit,
    commitCalculated,
    exportPgn,
    lastMove,
    captureText,
    status,
    chess,
  } = useGameWorkspace(props);
  const [hoveredMove, setHoveredMove] = useState<string | null>(null);
  const [pinnedMove, setPinnedMove] = useState<string | null | undefined>(undefined);
  const [squareAnswer, setSquareAnswer] = useState<((square: string) => void) | null>(null);
  const highlightedMove = hoveredMove ?? pinnedMove;
  const { activeVisual, arrows, targets, feedbackFen, showVisual, clearVisual, previewVisual } = useBoardVisuals({ fen, preferences, highlightedMove, exploring: !!explore, lastMove, retryPosition });
  function highlightVisual(insight: VisualInsight) {
    setHoveredMove(null); setPinnedMove(null); showVisual(insight);
  }
  useEffect(() => {
    setHoveredMove(null);
    setPinnedMove(undefined);
    setSquareAnswer(null);
  }, [fen]);
  function toggleHighlightedMove(uci: string) {
    setPinnedMove((current) => current === uci ? null : uci);
  }
  if (props.activeGameId && !game) {
    return (
      <GameLoading
        analysisMode={analysisMode}
        preferences={preferences}
        pending={gameQuery.isPending}
        error={gameQuery.error}
        onRetry={() => void gameQuery.refetch()}
      />
    );
  }
  return (
    <BoardVisualPreviewContext.Provider value={previewVisual}>
      {analysisMode && (
        <Link className="text-button back-button" href="/analyze">
          <ArrowLeft size={16} />
          {t('backGames')}
        </Link>
      )}
      <PageHeading title={t(analysisMode ? 'analyze' : 'play')} subtitle={analysisMode ? t('analysisHelp') : undefined}>
        {!analysisMode && (
          <button className="primary-button" onClick={() => setSetup(true)}>
            <Plus size={19} />
            {t('newGame')}
          </button>
        )}
      </PageHeading>
      <ErrorNotice error={error} onDismiss={() => setError(null)} />
      {notice && (
        <div className="success-notice" role="status">
          <Check size={16} />
          {notice}
          <button className="text-button" onClick={() => setNotice('')}>
            {t('close')}
          </button>
        </div>
      )}
      {explore && (
        <div className="explore-banner">
          <FlaskConical size={21} />
          <div>
            <strong>{t('exploring')}</strong>
            <span>{t('exploreNote')}</span>
          </div>
          <button
            className="outline-button"
            onClick={() => {
              if (explore.previewOnly && 'returnPly' in explore) setPly(explore.returnPly ?? null);
              setExplore(null);
              setAnalysis(null);
            }}
          >
            <ArrowLeft size={16} />
            {t('returnGame')}
          </button>
        </div>
      )}
      {game && finished && !analysisMode && <PostGameSummary game={game} />}
      <div className="game-layout">
        <section className={`board-panel panel ${explore ? 'is-exploring' : ''}`}>
          <div className="player-row">
            <span className="avatar">
              <Bot size={23} />
            </span>
            <div>
              <strong>
                {analysisMode ? t(game && game.mode !== 'analysis' ? 'match' : 'freeAnalysis') : t('stockfish')}
              </strong>
              <small>
                {analysisMode
                  ? t('status')
                  : `${game?.difficulty || preferences.difficulty} / 5 · ${t((game?.difficulty || preferences.difficulty) > 3 ? 'intermediate' : 'beginner')}`}
              </small>
            </div>
            <span className="game-mode">
              <GraduationCap size={18} />
              {t(
                analysisMode
                  ? 'analysis'
                  : preferences.coaching_mode === 'independent'
                    ? 'independent'
                    : preferences.coaching_mode === 'socratic'
                      ? 'socratic'
                      : preferences.coaching_mode === 'learning'
                        ? 'learning'
                        : 'guided',
              )}
            </span>
          </div>
          <PositionScore
            chess={feedbackFen ? new Chess(feedbackFen) : chess}
            result={!feedbackFen && !explore && atLatest ? game?.result : undefined}
            evaluation={feedbackFen ? undefined : displayedAnalysis?.candidates[0]}
            showEvaluation={!feedbackFen && (preferences.show_evaluation || preferences.show_evaluation_bar)}
          />
          {squareAnswer && <div className="board-explanation" role="status">{t('selectSquarePrompt')}<button className="text-button" onClick={() => setSquareAnswer(null)}>{t('cancelChoice')}</button></div>}
          <div className="board-area">
            {!feedbackFen && preferences.show_evaluation_bar && (
              <div className="evaluation-bar" title="White perspective">
                <div
                  style={{
                    height: `${Math.max(5, Math.min(95, 50 + (whiteCp ?? ((displayedAnalysis?.candidates[0]?.white_mate ?? 0) > 0 ? 10000 : (displayedAnalysis?.candidates[0]?.white_mate ?? 0) < 0 ? -10000 : 0)) / 14))}%`,
                  }}
                />
                <span>{evaluationText(whiteCp, displayedAnalysis?.candidates[0]?.white_mate)}</span>
              </div>
            )}
            <Board
              fen={feedbackFen || boardFen}
              result={game && finished && atLatest && !explore && !feedbackFen && !analysisMode ? {
                id: `${game.id}:${game.revision}`,
                score: game.result!,
                playerColor: game.player_color,
                reason: status,
              } : undefined}
              animate={!explore || preferences.animate_variations !== false}
              preferences={preferences}
              orientation={displayOrientation}
              lastMove={lastMove}
              highlightedMove={feedbackFen ? null : highlightedMove}
              arrows={arrows}
              targets={targets}
              onSelectSquare={!feedbackFen && squareAnswer ? (square) => { setSquareAnswer(null); squareAnswer(square); } : undefined}
              onMove={play}
              disabled={!!feedbackFen || (!squareAnswer && (busy || (!explore && (!atLatest || (!analysisMode && !!game && (!isPlayerTurn || finished))))))}
            />
          </div>
          {!analysisMode && game && <LastMoveFeedback game={game} ply={at} onVisual={highlightVisual} activeVisual={activeVisual} />}
          {activeVisual && <div className="board-explanation" role="status"><span>{feedbackFen && <strong>{t('feedbackPosition')}. </strong>}{activeVisual.text}</span><button className="text-button" onClick={clearVisual}>{t('clearVisuals')}</button></div>}
          {explore && <VariationPlayer base={explore.base} moves={explore.moves} cursor={variationCursor(explore)} onCursor={(cursor) => setExplore({ ...explore, cursor })} playing={playing} onPlaying={setPlaying} speed={speed} onSpeed={setSpeed} label={explore.label} />}
          <div className="player-bottom">
            <div className="player-row">
              <span className="avatar">
                <UserRound size={22} />
              </span>
              <div>
                <strong>{t('you')}</strong>
                <small>
                  {t(game?.player_color || preferences.player_color)}{' '}
                  <span className="captured-pieces" aria-label="Captured pieces">
                    {captureText(game?.player_color === 'black' ? 'b' : 'w')}
                  </span>
                </small>
              </div>
            </div>
            <div className="board-navigation">
              <button
                className="icon-button"
                title={t('first')}
                aria-label={t('first')}
                disabled={!!explore || at === 0}
                onClick={() => setPly(0)}
              >
                <ChevronFirst size={19} />
              </button>
              <button
                className="icon-button"
                title={t('previous')}
                aria-label={t('previous')}
                disabled={!!explore || at === 0}
                onClick={() => setPly(Math.max(0, at - 1))}
              >
                <ChevronLeft size={19} />
              </button>
              <button
                className="icon-button"
                title={t('next')}
                aria-label={t('next')}
                disabled={!!explore || atLatest}
                onClick={() => setPly(at + 1)}
              >
                <ChevronRight size={19} />
              </button>
              <button
                className="icon-button"
                title={t('last')}
                aria-label={t('last')}
                disabled={!!explore || atLatest}
                onClick={() => setPly(null)}
              >
                <ChevronLast size={19} />
              </button>
              <span className="toolbar-divider" />
              <button
                className="icon-button"
                aria-label={t('flip')}
                title={t('flip')}
                onClick={() => setFlipped(!flipped)}
              >
                <Repeat2 size={19} />
              </button>
            </div>
          </div>
          <div className="board-toolbar">
            <span className={`turn-status ${chess.isCheck() ? 'check' : ''}`}>
              <span className={`turn-dot ${chess.turn() === 'w' ? 'white' : 'black'}`} />
              {busy ? <Spinner /> : status}
            </span>
            {!explore ? (
              <div className="explore-actions">
                {(!game || (game.mode !== 'computer' && !(analysisMode && game.mode !== 'analysis'))) && (
                  <button
                    className="outline-button"
                    disabled={busy || !game?.moves.length || !atLatest}
                    onClick={() => void mutate((g) => api<Game>(`/games/${g.id}/undo`, { revision: g.revision }))}
                  >
                    <Undo2 size={17} />
                    {t('undo')}
                  </button>
                )}
                <button className="outline-button" onClick={enterExplore}>
                  <ScanEye size={17} />
                  {t('explore')}
                </button>
              </div>
            ) : (
              <div className="explore-actions">
                <button
                  className="icon-button"
                  aria-label={t('undo')}
                  title={t('undo')}
                  disabled={!explore.moves.length}
                  onClick={() =>
                    setExplore({
                      ...explore,
                      moves: explore.moves.slice(0, Math.max(0, variationCursor(explore) - 1)),
                      cursor: Math.max(0, variationCursor(explore) - 1),
                    })
                  }
                >
                  <Undo2 size={18} />
                </button>
                <button
                  className="icon-button"
                  aria-label={t('reset')}
                  title={t('reset')}
                  onClick={() => { setPlaying(false); setExplore({ ...explore, moves: [], cursor: 0 }); }}
                >
                  <RotateCcw size={18} />
                </button>
                {committable(game, explore) && (
                  <button
                    className="primary-button"
                    disabled={!explore.moves.length || busy}
                    onClick={() => void commit()}
                  >
                    {t('commit')}
                    <ArrowRight size={15} />
                  </button>
                )}
              </div>
            )}
          </div>
          {!analysisMode && <div className="play-mode-select"><label htmlFor="workspace-play-mode">{t('playMode')}</label><select id="workspace-play-mode" value={playMode} onChange={(event) => setPlayMode(event.target.value as typeof playMode)}><option value="automatic">{t('automaticPlay')}</option><option value="coach_first">{t('coachFirst')}</option><option value="independent">{t('independent')}</option></select>{playMode === 'coach_first' && <small>{t('coachFirstHelp')}</small>}</div>}
          {computerReady && (
            <button className="computer-button" disabled={busy} onClick={() => void computer()}>
              <Bot size={18} />
              {t('computerMove')}
              <ArrowRight size={17} />
            </button>
          )}
          {!atLatest && !explore && (
            <div className="review-position">
              <span>
                {t('viewing')} {at}
              </span>
              <button className="text-button" onClick={() => setPly(null)}>
                {t('latest')}
              </button>
            </div>
          )}
          {explore && (
            <div className="explore-line">
              {analysisRequest.isFetching ? (
                <Spinner label={t('thinking')} />
              ) : preferences.show_evaluation &&
                (whiteCp != null || displayedAnalysis?.candidates[0]?.white_mate != null) ? (
                <strong>
                  {evaluationText(whiteCp, displayedAnalysis?.candidates[0]?.white_mate)}
                  {rootCp != null && whiteCp != null && ` · Δ ${((whiteCp - rootCp) / 100).toFixed(2)}`}
                </strong>
              ) : null}
              <ErrorNotice error={analysisRequest.error} />
            </div>
          )}
        </section>
        <CoachPanel
          key={`${analysisMode}-${game?.id || 'new'}`}
          onPickSquare={(answer) => setSquareAnswer(() => answer)}
          onCommitCandidate={!feedbackFen && !explore && atLatest && !finished && ((!game && analysisMode) || game?.mode === 'analysis' || (!analysisMode && isPlayerTurn)) ? (uci, base, revision) => commitCalculated(uci, base, revision) : undefined}
          orientation={displayOrientation}
          positionPending={busy}
          reviewMode={analysisMode}
          onExplore={enterExplore}
          fen={fen}
          game={game}
          preferences={playMode === 'independent' ? { ...preferences, coaching_mode: 'independent', feedback: 'none' } : preferences}
          onVisual={highlightVisual}
          activeVisual={activeVisual}
          onRetry={async (base, rootPly) => {
            if (!game || rootPly === undefined) { retryPosition(base, rootPly); return; }
            try {
              const exercise = await api<Exercise>(`/games/${game.id}/retry`, { ply: rootPly });
              navigate(learnPath(exercise.category, exercise.id));
            } catch (failure) {
              if (failure instanceof ApiError && failure.status === 422) retryPosition(base, rootPly);
              else setError(failure);
            }
          }}
          exploring={!!explore}
          onPreview={preview}
          onHoverMove={setHoveredMove}
          onToggleMove={toggleHighlightedMove}
          highlightedMove={highlightedMove}
          ply={at}
          onNavigate={(p) => {
            setPly(p);
            clearVisual();
            setExplore(null);
          }}
          analysis={displayedAnalysis}
          onAnalysis={setAnalysis}
        />
      </div>
      <div className="game-utilities">
        <span>
          <Check size={14} />
          {game ? t('saved') : t('privacy')}
        </span>
        <div>
          {game && game.mode !== 'computer' && !(analysisMode && game.mode !== 'analysis') && (
            <button
              className="text-button"
              disabled={busy || !game.can_redo || !!explore}
              onClick={() => void mutate((g) => api<Game>(`/games/${g.id}/redo`, { revision: g.revision }))}
            >
              <Redo2 size={15} />
              {t('redo')}
            </button>
          )}
          <button className="text-button" onClick={() => setImporting(true)}>
            <Upload size={15} />
            {t('importPgn')}
          </button>
          {game && (
            <>
              <button className="text-button" onClick={() => void exportPgn()}>
                <Download size={15} />
                {t('export')}
              </button>
              {!analysisMode && !finished && (
                <Link className="text-button" href={analysisPath(game.id)}>
                  {t('analyzeGame')}
                </Link>
              )}
            </>
          )}
        </div>
      </div>
      {setup && !analysisMode && (
        <GameSetup
          analysisMode={analysisMode}
          preferences={preferences}
          onClose={() => setSetup(false)}
          onStart={async (body) => {
            try {
              const g = await create(body);
              save(g);
              setExplore(null);
              setSetup(false);
            } catch (e) {
              setError(e);
            }
          }}
        />
      )}
      {importing && (
        <ImportModal
          onClose={() => setImporting(false)}
          onImport={async (value) => {
            const isFen = value.trim().split(/\s+/).length === 6 && !value.includes('[');
            const g = await api<Game>('/games', {
              mode: 'analysis',
              player_color: preferences.player_color,
              difficulty: preferences.difficulty,
              ...(isFen ? { fen: value.trim() } : { pgn: value.trim() }),
            });
            selectGame(g);
            setImporting(false);
          }}
        />
      )}
    </BoardVisualPreviewContext.Provider>
  );
}
