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


# ---------- Fidelización con la regla de Power BI ("Registro Válido") ----------
# Ticket fidelizado = el cliente dejó un correo real. Sale de la tabla que en Power BI es
# 'perucentral ventas_bi' (ft_pe_venta_retail no trae el correo). Regla, igual que el DAX:
#   ruc_cliente numérico >= 99999991 → no; correo que empieza con "be@" o contiene "ecommerce@",
#   "xxx@" o "@forus" → no; correo sin "@" → no. Mayúsculas/minúsculas no importan (SEARCH).
TABLA_VENTAS_BI = "forus-analitica-prod-datalake.bronze.stg_pe_central_ventas_bi"
RUC_GENERICO_DESDE = 99999991
CORREOS_EXCLUIDOS = r"ecommerce@|xxx@|@forus"
# Nombres posibles de cada columna; se detectan con INFORMATION_SCHEMA (como en ForusIQ) y se
# pueden fijar en los secrets con fidelizacion_col_<campo> (p. ej. fidelizacion_col_correo).
ALIAS_BI = {
    "fecha": ["fecha_transaccion", "fecha", "fecha_venta", "fecmov_lv", "fecmov", "fecha_documento",
              "fecha_emision", "fecha_comprobante", "fec_doc", "fecha_dia", "dia"],
    "tienda": ["nombre_tienda", "nombre_local", "tienda_nombre", "local_nombre", "desc_local",
               "descripcion_local", "nombre_loc", "codigo_local", "cod_local", "nlocal_lv", "nlocal",
               "local", "codigo_tienda", "cod_tienda", "id_local", "id_tienda", "tienda"],
    "documento": ["nrodoc_lv", "nrodoc", "nro_documento", "numero_documento", "num_documento",
                  "nro_doc", "num_doc", "documento", "nro_boleta", "folio", "nro_comprobante",
                  "numero_comprobante", "id_ticket", "ticket", "id_transaccion", "transaccion"],
    "tipo_documento": ["tipdoc_lv", "tipdoc", "tipo_documento", "tipo_doc", "tipo_comprobante"],
    "ruc": ["ruc_cliente", "rutcli_lv", "rut_cliente", "dni_cliente", "doc_cliente",
            "documento_cliente", "nro_documento_cliente"],
    "correo": ["correo_cliente", "email_cliente", "mail_cliente", "correo", "email", "mail"],
}
OBLIGATORIAS_BI = ("fecha", "tienda", "documento", "correo")

SQL_FIDELIZACION = """
SELECT {fecha} AS fecha, UPPER(TRIM(CAST({tienda} AS STRING))) AS clave,
       COUNT(DISTINCT {ticket}) AS tickets_bi,
       COUNT(DISTINCT IF({valido}, {ticket}, NULL)) AS fidelizados_bi
FROM `{tabla}`
WHERE {fecha} BETWEEN @inicio AND @fin
GROUP BY 1, 2
"""


def _tabla_bi(cfg: dict) -> str:
    if cfg.get("fidelizacion_table"):
        return cfg["fidelizacion_table"]
    # Si en los secrets la tabla de ventas es la ventas_bi, se usa esa
    if "ventas_bi" in str(cfg.get("ventas_table", "")):
        return cfg["ventas_table"]
    return TABLA_VENTAS_BI


def _columnas(client, bigquery, tabla: str) -> dict[str, str]:
    """Nombre → tipo de las columnas de la tabla (INFORMATION_SCHEMA)."""
    proyecto, dataset, nombre = tabla.replace("`", "").split(".")
    filas = client.query(
        f"SELECT column_name, data_type FROM `{proyecto}.{dataset}.INFORMATION_SCHEMA.COLUMNS` "
        "WHERE table_name = @t",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("t", "STRING", nombre)])).result()
    return {f.column_name: f.data_type for f in filas}


def _mapear(cfg: dict, prefijo: str, alias_por_campo: dict, columnas: dict[str, str]) -> dict[str, str]:
    """Campo → columna: la fijada en los secrets (<prefijo>_<campo>) o el primer alias que exista."""
    por_minuscula = {c.lower(): c for c in columnas}
    mapa = {}
    for campo, alias in alias_por_campo.items():
        fijo = cfg.get(f"{prefijo}_{campo}")
        if fijo:
            mapa[campo] = fijo
            continue
        encontrada = next((por_minuscula[a] for a in alias if a in por_minuscula), None)
        if encontrada:
            mapa[campo] = encontrada
    return mapa


def _sql_fecha(col: str, tipo: str) -> str:
    if tipo == "STRING":
        return f"SAFE_CAST(LEFT(TRIM({col}), 10) AS DATE)"
    if tipo in ("INT64", "NUMERIC", "BIGNUMERIC"):  # 20261025
        return f"SAFE.PARSE_DATE('%Y%m%d', CAST({col} AS STRING))"
    return f"DATE({col})"


def sql_fidelizacion(tabla: str, mapa: dict[str, str], columnas: dict[str, str]) -> str:
    correo = f"LOWER(TRIM(IFNULL(CAST(`{mapa['correo']}` AS STRING), '')))"
    condiciones = [
        f"NOT STARTS_WITH({correo}, 'be@')",
        f"NOT REGEXP_CONTAINS({correo}, r'{CORREOS_EXCLUIDOS}')",
        f"STRPOS({correo}, '@') > 0",
    ]
    if "ruc" in mapa:  # VALUE() que falla cuenta como 0 en el DAX
        condiciones.insert(0, f"IFNULL(SAFE_CAST(TRIM(CAST(`{mapa['ruc']}` AS STRING)) AS BIGNUMERIC), 0)"
                              f" < {RUC_GENERICO_DESDE}")
    ticket = f"CAST(`{mapa['documento']}` AS STRING)"
    if "tipo_documento" in mapa:
        ticket = f"CONCAT(IFNULL(CAST(`{mapa['tipo_documento']}` AS STRING), ''), '|', {ticket})"
    return SQL_FIDELIZACION.format(
        tabla=tabla, tienda=f"`{mapa['tienda']}`", ticket=ticket, valido=" AND ".join(condiciones),
        fecha=_sql_fecha(f"`{mapa['fecha']}`", columnas.get(mapa["fecha"], "DATE")))


def _codigo(x) -> str:
    s = str(x).strip().upper()
    return s.lstrip("0") or s


def _traducir_tiendas(client, bigquery, df: pd.DataFrame, tabla_venta: str, params) -> pd.DataFrame:
    """`clave` → `tienda`. Si viene por código de local, se traduce con nlocal_lv → nombre_tienda."""
    if not df["clave"].isin(list(TIENDA_A_CASA)).any():
        codigos = client.query(
            f"SELECT DISTINCT CAST(nlocal_lv AS STRING) AS cod, UPPER(TRIM(nombre_tienda)) AS tienda "
            f"FROM `{tabla_venta}` WHERE DATE(fecmov_lv) BETWEEN DATE_SUB(@fin, INTERVAL 60 DAY) AND @fin",
            job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
        nombres = {_codigo(c): t for c, t in zip(codigos["cod"], codigos["tienda"])}
        df = df.assign(clave=df["clave"].map(lambda c: nombres.get(_codigo(c), c)))
    return df.rename(columns={"clave": "tienda"})


def _leer_fidelizacion(client, cfg: dict, bigquery, inicio: date, fin: date,
                       tabla_venta: str) -> tuple[pd.DataFrame | None, str]:
    """Fidelización por día y tienda con la regla de Power BI. Devuelve (datos o None, aviso)."""
    tabla = _tabla_bi(cfg)
    try:
        columnas = _columnas(client, bigquery, tabla)
    except Exception as e:  # sin permiso de metadatos, tabla mal escrita, etc.
        return None, f"No se pudo leer `{tabla}` ({type(e).__name__})."
    if not columnas:
        return None, f"No se encontró la tabla `{tabla}`."
    mapa = _mapear(cfg, "fidelizacion_col", ALIAS_BI, columnas)
    faltan = [c for c in OBLIGATORIAS_BI if c not in mapa]
    if faltan:
        return None, (f"En `{tabla}` no se encontraron las columnas de {', '.join(faltan)}. "
                      f"Columnas de la tabla: {', '.join(columnas)}.")
    params = [bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
              bigquery.ScalarQueryParameter("fin", "DATE", fin)]
    try:
        fid = client.query(sql_fidelizacion(tabla, mapa, columnas),
                           job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    except Exception as e:
        return None, f"Falló la consulta de fidelización en `{tabla}` ({type(e).__name__}: {str(e)[:200]})."
    if fid.empty:
        return None, f"`{tabla}` no tiene ventas del {inicio:%d/%m} al {fin:%d/%m}."
    fid = _traducir_tiendas(client, bigquery, fid, tabla_venta, params)
    fid["fecha"] = pd.to_datetime(fid["fecha"])
    for c in ("tickets_bi", "fidelizados_bi"):
        fid[c] = pd.to_numeric(fid[c], errors="coerce").astype(float)
    fid = fid.groupby(["fecha", "tienda"], as_index=False)[["tickets_bi", "fidelizados_bi"]].sum()
    return fid, f"Fidelización con la regla de Power BI (correo válido), de `{tabla}` al {fid['fecha'].max():%d/%m}."


def aplicar_fidelizacion(venta: pd.DataFrame, fid: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza tickets_fidelizados por el % de ventas_bi aplicado a los tickets de la venta.

    Los días o tiendas que ventas_bi todavía no trae (llega con atraso) quedan con la regla por RUC.
    """
    v = venta.copy()
    v["fecha"] = pd.to_datetime(v["fecha"])
    v = v.merge(fid, on=["fecha", "tienda"], how="left")
    tasa = v["fidelizados_bi"] / v["tickets_bi"].replace(0, np.nan)
    tickets = pd.to_numeric(v["tickets"], errors="coerce").astype(float)
    actual = pd.to_numeric(v["tickets_fidelizados"], errors="coerce").astype(float)
    v["tickets_fidelizados"] = np.where(tasa.notna(), (tickets * tasa).round(), actual)
    return v.drop(columns=["tickets_bi", "fidelizados_bi"])


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


# Nombres posibles de las columnas de la tabla de presupuesto (se fijan con presupuesto_col_<campo>)
ALIAS_PPTO = {
    "fecha": ["fecha", "fecha_presupuesto", "fecha_ppto", "fecha_dia", "dia", "fecha_venta", "fec",
              "periodo", "date"],
    "tienda": ["tienda", "nombre_tienda", "nombre_local", "tienda_nombre", "local_nombre", "desc_local",
               "codigo_local", "cod_local", "codigo_tienda", "cod_tienda", "nlocal_lv", "nlocal", "local",
               "id_local", "id_tienda", "sucursal", "store"],
    "valor": ["presupuesto", "ppto", "presupuesto_venta", "ppto_venta", "venta_presupuesto",
              "monto_presupuesto", "presupuesto_sin_igv", "ppto_sin_igv", "meta", "meta_venta",
              "monto", "valor", "importe", "budget"],
}


def _leer_presupuesto(client, cfg: dict, bigquery, inicio: date, fin: date,
                      tabla_venta: str) -> tuple[pd.DataFrame | None, str]:
    """Presupuesto diario por tienda. Devuelve (datos o None, aviso); nunca rompe la app.

    Si la tabla trae un monto por mes (todas las fechas son día 1), se reparte parejo entre los
    días del mes.
    """
    tabla = cfg.get("presupuesto_table")
    if not tabla:
        return None, ("No hay presupuesto cargado: falta configurar `presupuesto_table` en los secrets. "
                      "Sin presupuesto no se puede calcular el cumplimiento ni los puntos por venta.")
    try:
        columnas = _columnas(client, bigquery, tabla)
    except Exception as e:
        return None, f"No se pudo leer la tabla de presupuesto `{tabla}` ({type(e).__name__})."
    if not columnas:
        return None, f"No se encontró la tabla de presupuesto `{tabla}`."
    mapa = _mapear(cfg, "presupuesto_col", ALIAS_PPTO, columnas)
    faltan = [c for c in ALIAS_PPTO if c not in mapa]
    if faltan:
        return None, (f"En `{tabla}` no se encontraron las columnas de {', '.join(faltan)}. "
                      f"Columnas de la tabla: {', '.join(columnas)}. Fíjalas en los secrets con "
                      f"presupuesto_col_fecha, presupuesto_col_tienda y presupuesto_col_valor.")
    fecha = _sql_fecha(f"`{mapa['fecha']}`", columnas.get(mapa["fecha"], "DATE"))
    sql = f"""
        SELECT {fecha} AS fecha, UPPER(TRIM(CAST(`{mapa['tienda']}` AS STRING))) AS clave,
               SUM(SAFE_CAST(`{mapa['valor']}` AS FLOAT64)) AS presupuesto
        FROM `{tabla}`
        WHERE {fecha} BETWEEN DATE_TRUNC(@inicio, MONTH) AND @fin
        GROUP BY 1, 2"""
    params = [bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
              bigquery.ScalarQueryParameter("fin", "DATE", fin)]
    try:
        ppto = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    except Exception as e:
        return None, f"Falló la consulta de presupuesto en `{tabla}` ({type(e).__name__}: {str(e)[:200]})."
    if ppto.empty:
        return None, f"`{tabla}` no tiene presupuesto del {inicio:%d/%m} al {fin:%d/%m}."
    ppto["fecha"] = pd.to_datetime(ppto["fecha"])
    ppto["presupuesto"] = pd.to_numeric(ppto["presupuesto"], errors="coerce").astype(float).fillna(0.0)
    ppto = _traducir_tiendas(client, bigquery, ppto, tabla_venta, params)
    mensual = (ppto["fecha"].dt.day == 1).all() and ppto["fecha"].dt.to_period("M").nunique() == ppto["fecha"].nunique()
    if mensual:
        dias = ppto["fecha"].map(lambda f: pd.date_range(f, f + pd.offsets.MonthEnd(0)))
        ppto["presupuesto"] = ppto["presupuesto"] / dias.map(len)
        ppto = ppto.assign(fecha=dias).explode("fecha")
        ppto["fecha"] = pd.to_datetime(ppto["fecha"])
    ppto = ppto.groupby(["fecha", "tienda"], as_index=False)["presupuesto"].sum()
    cruzan = ppto["tienda"].isin(list(TIENDA_A_CASA)).sum()
    if not cruzan:
        return None, (f"El presupuesto de `{tabla}` no cruza con ninguna tienda del concurso "
                      f"(ejemplos: {', '.join(ppto['tienda'].drop_duplicates().head(4))}).")
    return ppto, ""


def _leer_bigquery(cfg: dict, inicio: date = INICIO, fin: date = FIN) -> pd.DataFrame:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                             credentials=cred, location=cfg.get("location"))
    tabla_venta = cfg.get("ventas_retail_table", TABLA_VENTA_RETAIL)
    sql = cfg.get("ventas_query") or SQL_VENTA.format(
        tabla=tabla_venta,
        col_venta=cfg.get("ventas_col_monto", "venta_total_sin_iva"),
    )
    venta = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
        bigquery.ScalarQueryParameter("fin", "DATE", fin),
        bigquery.ArrayQueryParameter("tiendas", "STRING", list(TIENDA_A_CASA)),
        bigquery.ArrayQueryParameter("genericos", "STRING", list(CLIENTES_GENERICOS)),
    ])).to_dataframe()
    ppto, aviso_ppto = _leer_presupuesto(client, cfg, bigquery, inicio, fin, tabla_venta)
    if "presupuesto" not in venta:
        if ppto is None:
            # Sin presupuesto no se puede medir cumplimiento: queda en 0 y la app avisa por qué
            venta["presupuesto"] = 0.0
        else:
            venta["fecha"] = pd.to_datetime(venta["fecha"])
            venta = venta.merge(ppto, on=["fecha", "tienda"], how="left")
            venta["presupuesto"] = venta["presupuesto"].fillna(0.0)
    fid, aviso = _leer_fidelizacion(client, cfg, bigquery, inicio, fin, tabla_venta)
    if fid is not None:
        venta = aplicar_fidelizacion(venta, fid)
    venta.attrs["fidelizacion"] = (aviso, fid is not None)
    venta.attrs["presupuesto"] = aviso_ppto
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
