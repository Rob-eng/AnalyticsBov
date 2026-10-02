import { useQuery } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router'
import { api, ApiError } from './api'
import Login from './Login'
import Workspace from './Workspace'

export default function App() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })

  if (me.isPending) return <div className="splash" aria-busy="true">Carregando…</div>
  if (me.error instanceof ApiError && me.error.status === 401) return <Login onLoggedIn={() => me.refetch()} />
  if (me.error) return (
    <div className="splash">
      <p>Não foi possível conectar ao servidor ({me.error.message}).</p>
      <button className="btn" onClick={() => me.refetch()}>Tentar de novo</button>
    </div>
  )
  return (
    <BrowserRouter basename="/app">
      <Workspace me={me.data} />
    </BrowserRouter>
  )
}
