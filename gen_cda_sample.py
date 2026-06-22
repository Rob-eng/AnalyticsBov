"""
Gera uma amostra do grafico CDA com dados sinteticos realistas.
Salva na pasta raiz do projeto: cda_sample_chart.png
Execute com: python gen_cda_sample.py
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# ── 1. Dados sinteticos ───────────────────────────────────────────────────────
np.random.seed(42)
start = datetime(2025, 6, 15)
dates = [start + timedelta(days=i) for i in range(0, 365, 7)]

RACES = {
    'Nelore':          {'base': 205, 'vol': 18, 'gain': 22, 'lots': 40},
    'Cruzado':         {'base': 195, 'vol': 15, 'gain': 18, 'lots': 30},
    'Angus / Bran.':   {'base': 222, 'vol': 20, 'gain': 28, 'lots': 20},
    'Brahman':         {'base': 188, 'vol': 12, 'gain': 14, 'lots': 15},
    'Outros':          {'base': 178, 'vol': 22, 'gain': 10, 'lots': 12},
}

records = []
for i, dt in enumerate(dates):
    frac = i / len(dates)
    for race, p in RACES.items():
        seasonal = 10 * np.sin(2 * np.pi * frac * 2)
        price = p['base'] + p['gain'] * frac + seasonal + np.random.normal(0, p['vol'] * 0.5)
        lots = max(3, int(np.random.normal(p['lots'], p['lots'] * 0.3)))
        records.append({'date': dt, 'race': race, 'price_arroba': price, 'lots': lots})

df = pd.DataFrame(records)

# Scot Brasil USD (eixo secundario)
scot = []
for i, dt in enumerate(dates):
    frac = i / len(dates)
    scot.append({'date': dt, 'price_usd': 74 + 8 * frac + 4 * np.sin(2 * np.pi * frac * 3) + np.random.normal(0, 1)})
df_scot = pd.DataFrame(scot).set_index('date')['price_usd']

# Volume total por semana
df_vol = df.groupby('date')['lots'].sum().reset_index()

# Suavizacao 4 semanas
def smooth(sub, col='price_arroba'):
    return (sub.set_index('date')
               .resample('W')[col].mean()
               .rolling(4, min_periods=1).mean()
               .reset_index())

# ── 2. Cores ─────────────────────────────────────────────────────────────────
BG       = '#0D1117'
PANEL    = '#161B22'
GRID     = '#21262D'
TEXT     = '#E6EDF3'
SUBTEXT  = '#8B949E'
ACCENT   = '#58A6FF'
VOL_CLR  = '#1F6FEB'
PALETTE  = ['#F78166', '#3FB950', '#D2A8FF', '#FFA657', '#79C0FF']

# ── 3. Figura ─────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(15, 10), facecolor=BG)
gs  = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.06)
ax  = fig.add_subplot(gs[0])
axv = fig.add_subplot(gs[1], sharex=ax)

for a in (ax, axv):
    a.set_facecolor(PANEL)
    a.spines[:].set_color(GRID)
    a.tick_params(colors=SUBTEXT, labelsize=10)
    a.yaxis.grid(True, color=GRID, lw=0.7, ls='--')
    a.xaxis.grid(True, color=GRID, lw=0.5, ls=':')
    a.set_axisbelow(True)

# ── 4. Linhas por raca ────────────────────────────────────────────────────────
handles = []
for i, race in enumerate(RACES):
    color = PALETTE[i]
    sub = df[df['race'] == race][['date', 'price_arroba']].copy()
    smo = smooth(sub)

    ax.plot(smo['date'], smo['price_arroba'], color=color, lw=2.5, alpha=0.93, zorder=5)
    ax.fill_between(smo['date'], smo['price_arroba'], alpha=0.07, color=color, zorder=2)

    last = smo.dropna().iloc[-1]
    ax.scatter(last['date'], last['price_arroba'], color=color, s=65, zorder=8,
               edgecolors='white', lw=0.9)
    ax.annotate(f"R$ {last['price_arroba']:,.0f}",
                xy=(last['date'], last['price_arroba']),
                xytext=(10, 0), textcoords='offset points',
                fontsize=9, color=color, va='center', fontweight='bold')
    handles.append(Line2D([0], [0], color=color, lw=2.2, label=race))

# ── 5. Eixo secundario Scot ───────────────────────────────────────────────────
ax2 = ax.twinx()
ax2.set_facecolor(PANEL)
smo_scot = df_scot.rolling(4, min_periods=1).mean()
ax2.plot(smo_scot.index, smo_scot.values, color=ACCENT, lw=1.8, ls='--', alpha=0.8, zorder=4)
ax2.set_ylabel('Scot Brasil (US$/cabeça)', color=ACCENT, fontsize=10, labelpad=12)
ax2.tick_params(colors=ACCENT, labelsize=9)
ax2.spines[:].set_color(GRID)
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'US$ {x:.0f}'))
handles.append(Line2D([0], [0], color=ACCENT, lw=1.6, ls='--', label='Scot Brasil (US$/cab.)'))

ax.set_ylabel('Preço Médio R$/@ (Leilão CDA)', color=TEXT, fontsize=11, labelpad=12)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'R$ {x:,.0f}'))
ax.tick_params(axis='x', labelbottom=False)
ax.legend(handles=handles, loc='upper left', frameon=True,
          facecolor='#161B22', edgecolor=GRID, labelcolor=TEXT, fontsize=10)

# ── 6. Volume ─────────────────────────────────────────────────────────────────
axv.bar(df_vol['date'], df_vol['lots'], width=5, color=VOL_CLR, alpha=0.75, zorder=3)
axv.set_ylabel('Lotes / semana', color=SUBTEXT, fontsize=9, labelpad=8)
axv.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
axv.tick_params(axis='y', colors=SUBTEXT, labelsize=9)

# ── 7. Eixo X ─────────────────────────────────────────────────────────────────
axv.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
axv.xaxis.set_major_formatter(mdates.DateFormatter('%b/%y'))
plt.setp(axv.xaxis.get_majorticklabels(), rotation=30, ha='right', color=SUBTEXT)

# ── 8. Titulo e rodape ────────────────────────────────────────────────────────
fig.suptitle(
    '📈 Evolução de Preços — Leilão Correa da Costa (CDA)\n'
    'Últimos 365 dias  ·  [AMOSTRA — dados simulados]',
    fontsize=17, fontweight='bold', color=TEXT, y=0.97
)
fig.text(
    0.5, 0.01,
    f'Fonte: Correa da Costa Agropecuária  •  Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}  •  Agro Analytics Bot',
    ha='center', fontsize=8.5, color=SUBTEXT, style='italic'
)

plt.subplots_adjust(left=0.08, right=0.87, top=0.91, bottom=0.10)

# ── 9. Salvar na raiz do projeto ──────────────────────────────────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(script_dir, 'cda_sample_chart.png')
plt.savefig(out, dpi=150, facecolor=BG, bbox_inches='tight')
plt.close()
print(f"✅ Salvo em: {out}")
