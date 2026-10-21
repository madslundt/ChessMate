import { useT, type TranslationKey } from './i18n';
import type { Color, Game, VisualInsight } from './types';
import { FeedbackHighlights } from './FeedbackHighlights';
import { ChessText } from './ChessText';

const classifications = new Set(['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder', 'forced', 'uncertain']);

export function LastMoveFeedback({ game, ply, onVisual, activeVisual }: { game: Game; ply: number; onVisual?: (insight: VisualInsight) => void; activeVisual?: VisualInsight | null }) {
  const t = useT();
  const initialBlack = game.initial_fen.split(' ')[1] === 'b';
  const firstMove = Number(game.initial_fen.split(' ')[5] || 1);
  const latest: Record<Color, number | undefined> = { white: undefined, black: undefined };
  for (let index = 0; index < Math.min(ply, game.moves.length); index++) {
    const move = game.moves[index];
    const color = move.color || (initialBlack === (index % 2 === 0) ? 'black' : 'white');
    latest[color] = index;
  }
  return (
    <section className="last-move-feedback" aria-label={t('lastMoveFeedback')} aria-live="polite" aria-atomic="true">
      <h3>{t('lastMoveFeedback')}</h3>
      <div className="last-move-feedback-cards">
        {(['white', 'black'] as const).map((color) => {
          const index = latest[color];
          const move = index === undefined ? undefined : game.moves[index];
          const feedback = move?.feedback;
          const beforeFen = move?.before_fen || (index === undefined || index === 0 ? game.initial_fen : game.moves[index - 1].fen);
          const referenceProps = { fen: move?.fen || beforeFen, beforeFen, coaching: feedback || undefined, onVisual, activeVisual };
          const classification = feedback?.classification?.toLowerCase();
          const quality = classification && classifications.has(classification) ? classification : 'unclassified';
          const reason = ['inaccuracy', 'mistake', 'blunder'].includes(quality) ? feedback?.consequence : undefined;
          const number = index === undefined ? null : firstMove + Math.floor((index + (initialBlack ? 1 : 0)) / 2);
          return (
            <article key={color} className={`last-move-feedback-card ${quality}`} aria-label={t(color)}>
              <div className="last-move-feedback-heading">
                <span><span className={`turn-dot ${color}`} aria-hidden="true" /><strong>{t(color)}</strong></span>
                {move && <span className="last-move-feedback-san">{number}{color === 'white' ? '.' : '...'} <ChessText {...referenceProps} text={move.san} /></span>}
              </div>
              {move ? <>
                <strong className="last-move-feedback-quality">{t(quality as TranslationKey)}</strong>
                <p><ChessText {...referenceProps} text={reason || feedback?.text || feedback?.explanation || feedback?.assessment || t('feedbackUnavailable')} /></p>
                {feedback && onVisual && index !== undefined && <FeedbackHighlights feedback={feedback} playedUci={move.uci} beforeFen={move.before_fen || (index === 0 ? game.initial_fen : game.moves[index - 1].fen)} onVisual={onVisual} activeVisual={activeVisual} />}
              </> : <p>{t('noMoves')}</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
