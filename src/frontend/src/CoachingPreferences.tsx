import { Field, Toggle } from './components';
import type { Preferences } from './types';

/** Persisted coaching controls share the same contract as the game workspace. */
export function CoachingPreferences({
  value,
  onChange,
}: {
  value: Preferences;
  onChange: (changes: Partial<Preferences>) => void;
}) {
  const label = (en: string, da: string) => (value.language === 'da' ? da : en);
  return (
    <>
      <Toggle
        label={label(
          'Use recommended coaching settings for my level',
          'Brug anbefalede trænerindstillinger til mit niveau',
        )}
        checked={value.skill_defaults !== false}
        onChange={(skill_defaults) => onChange({ skill_defaults })}
      />
      <Field label={label('Play pace', 'Spiltempo')}>
        <select
          value={value.play_mode || (value.auto_computer ? 'automatic' : 'coach_first')}
          onChange={(event) => {
            const mode = event.target.value as NonNullable<Preferences['play_mode']>;
            onChange({
              play_mode: mode,
              auto_computer: mode === 'automatic',
            });
          }}
        >
          <option value="automatic">{label('Automatic replies', 'Automatiske svar')}</option>
          <option value="coach_first">
            {label('Coach first: continue when ready', 'Træner først: fortsæt når du er klar')}
          </option>
          <option value="independent">{label('Independent play', 'Selvstændigt spil')}</option>
        </select>
      </Field>
      <Field label={label('Preferred explanation', 'Foretrukken forklaring')}>
        <select
          value={value.explanation_mode || 'both'}
          onChange={(event) =>
            onChange({
              explanation_mode: event.target.value as Preferences['explanation_mode'],
            })
          }
        >
          <option value="both">{label('Text and board', 'Tekst og bræt')}</option>
          <option value="visual">{label('Board first', 'Brættet først')}</option>
          <option value="text">{label('Text first', 'Teksten først')}</option>
        </select>
      </Field>
      <Field label={label('Coaching arrows', 'Træningspile')}>
        <select
          value={value.visual_arrows || 'automatic'}
          onChange={(event) =>
            onChange({
              visual_arrows: event.target.value as Preferences['visual_arrows'],
            })
          }
        >
          <option value="automatic">{label('Show automatically', 'Vis automatisk')}</option>
          <option value="on_request">{label('Show on request', 'Vis efter anmodning')}</option>
        </select>
      </Field>
      <Field
        label={label('Variation speed (milliseconds per move)', 'Varianttempo (millisekunder pr. træk)')}
      >
        <input
          type="number"
          min={400}
          max={3000}
          step={50}
          value={value.variation_speed_ms || 1000}
          onChange={(event) => onChange({ variation_speed_ms: Number(event.target.value) })}
        />
      </Field>
      <Toggle
        label={label('Highlight important pieces', 'Fremhæv vigtige brikker')}
        checked={value.highlight_pieces !== false}
        onChange={(highlight_pieces) => onChange({ highlight_pieces })}
      />
      <Toggle
        label={label('Highlight verified threats', 'Fremhæv kontrollerede trusler')}
        checked={value.highlight_threats !== false}
        onChange={(highlight_threats) => onChange({ highlight_threats })}
      />
      <Toggle
        label={label('Animate suggested variations', 'Animér foreslåede varianter')}
        checked={value.animate_variations !== false}
        onChange={(animate_variations) => onChange({ animate_variations })}
      />
      <Toggle
        label={label(
          'Return to the original position after playback',
          'Vend tilbage til udgangsstillingen efter afspilning',
        )}
        checked={value.return_after_playback !== false}
        onChange={(return_after_playback) => onChange({ return_after_playback })}
      />
      <Field label={label('Deep analysis budget (milliseconds)', 'Budget til dyb analyse (millisekunder)')}>
        <input
          type="number"
          min={5000}
          max={20000}
          step={1000}
          value={value.deep_analysis_time_ms || 5000}
          onChange={(event) => onChange({ deep_analysis_time_ms: Number(event.target.value) })}
        />
      </Field>
    </>
  );
}
