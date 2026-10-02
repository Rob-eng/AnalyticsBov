import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, type Analysis } from './api'

type Relief = Analysis<{ elev_min: number; elev_max: number; source: string }>
const ready = (d: unknown): d is Relief => !!d && !('status' in (d as object))

export default function MdtSection({ propertyId }: { propertyId: number }) {
  const map2d = useMutation({ mutationFn: () => api.mdt(propertyId, '2d') })
  // o vídeo 3D renderiza no servidor por alguns minutos: a consulta se repete até ele ficar pronto
  const [want3d, setWant3d] = useState(false)
  const video3d = useQuery({
    queryKey: ['mdt3d', propertyId], queryFn: () => api.mdt(propertyId, '3d'), enabled: want3d, retry: false,
    refetchInterval: q => (q.state.data && !ready(q.state.data) ? 10000 : false),
  })
  useEffect(() => { map2d.reset(); setWant3d(false) }, [propertyId])   // eslint-disable-line
  const map = ready(map2d.data) ? map2d.data : null
  const video = ready(video3d.data) ? video3d.data : null
  const rendering = want3d && !video && !video3d.isError
  const info = map?.result ?? video?.result

  return (
    <div className="block">
      <h3>Relevo (MDT)</h3>
      <p className="muted">Curvas de nível e modelo 3D do terreno sobre o perímetro.</p>
      {info && <p className="small">Altitude de <strong>{Math.round(info.elev_min)} m</strong> a <strong>{Math.round(info.elev_max)} m</strong> · fonte {info.source}</p>}
      <div className="row">
        <button className="btn btn-sm" disabled={map2d.isPending} onClick={() => map2d.mutate()}>
          {map2d.isPending ? 'Gerando curvas…' : 'Curvas de nível'}
        </button>
        <button className="btn btn-sm btn-ghost" disabled={rendering} onClick={() => { if (video3d.isError) video3d.refetch(); setWant3d(true) }}>
          {rendering ? 'Renderizando 3D (até 5 min)…' : 'Modelo 3D (vídeo)'}
        </button>
      </div>
      {map2d.isError && <p className="notice">{(map2d.error as Error).message}</p>}
      {video3d.isError && <p className="notice">{(video3d.error as Error).message}</p>}
      {map?.file_url && (
        <a className="media" href={map.file_url} target="_blank" rel="noreferrer" title="Abrir em tamanho cheio">
          <img src={map.file_url} alt="Mapa de curvas de nível da propriedade" />
        </a>
      )}
      {video?.file_url && (
        <video className="media" src={video.file_url} controls autoPlay muted loop playsInline aria-label="Modelo 3D do terreno" />
      )}
    </div>
  )
}
