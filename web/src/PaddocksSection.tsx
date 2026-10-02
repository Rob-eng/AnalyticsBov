import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, fmtHa, fmtMonth, fmtNdvi, type Paddocks } from './api'
import NdviChart from './NdviChart'

export type PaddockLayer = {
  fc: Paddocks | null; selected: number | null; drawing: boolean
  onDrawn: (g: GeoJSON.Polygon) => void; onClick: (id: number) => void
}
type Props = { propertyId: number; hasPerimeter: boolean; active: boolean; onLayer: (l: PaddockLayer | null) => void }

// últimos 12 meses fechados (o mês corrente ainda pode ganhar imagens)
const lastMonths = () => Array.from({ length: 12 }, (_, i) => {
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1 - i)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
})

export default function PaddocksSection({ propertyId, hasPerimeter, active, onLayer }: Props) {
  const qc = useQueryClient()
  const key = ['paddocks', propertyId]
  const list = useQuery({ queryKey: key, queryFn: () => api.paddocks(propertyId), enabled: hasPerimeter })
  const [drawing, setDrawing] = useState(false)
  const [pending, setPending] = useState<GeoJSON.Polygon | null>(null)
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const months = useMemo(lastMonths, [])
  const [month, setMonth] = useState(months[0])
  const [colorBy, setColorBy] = useState<string | null>(null)

  const feats = useMemo(() => list.data?.features ?? [], [list.data])
  useEffect(() => { setDrawing(false); setPending(null); setSelected(null); setColorBy(null) }, [propertyId])

  const ndvi = useQuery({ queryKey: ['paddocks-ndvi', propertyId, colorBy, feats.map(f => f.id).join(',')],
    queryFn: () => api.paddocksNdvi(propertyId, colorBy!), enabled: !!colorBy && feats.length > 0, retry: false })
  const values = useMemo(() => ndvi.data?.result.values ?? {}, [ndvi.data])
  const farm = useQuery({ queryKey: ['ndvi-series', propertyId], queryFn: () => api.ndviSeries(propertyId, 24), enabled: selected != null })
  const sel = feats.find(f => f.properties.id === selected) ?? null
  const zone = useQuery({ queryKey: ['ndvi-zone-paddock', propertyId, selected, sel?.geometry.coordinates[0].length],
    queryFn: () => api.ndviZone(propertyId, sel!.geometry, 24), enabled: !!sel, retry: false })

  const save = useMutation({
    mutationFn: () => api.createPaddock(propertyId, name.trim(), pending!),
    onSuccess: p => { setPending(null); setName(''); setSelected(p.properties.id); qc.invalidateQueries({ queryKey: key }) },
  })
  const rename = useMutation({
    mutationFn: (r: { id: number; name: string }) => api.editPaddock(propertyId, r.id, { name: r.name.trim() }),
    onSuccess: () => { setRenaming(null); qc.invalidateQueries({ queryKey: key }) },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.deletePaddock(propertyId, id),
    onSuccess: (_d, id) => { if (selected === id) setSelected(null); qc.invalidateQueries({ queryKey: key }) },
  })

  // camada do mapa: piquetes salvos (com NDVI do mês, se pedido) + o recém-desenhado
  const fc = useMemo<Paddocks | null>(() => {
    if (!active || !hasPerimeter) return null
    const base = feats.map(f => {
      const v = values[String(f.properties.id)]
      return { ...f, properties: { ...f.properties, ...(colorBy && v != null ? { ndvi: v } : {}) } }
    })
    if (pending) base.push({ type: 'Feature', id: -1, geometry: pending, properties: { id: -1, name: name || 'Novo piquete', area_ha: 0 } })
    return { type: 'FeatureCollection', features: base }
  }, [active, hasPerimeter, feats, values, colorBy, pending, name])

  useEffect(() => {
    onLayer(active ? {
      fc, selected, drawing,
      onDrawn: g => { setDrawing(false); setPending(g); setName(`Piquete ${feats.length + 1}`) },
      onClick: id => setSelected(s => (s === id ? null : id)),
    } : null)
  }, [active, fc, selected, drawing, feats.length, onLayer])
  useEffect(() => () => onLayer(null), [onLayer])

  if (!hasPerimeter) return <div className="block"><h3>Piquetes</h3><p className="muted">Vincule o CAR desta propriedade para desenhar os piquetes sobre o perímetro.</p></div>

  const total = feats.reduce((s, f) => s + (f.properties.area_ha || 0), 0)
  return (
    <div className="block">
      <h3>Piquetes</h3>
      {list.isPending && <p className="muted">Carregando piquetes…</p>}
      {list.isSuccess && !feats.length && !pending && !drawing && (
        <p className="muted">Desenhe os piquetes da fazenda para acompanhar o vigor do pasto em cada um.</p>
      )}
      {feats.length > 0 && <p className="muted small">{feats.length} piquete{feats.length > 1 ? 's' : ''} · {fmtHa(total)}</p>}

      {!drawing && !pending && <button className="btn btn-sm" onClick={() => { setSelected(null); setDrawing(true) }}>Desenhar piquete</button>}
      {drawing && (
        <div className="draw-help">
          <p className="small">Clique no mapa para marcar os cantos do piquete. Para fechar, clique de novo no primeiro ponto.</p>
          <button className="link" onClick={() => setDrawing(false)}>Cancelar</button>
        </div>
      )}
      {pending && (
        <form className="draw-help" onSubmit={e => { e.preventDefault(); if (name.trim()) save.mutate() }}>
          <label className="field"><span>Nome do piquete</span>
            <input className="input" value={name} onChange={e => setName(e.target.value)} maxLength={60} autoFocus />
          </label>
          <p className="muted small">O que passar do perímetro é recortado ao salvar.</p>
          {save.isError && <p className="notice">{(save.error as Error).message}</p>}
          <div className="row">
            <button className="btn btn-sm" type="submit" disabled={!name.trim() || save.isPending}>{save.isPending ? 'Salvando…' : 'Salvar piquete'}</button>
            <button className="link" type="button" onClick={() => { setPending(null); save.reset() }}>Descartar</button>
          </div>
        </form>
      )}

      {feats.length > 0 && (
        <>
          <div className="row paddock-ndvi-bar">
            <select className="input input-sm" value={month} onChange={e => setMonth(e.target.value)} aria-label="Mês do NDVI">
              {months.map(m => <option key={m} value={m}>{fmtMonth(m)}</option>)}
            </select>
            <button className="btn btn-sm btn-ghost" disabled={ndvi.isFetching} onClick={() => setColorBy(month)}>
              {ndvi.isFetching ? 'Calculando (≈30 s)…' : 'Colorir por NDVI'}
            </button>
            {colorBy && !ndvi.isFetching && <button className="link small" onClick={() => setColorBy(null)}>Limpar</button>}
          </div>
          {ndvi.isError && <p className="notice">{(ndvi.error as Error).message}</p>}
          {colorBy && ndvi.isSuccess && (
            <div className="ndvi-legend" aria-label="Escala de NDVI">
              <span>NDVI {fmtMonth(colorBy)}</span><i /><span className="mono small">0 — 0,8</span>
            </div>
          )}

          <ul className="paddock-list">
            {[...feats].sort((a, b) => colorBy ? (values[String(a.properties.id)] ?? 9) - (values[String(b.properties.id)] ?? 9) : 0).map(f => {
              const p = f.properties
              const v = values[String(p.id)]
              return (
                <li key={p.id} className={'paddock' + (p.id === selected ? ' paddock-on' : '')}>
                  {renaming?.id === p.id ? (
                    <form className="row" onSubmit={e => { e.preventDefault(); if (renaming.name.trim()) rename.mutate(renaming) }}>
                      <input className="input input-sm" value={renaming.name} onChange={e => setRenaming({ ...renaming, name: e.target.value })} maxLength={60} autoFocus />
                      <button className="link small" type="submit">Salvar</button>
                      <button className="link small" type="button" onClick={() => setRenaming(null)}>Cancelar</button>
                    </form>
                  ) : (
                    <button className="paddock-main" onClick={() => setSelected(s => (s === p.id ? null : p.id))}>
                      <strong>{p.name}</strong>
                      <span className="muted small">{fmtHa(p.area_ha)}{colorBy ? ` · NDVI ${fmtNdvi(v ?? null)}` : ''}</span>
                    </button>
                  )}
                  {p.id === selected && renaming?.id !== p.id && (
                    <span className="row small">
                      <button className="link" onClick={() => setRenaming({ id: p.id, name: p.name })}>Renomear</button>
                      <button className="link danger" onClick={() => { if (confirm(`Excluir o piquete "${p.name}"?`)) remove.mutate(p.id) }}>Excluir</button>
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          {colorBy && <p className="muted small">Ordenados do menor para o maior NDVI: os primeiros pedem atenção.</p>}

          {sel && (
            <div className="paddock-detail">
              <p className="small"><strong>{sel.properties.name}</strong> × média da fazenda, mês a mês</p>
              {(zone.isFetching || farm.isFetching) && <p className="muted small">Calculando 24 meses (≈15 s)…</p>}
              {zone.isError && <p className="notice">{(zone.error as Error).message}</p>}
              {farm.data && zone.data && (
                <NdviChart series={farm.data.result.series} selected={[]} onPick={() => {}} zone={zone.data.result.series} zoneLabel={sel.properties.name} />
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
