import base64
import math
import time
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import pandas as pd
import streamlit as st

from auth import auth_configurada, requerir_login, usuario
from concurso import (CASAS, COMPETENCIAS, DESAFIOS_SSS, GANADOR_2025, GANADORES_POR_CASA, INICIO,
                      MAESTROS_CC, MAESTROS_TIENDA, NOTAS_TIENDA, PREMIO_CAMPEON, RANGO_PAGO, REGLAMENTO,
                      TRAMOS, BONUS_FIDELIZACION, BONUS_SSS)
from data import ACTUALIZAR_CADA_MIN, cargar_datos, cargar_pronostico
from puntos import factor_pago, ganadores, puntos_por_tramo, ranking, resumen_casas

st.set_page_config(page_title="Forus y el Cáliz de los Campeones", page_icon="🏆", layout="wide",
                   initial_sidebar_state="collapsed")

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


def escudo(casa: str, px: int = 96) -> str:
    """Escudo recortado y cuadrado (assets/escudos/mini), liviano para repetirlo en cada fila."""
    return img_uri(f"escudos/mini/{CASAS[casa]['escudo'].rsplit('.', 1)[0]}-{px}.webp")


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
    st.warning(df_all.attrs.get("presupuesto") or
               "No hay presupuesto cargado: falta configurar `presupuesto_table` en los secrets. "
               "Sin presupuesto no se puede calcular el cumplimiento ni los puntos por venta.")
corte = df_all["fecha"].max().date()
pt_all = puntos_por_tramo(df_all, hasta=corte)
rank_all = ranking(pt_all)
casas = resumen_casas(rank_all)
comp_actual = next((c for c in COMPETENCIAS if c.inicio <= corte <= c.fin), COMPETENCIAS[-1])
# Fecha real de los datos (en el pronóstico, `corte` es la fecha simulada dentro del concurso)
corte_real = pronostico["hasta"] if pronostico else corte

# ---------- Utilidades ----------
def con_puesto(r: pd.DataFrame) -> pd.DataFrame:
    """Fija el puesto ANTES de filtrar: buscar una tienda no puede cambiar su posición."""
    return r.assign(puesto=range(1, len(r) + 1))


def _pct(x: float, signo: bool = False, dec: int = 0) -> str:
    if pd.isna(x) or math.isinf(x):
        return "–"
    # Se trunca (no se redondea): un 99.6% de cumplimiento no puede verse como "100%"
    x = math.floor(x * 10 ** (dec + 2)) / 10 ** (dec + 2)
    return f"{x:+.{dec}%}" if signo else f"{x:.{dec}%}"


def _color(casa: str) -> str:
    # Curiosity es azul casi negro: en la barra de color se aclara para que se distinga del fondo
    return "#3B5498" if casa == "Curiosity" else CASAS[casa]["color"]


@st.fragment(run_every=timedelta(minutes=ACTUALIZAR_CADA_MIN))
def auto_actualizar():
    """En vivo: cada N minutos vuelve a correr toda la app; si el caché venció, trae la venta nueva.

    El fragmento también corre en cada recarga completa: solo dispara si ya pasó el intervalo
    desde la última, para no entrar en un bucle de recargas.
    """
    if time.time() - st.session_state.get("ultima_carga", 0) >= ACTUALIZAR_CADA_MIN * 60 - 5:
        st.rerun()


# ---------- Componentes ----------
def barra_superior(casa: str | None):
    """Barra de título como la de X; toma el color de la casa elegida."""
    consultado = df_all.attrs.get("consultado")
    hora = f" · {consultado:%H:%M}" if consultado else ""
    color = _color(casa) if casa else "#5A1A1A"
    titulo = (f'<img src="{escudo(casa)}" alt="">Casa {casa}' if casa
              else '🏆 <span class="solo-pc-i">El </span>Cáliz de los Campeones')
    if pronostico:
        faltan = (INICIO - date.today()).days
        etapa = f"Pronóstico · empieza el {INICIO:%d/%m}" + (f" (faltan {faltan} días)" if faltan > 0 else "")
    else:
        dia = (corte - comp_actual.inicio).days + 1
        total = (comp_actual.fin - comp_actual.inicio).days + 1
        etapa = f"{comp_actual.nombre} · día {min(dia, total)} de {total}"
    html(f"""<div class="topbar" style="--c:{color}">
      <div class="tb-t">{titulo}</div>
      <div class="tb-r"><span class="live">En vivo{hora}</span></div>
    </div><div class="etapa">{etapa}</div>""")


def aviso_pronostico():
    if not pronostico:
        return
    comp = COMPETENCIAS[0]
    meta = (f" Sin presupuesto cargado, la meta es la venta del año pasado "
            f"+{DESAFIOS_SSS.get(comp.inicio.month, 0):.0%}.") if pronostico["referencial"] else ""
    texto = (f"🔮 Así quedaría <b>{comp.nombre}</b> con la venta real del {pronostico['desde']:%d/%m} "
             f"al {pronostico['hasta']:%d/%m}. Los puntos todavía no cuentan.{meta}")
    html(f'<div class="pronostico">{texto}</div>')


def tabla_posiciones(r: pd.DataFrame, corte_premio: int | None = None, marcar: str | None = None,
                     premio: bool = False, compacta: bool = False, titulo: str = "") -> str:
    """Tabla de posiciones estilo X: # · escudo + tienda · columnas cortas.

    En el celular solo quedan PTS y % PPTO; el resto se ve en PC. `corte_premio` dibuja la línea
    verde bajo ese puesto (los que ganan premio). `marcar` = columna booleana que pinta 🎁.
    Devuelve el HTML (para poder armar grillas de varias tablas en un solo bloque).
    """
    filas = ""
    for _, x in r.iterrows():
        pos = int(x["puesto"])
        cls = "corte" if corte_premio and pos == corte_premio else ""
        gana = '<span class="gana" title="Hoy gana premio">🎁</span>' if marcar and x.get(marcar) else ""
        nota = f'<sup title="{NOTAS_TIENDA[x["tienda"]]}">*</sup>' if x["tienda"] in NOTAS_TIENDA else ""
        cumple = "pos" if x["cumplimiento"] >= 1 else "neg"
        crece = "pos" if x["sss"] >= 0 else "neg"
        extra = "" if compacta else f"""
          <td class="n pc">{int(x['pts_venta'])}</td><td class="n pc">{int(x['pts_bonus'])}</td>
          <td class="n pc {crece}">{_pct(x['sss'], True)}</td><td class="n pc">{_pct(x['fidelizacion'])}</td>
          <td class="n pc">{x['venta']:,.0f}</td>"""
        col_premio = f'<td class="n oro">{soles(x["premio"])}</td>' if premio else ""
        filas += f"""<tr class="{cls}"><td class="num">{pos}</td>
          <td><div class="tm"><img src="{escudo(x['casa'])}" alt="{x['casa']}"><b>{x['tienda']}{nota}</b>{gana}</div></td>
          <td class="n pts">{int(x['puntos'])}</td><td class="n {cumple}">{_pct(x['cumplimiento'])}</td>
          {extra}{col_premio}</tr>"""
    th_extra = "" if compacta else ('<th class="n pc">VENTA</th><th class="n pc">BONUS</th><th class="n pc">SSS</th>'
                                    '<th class="n pc">FID</th><th class="n pc">VENTA S/</th>')
    th_premio = '<th class="n">PREMIO</th>' if premio else ""
    return f"""<div class="std-wrap">{titulo}<table class="std"><thead><tr><th class="num">#</th><th>TIENDA</th>
      <th class="n">PTS</th><th class="n">% PPTO</th>{th_extra}{th_premio}</tr></thead>
      <tbody>{filas}</tbody></table></div>"""


def panel_casas(clase: str = ""):
    """Las 5 casas en una tarjeta, como el 'Who to follow' de X."""
    filas = ""
    for i, r in casas.iterrows():
        filas += f"""<div class="pc-row" style="--c:{_color(r['casa'])}">
          <span class="pc-pos">{i + 1}</span><img src="{escudo(r['casa'])}" alt="">
          <div class="pc-nom"><b>{r['casa']}</b><small>{_pct(r['cumplimiento'])} ppto · SSS {_pct(r['sss'], True)}</small></div>
          <div class="pc-pts">{int(r['puntos']):,}<small>{r['puntos_prom']:.0f} x tienda</small></div></div>"""
    html(f'<div class="card {clase}"><div class="card-h">Casas</div>{filas}</div>')


def panel_retail():
    venta, ppto, ly = df_all["venta"].sum(), df_all["presupuesto"].sum(), df_all["venta_ly"].sum()
    cumpl = venta / ppto if ppto else 0.0
    sss = venta / ly - 1 if ly else 0.0
    meta_sss = DESAFIOS_SSS.get(corte.month, 0)
    fid = df_all["tickets_fidelizados"].sum() / max(df_all["tickets"].sum(), 1)
    f = factor_pago(cumpl)
    tiles = [
        ("Cumplimiento", f"{cumpl:.1%}", cumpl >= 1, "vs. presupuesto"),
        ("Se paga", f"{f:.0%}", f >= 1, "del premio"),
        ("SSS", f"{sss:+.1%}", sss >= meta_sss, f"meta +{meta_sss:.0%}"),
        ("Fidelización", f"{fid:.0%}", fid > BONUS_FIDELIZACION["umbral"],
         f"bonus sobre {BONUS_FIDELIZACION['umbral']:.0%}"),
    ]
    cuerpo = "".join(f'<div class="tile"><span>{l}</span><b class="{"pos" if ok else ""}">{v}</b><small>{s}</small></div>'
                     for l, v, ok, s in tiles)
    html(f'<div class="card"><div class="card-h">Canal Retail</div><div class="tiles">{cuerpo}</div></div>')


def cabecera_casa(casa: str, r: pd.DataFrame):
    res = casas.set_index("casa").loc[casa]
    puesto = int(casas.index[casas["casa"] == casa][0]) + 1
    html(f"""<div class="casa-head" style="--c:{_color(casa)}">
      <img src="{escudo(casa, 256)}" alt="{casa}">
      <div><b>Casa {casa}</b><small>{CASAS[casa]['animal']} · {len(r)} tiendas · #{puesto} de {len(casas)}</small></div>
      <div class="ch-stats"><div><b>{int(res['puntos']):,}</b><span>puntos</span></div>
        <div><b>{_pct(res['cumplimiento'])}</b><span>% ppto</span></div>
        <div><b>{_pct(res['sss'], True)}</b><span>SSS</span></div></div>
    </div>""")


def pie():
    partes = [f"Fuente: {fuente} · datos al {corte_real:%d/%m/%Y}",
              f"se actualiza sola cada {ACTUALIZAR_CADA_MIN} min"]
    if "fidelizacion" in df_all.attrs:
        aviso_fid, regla_bi = df_all.attrs["fidelizacion"]
        partes.append(("💳 " if regla_bi else "⚠️ ") + aviso_fid +
                      ("" if regla_bi else " Mientras tanto la fidelización se calcula por RUC/DNI."))
    html('<div class="pie">' + " · ".join(partes[:2]) + "<br>" + "<br>".join(partes[2:]) + "</div>")


# ---------- Vistas ----------
def vista_posiciones():
    periodos = ["Torneo", comp_actual.nombre]
    c_main, c_side = st.columns([2.3, 1], gap="large")
    with c_main:
        aviso_pronostico()
        periodo = st.segmented_control("Periodo", periodos, default=periodos[0], key="periodo",
                                       label_visibility="collapsed", width="stretch") or periodos[0]
        casa = st.segmented_control("Casa", ["Todas"] + list(CASAS), default="Todas", key="casa",
                                    label_visibility="collapsed", width="stretch") or "Todas"
        casa = None if casa == "Todas" else casa
        if periodo == periodos[0]:
            base = rank_all
        else:
            base = ranking(pt_all[pt_all["competencia"] == comp_actual.nombre])
        r = con_puesto(base[base["casa"] == casa].reset_index(drop=True) if casa else base)
        if casa:
            cabecera_casa(casa, r)
        else:
            # Las 5 casas arriba en el celular (en PC están en el panel derecho)
            panel_casas("solo-movil")
        texto = st.text_input("Buscar tienda", key="buscar", label_visibility="collapsed",
                              placeholder="🔎 Buscar tienda")
        zona = periodo != periodos[0]
        r["gana"] = (r.groupby("casa").cumcount() + 1 <= GANADORES_POR_CASA) if zona else False
        if texto.strip():
            palabras = texto.upper().split()
            r = r[r["tienda"].apply(lambda t: all(p in t for p in palabras))]
        if r.empty:
            st.caption("Ninguna tienda coincide con la búsqueda.")
        else:
            html(tabla_posiciones(r, corte_premio=GANADORES_POR_CASA if zona and casa and not texto.strip() else None,
                                  marcar="gana" if zona and not casa else None))
        nota = ("Ganan premio los 5 primeros de cada casa (línea verde)." if zona and casa else
                "🎁 = hoy está en el top 5 de su casa." if zona else
                "Copa del Mejor Mago: puntos sumando todas las competencias.")
        html(f'<div class="nota">{nota} PTS = puntos · % PPTO = venta vs. presupuesto.</div>')
    with c_side:
        panel_casas("solo-pc")
        panel_retail()


def vista_competencias():
    nombres = [c.nombre for c in COMPETENCIAS]
    sel = st.selectbox("Competencia", nombres, index=nombres.index(comp_actual.nombre),
                       label_visibility="collapsed")
    comp = COMPETENCIAS[nombres.index(sel)]
    top, cumpl, f = ganadores(pt_all, comp)
    if pronostico:
        estado = "Pronóstico" if comp == COMPETENCIAS[0] else "Por iniciar"
    else:
        estado = "Cerrada" if corte >= comp.fin else ("En curso" if corte >= comp.inicio else "Por iniciar")
    premios = " · ".join(f"{i}° {soles(p)}" for i, p in enumerate(comp.premios, 1))
    html(f"""<div class="card comp"><div><span><b>{comp.nombre}</b> <span class="chip">{estado}</span></span>
      <small>{comp.inicio:%d/%m} al {comp.fin:%d/%m} · pago {comp.pago:%d/%m} · {premios}</small></div>
      <div class="comp-pago"><b>{f:.0%}</b><small>se paga · Retail {cumpl:.1%}</small></div></div>""")
    if top.empty:
        st.info("Esta competencia todavía no tiene ventas.")
        return
    tablas = "".join(
        tabla_posiciones(top[top["casa"] == casa], premio=True, compacta=True,
                         titulo=f'<div class="grupo" style="--c:{_color(casa)}"><img src="{escudo(casa)}" alt="">Casa {casa}</div>')
        for casa in casas["casa"] if casa in set(top["casa"]))
    html(f'<div class="grilla">{tablas}</div>')
    html('<div class="nota">Part time: 50% del premio. Pago neto. Desempate: mejor % de cumplimiento.</div>')


def vista_calendario():
    hoy = corte_real if pronostico else corte  # el pronóstico no cierra tramos
    filas = ""
    for i, t in enumerate(TRAMOS):
        if t.fin <= hoy:
            estado, cls = "Cerrado", "pos"
        elif t.inicio <= hoy:
            estado, cls = "En curso", "oro"
        else:
            estado, cls = "Próximo", ""
        ganan = int((pt_all.loc[pt_all["tramo"] == i, "pts_venta"] > 0).sum()) if t.fin <= hoy else "–"
        filas += f"""<tr><td>{t.inicio:%d/%m} – {t.fin:%d/%m}</td><td class="n pts">{t.puntos}</td>
          <td class="{cls}">{estado}</td><td class="n">{ganan}</td></tr>"""
    html(f"""<div class="std-wrap"><table class="std"><thead><tr><th>TRAMO</th><th class="n">PTS</th>
      <th>ESTADO</th><th class="n">CUMPLIERON</th></tr></thead><tbody>{filas}</tbody></table></div>
      <div class="nota">Cumplir venta ≥ presupuesto en el tramo da sus puntos. Bonus por tramo:
      fidelización &gt; {BONUS_FIDELIZACION['umbral']:.0%} +{BONUS_FIDELIZACION['puntos']} · SSS &gt;
      {BONUS_SSS['umbral']:.0%} +{BONUS_SSS['puntos']}. El 25/12 no tiene tramo.</div>""")


def vista_reglas():
    rango = "".join(f"<li>Retail desde {d:.1%}: se paga el <b>{fct:.0%}</b> del premio</li>" for d, fct in RANGO_PAGO)
    desafios = "".join(f"<li>{'Noviembre' if m == 11 else 'Diciembre'}: SSS del canal +{v:.0%}</li>"
                       for m, v in DESAFIOS_SSS.items())
    html(f"""<div class="card"><div class="card-h">Reglamento</div><ol class="reglas">
      {''.join(f"<li>{r}</li>" for r in REGLAMENTO)}</ol>
      <div class="card-h">Pago según el canal</div><ul class="reglas">{rango}</ul>
      <div class="card-h">Desafíos del canal</div><ul class="reglas">{desafios}</ul>
      <div class="card-h">Copa del Mejor Mago</div><ul class="reglas"><li>{PREMIO_CAMPEON}</li>
      <li>Ganador 2025: {GANADOR_2025}</li></ul></div>""")
    filas = "".join(f"<tr><td><b>{c.nombre}</b><br><small>{c.inicio:%d/%m} – {c.fin:%d/%m} · pago {c.pago:%d/%m}</small></td>"
                    + "".join(f'<td class="n">{p:,}</td>' for p in c.premios) + "</tr>" for c in COMPETENCIAS)
    html(f"""<div class="std-wrap"><table class="std"><thead><tr><th>PREMIOS (S/)</th>
      {''.join(f'<th class="n">{i}°</th>' for i in range(1, 6))}</tr></thead><tbody>{filas}</tbody></table></div>""")
    filas = "".join(f"<tr><td><b>{cc}</b><br><small>{marcas}</small></td><td>{', '.join(m)}</td></tr>"
                    for cc, marcas, m in MAESTROS_CC)
    html(f"""<div class="std-wrap"><table class="std"><thead><tr><th>CENTRO COMERCIAL</th><th>MAESTROS</th></tr></thead>
      <tbody>{filas}</tbody></table></div>""")
    with st.expander("Maestros por tienda"):
        st.dataframe(pd.DataFrame(MAESTROS_TIENDA.items(), columns=["Tienda", "Maestro"]),
                     hide_index=True, use_container_width=True)
    if auth_configurada():
        html(f'<div class="nota">👤 {usuario()}</div>')
        if st.button("Cerrar sesión"):
            st.logout()


# ---------- Pantalla ----------
st.session_state["ultima_carga"] = time.time()
auto_actualizar()
barra_superior(st.session_state.get("casa") if st.session_state.get("casa") in CASAS
               and st.session_state.get("nav", "Posiciones") == "Posiciones" else None)
vista = st.segmented_control("Sección", ["Posiciones", "Competencias", "Calendario", "Reglas"],
                             default="Posiciones", key="nav", label_visibility="collapsed",
                             width="stretch") or "Posiciones"
if vista == "Posiciones":
    vista_posiciones()
elif vista == "Competencias":
    aviso_pronostico()
    vista_competencias()
elif vista == "Calendario":
    vista_calendario()
else:
    vista_reglas()
pie()
