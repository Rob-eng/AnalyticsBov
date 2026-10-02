import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, fmtHa, fmtMonth, fmtNdvi, type GrazingPaddock, type Paddocks } from './api'
import NdviChart from './NdviChart'

export type PaddockLayer = {
  fc: Paddocks | null; selected: number | null; drawing: boolean
  onDrawn: (g: GeoJSON.Geometry) => void; onClick: (id: number) => void
  editing: { id: number; geometry: GeoJSON.Polygon } | null; onEdited: (g: GeoJSON.Polygon) => void
}
const LATEST = 'latest'
const STATUS_LABEL: Record<string, string> = { em_uso: 'Em uso', descanso: 'Descanso', pronto: 'Pronto para entrada', descanso_longo: 'Descanso longo', sem_registro: 'Sem registro' }
const statusText = (g?: GrazingPaddock) => {
  if (!g) return null
  if (g.status === 'em_uso') return `Em uso · ${g.days} d${g.ua_ha != null ? ` · ${g.ua_ha.toFixed(2).replace('.', ',')} UA/ha` : ''}`
  if (g.status === 'sem_registro') return 'Sem registro de uso'
  return `${STATUS_LABEL[g.status]} · ${g.days} d`
}
const fmtDay = (d?: string | null) => d ? d.split('-').reverse().join('/') : ''
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
  // piquete criado/editado/recortado/excluído muda a área de pasto → lotação (UA/ha) também
  const refresh = () => { qc.invalidateQueries({ queryKey: key }); qc.invalidateQueries({ queryKey: ['grazing', propertyId] }); qc.invalidateQueries({ queryKey: ['herd', propertyId] }) }
  const [drawing, setDrawing] = useState(false)
  const [cutting, setCutting] = useState(false)   // desenho atual é um recorte (mata) do piquete selecionado
  const [pending, setPending] = useState<GeoJSON.Polygon | null>(null)
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const months = useMemo(lastMonths, [])
  const [month, setMonth] = useState(LATEST)
  const [editing, setEditing] = useState<{ id: number; geometry: GeoJSON.Polygon } | null>(null)
  const [edited, setEdited] = useState<GeoJSON.Polygon | null>(null)
  const [colorBy, setColorBy] = useState<string | null>(null)

  const feats = useMemo(() => list.data?.features ?? [], [list.data])
  useEffect(() => { setDrawing(false); setPending(null); setSelected(null); setColorBy(null); setEditing(null); setEdited(null) }, [propertyId])
  useEffect(() => { if (!active) { setEditing(null); setEdited(null); setDrawing(false) } }, [active])

  const ndvi = useQuery({ queryKey: ['paddocks-ndvi', propertyId, colorBy, feats.map(f => `${f.id}:${f.properties.pasture_ha}`).join(',')],
    queryFn: () => api.paddocksNdvi(propertyId, colorBy!), enabled: !!colorBy && feats.length > 0, retry: false })
  const values = useMemo(() => ndvi.data?.result.values ?? {}, [ndvi.data])
  const grazing = useQuery({ queryKey: ['grazing', propertyId], queryFn: () => api.grazing(propertyId), enabled: active && hasPerimeter })
  const gmap = useMemo(() => new Map((grazing.data?.paddocks ?? []).map(g => [g.id, g])), [grazing.data])
  // NDVI da última imagem recalculado → os alertas de lotação × NDVI usam o valor novo
  useEffect(() => { if (colorBy === LATEST && ndvi.isSuccess) qc.invalidateQueries({ queryKey: ['grazing', propertyId] }) }, [colorBy, ndvi.isSuccess, ndvi.data, qc, propertyId])
  const farm = useQuery({ queryKey: ['ndvi-series', propertyId], queryFn: () => api.ndviSeries(propertyId, 24), enabled: selected != null })
  const sel = feats.find(f => f.properties.id === selected) ?? null
  // série só da área de pasto (contorno − recortes): a chave muda quando o formato ou os recortes mudam
  const zone = useQuery({ queryKey: ['paddock-series', propertyId, selected, JSON.stringify(sel?.geometry.coordinates ?? null), sel?.properties.pasture_ha],
    queryFn: () => api.paddockSeries(propertyId, sel!.properties.id), enabled: !!sel, retry: false })

  const save = useMutation({
    mutationFn: () => api.createPaddock(propertyId, name.trim(), pending!),
    onSuccess: p => { setPending(null); setName(''); setSelected(p.properties.id); refresh() },
  })
  const rename = useMutation({
    mutationFn: (r: { id: number; name: string }) => api.editPaddock(propertyId, r.id, { name: r.name.trim() }),
    onSuccess: () => { setRenaming(null); refresh() },
  })
  const reshape = useMutation({
    mutationFn: () => api.editPaddock(propertyId, editing!.id, { geometry: edited! }),
    onSuccess: () => { setEditing(null); setEdited(null); refresh() },
  })
  const startEdit = (id: number) => {
    const f = feats.find(x => x.properties.id === id)
    if (f) { reshape.reset(); setDrawing(false); setEdited(null); setEditing({ id, geometry: f.geometry }) }
  }
  const cut = useMutation({
    mutationFn: (body: { geometry: GeoJSON.Polygon } | { source: 'car' }) => api.cutPaddock(propertyId, selected!, body),
    onSuccess: () => refresh(),
  })
  const cutMutate = cut.mutate   // estável entre renders (o objeto da mutação não é)
  const clearCuts = useMutation({
    mutationFn: (pid: number) => api.clearCuts(propertyId, pid),
    onSuccess: () => refresh(),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.deletePaddock(propertyId, id),
    onSuccess: (_d, id) => { if (selected === id) setSelected(null); refresh() },
  })

  // camada do mapa: piquetes salvos (com NDVI do mês, se pedido) + o recém-desenhado
  const fc = useMemo<Paddocks | null>(() => {
    if (!active || !hasPerimeter) return null
    const base = feats.filter(f => f.properties.id !== editing?.id).map(f => {
      const v = values[String(f.properties.id)]
      const g = gmap.get(f.properties.id)
      const st = g?.status
      // em uso: o rótulo do mapa ganha o boizinho e a lotação, com ou sem a cor de NDVI
      const use = st === 'em_uso' ? { in_use: true, ua_ha: g?.ua_ha ?? null } : {}
      return { ...f, properties: { ...f.properties, ...use, ...(colorBy && v != null ? { ndvi: v } : st ? { status: st } : {}) } }
    })
    if (pending) base.push({ type: 'Feature', id: -1, geometry: pending, properties: { id: -1, name: name || 'Novo piquete', area_ha: 0, pasture_ha: 0, excluded_ha: 0 } })
    return { type: 'FeatureCollection', features: base, exclusions: list.data?.exclusions }
  }, [active, hasPerimeter, feats, values, colorBy, pending, name, editing, list.data, gmap])

  useEffect(() => {
    onLayer(active ? {
      fc, selected, drawing,
      onDrawn: g => {
        setDrawing(false)
        if (g.type !== 'Polygon') return
        if (cutting) { setCutting(false); cutMutate({ geometry: g }) }
        else { setPending(g); setName(`Piquete ${feats.length + 1}`) }
      },
      onClick: id => { if (!editing) setSelected(s => (s === id ? null : id)) },
      editing,
      // selecionar já dispara 'change' no Terra Draw: só conta como edição se o formato mudou
      onEdited: g => setEdited(editing && JSON.stringify(g.coordinates) !== JSON.stringify(editing.geometry.coordinates) ? g : null),
    } : null)
  }, [active, fc, selected, drawing, cutting, cutMutate, feats.length, onLayer, editing])
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

      {editing && (
        <div className="draw-help">
          <p className="small"><strong>Editando {feats.find(f => f.properties.id === editing.id)?.properties.name}</strong></p>
          <p className="small">Arraste os cantos (pontos escuros) para ajustar. Arraste um ponto amarelo, no meio de um lado, para criar um canto novo. Botão direito num canto o remove.</p>
          {reshape.isError && <p className="notice">{(reshape.error as Error).message}</p>}
          <div className="row">
            <button className="btn btn-sm" disabled={!edited || reshape.isPending} onClick={() => reshape.mutate()}>
              {reshape.isPending ? 'Salvando…' : edited ? 'Salvar formato' : 'Sem alterações'}
            </button>
            <button className="link" onClick={() => { setEditing(null); setEdited(null) }}>Cancelar</button>
          </div>
        </div>
      )}
      {!drawing && !pending && !editing && <button className="btn btn-sm" onClick={() => { setSelected(null); setDrawing(true) }}>Desenhar piquete</button>}
      {drawing && (
        <div className="draw-help">
          <p className="small">{cutting
            ? 'Contorne a mata (ou outra área) a tirar do piquete. Para fechar, clique de novo no primeiro ponto.'
            : 'Clique no mapa para marcar os cantos do piquete. Para fechar, clique de novo no primeiro ponto.'}</p>
          <button className="link" onClick={() => { setDrawing(false); setCutting(false) }}>Cancelar</button>
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
              <option value={LATEST}>Última imagem</option>
              {months.map(m => <option key={m} value={m}>Média de {fmtMonth(m)}</option>)}
            </select>
            <button className="btn btn-sm btn-ghost" disabled={ndvi.isFetching} onClick={() => setColorBy(month)}>
              {ndvi.isFetching ? 'Calculando (≈30 s)…' : 'Colorir por NDVI'}
            </button>
            {colorBy && !ndvi.isFetching && <button className="link small" onClick={() => setColorBy(null)}>Limpar</button>}
          </div>
          {ndvi.isError && <p className="notice">{(ndvi.error as Error).message}</p>}
          {colorBy && ndvi.isSuccess && (
            <div className="ndvi-legend" aria-label="Escala de NDVI">
              <span>{colorBy === LATEST ? `NDVI da imagem de ${fmtDay(ndvi.data?.result.date)}` : `NDVI médio de ${fmtMonth(colorBy)}`}</span><i /><span className="mono small">0 — 0,8</span>
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
                      <span className="row"><strong>{p.name}</strong>{gmap.get(p.id) && <span className={`status-chip st-${gmap.get(p.id)!.status}`}>{statusText(gmap.get(p.id))}</span>}</span>
                      <span className="muted small">{fmtHa(p.area_ha)}{p.excluded_ha > 0 ? ` · pasto ${fmtHa(p.pasture_ha)}` : ''}{p.water_m != null ? (p.water_m === 0 ? ' · água no piquete' : ` · água a ${p.water_m.toLocaleString('pt-BR')} m`) : ''}{colorBy ? ` · NDVI ${fmtNdvi(v ?? null)}` : ''}</span>
                    </button>
                  )}
                  {p.id === selected && renaming?.id !== p.id && !editing && !drawing && (
                    <span className="row small paddock-cuts">
                      <button className="link" disabled={cut.isPending} onClick={() => { cut.reset(); setCutting(true); setDrawing(true) }}>Recortar mata</button>
                      <button className="link" disabled={cut.isPending} onClick={() => { cut.reset(); cut.mutate({ source: 'car' }) }}>
                        {cut.isPending ? 'Recortando…' : 'Tirar mata do CAR'}
                      </button>
                      {p.excluded_ha > 0 && <button className="link" disabled={clearCuts.isPending} onClick={() => clearCuts.mutate(p.id)}>Desfazer recortes</button>}
                    </span>
                  )}
                  {gmap.get(p.id)?.flag && <p className={`flag flag-${gmap.get(p.id)!.flag!.level}`}>{gmap.get(p.id)!.flag!.text}</p>}
                  {p.id === selected && (gmap.get(p.id)?.history.length ?? 0) > 0 && (
                    <ul className="occ-list" aria-label="Ocupações">
                      {gmap.get(p.id)!.history.map((o, i) => (
                        <li key={i}>{o.lot}: {o.entered_on.split('-').reverse().join('/')} → {o.left_on ? o.left_on.split('-').reverse().join('/') : 'hoje'} · {o.days} d · {o.ua.toLocaleString('pt-BR')} UA</li>
                      ))}
                    </ul>
                  )}
                  {p.id === selected && cut.isError && <p className="notice small">{(cut.error as Error).message}</p>}
                  {p.id === selected && p.excluded_ha > 0 && <p className="muted small">{fmtHa(p.excluded_ha)} de mata/água fora do cálculo de NDVI.</p>}
                  {p.id === selected && renaming?.id !== p.id && (
                    <span className="row small">
                      <button className="link" onClick={() => setRenaming({ id: p.id, name: p.name })}>Renomear</button>
                      <button className="link" disabled={!!editing} onClick={() => startEdit(p.id)}>Editar formato</button>
                      <button className="link danger" onClick={() => { if (confirm(`Excluir o piquete "${p.name}"?`)) remove.mutate(p.id) }}>Excluir</button>
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          {colorBy && <p className="muted small">Ordenados do menor para o maior NDVI: os primeiros pedem atenção.</p>}
          {!colorBy && grazing.data && grazing.data.paddocks.some(g => g.status !== 'sem_registro') && (
            <div className="status-legend small">
              <span className="status-chip st-em_uso">Em uso</span><span className="status-chip st-descanso">Descanso</span>
              <span className="status-chip st-pronto">Pronto ({grazing.data.rest_window[0]}–{grazing.data.rest_window[1]} d)</span>
              <span className="status-chip st-descanso_longo">Descanso longo</span>
            </div>
          )}
          {grazing.data && grazing.data.paddocks.some(g => g.status !== 'sem_registro') && (
            <p className="muted small">{grazing.data.ndvi_date
              ? `Alertas de pasto usam o NDVI da imagem de ${fmtDay(grazing.data.ndvi_date)}. Para atualizar: Última imagem › Colorir por NDVI.`
              : 'Para ver os alertas de pasto (lotação × NDVI), use Última imagem › Colorir por NDVI.'}</p>
          )}

          {sel && (
            <div className="paddock-detail">
              <p className="small"><strong>{sel.properties.name}</strong>{sel.properties.excluded_ha > 0 ? ' (só pasto)' : ''} × média da fazenda, mês a mês</p>
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
