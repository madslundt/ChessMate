import {
  ArrowRight,
  Bot,
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  ScanEye,
  Repeat2,
  Undo2,
  UserRound,
} from 'lucide-react';
import { api } from './api';
import { evaluationText } from './Board';
import { committable, variationCursor } from './exploration';
import { ErrorNotice, Spinner } from './components';
import type { useGameWorkspace } from './useGameWorkspace';
import type { Game, Preferences } from './types';

interface WorkspaceBoardControlsProps {
  workspace: ReturnType<typeof useGameWorkspace>;
  analysisMode: boolean;
  preferences: Preferences;
}
export function WorkspaceBoardControls({ workspace, analysisMode, preferences }: WorkspaceBoardControlsProps) {
  const {
    t,
    game,
    explore,
    at,
    atLatest,
    setPly,
    flipped,
    setFlipped,
    busy,
    chess,
    status,
    mutate,
    enterExplore,
    setExplore,
    setPlaying,
    commit,
    playMode,
    setPlayMode,
    computerReady,
    computer,
    analysisRequest,
    displayedAnalysis,
    whiteCp,
    rootCp,
    captureText,
  } = workspace;
  return (
    <>
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
          <button className="icon-button" aria-label={t('flip')} title={t('flip')} onClick={() => setFlipped(!flipped)}>
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
                onClick={() =>
                  void mutate((g) =>
                    api<Game>(`/games/${g.id}/undo`, {
                      revision: g.revision,
                    }),
                  )
                }
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
              onClick={() => {
                setPlaying(false);
                setExplore({ ...explore, moves: [], cursor: 0 });
              }}
            >
              <RotateCcw size={18} />
            </button>
            {committable(game, explore) && (
              <button className="primary-button" disabled={!explore.moves.length || busy} onClick={() => void commit()}>
                {t('commit')}
                <ArrowRight size={15} />
              </button>
            )}
          </div>
        )}
      </div>
      {!analysisMode && (
        <div className="play-mode-select">
          <label htmlFor="workspace-play-mode">{t('playMode')}</label>
          <select
            id="workspace-play-mode"
            value={playMode}
            onChange={(event) => setPlayMode(event.target.value as typeof playMode)}
          >
            <option value="automatic">{t('automaticPlay')}</option>
            <option value="coach_first">{t('coachFirst')}</option>
            <option value="independent">{t('independent')}</option>
          </select>
          {playMode === 'coach_first' && <small>{t('coachFirstHelp')}</small>}
        </div>
      )}
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
    </>
  );
}
