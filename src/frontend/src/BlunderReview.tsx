import { useQuery } from '@tanstack/react-query';
import { Chess } from 'chess.js';
import { api } from './api';
import { ErrorNotice, Spinner } from './components';
import { useT } from './i18n';
import type { Analysis, Candidate, Feedback, Preferences } from './types';

function score(candidate?: Candidate): number | null {
  if (candidate?.mate != null) return (100000 - Math.abs(candidate.mate)) * (candidate.mate > 0 ? 1 : -1);
  return candidate?.cp ?? null;
}
/** Engine scores use the side to move at the decision, for both White and Black. */
export function betterAlternatives(
  beforeFen: string,
  playedUci: string,
  candidates: Candidate[],
  played?: Candidate,
): Candidate[] {
  let legal: Set<string>;
  try {
    legal = new Set(new Chess(beforeFen).moves({ verbose: true }).map((move) => move.lan));
  } catch {
    return [];
  }
  const baseline = score(candidates.find((c) => c.uci === playedUci)) ?? score(played);
  // Without a comparison score, only the engine's first choice can be recommended.
  const ranked = baseline === null ? candidates.slice(0, 1) : candidates;
  const seen = new Set([playedUci]);
  return ranked
    .filter((c) => {
      if (!legal.has(c.uci) || seen.has(c.uci)) return false;
      seen.add(c.uci);
      const value = score(c);
      return value !== null && (baseline === null || value > baseline);
    })
    .slice(0, 3);
}
export function BlunderReview({
  beforeFen,
  uci,
  feedback,
  preferences,
  onPreview,
}: {
  beforeFen: string;
  uci: string;
  feedback: Feedback;
  preferences: Preferences;
  onPreview: (candidate: Candidate) => void;
}) {
  const t = useT();
  const stored = feedback.alternatives?.length ? feedback.alternatives : feedback.best ? [feedback.best] : [];
  const analysis = useQuery({
    queryKey: ['blunder-alternatives', beforeFen, preferences.analysis_time_ms, preferences.analysis_depth],
    queryFn: ({ signal }) =>
      api<Analysis>(
        '/analysis',
        {
          fen: beforeFen,
          candidates: 3,
          time_ms: preferences.analysis_time_ms,
          depth: preferences.analysis_depth,
        },
        undefined,
        signal,
      ),
    enabled: !stored.length,
    retry: false,
    staleTime: 60000,
  });
  const candidates = analysis.data?.fen === beforeFen ? analysis.data.candidates : stored;
  const alternatives = betterAlternatives(beforeFen, uci, candidates, feedback.played);
  const reason = feedback.consequence || feedback.explanation || feedback.text || feedback.assessment;
  const reply = feedback.played?.pv?.slice(1, 4).join(' → ');
  return (
    <section className="blunder-review" aria-label={t('whyBad')}>
      <h4>{t('whyBad')}</h4>
      <p>{reason || t('reasonUnavailable')}</p>
      {reply && (
        <p className="blunder-reply">
          <strong>{t('opponentReply')}:</strong> {reply}
        </p>
      )}
      {feedback.played && <button className="outline-button" onClick={() => onPreview(feedback.played!)}>{t('watchConsequence')}</button>}
      <h4>{t('reviewBetterMoves')}</h4>
      {analysis.isFetching ? (
        <Spinner label={t('thinking')} />
      ) : analysis.isError ? (
        <>
          <ErrorNotice error={analysis.error} />
          <button className="text-button" onClick={() => void analysis.refetch()}>
            {t('retryAnalysis')}
          </button>
        </>
      ) : !alternatives.length ? (
        <>
          <p className="muted">{t('noBetterMoves')}</p>
          <button className="text-button" onClick={() => void analysis.refetch()}>
            {t('retryAnalysis')}
          </button>
        </>
      ) : (
        <ol className="blunder-alternatives">
          {alternatives.map((candidate) => (
            <li key={candidate.uci}>
              <strong>{candidate.san}</strong>
              {(candidate.explanation || candidate.idea) && <p>{candidate.explanation || candidate.idea}</p>}
              <button className="outline-button" onClick={() => onPreview(candidate)}>
                {t('previewMove')} {candidate.san}
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
