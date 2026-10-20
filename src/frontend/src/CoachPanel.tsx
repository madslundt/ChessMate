import { useEffect, useRef, useState } from 'react';
import { ChartNoAxesColumnIncreasing, ChevronRight, Lightbulb, MessageCircle, Send, Sparkles } from 'lucide-react';
import { api, streamCoach } from './api';
import { useT, type TranslationKey } from './i18n';
import { evaluationText } from './Board';
import { ErrorNotice, Spinner } from './components';
import { GameReview } from './GameReview';
import type { Analysis, Candidate, ChatMessage, Game, Preferences } from './types';
const fallbackLabels: Record<string, TranslationKey> = {
  not_configured: 'coachNotConfigured',
  timeout: 'coachTimeout',
  authentication: 'coachAuthentication',
  tls_certificate: 'coachCertificate',
  connection: 'coachConnection',
  server_error: 'coachServerError',
  busy: 'coachBusy',
  invalid_response: 'coachInvalidResponse',
};
interface Props {
  reviewMode: boolean;
  onExplore: () => void;
  fen: string;
  game: Game | null;
  preferences: Preferences;
  exploring: boolean;
  onPreview: (candidate: Candidate, baseFen?: string, rootPly?: number) => void;
  onHoverMove: (uci: string | null) => void;
  onToggleMove: (uci: string) => void;
  highlightedMove?: string | null;
  onNavigate: (ply: number) => void;
  ply: number;
  onAnalysis: (a: Analysis) => void;
  analysis: Analysis | null;
}
export function CoachPanel({
  reviewMode,
  onExplore,
  fen,
  game,
  preferences,
  exploring,
  onPreview,
  onHoverMove,
  onToggleMove,
  highlightedMove,
  onNavigate,
  ply,
  onAnalysis,
  analysis,
}: Props) {
  const t = useT(),
    [tab, setTab] = useState<'coach' | 'moves' | 'review'>(reviewMode ? 'review' : 'coach'),
    [messages, setMessages] = useState<ChatMessage[]>([]),
    [question, setQuestion] = useState(''),
    [busy, setBusy] = useState(false),
    [analyzing, setAnalyzing] = useState(false),
    [showCandidates, setShowCandidates] = useState(false),
    [hintLevel, setHintLevel] = useState(0),
    [hint, setHint] = useState(''),
    [hintMove, setHintMove] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null);
  const controller = useRef<AbortController | null>(null),
    currentFen = useRef(fen),
    scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    currentFen.current = fen;
    controller.current?.abort();
    setBusy(false);
    setAnalyzing(false);
    setShowCandidates(false);
    setHint('');
    setHintMove(null);
    setHintLevel(0);
    setError(null);
  }, [fen]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    let cancelled = false;
    if (!game || exploring || (reviewMode && tab !== 'coach')) return;
    api<{ messages: ChatMessage[] }>(`/games/${game.id}/conversation?fen=${encodeURIComponent(fen)}`)
      .then((result) => {
        if (!cancelled && currentFen.current === fen)
          setMessages((previous) =>
            previous.some((m) => m.fen === fen) ? previous : [...previous, ...result.messages],
          );
      })
      .catch(() => {
        /* Gameplay remains available if saved conversations cannot be loaded. */
      });
    return () => {
      cancelled = true;
    };
  }, [game?.id, fen, exploring, reviewMode, tab]);

  useEffect(() => {
    scroll.current?.scrollTo({
      top: scroll.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, busy, hint]);
  const budget = {
    time_ms: preferences.analysis_time_ms,
    depth: preferences.analysis_depth,
    candidates: preferences.candidate_count,
  };
  async function compare() {
    const requested = fen;
    setAnalyzing(true);
    setError(null);
    try {
      const result = await api<Analysis>('/analysis', {
        fen,
        ...budget,
        candidates: 3,
      });
      if (currentFen.current === requested && result.fen === requested) {
        onAnalysis(result);
        setShowCandidates(true);
      }
    } catch (e) {
      if (currentFen.current === requested) setError(e);
    } finally {
      if (currentFen.current === requested) setAnalyzing(false);
    }
  }
  async function requestHint() {
    if (!preferences.progressive_hints) {
      setHint(t('hintDisabled'));
      return;
    }
    const level = Math.min(hintLevel + 1, 4),
      requested = fen;
    setAnalyzing(true);
    try {
      const result = await api<{ text?: string; hint?: string; fen?: string; highlight_move?: string }>('/hint', {
        fen,
        level,
        language: preferences.coach_language,
        ...budget,
      });
      if (currentFen.current === requested) {
        setHint(result.text || result.hint || '');
        setHintMove(result.highlight_move || null);
        setHintLevel(level);
        if (level === 4) await compare();
      }
    } catch (e) {
      if (currentFen.current === requested) setError(e);
    } finally {
      if (currentFen.current === requested) setAnalyzing(false);
    }
  }
  async function send(text = question) {
    if (!text.trim() || busy) return;
    const requested = fen;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const history = messages
      .filter((m) => m.fen === fen)
      .slice(-10)
      .map(({ role, content }) => ({ role, content }));
    setQuestion('');
    setError(null);
    setBusy(true);
    setMessages((m) => [...m, { role: 'user', content: text, fen }, { role: 'assistant', content: '', fen }]);
    try {
      await streamCoach(
        {
          fen,
          ...budget,
          question: text,
          game_id: game?.id,
          revision: game?.revision,
          explore: exploring,
          language: preferences.coach_language,
          history,
        },
        (event, data) => {
          if (currentFen.current !== requested) return;
          const content = String(data.text || data.content || '');
          if (event === 'error') {
            setError(new Error(String(data.message || data.detail || content)));
            return;
          }
          if (event === 'token' || event === 'message' || event === 'done')
            setMessages((m) => {
              const last = m[m.length - 1];
              if (last?.role !== 'assistant' || last.fen !== requested) return m;
              return [
                ...m.slice(0, -1),
                {
                  ...last,
                  content: event === 'done' && content ? content : last.content + content,
                  source: String(data.source || last.source || ''),
                  fallback_reason:
                    typeof data.fallback_reason === 'string' ? data.fallback_reason : last.fallback_reason,
                },
              ];
            });
          else if (event === 'status' && data.source)
            setMessages((m) => m.map((v, i) => (i === m.length - 1 ? { ...v, source: String(data.source) } : v)));
        },
        abort.signal,
      );
    } catch (e) {
      if (!abort.signal.aborted && currentFen.current === requested) setError(e);
    } finally {
      if (currentFen.current === requested) setBusy(false);
    }
  }
  const latest = game?.moves
    .slice(0, ply)
    .filter((m) => m.feedback)
    .at(-1)?.feedback;
  const cls = latest?.classification?.toLowerCase();
  const feedbackVisible =
    preferences.feedback !== 'none' &&
    ((!['mistakes'].includes(preferences.feedback) && preferences.feedback_frequency !== 'mistakes') ||
      ['mistake', 'blunder', 'inaccuracy'].includes(cls || ''));
  useEffect(() => {
    if (latest && feedbackVisible && preferences.show_alternatives && !preferences.hide_best_moves && !exploring)
      void compare();
  }, [fen, game?.revision, preferences.show_alternatives, preferences.hide_best_moves]);
  const guidedPiece =
    analysis?.fen === fen &&
    !exploring &&
    preferences.coaching_mode !== 'independent' &&
    fen.split(' ')[1] === (game?.player_color === 'black' ? 'b' : 'w')
      ? (analysis.observations?.exposed_pieces as { square: string; color: string; piece: string }[] | undefined)?.find(
          (p) => p.color === (game?.player_color || 'white'),
        )
      : undefined;
  const guidedText = guidedPiece
    ? preferences.coach_language === 'da'
      ? `Din brik på ${guidedPiece.square} er angrebet og geometrisk udækket. ${preferences.guided_questions ? 'Hvordan kan du beskytte den?' : 'Undersøg om den skal beskyttes.'} Et slag er ikke nødvendigvis sikkert.`
      : `Your ${guidedPiece.piece} on ${guidedPiece.square} is attacked and geometrically undefended. ${preferences.guided_questions ? 'How could you protect it?' : 'Check whether it needs protection.'} An attack alone does not prove a winning capture.`
    : null;
  const phase = analysis?.observations?.phase;
  const learningText =
    preferences.coaching_mode === 'learning' && !exploring && phase
      ? preferences.coach_language === 'da'
        ? {
            opening:
              'I åbningen kan du sammenligne tre ting: centrum, udvikling af lette officerer og kongens sikkerhed. Undersøg konkrete skakker og slag, før du følger et princip.',
            middlegame:
              'Begynd med modstanderens trusler. Find derefter din mindst aktive brik, og sammenlign to måder at forbedre den på. Undersøg modstanderens svar på begge idéer.',
            endgame:
              'Kongen og fribønderne bliver vigtige i slutspillet. Beregn korte varianter, og kontrollér altid pat, før du forvandler en bonde.',
          }[phase as 'opening']
        : {
            opening:
              'In the opening, compare three things: central control, minor-piece development, and king safety. Check concrete checks and captures before following a principle.',
            middlegame:
              'Start with the opponent’s threats. Then find your least active piece and compare two ways to improve it. Look at the opponent’s reply to each idea.',
            endgame:
              'In the endgame, king activity and passed pawns matter. Calculate short lines and always check for stalemate before promoting a pawn.',
          }[phase as 'opening']
      : null;
  const moveOffset = game?.initial_fen.split(' ')[1] === 'b' ? 1 : 0;
  const firstMove = Number(game?.initial_fen.split(' ')[5] || 1);
  return (
    <section className="coach-panel panel" aria-label={t(reviewMode ? 'analyze' : 'coach')}>
      <div
        className="panel-tabs"
        role={reviewMode ? 'tablist' : undefined}
        aria-label={t(reviewMode ? 'analyze' : 'coach')}
      >
        {reviewMode && (
          <button
            id="review-tab"
            role="tab"
            aria-selected={tab === 'review'}
            aria-controls="workspace-panel"
            onClick={() => setTab('review')}
            className={tab === 'review' ? 'selected' : ''}
          >
            {t('review')}
          </button>
        )}
        <button
          id="coach-tab"
          role={reviewMode ? 'tab' : undefined}
          aria-selected={reviewMode ? tab === 'coach' : undefined}
          aria-controls="workspace-panel"
          onClick={() => setTab('coach')}
          className={tab === 'coach' ? 'selected' : ''}
        >
          {t(reviewMode ? 'chat' : 'coach')}
        </button>
        <button
          id="moves-tab"
          role={reviewMode ? 'tab' : undefined}
          aria-selected={reviewMode ? tab === 'moves' : undefined}
          aria-controls="workspace-panel"
          onClick={() => setTab('moves')}
          className={tab === 'moves' ? 'selected' : ''}
        >
          {t('moves')}
          {!!game?.moves.length && <span className="move-count">{game.moves.length}</span>}
        </button>
      </div>
      <div
        id="workspace-panel"
        className="workspace-panel"
        role={reviewMode ? 'tabpanel' : undefined}
        aria-labelledby={`${tab}-tab`}
      >
        {tab === 'review' ? (
          <GameReview
            game={game}
            ply={ply}
            exploring={exploring}
            onNavigate={onNavigate}
            onExplore={onExplore}
            onPreview={onPreview}
            onHoverMove={onHoverMove}
            onToggleMove={onToggleMove}
            highlightedMove={highlightedMove}
            preferences={preferences}
          />
        ) : tab === 'moves' ? (
          <div className="moves-panel">
            <h3>{t('moves')}</h3>
            {!game?.moves.length ? (
              <p className="muted">{t('noMoves')}</p>
            ) : (
              <div className="move-table">
                {Array.from({ length: Math.ceil(((game?.moves.length || 0) + moveOffset) / 2) }, (_, i) => (
                  <div className="move-row" key={i}>
                    <span>{firstMove + i}.</span>
                    {[0, 1].map((side) => {
                      const index = i * 2 + side - moveOffset,
                        m = game?.moves[index];
                      return (
                        <button
                          key={side}
                          disabled={!m}
                          className={ply === index + 1 ? 'current' : ''}
                          onPointerEnter={() => m && onHoverMove(m.uci)}
                          onPointerLeave={() => onHoverMove(null)}
                          onClick={() => {
                            if (!m) return;
                            onNavigate(index + 1);
                            onToggleMove(m.uci);
                          }}
                        >
                          {m?.san || '—'}
                          {m?.feedback?.classification && (
                            <span className={`move-quality ${m.feedback.classification.toLowerCase()}`} />
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="coach-scroll" ref={scroll}>
              <div className="coach-intro">
                <span className="round-icon">
                  <MessageCircle size={21} />
                </span>
                <p>{t('welcomeText')}</p>
              </div>
              {learningText && (
                <div className="feedback-note">
                  <p>{learningText}</p>
                </div>
              )}
              {guidedText && (
                <div className="hint-note guided-note">
                  <p>{guidedText}</p>
                </div>
              )}
              {latest && feedbackVisible && !exploring && (
                <div className={`feedback-note ${cls || ''}`} data-testid="move-feedback">
                  <div>
                    <Sparkles size={16} />
                    <strong>
                      {cls && ['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder'].includes(cls)
                        ? t(cls as 'good')
                        : t('unclassified')}
                    </strong>
                  </div>
                  <p>{latest.text || latest.explanation || latest.assessment}</p>
                  {preferences.feedback === 'detailed' && latest.takeaway && (
                    <p className="takeaway">{latest.takeaway}</p>
                  )}
                </div>
              )}
              <div className="coach-actions">
                <button className="outline-button" onClick={requestHint} disabled={analyzing || busy || hintLevel >= 4}>
                  <Lightbulb size={20} />
                  {hintLevel ? t('nextHint') : t('hint')}
                  {hintLevel > 0 && <small>{hintLevel}/4</small>}
                </button>
                <button className="outline-button" onClick={compare} disabled={analyzing}>
                  <ChartNoAxesColumnIncreasing size={20} />
                  {t('compare')}
                </button>
              </div>
              {!hint && !showCandidates && <p className="hint-caption">{t('hintsFirst')}</p>}
              {analyzing && <Spinner label={t('thinking')} />}
              {hint && (
                <div
                  className={`hint-note hint-note-selectable${highlightedMove === hintMove ? ' is-highlighted' : ''}`}
                  data-testid="position-hint"
                  role={hintMove ? 'button' : undefined}
                  tabIndex={hintMove ? 0 : undefined}
                  aria-pressed={hintMove ? highlightedMove === hintMove : undefined}
                  onPointerEnter={() => hintMove && onHoverMove(hintMove)}
                  onPointerLeave={() => onHoverMove(null)}
                  onClick={() => hintMove && onToggleMove(hintMove)}
                  onKeyDown={(event) => {
                    if (hintMove && (event.key === 'Enter' || event.key === ' ')) {
                      event.preventDefault();
                      onToggleMove(hintMove);
                    }
                  }}
                >
                  <span>
                    {t('hint')} {hintLevel}/4
                  </span>
                  <p>{hint}</p>
                </div>
              )}
              {showCandidates && analysis?.fen === fen && (
                <div className="candidate-list">
                  <small className="muted">
                    {t(fen.split(' ')[1] === 'w' ? 'white' : 'black')} {t('sideToMove')}
                  </small>
                  {!analysis.candidates.length && <p>{t('noCandidates')}</p>}
                  {analysis.candidates.map((c, i) => (
                    <div className="candidate" key={c.uci}>
                      <button
                        className={`candidate-title${highlightedMove === c.uci ? ' is-highlighted' : ''}`}
                        aria-pressed={highlightedMove === c.uci}
                        onPointerEnter={() => onHoverMove(c.uci)}
                        onPointerLeave={() => onHoverMove(null)}
                        onClick={() => onToggleMove(c.uci)}
                      >
                        <span className="candidate-rank">{i + 1}</span>
                        <strong>{c.san}</strong>
                        {preferences.show_evaluation && (
                          <span className="eval-score">{evaluationText(c.cp, c.mate)}</span>
                        )}
                      </button>
                      <p>{c.explanation || c.idea || `${t('candidatePreview')}: ${c.san}`}</p>
                      {preferences.show_pv && (
                        <>
                          <code>{c.pv?.slice(0, 6).join(' ')}</code>
                          {c.risk && <p className="candidate-risk">{c.risk}</p>}
                        </>
                      )}
                      {preferences.show_evaluation && i > 0 && c.cp !== null && analysis.candidates[0].cp !== null && (
                        <small className="muted">Δ {((c.cp - analysis.candidates[0].cp) / 100).toFixed(2)}</small>
                      )}
                      <button className="text-button" onClick={() => onPreview(c)}>
                        {t('candidatePreview')}
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {messages.map((m, i) => (
                <div className={`chat-message ${m.role}`} key={i}>
                  <span>
                    {m.role === 'user' ? t('you') : t('coach')}
                    {m.fen !== fen && <small> · {t('viewing')}</small>}
                  </span>
                  <p>
                    {m.content ||
                      (busy && i === messages.length - 1 ? <Spinner label={t('coachThinking')} /> : t('offline'))}
                  </p>
                  {m.source && m.source !== 'analyzing' && m.role === 'assistant' && (
                    <small className="message-source">
                      {['llm', 'local_llm_verified'].includes(m.source) ? t('sourceLlm') : t('sourceFallback')}
                      {m.fallback_reason && ` · ${t(fallbackLabels[m.fallback_reason] || 'coachInvalidResponse')}`}
                    </small>
                  )}
                </div>
              ))}
              <ErrorNotice error={error} onDismiss={() => setError(null)} />
            </div>
            <form
              className="chat-form"
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
            >
              <label className="sr-only" htmlFor="coach-question">
                {t('ask')}
              </label>
              <textarea
                id="coach-question"
                placeholder={t('ask')}
                value={question}
                rows={1}
                maxLength={2000}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                type="submit"
                className="primary-button"
                aria-label={t('send')}
                disabled={!question.trim() || busy}
              >
                <Send size={19} />
              </button>
            </form>
          </>
        )}
      </div>
    </section>
  );
}
