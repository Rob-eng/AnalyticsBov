import { useQuery } from '@tanstack/react-query'
import { api } from './api'

const fmtWhen = (iso: string) => new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
const openLabel = (t: string | null) => t?.startsWith('video') ? 'Ver vídeo' : t === 'application/pdf' ? 'Baixar PDF' : 'Ver imagem'

export default function HistorySection({ propertyId, active }: { propertyId: number; active: boolean }) {
  const h = useQuery({ queryKey: ['history', propertyId], queryFn: () => api.history(propertyId), enabled: active, refetchOnMount: 'always' })
  const items = h.data ?? []

  return (
    <div className="block">
      <h3>Histórico</h3>
      <p className="muted small">Tudo o que já foi gerado para esta propriedade, do mais recente ao mais antigo.</p>
      {h.isPending && <p className="muted">Carregando…</p>}
      {h.isError && <p className="notice">{(h.error as Error).message}</p>}
      {h.isSuccess && !items.length && <p className="muted">Nada gerado ainda. As análises da aba ao lado ficam guardadas aqui.</p>}
      <ul className="history">
        {items.map(it => (
          <li key={it.id}>
            <div>
              <strong>{it.title}</strong>
              {it.detail && <span className="muted"> · {it.detail}</span>}
              <span className="small muted history-when">{fmtWhen(it.created_at)}</span>
            </div>
            {it.file_url && (
              <a className="link small" href={it.file_url} target="_blank" rel="noreferrer">
                {openLabel(it.file_type)}
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
