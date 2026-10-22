import { useState } from 'react';
import { Play } from 'lucide-react';
import { api } from './api';
import { ErrorNotice, Field, Spinner } from './components';
import { useT } from './i18n';
import { gamePath, navigate } from './navigation';
import type { Game, Preferences } from './types';
const topics = [
  'personalized',
  'mixed',
  'forks',
  'pins',
  'skewers',
  'defense',
  'exchanges',
  'sacrifices',
  'positional',
  'development',
  'pawn_structure',
  'middlegame',
  'endgame',
] as const;
const names: Record<string, [string, string]> = {
  personalized: ['Personalized', 'Personlig'],
  mixed: ['Mixed', 'Blandet'],
  forks: ['Forks', 'Gafler'],
  pins: ['Pins', 'Bindinger'],
  skewers: ['Skewers', 'Spidninger'],
  defense: ['Defensive awareness', 'Forsvarsforståelse'],
  exchanges: ['Exchanges', 'Afbytninger'],
  sacrifices: ['Sacrifices', 'Ofre'],
  positional: ['Positional play', 'Positionsspil'],
  development: ['Piece development', 'Brikudvikling'],
  pawn_structure: ['Pawn structure', 'Bondestruktur'],
  middlegame: ['Middlegame planning', 'Midtspilsplaner'],
  endgame: ['Endgames', 'Slutspil'],
  endgames: ['Endgames', 'Slutspil'],
  safety: ['Piece safety', 'Briksikkerhed'],
  plans: ['Positional plans', 'Positionelle planer'],
  forcing_moves: ['Checks, captures and threats', 'Skakker, slag og trusler'],
  opening: ['Opening understanding', 'Åbningsforståelse'],
};
export function trainingFocusLabel(topic: string, language: 'en' | 'da') { return names[topic]?.[language === 'da' ? 1 : 0] || topic.replaceAll('_', ' '); }
export function RealisticTraining({ preferences }: { preferences: Preferences }) {
  const t = useT(),
    [focus, setFocus] = useState(() => { const requested = typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('focus'); return requested && topics.some((topic) => topic === requested) ? requested : 'personalized'; }),
    [blind, setBlind] = useState(true),
    [minutes, setMinutes] = useState(10),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const game = await api<Game>('/training/games', {
        focus,
        blind,
        minutes,
      });
      navigate(gamePath(game));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel realistic-training">
      <h2>{t('realisticTraining')}</h2>
      <p className="muted">{t('realisticTrainingHelp')}</p>
      <form
        className="realistic-controls"
        onSubmit={(event) => {
          event.preventDefault();
          void start();
        }}
      >
        <Field label={t('trainingFocus')}>
          <select value={focus} onChange={(event) => setFocus(event.target.value)}>
            {topics.map((topic) => (
              <option key={topic} value={topic}>
                {trainingFocusLabel(topic, preferences.language)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('mode')}>
          <select value={blind ? 'blind' : 'focused'} onChange={(event) => setBlind(event.target.value === 'blind')}>
            <option value="blind">{t('blindTraining')}</option>
            <option value="focused">{t('focusedTraining')}</option>
          </select>
        </Field>
        <Field label={preferences.language === 'da' ? 'Minutter' : 'Minutes'}>
          <input
            type="number"
            min={1}
            max={60}
            required
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
        </Field>
        <button className="primary-button" disabled={busy}>
          {busy ? <Spinner /> : <Play size={17} />}
          {t('startTrainingGame')}
        </button>
      </form>
      <ErrorNotice error={error} />
    </section>
  );
}
