import { useEffect, useRef, useState } from 'react'
import { api, type LoginStart } from './api'
import MapView from './MapView'

// Login pelo bot: o código vai no "brinco"; o usuário envia ao WhatsApp/Telegram e o navegador entra sozinho.
export default function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [login, setLogin] = useState<LoginStart | null>(null)
  const [status, setStatus] = useState<'idle' | 'waiting' | 'expired' | 'error'>('idle')
  const timer = useRef<number | undefined>(undefined)

  async function start() {
    window.clearInterval(timer.current)
    try {
      setLogin(await api.loginStart())
      setStatus('waiting')
    } catch {
      setStatus('error')
    }
  }

  useEffect(() => { start() }, [])

  useEffect(() => {
    if (status !== 'waiting' || !login) return
    timer.current = window.setInterval(async () => {
      try {
        const r = await api.loginPoll(login.code)
        if (r.status === 'ok') { window.clearInterval(timer.current); onLoggedIn() }
        if (r.status === 'expired') { window.clearInterval(timer.current); setStatus('expired') }
      } catch { /* rede instável: tenta no próximo ciclo */ }
    }, 2000)
    return () => window.clearInterval(timer.current)
  }, [status, login, onLoggedIn])

  return (
    <div className="login">
      <div className="login-map" aria-hidden="true"><MapView properties={[]} interactive={false} /></div>
      <main className="login-card">
        <p className="brand">Agro Analytics</p>
        <h1>Suas fazendas no mapa, do satélite ao piquete.</h1>
        <p className="lead">Entre com o mesmo WhatsApp ou Telegram que você usa no bot. Sem senha.</p>

        {status === 'error' && <p className="notice">Não foi possível gerar o código de acesso. <button className="link" onClick={start}>Gerar de novo</button></p>}
        {status === 'expired' && <p className="notice">O código expirou. <button className="link" onClick={start}>Gerar um novo código</button></p>}

        {login && status === 'waiting' && (
          <>
            <div className="tag" aria-label={`Código de acesso ${login.code}`}>
              <span className="tag-hole" aria-hidden="true" />
              <span className="tag-code">{login.code}</span>
              <span className="tag-caption">válido por 10 minutos</span>
            </div>
            <ol className="steps">
              <li>Toque no botão do seu aplicativo — a mensagem já vai pronta.</li>
              <li>Envie a mensagem ao bot.</li>
              <li>Esta página entra sozinha.</li>
            </ol>
            <div className="actions">
              {login.whatsapp_url && <a className="btn btn-wa" href={login.whatsapp_url} target="_blank" rel="noreferrer">Entrar pelo WhatsApp</a>}
              <a className="btn btn-tg" href={login.telegram_url} target="_blank" rel="noreferrer">Entrar pelo Telegram</a>
            </div>
            <p className="waiting" role="status">Aguardando a confirmação do bot…</p>
          </>
        )}
      </main>
    </div>
  )
}
