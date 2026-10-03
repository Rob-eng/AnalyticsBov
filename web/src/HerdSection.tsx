import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, fmtBRL, fmtHa, type Herd, type Lot } from './api'

const today = () => new Date().toLocaleDateString('sv-SE')   // AAAA-MM-DD no fuso local
const fmtDay = (d: string) => d.split('-').reverse().join('/')
const daysSince = (d: string) => Math.max(0, Math.round((Date.parse(today()) - Date.parse(d)) / 86400000))
const fmtNum = (v: number, nd = 0) => v.toLocaleString('pt-BR', { minimumFractionDigits: nd, maximumFractionDigits: nd })

type Form = { name: string; category: string; head_count: string; avg_weight_kg: string }
const EMPTY_FORM: Form = { name: '', category: 'vaca', head_count: '', avg_weight_kg: '' }

export default function HerdSection({ propertyId, active }: { propertyId: number; active: boolean }) {
  const qc = useQueryClient()
  const herd = useQuery({ queryKey: ['herd', propertyId], queryFn: () => api.herd(propertyId), enabled: active })
  const value = useQuery({ queryKey: ['herd-value', propertyId, herd.data?.lots.map(l => `${l.id}:${l.head_count}:${l.avg_weight_kg}:${l.category}`).join(',')],
    queryFn: () => api.herdValue(propertyId), enabled: active && !!herd.data?.lots.length, retry: false })
  const paddocks = useQuery({ queryKey: ['paddocks', propertyId], queryFn: () => api.paddocks(propertyId), enabled: active })
  const [form, setForm] = useState<Form | null>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [moving, setMoving] = useState<{ lot: number; paddock: string; on: string } | null>(null)
  useEffect(() => { setForm(null); setEditing(null); setMoving(null) }, [propertyId])

  const done = (h: Herd | void) => {
    if (h) qc.setQueryData(['herd', propertyId], h)
    qc.invalidateQueries({ queryKey: ['herd', propertyId] })
    qc.invalidateQueries({ queryKey: ['grazing', propertyId] })
  }
  const save = useMutation({
    mutationFn: (f: Form) => {
      const body = { name: f.name.trim(), category: f.category, head_count: Number(f.head_count), avg_weight_kg: f.avg_weight_kg ? Number(f.avg_weight_kg.replace(',', '.')) : null }
      return editing ? api.editLot(propertyId, editing, body) : api.createLot(propertyId, body)
    },
    onSuccess: h => { setForm(null); setEditing(null); done(h) },
  })
  const move = useMutation({
    mutationFn: (m: { lot: number; paddock: string; on: string }) => api.moveLot(propertyId, m.lot, m.paddock ? Number(m.paddock) : null, m.on),
    onSuccess: h => { setMoving(null); done(h) },
  })
  const remove = useMutation({ mutationFn: (lot: number) => api.deleteLot(propertyId, lot), onSuccess: () => done() })

  const h = herd.data
  const cats = h?.categories ?? []
  const pads = paddocks.data?.features ?? []
  const startEdit = (l: Lot) => {
    save.reset(); setMoving(null); setEditing(l.id)
    setForm({ name: l.name, category: l.category, head_count: String(l.head_count), avg_weight_kg: l.avg_weight_kg ? String(l.avg_weight_kg) : '' })
  }

  const formView = form && (
    <form className="draw-help" onSubmit={e => { e.preventDefault(); save.mutate(form) }}>
      <p className="small"><strong>{editing ? 'Editar lote' : 'Novo lote'}</strong></p>
      <label className="field"><span>Nome do lote</span>
        <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} maxLength={60} placeholder="Ex.: Vacas paridas" autoFocus />
      </label>
      <div className="compare">
        <label className="field"><span>Categoria</span>
          <select className="input" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
            {cats.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </label>
        <label className="field"><span>Cabeças</span>
          <input className="input" inputMode="numeric" value={form.head_count} onChange={e => setForm({ ...form, head_count: e.target.value.replace(/\D/g, '') })} />
        </label>
      </div>
      <label className="field"><span>Peso médio (kg, opcional)</span>
        <input className="input" inputMode="decimal" value={form.avg_weight_kg} onChange={e => setForm({ ...form, avg_weight_kg: e.target.value.replace(/[^\d,.]/g, '') })}
          placeholder={`padrão da categoria: ${cats.find(c => c.key === form.category)?.default_weight_kg ?? ''} kg`} />
      </label>
      {save.isError && <p className="notice">{(save.error as Error).message}</p>}
      <div className="row">
        <button className="btn btn-sm" type="submit" disabled={!form.name.trim() || !form.head_count || save.isPending}>{save.isPending ? 'Salvando…' : 'Salvar lote'}</button>
        <button className="link" type="button" onClick={() => { setForm(null); setEditing(null) }}>Cancelar</button>
      </div>
    </form>
  )

  return (
    <div className="block">
      <h3>Rebanho</h3>
      {herd.isPending && <p className="muted">Carregando…</p>}
      {herd.isError && <p className="notice">{(herd.error as Error).message}</p>}
      {h && (
        <>
          {h.lots.length > 0 && (
            <div className="herd-summary">
              <div><strong>{fmtNum(h.summary.heads)}</strong><span>cabeças</span></div>
              <div><strong>{fmtNum(h.summary.ua, 1)}</strong><span>UA</span></div>
              <div><strong>{h.summary.ua_ha != null ? fmtNum(h.summary.ua_ha, 2) : '—'}</strong><span>UA/ha</span></div>
            </div>
          )}
          {h.lots.length > 0 && <p className="muted small">Lotação sobre {h.summary.area_base} ({fmtHa(h.summary.area_ha)}). 1 UA = 450 kg de peso vivo.</p>}
          {value.data && (
            <details className="herd-value">
              <summary>
                <span className="muted small">Valor estimado do rebanho · praça {value.data.uf}</span>
                <strong>{fmtBRL(value.data.total, 0)}</strong>
              </summary>
              <ul className="occ-list">{value.data.lots.map(l => (
                <li key={l.id}><strong>{l.name}</strong>: {l.value ? `${fmtBRL(l.value, 0)} (${fmtBRL(l.per_head, 0)}/cab.)` : '—'}<br /><span>{l.method}</span></li>
              ))}</ul>
              <p className="muted small">{value.data.note}{!value.data.uf_from_property ? ' A UF da fazenda não tem indicador DATAGRO; usada a praça MS.' : ''}</p>
            </details>
          )}
          {value.isError && <p className="notice small">{(value.error as Error).message}</p>}
          {!h.lots.length && !form && <p className="muted">Cadastre os lotes (categoria, cabeças e peso médio) para acompanhar a lotação e a rotação dos piquetes.</p>}
          {!form && <button className="btn btn-sm" onClick={() => { save.reset(); setEditing(null); setForm({ ...EMPTY_FORM }) }}>Novo lote</button>}
          {!editing && formView}

          <ul className="paddock-list lot-list">
            {h.lots.map(l => (
              <li key={l.id} className="paddock">
                {editing === l.id ? formView : (
                  <>
                    <div className="lot-head">
                      <strong>{l.name}</strong>
                      <span className="muted small">{l.category_label} · {fmtNum(l.head_count)} cab. · {fmtNum(l.ua, 1)} UA{l.avg_weight_kg ? ` · ${fmtNum(l.avg_weight_kg)} kg` : ''}</span>
                      <span className="small">{l.paddock_name
                        ? <>No {l.paddock_name}{l.since ? ` desde ${fmtDay(l.since)} (${daysSince(l.since)} d)` : ''}</>
                        : <span className="muted">Sem piquete</span>}</span>
                    </div>
                    {moving?.lot === l.id ? (
                      <form className="move-form" onSubmit={e => { e.preventDefault(); move.mutate(moving) }}>
                        <select className="input input-sm" value={moving.paddock} onChange={e => setMoving({ ...moving, paddock: e.target.value })} aria-label="Piquete de destino">
                          <option value="">Saiu (sem piquete)</option>
                          {pads.filter(p => p.properties.id !== l.paddock_id).map(p => <option key={p.properties.id} value={p.properties.id}>{p.properties.name}</option>)}
                        </select>
                        <input className="input input-sm" type="date" value={moving.on} max={today()} onChange={e => setMoving({ ...moving, on: e.target.value })} aria-label="Data" />
                        <button className="btn btn-sm" type="submit" disabled={move.isPending || (!moving.paddock && !l.paddock_id)}>{move.isPending ? '…' : 'Confirmar'}</button>
                        <button className="link small" type="button" onClick={() => setMoving(null)}>Cancelar</button>
                        {move.isError && <p className="notice small">{(move.error as Error).message}</p>}
                      </form>
                    ) : (
                      <span className="row small">
                        <button className="link" disabled={!pads.length} title={pads.length ? '' : 'Desenhe os piquetes primeiro'}
                          onClick={() => { move.reset(); setForm(null); setEditing(null); setMoving({ lot: l.id, paddock: String(pads.find(p => p.properties.id !== l.paddock_id)?.properties.id ?? ''), on: today() }) }}>
                          {l.paddock_id ? 'Mudar de piquete' : 'Colocar em piquete'}
                        </button>
                        <button className="link" onClick={() => startEdit(l)}>Editar</button>
                        <button className="link danger" onClick={() => { if (confirm(`Excluir o lote "${l.name}"? O histórico de ocupação dele também sai.`)) remove.mutate(l.id) }}>Excluir</button>
                      </span>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
          {h.lots.length > 0 && !pads.length && <p className="muted small">Desenhe os piquetes (aba Piquetes) para registrar a rotação dos lotes.</p>}
        </>
      )}
    </div>
  )
}
