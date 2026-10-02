import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { api, fmtHa, LAYER_ORDER, LAYER_STYLE, type Ndvi } from './api'
import type { Focus } from './MapView'
import NdviSection from './NdviSection'
import RainSection from './RainSection'
import MdtSection from './MdtSection'
import ProdesSection from './ProdesSection'
import type { ProdesList } from './api'

export type Pick = { active: boolean; point: { lat: number; lon: number } | null }

export default function PropertyPanel({ onFocus, pick, setPick }: { onFocus: (f: Focus | null) => void; pick: Pick; setPick: (p: Pick) => void }) {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const prop = useQuery({ queryKey: ['property', id], queryFn: () => api.property(id) })
  const layers = useQuery({ queryKey: ['layers', id], queryFn: () => api.layers(id), enabled: !!prop.data?.has_perimeter })
  const [visible, setVisible] = useState<Set<string>>(new Set(LAYER_ORDER))
  const [ndvi, setNdvi] = useState<Ndvi | null>(null)
  const [prodes, setProdes] = useState<{ fc: ProdesList | null; selected: Set<string> }>({ fc: null, selected: new Set() })
  const onProdes = useCallback((fc: ProdesList | null, selected: Set<string>) => setProdes({ fc, selected }), [])
  const [code, setCode] = useState('')
  const [downloading, setDownloading] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  useEffect(() => { setNdvi(null) }, [id])

  const focus = useMemo<Focus | null>(() => prop.data ? {
    perimeter: prop.data.perimeter, bbox: prop.data.bbox, layers: layers.data ?? null, visible, ndvi,
    prodes: prodes.fc, prodesSelected: prodes.selected,
  } : null, [prop.data, layers.data, visible, ndvi, prodes])
  useEffect(() => { onFocus(focus); }, [focus, onFocus])
  useEffect(() => () => onFocus(null), [onFocus])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['property', id] })
    qc.invalidateQueries({ queryKey: ['layers', id] })
    qc.invalidateQueries({ queryKey: ['properties'] })
  }
  const sync = useMutation({ mutationFn: () => api.syncCar(id, code.trim().toUpperCase() || undefined), onSuccess: refresh })
  const remove = useMutation({
    mutationFn: () => api.deleteProperty(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['properties'] }); navigate('/') },
  })

  async function download(url: string, label: string) {
    setDownloading(label); setDownloadError(null)
    try {
      const res = await fetch(url, { credentials: 'same-origin' })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Falha no download')
      const blob = await res.blob()
      const name = decodeURIComponent((res.headers.get('content-disposition') ?? '').split("''")[1] ?? label)
      const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name })
      a.click(); URL.revokeObjectURL(a.href)
    } catch (e) { setDownloadError((e as Error).message) } finally { setDownloading(null) }
  }

  const toggle = (cat: string) => setVisible(v => { const n = new Set(v); if (n.has(cat)) n.delete(cat); else n.add(cat); return n })

  if (prop.isPending) return <section className="panel"><p className="muted">Carregando…</p></section>
  if (prop.isError) return <section className="panel"><p className="notice">{(prop.error as Error).message}</p><Link className="link" to="/">Voltar</Link></section>
  const p = prop.data
  const presentCats = new Set((layers.data?.features ?? []).map(f => f.properties?.category as string))

  return (
    <section className="panel">
      <Link className="link back" to="/">← Propriedades</Link>
      <div>
        <h2 className="prop-title">{p.name}</h2>
        {p.has_perimeter
          ? <p className="muted">{fmtHa(p.area_ha)} · {p.municipio}/{p.uf}</p>
          : <p className="muted">Cadastrada pelo bot, ainda sem o CAR vinculado.</p>}
        {p.car_code && <p className="mono small">{p.car_code}</p>}
      </div>

      {!p.has_perimeter && (
        <div className="field-group">
          <label className="field">
            <span>Código do CAR (opcional)</span>
            <input className="input mono" value={code} onChange={e => setCode(e.target.value)} placeholder="Deixe em branco para achar pela localização" spellCheck={false} />
          </label>
          {sync.isError && <p className="notice">{(sync.error as Error).message}</p>}
          <button className="btn" disabled={sync.isPending} onClick={() => sync.mutate()}>
            {sync.isPending ? 'Buscando as camadas do CAR…' : 'Vincular CAR'}
          </button>
        </div>
      )}

      {p.has_perimeter && (
        <>
          <div className="block">
            <h3>Camadas do CAR</h3>
            {layers.isPending && <p className="muted">Carregando camadas…</p>}
            <ul className="layer-list">
              {(layers.data?.areas ?? []).filter(a => a.category !== 'imovel').map(a => (
                <li key={a.category}>
                  <label className="layer">
                    <input type="checkbox" checked={visible.has(a.category)} onChange={() => toggle(a.category)} disabled={!presentCats.has(a.category)} />
                    <span className="swatch" style={{ background: LAYER_STYLE[a.category]?.color ?? '#999' }} />
                    <span className="layer-name">{a.label}</span>
                    <span className="layer-area">{fmtHa(a.area_ha)}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>

          <NdviSection propertyId={id} shown={ndvi} onShow={setNdvi} pick={pick} setPick={setPick} />

          <RainSection propertyId={id} />

          <MdtSection propertyId={id} />

          <ProdesSection propertyId={id} onLayer={onProdes} />

          <div className="block">
            <h3>Arquivos</h3>
            <div className="row">
              <button className="btn btn-sm btn-ghost" disabled={!!downloading} onClick={() => download(api.zipUrl(id), 'CAR.zip')}>
                {downloading === 'CAR.zip' ? 'Gerando…' : 'Camadas do CAR (ZIP)'}
              </button>
              <button className="btn btn-sm btn-ghost" disabled={!!downloading} onClick={() => download(api.mapUrl(id), 'Mapa.png')}>
                {downloading === 'Mapa.png' ? 'Gerando mapa (≈20 s)…' : 'Mapa CAR (PNG)'}
              </button>
            </div>
            {downloadError && <p className="notice">{downloadError}</p>}
          </div>

          <div className="row muted small">
            <button className="link" disabled={sync.isPending} onClick={() => sync.mutate()}>{sync.isPending ? 'Atualizando…' : 'Atualizar dados do CAR'}</button>
            {p.car_synced_at && <span>· atualizado em {new Date(p.car_synced_at).toLocaleDateString('pt-BR')}</span>}
          </div>
        </>
      )}

      <button className="link danger" onClick={() => { if (confirm(`Excluir "${p.name}"? Ela também some do bot.`)) remove.mutate() }}>
        Excluir propriedade
      </button>
    </section>
  )
}
