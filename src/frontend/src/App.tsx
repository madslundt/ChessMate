import { useEffect, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookOpen,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  Clock3,
  Play,
  Moon,
  Pencil,
  Plus,
  Settings,
  ShieldCheck,
  Sun,
  Trash2,
  Trophy,
  UserRound,
  X,
} from 'lucide-react';
import { api } from './api';
import { defaults, type Game, type Page, type Preferences, type User } from './types';
import { LocaleContext, useT } from './i18n';
import { ErrorNotice, Spinner } from './components';
import { GameWorkspace } from './GameWorkspace';
import { Learn } from './Learn';
import { History, ProgressPage, SettingsPage } from './Pages';

const PROFILE_KEY = 'chessmate.profile';

export function App() {
  const queryClient = useQueryClient(),
    [page, setPage] = useState<Page>('play'),
    [activeGame, setActiveGame] = useState<string | null>(() => localStorage.getItem('chessmate.game')),
    [profileId, setProfileId] = useState<string | null>(() => localStorage.getItem(PROFILE_KEY)),
    [showProfiles, setShowProfiles] = useState(false),
    [preferences, setPreferences] = useState<Preferences>(defaults),
    [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches),
    [themePending, setThemePending] = useState(false),
    [themeError, setThemeError] = useState<unknown>(null);
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: () => api<User[]>('/profiles') });
  const user = profiles.data?.find((profile) => profile.id === profileId) ?? null;
  useEffect(() => {
    if (!profiles.isPending && profileId && !profiles.data?.some((profile) => profile.id === profileId)) {
      setProfileId(null);
      localStorage.removeItem(PROFILE_KEY);
    }
  }, [profiles.data, profiles.isPending, profileId]);
  useEffect(() => {
    if (user?.preferences) setPreferences({ ...defaults, ...user.preferences });
  }, [user]);
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
  function selectProfile(profile: User) {
    if (profileId !== profile.id) {
      localStorage.setItem(PROFILE_KEY, profile.id);
      setProfileId(profile.id);
      queryClient.clear();
      setActiveGame(null);
      localStorage.removeItem('chessmate.game');
      setPage('play');
    }
    setShowProfiles(false);
  }
  async function toggleTheme() {
    const previous = preferences;
    setPreferences({ ...preferences, theme: dark ? 'light' : 'dark' });
    setThemePending(true);
    setThemeError(null);
    try {
      const saved = await api<Preferences>('/settings', { theme: dark ? 'light' : 'dark' }, 'PATCH');
      setPreferences(saved);
      queryClient.setQueryData<User[]>(['profiles'], (items) =>
        items?.map((u) => (u.id === user?.id ? { ...u, preferences: saved } : u)),
      );
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
  const nav = [
    ['play', Play],
    ['learn', BookOpen],
    ['analyze', ChartNoAxesColumnIncreasing],
    ['history', Clock3],
    ['progress', Trophy],
    ['settings', Settings],
  ] as const;
  if (profiles.isPending)
    return (
      <div className="app-loading">
        <span className="brand-mark">♞</span>
        <Spinner label="Chessmate" />
      </div>
    );
  if (profiles.error)
    return (
      <div className="app-loading">
        <ErrorNotice error={profiles.error} />
        <button className="primary-button" onClick={() => void profiles.refetch()}>
          Try again
        </button>
      </div>
    );
  return (
    <LocaleContext.Provider value={preferences.language}>
      {!user ? (
        <ProfileChooser
          profiles={profiles.data ?? []}
          onSelect={selectProfile}
          onChanged={() => void profiles.refetch()}
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
                  <small>{user.name}</small>
                </div>
                <ShieldCheck size={17} />
              </div>
              <button className="text-button profile-switch" onClick={() => setShowProfiles(true)}>
                <UserRound size={15} />
                {preferences.language === 'da' ? 'Skift profil' : 'Switch profile'}
              </button>
            </div>
          </aside>
          <main className="main-content">
            <header className="app-toolbar">
              <button
                className="profile-toolbar"
                onClick={() => setShowProfiles(true)}
                aria-label={preferences.language === 'da' ? 'Skift profil' : 'Switch profile'}
              >
                <UserRound size={15} />
                <span>{user.name}</span>
              </button>
              <ThemeToggle dark={dark} pending={themePending} onToggle={() => void toggleTheme()} />
            </header>
            <ErrorNotice error={themeError} />
            {(page === 'play' || page === 'analyze') && (
              <GameWorkspace
                key={`${page}-${user.id}`}
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
                preferences={preferences}
                onSaved={(p) => {
                  setPreferences(p);
                  ['game', 'progress', 'exercises'].forEach((key) => {
                    void queryClient.invalidateQueries({ queryKey: [key] });
                  });
                  queryClient.setQueryData<User[]>(['profiles'], (items) =>
                    items?.map((u) => (u.id === user.id ? { ...u, preferences: p } : u)),
                  );
                }}
              />
            )}
          </main>
          {showProfiles && (
            <ProfileChooser
              profiles={profiles.data ?? []}
              currentId={user.id}
              onSelect={selectProfile}
              onClose={() => setShowProfiles(false)}
              onChanged={() => void profiles.refetch()}
            />
          )}
        </div>
      )}
    </LocaleContext.Provider>
  );
}

function ProfileChooser({
  profiles,
  currentId,
  onSelect,
  onClose,
  onChanged,
}: {
  profiles: User[];
  currentId?: string;
  onSelect: (profile: User) => void;
  onClose?: () => void;
  onChanged: () => void;
}) {
  const t = useT();
  const [name, setName] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const profile = await api<User>(
        editing ? `/profiles/${editing}` : '/profiles',
        { name: name.trim() },
        editing ? 'PATCH' : 'POST',
      );
      onChanged();
      setName('');
      setEditing(null);
      if (!currentId) onSelect(profile);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }
  async function remove(profile: User) {
    if (!window.confirm(`${t('deleteProfile')} “${profile.name}”? ${t('deleteProfileData')}`)) return;
    setPending(true);
    setError(null);
    try {
      await api<void>(`/profiles/${profile.id}`, undefined, 'DELETE');
      if (profile.id === currentId) {
        localStorage.removeItem(PROFILE_KEY);
        onClose?.();
        window.location.reload();
      } else onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }
  return (
    <div
      className={onClose ? 'profile-overlay' : 'profile-page'}
      role={onClose ? 'dialog' : undefined}
      aria-modal={onClose ? true : undefined}
    >
      <section className="profile-panel">
        {onClose && (
          <button className="profile-close" aria-label={t('close')} onClick={onClose}>
            <X size={18} />
          </button>
        )}
        <span className="auth-knight">♞</span>
        <h1>{currentId ? t('profiles') : t('chooseProfile')}</h1>
        <p>{t('profileDescription')}</p>
        <div className="profile-list">
          {profiles.map((profile) => (
            <div className="profile-row" key={profile.id}>
              <button className="profile-select" onClick={() => onSelect(profile)}>
                <UserRound size={19} />
                <span>{profile.name}</span>
                <ChevronRight size={17} />
              </button>
              <button
                className="icon-button"
                aria-label={`${t('editProfile')} ${profile.name}`}
                onClick={() => {
                  setEditing(profile.id);
                  setName(profile.name);
                  setError(null);
                }}
              >
                <Pencil size={16} />
              </button>
              <button
                className="icon-button danger"
                aria-label={`${t('deleteProfile')} ${profile.name}`}
                disabled={pending}
                onClick={() => void remove(profile)}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {profiles.length === 0 && <p className="empty-profiles">{t('noProfiles')}</p>}
        </div>
        <form className="profile-form" onSubmit={(e) => void save(e)}>
          <label htmlFor="profile-name">{editing ? t('editProfile') : t('newProfile')}</label>
          <div className="profile-create-row">
            <input
              id="profile-name"
              required
              minLength={1}
              maxLength={40}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('profileName')}
            />
            <button className="primary-button" disabled={pending}>
              {pending ? (
                <Spinner />
              ) : (
                <>
                  <Plus size={17} />
                  {editing ? t('saveProfile') : t('createProfile')}
                </>
              )}
            </button>
          </div>
          {editing && (
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setEditing(null);
                setName('');
              }}
            >
              {t('cancel')}
            </button>
          )}
          <ErrorNotice error={error} />
        </form>
      </section>
    </div>
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
