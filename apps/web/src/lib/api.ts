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

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
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
  subscription: { plan: Plan; monthly_recipe_count: number } | null;
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
  auth = true
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

  // trends
  listTrends: (region?: string) => {
    const qs = region ? `?region=${encodeURIComponent(region)}` : "";
    return request<Trend[]>(`/trends${qs}`, {}, false);
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
