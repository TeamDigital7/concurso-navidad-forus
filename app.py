import base64
import math
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from auth import auth_configurada, requerir_login, usuario
from concurso import (CASAS, COMPETENCIAS, DESAFIOS_SSS, FACTOR_PART_TIME, GANADOR_2025, GANADORES_POR_CASA, INICIO,
                      MAESTROS_CC, MAESTROS_TIENDA, NOTAS_TIENDA, PREMIO_CAMPEON, RANGO_PAGO, REGLAMENTO,
                      TRAMOS, BONUS_FIDELIZACION, BONUS_SSS)
from data import ACTUALIZAR_CADA_MIN, SIM_DESFASE, cargar_datos, cargar_simulacion
from puntos import factor_pago, ganadores, puntos_por_tramo, ranking, resumen_casas

st.set_page_config(page_title="Forus y el Cáliz de los Campeones", page_icon="🏆", layout="wide",
                   initial_sidebar_state="collapsed")

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
st.markdown(f"<style>{(ASSETS / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def html(s: str):
    # Se quitan los saltos/sangrías para que Markdown no lo trate como bloque de código
    # Unidas con espacio: un texto partido en dos líneas no debe quedar pegado ("tramocada")
    st.markdown(" ".join(line.strip() for line in s.splitlines()), unsafe_allow_html=True)


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
# Simulación: el torneo completo jugado con la venta real de septiembre y octubre (corrida 9 semanas
# para que cada día caiga en el mismo día de la semana que en el torneo). Antes del 01/11 es lo que se ve; después queda como opción en el
# interruptor de arriba. El link ?simulacion=1 la abre directo.
def _sincronizar_link():
    if st.session_state["simulacion"]:
        st.query_params["simulacion"] = "1"
    else:
        st.query_params.pop("simulacion", None)


def interruptor_simulacion():
    st.toggle("🔮 Simulación con la venta real de septiembre y octubre", key="simulacion",
              on_change=_sincronizar_link,
              help="Juega todo el torneo con la venta real de set–oct, día de la semana contra día de la "
                   "semana: el domingo 30/08 cuenta como el domingo 01/11.")


if "simulacion" not in st.session_state:
    st.session_state["simulacion"] = date.today() < INICIO or st.query_params.get("simulacion") == "1"
simulacion = None
desfase = timedelta(0)
if st.session_state["simulacion"]:
    df_all, fuente, s_desde, s_hasta, s_referencial = cargar_simulacion()
    simulacion = {"desde": s_desde, "hasta": s_hasta, "referencial": s_referencial}
    desfase = SIM_DESFASE
else:
    df_all, fuente = cargar_datos()
if df_all.empty:
    interruptor_simulacion()
    st.info(f"Fuente: {fuente}. Todavía no hay ventas del concurso (empieza el {INICIO:%d/%m/%Y}). "
            "Activa la simulación para ver el torneo con la venta real de septiembre y octubre.")
    st.stop()
if df_all["presupuesto"].sum() == 0:
    st.warning(df_all.attrs.get("presupuesto") or
               "No hay presupuesto cargado: falta configurar `presupuesto_table` en los secrets. "
               "Sin presupuesto no se puede calcular el cumplimiento ni los puntos por venta.")
corte = df_all["fecha"].max().date()
# Último día ya terminado: un tramo suma puntos recién cuando su último día cerró. Si BigQuery trae
# venta del día en curso, ese día no cierra tramos (quedaría con la venta a medias). En la
# simulación todos los días ya pasaron.
ayer = (datetime.now(ZoneInfo("America/Lima")) - timedelta(days=1)).date()
cierre = corte if simulacion else min(corte, ayer)
pt_all = puntos_por_tramo(df_all, hasta=cierre)
rank_all = ranking(pt_all)
casas = resumen_casas(rank_all)
comp_actual = next((c for c in COMPETENCIAS if c.inicio <= corte <= c.fin), COMPETENCIAS[-1])

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


def selector(etiqueta: str, opciones: list[str], clave: str) -> str:
    """Selector segmentado que no se puede dejar vacío: tocar la opción activa la mantiene.

    st.segmented_control deselecciona al tocar la opción ya elegida (queda en None y pierde el
    resaltado); el callback devuelve la última opción elegida.
    """
    ultima = f"_ultima_{clave}"

    def _mantener():
        if st.session_state.get(clave) is None:
            st.session_state[clave] = st.session_state.get(ultima, opciones[0])

    valor = st.segmented_control(etiqueta, opciones, default=opciones[0], key=clave, on_change=_mantener,
                                 label_visibility="collapsed", width="stretch") or opciones[0]
    st.session_state[ultima] = valor
    return valor


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
    """Barra de título como la de X, sobre el castillo de la portada; toma el color de la casa elegida."""
    consultado = df_all.attrs.get("consultado")
    hora = f'<span class="solo-pc-i"> · </span>{consultado:%H:%M}' if consultado else ""
    color = _color(casa) if casa else "#5A1A1A"
    titulo = (f'<img src="{escudo(casa)}" alt="">Casa {casa}' if casa
              else (f'<img src="{img_uri("caliz.png")}" alt="">' if img_uri("caliz.png") else "🏆")
              + ' <span class="solo-pc-i">El </span>Cáliz de los Campeones')
    dia = (corte - comp_actual.inicio).days + 1
    total = (comp_actual.fin - comp_actual.inicio).days + 1
    etapa = f"⚡ {comp_actual.nombre} · día {min(dia, total)} de {total}"
    if simulacion:
        etapa = f"🔮 Simulación · {etapa}"
    # Banda y cáliz: si están las imágenes nuevas en assets/ (banda.jpg, caliz.png) se usan esas
    banda = img_uri("banda.jpg") or img_uri("portada-banda.jpg")
    html(f"""<div class="topbar" style="--c:{color}; --portada:url('{banda}')">
      <div class="tb-t">{titulo}</div>
      <div class="tb-r"><span class="live"><span class="solo-pc-i">En vivo</span>{hora}</span></div>
    </div><div class="etapa">{etapa}</div>""")


def aviso_simulacion():
    if not simulacion:
        return
    hasta_sim = simulacion["hasta"] + desfase
    meta = (" Sin presupuesto cargado para esas fechas, la meta es la venta del año pasado + el desafío "
            "SSS del mes.") if simulacion["referencial"] else ""
    texto = (f"🔮 <b>La profecía:</b> el torneo jugado con la venta real del {simulacion['desde']:%d/%m} al "
             f"{simulacion['hasta']:%d/%m} (el domingo {simulacion['desde']:%d/%m} cuenta como el domingo {INICIO:%d/%m}, día de la semana contra día de la semana; "
             f"llega hasta el {hasta_sim:%d/%m} del torneo). Los puntos no cuentan.{meta}")
    html(f'<div class="pronostico">{texto}</div>')


def tabla_posiciones(r: pd.DataFrame, corte_premio: int | None = None,
                     compacta: bool = False, titulo: str = "") -> str:
    """Tabla de posiciones estilo X: # · escudo + tienda · columnas cortas.

    En el celular la tabla se cambia por una lista desplegable: cada mago muestra PTS y % PPTO y, al
    tocarlo, se abren todos sus campos. `corte_premio` dibuja la línea verde bajo ese puesto (los
    que ganan premio).
    Devuelve el HTML (para poder armar grillas de varias tablas en un solo bloque).
    """
    filas = tarjetas = ""
    for _, x in r.iterrows():
        pos = int(x["puesto"])
        cls = "corte" if corte_premio and pos == corte_premio else ""
        nota = f'<sup title="{NOTAS_TIENDA[x["tienda"]]}">*</sup>' if x["tienda"] in NOTAS_TIENDA else ""
        cumple = "pos" if x["cumplimiento"] >= 1 else "neg"
        crece = "pos" if x["sss"] >= 0 else "neg"
        extra = "" if compacta else f"""
          <td class="n pc">{int(x['pts_venta'])}</td><td class="n pc">{int(x['pts_bonus'])}</td>
          <td class="n pc {crece}">{_pct(x['sss'], True)}</td><td class="n pc">{_pct(x['fidelizacion'])}</td>
          <td class="n pc">{x['venta']:,.0f}</td>"""
        sello = f'<span class="sello s{pos}">{pos}</span>' if pos <= 3 else pos
        filas += f"""<tr class="{cls}"><td class="num">{sello}</td>
          <td><div class="tm"><img src="{escudo(x['casa'])}" alt="{x['casa']}"><b>{x['tienda']}{nota}</b></div></td>
          <td class="n pts">{int(x['puntos'])}</td><td class="n {cumple}">{_pct(x['cumplimiento'])}</td>
          {extra}</tr>"""
        tarjetas += f"""<details class="fila {cls}"><summary><span class="num">{sello}</span>
          <div class="tm"><img src="{escudo(x['casa'])}" alt="{x['casa']}"><b>{x['tienda']}{nota}</b></div>
          <span class="n pts">{int(x['puntos'])}</span><span class="n {cumple}">{_pct(x['cumplimiento'])}</span></summary>
          <div class="det">
            <div><span>Puntos por venta</span><b>{int(x['pts_venta'])}</b></div>
            <div><span>Puntos bonus</span><b>{int(x['pts_bonus'])}</b></div>
            <div><span>% Presupuesto</span><b class="{cumple}">{_pct(x['cumplimiento'], dec=1)}</b></div>
            <div><span>SSS</span><b class="{crece}">{_pct(x['sss'], True, 1)}</b></div>
            <div><span>Fidelización</span><b>{_pct(x['fidelizacion'], dec=1)}</b></div>
            <div><span>Casa</span><b>{x['casa']}</b></div>
            <div><span>Venta</span><b>{soles(x['venta'])}</b></div>
            <div><span>Presupuesto</span><b>{soles(x['presupuesto'])}</b></div>
          </div></details>"""
    th_extra = "" if compacta else ('<th class="n pc">VENTA</th><th class="n pc">BONUS</th><th class="n pc">SSS</th>'
                                    '<th class="n pc">FID</th><th class="n pc">VENTA S/</th>')
    return f"""<div class="std-wrap">{titulo}<table class="std tabla-pc"><thead><tr><th class="num">#</th><th>MAGO</th>
      <th class="n">PTS</th><th class="n">% PPTO</th>{th_extra}</tr></thead>
      <tbody>{filas}</tbody></table>
      <div class="lista-movil"><div class="lm-cab"><span>#</span><span>MAGO · toca para ver el detalle</span>
        <span class="n">PTS</span><span class="n">% PPTO</span></div>{tarjetas}</div></div>"""


def relojes_casas() -> str:
    """Los relojes de arena de la Copa de las Casas: las gemas suben con los puntos de cada casa."""
    tope = max(casas["puntos"].max(), 1)
    relojes = "".join(f"""<div class="reloj" style="--c:{_color(r['casa'])}; --h:{max(r['puntos'] / tope, .04):.0%}">
        <div class="tubo"><div class="gemas"></div></div><img src="{escudo(r['casa'])}" alt="{r['casa']}">
        <b>{int(r['puntos']):,}</b></div>""" for _, r in casas.iterrows())
    return f'<div class="relojes">{relojes}</div>'


def panel_casas(clase: str = ""):
    """Las 5 casas en una tarjeta, como el 'Who to follow' de X, con sus relojes de arena."""
    filas = ""
    for i, r in casas.iterrows():
        filas += f"""<div class="pc-row" style="--c:{_color(r['casa'])}">
          <span class="pc-pos">{i + 1}</span><img src="{escudo(r['casa'])}" alt="">
          <div class="pc-nom"><b>{r['casa']}</b><small>{_pct(r['cumplimiento'])} ppto · SSS {_pct(r['sss'], True)}</small></div>
          <div class="pc-pts">{int(r['puntos']):,}<small>{r['puntos_prom']:.0f} x mago</small></div></div>"""
    html(f'<div class="card {clase}"><div class="card-h">Copa de las Casas</div>{relojes_casas()}{filas}</div>')


def panel_retail(clase: str = ""):
    venta, ppto, ly = df_all["venta"].sum(), df_all["presupuesto"].sum(), df_all["venta_ly"].sum()
    cumpl = venta / ppto if ppto else 0.0
    sss = df_all["venta"].where(df_all["venta_ly"] > 0, 0).sum() / ly - 1 if ly else 0.0  # días comparables
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
    html(f'<div class="card {clase}"><div class="card-h">Canal Retail</div><div class="tiles">{cuerpo}</div></div>')


def cabecera_casa(casa: str, r: pd.DataFrame):
    res = casas.set_index("casa").loc[casa]
    puesto = int(casas.index[casas["casa"] == casa][0]) + 1
    html(f"""<div class="casa-head" style="--c:{_color(casa)}">
      <img src="{escudo(casa, 256)}" alt="{casa}">
      <div><b>Casa {casa}</b><small>{CASAS[casa]['animal']} · {len(r)} magos · #{puesto} de {len(casas)}</small></div>
      <div class="ch-stats"><div><b>{int(res['puntos']):,}</b><span>puntos</span></div>
        <div><b>{_pct(res['cumplimiento'])}</b><span>% ppto</span></div>
        <div><b>{_pct(res['sss'], True)}</b><span>SSS</span></div></div>
    </div>""")


def pie():
    # Solo el cierre: la fuente y los avisos técnicos (fidelización) no se muestran al equipo
    html('<div class="pie"><div class="travesura">✨ Travesura realizada ✨</div></div>')


# ---------- Vistas ----------
ACUMULADO = "Torneo completo · acumulado"


def _estado_comp(c) -> str:
    return "cerrada" if cierre >= c.fin else ("en curso" if corte >= c.inicio else "por iniciar")


def selector_periodo() -> str:
    """Desplegable: el acumulado del torneo (Copa del Mejor Mago) o cada competencia por su nombre."""
    opciones = [ACUMULADO] + [c.nombre for c in COMPETENCIAS]
    if st.session_state.get("periodo") not in opciones:  # sesiones con el selector anterior
        st.session_state.pop("periodo", None)

    def _etiqueta(o: str) -> str:
        if o == ACUMULADO:
            return "🏆 Acumulado · Copa del Mejor Mago"
        c = next(c for c in COMPETENCIAS if c.nombre == o)
        return f"⚡ {c.nombre} ({c.inicio:%d/%m}–{c.fin:%d/%m}) · {_estado_comp(c)}"

    return st.selectbox("Periodo", opciones, key="periodo", format_func=_etiqueta,
                        label_visibility="collapsed")


def vista_posiciones():
    c_main, c_side = st.columns([2.3, 1], gap="large")
    with c_main:
        aviso_simulacion()
        # Celular: Canal Retail arriba, luego la tabla y las casas al final (en PC van a la derecha)
        panel_retail("solo-movil")
        periodo = selector_periodo()
        casa = selector("Casa", ["Todas"] + list(CASAS), "casa")
        casa = None if casa == "Todas" else casa
        zona = periodo != ACUMULADO
        base = ranking(pt_all[pt_all["competencia"] == periodo]) if zona else rank_all
        r = con_puesto(base[base["casa"] == casa].reset_index(drop=True) if casa else base)
        if casa:
            cabecera_casa(casa, r)
        texto = st.text_input("Buscar tienda", key="buscar", label_visibility="collapsed",
                              placeholder="🔎 Buscar mago (tienda)")
        if texto.strip():
            palabras = texto.upper().split()
            r = r[r["tienda"].apply(lambda t: all(p in t for p in palabras))]
        if base.empty:
            st.caption(f"{periodo} todavía no empieza: aquí aparecerá su ranking.")
        elif r.empty:
            st.caption("Ninguna tienda coincide con la búsqueda.")
        else:
            html(tabla_posiciones(r, corte_premio=GANADORES_POR_CASA if zona and casa and not texto.strip() else None))
        nota = (f"{periodo}: ganan premio los 5 primeros de cada casa (línea verde)." if zona and casa else
                f"{periodo}: ganan los 5 primeros de cada casa (elige una casa para ver el corte)." if zona else
                "Copa del Mejor Mago: puntos sumando todas las competencias.")
        html(f'<div class="nota">{nota} PTS = puntos · % PPTO = venta vs. presupuesto.</div>')
        if not casa:
            panel_casas("solo-movil")
    with c_side:
        panel_casas("solo-pc")
        panel_retail("solo-pc")


def vista_competencias():
    nombres = [c.nombre for c in COMPETENCIAS]
    sel = st.selectbox("Competencia", nombres, index=nombres.index(comp_actual.nombre),
                       label_visibility="collapsed")
    comp = COMPETENCIAS[nombres.index(sel)]
    top, cumpl, f = ganadores(pt_all, comp)
    estado = "Cerrada" if cierre >= comp.fin else ("En curso" if corte >= comp.inicio else "Por iniciar")
    if simulacion:
        estado += " (simulación)"
    html(f"""<div class="card comp"><div><span><b>{comp.nombre}</b> <span class="chip">{estado}</span></span>
      <small>{comp.inicio:%d/%m} al {comp.fin:%d/%m} · pago {comp.pago:%d/%m}</small></div>
      <div class="comp-pago"><b>{f:.0%}</b><small>se paga · Retail {cumpl:.1%}</small></div></div>""")
    if top.empty:
        st.info("Esta competencia todavía no tiene ventas.")
        return
    tablas = "".join(
        tabla_posiciones(top[top["casa"] == casa], compacta=True,
                         titulo=f'<div class="grupo" style="--c:{_color(casa)}"><img src="{escudo(casa)}" alt="">Casa {casa}</div>')
        for casa in casas["casa"] if casa in set(top["casa"]))
    html(f'<div class="grilla">{tablas}</div>')
    html('<div class="nota">Part time: 50% del premio. Pago neto. Desempate: mejor % de cumplimiento.</div>')


def vista_calendario():
    hoy = cierre
    filas = ""
    # Hasta qué día llegó el dato de correo (ventas_bi): el bonus de fidelización de un tramo
    # cerrado espera a que estén todos sus días
    con_correo = df_all.loc[df_all["con_bi"].fillna(False).astype(bool), "fecha"] if "con_bi" in df_all else None
    for i, t in enumerate(TRAMOS):
        if t.fin <= hoy:
            estado, cls = "Cerrado", "pos"
        elif t.inicio <= corte:
            estado, cls = "En curso", "oro"
        else:
            estado, cls = "Próximo", ""
        tramo = pt_all[pt_all["tramo"] == i]
        ganan = int((tramo["pts_venta"] > 0).sum()) if t.fin <= hoy else "–"
        if t.fin > hoy:
            fid, fcls = "–", ""
        elif tramo["fid_pendiente"].any():
            fid, fcls = "⏳ Falta correo", "oro"
        else:
            fid, fcls = f"✓ {int((tramo['pts_fidelizacion'] > 0).sum())} magos", "pos"
        filas += f"""<tr><td>{t.inicio:%d/%m} – {t.fin:%d/%m}</td><td class="n pts">{t.puntos}</td>
          <td class="{cls}">{estado}</td><td class="n">{ganan}</td><td class="{fcls}">{fid}</td></tr>"""
    if con_correo is None:
        aviso_correo = ""
    elif con_correo.empty:
        aviso_correo = " Todavía no hay datos de correo: el bonus de fidelización está en espera."
    else:
        aviso_correo = f" Datos de correo cargados hasta el <b>{con_correo.max():%d/%m}</b>."
    html(f"""<div class="std-wrap"><table class="std"><thead><tr><th>TRAMO</th><th class="n">PTS</th>
      <th>ESTADO</th><th class="n">CUMPLIERON</th><th>BONUS FIDELIZ.</th></tr></thead><tbody>{filas}</tbody></table></div>
      <div class="nota">Cumplir venta ≥ presupuesto en el tramo da sus puntos. Bonus por tramo:
      fidelización &gt; {BONUS_FIDELIZACION['umbral']:.0%} +{BONUS_FIDELIZACION['puntos']} · SSS &gt;
      {BONUS_SSS['umbral']:.0%} +{BONUS_SSS['puntos']}. El 25/12 no tiene tramo.
      El bonus de fidelización se otorga cuando están los datos de correo de todos los días del tramo
      (⏳ = todavía faltan).{aviso_correo}</div>""")


def como_se_ganan_puntos():
    """Explicación de los puntos armada con las mismas constantes que usa el cálculo (concurso.py)."""
    pts_tramos = sum(t.puntos for t in TRAMOS)
    bonus_tramo = BONUS_FIDELIZACION["puntos"] + BONUS_SSS["puntos"]
    valores = " · ".join(str(t.puntos) for t in TRAMOS)
    filas_comp = ""
    for c in COMPETENCIAS:
        ts = [t for t in TRAMOS if c.inicio <= t.inicio <= c.fin]
        venta = sum(t.puntos for t in ts)
        filas_comp += f"""<tr><td><b>{c.nombre}</b><br><small>{c.inicio:%d/%m} – {c.fin:%d/%m}</small></td>
          <td class="n">{len(ts)}</td><td>{" · ".join(str(t.puntos) for t in ts)}</td>
          <td class="n pts">{venta + bonus_tramo * len(ts)}</td></tr>"""
    pago = "".join(f'<tr><td>Desde {d:.1%}</td><td class="n pts">{f:.0%}</td></tr>' for d, f in RANGO_PAGO)
    ej = TRAMOS[3]
    html(f"""<div class="card"><div class="card-h">¿Cómo se ganan los puntos?</div>
      <p class="reglas-p">El torneo (01/11 al 31/12) se divide en <b>{len(TRAMOS)} tramos</b> de 2 a 5 días. En cada tramo
      cada mago se mide con la <b>suma de esos días</b> y los puntos se ganan <b>cuando el tramo cierra</b>
      (mientras está en curso, suma 0). Cada condición es de todo o nada.</p>
      <div class="std-wrap interior"><table class="std"><thead><tr><th>EN CADA TRAMO</th><th>CONDICIÓN</th>
        <th class="n">PUNTOS</th></tr></thead><tbody>
        <tr><td><b>Puntos por venta</b></td><td>Venta ≥ presupuesto (cumplimiento ≥ 100%)</td>
          <td class="n pts">{min(t.puntos for t in TRAMOS)} a {max(t.puntos for t in TRAMOS)}</td></tr>
        <tr><td><b>Bonus fidelización</b></td><td>Más del {BONUS_FIDELIZACION['umbral']:.0%} de tickets con correo y RUC/DNI válidos.
          Se otorga cuando están los datos de correo de todos los días del tramo</td>
          <td class="n pts">+{BONUS_FIDELIZACION['puntos']}</td></tr>
        <tr><td><b>Bonus SSS</b></td><td>Crecer más de {BONUS_SSS['umbral']:.0%} vs. el año pasado (mismo día de la semana,
          solo días con venta en los dos años)</td><td class="n pts">+{BONUS_SSS['puntos']}</td></tr>
      </tbody></table></div>
      <p class="reglas-p">Los tramos valen más hacia el final: <b>{valores}</b>. El 25/12 no tiene tramo.</p>
      <p class="reglas-p"><b>Ejemplo:</b> en el tramo del {ej.inicio:%d/%m} al {ej.fin:%d/%m} (vale {ej.puntos}), un mago con
      105% de cumplimiento, 72% de fidelización y SSS de +8% gana {ej.puntos} + {BONUS_FIDELIZACION['puntos']} + 0 =
      <b>{ej.puntos + BONUS_FIDELIZACION['puntos']} puntos</b>.</p></div>""")
    html(f"""<div class="std-wrap"><table class="std"><thead><tr><th>COMPETENCIA</th><th class="n">TRAMOS</th>
      <th>PUNTOS POR TRAMO</th><th class="n">MÁXIMO</th></tr></thead><tbody>{filas_comp}</tbody></table></div>""")
    html(f"""<div class="card"><div class="card-h">¿Quién gana?</div><ul class="reglas">
      <li><b>Cada competencia:</b> sus puntos son la suma de sus tramos. Ganan los <b>{GANADORES_POR_CASA} magos con más
        puntos de cada casa</b>. Empate: gana el de mejor % de cumplimiento.</li>
      <li><b>Copa del Mejor Mago:</b> el acumulado de todas las competencias (máximo
        {pts_tramos + bonus_tramo * len(TRAMOS)} puntos). Es la vista «Torneo completo · acumulado».</li>
      <li><b>Copa de las Casas:</b> la suma de los puntos de todos los magos de la casa (los relojes de arena). Como las
        casas tienen distinta cantidad de tiendas, también se muestra el promedio por mago.</li>
      <li>Los part time reciben el {FACTOR_PART_TIME:.0%} del premio.</li></ul>
      <div class="card-h">¿Cuánto del premio se paga?</div>
      <p class="reglas-p">Depende del cumplimiento de <b>todo el canal Retail</b> en la competencia (el «Se paga» de la app).
      Por debajo de {RANGO_PAGO[0][0]:.0%} no hay premio.</p>
      <div class="std-wrap interior"><table class="std"><thead><tr><th>CUMPLIMIENTO DEL CANAL</th>
        <th class="n">SE PAGA</th></tr></thead><tbody>{pago}</tbody></table></div></div>""")


# Material oficial del concurso para descargar desde Reglas: se muestra un botón por cada archivo
# que exista en assets/ (el PPT y, si se sube, su versión en PDF, que se abre mejor en el celular).
DESCARGAS = [
    ("concurso.pptx", "📥 Descargar el PPT del concurso",
     "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("concurso.pdf", "📥 Descargar la presentación del concurso (PDF)", "application/pdf"),
]


def descargas_concurso():
    archivos = [(ASSETS / n, n, t, m) for n, t, m in DESCARGAS if (ASSETS / n).exists()]
    if not archivos:
        return
    html('<div class="card-h descargas-h">Material del concurso</div>')
    cols = st.columns(len(archivos))
    for col, (ruta, nombre, texto, mime) in zip(cols, archivos):
        with col:
            st.download_button(texto, ruta.read_bytes(), file_name=f"Forus-Caliz-de-los-Campeones-{nombre}",
                               mime=mime, use_container_width=True, type="primary", key=f"dl_{nombre}")


def vista_reglas():
    descargas_concurso()
    como_se_ganan_puntos()
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


def _rango(intento: dict) -> str:
    if "desde" not in intento:
        return "–"
    return f"{intento['desde']:%d/%m} – {intento['hasta']:%d/%m}"


def vista_diagnostico():
    """De dónde sale la fidelización y su % por tienda con las dos reglas, para cuadrar con Power BI."""
    aviso, regla_bi = df_all.attrs.get("fidelizacion", ("Datos de ejemplo: sin consulta a BigQuery.", False))
    real = (simulacion["desde"], simulacion["hasta"]) if simulacion else (df_all["fecha"].min().date(), corte)
    html(f"""<div class="card"><div class="card-h">Fidelización · de dónde sale</div>
      <p class="reglas-p">{"✅" if regla_bi else "⚠️"} {aviso}</p>
      <p class="reglas-p">Ventas del {real[0]:%d/%m/%Y} al {real[1]:%d/%m/%Y}{" (simulación)" if simulacion else ""}.
      Regla de Power BI: el ticket cuenta solo si tiene <b>correo válido</b> (con @, sin <i>be@</i>, <i>ecommerce@</i>,
      <i>xxx@</i> ni <i>@forus</i>) <b>y RUC/DNI válido</b> (no vacío, no solo ceros y menor a 99999991). Regla de
      respaldo (días sin tabla con correo): solo el RUC/DNI válido.</p></div>""")
    intentos = df_all.attrs.get("fidelizacion_intentos", [])
    if intentos:
        filas = "".join(
            f"<tr><td><b>{i['tabla']}</b></td><td class='{'pos' if i['estado'] == 'en uso' else 'neg'}'>{i['estado']}</td>"
            f"<td><small>{', '.join(f'{k}: {v}' for k, v in i.get('columnas', {}).items()) or '–'}</small></td>"
            f"<td>{_rango(i)}</td></tr>"
            for i in intentos)
        html(f"""<div class="std-wrap interior"><table class="std"><thead><tr><th>TABLA PROBADA</th><th>RESULTADO</th>
          <th>COLUMNAS USADAS</th><th>FECHAS</th></tr></thead><tbody>{filas}</tbody></table></div>""")
    d = df_all.copy()
    if "fid_ruc" not in d:
        d["fid_ruc"], d["con_bi"] = d["tickets_fidelizados"], False
    t = d.groupby(["tienda", "casa"], as_index=False).agg(
        tickets=("tickets", "sum"), fidelizados=("tickets_fidelizados", "sum"), fid_ruc=("fid_ruc", "sum"),
        dias=("fecha", "nunique"), dias_bi=("con_bi", "sum"))
    t["% fidelización (app)"] = t["fidelizados"] / t["tickets"].replace(0, np.nan)
    t["% regla RUC"] = t["fid_ruc"] / t["tickets"].replace(0, np.nan)
    t["días con regla Power BI"] = t["dias_bi"].astype(int).astype(str) + " de " + t["dias"].astype(str)
    t = t.sort_values(["casa", "tienda"])[["casa", "tienda", "tickets", "% fidelización (app)", "% regla RUC",
                                          "días con regla Power BI"]]
    html('<div class="card-h">Fidelización por tienda (todo el periodo)</div>')
    st.dataframe(t, hide_index=True, use_container_width=True,
                 column_config={"% fidelización (app)": st.column_config.NumberColumn(format="percent"),
                                "% regla RUC": st.column_config.NumberColumn(format="percent")})
    st.download_button("⬇️ Descargar para comparar con Power BI (CSV)", t.to_csv(index=False).encode("utf-8"),
                       "fidelizacion_por_tienda.csv", "text/csv")


# ---------- Pantalla ----------
st.session_state["ultima_carga"] = time.time()
auto_actualizar()
barra_superior(st.session_state.get("casa") if st.session_state.get("casa") in CASAS
               and st.session_state.get("nav", "Posiciones") == "Posiciones" else None)
interruptor_simulacion()
# La vista de diagnóstico solo aparece con el link ?diagnostico=1 (para quien revisa los datos)
secciones = ["Posiciones", "Competencias", "Calendario", "Reglas"]
if st.query_params.get("diagnostico") == "1":
    secciones.append("Diagnóstico")
vista = selector("Sección", secciones, "nav")
if vista == "Posiciones":
    vista_posiciones()
elif vista == "Competencias":
    aviso_simulacion()
    vista_competencias()
elif vista == "Calendario":
    vista_calendario()
elif vista == "Diagnóstico":
    vista_diagnostico()
else:
    vista_reglas()
pie()
