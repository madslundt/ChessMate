import { ChevronRight } from 'lucide-react';
import { Link } from './navigation';
import { useT, type TranslationKey } from './i18n';
import type { Preferences } from './types';
import { positionPath } from './diaryCalendar';

export interface DiaryStatistics {
  games: number;
  wins: number;
  draws: number;
  losses: number;
  independent: number;
  assisted: number;
  unknown: number;
  independent_sound?: number;
  assisted_sound?: number;
}
export interface DiaryObservation {
  game_id: string;
  ply: number;
  fen: string;
  san?: string;
  classification?: string;
  concepts?: string[];
  topic?: string;
  text?: string;
  assistance?: string;
}
export interface DiaryContent {
  date?: string;
  id?: string;
  start_date?: string;
  end_date?: string;
  status: string;
  summary: string;
  statistics: DiaryStatistics;
  assistance_breakdown?: Record<string, number>;
  source_statistics?: Partial<Record<'game' | 'training' | 'import', DiaryStatistics>>;
  observations: DiaryObservation[];
  recommendations: { topic: string; label?: string; reason?: string }[];
  games?: {
    id: string;
    result: string;
    difficulty: number;
    analysis_status: string;
  }[];
  outdated?: boolean;
  updated_at?: string;
  created_at?: string;
  comparison?: {
    start_date: string;
    end_date: string;
    sufficient_evidence: boolean;
    statistics: DiaryStatistics;
    independent_sound_rate_change: number | null;
    qualification: string;
  };
}
export function DiaryEvidence({ content, preferences }: { content: DiaryContent; preferences: Preferences }) {
  const t = useT(),
    s = content.statistics;
  return (
    <div className="diary-evidence">
      <p className={`diary-status status-${content.status}`}>
        {t(
          content.status === 'complete' || content.status === 'completed' || content.status === 'ready'
            ? 'diaryReady'
            : content.status === 'partial'
              ? 'diaryPartial'
              : content.status === 'failed'
                ? 'diaryFailed'
                : 'diaryPending',
        )}
      </p>
      {s && (
        <>
          <div className="diary-statistics">
            {[
              [t('games'), s.games],
              [t('victory'), s.wins],
              [t('draw'), s.draws],
              [t('defeat'), s.losses],
            ].map(([name, value]) => (
              <div key={name}>
                <strong>{value}</strong>
                <span>{name}</span>
              </div>
            ))}
          </div>
          <p className="diary-assistance">
            {t('independentDecisions')}: {s.independent} · {t('assistedDecisions')}: {s.assisted} ·{' '}
            {t('unknownAssistance')}: {s.unknown}
          </p>
          {!!content.assistance_breakdown?.engine_assisted && (
            <p className="muted diary-assistance-detail">
              {t('engineAnalysisDecisions')}: {content.assistance_breakdown.engine_assisted}.{' '}
              {t('assistanceIncludesEvaluation')}
            </p>
          )}
        </>
      )}
      {content.source_statistics && (
        <section
          className="diary-source-evidence"
          aria-label={preferences.language === 'da' ? 'Læring fordelt på aktivitet' : 'Learning evidence by activity'}
        >
          <h3>{preferences.language === 'da' ? 'Læring fordelt på aktivitet' : 'Learning evidence by activity'}</h3>
          {(['game', 'training', 'import'] as const).map((source) => {
            const evidence = content.source_statistics?.[source];
            if (!evidence || !evidence.games) return null;
            const names = {
              game: ['Complete games', 'Komplette partier'],
              training: ['Position training', 'Positionstræning'],
              import: ['Imported games', 'Importerede partier'],
            };
            return (
              <article key={source} className="diary-source-statistics">
                <strong>{names[source][preferences.language === 'da' ? 1 : 0]}</strong>
                <p>
                  {evidence.games} {t('games').toLowerCase()} · {t('independentDecisions')}: {evidence.independent} ·{' '}
                  {t('assistedDecisions')}: {evidence.assisted} · {t('unknownAssistance')}: {evidence.unknown}
                </p>
              </article>
            );
          })}
          <small className="muted">
            {preferences.language === 'da'
              ? 'Øvelser og importerede partier holdes adskilt fra selvstændig forståelse i komplette partier. Periodesammenligningen bruger kun komplette partier.'
              : 'Training and imports remain separate from independent understanding in complete games. Period comparisons use complete games only.'}
          </small>
        </section>
      )}
      <div className="diary-narrative">
        {content.summary?.split(/\n\n+/).map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
      {content.comparison && (
        <section className="diary-comparison">
          <h3>
            {preferences.language === 'da'
              ? 'Sammenligning med forrige periode'
              : 'Comparison with the preceding period'}
          </h3>
          <p>
            {content.comparison.start_date} — {content.comparison.end_date}
          </p>
          <p>
            {content.comparison.statistics.games} {t('games').toLowerCase()} ·{' '}
            {content.comparison.statistics.independent} {t('independentDecisions').toLowerCase()}
          </p>
          {content.comparison.sufficient_evidence && content.comparison.independent_sound_rate_change !== null ? (
            <p>
              {preferences.language === 'da'
                ? 'Ændring i andelen af rimelige selvstændige valg'
                : 'Change in the share of reasonable independent decisions'}
              : {(content.comparison.independent_sound_rate_change * 100).toFixed(1)}{' '}
              {preferences.language === 'da' ? 'procentpoint' : 'percentage points'}
            </p>
          ) : (
            <p>
              {preferences.language === 'da'
                ? 'Der er endnu ikke nok selvstændige observationer fra flere partier til at sammenligne udviklingen.'
                : 'There are not yet enough independent observations across multiple games to compare progress.'}
            </p>
          )}
          <p className="muted">
            {preferences.language === 'da'
              ? 'Dette er en beskrivende sammenligning. Modstanderstyrke, stillingernes sværhedsgrad og udvælgelse kan variere.'
              : content.comparison.qualification}
          </p>
        </section>
      )}
      {!!content.observations?.length && (
        <section>
          <h3>{t('interestingPositions')}</h3>
          <div className="diary-observations">
            {content.observations.map((item, index) => (
              <Link
                key={`${item.game_id}-${item.ply}-${index}`}
                className="lesson-row"
                href={positionPath(item.game_id, item.ply - 1)}
              >
                <span>
                  <strong>
                    {item.san || t('review')}{' '}
                    {item.classification
                      ? `· ${t(item.classification.toLowerCase() as TranslationKey) || item.classification}`
                      : ''}
                  </strong>
                  <small>{item.text || item.topic || item.concepts?.join(', ')}</small>
                </span>
                <ChevronRight size={17} />
              </Link>
            ))}
          </div>
        </section>
      )}
      {!!content.recommendations?.length && (
        <section>
          <h3>{t('recommendedFocus')}</h3>
          {content.recommendations.map((item) => (
            <Link key={item.topic} className="lesson-row" href={`/learn?focus=${encodeURIComponent(item.topic)}`}>
              <span>{item.label || item.reason || item.topic}</span>
              <ChevronRight size={17} />
            </Link>
          ))}
        </section>
      )}
      {!!content.games?.length && (
        <section>
          <h3>{t('games')}</h3>
          {content.games.map((game, index) => (
            <Link key={game.id} className="lesson-row" href={`/analyze/${encodeURIComponent(game.id)}`}>
              <span>
                {t('match')} {index + 1} · {game.result} · {t('difficulty')} {game.difficulty}/5
              </span>
              <ChevronRight size={17} />
            </Link>
          ))}
        </section>
      )}
      <p className="muted diary-qualification">
        {preferences.language === 'da'
          ? 'Observationer bygger på kontrollerede stillinger. Hjælp og ukendt historik tæller ikke som selvstændig forståelse.'
          : 'Observations use verified positions. Assisted decisions and unknown historical records do not establish independent understanding.'}
      </p>
    </div>
  );
}
