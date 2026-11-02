import { createClient } from "@supabase/supabase-js";

const listeners = new Set();
let supabase;
let session;
let configured = false;
let initialization;

function notify() {
  for (const listener of listeners) {
    listener(session);
  }
}

async function initialize() {
  if (initialization) return initialization;
  initialization = (async () => {
    const response = await fetch("/api/v1/auth/config");
    const config = await response.json();
    if (!response.ok) {
      throw new Error(config.detail || `Authentication setup failed (${response.status}).`);
    }
    configured = Boolean(config.enabled);
    if (!configured) return;

    supabase = createClient(config.supabase_url, config.supabase_anon_key, {
      auth: {
        storage: window.sessionStorage,
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
    const { data, error } = await supabase.auth.getSession();
    if (error) throw error;
    session = data.session;
    supabase.auth.onAuthStateChange((_event, nextSession) => {
      session = nextSession;
      notify();
    });
  })();
  return initialization;
}

async function signIn(email, password) {
  if (!supabase) throw new Error("Supabase authentication is not configured.");
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
  session = data.session;
  notify();
}

async function signOut() {
  if (!supabase) return;
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
  session = null;
  notify();
}

window.floppiAuth = {
  initialize,
  signIn,
  signOut,
  subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  isConfigured: () => configured,
  getAccessToken: () => session?.access_token ?? null,
  getUserEmail: () => session?.user?.email ?? "",
  isAdmin: () => session?.user?.app_metadata?.role === "admin",
};
