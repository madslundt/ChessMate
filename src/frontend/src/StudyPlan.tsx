import { ArrowRight, CalendarDays } from 'lucide-react';
import type { Topic } from './types';
import { Link } from './navigation';
import { useContext } from 'react';
import { LocaleContext } from './i18n';

type Recommendation = string | { topic?: string; reason?: string };
type PlanDay = { title: string; detail: string; kind: string; topic?: string; minutes: number; link?: string };

function planFor(topics: Topic[], recommendations: Recommendation[], dueReviews: number, da: boolean): PlanDay[] {
  const focus = recommendations
    .map((item) => (typeof item === 'string' ? undefined : item.topic))
    .filter((topic): topic is string => !!topic);
  const first = focus[0] || topics.find((topic) => topic.attempts)?.topic || 'middlegame';
  const second = focus.find((topic) => topic !== first) || topics.find((topic) => topic.topic !== first)?.topic || 'endgame';
  const danishTopics: Record<string, string> = { forks: 'gafler', pins: 'bindinger', skewers: 'spidninger', opening: 'åbning', middlegame: 'midtspil', endgame: 'slutspil' };
  const topicName = (topic: string) => da ? danishTopics[topic] || topic : topic;
  const plan: PlanDay[] = [
    dueReviews > 0
      ? { title: da ? 'Gentag forfaldne stillinger' : 'Review due positions', detail: da ? `${dueReviews} gentagelser er klar.` : `${dueReviews} spaced reviews are ready.`, kind: 'review', minutes: 10 }
      : { title: da ? `Styrk ${topicName(first)}` : `Build ${topicName(first)} skill`, detail: da ? 'Begynd med det vigtigste emne fra din fremgang.' : 'Start with the highest priority topic in your progress.', kind: first, topic: first, minutes: 10 },
    { title: da ? `Øv ${topicName(first)}` : `Practice ${topicName(first)}`, detail: da ? 'Løs uden hints først, og sammenlign derefter din tankegang.' : 'Solve without hints first, then compare your reasoning.', kind: first, topic: first, minutes: 10 },
    { title: da ? 'Spil og notér' : 'Play and annotate', detail: da ? 'Spil et fokuseret parti, og skriv din plan før motorens feedback.' : 'Play a focused game, then write your plan before opening engine feedback.', kind: 'game', minutes: 0, link: '/play' },
    { title: da ? `Studér ${topicName(second)}` : `Study ${topicName(second)}`, detail: da ? 'Udvid din træning med et andet anbefalet emne.' : 'Build range with a second topic from your recommendations.', kind: second, topic: second, minutes: 10 },
    { title: da ? 'Bland og gentag' : 'Mix and revisit', detail: da ? 'Afslut med blandede stillinger, og styrk tidligere idéer.' : 'Finish with varied positions and reinforce earlier ideas.', kind: 'mixed', minutes: 10 },
  ];
  return plan;
}

export function StudyPlan({
  topics,
  recommendations,
  dueReviews,
  onStart,
}: {
  topics: Topic[];
  recommendations: Recommendation[];
  dueReviews: number;
  onStart: (kind: string, minutes: number) => void;
}) {
  const da = useContext(LocaleContext) === 'da';
  const plan = planFor(topics, recommendations, dueReviews, da);
  return (
    <section className="panel study-plan">
      <div className="study-plan-heading">
        <span className="round-icon"><CalendarDays size={21} /></span>
        <div>
          <h2>{da ? 'Din studieplan med fem sessioner' : 'Your five-session study plan'}</h2>
          <p className="muted">{da ? 'En kort rutine baseret på gentagelser og dine aktuelle fokusområder.' : 'A short routine built from due reviews and your current focus areas.'}</p>
        </div>
      </div>
      <ol>
        {plan.map((day, index) => (
          <li key={`${index}-${day.kind}`}>
            <span className="study-plan-day">{index + 1}</span>
            <div className="study-plan-copy">
              <strong>{day.title}</strong>
              <small>{day.detail}</small>
            </div>
            {day.link ? (
              <Link className="outline-button" href={day.link}>{da ? 'Spil et parti' : 'Play a game'} <ArrowRight size={15} /></Link>
            ) : (
              <button className="outline-button" onClick={() => onStart(day.kind, day.minutes)}>
                {da ? 'Start' : 'Start'} <ArrowRight size={15} />
              </button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
