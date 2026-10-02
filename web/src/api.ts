// Cliente da API /api/v1 (mesma origem; sessão por cookie HttpOnly)

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* corpo sem JSON */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export type Organization = { id: number; name: string; kind: 'produtor' | 'consultoria'; role: string }
export type Me = {
  chat_id: string
  name: string | null
  platform: 'whatsapp' | 'telegram'
  plan: 'FREE' | 'STARTER' | 'PRO'
  trial_expires_at: string | null
  organizations: Organization[]
  mode: 'produtor' | 'consultor'
}
export type Property = { id: number; name: string; lat: number; lon: number }
export type LoginStart = { code: string; expires_in: number; whatsapp_url: string | null; telegram_url: string }

export const api = {
  me: () => request<Me>('/me'),
  properties: () => request<Property[]>('/properties'),
  loginStart: () => request<LoginStart>('/auth/start', { method: 'POST' }),
  loginPoll: (code: string) => request<{ status: 'pending' | 'expired' | 'ok' }>(`/auth/poll?code=${encodeURIComponent(code)}`),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),
}

export const PLAN_LABEL: Record<Me['plan'], string> = { FREE: 'Bronze', STARTER: 'Starter', PRO: 'Ouro' }
