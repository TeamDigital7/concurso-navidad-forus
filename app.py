import base64
from datetime import date
from functools import cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth import auth_configurada, requerir_login, usuario
from concurso import (CASAS, COMPETENCIAS, DESAFIOS_SSS, FIN, GANADOR_2025, INICIO, MAESTROS_CC,
                      MAESTROS_TIENDA, NOTAS_TIENDA, PREMIO_CAMPEON, RANGO_PAGO, REGLAMENTO, TIENDAS,
                      TRAMOS, BONUS_FIDELIZACION, BONUS_SSS)
from data import cargar_datos
from puntos import factor_pago, ganadores, puntos_por_tramo, ranking, resumen_casas

st.set_page_config(page_title="Forus y el Cáliz de los Campeones", page_icon="🏆", layout="wide")

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
st.markdown(f"<style>{(ASSETS / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def html(s: str):
    # Se quitan los saltos/sangrías para que Markdown no lo trate como bloque de código
    st.markdown("".join(line.strip() for line in s.splitlines()), unsafe_allow_html=True)


@cache
def img_uri(nombre: str) -> str:
    p = ASSETS / nombre
    if not p.exists():
        return ""
    mime = {".webp": "image/webp", ".png": "image/png"}.get(p.suffix, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def escudo(casa: str) -> str:
    return img_uri(f"escudos/{CASAS[casa]['escudo']}")


def soles(x: float) -> str:
    return f"S/ {x:,.0f}"


if not requerir_login():
    st.stop()

# ---------- Datos ----------
df_all, fuente = cargar_datos()
if df_all.empty:
    st.info(f"Fuente: {fuente}. Todavía no hay ventas del concurso (empieza el {INICIO:%d/%m/%Y}).")
    st.stop()
if df_all["presupuesto"].sum() == 0:
    st.warning("No hay presupuesto cargado: falta configurar `presupuesto_table` en los secrets. "
               "Sin presupuesto no se puede calcular el cumplimiento ni los puntos por venta.")
corte = df_all["fecha"].max().date()
pt_all = puntos_por_tramo(df_all, hasta=corte)
rank_all = ranking(pt_all)
casas = resumen_casas(rank_all)
comp_actual = next((c for c in COMPETENCIAS if c.inicio <= corte <= c.fin), COMPETENCIAS[-1])

# ---------- Sidebar ----------
with st.sidebar:
    html("""
    <div class="brand">FORUS</div>
    <div class="brand-sub">El Cáliz de los Campeones</div>
    <div class="brand-tag">Concurso navideño 2026</div>
    """)
    pagina = st.radio(
        "Navegación",
        ["🏰  Gran Salón", "🛡️  Casas", "⚔️  Competencias", "🏆  Copa del Mejor Mago",
         "📅  Calendario de puntos", "📜  Reglamento", "🧙  Maestros"],
        label_visibility="collapsed",
    )
    st.divider()
    casa_sel = st.selectbox("Casa", ["Todas las casas", *CASAS])
    html(f'<div class="fuente">Fuente: {fuente} · corte {corte:%d/%m/%Y}</div>')
    if auth_configurada():
        html(f'<div class="fuente">👤 {usuario()}</div>')
        if st.button("Cerrar sesión", use_container_width=True):
            st.logout()


def filtrar(r: pd.DataFrame) -> pd.DataFrame:
    return r if casa_sel == "Todas las casas" else r[r["casa"] == casa_sel].reset_index(drop=True)


# ---------- Componentes ----------
def hero():
    total = (FIN - INICIO).days + 1
    dia = min(max((corte - INICIO).days + 1, 0), total)
    portada = img_uri("portada.jpg")
    # La portada del PPT ya trae el título; sin imagen se dibuja en texto
    fondo = f"background-image: url('{portada}');" if portada else ""
    titulo = "" if portada else "<h1>Forus <span>y el Cáliz de los Campeones</span></h1>"
    html(f"""
    <div class="hero{' con-portada' if portada else ''}" style="{fondo}">
      {titulo}
      <p>CINCO CASAS · CUATRO COMPETENCIAS · UNA COPA</p>
      <div class="progress-card">
        <b>{comp_actual.nombre}</b><br>
        📅 {comp_actual.inicio:%d/%m} – {comp_actual.fin:%d/%m} · pago {comp_actual.pago:%d/%m}
        <div class="progress-bar"><div style="width:{dia / total:.0%}"></div></div>
        Día {dia} de {total} del torneo
      </div>
    </div>
    """)


def tarjetas_casas():
    cards = ""
    for i, r in casas.iterrows():
        c = CASAS[r["casa"]]
        cards += f"""
        <div class="house" style="--c:{c['color']}; --a:{c['acento']}; --f:{c['fondo']}">
          <span class="rank">#{i + 1}</span>
          <img src="{escudo(r['casa'])}" alt="{r['casa']}">
          <div class="name">{r['casa'].upper()}</div>
          <div class="pts">{r['puntos']:,}</div>
          <div class="pts-l">puntos · {r['puntos_prom']:.1f} por mago</div>
          <div class="foot">{r['magos']} magos · {r['cumplimiento']:.0%} ppto · SSS {r['sss']:+.0%}</div>
        </div>"""
    html(f'<div class="houses">{cards}</div>')


def kpis():
    venta, ppto, ly = df_all["venta"].sum(), df_all["presupuesto"].sum(), df_all["venta_ly"].sum()
    cumpl = venta / ppto if ppto else 0.0
    sss = venta / ly - 1 if ly else 0.0
    meta_sss = DESAFIOS_SSS.get(corte.month, 0)
    fid = df_all["tickets_fidelizados"].sum() / df_all["tickets"].sum()
    f = factor_pago(cumpl)
    items = [
        ("📈", "Cumplimiento Retail", f"{cumpl:.1%}", cumpl >= 1, f"{soles(venta)} / {soles(ppto)}"),
        ("💰", "Factor de pago de premios", f"{f:.0%}", f >= 1, "según rango de cumplimiento del canal"),
        ("🚀", "Crecimiento SSS", f"{sss:+.1%}", sss >= meta_sss, f"desafío del mes: +{meta_sss:.0%}"),
        ("💳", "Fidelización", f"{fid:.1%}", fid > BONUS_FIDELIZACION["umbral"],
         f"bonus +{BONUS_FIDELIZACION['puntos']} pts sobre {BONUS_FIDELIZACION['umbral']:.0%}"),
        ("🧾", "Ticket promedio", soles(venta / df_all["tickets"].sum()), False, "acumulado del torneo"),
        ("⭐", "Puntos repartidos", f"{int(rank_all['puntos'].sum()):,}", False,
         f"{int((pt_all['cerrado']).groupby(pt_all['tramo']).any().sum())} tramos cerrados de {len(TRAMOS)}"),
    ]
    cards = "".join(f"""
      <div class="kpi"><div class="ic">{ic}</div>
        <div><div class="lbl">{lbl}</div><div class="val {'g' if ok else ''}">{val}</div><div class="sub">{sub}</div></div>
      </div>""" for ic, lbl, val, ok, sub in items)
    html(f"""
    <div class="section-title"><h3>Indicadores del canal Retail</h3>
      <span class="live">Actualizado al {corte:%d/%m/%Y}</span></div>
    <div class="kpis">{cards}</div>
    """)


def _layout(fig, h=320, soles_y=True):
    fig.update_layout(
        height=h, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#D9CFB8", family="EB Garamond, serif", size=14),
        legend=dict(orientation="h", y=1.1, x=1, xanchor="right", bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)",
                   **({"tickprefix": "S/ ", "tickformat": "~s"} if soles_y else {})),
    )
    return fig


def grafico_tendencia():
    d = df_all.groupby("fecha", as_index=False)[["venta", "presupuesto"]].sum()
    fig = go.Figure()
    fig.add_bar(x=d["fecha"], y=d["venta"], name="Venta", marker=dict(color="#B8862F", line=dict(width=0)))
    fig.add_scatter(x=d["fecha"], y=d["presupuesto"], name="Presupuesto", mode="lines",
                    line=dict(color="#F3E2B3", dash="dash", width=2))
    fig.update_xaxes(tickformat="%d %b")
    return _layout(fig)


def grafico_carrera():
    d = pt_all[pt_all["cerrado"]].groupby(["fin", "casa"], as_index=False)["puntos"].sum()
    d = d.sort_values("fin")
    d["acumulado"] = d.groupby("casa")["puntos"].cumsum() / d["casa"].map(casas.set_index("casa")["magos"])
    fig = go.Figure()
    for casa, g in d.groupby("casa"):
        fig.add_scatter(x=g["fin"], y=g["acumulado"], name=casa, mode="lines+markers",
                        line=dict(color=CASAS[casa]["color"] if casa != "Curiosity" else "#8EA3D1", width=3))
    return _layout(fig, soles_y=False)


def tabla_magos(r: pd.DataFrame, top: int | None = None, premio: bool = False):
    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
    filas = ""
    for i, x in (r.head(top) if top else r).iterrows():
        pos = int(x["puesto"]) if "puesto" in x else i + 1
        col = CASAS[x["casa"]]["color"]
        nota = f' <small title="{NOTAS_TIENDA[x["tienda"]]}">*</small>' if x["tienda"] in NOTAS_TIENDA else ""
        extra = f'<td class="num pts">{soles(x["premio"])}</td>' if premio else ""
        filas += f"""<tr>
          <td>{medallas.get(pos, pos)}</td><td>{x['tienda']}{nota}</td>
          <td><span class="chip"><i style="background:{col}"></i>{x['casa']}</span></td>
          <td class="num pts">{int(x['puntos']):,}</td><td class="num">{int(x['pts_venta'])} / {int(x['pts_bonus'])}</td>
          <td class="num {'pos' if x['cumplimiento'] >= 1 else 'neg'}">{x['cumplimiento']:.1%}</td>
          <td class="num {'pos' if x['sss'] >= 0 else 'neg'}">{x['sss']:+.1%}</td>
          <td class="num">{x['fidelizacion']:.0%}</td><td class="num">{soles(x['venta'])}</td>{extra}
        </tr>"""
    th_premio = '<th class="num">Premio</th>' if premio else ""
    html(f"""<table class="rank-table"><thead><tr>
      <th>#</th><th>Mago (tienda)</th><th>Casa</th><th class="num">Puntos</th><th class="num">Venta / Bonus</th>
      <th class="num">% Ppto</th><th class="num">SSS</th><th class="num">Fidelización</th>
      <th class="num">Venta</th>{th_premio}</tr></thead><tbody>{filas}</tbody></table>""")


# ---------- Páginas ----------
if pagina.endswith("Gran Salón"):
    hero()
    tarjetas_casas()
    kpis()
    c1, c2 = st.columns([1.5, 1], gap="medium")
    with c1, st.container(border=True):
        html('<div class="card-title">Venta diaria vs. presupuesto (canal Retail)</div>')
        st.plotly_chart(grafico_tendencia(), use_container_width=True, config={"displayModeBar": False})
    with c2, st.container(border=True):
        html('<div class="card-title">Carrera de casas · puntos promedio por mago</div>')
        st.plotly_chart(grafico_carrera(), use_container_width=True, config={"displayModeBar": False})
    with st.container(border=True):
        html('<div class="card-title">Top 10 magos del torneo</div>')
        tabla_magos(filtrar(rank_all), top=10)

elif pagina.endswith("Casas"):
    tabs = st.tabs([f"{c}" for c in CASAS])
    for tab, casa in zip(tabs, CASAS):
        with tab:
            c = CASAS[casa]
            r = rank_all[rank_all["casa"] == casa].reset_index(drop=True)
            res = casas.set_index("casa").loc[casa]
            col1, col2 = st.columns([1, 3], gap="large")
            with col1:
                html(f'<img class="crest-big" src="{escudo(casa)}">')
            with col2:
                html(f"""
                <div class="house-head" style="--c:{c['color']}; --a:{c['acento']}">
                  <h2>Casa {casa}</h2><p>Animal: {c['animal']} · {len(TIENDAS[casa])} magos</p>
                  <div class="mini-kpis">
                    <div><b>{int(res['puntos']):,}</b><span>puntos</span></div>
                    <div><b>{res['cumplimiento']:.1%}</b><span>cumplimiento</span></div>
                    <div><b>{res['sss']:+.1%}</b><span>SSS</span></div>
                    <div><b>{soles(res['venta'])}</b><span>venta</span></div>
                  </div>
                </div>""")
                tabla_magos(r)

elif pagina.endswith("Competencias"):
    nombres = [c.nombre for c in COMPETENCIAS]
    sel = st.segmented_control("Competencia", nombres, default=comp_actual.nombre,
                               label_visibility="collapsed") or comp_actual.nombre
    comp = COMPETENCIAS[nombres.index(sel)]
    top, cumpl, f = ganadores(pt_all, comp)
    estado = "Cerrada" if corte >= comp.fin else ("En curso" if corte >= comp.inicio else "Por iniciar")
    premios = " · ".join(f"{i}° {soles(p)}" for i, p in enumerate(comp.premios, 1))
    html(f"""
    <div class="comp-head">
      <div><h2>{comp.nombre}</h2>
        <p>{comp.inicio:%d/%m} al {comp.fin:%d/%m} · pago {comp.pago:%d/%m/%Y} · <b>{estado}</b></p>
        <p class="premios">{premios}</p></div>
      <div class="pago"><span>Cumplimiento Retail</span><b>{cumpl:.1%}</b>
        <span>Se paga el <b>{f:.0%}</b> del premio</span></div>
    </div>""")
    if top.empty:
        st.info("Esta competencia todavía no tiene ventas.")
    for casa in CASAS:
        if casa_sel not in ("Todas las casas", casa):
            continue
        g = top[top["casa"] == casa]
        if g.empty:
            continue
        with st.container(border=True):
            html(f'<div class="card-title"><img class="crest-sm" src="{escudo(casa)}"> Casa {casa} · Top 5</div>')
            tabla_magos(g, premio=True)
    st.caption("Los part times reciben el 50% del premio. Pago de premios neto. "
               "Desempate: mejor % de cumplimiento de venta vs. presupuesto.")

elif pagina.endswith("Copa del Mejor Mago"):
    html(f"""
    <div class="copa"><div class="trofeo">🏆</div><div>
      <h2>La Copa del Mejor Mago del Retail</h2>
      <p>Gana el mago con más puntos sumando todas las competencias de noviembre y diciembre.</p>
      <p class="premio">Premio: {PREMIO_CAMPEON}</p>
      <p class="hist">Ganadores 2025: {GANADOR_2025}</p></div></div>""")
    with st.container(border=True):
        tabla_magos(filtrar(rank_all))
    st.download_button("⬇️ Exportar ranking (CSV)", rank_all.to_csv(index=False).encode("utf-8"),
                       "copa_mejor_mago.csv", "text/csv")

elif pagina.endswith("Calendario de puntos"):
    filas = ""
    for i, t in enumerate(TRAMOS):
        estado = "✅ Cerrado" if t.fin <= corte else ("⏳ En curso" if t.inicio <= corte else "🔒 Próximo")
        ganan = int((pt_all.loc[pt_all["tramo"] == i, "pts_venta"] > 0).sum()) if t.fin <= corte else "–"
        filas += f"""<tr><td>{t.inicio:%B}</td><td>Del {t.inicio.day} al {t.fin.day}</td>
          <td class="num pts">{t.puntos}</td><td>{estado}</td><td class="num">{ganan}</td></tr>"""
    c1, c2 = st.columns([1.4, 1], gap="large")
    with c1, st.container(border=True):
        html(f"""<div class="card-title">Rango de fechas para acumular puntos</div>
        <table class="rank-table"><thead><tr><th>Mes</th><th>Fecha</th><th class="num">Puntos</th>
        <th>Estado</th><th class="num">Magos que cumplieron</th></tr></thead><tbody>{filas}</tbody></table>""")
    with c2, st.container(border=True):
        rango = "".join(
            f"<li>Desde {d:.2%}: se paga el <b>{fct:.0%}</b> del premio</li>" for d, fct in RANGO_PAGO)
        html(f"""<div class="card-title">Cómo se suman puntos</div><ul class="reglas">
          <li>Cumplir venta ≥ presupuesto en el tramo otorga sus puntos.</li>
          <li>Bonus fidelización mayor a {BONUS_FIDELIZACION['umbral']:.0%}: +{BONUS_FIDELIZACION['puntos']} puntos.</li>
          <li>Bonus crecimiento SSS mayor a {BONUS_SSS['umbral']:.0%}: +{BONUS_SSS['puntos']} puntos.</li>
          <li>El 25 de diciembre no tiene tramo asignado.</li></ul>
          <div class="card-title">Rango de premios (cumplimiento Retail)</div><ul class="reglas">{rango}</ul>
          <div class="card-title">Desafíos del canal</div><ul class="reglas">
          {''.join(f"<li>{'Noviembre' if m == 11 else 'Diciembre'}: +{v:.0%} SSS</li>" for m, v in DESAFIOS_SSS.items())}
          </ul>""")

elif pagina.endswith("Reglamento"):
    with st.container(border=True):
        html('<div class="pergamino"><h2>📜 Reglamento del Torneo</h2><ol>'
             + "".join(f"<li>{r}</li>" for r in REGLAMENTO) + "</ol></div>")
    cols = st.columns(len(COMPETENCIAS))
    for col, c in zip(cols, COMPETENCIAS):
        with col, st.container(border=True):
            html(f"""<div class="premio-card"><small>{c.inicio:%d/%m} al {c.fin:%d/%m}</small>
              <h4>{c.nombre}</h4>{''.join(f'<div>{i}° puesto <b>{soles(p)}</b></div>' for i, p in enumerate(c.premios, 1))}
              <small>Pago: {c.pago:%d/%m}</small></div>""")

else:
    c1, c2 = st.columns([1.3, 1], gap="large")
    with c1, st.container(border=True):
        filas = "".join(f"<tr><td><b>{cc}</b></td><td>{marcas}</td><td>{'<br>'.join(m)}</td></tr>"
                        for cc, marcas, m in MAESTROS_CC)
        html(f"""<div class="card-title">Maestros por centro comercial</div>
        <table class="rank-table"><thead><tr><th>Centro comercial</th><th>Marcas</th><th>Maestros</th></tr></thead>
        <tbody>{filas}</tbody></table>""")
    with c2, st.container(border=True):
        st.dataframe(pd.DataFrame(MAESTROS_TIENDA.items(), columns=["Tienda", "Maestro"]),
                     hide_index=True, use_container_width=True, height=760)
