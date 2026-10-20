import { Chess } from 'chess.js';
import { evaluationText } from './Board';
import { useT } from './i18n';
import type { Candidate } from './types';

export function materialScore(chess: Chess) {
  const score = { w: 0, b: 0 };
  const values = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
  for (const rank of chess.board()) {
    for (const piece of rank) {
      if (piece) score[piece.color] += values[piece.type];
    }
  }
  return score;
}

export function PositionScore({
  chess,
  result,
  evaluation,
  showEvaluation,
}: {
  chess: Chess;
  result?: string;
  evaluation?: Candidate;
  showEvaluation: boolean;
}) {
  const t = useT();
  const material = materialScore(chess);
  const difference = material.w - material.b;
  const outcome =
    result && result !== '*'
      ? result
      : chess.isCheckmate()
        ? chess.turn() === 'w'
          ? '0-1'
          : '1-0'
        : chess.isDraw()
          ? '1/2-1/2'
          : null;
  const cp = evaluation?.white_cp;
  const mate = evaluation?.white_mate;
  const leading = mate != null ? mate : cp;
  return (
    <div className="position-score" role="status" aria-live="polite" aria-atomic="true">
      <div className="material-score" title={t('pieceValues')}>
        <span>{t('material')}</span>
        <div>
          <span>
            <i className="turn-dot white" />
            {t('white')} <b>{material.w}</b>
          </span>
          <span aria-hidden="true">:</span>
          <span>
            <i className="turn-dot black" />
            {t('black')} <b>{material.b}</b>
          </span>
        </div>
      </div>
      <strong className="score-standing">
        {outcome
          ? outcome === '1-0'
            ? `${t('whiteWins')} · 1–0`
            : outcome === '0-1'
              ? `${t('blackWins')} · 0–1`
              : `${t('draw')} · ½–½`
          : difference === 0
            ? t('materialEqual')
            : `${t(difference > 0 ? 'whiteLeadsMaterial' : 'blackLeadsMaterial')} +${Math.abs(difference)}`}
      </strong>
      {showEvaluation && !outcome && (
        <div className="position-evaluation">
          <span>{t('positionEvaluation')}</span>
          <span>
            {leading == null
              ? t('evaluationUnavailable')
              : `${
                  mate != null
                    ? t(mate > 0 ? 'whiteMates' : 'blackMates')
                    : t(Math.abs(cp!) < 30 ? 'balancedPosition' : cp! > 0 ? 'whiteLeads' : 'blackLeads')
                } · ${evaluationText(cp, mate)}`}
          </span>
        </div>
      )}
    </div>
  );
}
