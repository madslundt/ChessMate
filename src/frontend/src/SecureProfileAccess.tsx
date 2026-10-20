import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { ErrorNotice, Spinner } from './components';
import type { User } from './types';

/** Passwords stay in this form; the backend issues an HttpOnly session cookie. */
export function SecureProfileAccess({ onAuthenticated }: { onAuthenticated: (profile: User) => void }) {
  const da = document.documentElement.lang === 'da';
  const access = useQuery({ queryKey: ['profile-access'], queryFn: () => api<{ registration_allowed: boolean }>('/profiles/access'), retry: false });
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [register, setRegister] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const user = await api<User>(register ? '/profiles' : '/profiles/session', { name, password });
      setPassword('');
      onAuthenticated(user);
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  return <div className="profile-page"><section className="profile-panel">
    <span className="auth-knight">♞</span>
    <h1>{register ? (da ? 'Opret konto' : 'Create account') : (da ? 'Log ind' : 'Sign in')}</h1>
    <p>{da ? 'Din konto beskytter dine partier, træning og modelindstillinger.' : 'Your account protects your games, training, and model settings.'}</p>
    <form className="profile-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="account-name">{da ? 'Profilnavn' : 'Profile name'}</label>
      <input id="account-name" autoComplete="username" value={name} onChange={(event) => setName(event.target.value)} required maxLength={40} />
      <label htmlFor="account-password">{da ? 'Adgangskode' : 'Password'}</label>
      <input id="account-password" type="password" autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={register ? 12 : 1} maxLength={256} />
      <button className="primary-button" disabled={pending}>{pending ? <Spinner /> : register ? (da ? 'Opret konto' : 'Create account') : (da ? 'Log ind' : 'Sign in')}</button>
      {access.data?.registration_allowed && <button type="button" className="text-button" onClick={() => { setRegister(!register); setError(null); }}>{register ? (da ? 'Log ind i stedet' : 'Sign in instead') : (da ? 'Opret en konto' : 'Create an account')}</button>}
      <ErrorNotice error={error || access.error} />
    </form>
    <p className="muted">{da ? 'Kontakt installationens ejer, hvis du har glemt adgangskoden.' : 'Contact the installation owner if you have forgotten your password.'}</p>
  </section></div>;
}
