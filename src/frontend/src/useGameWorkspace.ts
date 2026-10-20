import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Chess } from 'chess.js';
import { api, ApiError } from './api';
import { replayVariation } from './exploration';
import { useT } from './i18n';
import type { Analysis, Candidate, Color, Game, Preferences } from './types';
const START = new Chess().fen();
export interface WorkspaceProps {
  activeGameId: string | null;
  preferences: Preferences;
  selectGame: (game: Game) => void;
  analysisMode: boolean;
}
export function useGameWorkspace({ activeGameId, preferences, selectGame, analysisMode }: WorkspaceProps) {
  const t = useT(),
    client = useQueryClient(),
    [setup, setSetup] = useState(false),
    [importing, setImporting] = useState(false),
    [ply, setPly] = useState<number | null>(null),
    [flipped, setFlipped] = useState(false),
    [explore, setExplore] = useState<{
      base: string;
      moves: string[];
      revision: number;
      atLatest: boolean;
    } | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [pendingMove, setPendingMove] = useState<{
      gameId: string | null;
      base: string;
      fen: string;
      uci: string;
    } | null>(null),
    [analysis, setAnalysis] = useState<Analysis | null>(null),
    [notice, setNotice] = useState('');
  const lock = useRef(false);
  const computerAttempt = useRef<string | null>(null);
  const gameQuery = useQuery({
    queryKey: ['game', activeGameId],
    queryFn: ({ signal }) => api<Game>(`/games/${activeGameId}`, undefined, undefined, signal),
    enabled: !!activeGameId,
    retry: false,
  });
  const game = gameQuery.data && (analysisMode || gameQuery.data.mode !== 'analysis') ? gameQuery.data : null;
  const at = ply === null ? game?.moves.length || 0 : Math.min(ply, game?.moves.length || 0),
    actualFen = at === 0 ? game?.initial_fen || START : game?.moves[at - 1]?.fen || START;
  const chess = useMemo(() => {
    return replayVariation(explore?.base || actualFen, explore?.moves || []);
  }, [actualFen, explore]);
  const fen = chess.fen(),
    atLatest = at === (game?.moves.length || 0),
    isPlayerTurn = chess.turn() === (game?.player_color === 'black' ? 'b' : 'w'),
    finished = !!game && game.result !== '*' && !!game.result;
  const orientation: Color =
    preferences.orientation === 'player' ? game?.player_color || preferences.player_color : preferences.orientation;
  const displayOrientation = flipped ? (orientation === 'white' ? 'black' : 'white') : orientation;
  const analysisRequest = useQuery({
    queryKey: ['explore-analysis', fen, preferences.analysis_time_ms, preferences.analysis_depth],
    queryFn: () =>
      api<Analysis>('/analysis', {
        fen,
        time_ms: preferences.analysis_time_ms,
        depth: preferences.analysis_depth,
        candidates: 3,
      }),
    enabled:
      !!explore ||
      preferences.show_evaluation ||
      preferences.show_evaluation_bar ||
      (!!game?.moves.length && isPlayerTurn && preferences.coaching_mode !== 'independent'),
    staleTime: 60000,
  });
  const rootAnalysis = useQuery({
    queryKey: ['explore-analysis', explore?.base, preferences.analysis_time_ms, preferences.analysis_depth],
    queryFn: () =>
      api<Analysis>('/analysis', {
        fen: explore!.base,
        time_ms: preferences.analysis_time_ms,
        depth: preferences.analysis_depth,
        candidates: 3,
      }),
    enabled: !!explore,
    staleTime: 60000,
  });
  const displayedAnalysis =
    analysis?.fen === fen ? analysis : analysisRequest.data?.fen === fen ? analysisRequest.data : null;
  const whiteCp = displayedAnalysis?.candidates[0]?.white_cp;
  const rootCp = rootAnalysis.data?.candidates[0]?.white_cp;
  useEffect(() => {
    setPly(null);
    setExplore(null);
    setPendingMove(null);
    setAnalysis(null);
    setError(null);
  }, [activeGameId]);
  useEffect(() => {
    if (gameQuery.error) setError(gameQuery.error);
  }, [gameQuery.error]);
  async function create(body: Record<string, unknown> = {}) {
    return api<Game>('/games', {
      mode: analysisMode ? 'analysis' : 'training',
      player_color: preferences.player_color,
      difficulty: preferences.difficulty,
      ...body,
    });
  }
  function save(g: Game) {
    client.setQueryData(['game', g.id], g);
    client.invalidateQueries({ queryKey: ['games'] });
    setPly(null);
    if (g.id !== activeGameId) selectGame(g);
  }
  async function mutate(action: (g: Game) => Promise<Game>) {
    if (lock.current || (activeGameId && !game)) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const g = game || (await create());
      // Preserve the new game's identity even if its first move fails to save.
      if (!game) save(g);
      save(await action(g));
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.status === 409) await gameQuery.refetch();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function play(uci: string) {
    if (lock.current || (activeGameId && !game)) return;
    if (explore) {
      setExplore({ ...explore, moves: [...explore.moves, uci] });
      setAnalysis(null);
      return;
    }
    if (analysisMode && game && game.mode !== 'analysis') {
      setExplore({ base: actualFen, moves: [uci], revision: game.revision, atLatest: false });
      setAnalysis(null);
      return;
    }
    if (!atLatest) return;
    const next = new Chess(fen);
    next.move(uci);
    // Preview only the board; saved history, coaching and analysis keep the confirmed position.
    setPendingMove({ gameId: activeGameId, base: fen, fen: next.fen(), uci });
    try {
      await mutate((g) => api<Game>(`/games/${g.id}/moves`, { move: uci, revision: g.revision }));
    } finally {
      // A failed save (including a revision conflict) restores the authoritative position.
      setPendingMove(null);
    }
  }
  const computerReady = !!game && !analysisMode && !explore && !isPlayerTurn && !finished && atLatest;
  async function computer() {
    if (!computerReady || !game) return;
    computerAttempt.current = `${game.id}:${game.revision}`;
    await mutate((g) => api<Game>(`/games/${g.id}/computer`, { revision: g.revision }));
  }
  useEffect(() => {
    if (
      preferences.auto_computer &&
      computerReady &&
      !busy &&
      game &&
      computerAttempt.current !== `${game.id}:${game.revision}`
    ) {
      const timer = setTimeout(() => {
        void computer();
      }, 900);
      return () => clearTimeout(timer);
    }
  }, [preferences.auto_computer, computerReady, game?.id, game?.revision, busy]);
  function enterExplore() {
    setExplore({
      base: actualFen,
      moves: [],
      revision: game?.revision || 0,
      atLatest: atLatest && !(analysisMode && game?.mode !== 'analysis'),
    });
    setAnalysis(null);
  }
  function preview(c: Candidate, baseFen?: string, rootPly?: number) {
    if (rootPly !== undefined) setPly(rootPly);
    setExplore({
      base: baseFen || fen,
      moves: c.pv_uci?.length ? c.pv_uci : [c.uci],
      revision: game?.revision || 0,
      atLatest: !baseFen && !explore && atLatest && !(analysisMode && game?.mode !== 'analysis'),
    });
    setAnalysis(null);
  }
  async function commit() {
    if (!explore?.moves[0] || !explore.atLatest) return;
    const first = explore.moves[0];
    await mutate(async (g) => {
      if (g.revision !== explore.revision) throw new Error(t('stale'));
      return api<Game>(`/games/${g.id}/moves`, {
        move: first,
        revision: g.revision,
      });
    });
    setExplore(null);
  }
  async function exportPgn() {
    if (!game) return;
    try {
      const res = await fetch(`/api/games/${game.id}/pgn`);
      if (!res.ok) throw new Error(t('offline'));
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `chessmate-${game.id.slice(0, 8)}.pgn`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e);
    }
  }
  const displayedMove =
    !explore && atLatest && pendingMove?.gameId === activeGameId && pendingMove?.base === actualFen
      ? pendingMove
      : null;
  const boardFen = displayedMove?.fen || fen;
  const lastMove = explore ? explore.moves.at(-1) : displayedMove?.uci || game?.moves[at - 1]?.uci;
  const captured = useMemo(() => {
    const c = new Chess(game?.initial_fen || START),
      pieces: { w: string[]; b: string[] } = { w: [], b: [] };
    for (const m of game?.moves.slice(0, at) || []) {
      const r = c.move(m.uci);
      if (r.captured) pieces[r.color].push(r.captured);
    }
    return pieces;
  }, [game, at]);
  const captureText = (side: 'w' | 'b') =>
    captured[side].map((p) => ({ p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚' })[p]).join('');
  const status =
    finished && !explore && atLatest
      ? game?.status === 'checkmate'
        ? t('checkmate')
        : game?.status === 'stalemate'
          ? t('stalemate')
          : t('draw')
      : chess.isCheckmate()
        ? t('checkmate')
        : chess.isStalemate()
          ? t('stalemate')
          : chess.isDraw()
            ? t('draw')
            : chess.isCheck()
              ? t('check')
              : explore
                ? `${chess.turn() === 'w' ? t('white') : t('black')} ${t('sideToMove')}`
                : isPlayerTurn || analysisMode
                  ? t('yourTurn')
                  : t('computerTurn');
  return {
    t,
    client,
    setup,
    setSetup,
    importing,
    setImporting,
    ply,
    setPly,
    flipped,
    setFlipped,
    explore,
    setExplore,
    error,
    setError,
    busy,
    analysis,
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
    exportPgn,
    lastMove,
    captureText,
    status,
    chess,
  };
}
