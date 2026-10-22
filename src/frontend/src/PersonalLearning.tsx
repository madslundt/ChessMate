import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { ErrorNotice, Spinner } from './components';
import { useT, type TranslationKey } from './i18n';
import type { Preferences } from './types';
import { Link } from './navigation';
import { trainingFocusLabel } from './RealisticTraining';
import { positionPath } from './diaryCalendar';
interface LearningProfile {
  adaptive_difficulty: number;
  difficulty_reason: string;
  sample_games: number;
  independent_assessed: number;
  assistance_counts: Record<string, number>;
  concepts: {
    topic: string;
    status: string;
    observations: number;
    games: number;
    independent: number;
    independent_success_rate: number | null;
    confidence: number | string;
    evidence: { game_id: string; ply: number; fen: string; san?: string }[];
  }[];
  recommendations: { topic: string; reason: string }[];
}
const statuses: Record<string, [string, string]> = {
  emerging_weakness: ['Emerging weakness', 'Mulig svaghed'],
  recurring_weakness: ['Recurring weakness', 'Tilbagevendende svaghed'],
  improving: ['Improving', 'I fremgang'],
  stable: ['Stable', 'Stabil'],
  declining: ['Needs renewed attention', 'Kræver fornyet opmærksomhed'],
  strength: ['Consistently demonstrated strength', 'Stabilt demonstreret styrke'],
  consistently_demonstrated_strength: ['Consistently demonstrated strength', 'Stabilt demonstreret styrke'],
  insufficient_evidence: ['Building evidence', 'Indsamler observationer'],
};
export function PersonalLearning({ preferences }: { preferences: Preferences }) {
  const t = useT(),
    da = preferences.language === 'da';
  const profile = useQuery({
    queryKey: ['learning-profile'],
    queryFn: ({ signal }) => api<LearningProfile>('/learning/profile', undefined, undefined, signal),
  });
  return (
    <section className="panel personal-learning">
      <h2>{t('personalLearning')}</h2>
      <ErrorNotice error={profile.error} />
      {profile.isPending ? (
        <Spinner />
      ) : profile.data ? (
        <>
          <p>
            <strong>
              {t('adaptiveDifficulty')}: {profile.data.adaptive_difficulty}/5
            </strong>
          </p>
          <p>{profile.data.difficulty_reason}</p>
          <small className="muted">
            {profile.data.sample_games} {da ? 'partier' : 'games'} · {profile.data.independent_assessed}{' '}
            {t('independentDecisions').toLowerCase()}
          </small>
          <p className="muted">{t('adaptiveDifficultyHelp')}</p>
          {!!profile.data.concepts?.length && (
            <div className="learning-concepts">
              {profile.data.concepts.map((concept) => (
                <article key={concept.topic} className="learning-concept">
                  <strong>{t(concept.topic as TranslationKey) || trainingFocusLabel(concept.topic, preferences.language)}</strong>
                  <span>{statuses[concept.status]?.[da ? 1 : 0] || concept.status.replaceAll('_', ' ')}</span>
                  <small>
                    {concept.observations} {da ? 'observationer fra' : 'observations across'} {concept.games}{' '}
                    {da ? 'partier' : 'games'} · {concept.independent} {da ? 'selvstændige' : 'independent'}
                  </small>
                  <small>{da ? 'Evidensgrundlag' : 'Evidence confidence'}: {concept.confidence === 'moderate' ? (da ? 'moderat' : 'moderate') : (da ? 'begrænset' : 'limited')}</small>
                  {concept.evidence?.slice(0, 2).map((evidence) => (
                    <Link
                      className="text-button"
                      key={`${evidence.game_id}-${evidence.ply}`}
                      href={positionPath(evidence.game_id, evidence.ply - 1)}
                    >
                      {evidence.san || t('review')}
                    </Link>
                  ))}
                </article>
              ))}
            </div>
          )}
          <Link className="text-button" href="/diary">
            {t('diary')} →
          </Link>
        </>
      ) : null}
    </section>
  );
}
