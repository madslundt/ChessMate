import { useContext } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, BookOpen, Check, ChevronRight, Flame, Gamepad2, Lightbulb, Target } from 'lucide-react';
import { api } from './api';
import { ErrorNotice, PageHeading, Spinner } from './components';
import { LocaleContext, useT, type TranslationKey } from './i18n';
import { defaults, type Preferences, type Progress } from './types';
import { CalculationHistory } from './CalculationHistory';
import { learnPath, Link, navigate } from './navigation';
import { StudyPlan } from './StudyPlan';
import { PersonalLearning } from './PersonalLearning';
import { ImprovementTrend } from './ImprovementTrend';

export function ProgressPage({ onLearn, preferences = defaults }: { onLearn: () => void; preferences?: Preferences }) {
  const language = useContext(LocaleContext);
  const label = (en: string, da: string) => (language === 'da' ? da : en);
  const t = useT(),
    progress = useQuery({
      queryKey: ['progress'],
      queryFn: () => api<Progress>('/progress'),
    }),
    p = progress.data;
  async function startPlanSession(kind: string, minutes: number) {
    try {
      const session = await api<{ id: string; exercises: { id: string }[] }>('/training/sessions', { kind, minutes });
      if (session.exercises[0])
        navigate(learnPath(kind === 'mixed' || kind === 'review' ? 'all' : kind, session.exercises[0].id, session.id));
      else onLearn();
    } catch {
      onLearn();
    }
  }
  return (
    <>
      <PageHeading
        title={t('progress')}
        subtitle={
          p?.due_reviews
            ? `${p.due_reviews} ${label('reviews ready to practice', 'repetitioner klar til træning')}`
            : undefined
        }
      />
      <PersonalLearning preferences={preferences} />
      <ErrorNotice error={progress.error} />
      {progress.isPending ? (
        <Spinner />
      ) : (
        p && (
          <>
            <div className="progress-stats">
              {[
                [Gamepad2, 'games', p.games_played],
                [Target, 'attempts', p.attempts],
                [Check, 'accuracy', `${Math.round(p.accuracy * 100)}%`],
                [Lightbulb, 'hintsUsed', p.hints_used],
              ].map(([Icon, key, value]) => {
                const I = Icon as typeof Target;
                return (
                  <div className="stat" key={String(key)}>
                    <I size={21} />
                    <span>{t(key as TranslationKey)}</span>
                    <strong>{String(value)}</strong>
                  </div>
                );
              })}
            </div>
            {!!p.calculation?.attempts && (
              <section className="panel topic-panel">
                <h2>{label('Calculation practice', 'Beregningsøvelser')}</h2>
                <p>
                  {p.calculation.attempts} {label('attempts', 'forsøg')} · {p.calculation.independent_solves}{' '}
                  {label('independent solves', 'selvstændige løsninger')}
                </p>
                <p>
                  {label('Accurate predicted moves', 'Præcise forudsagte træk')}:{' '}
                  {p.calculation.accuracy === null ? '—' : `${Math.round(p.calculation.accuracy * 100)}%`} ·{' '}
                  {label('Opponent response predictions', 'Forudsigelser af modstanderens svar')}:{' '}
                  {p.calculation.response_accuracy === null
                    ? '—'
                    : `${Math.round(p.calculation.response_accuracy * 100)}%`}
                </p>
                {p.calculation.final_assessment_accuracy !== null && (
                  <p>
                    {label(
                      'Final position assessments matching the search',
                      'Vurderinger af slutstillingen, der matcher søgningen',
                    )}
                    : {Math.round(p.calculation.final_assessment_accuracy * 100)}%
                  </p>
                )}
              </section>
            )}
            <CalculationHistory preferences={preferences} />
            {!!p.observed_skills?.length && (
              <section className="panel topic-panel">
                <h2>{label('Observed learning patterns', 'Observerede læringsmønstre')}</h2>
                {p.observed_skills.map((skill) => (
                  <div className="topic-row" key={skill.skill}>
                    <strong>{skill.label}</strong>
                    <p>
                      {skill.correct}/{skill.observations} {label('sound decisions', 'gode beslutninger')} ·{' '}
                      {skill.mistakes} {label('decisions to revisit', 'beslutninger til repetition')}
                    </p>
                    <small>
                      {label('Evidence from', 'Evidens fra')}:{' '}
                      {Object.entries(skill.sources)
                        .map(
                          ([source, count]) =>
                            `${source === 'game' ? label('games', 'partier') : source === 'calculation' ? label('calculation', 'beregning') : label('exercises', 'øvelser')} (${count})`,
                        )
                        .join(' · ')}
                    </small>
                  </div>
                ))}
              </section>
            )}
            {!!p.transfer?.decisions && (
              <section className="panel topic-panel">
                <h2>{label('Applying practice in later games', 'Brug af træning i senere partier')}</h2>
                <p>
                  {p.transfer.sound_decisions}/{p.transfer.decisions}{' '}
                  {label(
                    'later matching decisions were sound in engine analysis.',
                    'senere lignende beslutninger var gode i motoranalysen.',
                  )}
                </p>
                <p>
                  {typeof p.transfer.independent_decisions === 'number' && typeof p.transfer.independent_sound_decisions === 'number'
                    ? `${p.transfer.independent_sound_decisions}/${p.transfer.independent_decisions} ${label('verified independent matching decisions were sound.', 'kontrollerede selvstændige lignende beslutninger var gode.')}`
                    : label('Independent transfer is unknown for records without reliable assistance metadata.', 'Selvstændig overførsel er ukendt for historik uden pålidelige oplysninger om hjælp.')}
                </p>
                <p className="muted">
                  {label(
                    'The total includes assisted and unknown decisions. Only verified independent decisions support independent transfer; repeated familiar positions remain weaker evidence than unfamiliar situations. These matches do not establish that practice caused the result.',
                    'Det samlede antal omfatter beslutninger med hjælp og ukendt hjælpestatus. Kun kontrollerede selvstændige valg underbygger selvstændig overførsel; kendte stillinger er svagere evidens end nye situationer. Sammenfaldene beviser ikke, at træningen var årsagen til resultatet.',
                  )}
                </p>
                {p.transfer.samples
                  .slice(-8)
                  .reverse()
                  .map((sample) => (
                    <Link
                      className="lesson-row"
                      key={`${sample.game_id}-${sample.revision}`}
                      href={`/analyze/${sample.game_id}`}
                    >
                      <span>
                        <strong>
                          {sample.san} ·{' '}
                          {t(sample.classification.toLowerCase() as TranslationKey) || sample.classification}
                        </strong>
                        <small>
                          {sample.match === 'same_position'
                            ? label('Same position revisited after practice', 'Samme stilling genbesøgt efter træning')
                            : label(
                                'Same verified pattern in a later decision',
                                'Samme kontrollerede mønster i en senere beslutning',
                              )}
                        </small>
                      </span>
                      <ArrowRight size={18} />
                    </Link>
                  ))}
              </section>
            )}
            <StudyPlan
              topics={p.topics}
              recommendations={p.recommendations}
              dueReviews={p.due_reviews || 0}
              onStart={(kind, minutes) => void startPlanSession(kind, minutes)}
            />
            <ImprovementTrend games={p.game_performance || []} />
            <div className="progress-layout">
              <section className="panel topic-panel">
                <h2>{t('topics')}</h2>
                {!p.attempts && <p className="muted">{t('noProgress')}</p>}
                {p.topics.map((topic) => (
                  <div className="topic-row" key={topic.topic}>
                    <div>
                      <strong>{t(topic.topic as TranslationKey)}</strong>
                      <span>
                        {topic.attempts} {t('attempts').toLowerCase()}
                        <b>{Math.round(topic.accuracy * 100)}%</b>
                      </span>
                    </div>
                    {typeof topic.mastery === 'number' && (
                      <small>
                        {label('Mastery estimate', 'Estimeret mestring')}: {Math.round(topic.mastery * 100)}% ·{' '}
                        {label('Independent solves', 'Selvstændige løsninger')}:{' '}
                        {Math.round((topic.independent_accuracy || 0) * 100)}% ·{' '}
                        {label('Practice level', 'Øvelsesniveau')} {topic.suggested_difficulty}/5
                        {topic.due ? ` · ${topic.due} ${label('due', 'klar')}` : ''}
                      </small>
                    )}
                    <div className="topic-track">
                      <span
                        style={{
                          width: `${(topic.mastery ?? topic.accuracy) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </section>
              <section className="practice-recommendations">
                <span className="round-icon">
                  <Flame size={23} />
                </span>
                <h2>{t('recommended')}</h2>
                {p.recommendations.map((r, i) => (
                  <button
                    className="recommendation"
                    key={i}
                    onClick={() => (typeof r === 'string' || !r.topic ? onLearn() : navigate(learnPath(r.topic)))}
                  >
                    <BookOpen size={20} />
                    <div>
                      <strong>{typeof r === 'string' ? r : t((r.topic || 'learn') as TranslationKey)}</strong>
                      {typeof r !== 'string' && r.reason && <p>{r.reason}</p>}
                    </div>
                    <ChevronRight size={18} />
                  </button>
                ))}
                <button className="primary-button" onClick={onLearn}>
                  {t('startPractice')}
                  <ArrowRight size={16} />
                </button>
              </section>
            </div>
            {!!p.repeated_mistakes?.length && (
              <section className="panel topic-panel">
                <h2>{label('Ideas to revisit', 'Idéer til repetition')}</h2>
                {p.repeated_mistakes.map((item) => (
                  <Link className="lesson-row" key={item.exercise_id} href={learnPath(item.topic, item.exercise_id)}>
                    <span>
                      <strong>{t(item.topic as TranslationKey)}</strong>
                      <small>
                        {item.failures}{' '}
                        {label(
                          'unsolved attempts. Try again with a fresh plan.',
                          'uløste forsøg. Prøv igen med en ny plan.',
                        )}
                      </small>
                    </span>
                    <ArrowRight size={18} />
                  </Link>
                ))}
              </section>
            )}
            {Array.isArray(p.timeline) && p.timeline.length > 0 && (
              <section className="panel timeline-panel">
                <h2>{t('progress')}</h2>
                <div className="progress-timeline">
                  {(
                    p.timeline as {
                      date: string;
                      attempts: number;
                      correct: number;
                    }[]
                  )
                    .slice(-20)
                    .map((x) => (
                      <div key={x.date} title={`${x.correct}/${x.attempts}`}>
                        <span
                          style={{
                            height: `${Math.max(5, (100 * x.correct) / x.attempts)}px`,
                          }}
                        />
                        <small>{x.date.slice(5)}</small>
                      </div>
                    ))}
                </div>
              </section>
            )}
          </>
        )
      )}
    </>
  );
}
