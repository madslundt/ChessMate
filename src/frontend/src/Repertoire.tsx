import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, BookOpen, Plus, Trash2 } from 'lucide-react';
import { api } from './api';
import { ErrorNotice, Field, Modal, Spinner } from './components';
import { useT } from './i18n';
import type { Exercise, Preferences } from './types';
interface Line {
  id: string;
  name: string;
  color: 'white' | 'black';
  initial_fen: string;
  moves: string[];
  san: string[];
  fen: string;
}
export function Repertoire({
  preferences,
  onPractice,
}: {
  preferences: Preferences;
  onPractice: (session: { id: string; exercises: Exercise[] }) => void;
}) {
  const t = useT(),
    client = useQueryClient(),
    [adding, setAdding] = useState(false),
    [name, setName] = useState(''),
    [color, setColor] = useState<'white' | 'black'>('white'),
    [moves, setMoves] = useState(''),
    [error, setError] = useState<unknown>(null),
    [pending, setPending] = useState(false);
  const da = preferences.language === 'da',
    lines = useQuery({
      queryKey: ['repertoire'],
      queryFn: () => api<Line[]>('/repertoire'),
    });
  return (
    <section className="repertoire">
      <div className="section-heading">
        <h2>{da ? 'Dit åbningsrepertoire' : 'Your opening repertoire'}</h2>
        <button className="outline-button" onClick={() => setAdding(true)}>
          <Plus size={16} />
          {da ? 'Tilføj variant' : 'Add a line'}
        </button>
      </div>
      <p className="muted">
        {da
          ? 'Gem lovlige varianter for hvid eller sort, og øv motorverificerede beslutninger.'
          : 'Save legal lines for white or black, then practice engine-verified decisions.'}
      </p>
      <ErrorNotice error={error || lines.error} />
      {lines.data?.map((line) => (
        <div className="repertoire-line" key={line.id}>
          <BookOpen size={20} />
          <div>
            <strong>
              {line.name} · {t(line.color)}
            </strong>
            <code>{line.san.join(' ')}</code>
          </div>
          <button
            className="text-button"
            disabled={pending}
            onClick={async () => {
              setPending(true);
              try {
                const session = await api<{
                  id: string;
                  exercises: Exercise[];
                  message: string;
                }>(`/repertoire/${line.id}/practice`, {});
                if (!session.exercises.length) throw new Error(session.message);
                onPractice(session);
              } catch (e) {
                setError(e);
              } finally {
                setPending(false);
              }
            }}
          >
            {t('startPractice')}
            <ArrowRight size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={da ? 'Fjern variant' : 'Remove line'}
            onClick={async () => {
              try {
                await api(`/repertoire/${line.id}`, undefined, 'DELETE');
                client.invalidateQueries({ queryKey: ['repertoire'] });
              } catch (e) {
                setError(e);
              }
            }}
          >
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      {adding && (
        <Modal title={da ? 'Tilføj åbningsvariant' : 'Add an opening line'} onClose={() => setAdding(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setPending(true);
              try {
                await api('/repertoire', {
                  name,
                  color,
                  moves: moves.trim().split(/\s+/),
                });
                client.invalidateQueries({ queryKey: ['repertoire'] });
                setAdding(false);
                setName('');
                setMoves('');
              } catch (e) {
                setError(e);
              } finally {
                setPending(false);
              }
            }}
          >
            <Field label={da ? 'Navn' : 'Name'}>
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
            </Field>
            <Field label={t('color')}>
              <select value={color} onChange={(e) => setColor(e.target.value as 'white' | 'black')}>
                <option value="white">{t('white')}</option>
                <option value="black">{t('black')}</option>
              </select>
            </Field>
            <Field
              label={da ? 'Træk fra startstillingen (SAN eller UCI)' : 'Moves from the starting position (SAN or UCI)'}
            >
              <textarea
                value={moves}
                onChange={(e) => setMoves(e.target.value)}
                placeholder="e4 e5 Nf3 Nc6 Bc4 Bc5"
                required
                maxLength={2000}
                className="import-area"
              />
            </Field>
            <ErrorNotice error={error} />
            <button type="submit" className="primary-button" disabled={pending}>
              {pending ? <Spinner /> : t('save')}
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
