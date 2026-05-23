/**
 * Typed API client for the K-Heritage Recipe AI backend.
 *
 * All requests target `/v1/*` and (in dev) are proxied to the FastAPI server
 * via Vite's `server.proxy` config. Auth tokens live in localStorage.
 */

const TOKEN_KEY = "kh.access_token";
const REFRESH_KEY = "kh.refresh_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

let onSessionExpired: (() => void) | null = null;

/** Wire a callback that fires when a refresh attempt definitively fails so the
 *  UI layer can sign the user out (instead of looping on 401s). */
export function setOnSessionExpired(cb: (() => void) | null) {
  onSessionExpired = cb;
}

// In-flight refresh promise so concurrent 401s share a single refresh call.
let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;

  refreshInFlight = (async () => {
    try {
      const res = await fetch("/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        clearTokens();
        onSessionExpired?.();
        return null;
      }
      const tokens = (await res.json()) as TokenResponse;
      setTokens(tokens.access_token, tokens.refresh_token);
      return tokens.access_token;
    } catch {
      clearTokens();
      onSessionExpired?.();
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export type Plan = "free" | "pro" | "b2b";
export type RecipeStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "rejected"
  | "flagged";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  onboarding_completed: boolean;
  persona: string;
  preferred_regions: string[];
  preferred_keywords: string[];
  subscription: { plan: Plan; monthly_recipe_count: number } | null;
}

export interface UserUpdatePayload {
  display_name?: string;
  persona?: string;
  preferred_regions?: string[];
  preferred_keywords?: string[];
  onboarding_completed?: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Trend {
  rank: number;
  keyword: string;
  region: string;
  change_percent: number;
  is_up: boolean;
  week_of: string;
}

export interface TrendSeriesPoint {
  period: string;
  ratio: number;
}

export interface TrendSeries {
  keyword: string;
  time_unit: string;
  points: TrendSeriesPoint[];
}

export interface HeritageDocument {
  id: string;
  title: string;
  institution: string;
  region: string;
  period: string;
  category: string;
  year: number | null;
  summary: string;
  license: string;
}

export interface DocumentMatch {
  document: HeritageDocument;
  match_score: number;
}

export interface RecipeCandidate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  time_minutes: number;
  estimated_cost_krw: number;
  source_attribution: string;
  is_recommended: boolean;
  image_url: string;
  status: RecipeStatus;
}

export interface RecipeListItem {
  id: string;
  name: string;
  region: string;
  era: string;
  keyword: string;
  status: RecipeStatus;
  is_recommended: boolean;
  image_url: string;
  estimated_cost_krw: number;
  time_minutes: number;
  rating: number;
  is_selling: boolean;
  rejection_reason: string;
}

export interface RecipeStep {
  title: string;
  description: string;
  waiting: boolean;
}

export interface IngredientLine {
  name: string;
  amount: string;
  note: string;
}

export interface RecipeDetail {
  id: string;
  name: string;
  description: string;
  region: string;
  era: string;
  diet: string;
  menu_type: string;
  keyword: string;
  difficulty: string;
  time_minutes: number;
  servings: number;
  estimated_cost_krw: number;
  estimated_price_krw: number;
  steps: RecipeStep[];
  ingredients: IngredientLine[];
  sns_caption: string;
  image_url: string;
  source_attribution: string;
  status: RecipeStatus;
  is_recommended: boolean;
  rating: number;
  is_selling: boolean;
  rejection_reason: string;
}

export interface GenerateResponse {
  candidates: RecipeCandidate[];
  matched_documents: DocumentMatch[];
}

export interface ApiError extends Error {
  status: number;
  code?: string;
  detail?: unknown;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  auth = true,
  isRetry = false
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`/v1${path}`, { ...init, headers });

  // 401 on an authenticated request → try to silently refresh once, then retry.
  // Skip the refresh path itself to avoid recursion and skip non-auth calls.
  if (
    res.status === 401 &&
    auth &&
    !isRetry &&
    path !== "/auth/refresh" &&
    getRefreshToken()
  ) {
    const fresh = await refreshAccessToken();
    if (fresh) return request<T>(path, init, auth, true);
  }

  if (res.status === 204) return undefined as unknown as T;

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await res.json() : await res.blob();

  if (!res.ok) {
    const err = new Error(
      (body as { message?: string })?.message || `${res.status} ${res.statusText}`
    ) as ApiError;
    err.status = res.status;
    err.code = (body as { error?: string })?.error;
    err.detail = body;
    throw err;
  }
  return body as T;
}

export const api = {
  // auth
  register: (email: string, password: string, displayName?: string) =>
    request<TokenResponse>(
      "/auth/register",
      {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: displayName || "" }),
      },
      false
    ),
  login: (email: string, password: string) =>
    request<TokenResponse>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false
    ),
  me: () => request<User>("/auth/me"),
  updateMe: (payload: UserUpdatePayload) =>
    request<User>("/private/users/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  refresh: (refreshToken: string) =>
    request<TokenResponse>(
      "/auth/refresh",
      { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) },
      false
    ),

  // trends
  listTrends: (region?: string) => {
    const qs = region ? `?region=${encodeURIComponent(region)}` : "";
    return request<Trend[]>(`/trends${qs}`, {}, false);
  },
  getTrendSeries: (keyword: string, weeks = 8) => {
    const qs = new URLSearchParams({ keyword, weeks: String(weeks) }).toString();
    return request<TrendSeries>(`/trends/series?${qs}`, {}, false);
  },

  // documents
  searchDocuments: (params: {
    q?: string;
    institution?: string;
    region?: string;
    period?: string;
  }) => {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v) usp.set(k, v);
    });
    const qs = usp.toString() ? `?${usp}` : "";
    return request<HeritageDocument[]>(`/documents${qs}`, {}, false);
  },
  getDocument: (id: string) => request<HeritageDocument>(`/documents/${id}`, {}, false),

  // recipes
  generateRecipes: (payload: {
    keyword: string;
    region: string;
    diet: string;
    menu_type: string;
    document_id?: string;
  }) =>
    request<GenerateResponse>("/private/recipes/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listMyRecipes: () => request<RecipeListItem[]>("/private/recipes"),
  getRecipe: (id: string) => request<RecipeDetail>(`/private/recipes/${id}`),
  updateRecipe: (
    id: string,
    payload: { rating?: number; is_selling?: boolean }
  ) =>
    request<RecipeDetail>(`/private/recipes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteRecipe: (id: string) =>
    request<void>(`/private/recipes/${id}`, { method: "DELETE" }),
  recipePdfUrl: (id: string) => `/v1/private/recipes/${id}/export/pdf`,
  certificateUrl: (id: string) => `/v1/private/recipes/${id}/certificate`,

  // subscription
  getSubscription: () =>
    request<{ plan: Plan; monthly_recipe_count: number }>("/private/subscription"),
  changePlan: (plan: Plan) =>
    request<{ plan: Plan; monthly_recipe_count: number }>(
      "/private/subscription/plan",
      { method: "POST", body: JSON.stringify({ plan }) }
    ),

  // admin
  listPendingRecipes: (status: RecipeStatus = "pending_review") =>
    request<RecipeListItem[]>(`/admin/recipes?status_filter=${status}`),
  updateRecipeStatus: (id: string, status: RecipeStatus, rejection_reason = "") =>
    request<RecipeListItem>(`/admin/recipes/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, rejection_reason }),
    }),
};
