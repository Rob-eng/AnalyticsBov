import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, fmtHa, type ProdesList } from './api'

type Props = { propertyId: number; onLayer: (fc: ProdesList | null, selected: Set<string>) => void }
const STATUS: Record<string, string> = { PENDING: 'na fila', PROCESSING: 'processando', DONE: 'pronto', ERROR: 'erro' }

export default function ProdesSection({ propertyId, onLayer }: Props) {
  const qc = useQueryClient()
  const [enabled, setEnabled] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const list = useQuery({ queryKey: ['prodes', propertyId], queryFn: () => api.prodes(propertyId), enabled })
  const jobs = useQuery({
    queryKey: ['prodes-jobs', propertyId], queryFn: () => api.prodesJobs(propertyId),
    refetchInterval: q => (q.state.data ?? []).some(j => j.status === 'PENDING' || j.status === 'PROCESSING') ? 8000 : false,
  })
  const report = useMutation({
    mutationFn: () => api.prodesReport(propertyId, [...selected]),
    onSuccess: () => { setSelected(new Set()); qc.invalidateQueries({ queryKey: ['prodes-jobs', propertyId] }) },
  })
  const fc = list.data?.result

  useEffect(() => { setEnabled(false); setSelected(new Set()) }, [propertyId])
  useEffect(() => { onLayer(fc ?? null, selected) }, [fc, selected, onLayer])
  useEffect(() => () => onLayer(null, new Set()), [onLayer])

  const toggle = (uuid: string) => setSelected(s => { const n = new Set(s); if (n.has(uuid)) n.delete(uuid); else n.add(uuid); return n })
  // mais recentes primeiro (o que vem depois de 2008 é o que pesa no laudo), depois os maiores
  const feats = [...(fc?.features ?? [])].sort((a, b) =>
    (b.properties.year ?? 0) - (a.properties.year ?? 0) || b.properties.area_intersect_ha - a.properties.area_intersect_ha)

  return (
    <div className="block">
      <h3>Desmatamento (PRODES/INPE)</h3>
      {!enabled && (
        <>
          <p className="muted">Apontamentos de desmatamento do INPE que cruzam o perímetro, com laudo técnico em PDF.</p>
          <button className="btn btn-sm" onClick={() => setEnabled(true)}>Consultar PRODES</button>
        </>
      )}
      {list.isFetching && <p className="muted">Consultando a base do INPE…</p>}
      {list.isError && <p className="notice">{(list.error as Error).message}</p>}
      {list.isSuccess && !feats.length && <p className="ok">Nenhum apontamento PRODES cruza este imóvel.</p>}
      {feats.length > 0 && (
        <>
          <p className="muted small">{feats.length} apontamento{feats.length > 1 ? 's' : ''} · <span className="dot dot-blue" /> até 2008 · <span className="dot dot-red" /> após 2008. Marque para gerar o laudo.</p>
          <ul className="prodes-list">
            {feats.map(f => (
              <li key={f.properties.uuid}>
                <label className={'candidate' + (selected.has(f.properties.uuid) ? ' candidate-on' : '')}>
                  <input type="checkbox" checked={selected.has(f.properties.uuid)} onChange={() => toggle(f.properties.uuid)} />
                  <span>
                    <span className="candidate-area">{f.properties.class_name}</span>
                    <span className="muted"> · {fmtHa(f.properties.area_intersect_ha)} no imóvel</span>
                    {f.properties.image_date && <span className="muted small"> · imagem {f.properties.image_date.split('-').reverse().join('/')}</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {report.isError && <p className="notice">{(report.error as Error).message}</p>}
          <button className="btn btn-sm" disabled={!selected.size || report.isPending} onClick={() => report.mutate()}>
            {report.isPending ? 'Enviando…' : `Gerar laudo${selected.size > 1 ? 's' : ''} (${selected.size})`}
          </button>
        </>
      )}

      {(jobs.data ?? []).length > 0 && (
        <div className="jobs">
          <p className="muted small">Laudos desta propriedade</p>
          {jobs.data!.map(j => (
            <div key={j.id} className="job">
              <span><strong>{j.class_name}</strong> · {STATUS[j.status] ?? j.status}</span>
              {j.status === 'DONE' && (
                <span className="row">
                  {j.files.pdf && <a className="link" href={`${j.files.pdf}?download=true`}>PDF</a>}
                  {j.files.antes && <a className="link" href={j.files.antes} target="_blank" rel="noreferrer">antes</a>}
                  {j.files.depois && <a className="link" href={j.files.depois} target="_blank" rel="noreferrer">depois</a>}
                </span>
              )}
              {j.status === 'ERROR' && <span className="small muted">{j.error}</span>}
              {(j.status === 'PENDING' || j.status === 'PROCESSING') && <span className="small muted">≈2–5 min</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
