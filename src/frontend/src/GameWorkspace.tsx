import { useEffect, useState } from 'react';
import { Chess } from 'chess.js';
import {
  ArrowLeft,
  Bot,
  Check,
  Download,
  FlaskConical,
  GraduationCap,
  Plus,
  Redo2,
  Upload,
} from 'lucide-react';
import { api, ApiError } from './api';
import { trainingFocusLabel } from './RealisticTraining';
import { Board, evaluationText } from './Board';
import { PositionScore } from './PositionScore';
import { LastMoveFeedback } from './LastMoveFeedback';
import { CoachPanel } from './CoachPanel';
import { variationCursor } from './exploration';
import { VariationPlayer } from './VariationPlayer';
import { ErrorNotice, PageHeading } from './components';
import { GameLoading, GameSetup, ImportModal } from './GameDialogs';
import { useGameWorkspace, type WorkspaceProps } from './useGameWorkspace';
import { BoardVisualPreviewContext, useBoardVisuals } from './useBoardVisuals';
import { WorkspaceBoardControls } from './WorkspaceBoardControls';
import { PostGameSummary } from './GameReview';
import type { Exercise, Game, VisualInsight } from './types';
import { analysisPath, learnPath, navigate, Link } from './navigation';
export function GameWorkspace(props: WorkspaceProps) {
  const { analysisMode, selectGame } = props;
  const workspace = useGameWorkspace(props);
  const {
    t,
    preferences,
    setup,
    setSetup,
    importing,
    setImporting,
    setPly,
    explore,
    setExplore,
    playing,
    setPlaying,
    speed,
    setSpeed,
    retryPosition,
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
    displayedAnalysis,
    whiteCp,
    create,
    save,
    ensureGame,
    mutate,
    play,
    enterExplore,
    preview,
    commitCalculated,
    exportPgn,
    lastMove,
    status,
    chess,
  } = workspace;
  const [hoveredMove, setHoveredMove] = useState<string | null>(null);
  const [pinnedMove, setPinnedMove] = useState<string | null | undefined>(undefined);
  const [squareAnswer, setSquareAnswer] = useState<((square: string) => void) | null>(null);
  const highlightedMove = hoveredMove ?? pinnedMove;
  const { activeVisual, arrows, targets, feedbackFen, showVisual, clearVisual, previewVisual, previewing } = useBoardVisuals({
    fen,
    preferences,
    highlightedMove,
    exploring: !!explore,
    lastMove,
    retryPosition,
  });
  function highlightVisual(insight: VisualInsight) {
    setHoveredMove(null);
    setPinnedMove(null);
    showVisual(insight);
  }
  useEffect(() => {
    setHoveredMove(null);
    setPinnedMove(undefined);
    setSquareAnswer(null);
  }, [fen, game?.id]);
  function toggleHighlightedMove(uci: string) {
    setPinnedMove((current) => (current === uci ? null : uci));
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
      {game?.training_context && !analysisMode && (
        <div className="training-context-banner">
          <GraduationCap size={21} />
          <div>
            <strong>
              {t(game.training_context.blind ? 'blindTraining' : 'focusedTraining')}
              {!game.training_context.blind &&
                ` · ${trainingFocusLabel(game.training_context.focus || 'mixed', preferences.language)}`}
            </strong>
            <p>
              {preferences.language === 'da'
                ? 'Spil videre, undersøg modstanderens svar, og lær af dine beslutninger.'
                : 'Keep playing, examine your opponent’s replies, and learn from your decisions.'}
            </p>
          </div>
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
                  : !game && (preferences.difficulty_mode || 'adaptive') === 'adaptive'
                    ? t('adaptiveDifficulty')
                    : `${game?.difficulty || preferences.difficulty} / 5 · ${t((game?.difficulty_mode || preferences.difficulty_mode || 'adaptive') === 'adaptive' ? 'adaptiveDifficulty' : 'manualDifficulty')}`}
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
          {squareAnswer && (
            <div className="board-explanation" role="status">
              {t('selectSquarePrompt')}
              <button className="text-button" onClick={() => setSquareAnswer(null)}>
                {t('cancelChoice')}
              </button>
            </div>
          )}
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
              result={
                game && finished && atLatest && !explore && !feedbackFen && !analysisMode
                  ? {
                      id: `${game.id}:${game.revision}`,
                      score: game.result!,
                      playerColor: game.player_color,
                      reason: status,
                    }
                  : undefined
              }
              animate={!explore || preferences.animate_variations !== false}
              preferences={preferences}
              orientation={displayOrientation}
              lastMove={lastMove}
              highlightedMove={feedbackFen ? null : highlightedMove}
              arrows={arrows}
              targets={targets}
              onSelectSquare={
                !feedbackFen && squareAnswer
                  ? (square) => {
                      setSquareAnswer(null);
                      squareAnswer(square);
                    }
                  : undefined
              }
              onMove={play}
              disabled={
                !!feedbackFen ||
                (!squareAnswer &&
                  (busy || (!explore && (!atLatest || (!analysisMode && !!game && (!isPlayerTurn || finished))))))
              }
            />
          </div>
          {!analysisMode && game && (
            <LastMoveFeedback game={game} ply={at} onVisual={highlightVisual} activeVisual={activeVisual} />
          )}
          {activeVisual && (
            <div className={`board-explanation ${previewing ? 'board-explanation-preview' : ''}`} role="status">
              <span>
                {feedbackFen && <strong>{t('feedbackPosition')}. </strong>}
                {activeVisual.text}
              </span>
              {!previewing && <button className="text-button" onClick={clearVisual}>
                {t('clearVisuals')}
              </button>}
            </div>
          )}
          {explore && (
            <VariationPlayer
              base={explore.base}
              moves={explore.moves}
              cursor={variationCursor(explore)}
              onCursor={(cursor) => setExplore({ ...explore, cursor })}
              playing={playing}
              onPlaying={setPlaying}
              speed={speed}
              onSpeed={setSpeed}
              label={explore.label}
            />
          )}
          <WorkspaceBoardControls workspace={workspace} analysisMode={analysisMode} preferences={preferences} />
        </section>
        <CoachPanel
          key={String(analysisMode)}
          ensureGame={ensureGame}
          onPickSquare={(answer) => setSquareAnswer(() => answer)}
          onCommitCandidate={
            !feedbackFen &&
            !explore &&
            atLatest &&
            !finished &&
            ((!game && analysisMode) || game?.mode === 'analysis' || (!analysisMode && isPlayerTurn))
              ? (uci, base, revision) => commitCalculated(uci, base, revision)
              : undefined
          }
          orientation={displayOrientation}
          positionPending={busy}
          reviewMode={analysisMode}
          onExplore={enterExplore}
          fen={fen}
          game={game}
          preferences={preferences}
          onVisual={highlightVisual}
          activeVisual={activeVisual}
          onRetry={async (base, rootPly) => {
            if (!game || rootPly === undefined) {
              retryPosition(base, rootPly);
              return;
            }
            try {
              const exercise = await api<Exercise>(`/games/${game.id}/retry`, {
                ply: rootPly,
              });
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
              {!analysisMode && !finished && <button className="text-button" disabled={busy || !game.moves.length} onClick={() => void mutate((current) => api<Game>(`/games/${current.id}/resign`, { revision: current.revision }))}>{t('resignGame')}</button>}
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
