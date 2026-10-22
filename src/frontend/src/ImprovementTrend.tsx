import { ArrowRight, TrendingUp } from 'lucide-react';
import { Link } from './navigation';
import { useContext } from 'react';
import { LocaleContext } from './i18n';

export type GamePerformance = {
  game_id: string;
  date: string;
  assessed_moves: number;
  sound_moves: number;
  errors: number;
  sound_rate: number;
};

function average(items: GamePerformance[]) {
  const moves = items.reduce((sum, item) => sum + item.assessed_moves, 0);
  return moves ? items.reduce((sum, item) => sum + item.sound_moves, 0) / moves : null;
}

export function ImprovementTrend({ games }: { games: GamePerformance[] }) {
  const da = useContext(LocaleContext) === 'da';
  const recent = games.slice(-5);
  const previous = games.slice(-10, -5);
  const recentRate = average(recent);
  const previousRate = average(previous);
  const observedMoves = (items: GamePerformance[]) => items.reduce((sum, item) => sum + item.assessed_moves, 0);
  const comparable = recent.filter((item) => item.assessed_moves > 0).length >= 3
    && previous.filter((item) => item.assessed_moves > 0).length >= 3
    && observedMoves(recent) >= 20 && observedMoves(previous) >= 20;
  const delta = comparable && recentRate !== null && previousRate !== null ? Math.round((recentRate - previousRate) * 100) : null;
  if (!games.length) {
    return (
      <section className="panel improvement-trend">
        <h2><TrendingUp size={20} /> {da ? 'Mål din fremgang' : 'Improvement check'}</h2>
        <p className="muted">{da ? 'Spil og analysér et computerparti for at starte en udvikling i trækkvalitet. Importerede analysepartier tæller ikke med.' : 'Play and review a computer game to start a move-quality trend. Imported analysis games do not count toward this comparison.'}</p>
      </section>
    );
  }
  return (
    <section className="panel improvement-trend">
      <div className="improvement-heading">
        <div>
          <h2><TrendingUp size={20} /> {da ? 'Udvikling i trækkvalitet' : 'Move-quality trend'}</h2>
          <p className="muted">{da ? 'Selvstændige motorvurderede beslutninger i komplette partier. Beslutninger med hjælp, ukendt historik og positionsøvelser tæller ikke med.' : 'Independent engine-assessed decisions in complete games. Assisted decisions, unknown history and position drills are excluded.'}</p>
        </div>
        {recentRate !== null && <strong className="improvement-rate">{Math.round(recentRate * 100)}%</strong>}
      </div>
      <p className="muted">{observedMoves(recent)} {da ? 'selvstændige vurderede beslutninger fra' : 'independent assessed decisions across'} {recent.length} {da ? 'seneste partier' : 'recent games'}</p>
      {delta === null && <p className="muted">{da ? 'En sammenligning kræver mindst tre partier og tyve selvstændige vurderede beslutninger i hver periode.' : 'A comparison needs at least three games and twenty independent assessed decisions in each period.'}</p>}
      {delta !== null && (
        <p className="improvement-comparison">
          {da ? (delta > 0 ? 'Op' : delta < 0 ? 'Ned' : 'Uændret') : (delta > 0 ? 'Up' : delta < 0 ? 'Down' : 'Unchanged')} {Math.abs(delta)} {da ? 'procentpoint fra de foregående' : 'percentage points from the previous'} {previous.length} {da ? 'vurderede partier' : 'assessed games'}
          <small> · {recent.length} {da ? 'seneste partier' : 'recent games'}</small>
        </p>
      )}
      <div className="improvement-bars" role="img" aria-label={da ? 'Motorens vurdering af gode selvstændige træk i seneste partier' : 'Engine-assessed sound independent move rate for recent games'}>
        {recent.map((game) => (
          <Link key={game.game_id} href={`/analyze/${encodeURIComponent(game.game_id)}`} title={`${game.date}: ${game.sound_moves}/${game.assessed_moves} ${da ? 'gode træk' : 'sound moves'}`}>
            <span style={{ height: `${Math.max(5, Math.round(game.sound_rate * 72))}px` }} />
            <small>{game.date.slice(5)}</small>
          </Link>
        ))}
      </div>
      <Link className="text-button improvement-review-link" href={`/analyze/${encodeURIComponent(recent.at(-1)!.game_id)}`}>
        {da ? 'Analysér seneste parti' : 'Review latest game'} <ArrowRight size={15} />
      </Link>
    </section>
  );
}
