import { lazy, Suspense, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useCoachSession } from './useCoachSession';
import { ChartNoAxesColumnIncreasing, Lightbulb, MessageCircle, Send, Sparkles } from 'lucide-react';
import { useT } from './i18n';
import { CoachMessages } from './CoachMessages';
import { CandidateList } from './CandidateList';
import { HintCard } from './HintCard';
import { ConfidenceBadge } from './ConfidenceBadge';
import { ErrorNotice, Spinner } from './components';
import { GameReview } from './GameReview';
import { VoiceControls } from './VoiceControls';
import { api } from './api';
import { transcribeAudio, synthesizeSpeech, type SpeechSettings } from './speechClient';
import { VisualExplanation } from './VisualExplanation';
import { ExplanationText } from './ExplanationText';
import { ConsequenceComparison } from './ConsequenceComparison';
import { SocraticProgress } from './SocraticProgress';
const CalculationPractice = lazy(() => import('./CalculationPractice').then((module) => ({ default: module.CalculationPractice })));
import type { Analysis, Candidate, Color, Game, Preferences, VisualInsight } from './types';
function MoveFeedbackHistory({
  game,
  preferences,
  exploring,
  feedbackPly,
  currentFen,
  orientation,
  onVisual,
  onPreview,
  onRetry,
}: {
  game: Game | null;
  preferences: Preferences;
  exploring: boolean;
  feedbackPly: number;
  currentFen: string;
  orientation: Color;
  onVisual: (insight: VisualInsight) => void;
  onPreview: (candidate: Candidate, baseFen?: string, rootPly?: number) => void;
  onRetry: (baseFen: string, rootPly?: number) => void;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState<Record<string, string | null>>({});
  if (!game || exploring) return null;
  return (
    <>
      {game.moves.map((move, index) => {
        const feedback = move.feedback;
        const moveClass = feedback?.classification?.toLowerCase();
        const isBadMove = ['inaccuracy', 'mistake', 'blunder'].includes(moveClass || '');
        const isGoodMove = ['best', 'excellent', 'good'].includes(moveClass || '');
        const moveFeedbackVisible = preferences.feedback !== 'none' &&
          ((!['mistakes'].includes(preferences.feedback) && preferences.feedback_frequency !== 'mistakes') ||
            ['mistake', 'blunder', 'inaccuracy'].includes(moveClass || ''));
        if (!feedback || !moveFeedbackVisible) return null;
        const initialTurn = game.initial_fen.split(' ')[1];
        const moveColor = move.color || (feedback.actor_color as Color | undefined) ||
          (initialTurn === 'b'
            ? (index % 2 === 0 ? 'black' : 'white')
            : (index % 2 === 0 ? 'white' : 'black'));
        const moveNumber = Number(game.initial_fen.split(' ')[5] || 1) +
          Math.floor((index + (initialTurn === 'b' ? 1 : 0)) / 2);
        const isCurrentFeedback = index === feedbackPly;
        const moveBase = move.before_fen || (index === 0 ? game.initial_fen : game.moves[index - 1]?.fen);
        const expandedKey = `${game.id}-${index}-${move.uci}`;
        const activeExplanation = expanded[expandedKey];
        const threatInsights = feedback.insights?.filter((insight) => /threat|attack|check|defen|pin|fork|tactic/i.test(`${insight.claim_type || ''} ${insight.id} ${insight.text}`)) || [];
        const explanation = activeExplanation === 'bad'
          ? feedback.consequence || feedback.explanation || feedback.text || feedback.assessment
          : activeExplanation === 'good'
            ? feedback.explanation || feedback.text || feedback.assessment
            : activeExplanation === 'better'
              ? feedback.best?.explanation || feedback.best?.idea || (feedback.best ? `${t('betterMoveIs')} ${feedback.best.san}.` : t('noBetterMoveConfirmed'))
              : '';
        const toggleExplanation = (kind: string) => setExpanded((current) => ({
          ...current,
          [expandedKey]: current[expandedKey] === kind ? null : kind,
        }));
        return (
          <div className={`feedback-note move-feedback-entry ${moveColor} ${moveClass || ''}`} data-testid="move-feedback" key={`${index}-${move.uci}`}>
            <div className="move-feedback-heading">
              <span className="move-feedback-turn">
                <span className="move-feedback-color-dot" aria-hidden="true" />
                <strong>{moveColor === 'white' ? t('white') : t('black')}</strong>
              </span>
              <span className="move-feedback-san">{moveNumber}{moveColor === 'white' ? '.' : '...'} {move.san}</span>
            </div>
            <div>
              <Sparkles size={16} />
              <strong>
                {moveClass && ['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder', 'forced', 'uncertain'].includes(moveClass)
                  ? t(moveClass as 'good')
                  : t('unclassified')}
              </strong>
            </div>
            {feedback.actor === 'opponent' && <small>{t('opponentMove')}</small>}
            <ConfidenceBadge mode={feedback.analysis_mode} confidence={feedback.confidence} />
            <ExplanationText mode={preferences.explanation_mode}>
              <p>{feedback.text || feedback.explanation || feedback.assessment}</p>
              {feedback.consequence && feedback.consequence !== feedback.text && <p>{feedback.consequence}</p>}
            </ExplanationText>
            {activeExplanation === 'threats' && (threatInsights.length ? <div className="move-threat-details">{threatInsights.map((insight) => <p key={insight.id}>{insight.text}</p>)}{threatInsights.some((insight) => insight.fen === currentFen) && <VisualExplanation coaching={{ insights: threatInsights.filter((insight) => insight.fen === currentFen) }} onVisual={onVisual} onPreview={onPreview} />}</div> : <p className="muted">{t('threatsUnavailable')}</p>)}
            <div className="visual-explanation-actions move-feedback-actions">
              <button className="text-button" onClick={() => feedback.best && moveBase ? onPreview(feedback.best, moveBase, index) : toggleExplanation('better')}>{t('showBetterMove')}</button>
              <button className="text-button" onClick={() => toggleExplanation('threats')} aria-expanded={activeExplanation === 'threats'}>{t('showThreats')}</button>
              {isBadMove && <button className="text-button" onClick={() => toggleExplanation('bad')} aria-expanded={activeExplanation === 'bad'}>{t('whyWasBad')}</button>}
              {isGoodMove && <button className="text-button" onClick={() => toggleExplanation('good')} aria-expanded={activeExplanation === 'good'}>{t('whyWasGood')}</button>}
              {isBadMove && <button className="text-button" onClick={() => toggleExplanation('better')} aria-expanded={activeExplanation === 'better'}>{t('whatWasBetter')}</button>}
            </div>
            {activeExplanation && activeExplanation !== 'threats' && <p className="move-feedback-explanation">{explanation || t('explanationUnavailable')}</p>}
            {isCurrentFeedback && preferences.explanation_mode !== 'text' && <VisualExplanation coaching={feedback} onVisual={onVisual} onPreview={onPreview} />}
            {isCurrentFeedback && moveBase && <ConsequenceComparison feedback={feedback} base={moveBase} preferences={preferences} orientation={orientation} onPreview={onPreview} />}
            {isCurrentFeedback && moveBase && <div className="visual-explanation-actions">
              {feedback.played && <button className="text-button" onClick={() => onPreview(feedback.played!, moveBase, index)}>{t('watchConsequence')}</button>}
              {feedback.best && !preferences.hide_best_moves && <button className="text-button" onClick={() => onPreview(feedback.best!, moveBase, index)}>{t('watchAlternative')}</button>}
              <button className="text-button" onClick={() => onRetry(moveBase, index)}>{t('retryPosition')}</button>
            </div>}
            {isCurrentFeedback && preferences.feedback === 'detailed' && feedback.takeaway && (
              <p className="takeaway">{feedback.takeaway}</p>
            )}
          </div>
        );
      })}
    </>
  );
}
interface Props {
  orientation: Color;
  onPickSquare: (answer: (square: string) => void) => void;
  onCommitCandidate?: (uci: string, base: string, revision: number) => Promise<void>;
  onVisual: (insight: VisualInsight) => void;
  onRetry: (baseFen: string, rootPly?: number) => void;
  positionPending: boolean;
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
  orientation,
  onCommitCandidate,
  onPickSquare,
  onVisual,
  onRetry,
  positionPending,
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
  const t = useT();
  const speechSettings = useQuery({
    queryKey: ['speech-settings'],
    queryFn: () => api<SpeechSettings>('/settings/speech'),
    staleTime: 30000,
    retry: false,
  });
  const [tab, setTab] = useState<'coach' | 'moves' | 'review'>(reviewMode ? 'review' : 'coach');
  const { messages, question, setQuestion, busy, analyzing, showCandidates, hintLevel, hint, hintMove, hintVisual, calculating, setCalculating, error, setError, scroll, compare, requestHint, send, cancelAnalysis, teachingMode, setTeachingMode, state } = useCoachSession({ fen, game, preferences, exploring, reviewMode, tab, positionPending, onAnalysis });
  const feedbackPly = game?.moves.slice(0, ply).map((move) => !!move.feedback).lastIndexOf(true) ?? -1;
  const feedbackMove = game?.moves[feedbackPly];
  const latest = feedbackMove?.feedback;
  useEffect(() => {
    const hintGuide = hintVisual?.insights?.find((item) => item.id === 'hint-guide' && item.fen === fen);
    if (hintGuide) { onVisual(hintGuide); return; }
    if (exploring || preferences.visual_arrows === 'on_request' || preferences.explanation_mode === 'text' || preferences.coaching_mode === 'independent') return;
    const currentMessage = messages.at(-1);
    const feedbackInsights = preferences.hide_best_moves && (latest?.actor === 'opponent' || feedbackMove?.actor === 'computer') ? undefined : latest?.insights;
    const insights = hintVisual?.insights || (currentMessage?.role === 'assistant' && currentMessage.fen === fen ? currentMessage.insights : undefined) || feedbackInsights;
    const insight = insights?.find((item) => item.fen === fen);
    if (insight) onVisual(insight);
  }, [fen, game?.revision, latest, messages, hintVisual, exploring, preferences.visual_arrows, preferences.explanation_mode, preferences.coaching_mode, preferences.hide_best_moves]);
  const cls = latest?.classification?.toLowerCase();
  const feedbackVisible =
    !positionPending && preferences.feedback !== 'none' &&
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
            orientation={orientation}
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
            onRetry={onRetry}
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
              <div className="teaching-controls"><label htmlFor="teaching-mode">{t('teachingStyle')}</label><select id="teaching-mode" value={teachingMode} onChange={(event) => setTeachingMode(event.target.value as typeof teachingMode)}><option value="guided">{t('guidedQuestions')}</option><option value="direct">{t('directExplanation')}</option></select>{state && <small role="status">{t('discoveredFacts')}: {state.discovered_ids.length}</small>}</div>
              {teachingMode === 'guided' && state && <SocraticProgress state={state} />}
              {teachingMode === 'guided' && <button className="text-button" disabled={busy || positionPending} onClick={() => onPickSquare((square) => void send(square))}>{t('answerOnBoard')}</button>}
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
              <div className="coach-actions">
                <button className="text-button" disabled={positionPending || analyzing} onClick={() => void compare('deep')}>{t('deepAnalysis')}</button>
                <button className="text-button" aria-expanded={calculating} onClick={() => setCalculating(!calculating)}>{t('calculateFirst')}</button>
              </div>
              {calculating && <Suspense fallback={<Spinner label={t('thinking')} />}><CalculationPractice orientation={orientation} key={fen} fen={fen} preferences={preferences} onPreview={onPreview} revision={game?.revision || 0} hintLevel={hintLevel} onCommitCandidate={onCommitCandidate} /></Suspense>}
              {!hint && !showCandidates && <p className="hint-caption">{t('hintsFirst')}</p>}
              {analyzing && <div className="coach-actions"><Spinner label={t('thinking')} /><button className="text-button" onClick={cancelAnalysis}>{t('cancelAnalysis')}</button></div>}
              {hint && <HintCard hint={hint} hintLevel={hintLevel} hintMove={hintMove} hintVisual={hintVisual} preferences={preferences} highlightedMove={highlightedMove} onHoverMove={onHoverMove} onToggleMove={onToggleMove} onVisual={onVisual} onPreview={onPreview} />}
              {showCandidates && analysis?.fen === fen && <CandidateList orientation={orientation} analysis={analysis} fen={fen} preferences={preferences} highlightedMove={highlightedMove} onHoverMove={onHoverMove} onToggleMove={onToggleMove} onPreview={onPreview} onVisual={onVisual} />}
              <MoveFeedbackHistory game={game} preferences={preferences} exploring={exploring} feedbackPly={feedbackPly} currentFen={fen} orientation={orientation} onVisual={onVisual} onPreview={onPreview} onRetry={onRetry} />
              <CoachMessages messages={messages} busy={busy || positionPending} fen={fen} preferences={preferences} onVisual={onVisual} onPreview={onPreview} onResolve={(uci) => void send(preferences.coach_language === 'da' ? `Hvad hvis jeg spiller ${uci}?` : `What if I play ${uci}?`)} />
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
                disabled={positionPending}
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
                disabled={positionPending || !question.trim() || busy}
              >
                <Send size={19} />
              </button>
            </form>
            <VoiceControls
              question={question}
              setQuestion={setQuestion}
              onSubmit={(value) => void send(value)}
              disabled={positionPending || busy}
              latestAssistantText={[...messages].reverse().find((message) => message.role === 'assistant')?.content}
              language={preferences.coach_language}
              sttMode={speechSettings.data?.stt_mode || 'browser'}
              ttsMode={speechSettings.data?.tts_mode || 'browser'}
              onServerTranscribe={transcribeAudio}
              onServerSpeak={(text) => synthesizeSpeech(text, preferences.coach_language)}
            />
            <div className="coach-actions coach-primary-actions">
              <button className="outline-button" onClick={requestHint} disabled={positionPending || analyzing || busy || hintLevel >= 2}>
                <Lightbulb size={20} />
                {hintLevel ? t('nextHint') : t('hint')}
                {hintLevel > 0 && <small>{hintLevel}/2</small>}
              </button>
              <button className="outline-button" onClick={() => void compare()} disabled={positionPending || analyzing}>
                <ChartNoAxesColumnIncreasing size={20} />
                {t('compare')}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
