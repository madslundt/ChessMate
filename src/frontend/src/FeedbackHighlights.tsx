import { Chess } from 'chess.js';
import { useContext, useEffect, useId, type ReactNode } from 'react';
import { useT } from './i18n';
import { BoardVisualPreviewContext } from './useBoardVisuals';
import type { Feedback, VisualInsight } from './types';
import './styles/feedback-highlights.css';

export function VisualHighlight({ insight, activeVisual, onVisual, children, className = '' }: {
  insight: VisualInsight;
  activeVisual?: VisualInsight | null;
  onVisual: (insight: VisualInsight) => void;
  children: ReactNode;
  className?: string;
}) {
  const t = useT();
  const preview = useContext(BoardVisualPreviewContext);
  const id = useId();
  useEffect(() => () => {
    preview(null, `${id}-pointer`);
    preview(null, `${id}-focus`);
  }, [preview, id]);
  return <button type="button" className={`feedback-highlight-label ${className}`.trim()}
    title={t('clickToHighlight')} aria-pressed={activeVisual?.id === insight.id && activeVisual.fen === insight.fen}
    onPointerEnter={(event) => { if (event.pointerType !== 'touch') preview(insight, `${id}-pointer`); }}
    onPointerLeave={() => preview(null, `${id}-pointer`)} onPointerCancel={() => preview(null, `${id}-pointer`)}
    onFocus={() => preview(insight, `${id}-focus`)} onBlur={() => preview(null, `${id}-focus`)}
    onClick={() => onVisual(insight)}>{children}</button>;
}

export function feedbackImprovement(feedback: Feedback, beforeFen: string, playedUci: string) {
  if (typeof feedback.fen === 'string' && feedback.fen !== beforeFen) return null;
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
  return <div className="feedback-highlights">
    {threats.length > 0 && <div className="feedback-threat-labels">
      <span>{t('threatsLabel')}</span>
      {threats.map((threat) => {
        const insight = { ...threat, id: `feedback-threat-${threat.id}` };
        return <VisualHighlight key={`${threat.id}-${threat.fen}`} insight={insight} activeVisual={activeVisual} onVisual={onVisual}>{threat.label || threat.text}</VisualHighlight>;
      })}
    </div>}
    {better && improvement && <p className="feedback-improvement">{t('betterMoveIs')} <VisualHighlight insight={improvement} activeVisual={activeVisual} onVisual={onVisual}>{better.san}</VisualHighlight>.</p>}
  </div>;
}
