export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
const TOKEN_KEY = "psx_ai_token";
const GET_CACHE_TTL_MS = 60_000;
export const IMMUTABLE_CACHE_TTL_MS = 10 * 60_000;
type CachedResponse = { expiresAt: number; value: unknown };
const responseCache = new Map<string, CachedResponse>();
const pendingRequests = new Map<string, Promise<unknown>>();
let sampleSessionPromise: Promise<string> | null = null;

export function clearApiCache() { responseCache.clear(); pendingRequests.clear(); }
function invalidateCache(path: string) {
  const portfolioScope = path.match(/^\/portfolios\/([^/]+)\//)?.[0];
  if (!portfolioScope) { clearApiCache(); return; }
  for (const key of Array.from(responseCache.keys())) if (key.includes(portfolioScope)) responseCache.delete(key);
  for (const key of Array.from(pendingRequests.keys())) if (key.includes(portfolioScope)) pendingRequests.delete(key);
}
export function getToken() { return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY); }
export function setToken(token: string) { clearApiCache(); window.localStorage.setItem(TOKEN_KEY, token); }
export function clearToken() { clearApiCache(); window.localStorage.removeItem(TOKEN_KEY); }

async function ensureSampleToken(): Promise<string> {
  const existing = getToken();
  if (existing) return existing;
  if (!sampleSessionPromise) sampleSessionPromise = fetch(`${API_BASE_URL}/auth/sample-session`, {method:"POST",headers:{"Content-Type":"application/json"}}).then(async response=>{
    if(!response.ok)throw new Error(`Sample workspace unavailable (${response.status})`);
    const session=await response.json() as {access_token:string};setToken(session.access_token);return session.access_token;
  }).finally(()=>{sampleSessionPromise=null});
  return sampleSessionPromise;
}

export async function request<T>(path:string,options:RequestInit={},ttlMs:number=GET_CACHE_TTL_MS):Promise<T>{
  let token=getToken();if(!token&&typeof window!=="undefined"&&!path.startsWith("/auth/"))token=await ensureSampleToken();
  const method=(options.method??"GET").toUpperCase(),cacheKey=`${token?"authenticated":"anonymous"}:${path}`;
  if(method==="GET"){const cached=responseCache.get(cacheKey);if(cached&&cached.expiresAt>Date.now())return cached.value as T;if(cached)responseCache.delete(cacheKey);const pending=pendingRequests.get(cacheKey);if(pending)return pending as Promise<T>}else invalidateCache(path);
  const headers=new Headers(options.headers);headers.set("Content-Type","application/json");if(token)headers.set("Authorization",`Bearer ${token}`);
  const execute=async()=>{const response=await fetch(`${API_BASE_URL}${path}`,{...options,headers});if(!response.ok){const body=await response.json().catch(()=>({}));const detail=body.detail;const fallback=response.status>=500?"The service could not complete this request. Please try again.":`Request could not be completed (${response.status}).`;throw new Error(typeof detail==="string"?detail:detail&&typeof detail.message==="string"?detail.message:fallback)}if(response.status===204)return undefined as T;const value=await response.json() as T;if(method==="GET")responseCache.set(cacheKey,{value,expiresAt:Date.now()+ttlMs});return value};
  const result=execute();if(method==="GET")pendingRequests.set(cacheKey,result);try{return await result}finally{if(method==="GET")pendingRequests.delete(cacheKey)}
}
