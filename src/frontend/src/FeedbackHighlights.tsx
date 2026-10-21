import { Chess } from 'chess.js';
import { useT } from './i18n';
import type { Feedback, VisualInsight } from './types';
import './styles/feedback-highlights.css';

export function feedbackImprovement(feedback: Feedback, beforeFen: string, playedUci: string) {
  const candidate = feedback.improvement || (feedback.best ? { ...feedback.best, fen: beforeFen } : undefined);
  if (!candidate || candidate.fen !== beforeFen || candidate.uci === playedUci) return null;
  try {
    const move = new Chess(beforeFen).moves({ verbose: true }).find((move) => move.lan === candidate.uci);
    return move ? { uci: move.lan, san: move.san, fen: beforeFen } : null;
  } catch {
    return null;
  }
}

/** Labels show verified evidence on its own position without playing a move. */
export function FeedbackHighlights({ feedback, beforeFen, playedUci, activeVisual, onVisual }: {
  feedback: Feedback;
  beforeFen: string;
  playedUci: string;
  activeVisual?: VisualInsight | null;
  onVisual: (insight: VisualInsight) => void;
}) {
  const t = useT();
  if (!['inaccuracy', 'mistake', 'blunder'].includes(feedback.classification?.toLowerCase() || '')) return null;
  const threats = (feedback.threats || []).filter((item) => item.squares?.length || item.arrows?.length);
  const better = feedbackImprovement(feedback, beforeFen, playedUci);
  const improvement: VisualInsight | null = better ? {
    id: `feedback-improvement-${better.uci}`, fen: better.fen,
    text: `${t('betterMoveIs')} ${better.san}.`,
    squares: [better.uci.slice(0, 2), better.uci.slice(2, 4)],
    arrows: [{ from: better.uci.slice(0, 2), to: better.uci.slice(2, 4), color: '#378466' }],
  } : null;
  const pressed = (item: VisualInsight) => activeVisual?.id === item.id && activeVisual.fen === item.fen;
  return <div className="feedback-highlights">
    {threats.length > 0 && <div className="feedback-threat-labels">
      <span>{t('threatsLabel')}</span>
      {threats.map((threat) => {
        const insight = { ...threat, id: `feedback-threat-${threat.id}` };
        return <button key={`${threat.id}-${threat.fen}`} className="feedback-highlight-label" title={t('clickToHighlight')} aria-pressed={pressed(insight)} onClick={() => onVisual(insight)}>{threat.label || threat.text}</button>;
      })}
    </div>}
    {better && improvement && <p className="feedback-improvement">{t('betterMoveIs')} <button className="feedback-highlight-label" title={t('clickToHighlight')} aria-pressed={pressed(improvement)} onClick={() => onVisual(improvement)}>{better.san}</button>.</p>}
  </div>;
}
