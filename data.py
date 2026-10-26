"""Fuente de datos del concurso.

Si `.streamlit/secrets.toml` tiene [bigquery] + [gcp_service_account] (mismo formato que el
Catalog Control Center), lee la venta diaria de BigQuery. Si no, genera datos de ejemplo.

La consulta debe devolver estas columnas (una fila por tienda y día):
    fecha, tienda, venta, presupuesto, venta_ly, tickets, tickets_fidelizados, unidades
La `casa` se asigna con concurso.TIENDA_A_CASA (por nombre de tienda).
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from concurso import COMPETENCIAS, DESAFIOS_SSS, FIN, INICIO, TIENDA_A_CASA

COLUMNAS = ["fecha", "tienda", "venta", "presupuesto", "venta_ly", "tickets",
            "tickets_fidelizados", "unidades"]
FECHA_DEMO = date(2026, 12, 9)  # hasta dónde llegan los datos de ejemplo
ACTUALIZAR_CADA_MIN = 10  # cada cuánto la app se refresca sola (el caché vence 30 s antes)
LIMA = ZoneInfo("America/Lima")


# Tabla de venta retail que usa ForusIQ/Forusight (src/forusight/data/fuentes.py).
TABLA_VENTA_RETAIL = "forus-analitica-prod-datalake.silver.ft_pe_venta_retail"
# Documentos de cliente genéricos: un ticket con estos RUT no cuenta como fidelizado.
CLIENTES_GENERICOS = ("", "0", "00000000", "11111111", "99999999", "999999999")

# Venta diaria por tienda del concurso, este año y el mismo día del año pasado (364 días antes,
# mismo día de la semana). Un ticket es un nrodoc_lv distinto; fidelizado si trae cliente real.
SQL_VENTA = """
WITH dia AS (
  SELECT
    DATE(fecmov_lv) AS fecha,
    UPPER(TRIM(nombre_tienda)) AS tienda,
    SUM({col_venta}) AS venta,
    COUNT(DISTINCT nrodoc_lv) AS tickets,
    COUNT(DISTINCT IF(TRIM(IFNULL(CAST(rutcli_lv AS STRING), '')) NOT IN UNNEST(@genericos),
                      nrodoc_lv, NULL)) AS tickets_fidelizados,
    SUM(unidades_venta) AS unidades
  FROM `{tabla}`
  WHERE DATE(fecmov_lv) BETWEEN DATE_SUB(@inicio, INTERVAL 364 DAY) AND @fin
    AND UPPER(TRIM(nombre_tienda)) IN UNNEST(@tiendas)
  GROUP BY fecha, tienda
)
SELECT a.fecha, a.tienda, a.venta, IFNULL(ly.venta, 0) AS venta_ly,
       a.tickets, a.tickets_fidelizados, a.unidades
FROM dia a
LEFT JOIN dia ly ON ly.tienda = a.tienda AND ly.fecha = DATE_SUB(a.fecha, INTERVAL 364 DAY)
WHERE a.fecha BETWEEN @inicio AND @fin
"""


def config_bigquery() -> dict | None:
    """Usa los mismos secrets que Catálogo Control Center y ForusIQ ([bigquery] + [gcp_service_account])."""
    try:
        cfg = dict(st.secrets.get("bigquery", {}))
        tiene_cuenta = "gcp_service_account" in st.secrets
    except FileNotFoundError:
        return None
    if not cfg or not tiene_cuenta or not cfg.get("enabled", True):
        return None
    return cfg


def _leer_presupuesto(client, cfg: dict, bigquery, inicio: date, fin: date) -> pd.DataFrame | None:
    """Presupuesto diario por tienda: tabla configurable (fecha, tienda, presupuesto)."""
    tabla = cfg.get("presupuesto_table")
    if not tabla:
        return None
    sql = f"""
        SELECT DATE({cfg.get('presupuesto_col_fecha', 'fecha')}) AS fecha,
               UPPER(TRIM({cfg.get('presupuesto_col_tienda', 'tienda')})) AS tienda,
               SUM({cfg.get('presupuesto_col_valor', 'presupuesto')}) AS presupuesto
        FROM `{tabla}`
        WHERE DATE({cfg.get('presupuesto_col_fecha', 'fecha')}) BETWEEN @inicio AND @fin
        GROUP BY fecha, tienda"""
    return client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
        bigquery.ScalarQueryParameter("fin", "DATE", fin),
    ])).to_dataframe()


def _leer_bigquery(cfg: dict, inicio: date = INICIO, fin: date = FIN) -> pd.DataFrame:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                             credentials=cred, location=cfg.get("location"))
    sql = cfg.get("ventas_query") or SQL_VENTA.format(
        tabla=cfg.get("ventas_retail_table", TABLA_VENTA_RETAIL),
        col_venta=cfg.get("ventas_col_monto", "venta_total_sin_iva"),
    )
    venta = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
        bigquery.ScalarQueryParameter("fin", "DATE", fin),
        bigquery.ArrayQueryParameter("tiendas", "STRING", list(TIENDA_A_CASA)),
        bigquery.ArrayQueryParameter("genericos", "STRING", list(CLIENTES_GENERICOS)),
    ])).to_dataframe()
    ppto = _leer_presupuesto(client, cfg, bigquery, inicio, fin)
    if ppto is None:
        # Sin tabla de presupuesto no se puede medir cumplimiento: queda en 0 y la app lo avisa
        venta["presupuesto"] = 0.0
    elif "presupuesto" not in venta:
        venta = venta.merge(ppto, on=["fecha", "tienda"], how="left")
        venta["presupuesto"] = venta["presupuesto"].fillna(0.0)
    return venta


def _ejemplo(seed: int = 7, inicio: date = INICIO, fin: date = FECHA_DEMO) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    filas = []
    dias = (fin - inicio).days + 1
    for tienda in TIENDA_A_CASA:
        base = rng.uniform(4000, 22000)
        sesgo = rng.normal(1.0, 0.05)
        for d in range(dias):
            dia = inicio + timedelta(days=d)
            factor = 1 + d * 0.012 + (0.3 if dia.weekday() >= 5 else 0)
            presupuesto = base * factor
            venta = presupuesto * rng.normal(sesgo, 0.09)
            tickets = max(int(venta / rng.normal(190, 15)), 1)
            filas.append({
                "fecha": dia, "tienda": tienda, "venta": venta, "presupuesto": presupuesto,
                "venta_ly": venta / rng.normal(1.15, 0.08),
                "tickets": tickets,
                "tickets_fidelizados": int(tickets * np.clip(rng.normal(0.66, 0.08), 0, 1)),
                "unidades": int(tickets * rng.normal(1.9, 0.15)),
            })
    return pd.DataFrame(filas)


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    df["fecha"] = pd.to_datetime(df["fecha"])
    # BigQuery entrega NUMERIC como Decimal (y enteros como Int64 con nulos): todo a float
    for col in COLUMNAS[2:]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float).fillna(0.0)
    df["tienda"] = df["tienda"].astype(str).str.strip().str.upper()
    df["casa"] = df["tienda"].map(TIENDA_A_CASA)
    df = df[df["casa"].notna()].reset_index(drop=True)
    df.attrs["consultado"] = datetime.now(LIMA)  # hora de la consulta, para mostrarla en la app
    return df


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner="Consultando la venta…")
def cargar_datos() -> tuple[pd.DataFrame, str]:
    cfg = config_bigquery()
    df, fuente = (_leer_bigquery(cfg), "BigQuery") if cfg else (_ejemplo(), "Datos de ejemplo")
    return _normalizar(df), fuente


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner="Armando el pronóstico…")
def cargar_pronostico() -> tuple[pd.DataFrame, str, date, date, bool]:
    """Antes del concurso: la venta real de los últimos días jugada como si fuera la 1ª competencia.

    Se toman los últimos N días con venta (N = días de la 1ª competencia) y se corren las fechas
    para que caigan en sus tramos, así puntos.py aplica las reglas tal cual. Devuelve también las
    fechas reales de la ventana y si el presupuesto es referencial (venta LY + desafío SSS del mes).
    """
    comp = COMPETENCIAS[0]
    n = (comp.fin - comp.inicio).days + 1
    fin = min(date.today(), INICIO) - timedelta(days=1)
    inicio = fin - timedelta(days=n + 6)  # margen por si la tabla viene con días de atraso
    cfg = config_bigquery()
    df, fuente = ((_leer_bigquery(cfg, inicio, fin), "BigQuery") if cfg
                  else (_ejemplo(inicio=inicio, fin=fin), "Datos de ejemplo"))
    df = _normalizar(df)
    if df.empty:
        return df, fuente, inicio, fin, False
    hasta = df["fecha"].max()
    desde = hasta - pd.Timedelta(days=n - 1)
    df = df[df["fecha"] >= desde].copy()  # .copy() conserva attrs["consultado"]
    df["fecha"] += pd.Timestamp(comp.inicio) - desde
    referencial = df["presupuesto"].sum() == 0
    if referencial:
        df["presupuesto"] = df["venta_ly"] * (1 + DESAFIOS_SSS.get(comp.inicio.month, 0))
    return df.reset_index(drop=True), fuente, desde.date(), hasta.date(), referencial
