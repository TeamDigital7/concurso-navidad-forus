import base64
import time
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth import auth_configurada, requerir_login, usuario
from concurso import (CASAS, COMPETENCIAS, DESAFIOS_SSS, FIN, GANADOR_2025, INICIO, MAESTROS_CC,
                      MAESTROS_TIENDA, NOTAS_TIENDA, PREMIO_CAMPEON, RANGO_PAGO, REGLAMENTO, TIENDAS,
                      TRAMOS, BONUS_FIDELIZACION, BONUS_SSS)
from data import ACTUALIZAR_CADA_MIN, cargar_datos, cargar_pronostico
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
# Antes del 01/11 no hay venta del concurso: se muestra un pronóstico con la venta de los últimos días
pronostico = None
desfase = timedelta(0)
if df_all.empty:
    df_all, fuente, p_desde, p_hasta, p_referencial = cargar_pronostico()
    if df_all.empty:
        st.info(f"Fuente: {fuente}. Todavía no hay ventas del concurso (empieza el {INICIO:%d/%m/%Y}).")
        st.stop()
    pronostico = {"desde": p_desde, "hasta": p_hasta, "referencial": p_referencial}
    desfase = COMPETENCIAS[0].inicio - p_desde
if df_all["presupuesto"].sum() == 0:
    st.warning("No hay presupuesto cargado: falta configurar `presupuesto_table` en los secrets. "
               "Sin presupuesto no se puede calcular el cumplimiento ni los puntos por venta.")
corte = df_all["fecha"].max().date()
pt_all = puntos_por_tramo(df_all, hasta=corte)
rank_all = ranking(pt_all)
casas = resumen_casas(rank_all)
comp_actual = next((c for c in COMPETENCIAS if c.inicio <= corte <= c.fin), COMPETENCIAS[-1])
# Fecha real de los datos (en el pronóstico, `corte` es la fecha simulada dentro del concurso)
corte_real = pronostico["hasta"] if pronostico else corte

# ---------- Sidebar ----------
with st.sidebar:
    html("""
    <div class="brand">FORUS</div>
    <div class="brand-sub">El Cáliz de los Campeones</div>
    <div class="brand-tag">Concurso navideño 2026</div>
    """)
    pagina = st.radio(
        "Navegación",
        ["🏁  Ranking", "🏰  Gran Salón", "🛡️  Casas", "⚔️  Competencias", "🏆  Copa del Mejor Mago",
         "📅  Calendario de puntos", "📜  Reglamento", "🧙  Maestros"],
        label_visibility="collapsed",
    )
    st.divider()
    html(f'<div class="fuente">Fuente: {fuente} · corte {corte_real:%d/%m/%Y}</div>')
    if auth_configurada():
        html(f'<div class="fuente">👤 {usuario()}</div>')
        if st.button("Cerrar sesión", use_container_width=True):
            st.logout()


def con_puesto(r: pd.DataFrame) -> pd.DataFrame:
    """Fija el puesto ANTES de filtrar: buscar una tienda no puede cambiar su posición."""
    return r.assign(puesto=range(1, len(r) + 1))


def filtros_de_ranking(r: pd.DataFrame, clave: str, top: int | None = None) -> pd.DataFrame:
    """Buscador y casa en la pantalla principal (en el celular el menú lateral queda escondido)."""
    texto = st.text_input("Buscar tienda", key=f"buscar_{clave}", placeholder="🔎 Buscar tienda (ej. Jockey, CLB, Trujillo)",
                          label_visibility="collapsed")
    casa = st.pills("Casa", list(CASAS), key=f"casa_{clave}", label_visibility="collapsed")
    if casa:
        r = r[r["casa"] == casa]
    if texto.strip():
        palabras = texto.upper().split()
        r = r[r["tienda"].apply(lambda t: all(p in t for p in palabras))]
        if r.empty:
            st.caption("Ninguna tienda coincide con la búsqueda.")
        return r
    if top and len(r) > top and not st.toggle(f"Ver las {len(r)} tiendas", key=f"todas_{clave}"):
        return r.head(top)
    return r


# ---------- Componentes ----------
def aviso_pronostico():
    if not pronostico:
        return
    faltan = (INICIO - date.today()).days
    cuenta = f"faltan {faltan} días" if faltan > 1 else ("empieza mañana" if faltan == 1 else "empieza hoy")
    comp = COMPETENCIAS[0]
    meta = (f" Como aún no hay presupuesto cargado, la meta es referencial: venta del año pasado "
            f"+{DESAFIOS_SSS.get(comp.inicio.month, 0):.0%} (desafío SSS de noviembre).") if pronostico["referencial"] else ""
    texto = (f"Así quedaría <b>{comp.nombre}</b> si se jugara con la venta real del "
             f"{pronostico['desde']:%d/%m} al {pronostico['hasta']:%d/%m}, con las mismas reglas de puntos. "
             f"Estos puntos no cuentan: sirven para que cada tienda vea su potencial.{meta}")
    html(f"""<div class="pronostico"><div class="t">🔮 Pronóstico · el concurso empieza el {INICIO:%d/%m} ({cuenta})</div>
      <span>{texto}</span></div>""")


def hero():
    total = (FIN - INICIO).days + 1
    dia = min(max((corte - INICIO).days + 1, 0), total)
    if pronostico:
        dia = 0
    portada = img_uri("portada.jpg")
    # La portada del PPT ya trae el título; sin imagen se dibuja en texto
    fondo = f"background-image: url('{portada}'); --portada: url('{portada}');" if portada else ""
    titulo = "" if portada else "<h1>Forus <span>y el Cáliz de los Campeones</span></h1>"
    html(f"""
    <div class="hero{' con-portada' if portada else ''}" style="{fondo}">
      {titulo}
      <p>CINCO CASAS · CUATRO COMPETENCIAS · UNA COPA</p>
      <div class="progress-card">
        <b>{comp_actual.nombre}</b><br>
        📅 {comp_actual.inicio:%d/%m} – {comp_actual.fin:%d/%m} · pago {comp_actual.pago:%d/%m}
        <div class="progress-bar"><div style="width:{dia / total:.0%}"></div></div>
        {f"Empieza el {INICIO:%d/%m/%Y} · {total} días de torneo" if pronostico else f"Día {dia} de {total} del torneo"}
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
    meta_sss = DESAFIOS_SSS.get(corte.month, 0)  # en el pronóstico, corte cae en noviembre
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
      <span class="live">{'Pronóstico con venta al' if pronostico else 'Actualizado al'} {corte_real:%d/%m/%Y}</span></div>
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
    d["fecha"] -= desfase  # en el pronóstico se muestran las fechas reales
    fig = go.Figure()
    fig.add_bar(x=d["fecha"], y=d["venta"], name="Venta", marker=dict(color="#B8862F", line=dict(width=0)))
    fig.add_scatter(x=d["fecha"], y=d["presupuesto"], name="Presupuesto", mode="lines",
                    line=dict(color="#F3E2B3", dash="dash", width=2))
    fig.update_xaxes(tickformat="%d %b")
    return _layout(fig)


def grafico_carrera():
    d = pt_all[pt_all["cerrado"]].groupby(["fin", "casa"], as_index=False)["puntos"].sum()
    d = d.sort_values("fin")
    d["fin"] = d["fin"] - desfase
    d["acumulado"] = d.groupby("casa")["puntos"].cumsum() / d["casa"].map(casas.set_index("casa")["magos"])
    fig = go.Figure()
    for casa, g in d.groupby("casa"):
        fig.add_scatter(x=g["fin"], y=g["acumulado"], name=casa, mode="lines+markers",
                        line=dict(color=CASAS[casa]["color"] if casa != "Curiosity" else "#8EA3D1", width=3))
    return _layout(fig, soles_y=False)


def _pct(x: float, signo: bool = False) -> str:
    if pd.isna(x):
        return "–"
    return f"{x:+.1%}" if signo else f"{x:.1%}"


def tabla_magos(r: pd.DataFrame, top: int | None = None, premio: bool = False,
                solo_lista: bool = False, zona_premio: int | None = None):
    """Tabla en escritorio y, en el celular, una tarjeta por tienda que se toca para ver el detalle.

    `solo_lista` dibuja las tarjetas también en escritorio (la vista Ranking). `zona_premio` marca
    los puestos que hoy ganarían premio.
    """
    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
    filas = tarjetas = ""
    for n, (_, x) in enumerate((r.head(top) if top else r).iterrows()):
        pos = int(x["puesto"]) if "puesto" in x else n + 1
        col = CASAS[x["casa"]]["color"]
        nota = f' <small title="{NOTAS_TIENDA[x["tienda"]]}">*</small>' if x["tienda"] in NOTAS_TIENDA else ""
        extra = f'<td class="num pts">{soles(x["premio"])}</td>' if premio else ""
        cumple = "pos" if x["cumplimiento"] >= 1 else "neg"
        crece = "pos" if x["sss"] >= 0 else "neg"
        premio_m = f'<div><span>Premio</span><b class="pts">{soles(x["premio"])}</b></div>' if premio else ""
        maestro = MAESTROS_TIENDA.get(x["tienda"])
        maestro_m = f'<div class="ancho"><span>Maestro</span><b>{maestro}</b></div>' if maestro else ""
        gana = bool(x["gana"]) if "gana" in x else bool(zona_premio and pos <= zona_premio)
        sello = '<em class="sello">🎁 Premio</em>' if gana else ""
        tarjetas += f"""<details class="mago{' gana' if gana else ''}" style="--c:{col}">
          <summary><span class="pos">{medallas.get(pos, pos)}</span>
            <span class="nom"><b>{x['tienda']}{nota}</b><small><i></i>{x['casa']}{sello}</small></span>
            <span class="pts">{int(x['puntos']):,}<small>pts</small></span></summary>
          <div class="det">
            <div><span>% Presupuesto</span><b class="{cumple}">{_pct(x['cumplimiento'])}</b></div>
            <div><span>Crecimiento SSS</span><b class="{crece}">{_pct(x['sss'], True)}</b></div>
            <div><span>Fidelización</span><b>{x['fidelizacion']:.0%}</b></div>
            <div><span>Venta</span><b>{soles(x['venta'])}</b></div>
            <div><span>Puntos por venta</span><b>{int(x['pts_venta'])}</b></div>
            <div><span>Puntos bonus</span><b>{int(x['pts_bonus'])}</b></div>
            {premio_m}{maestro_m}
          </div></details>"""
        filas += f"""<tr>
          <td>{medallas.get(pos, pos)}</td><td>{x['tienda']}{nota}</td>
          <td><span class="chip"><i style="background:{col}"></i>{x['casa']}</span></td>
          <td class="num pts">{int(x['puntos']):,}</td><td class="num">{int(x['pts_venta'])} / {int(x['pts_bonus'])}</td>
          <td class="num {cumple}">{_pct(x['cumplimiento'])}</td>
          <td class="num {crece}">{_pct(x['sss'], True)}</td>
          <td class="num">{x['fidelizacion']:.0%}</td><td class="num">{soles(x['venta'])}</td>{extra}
        </tr>"""
    if solo_lista:
        html(f'<div class="magos-movil siempre">{tarjetas}</div>')
        return
    th_premio = '<th class="num">Premio</th>' if premio else ""
    html(f"""<table class="rank-table solo-escritorio"><thead><tr>
      <th>#</th><th>Mago (tienda)</th><th>Casa</th><th class="num">Puntos</th><th class="num">Venta / Bonus</th>
      <th class="num">% Ppto</th><th class="num">SSS</th><th class="num">Fidelización</th>
      <th class="num">Venta</th>{th_premio}</tr></thead><tbody>{filas}</tbody></table>
      <div class="magos-movil">{tarjetas}</div>""")


def podio(r: pd.DataFrame):
    if r.empty:
        return
    medallas = ["🥇", "🥈", "🥉"]
    puestos = ""
    for (_, x), medalla in zip(r.head(3).iterrows(), medallas):
        c = CASAS[x["casa"]]
        puestos += f"""<div class="podio-p" style="--c:{c['color']}; --a:{c['acento']}">
          <div class="med">{medalla}</div><div class="tn">{x['tienda']}</div>
          <div class="cs"><i></i>{x['casa']}</div><div class="pt">{int(x['puntos']):,}<small> pts</small></div>
        </div>"""
    html(f'<div class="podio">{puestos}</div>')


def vista_ranking():
    """La vista de entrada: quién va primero y la lista completa de tiendas, sin buscar nada."""
    opciones = ["Torneo completo", comp_actual.nombre]
    vista = st.segmented_control("Ranking", opciones, default=opciones[0],
                                 key="rk_vista", label_visibility="collapsed") or opciones[0]
    if vista == opciones[0]:
        base, zona, nota = rank_all, None, "Copa del Mejor Mago: suma de todas las competencias."
    else:
        base, zona = ranking(pt_all[pt_all["competencia"] == comp_actual.nombre]), 5
        nota = (f"{comp_actual.nombre} · {comp_actual.inicio:%d/%m} al {comp_actual.fin:%d/%m}. "
                "Ganan los 5 primeros de cada casa.")
    texto = st.text_input("Buscar tienda", key="rk_buscar", label_visibility="collapsed",
                          placeholder="🔎 Buscar tienda (ej. Jockey, CLB, Trujillo)")
    casa = st.pills("Casa", list(CASAS), key="rk_casa", label_visibility="collapsed")
    if casa:
        # Los premios son por casa: con una casa elegida, el puesto es el puesto dentro de la casa
        r = con_puesto(base[base["casa"] == casa].reset_index(drop=True))
    else:
        r = con_puesto(base)
        if zona:
            r["puesto_casa"] = r.groupby("casa").cumcount() + 1
    buscando = bool(texto.strip())
    if buscando:
        palabras = texto.upper().split()
        r = r[r["tienda"].apply(lambda t: all(p in t for p in palabras))]
    html(f'<div class="rk-nota">{nota} Toca una tienda para ver su detalle.</div>')
    if r.empty:
        st.caption("Ninguna tienda coincide con la búsqueda.")
        return
    if not buscando:
        podio(r)
    if zona and not casa:
        # Sin casa elegida, la marca de premio sale del puesto dentro de SU casa
        r = r.assign(gana=r["puesto_casa"] <= zona)
    tabla_magos(r, solo_lista=True, zona_premio=zona if casa else None)
    if zona and not casa:
        st.caption("🎁 marca a quienes hoy están en el top 5 de su casa.")


@st.fragment(run_every=timedelta(minutes=ACTUALIZAR_CADA_MIN))
def auto_actualizar():
    """En vivo: cada N minutos vuelve a correr toda la app; si el caché venció, trae la venta nueva.

    El fragmento también corre en cada recarga completa: solo dispara si ya pasó el intervalo
    desde la última, para no entrar en un bucle de recargas.
    """
    if time.time() - st.session_state.get("ultima_carga", 0) >= ACTUALIZAR_CADA_MIN * 60 - 5:
        st.rerun()


st.session_state["ultima_carga"] = time.time()
auto_actualizar()
consultado = df_all.attrs.get("consultado")
html(f'<div class="en-vivo"><span class="live">En vivo</span>'
     f'{f" · venta consultada a las {consultado:%H:%M}" if consultado else ""}'
     f' · se actualiza sola cada {ACTUALIZAR_CADA_MIN} min</div>')
if "fidelizacion" in df_all.attrs:
    aviso_fid, regla_bi = df_all.attrs["fidelizacion"]
    if not regla_bi:
        aviso_fid += " Mientras tanto la fidelización se calcula por RUC/DNI del cliente."
    html(f'<div class="en-vivo">{"💳" if regla_bi else "⚠️"} {aviso_fid}</div>')

# ---------- Páginas ----------
if pagina.endswith(("Ranking", "Gran Salón", "Casas", "Competencias", "Copa del Mejor Mago")):
    aviso_pronostico()

if pagina.endswith("Ranking"):
    vista_ranking()

elif pagina.endswith("Gran Salón"):
    hero()
    tarjetas_casas()
    with st.container(border=True):
        html('<div class="card-title">Ranking de tiendas</div>')
        tabla_magos(filtros_de_ranking(con_puesto(rank_all), "salon", top=10))
    kpis()
    c1, c2 = st.columns([1.5, 1], gap="medium")
    with c1, st.container(border=True):
        html('<div class="card-title">Venta diaria vs. presupuesto (canal Retail)</div>')
        st.plotly_chart(grafico_tendencia(), use_container_width=True, config={"displayModeBar": False})
    with c2, st.container(border=True):
        html('<div class="card-title">Carrera de casas · puntos promedio por mago</div>')
        st.plotly_chart(grafico_carrera(), use_container_width=True, config={"displayModeBar": False})

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
    if pronostico:
        estado = "Pronóstico" if comp == COMPETENCIAS[0] else "Por iniciar"
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
    casa_comp = st.pills("Casa", list(CASAS), key="casa_comp", label_visibility="collapsed")
    for casa in CASAS:
        if casa_comp and casa_comp != casa:
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
        tabla_magos(filtros_de_ranking(con_puesto(rank_all), "copa"))
    st.download_button("⬇️ Exportar ranking (CSV)", rank_all.to_csv(index=False).encode("utf-8"),
                       "copa_mejor_mago.csv", "text/csv")

elif pagina.endswith("Calendario de puntos"):
    filas = ""
    hoy = corte_real if pronostico else corte  # el pronóstico no cierra tramos
    for i, t in enumerate(TRAMOS):
        estado = "✅ Cerrado" if t.fin <= hoy else ("⏳ En curso" if t.inicio <= hoy else "🔒 Próximo")
        ganan = int((pt_all.loc[pt_all["tramo"] == i, "pts_venta"] > 0).sum()) if t.fin <= hoy else "–"
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
