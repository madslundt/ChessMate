import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  Clock3,
  Play,
  LogOut,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
  Trophy,
} from 'lucide-react';
import { api, ApiError } from './api';
import { defaults, type Game, type Page, type Preferences, type User } from './types';
import { LocaleContext, useT } from './i18n';
import { ErrorNotice, Field, Spinner } from './components';
import { GameWorkspace } from './GameWorkspace';
import { Learn } from './Learn';
import { History, ProgressPage, SettingsPage } from './Pages';

export function App() {
  const queryClient = useQueryClient(),
    [page, setPage] = useState<Page>('play'),
    [activeGame, setActiveGame] = useState<string | null>(() => localStorage.getItem('chessmate.game')),
    [preferences, setPreferences] = useState<Preferences>(defaults),
    [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches),
    [themePending, setThemePending] = useState(false),
    [themeError, setThemeError] = useState<unknown>(null);
  const user = useQuery({
    queryKey: ['me'],
    queryFn: () => api<User>('/auth/me'),
    retry: false,
  });
  useEffect(() => {
    if (user.data?.preferences) setPreferences({ ...defaults, ...user.data.preferences });
  }, [user.data]);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystemDark(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  const dark = preferences.theme === 'dark' || (preferences.theme === 'system' && systemDark);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.lang = preferences.language;
  }, [dark, preferences.language]);
  async function toggleTheme() {
    const previous = preferences;
    setPreferences({ ...preferences, theme: dark ? 'light' : 'dark' });
    setThemePending(true);
    setThemeError(null);
    try {
      const saved = await api<Preferences>('/settings', { theme: dark ? 'light' : 'dark' }, 'PATCH');
      setPreferences(saved);
      queryClient.setQueryData<User>(['me'], (u) => (u ? { ...u, preferences: saved } : u));
    } catch (error) {
      setPreferences(previous);
      setThemeError(error);
    } finally {
      setThemePending(false);
    }
  }
  function selectGame(game: Game) {
    setActiveGame(game.id);
    localStorage.setItem('chessmate.game', game.id);
    queryClient.setQueryData(['game', game.id], game);
    setPage(game.mode === 'analysis' ? 'analyze' : 'play');
  }
  async function signOut() {
    await api('/auth/logout', {});
    queryClient.clear();
    setActiveGame(null);
    localStorage.removeItem('chessmate.game');
    void user.refetch();
  }
  const nav = [
    ['play', Play],
    ['learn', BookOpen],
    ['analyze', ChartNoAxesColumnIncreasing],
    ['history', Clock3],
    ['progress', Trophy],
    ['settings', Settings],
  ] as const;
  if (user.isPending)
    return (
      <div className="app-loading">
        <span className="brand-mark">♞</span>
        <Spinner label="Chessmate" />
      </div>
    );
  return (
    <LocaleContext.Provider value={preferences.language}>
      {!user.data ? (
        <Auth
          onUser={(u) => queryClient.setQueryData(['me'], u)}
          error={user.error instanceof ApiError && user.error.status === 401 ? null : user.error}
        />
      ) : (
        <div className="app-shell">
          <aside className="sidebar">
            <a
              className="brand"
              href="#play"
              onClick={(e) => {
                e.preventDefault();
                setPage('play');
              }}
            >
              <span className="brand-mark">♞</span>Chessmate
            </a>
            <nav aria-label={preferences.language === 'da' ? 'Hovednavigation' : 'Main navigation'}>
              {nav.map(([key, Icon]) => (
                <NavItem key={key} name={key} Icon={Icon} active={page === key} onClick={() => setPage(key)} />
              ))}
            </nav>
            <div className="sidebar-bottom">
              <div className="privacy-note">
                <span className="status-dot" />
                <div>
                  <strong>{preferences.language === 'da' ? 'Lokalt og privat' : 'Local & private'}</strong>
                  <small>{user.data.name}</small>
                </div>
                <ShieldCheck size={17} />
              </div>
              <button className="text-button logout" onClick={signOut}>
                <LogOut size={15} />
                {preferences.language === 'da' ? 'Log ud' : 'Sign out'}
              </button>
            </div>
          </aside>
          <main className="main-content">
            <header className="app-toolbar">
              <ThemeToggle dark={dark} pending={themePending} onToggle={() => void toggleTheme()} />
            </header>
            <ErrorNotice error={themeError} />
            {(page === 'play' || page === 'analyze') && (
              <GameWorkspace
                key={page}
                activeGameId={activeGame}
                preferences={preferences}
                selectGame={selectGame}
                analysisMode={page === 'analyze'}
              />
            )}
            {page === 'learn' && <Learn preferences={preferences} />}
            {page === 'history' && <History onResume={selectGame} />}
            {page === 'progress' && <ProgressPage onLearn={() => setPage('learn')} />}
            {page === 'settings' && (
              <SettingsPage
                onLogout={signOut}
                preferences={preferences}
                onSaved={(p) => {
                  setPreferences(p);
                  ['game', 'progress', 'exercises'].forEach((key) => {
                    void queryClient.invalidateQueries({ queryKey: [key] });
                  });
                  queryClient.setQueryData<User>(['me'], (u) => (u ? { ...u, preferences: p } : u));
                }}
              />
            )}
          </main>
        </div>
      )}
    </LocaleContext.Provider>
  );
}
function ThemeToggle({ dark, pending, onToggle }: { dark: boolean; pending: boolean; onToggle: () => void }) {
  const t = useT();
  const label = t(dark ? 'switchLight' : 'switchDark');
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      disabled={pending}
      aria-busy={pending}
      aria-label={label}
      title={label}
    >
      {dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
      <span>{t(dark ? 'lightMode' : 'darkMode')}</span>
    </button>
  );
}
function NavItem({
  name,
  Icon,
  active,
  onClick,
}: {
  name: Page;
  Icon: typeof Play;
  active: boolean;
  onClick: () => void;
}) {
  const t = useT();
  return (
    <button
      aria-label={t(name)}
      className={`nav-item ${active ? 'active' : ''}`}
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
    >
      <Icon size={21} fill={name === 'play' ? 'currentColor' : 'none'} />
      <span>{t(name)}</span>
      {active && <ChevronRight className="nav-chevron" size={14} />}
    </button>
  );
}
function Auth({ onUser, error }: { onUser: (u: User) => void; error: unknown }) {
  const t = useT(),
    [register, setRegister] = useState(true),
    [name, setName] = useState(''),
    [password, setPassword] = useState(''),
    [pending, setPending] = useState(false),
    [failure, setFailure] = useState<unknown>(null);
  return (
    <div className="auth-page">
      <div className="auth-story">
        <a className="brand" href="/">
          {' '}
          <span className="brand-mark">♞</span>Chessmate
        </a>
        <div>
          <div className="auth-board" aria-hidden="true">
            {Array.from({ length: 16 }, (_, i) => (
              <span key={i} className={(i + Math.floor(i / 4)) % 2 ? 'dark-square' : ''}>
                {{ 5: '♞', 10: '♙' }[i]}
              </span>
            ))}
          </div>
        </div>
        <small>
          <ShieldCheck size={16} />
          {t('privateText')}
        </small>
      </div>
      <div className="auth-form-wrap">
        <form
          className="auth-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setFailure(null);
            try {
              onUser(
                await api<User>(`/auth/${register ? 'register' : 'login'}`, {
                  name,
                  password,
                }),
              );
            } catch (e) {
              setFailure(e);
            } finally {
              setPending(false);
            }
          }}
        >
          <span className="auth-knight">♞</span>
          <h2>{t(register ? 'createAccount' : 'signIn')}</h2>
          <Field label={t('username')}>
            <input
              name="username"
              autoComplete="username"
              minLength={2}
              maxLength={40}
              pattern="[a-zA-Z0-9_.-]+"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label={t('password')}>
            <input
              name="password"
              type="password"
              autoComplete={register ? 'new-password' : 'current-password'}
              minLength={8}
              maxLength={128}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <ErrorNotice error={failure || error} />
          <button className="primary-button" disabled={pending}>
            {pending ? (
              <Spinner />
            ) : (
              <>
                {t(register ? 'createAccount' : 'signIn')}
                <ArrowRight size={18} />
              </>
            )}
          </button>
          <div className="auth-switch">
            {t(register ? 'hasAccount' : 'noAccount')}{' '}
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setRegister(!register);
                setFailure(null);
              }}
            >
              {t(register ? 'signIn' : 'createAccount')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
