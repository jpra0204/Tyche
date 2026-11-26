// The console's key for this launch (ADR-0046). `tyche ui` opens the page at
// /#token=…; the fragment never reaches a server. It is kept for this tab only and
// removed from the address bar, so it is not left in the history.

const STORAGE_KEY = "tyche-console-token";

export function takeToken(): string | null {
  const match = /(?:^#|&)token=([^&]+)/.exec(window.location.hash);
  if (match?.[1]) {
    const token = decodeURIComponent(match[1]);
    window.sessionStorage.setItem(STORAGE_KEY, token);
    const { pathname, search } = window.location;
    window.history.replaceState(null, "", pathname + search);
    return token;
  }
  return window.sessionStorage.getItem(STORAGE_KEY);
}
