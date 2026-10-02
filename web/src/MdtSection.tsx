import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from './api'

export default function MdtSection({ propertyId }: { propertyId: number }) {
  const map2d = useMutation({ mutationFn: () => api.mdt(propertyId, '2d') })
  const video3d = useMutation({ mutationFn: () => api.mdt(propertyId, '3d') })
  useEffect(() => { map2d.reset(); video3d.reset() }, [propertyId])   // eslint-disable-line
  const info = map2d.data?.result ?? video3d.data?.result

  return (
    <div className="block">
      <h3>Relevo (MDT)</h3>
      <p className="muted">Curvas de nível e modelo 3D do terreno sobre o perímetro.</p>
      {info && <p className="small">Altitude de <strong>{Math.round(info.elev_min)} m</strong> a <strong>{Math.round(info.elev_max)} m</strong> · fonte {info.source}</p>}
      <div className="row">
        <button className="btn btn-sm" disabled={map2d.isPending} onClick={() => map2d.mutate()}>
          {map2d.isPending ? 'Gerando curvas…' : 'Curvas de nível'}
        </button>
        <button className="btn btn-sm btn-ghost" disabled={video3d.isPending} onClick={() => video3d.mutate()}>
          {video3d.isPending ? 'Renderizando 3D (≈1 min)…' : 'Modelo 3D (vídeo)'}
        </button>
      </div>
      {map2d.isError && <p className="notice">{(map2d.error as Error).message}</p>}
      {video3d.isError && <p className="notice">{(video3d.error as Error).message}</p>}
      {map2d.data?.file_url && (
        <a className="media" href={map2d.data.file_url} target="_blank" rel="noreferrer" title="Abrir em tamanho cheio">
          <img src={map2d.data.file_url} alt="Mapa de curvas de nível da propriedade" />
        </a>
      )}
      {video3d.data?.file_url && (
        <video className="media" src={video3d.data.file_url} controls autoPlay muted loop playsInline aria-label="Modelo 3D do terreno" />
      )}
    </div>
  )
}
