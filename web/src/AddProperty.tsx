import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { api, fmtHa } from './api'

type Pick = { active: boolean; point: { lat: number; lon: number } | null }
const CAR_RE = /^[A-Z]{2}-\d{7}-[A-F0-9]{32}$/

// Cadastro: pelo código do CAR ou clicando na fazenda no mapa (com sobreposição, o usuário escolhe o imóvel)
export default function AddProperty({ pick, setPick }: { pick: Pick; setPick: (p: Pick) => void }) {
  const [tab, setTab] = useState<'mapa' | 'codigo'>('mapa')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)
  const qc = useQueryClient()
  const navigate = useNavigate()

  useEffect(() => {
    setPick({ active: tab === 'mapa', point: null })
    return () => setPick({ active: false, point: null })
  }, [tab, setPick])

  const lookup = useQuery({
    queryKey: ['car-lookup', pick.point?.lat, pick.point?.lon],
    queryFn: () => api.carLookup(pick.point!.lat, pick.point!.lon),
    enabled: tab === 'mapa' && !!pick.point,
  })
  const candidates = lookup.data?.candidates ?? []
  useEffect(() => { setChosen(candidates.length ? candidates[0].car_code : null) }, [lookup.data])  // eslint-disable-line

  const create = useMutation({
    mutationFn: () => api.createProperty(tab === 'codigo'
      ? { name, car_code: code.trim().toUpperCase() }
      : { name, car_code: chosen ?? undefined, lat: pick.point?.lat, lon: pick.point?.lon }),
    onSuccess: p => { qc.invalidateQueries({ queryKey: ['properties'] }); navigate(`/p/${p.id}`) },
  })

  const codeOk = CAR_RE.test(code.trim().toUpperCase())
  const canSave = name.trim().length > 0 && (tab === 'codigo' ? codeOk : !!chosen)

  return (
    <section className="panel">
      <div className="panel-title">
        <h2>Adicionar propriedade</h2>
        <Link className="link" to="/">Cancelar</Link>
      </div>

      <div className="mode" role="tablist" aria-label="Como encontrar a propriedade">
        <button role="tab" aria-selected={tab === 'mapa'} onClick={() => setTab('mapa')}>Clicar no mapa</button>
        <button role="tab" aria-selected={tab === 'codigo'} onClick={() => setTab('codigo')}>Código do CAR</button>
      </div>

      {tab === 'mapa' ? (
        <div className="field-group">
          {!pick.point && <p className="muted">Aproxime o mapa e clique dentro da fazenda. Mostramos o imóvel do CAR que contém o ponto.</p>}
          {lookup.isFetching && <p className="muted">Procurando o imóvel no CAR…</p>}
          {lookup.isError && <p className="notice">{(lookup.error as Error).message}</p>}
          {lookup.isSuccess && !candidates.length && <p className="notice">Nenhum imóvel do CAR neste ponto. Clique em outro lugar ou use o código.</p>}
          {candidates.length > 1 && <p className="muted">Há {candidates.length} imóveis sobrepostos neste ponto. Escolha o seu:</p>}
          {candidates.map(c => (
            <label key={c.car_code} className={'candidate' + (chosen === c.car_code ? ' candidate-on' : '')}>
              <input type="radio" name="car" checked={chosen === c.car_code} onChange={() => setChosen(c.car_code)} />
              <span>
                <span className="candidate-area">{fmtHa(c.area_ha)}</span>
                <span className="muted"> · {c.municipio}/{c.uf}</span>
                <span className="mono">{c.car_code}</span>
              </span>
            </label>
          ))}
        </div>
      ) : (
        <label className="field">
          <span>Código do CAR</span>
          <input className="input mono" value={code} onChange={e => setCode(e.target.value)} placeholder="MS-5001102-F4C226D6…" spellCheck={false} />
          {code && !codeOk && <span className="field-hint">Formato: UF-0000000-seguido de 32 letras/números</span>}
        </label>
      )}

      <label className="field">
        <span>Nome da propriedade</span>
        <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="Ex.: Faz Santa Fé" maxLength={80} />
      </label>

      {create.isError && <p className="notice">{(create.error as Error).message}</p>}
      <button className="btn" disabled={!canSave || create.isPending} onClick={() => create.mutate()}>
        {create.isPending ? 'Buscando as camadas do CAR…' : 'Adicionar propriedade'}
      </button>
    </section>
  )
}
