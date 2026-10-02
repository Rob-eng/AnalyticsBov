// Ícones de traço (24×24, stroke = currentColor) — mesmo desenho do boizinho dos piquetes.
const P: Record<string, string> = {
  sede: '<path d="M4 11 12 4l8 7"/><path d="M6 10v9h12v-9"/><path d="M10 19v-5h4v5"/>',
  curral: '<path d="M4 6v13M12 6v13M20 6v13"/><path d="M4 10h16M4 15h16"/>',
  galpao: '<path d="M3 10 12 5l9 5v9H3z"/><path d="M8 19v-6h8v6"/>',
  aguada: '<path d="M12 4c3 4 5 6.5 5 9a5 5 0 0 1-10 0c0-2.5 2-5 5-9z"/>',
  bebedouro: '<path d="M4 13h16l-2 5H6z"/><path d="M12 4c1.6 2 2.5 3.2 2.5 4.3a2.5 2.5 0 0 1-5 0C9.5 7.2 10.4 6 12 4z"/>',
  cocho: '<path d="M3 10h18l-3 6H6z"/><path d="M7 16v3M17 16v3"/>',
  poco: '<ellipse cx="12" cy="6" rx="6" ry="2.2"/><path d="M6 6v11c0 1.2 2.7 2.2 6 2.2s6-1 6-2.2V6"/>',
  porteira: '<path d="M4 5v15M20 5v15"/><path d="M4 8h16M4 16h16M4 16 20 8"/>',
  nota: '<path d="M12 21s-6-5.4-6-10a6 6 0 0 1 12 0c0 4.6-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>',
  cerca: '<path d="M3 17h18M3 11h18"/><path d="M6 7v13M12 7v13M18 7v13"/>',
  estrada: '<path d="M8 20 10 4M16 20 14 4"/><path d="M12 6v2M12 11v2M12 16v2"/>',
  rede_agua: '<path d="M3 12h7a3 3 0 0 0 3-3V5"/><path d="M13 12h8"/><path d="M17 15c1 1.3 1.5 2.2 1.5 3a1.5 1.5 0 0 1-3 0c0-.8.5-1.7 1.5-3z"/>',
}

export const WATER_KINDS = ['aguada', 'bebedouro', 'poco', 'rede_agua']

export function iconSvg(kind: string, size = 16, cls = 'ico'): string {
  return `<svg class="${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${P[kind] ?? P.nota}</svg>`
}

// cor da linha no mapa por tipo
export const LINE_COLORS: Record<string, string> = { cerca: '#F2EEE3', estrada: '#C9A26B', rede_agua: '#4FA3E0' }
