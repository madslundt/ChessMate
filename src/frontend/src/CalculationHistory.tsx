import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { Board } from './Board';
import { VariationPlayer } from './VariationPlayer';
import { legalVariation, replayVariation } from './exploration';
import { ErrorNotice } from './components';
import type { Preferences } from './types';

interface CalculationEntry {
  id: string;
  fen: string;
  created_at: string;
  moves: string[];
  correct: boolean | null;
  first_inaccuracy_ply: number | null;
  independent: boolean;
  hint_level: number;
  assessment_agrees: boolean | null;
  expected_evaluation: 'winning' | 'balanced' | 'losing' | null;
  final_evaluation: 'winning' | 'balanced' | 'losing' | null;
  steps: {
    ply: number;
    fen: string;
    explanation: string;
    classification: string;
    evidence: { best?: { pv_uci?: string[]; uci?: string } };
  }[];
}

export function CalculationHistory({ preferences }: { preferences: Preferences }) {
  const label = (en: string, da: string) => (preferences.language === 'da' ? da : en);
  const history = useQuery({
    queryKey: ['calculation-history'],
    queryFn: () => api<CalculationEntry[]>('/calculation/attempts'),
  });
  const [selected, setSelected] = useState<CalculationEntry | null>(null);
  const [alternative, setAlternative] = useState<{ base: string; moves: string[] } | null>(null);
  const [cursor, setCursor] = useState(0),
    [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(preferences.variation_speed_ms || 1000);
  const base = alternative?.base || selected?.fen;
  const moves = alternative?.moves || selected?.moves || [];
  useEffect(() => {
    if (!playing) return;
    if (cursor >= moves.length) {
      setPlaying(false);
      if (preferences.return_after_playback) setCursor(0);
      return;
    }
    const timer = window.setTimeout(() => setCursor(cursor + 1), speed);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, moves.length, speed, preferences.return_after_playback]);
  if (!history.data?.length && !history.error) return null;
  const current = selected?.steps[Math.max(0, cursor - 1)];
  const comparison = current?.evidence.best;
  return (
    <section className="panel topic-panel">
      <h2>{label('Saved calculations', 'Gemte beregninger')}</h2>
      <ErrorNotice error={history.error} />
      {history.data?.map((entry) => (
        <button
          className="lesson-row"
          key={entry.id}
          onClick={() => {
            setSelected(entry);
            setAlternative(null);
            setCursor(0);
            setPlaying(false);
          }}
        >
          <span>
            <strong>
              {new Date(entry.created_at).toLocaleString(preferences.language === 'da' ? 'da-DK' : 'en-GB')}
            </strong>
            <small>
              {entry.moves.length} {label('predicted moves', 'forudsagte træk')} ·{' '}
              {entry.first_inaccuracy_ply
                ? `${label('First weaker prediction', 'Første svagere forudsigelse')}: ${entry.first_inaccuracy_ply}`
              : entry.correct === null ? label('Uncertain assessment', 'Usikker vurdering') : entry.assessment_agrees === false ? label('Recheck the final position assessment', 'Kontrollér vurderingen af slutstillingen') : label('No clear prediction error found', 'Ingen klar forudsigelsesfejl fundet')}
            </small>
          </span>
        </button>
      ))}
      {selected && base && (
        <div className="exercise-layout">
          <div>
            <Board
              fen={replayVariation(base, moves.slice(0, cursor)).fen()}
              preferences={preferences}
              orientation={selected.fen.split(' ')[1] === 'w' ? 'white' : 'black'}
              onMove={() => {}}
              disabled
              lastMove={moves[cursor - 1]}
            />
            <VariationPlayer
              base={base}
              moves={moves}
              cursor={cursor}
              onCursor={setCursor}
              playing={playing}
              onPlaying={setPlaying}
              speed={speed}
              onSpeed={setSpeed}
            />
          </div>
          <div>
            <h3>
              {alternative
                ? label('Engine comparison', 'Motorsammenligning')
                : label('Your predicted line', 'Din forudsagte variant')}
            </h3>
            {!alternative && current && <p>{current.explanation}</p>}
              {selected.expected_evaluation && <p>{label('Your final assessment', 'Din vurdering af slutstillingen')}: {label(selected.expected_evaluation, { winning: 'gevinst', balanced: 'balance', losing: 'tab' }[selected.expected_evaluation])}. {label('Engine estimate', 'Motorens estimat')}: {selected.final_evaluation ? label(selected.final_evaluation, { winning: 'gevinst', balanced: 'balance', losing: 'tab' }[selected.final_evaluation]) : label('uncertain', 'usikker')}.</p>}
            {!alternative && current && comparison?.uci && (
              <button
                className="outline-button"
                onClick={() => {
                  const line = legalVariation(current.fen, comparison.pv_uci || [comparison.uci!]);
                  if (line.length) {
                    setAlternative({ base: current.fen, moves: line });
                    setCursor(0);
                    setPlaying(false);
                  }
                }}
              >
                {label('Compare the verified alternative', 'Sammenlign det kontrollerede alternativ')}
              </button>
            )}
            {alternative && (
              <button
                className="outline-button"
                onClick={() => {
                  setAlternative(null);
                  setCursor(0);
                  setPlaying(false);
                }}
              >
                {label('Return to your calculation', 'Tilbage til din beregning')}
              </button>
            )}
            <button
              className="text-button"
              onClick={() => {
                setSelected(null);
                setPlaying(false);
              }}
            >
              {label('Close replay', 'Luk afspilning')}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
