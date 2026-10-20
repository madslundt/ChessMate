import { useState, type FormEvent } from 'react';
import { api } from './api';
import { ErrorNotice, Spinner } from './components';

export function AccountSecurity({ language }: { language: 'en' | 'da' }) {
  const da = language === 'da';
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  async function change(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmation) { setError(new Error(da ? 'Adgangskoderne er ikke ens.' : 'Passwords do not match.')); return; }
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api('/profiles/password', { current_password: current, password }, 'PATCH');
      setCurrent(''); setPassword(''); setConfirmation(''); setSaved(true);
    } catch (failure) { setError(failure); }
    finally { setBusy(false); }
  }
  return <section className="panel" style={{ padding: 24, marginBottom: 20 }}>
    <h2>{da ? 'Kontosikkerhed' : 'Account security'}</h2>
    <p>{da ? 'Ændring af adgangskode logger dine andre enheder ud.' : 'Changing your password signs out your other devices.'}</p>
    <form className="profile-form" onSubmit={(event) => void change(event)}>
      <label htmlFor="current-password">{da ? 'Nuværende adgangskode' : 'Current password'}</label>
      <input id="current-password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required maxLength={256} />
      <label htmlFor="new-password">{da ? 'Ny adgangskode' : 'New password'}</label>
      <input id="new-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} maxLength={256} />
      <label htmlFor="confirm-password">{da ? 'Gentag adgangskode' : 'Repeat password'}</label>
      <input id="confirm-password" type="password" autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required minLength={12} maxLength={256} />
      <button className="outline-button" disabled={busy}>{busy ? <Spinner /> : da ? 'Skift adgangskode' : 'Change password'}</button>
      {saved && <p role="status">{da ? 'Adgangskoden er ændret.' : 'Password changed.'}</p>}
      <ErrorNotice error={error} />
    </form>
  </section>;
}
