import { useEffect, useId, useState, type ReactNode } from 'react';
import './styles/active-recall.css';

type RecallNotes = {
  move: string;
  threat: string;
  plan: string;
  revealed: boolean;
};

const emptyNotes: RecallNotes = { move: '', threat: '', plan: '', revealed: false };

function storageKey(gameId: string, ply: number) {
  return `chessmate:active-recall:${encodeURIComponent(gameId)}:${ply}`;
}

function readNotes(key: string): RecallNotes {
  try {
    const saved = window.localStorage.getItem(key);
    if (!saved) return emptyNotes;
    const parsed = JSON.parse(saved) as Partial<RecallNotes>;
    return {
      move: typeof parsed.move === 'string' ? parsed.move : '',
      threat: typeof parsed.threat === 'string' ? parsed.threat : '',
      plan: typeof parsed.plan === 'string' ? parsed.plan : '',
      revealed: parsed.revealed === true,
    };
  } catch {
    return emptyNotes;
  }
}

/**
 * An active-recall checkpoint for a position in a completed game.
 * Notes are kept locally per game and ply so learners can return and revise them.
 */
export function ActiveRecallReview({
  gameId,
  ply,
  san,
  positionFen,
  moveLabel,
  language = 'en',
  engineFeedback,
  onReveal,
}: {
  gameId: string;
  ply: number;
  san?: string;
  positionFen?: string;
  moveLabel?: string;
  language?: 'en' | 'da';
  engineFeedback?: ReactNode;
  onReveal?: () => void;
}) {
  const key = storageKey(gameId, ply);
  const titleId = useId();
  const [stored, setStored] = useState(() => ({ key, notes: readNotes(key) }));
  const notes = stored.key === key ? stored.notes : readNotes(key);
  const da = language === 'da';

  useEffect(() => {
    setStored({ key, notes: readNotes(key) });
  }, [key]);

  useEffect(() => {
    if (stored.key !== key) return;
    try {
      window.localStorage.setItem(key, JSON.stringify(notes));
    } catch {
      // Private browsing or a full storage quota should not prevent review.
    }
  }, [key, notes, stored.key]);

  function update(field: keyof Omit<RecallNotes, 'revealed'>, value: string) {
    setStored((current) => ({ key, notes: { ...(current.key === key ? current.notes : readNotes(key)), [field]: value } }));
  }

  function revealFeedback() {
    setStored({ key, notes: { ...notes, revealed: true } });
    onReveal?.();
  }

  function hideFeedback() {
    setStored({ key, notes: { ...notes, revealed: false } });
  }

  return (
    <section className="active-recall panel" aria-labelledby={titleId} data-position-fen={positionFen}>
      <div className="active-recall-heading">
        <div>
          <span className="active-recall-kicker">{da ? 'Tænk først' : 'Think first'}</span>
          <h3 id={titleId}>{da ? 'Hvad overvejede du' : 'What were you considering'}{moveLabel || san ? ` ${da ? 'ved' : 'at'} ${moveLabel || san}` : ''}?</h3>
          <p className="muted">{da ? 'Skriv din egen vurdering af stillingen, før du sammenligner med motoren.' : 'Write down your own read of the position before comparing it with the engine.'}</p>
        </div>
        <span className="active-recall-ply" aria-label={`Ply ${ply}`}>Ply {ply}</span>
      </div>

      <div className="active-recall-fields">
          <label>
          <span>{da ? 'Dit planlagte træk' : 'Your intended move'}</span>
          <textarea
            rows={2}
            value={notes.move}
            onChange={(event) => update('move', event.target.value)}
            placeholder={da ? 'Hvilket træk ville du spille, og hvorfor?' : 'Which move would you play, and why?'}
          />
        </label>
        <label>
          <span>{da ? 'Modstanderens trussel' : 'Opponent’s threat'}</span>
          <textarea
            rows={2}
            value={notes.threat}
            onChange={(event) => update('threat', event.target.value)}
            placeholder={da ? 'Hvad truer modstanderen?' : 'What is your opponent threatening?'}
          />
        </label>
        <label>
          <span>{da ? 'Din plan' : 'Your plan'}</span>
          <textarea
            rows={2}
            value={notes.plan}
            onChange={(event) => update('plan', event.target.value)}
            placeholder={da ? 'Hvad vil du forsøge at opnå?' : 'What would you try to achieve next?'}
          />
        </label>
      </div>

      <div className="active-recall-footer">
        <span className="active-recall-saved" role="status">{da ? 'Gemt på denne enhed' : 'Saved on this device'}</span>
        {!notes.revealed ? (
          <button
            className="primary-button"
            type="button"
            disabled={!engineFeedback}
            onClick={revealFeedback}
          >
            {da ? 'Vis motorens feedback' : 'Reveal engine feedback'}
          </button>
        ) : (
          <button
            className="text-button"
            type="button"
            onClick={hideFeedback}
          >
            {da ? 'Skjul motorens feedback' : 'Hide engine feedback'}
          </button>
        )}
      </div>

      {notes.revealed && (
        <div className="active-recall-feedback" aria-live="polite" aria-label="Engine feedback">
          <h4>{da ? 'Motorens feedback' : 'Engine feedback'}</h4>
          {engineFeedback ?? <p>{da ? 'Motorens feedback er ikke tilgængelig for denne stilling.' : 'Engine feedback is not available for this position.'}</p>}
        </div>
      )}
    </section>
  );
}
