// Teste de ponta a ponta da plataforma web (Playwright).
//   BASE=http://localhost:8765 SESSION=<cookie ab_session> SHOTS=/tmp node e2e/smoke.mjs
// Fluxo: lista → adicionar clicando no mapa → página da propriedade (camadas, quadro,
// NDVI, liga/desliga) → excluir. Sai com código 1 se algum passo falhar.
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://localhost:8765'
const SHOTS = process.env.SHOTS
const POINT = { lat: -20.7434821, lon: -56.0462618 }   // Faz Boa Esperança (Anastácio/MS)
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await ctx.addCookies([{ name: 'ab_session', value: process.env.SESSION, domain: new URL(BASE).hostname, path: '/' }])
const page = await ctx.newPage()
const errors = []
page.on('pageerror', e => errors.push(e.message))
const step = async (name, fn) => {
  try { await fn(); console.log('✅', name) }
  catch (e) { console.log('❌', name, '—', e.message.split('\n')[0]); if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e_fail.png` }); await browser.close(); process.exit(1) }
}

await step('abre a lista de propriedades', async () => {
  await page.goto(`${BASE}/app/`, { waitUntil: 'networkidle' })
  await page.getByRole('link', { name: 'Adicionar' }).waitFor()
})
await step('adiciona clicando no mapa', async () => {
  await page.getByRole('link', { name: 'Adicionar' }).click()
  await page.getByText('Clique dentro da fazenda no mapa').waitFor()
  // centraliza o mapa no ponto e clica no centro
  const box = await page.locator('.stage').boundingBox()
  await page.evaluate(({ lat, lon }) => window.dispatchEvent(new CustomEvent('qa-fly', { detail: { lat, lon } })), POINT)
  await page.waitForTimeout(1500)
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await page.getByText('MS-5000708-AE35133B3D504DECAC0E8C4F6A8DCF1D').waitFor({ timeout: 30000 })
  await page.getByLabel('Nome da propriedade').fill('QA Boa Esperança')
  await page.getByRole('button', { name: 'Adicionar propriedade' }).click()
  await page.getByRole('heading', { name: 'QA Boa Esperança' }).waitFor({ timeout: 60000 })
})
await step('mostra camadas e quadro de áreas', async () => {
  await page.getByText('Reserva Legal').waitFor({ timeout: 30000 })
  await page.getByText('Sem classificação no CAR').waitFor()
  await page.waitForTimeout(1500)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e_property.png` })
})
await step('desliga e liga uma camada', async () => {
  const cb = page.getByRole('checkbox', { name: /Área antropizada/ })
  await cb.uncheck(); await cb.check()
})
await step('mostra o histórico de NDVI', async () => {
  await page.getByRole('button', { name: 'Ver histórico' }).click()
  await page.getByRole('img', { name: 'NDVI médio mensal sobre o perímetro' }).waitFor({ timeout: 120000 })
})
await step('compara dois meses e mostra no mapa', async () => {
  await page.getByRole('button', { name: 'Comparar' }).click()
  await page.locator('.thumb').nth(1).waitFor({ timeout: 180000 })
  await page.waitForFunction(() => [...document.querySelectorAll('.thumb img')].every(i => i.complete && i.naturalWidth > 0), null, { timeout: 30000 })
  await page.locator('.thumb').nth(1).click()
  await page.getByText(/No mapa: NDVI/).waitFor()
  await page.waitForTimeout(2000)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e_ndvi.png` })
})
await step('exclui a propriedade', async () => {
  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Excluir propriedade' }).click()
  await page.getByRole('link', { name: 'Adicionar' }).waitFor()
  for (let i = 0; i < 30 && await page.getByText('QA Boa Esperança').count(); i++) await page.waitForTimeout(500)
  if (await page.getByText('QA Boa Esperança').count()) throw new Error('propriedade continua na lista')
})
if (errors.length) { console.log('❌ erros de JavaScript na página:', errors); process.exit(1) }
console.log('✅ fluxo completo OK')
await browser.close()
