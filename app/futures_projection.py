"""
Curva de preço projetada: boi (futuro B3), vaca e novilha por praça,
sobrepondo os últimos N pregões para mostrar a dinâmica da curva.

1. Boi: ajustes BGI da B3 (referência SP). Para outra praça aplica-se o
   basis do dia: boi_UF / boi_SP (Indicador do Boi DATAGRO).
2. Vaca e novilha: relação com o boi à vista da mesma praça.
     - com >= MIN_HISTORY_DAYS dias no banco: regressão linear  cat = a + b·boi
     - sem histórico suficiente: razão do dia  cat = boi · (cat_dia / boi_dia)
3. Pregões sem cotação à vista gravada usam a cotação mais recente anterior
   (ou a mais antiga disponível) — marcado em `spot_date` de cada curva.

Fontes: futures_settlements (app/scraper_b3.py) e datagro_quotes (app/scraper_datagro.py).
"""

MIN_HISTORY_DAYS = 30
CATEGORIES = ("boi", "vaca", "novilha")


def _fit_relation(pairs):
    """pairs = [(boi, cat), ...] em ordem de data → (a, b, método)."""
    if len(pairs) >= MIN_HISTORY_DAYS:
        n = len(pairs)
        mx = sum(x for x, _ in pairs) / n
        my = sum(y for _, y in pairs) / n
        sxx = sum((x - mx) ** 2 for x, _ in pairs)
        if sxx > 0:
            b = sum((x - mx) * (y - my) for x, y in pairs) / sxx
            return my - b * mx, b, f"regressão ({n} dias)"
    boi, cat = pairs[-1]
    return 0.0, cat / boi, "razão do dia"


def _spot_for(session_date, spot_by_date):
    """Cotação à vista do pregão, ou a mais próxima anterior (senão a mais antiga)."""
    dates = sorted(spot_by_date)
    earlier = [d for d in dates if d <= session_date]
    d = earlier[-1] if earlier else dates[0]
    return d, spot_by_date[d]


def build_sessions(futures_by_date, spot_by_date, uf="SP", sessions=10):
    """
    futures_by_date: {pregão: [(mês_vencimento, ajuste), ...]}   (B3, ref. SP)
    spot_by_date:    {data: {(categoria, UF): valor}}            (DATAGRO)
    Retorna lista (mais antigo → mais recente) de curvas por pregão.
    """
    ufs_needed = {("boi", "SP")} | {(c, uf) for c in CATEGORIES}
    spot_by_date = {d: s for d, s in spot_by_date.items() if ufs_needed <= set(s)}
    if not spot_by_date:
        raise ValueError(f"Sem cotação à vista DATAGRO completa para {uf}")

    out = []
    for session_date in sorted(futures_by_date)[-sessions:]:
        spot_date, spot = _spot_for(session_date, spot_by_date)
        basis = spot[("boi", uf)] / spot[("boi", "SP")]
        boi_curve = [(m, v * basis) for m, v in sorted(futures_by_date[session_date])]

        curve, relations = {"boi": boi_curve}, {}
        for cat in ("vaca", "novilha"):
            # histórico até a cotação usada (a última é a própria cotação do pregão)
            pairs = [(s[("boi", uf)], s[(cat, uf)])
                     for d, s in sorted(spot_by_date.items()) if d <= spot_date]
            a, b, method = _fit_relation(pairs)
            relations[cat] = {"a": a, "b": b, "method": method}
            curve[cat] = [(m, a + b * v) for m, v in boi_curve]

        out.append({
            "uf": uf,
            "session_date": session_date,
            "spot_date": spot_date,
            "spot": {c: spot[(c, uf)] for c in CATEGORIES},
            "basis": basis,
            "curve": curve,
            "relations": relations,
        })
    return out


# ── Carregamento do banco ─────────────────────────────────────────────────────

def load_from_db(uf="SP", sessions=10):
    from app.models import SessionLocal, FuturesSettlement, DatagroQuote

    db = SessionLocal()
    try:
        dates = [
            d for (d,) in db.query(FuturesSettlement.ref_date)
            .distinct().order_by(FuturesSettlement.ref_date.desc()).limit(sessions)
        ]
        futures_by_date = {}
        for s in db.query(FuturesSettlement).filter(FuturesSettlement.ref_date.in_(dates)):
            futures_by_date.setdefault(s.ref_date, []).append((s.contract_month, s.settle))

        spot_by_date = {}
        rows = db.query(DatagroQuote).filter(
            DatagroQuote.category.in_(CATEGORIES),
            DatagroQuote.region.in_({uf, "SP"}),
        )
        for q in rows:
            spot_by_date.setdefault(q.ref_date, {})[(q.category, q.region)] = q.value
    finally:
        db.close()

    return build_sessions(futures_by_date, spot_by_date, uf=uf, sessions=sessions)


# ── Gráfico ───────────────────────────────────────────────────────────────────

def _brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate_projection_chart(sessions, output_path="projecao_curva.png"):
    """sessions: saída de build_sessions (mais antigo → mais recente)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.lines import Line2D

    SURFACE, INK, INK_2, INK_3, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
    SERIES = {  # ordem categórica fixa (slots 1-3); boi contínua, vaca/novilha tracejadas
        "boi":     ("Boi gordo", "#2a78d6", "o", "-"),
        "vaca":    ("Vaca",      "#eb6834", "s", (0, (5, 3))),
        "novilha": ("Novilha",   "#1baf7a", "D", (0, (5, 3))),
    }
    MES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

    latest = sessions[-1]
    months = sorted({m for s in sessions for m, _ in s["curve"]["boi"]})
    m0 = months[0]

    def x_of(m):  # meses a partir do 1º vencimento (=1); x=0 é o à vista
        return 1 + (m.year - m0.year) * 12 + (m.month - m0.month)

    fig, ax = plt.subplots(figsize=(12, 6.8), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    n = len(sessions)
    for i, sess in enumerate(sessions):
        newest = i == n - 1
        # opacidade cresce do mais antigo (0.12) ao penúltimo (0.45); o mais recente é 1.0
        alpha = 1.0 if newest else 0.12 + 0.33 * (i / max(n - 2, 1))
        lw = 2.4 if newest else 1.2
        for cat, (label, color, marker, ls) in SERIES.items():
            pts = sess["curve"][cat]
            xs, ys = [x_of(m) for m, _ in pts], [v for _, v in pts]
            ax.plot(xs, ys, color=color, lw=lw, ls=ls, alpha=alpha,
                    marker=marker if newest else None, ms=7, mec=SURFACE, mew=1.5,
                    zorder=3 if newest else 2)
            if newest:
                spot = sess["spot"][cat]
                ax.plot([0, xs[0]], [spot, ys[0]], color=color, lw=1.4, ls=(0, (1, 2)), zorder=2)
                ax.plot([0], [spot], marker=marker, ms=10, color=color, mec=INK, mew=1.2, zorder=4)
                ax.annotate(f"{label}  {_brl(ys[-1])}", (xs[-1], ys[-1]), xytext=(12, 0),
                            textcoords="offset points", va="center", fontsize=11, color=INK)

    ax.annotate(f"À vista\n{latest['spot_date'].strftime('%d/%m')}", (0, latest["spot"]["boi"]),
                xytext=(0, 16), textcoords="offset points", ha="center", fontsize=10, color=INK_2)

    ticks = [0] + [x_of(m) for m in months]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Hoje"] + [f"{MES[m.month]}/{m.year % 100}" for m in months])
    ax.set_xlim(-0.5, ticks[-1] + 3.2)
    lo = min([latest["spot"]["vaca"]] + [v for s in sessions for _, v in s["curve"]["vaca"]])
    hi = max(v for s in sessions for _, v in s["curve"]["boi"])
    ax.set_ylim(lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R$ {v:,.0f}".replace(",", ".")))
    ax.set_ylabel("R$/@", color=INK_2, fontsize=11)

    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=10.5, length=0)

    # Legenda: categoria (cor + traço) e intensidade (recente × anteriores)
    handles = [Line2D([], [], color=c, lw=2.4, ls=ls, marker=mk, ms=7, mec=SURFACE, label=lb)
               for lb, c, mk, ls in SERIES.values()]
    first = sessions[0]["session_date"].strftime("%d/%m")
    last = latest["session_date"].strftime("%d/%m")
    handles += [
        Line2D([], [], color=INK, lw=2.4, label=f"Pregão {last}"),
        Line2D([], [], color=INK, lw=1.2, alpha=0.3, label=f"{n - 1} pregões anteriores ({first}→)"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(-0.01, 1.11), ncol=5,
              frameon=False, fontsize=10.5, labelcolor=INK, handlelength=2.6)

    uf, rel = latest["uf"], latest["relations"]
    fig.text(0.06, 0.93, f"Curva de preço projetada — {uf}", fontsize=18, fontweight="bold", color=INK)
    basis_txt = "" if uf == "SP" else f" · basis {uf}/SP {latest['basis']:.3f}"
    fig.text(0.06, 0.885,
             f"Boi: ajustes B3 (BGI){basis_txt} · Vaca {rel['vaca']['b']:.3f}× e novilha "
             f"{rel['novilha']['b']:.3f}× o boi à vista ({rel['vaca']['method']}) · "
             f"últimos {n} pregões, o mais recente em destaque",
             fontsize=10.5, color=INK_2)
    stale = [s for s in sessions if s["spot_date"] != s["session_date"]]
    note = (f"\n{len(stale)} pregões sem cotação à vista gravada usam a relação vaca/novilha e o basis de "
            f"{stale[-1]['spot_date'].strftime('%d/%m')}." if stale else "")
    fig.text(0.06, 0.015,
             "Fonte: B3 (ajustes Boi Gordo BGI) e DATAGRO (Indicador do Boi, Vaca e Novilha). "
             "Projeção indicativa, não é recomendação de negócio." + note,
             fontsize=9, color=INK_3, linespacing=1.5)

    fig.subplots_adjust(left=0.08, right=0.97, top=0.78, bottom=0.12)
    fig.savefig(output_path, dpi=140, facecolor=SURFACE)
    plt.close(fig)
    return output_path


# ── Bot (Telegram / WhatsApp) ─────────────────────────────────────────────────

UFS = ("BA", "GO", "MG", "MS", "MT", "PA", "RO", "SP", "TO")
DEFAULT_UF = "MS"


def normalize_uf(value):
    uf = (value or "").strip().upper()
    return uf if uf in UFS else DEFAULT_UF


def build_bot_projection(uf=DEFAULT_UF, sessions=10):
    """Gera o PNG da curva e a legenda para o bot. Retorna (caminho, legenda)."""
    import tempfile

    uf = normalize_uf(uf)
    data = load_from_db(uf=uf, sessions=sessions)
    path = generate_projection_chart(data, tempfile.NamedTemporaryFile(suffix=".png", delete=False).name)

    MES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    latest, oldest = data[-1], data[0]
    lines = [f"📈 *Curva projetada — {uf}*", ""]
    for cat, label in (("boi", "🐂 Boi"), ("novilha", "🐄 Novilha"), ("vaca", "🐄 Vaca")):
        peak_m, peak_v = max(latest["curve"][cat], key=lambda p: p[1])
        lines.append(f"{label}: à vista {_brl(latest['spot'][cat])} → pico {_brl(peak_v)} "
                     f"({MES[peak_m.month]}/{peak_m.year % 100})")

    if len(data) > 1:
        old = dict(oldest["curve"]["boi"])
        diffs = [v - old[m] for m, v in latest["curve"]["boi"] if m in old]
        if diffs:
            avg = sum(diffs) / len(diffs)
            arrow = "⬆️" if avg > 0.05 else "⬇️" if avg < -0.05 else "➡️"
            lines += ["", f"{arrow} Curva do boi {'+' if avg >= 0 else '−'}{_brl(abs(avg))}/@ em média "
                          f"desde {oldest['session_date'].strftime('%d/%m')} ({len(data)} pregões)"]

    lines += [
        "",
        f"_Linha forte = pregão {latest['session_date'].strftime('%d/%m')}; as mais claras são os anteriores. "
        "Vaca e novilha projetadas pela relação com o boi à vista da praça._",
        "*Fontes:* B3 e DATAGRO",
        f"Outras praças ({', '.join(u for u in UFS if u != uf)}): peça, por ex., \"curva de preço MT\".",
    ]
    return path, "\n".join(lines)
