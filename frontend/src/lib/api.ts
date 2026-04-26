// Base URL for all API calls.
// In dev, VITE_API_URL is unset so paths are relative — Vite's proxy handles them.
// In production, set VITE_API_URL to your backend URL (e.g. https://api.evidentia.app).
export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

// For WebSocket connections, derive wss:// / ws:// from the API_BASE or current host.
export function wsUrl(path: string): string {
  if (API_BASE) {
    const base = API_BASE.replace(/^https:/, "wss:").replace(/^http:/, "ws:");
    return `${base}${path}`;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
