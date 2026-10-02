import type * as GeoJSON from 'geojson'
// Cliente da API /api/v1 (mesma origem; sessão por cookie HttpOnly)

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init?.headers } : init?.headers,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* corpo sem JSON */ }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : 'Dados inválidos')
  }
  return res.status === 204 ? (undefined as T) : (res.json() as Promise<T>)
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
export type Property = {
  id: number; name: string; lat: number | null; lon: number | null
  car_code: string | null; area_ha: number | null; municipio: string | null; uf: string | null
  car_synced_at: string | null; has_perimeter: boolean
}
export type PropertyDetail = Property & { perimeter: GeoJSON.MultiPolygon | null; bbox: [number, number, number, number] | null }
export type AreaRow = { category: string; label: string; area_ha: number }
export type Layers = GeoJSON.FeatureCollection & { areas: AreaRow[] }
export type CarCandidate = { car_code: string; municipio: string | null; uf: string | null; area_ha: number | null; modulos_rurais: number | null; tipo: string }
export type Ndvi = { date: string; mean: number | null; cloud_pct: number | null; image: string; coordinates: [number, number][] }
export type Analysis<R = Record<string, unknown>> = { id: number; kind: string; params: Record<string, unknown>; result: R; file_url: string | null; created_at: string }
export type NdviPoint = { month: string; images: number; mean: number | null; p25: number | null; p75: number | null }
export type NdviMonth = { mean: number | null; images: number; coordinates: [number, number][] }
export type RainDay = { date: string; mm: number; prob: number | null }
export type RainWeek = { start: string; end: string; mm: number }
export type Rain = { forecast: RainDay[]; weeks: RainWeek[]; last30_mm: number; normal30_mm: number | null; pct_of_normal: number | null; next7_mm: number }
export type ProdesProps = { uuid: string; class_name: string; year: number | null; image_date: string | null; area_total_ha: number; area_intersect_ha: number; biome: string | null }
export type ProdesList = GeoJSON.FeatureCollection<GeoJSON.Geometry, ProdesProps> & { source_label: string; queried_at: string }
export type ProdesJob = { id: number; status: 'PENDING' | 'PROCESSING' | 'DONE' | 'ERROR'; class_name: string; year: number | null; uuid: string; area_intersect_ha: number | null; created_at: string; finished_at: string | null; error: string | null; files: Partial<Record<'pdf' | 'antes' | 'depois', string>> }
export type LoginStart = { code: string; expires_in: number; whatsapp_url: string | null; telegram_url: string }

export const api = {
  me: () => request<Me>('/me'),
  loginStart: () => request<LoginStart>('/auth/start', { method: 'POST' }),
  loginPoll: (code: string) => request<{ status: 'pending' | 'expired' | 'ok' }>(`/auth/poll?code=${encodeURIComponent(code)}`),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),

  properties: () => request<Property[]>('/properties'),
  property: (id: number) => request<PropertyDetail>(`/properties/${id}`),
  createProperty: (body: { name: string; car_code?: string; lat?: number; lon?: number }) =>
    request<PropertyDetail>('/properties', { method: 'POST', body: JSON.stringify(body) }),
  renameProperty: (id: number, name: string) => request<PropertyDetail>(`/properties/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteProperty: (id: number) => request<void>(`/properties/${id}`, { method: 'DELETE' }),
  syncCar: (id: number, car_code?: string) => request<PropertyDetail>(`/properties/${id}/sync-car`, { method: 'POST', body: JSON.stringify(car_code ? { car_code } : {}) }),
  layers: (id: number) => request<Layers>(`/properties/${id}/layers`),
  ndvi: (id: number) => request<Ndvi>(`/properties/${id}/ndvi`),
  carLookup: (lat: number, lon: number) => request<{ candidates: CarCandidate[] }>(`/car/lookup?lat=${lat}&lon=${lon}`),
  ndviSeries: (id: number, months = 24) => request<Analysis<{ series: NdviPoint[] }>>(`/properties/${id}/ndvi/series?months=${months}`),
  ndviMonth: (id: number, month: string) => request<Analysis<NdviMonth>>(`/properties/${id}/ndvi/month?month=${month}`),
  rain: (id: number) => request<Analysis<Rain>>(`/properties/${id}/rain`),
  mdt: (id: number, kind: '2d' | '3d') => request<Analysis<{ elev_min: number; elev_max: number; source: string }>>(`/properties/${id}/mdt?kind=${kind}`),
  prodes: (id: number, refresh = false) => request<Analysis<ProdesList>>(`/properties/${id}/prodes${refresh ? '?refresh=true' : ''}`),
  prodesReport: (id: number, uuids: string[]) => request<{ job_id: number; class_name: string }[]>(`/properties/${id}/prodes/report`, { method: 'POST', body: JSON.stringify({ uuids }) }),
  prodesJobs: (id: number) => request<ProdesJob[]>(`/properties/${id}/prodes/jobs`),
  analyses: (id: number) => request<Analysis[]>(`/properties/${id}/analyses`),
  zipUrl: (id: number) => `/api/v1/properties/${id}/car.zip`,
  mapUrl: (id: number) => `/api/v1/properties/${id}/map.png`,
}

export const PLAN_LABEL: Record<Me['plan'], string> = { FREE: 'Bronze', STARTER: 'Starter', PRO: 'Ouro' }

export const fmtHa = (v: number | null | undefined) =>
  v == null ? '—' : `${v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ha`

// Cores das camadas = as mesmas do mapa ambiental do bot (app/charts.py)
export const LAYER_STYLE: Record<string, { color: string; opacity: number; label: string }> = {
  sem_classificacao: { color: '#bdbdbd', opacity: 0.55, label: 'Sem classificação no CAR' },
  consolidada: { color: '#ff3d00', opacity: 0.6, label: 'Área antropizada (consolidada)' },
  uso_restrito: { color: '#fff59d', opacity: 0.75, label: 'Uso restrito' },
  vegetacao: { color: '#4caf50', opacity: 0.55, label: 'Remanescente nativo' },
  app: { color: '#03a9f4', opacity: 0.6, label: 'A.P.P.' },
  reserva: { color: '#1b5e20', opacity: 0.7, label: 'Reserva Legal' },
  agua: { color: '#4fc3f7', opacity: 0.9, label: "Corpo d'água" },
  extra_servidao: { color: '#9e9e9e', opacity: 0.5, label: 'Servidão administrativa' },
  extra_pousio: { color: '#c5a880', opacity: 0.5, label: 'Área de pousio' },
}
export const LAYER_ORDER = Object.keys(LAYER_STYLE)

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
export const fmtMonth = (ym: string) => { const [y, m] = ym.split('-'); return `${MESES[Number(m) - 1]}/${y.slice(2)}` }
export const fmtNdvi = (v: number | null | undefined) => v == null ? '—' : v.toFixed(2).replace('.', ',')
export const fmtMm = (v: number | null | undefined) => v == null ? '—' : `${v.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mm`
export const fmtDay = (iso: string) => { const [, m, d] = iso.split('-'); return `${d}/${m}` }
