/* One place that talks to our API, so every request gets the login token. */
import { clearTokens, getAccessToken, login } from "./auth.js";

const CONFIG = window.APP_CONFIG;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(method, path, body) {
  const token = await getAccessToken();
  if (!token) {
    await login();
    throw new ApiError("Signing you in.", 401);
  }

  let response;
  try {
    response = await fetch(CONFIG.apiUrl + path, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch only throws when there's no response at all (offline, or a
    // throttled request blocked by the browser's CORS check).
    throw new ApiError("Couldn't reach the server. Check your connection and try again.", 0);
  }

  if (response.status === 401) {
    clearTokens();
    await login();
    throw new ApiError("Your session ended. Signing you in again.", 401);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = response.status === 429
      ? "Too many requests at once. Wait a moment and try again."
      : data.error || `Request failed (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return data;
}
