import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Improvements } from './api'
import { iconSvg } from './icons'

export type ImprovementLayer = {
  fc: Improvements | null; selected: number | null
  drawing: boolean; mode: 'point' | 'linestring'
  onDrawn: (g: GeoJSON.Geometry) => void; onClick: (id: number) => void
}
type Props = { propertyId: number; active: boolean; busy: boolean; onLayer: (l: ImprovementLayer | null) => void }

const Icon = ({ kind, size = 16 }: { kind: string; size?: number }) => <span className="ico-wrap" dangerouslySetInnerHTML={{ __html: iconSvg(kind, size) }} />
const fmtM = (m: number) => m >= 1000 ? `${(m / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} km` : `${m.toLocaleString('pt-BR')} m`

export default function ImprovementsSection({ propertyId, active, busy, onLayer }: Props) {
  const qc = useQueryClient()
  const key = ['improvements', propertyId]
  const list = useQuery({ queryKey: key, queryFn: () => api.improvements(propertyId), enabled: active })
  const [picking, setPicking] = useState(false)             // escolhendo o tipo
  const [kind, setKind] = useState<string | null>(null)       // desenhando este tipo
  const [pending, setPending] = useState<GeoJSON.Geometry | null>(null)
  const [form, setForm] = useState({ name: '', notes: '' })
  const [selected, setSelected] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  useEffect(() => { setPicking(false); setKind(null); setPending(null); setSelected(null) }, [propertyId])
  useEffect(() => { if (!active) { setKind(null); setPending(null); setPicking(false) } }, [active])

  const kinds = list.data?.kinds ?? []
  const kindInfo = (k: string | null) => kinds.find(x => x.key === k)
  const feats = useMemo(() => list.data?.features ?? [], [list.data])
  const refresh = () => { qc.invalidateQueries({ queryKey: key }); qc.invalidateQueries({ queryKey: ['paddocks', propertyId] }) }

  const save = useMutation({
    mutationFn: () => api.createImprovement(propertyId, { kind: kind!, geometry: pending!, name: form.name, notes: form.notes }),
    onSuccess: () => { setKind(null); setPending(null); setForm({ name: '', notes: '' }); refresh() },
  })
  const edit = useMutation({
    mutationFn: () => api.editImprovement(propertyId, selected!, form),
    onSuccess: () => { setEditing(false); refresh() },
  })
  const remove = useMutation({ mutationFn: (id: number) => api.deleteImprovement(propertyId, id), onSuccess: () => { setSelected(null); refresh() } })

  // pendente aparece no mapa junto com os salvos
  const fc = useMemo<Improvements | null>(() => {
    if (!active || !list.data) return null
    const extra = pending && kind ? [{ type: 'Feature' as const, id: -1, geometry: pending as GeoJSON.Point | GeoJSON.LineString,
      properties: { id: -1, kind, kind_label: kindInfo(kind)?.label ?? kind, name: form.name || null, notes: null, length_m: null } }] : []
    return { ...list.data, features: [...feats, ...extra] }
  }, [active, list.data, feats, pending, kind, form.name])   // eslint-disable-line

  const drawing = !!kind && !pending
  useEffect(() => {
    onLayer(active ? {
      fc, selected, drawing, mode: kindInfo(kind)?.geometry === 'LineString' ? 'linestring' : 'point',
      onDrawn: g => setPending(g),
      onClick: id => { setEditing(false); setSelected(s => (s === id ? null : id)) },
    } : null)
  }, [active, fc, selected, drawing, kind, onLayer])   // eslint-disable-line
  useEffect(() => () => onLayer(null), [onLayer])

  const sel = feats.find(f => f.properties.id === selected) ?? null
  const groups = useMemo(() => {
    const g = new Map<string, typeof feats>()
    feats.forEach(f => g.set(f.properties.kind, [...(g.get(f.properties.kind) ?? []), f]))
    return [...g.entries()]
  }, [feats])

  return (
    <div className="block">
      <h3>Benfeitorias e água</h3>
      {list.isSuccess && !feats.length && !picking && !kind && (
        <p className="muted">Marque sede, currais, aguadas, bebedouros, cochos, porteiras, cercas e estradas. As aguadas e bebedouros entram na distância até a água de cada piquete.</p>
      )}
      {!picking && !kind && (
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => { setSelected(null); setPicking(true) }}>Adicionar no mapa</button>
      )}
      {picking && (
        <div className="draw-help">
          <p className="small">O que você vai marcar?</p>
          <div className="kind-grid">
            {kinds.map(k => (
              <button key={k.key} className={'kind-btn' + (k.water ? ' kind-water' : '')} onClick={() => { setPicking(false); save.reset(); setForm({ name: '', notes: '' }); setKind(k.key) }}>
                <Icon kind={k.key} size={18} /><span>{k.label}</span>
              </button>
            ))}
          </div>
          <button className="link" onClick={() => setPicking(false)}>Cancelar</button>
        </div>
      )}
      {drawing && (
        <div className="draw-help">
          <p className="small"><strong>{kindInfo(kind)?.label}</strong>: {kindInfo(kind)?.geometry === 'LineString'
            ? 'clique no mapa para traçar a linha. Para terminar, clique de novo no último ponto.'
            : 'clique no mapa onde fica.'}</p>
          <button className="link" onClick={() => setKind(null)}>Cancelar</button>
        </div>
      )}
      {pending && kind && (
        <form className="draw-help" onSubmit={e => { e.preventDefault(); save.mutate() }}>
          <p className="small"><Icon kind={kind} /> <strong>{kindInfo(kind)?.label}</strong></p>
          <label className="field"><span>Nome (opcional)</span>
            <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} maxLength={60} autoFocus
              placeholder={kind === 'nota' ? 'Ex.: erosão na grota' : 'Ex.: Curral da sede'} />
          </label>
          <label className="field"><span>Observação (opcional)</span>
            <textarea className="input" rows={2} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} maxLength={500} />
          </label>
          {save.isError && <p className="notice">{(save.error as Error).message}</p>}
          <div className="row">
            <button className="btn btn-sm" type="submit" disabled={save.isPending}>{save.isPending ? 'Salvando…' : 'Salvar'}</button>
            <button className="link" type="button" onClick={() => { setPending(null); setKind(null) }}>Descartar</button>
          </div>
        </form>
      )}

      {groups.length > 0 && (
        <ul className="imp-list">
          {groups.map(([k, items]) => items.map(f => {
            const p = f.properties
            const on = p.id === selected
            return (
              <li key={p.id} className={on ? 'imp-row imp-row-on' : 'imp-row'}>
                <button className="imp-main" onClick={() => { setEditing(false); setSelected(on ? null : p.id) }}>
                  <span className={'imp-dot ' + (kindInfo(k)?.water ? 'imp-water' : k === 'nota' ? 'imp-note' : 'imp-struct')}><Icon kind={k} size={13} /></span>
                  <span><strong>{p.name || p.kind_label}</strong>
                    <span className="muted small">{p.name ? ` · ${p.kind_label}` : ''}{p.length_m ? ` · ${fmtM(p.length_m)}` : ''}</span></span>
                </button>
                {on && sel && !editing && (
                  <>
                    {p.notes && <p className="small">{p.notes}</p>}
                    <span className="row small">
                      <button className="link" onClick={() => { edit.reset(); setForm({ name: p.name ?? '', notes: p.notes ?? '' }); setEditing(true) }}>Editar</button>
                      <button className="link danger" onClick={() => { if (confirm(`Excluir "${p.name || p.kind_label}"?`)) remove.mutate(p.id) }}>Excluir</button>
                    </span>
                  </>
                )}
                {on && editing && (
                  <form className="draw-help" onSubmit={e => { e.preventDefault(); edit.mutate() }}>
                    <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} maxLength={60} placeholder="Nome" aria-label="Nome" />
                    <textarea className="input" rows={2} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} maxLength={500} placeholder="Observação" aria-label="Observação" />
                    {edit.isError && <p className="notice">{(edit.error as Error).message}</p>}
                    <div className="row">
                      <button className="btn btn-sm" type="submit" disabled={edit.isPending}>Salvar</button>
                      <button className="link" type="button" onClick={() => setEditing(false)}>Cancelar</button>
                    </div>
                  </form>
                )}
              </li>
            )
          }))}
        </ul>
      )}
    </div>
  )
}
