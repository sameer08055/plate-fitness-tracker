/*
  Login with Cognito's hosted login page, using the "authorization code
  with PKCE" flow, which is the recommended flow for browser apps:

  1. We make a random secret (the "verifier") and send only its SHA-256
     hash (the "challenge") when redirecting to the login page.
  2. Cognito sends the browser back here with a one-time ?code=...
  3. We trade the code AND the original verifier for tokens. Someone who
     intercepted the code can't use it without the verifier.
*/
const CONFIG = window.APP_CONFIG;
const TOKEN_KEY = "plate.tokens";

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString() {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return base64url(new Uint8Array(digest));
}

function saveTokens(response, previous = {}) {
  const tokens = {
    accessToken: response.access_token,
    // Refreshing doesn't return a new refresh token, so keep the old one.
    refreshToken: response.refresh_token || previous.refreshToken,
    expiresAt: Date.now() + response.expires_in * 1000,
  };
  localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
  return tokens;
}

function loadTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKEN_KEY));
  } catch {
    return null;
  }
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
}

async function requestTokens(params) {
  const response = await fetch(`${CONFIG.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CONFIG.clientId, ...params }),
  });
  if (!response.ok) throw new Error("Sign-in failed. Please sign in again.");
  return response.json();
}

export async function login() {
  const verifier = randomString();
  const state = randomString();
  // localStorage (not sessionStorage) so this survives the redirect even
  // when the app is opened from a phone's home screen.
  localStorage.setItem("plate.pkce", JSON.stringify({ verifier, state }));

  const params = new URLSearchParams({
    response_type: "code",
    client_id: CONFIG.clientId,
    redirect_uri: CONFIG.redirectUri,
    scope: "openid email",
    code_challenge_method: "S256",
    code_challenge: await sha256(verifier),
    state,
  });
  location.assign(`${CONFIG.cognitoDomain}/oauth2/authorize?${params}`);
}

/** If we just came back from the login page, finish signing in. */
export async function handleLoginRedirect() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (!code) return;

  const saved = JSON.parse(localStorage.getItem("plate.pkce") || "{}");
  localStorage.removeItem("plate.pkce");
  history.replaceState({}, "", "/"); // remove ?code= from the address bar

  // 'state' must match what we sent, which blocks forged login redirects.
  if (params.get("state") !== saved.state) throw new Error("Sign-in didn't match. Please try again.");

  const response = await requestTokens({
    grant_type: "authorization_code",
    code,
    redirect_uri: CONFIG.redirectUri,
    code_verifier: saved.verifier,
  });
  saveTokens(response);
}

/** A valid access token, refreshed if it's about to expire. Null if signed out. */
export async function getAccessToken() {
  const tokens = loadTokens();
  if (!tokens) return null;
  if (Date.now() < tokens.expiresAt - 60_000) return tokens.accessToken;
  if (!tokens.refreshToken) return null;

  try {
    const response = await requestTokens({ grant_type: "refresh_token", refresh_token: tokens.refreshToken });
    return saveTokens(response, tokens).accessToken;
  } catch {
    clearTokens();
    return null;
  }
}

export function isSignedIn() {
  return loadTokens() !== null;
}

export function logout() {
  clearTokens();
  const params = new URLSearchParams({ client_id: CONFIG.clientId, logout_uri: CONFIG.redirectUri });
  location.assign(`${CONFIG.cognitoDomain}/logout?${params}`);
}
