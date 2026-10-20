import { useSyncExternalStore, type AnchorHTMLAttributes } from 'react';
import type { Page } from './types';

export const categories = ['forks', 'pins', 'skewers', 'opening', 'middlegame', 'endgame'] as const;
const pages: Page[] = ['play', 'learn', 'analyze', 'history', 'progress', 'settings'];
export interface Route {
  page: Page;
  gameId: string | null;
  category: string;
  exerciseId: string | null;
  sessionId: string | null;
  found: boolean;
}

export function parseRoute(path: string, search = ''): Route {
  const route: Route = {
    page: 'play',
    gameId: null,
    category: 'all',
    exerciseId: null,
    sessionId: null,
    found: true,
  };
  let parts: string[];
  try {
    parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  } catch {
    return { ...route, found: false };
  }
  if (!parts.length) return route;
  if (!pages.includes(parts[0] as Page)) return { ...route, found: false };
  route.page = parts[0] as Page;
  const validId = (id: string) => /^[\w-]{1,100}$/.test(id);
  if (route.page === 'play' || route.page === 'analyze') {
    route.found = parts.length === 1 || (parts.length === 2 && validId(parts[1]));
    route.gameId = parts.length === 2 && route.found ? parts[1] : null;
  } else if (route.page === 'learn') {
    route.category = parts[1] || 'all';
    route.found =
      ['all', ...categories].includes(route.category) &&
      (parts.length <= 2 || (parts.length === 4 && parts[2] === 'exercises' && validId(parts[3])));
    route.exerciseId = route.found && parts.length === 4 ? parts[3] : null;
    const session = new URLSearchParams(search).get('session');
    route.sessionId = session && validId(session) ? session : null;
  } else route.found = parts.length === 1;
  return route;
}

const subscribe = (listener: () => void) => {
  window.addEventListener('popstate', listener);
  return () => window.removeEventListener('popstate', listener);
};
const snapshot = () => window.location.pathname + window.location.search;
export function useRoute() {
  useSyncExternalStore(subscribe, snapshot);
  return parseRoute(window.location.pathname, window.location.search);
}
export function navigate(href: string, replace = false) {
  if (href === snapshot()) return;
  window.history[replace ? 'replaceState' : 'pushState'](null, '', href);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
export function gamePath(game: { id: string; mode: string }) {
  return `/${game.mode === 'analysis' ? 'analyze' : 'play'}/${encodeURIComponent(game.id)}`;
}
export function learnPath(category = 'all', exerciseId?: string, sessionId?: string | null) {
  const base = category === 'all' && !exerciseId ? '/learn' : `/learn/${category}`;
  return (
    base +
    (exerciseId ? `/exercises/${encodeURIComponent(exerciseId)}` : '') +
    (sessionId && exerciseId ? `?session=${encodeURIComponent(sessionId)}` : '')
  );
}
export function Link({ href = '/', onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      {...props}
      href={href}
      onClick={(event) => {
        onClick?.(event);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey ||
          props.target ||
          props.download
        )
          return;
        event.preventDefault();
        navigate(href);
      }}
    />
  );
}
