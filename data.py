"""Fuente de datos del concurso.

Si `.streamlit/secrets.toml` tiene [bigquery] + [gcp_service_account] (mismo formato que el
Catalog Control Center), lee la venta diaria de BigQuery. Si no, genera datos de ejemplo.

La consulta debe devolver estas columnas (una fila por tienda y día):
    fecha, tienda, venta, presupuesto, venta_ly, tickets, tickets_fidelizados, unidades
La `casa` se asigna con concurso.TIENDA_A_CASA (por nombre de tienda).
"""
from datetime import date, datetime, timedelta
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from concurso import DESAFIOS_SSS, FIN, INICIO, TIENDA_A_CASA, TIENDAS_FID_SOLO_DNI

COLUMNAS = ["fecha", "tienda", "venta", "presupuesto", "venta_ly", "tickets",
            "tickets_fidelizados", "unidades"]
FECHA_DEMO = date(2026, 12, 9)  # hasta dónde llegan los datos de ejemplo
ACTUALIZAR_CADA_MIN = 10  # cada cuánto la app se refresca sola (el caché vence 30 s antes)
LIMA = ZoneInfo("America/Lima")


# Tabla de venta retail que usa ForusIQ/Forusight (src/forusight/data/fuentes.py).
TABLA_VENTA_RETAIL = "forus-analitica-prod-datalake.silver.ft_pe_venta_retail"
# Documentos de cliente genéricos: un ticket con estos RUT no cuenta como fidelizado.
CLIENTES_GENERICOS = ("", "0", "00000000", "11111111", "99999999", "999999999")
RUC_GENERICO_DESDE = 99999991


def sql_ruc_valido(col: str) -> str:
    """RUC/DNI de un cliente real: no vacío, no solo ceros y menor a 99999991 (los genéricos son
    99999991 en adelante). Un documento no numérico (carné de extranjería, pasaporte) cuenta como
    válido, igual que en el DAX donde VALUE() falla y vale 0."""
    r = f"TRIM(IFNULL(CAST({col} AS STRING), ''))"
    return (f"({r} != '' AND NOT REGEXP_CONTAINS({r}, r'^0+$') "
            f"AND IFNULL(SAFE_CAST({r} AS BIGNUMERIC), 0) < {RUC_GENERICO_DESDE})")

# Peruano = DNI: solo números, 8 dígitos (7 si el sistema guardó el número sin el cero inicial).
# Pasaporte (letras), carné de extranjería (9 dígitos o más) y RUC (11 dígitos) no cuentan.
def sql_dni_peruano(col: str) -> str:
    return f"REGEXP_CONTAINS(TRIM(IFNULL(CAST({col} AS STRING), '')), r'^[0-9]{{7,8}}$')"


# Correo con buen formato: usuario@dominio.ext (sin espacios, con punto y extensión de 2+ letras)
CORREO_FORMATO = r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$"

# Venta diaria por tienda del concurso, este año y el mismo día del año pasado (364 días antes,
# mismo día de la semana). Un ticket es un nrodoc_lv distinto; con RUC válido es la regla de respaldo
# de fidelización (la de Power BI pide además correo válido y sale de la tabla ventas_bi).
SQL_VENTA = """
WITH dia AS (
  SELECT
    DATE(fecmov_lv) AS fecha,
    UPPER(TRIM(nombre_tienda)) AS tienda,
    SUM({col_venta}) AS venta,
    COUNT(DISTINCT nrodoc_lv) AS tickets,
    COUNT(DISTINCT IF({ruc_valido}, nrodoc_lv, NULL)) AS tickets_fidelizados,
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
# Tablas donde buscar el correo del cliente, en orden. En Power BI la tabla es 'perucentral ventas_bi',
# que en BigQuery sigue el patrón pe_bronze.stg_pe_perucentral_* (como pedidos y locales en ForusIQ).
# Se usa la primera que tenga las columnas y ventas en el periodo; ft_pe_venta_retail entra primero
# si resulta traer el correo (así se usan exactamente los mismos tickets que la venta).
TABLAS_BI = [
    "forus-analitica-prod-datalake.pe_bronze.stg_pe_perucentral_ventas_bi",
    "forus-analitica-prod-datalake.bronze.stg_pe_central_ventas_bi",
]
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
# Fidelizado = correo válido Y RUC válido: sin columna de RUC la tabla no sirve
OBLIGATORIAS_BI = ("fecha", "tienda", "documento", "correo", "ruc")

SQL_FIDELIZACION = """
SELECT {fecha} AS fecha, UPPER(TRIM(CAST({tienda} AS STRING))) AS clave,
       COUNT(DISTINCT {ticket}) AS tickets_bi,
       COUNT(DISTINCT IF({valido}, {ticket}, NULL)) AS fidelizados_bi,
       COUNT(DISTINCT IF({dni}, {ticket}, NULL)) AS tickets_dni,
       COUNT(DISTINCT IF({dni} AND {valido} AND {correo_ok}, {ticket}, NULL)) AS fidelizados_dni
FROM `{tabla}`
WHERE {fecha} BETWEEN @inicio AND @fin
GROUP BY 1, 2
"""


def _tablas_bi(cfg: dict, tabla_venta: str) -> list[str]:
    """Candidatas en orden: la fijada en los secrets, la de venta (si trae correo) y las ventas_bi."""
    tablas = []
    if cfg.get("fidelizacion_table"):
        tablas.append(cfg["fidelizacion_table"])
    if "ventas_bi" in str(cfg.get("ventas_table", "")):
        tablas.append(cfg["ventas_table"])
    tablas += [tabla_venta] + TABLAS_BI
    return list(dict.fromkeys(t.replace("`", "") for t in tablas))


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
    """Campo → columna: la fijada en los secrets (<prefijo>_<campo>) o el primer alias que exista.

    Una columna fijada en los secrets que no existe en la tabla se ignora (antes rompía la consulta).
    """
    por_minuscula = {c.lower(): c for c in columnas}
    mapa = {}
    for campo, alias in alias_por_campo.items():
        fijo = str(cfg.get(f"{prefijo}_{campo}") or "").strip().strip("`").lower()
        if fijo in por_minuscula:
            mapa[campo] = por_minuscula[fijo]
            continue
        encontrada = next((por_minuscula[a] for a in alias if a in por_minuscula), None)
        if encontrada:
            mapa[campo] = encontrada
    return mapa


def _sql_fecha(col: str, tipo: str) -> str:
    if tipo == "STRING":  # 2026-10-26, 26/10/2026 o 20261026 (con o sin hora)
        t = f"TRIM({col})"
        return (f"COALESCE(SAFE_CAST(LEFT({t}, 10) AS DATE), SAFE.PARSE_DATE('%d/%m/%Y', LEFT({t}, 10)), "
                f"SAFE.PARSE_DATE('%Y%m%d', LEFT({t}, 8)))")
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
    condiciones.insert(0, sql_ruc_valido(f"`{mapa['ruc']}`"))
    ticket = f"CAST(`{mapa['documento']}` AS STRING)"
    if "tipo_documento" in mapa:
        ticket = f"CONCAT(IFNULL(CAST(`{mapa['tipo_documento']}` AS STRING), ''), '|', {ticket})"
    return SQL_FIDELIZACION.format(
        tabla=tabla, tienda=f"`{mapa['tienda']}`", ticket=ticket, valido=" AND ".join(condiciones),
        dni=sql_dni_peruano(f"`{mapa['ruc']}`"), correo_ok=f"REGEXP_CONTAINS({correo}, r'{CORREO_FORMATO}')",
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


def _probar_tabla_bi(client, cfg: dict, bigquery, tabla: str, params) -> tuple[pd.DataFrame | None, dict]:
    """Intenta leer la fidelización de una tabla. Devuelve (datos o None, detalle del intento)."""
    intento = {"tabla": tabla, "estado": "", "columnas": {}}
    try:
        columnas = _columnas(client, bigquery, tabla)
    except Exception as e:  # sin permiso de metadatos, tabla mal escrita, etc.
        intento["estado"] = f"no se pudo leer ({type(e).__name__})"
        return None, intento
    if not columnas:
        intento["estado"] = "no existe"
        return None, intento
    mapa = _mapear(cfg, "fidelizacion_col", ALIAS_BI, columnas)
    intento["columnas"] = mapa
    faltan = [c for c in OBLIGATORIAS_BI if c not in mapa]
    if faltan:
        intento["estado"] = f"sin columna de {', '.join(faltan)}"
        return None, intento
    try:
        fid = client.query(sql_fidelizacion(tabla, mapa, columnas),
                           job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    except Exception as e:
        intento["estado"] = f"falló la consulta ({type(e).__name__}: {str(e)[:160]})"
        return None, intento
    if fid.empty:
        intento["estado"] = "sin ventas en el periodo"
        return None, intento
    intento["estado"] = "en uso"
    return fid, intento


def _leer_fidelizacion(client, cfg: dict, bigquery, inicio: date, fin: date,
                       tabla_venta: str) -> tuple[pd.DataFrame | None, str, list[dict]]:
    """Fidelización por día y tienda con la regla de Power BI, de la primera tabla que sirva.

    Devuelve (datos o None, aviso, intentos): los intentos se muestran en la vista de diagnóstico.
    """
    params = [bigquery.ScalarQueryParameter("inicio", "DATE", inicio),
              bigquery.ScalarQueryParameter("fin", "DATE", fin)]
    intentos = []
    for tabla in _tablas_bi(cfg, tabla_venta):
        fid, intento = _probar_tabla_bi(client, cfg, bigquery, tabla, params)
        intentos.append(intento)
        if fid is not None:
            break
    else:
        return None, "Ninguna tabla trae el correo del cliente para el periodo.", intentos
    fid = _traducir_tiendas(client, bigquery, fid, tabla_venta, params)
    fid["fecha"] = pd.to_datetime(fid["fecha"])
    cols = ["tickets_bi", "fidelizados_bi", "tickets_dni", "fidelizados_dni"]
    for c in cols:
        fid[c] = pd.to_numeric(fid[c], errors="coerce").astype(float)
    fid = fid.groupby(["fecha", "tienda"], as_index=False)[cols].sum()
    intentos[-1]["desde"], intentos[-1]["hasta"] = fid["fecha"].min().date(), fid["fecha"].max().date()
    return fid, f"Fidelización con la regla de Power BI (correo y RUC válidos), de `{tabla}` al {fid['fecha'].max():%d/%m}.", intentos


def aplicar_fidelizacion(venta: pd.DataFrame, fid: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza tickets_fidelizados por el % de ventas_bi aplicado a los tickets de la venta.

    Los días o tiendas que ventas_bi todavía no trae (llega con atraso) quedan con la regla por RUC.
    """
    v = venta.copy()
    v["fecha"] = pd.to_datetime(v["fecha"])
    v = v.merge(fid, on=["fecha", "tienda"], how="left")
    tasa = v["fidelizados_bi"] / v["tickets_bi"].replace(0, np.nan)
    # Tiendas de turistas: % sobre las boletas con DNI peruano (un día sin ninguna queda en 0)
    solo_dni = v["tienda"].isin(TIENDAS_FID_SOLO_DNI) & v["tickets_bi"].notna()
    tasa_dni = (v["fidelizados_dni"] / v["tickets_dni"].replace(0, np.nan)).fillna(0)
    tasa = tasa.where(~solo_dni, tasa_dni)
    tickets = pd.to_numeric(v["tickets"], errors="coerce").astype(float)
    actual = pd.to_numeric(v["tickets_fidelizados"], errors="coerce").astype(float)
    # Para el diagnóstico: el resultado con la regla por RUC y qué días traen la regla de Power BI
    v["fid_ruc"] = actual
    v["con_bi"] = tasa.notna()
    v["tickets_fidelizados"] = np.where(tasa.notna(), (tickets * tasa).round(), actual)
    return v.drop(columns=["tickets_bi", "fidelizados_bi", "tickets_dni", "fidelizados_dni"])


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
    "fecha": ["fecha", "fecha_presupuesto", "fecha_ppto", "fecha_dia", "fecha_venta", "fec", "date"],
    "tienda": ["tienda", "nombre_tienda", "nombre_local", "tienda_nombre", "local_nombre", "desc_local",
               "codigo_local", "cod_local", "codigo_tienda", "cod_tienda", "nlocal_pd", "nlocal_lv",
               "nlocal", "local", "id_local", "id_tienda", "sucursal", "store"],
    "valor": ["presupuesto", "ppto", "presupuesto_venta", "ppto_venta", "venta_presupuesto",
              "monto_presupuesto", "presupuesto_sin_igv", "ppto_sin_igv", "monto_pd", "meta", "meta_venta",
              "monto", "valor", "importe", "budget"],
    # Sin columna de fecha, la fecha se arma con periodo (yyyymm) + día del mes, como en la tabla
    # de presupuesto de Perú central (periodo_pd = 202611, dia_pd = 15).
    "periodo": ["periodo_pd", "periodo", "anio_mes", "aniomes", "yyyymm", "mes_pd"],
    "dia": ["dia_pd", "dia", "dia_mes", "day"],
}
OBLIGATORIAS_PPTO = ("tienda", "valor")


def _sql_periodo_dia(periodo: str, dia: str) -> str:
    """Fecha a partir de periodo (yyyymm, o yyyymmdd) y día del mes. Un día inválido queda NULL."""
    p = f"SAFE_CAST({periodo} AS INT64)"
    return (f"(CASE WHEN {p} >= 10000000 THEN SAFE.PARSE_DATE('%Y%m%d', CAST({p} AS STRING)) "
            f"ELSE SAFE.DATE(DIV({p}, 100), MOD({p}, 100), SAFE_CAST({dia} AS INT64)) END)")


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
    faltan = [c for c in OBLIGATORIAS_PPTO if c not in mapa]
    if "fecha" not in mapa and not {"periodo", "dia"} <= set(mapa):
        faltan.insert(0, "fecha (o periodo + día)")
    if faltan:
        return None, (f"En `{tabla}` no se encontraron las columnas de {', '.join(faltan)}. "
                      f"Columnas de la tabla: {', '.join(columnas)}. Fíjalas en los secrets con "
                      f"presupuesto_col_fecha (o presupuesto_col_periodo y presupuesto_col_dia), "
                      f"presupuesto_col_tienda y presupuesto_col_valor.")
    fecha = (_sql_fecha(f"`{mapa['fecha']}`", columnas.get(mapa["fecha"], "DATE")) if "fecha" in mapa
             else _sql_periodo_dia(f"`{mapa['periodo']}`", f"`{mapa['dia']}`"))
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


# Venta BRUTA (con IGV), como la mide el concurso. Se usa la columna fijada en los secrets
# (ventas_col_monto) o la primera de esta lista que exista en la tabla.
COLS_VENTA_BRUTA = ["venta_total_con_iva", "venta_total_con_igv", "venta_con_iva", "venta_con_igv",
                    "venta_bruta", "venta_total_bruta", "venta_total"]


def _col_venta_bruta(client, bigquery, cfg: dict, tabla: str) -> str:
    fija = str(cfg.get("ventas_col_monto") or "").strip().strip("`")
    if any(x in fija.lower() for x in ("sin_iva", "sin_igv", "neta", "neto")):
        fija = ""  # el concurso se mide con venta bruta: una columna sin IGV en los secrets se ignora
    try:
        columnas = {c.lower(): c for c in _columnas(client, bigquery, tabla)}
    except Exception:  # sin permiso a INFORMATION_SCHEMA: se confía en la configurada
        return fija or COLS_VENTA_BRUTA[0]
    for c in ([fija.lower()] if fija else []) + COLS_VENTA_BRUTA:
        if c in columnas:
            return columnas[c]
    raise RuntimeError(f"`{tabla}` no tiene una columna de venta bruta ({', '.join(COLS_VENTA_BRUTA)}). "
                       "Fíjala en los secrets con ventas_col_monto.")


def _leer_bigquery(cfg: dict, inicio: date = INICIO, fin: date = FIN) -> pd.DataFrame:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                             credentials=cred, location=cfg.get("location"))
    tabla_venta = cfg.get("ventas_retail_table", TABLA_VENTA_RETAIL)
    col_monto = "" if cfg.get("ventas_query") else _col_venta_bruta(client, bigquery, cfg, tabla_venta)
    # Una ventas_query propia en los secrets también se lleva a venta bruta
    sql = str(cfg.get("ventas_query") or "").replace("venta_total_sin_iva", "venta_total_con_iva") or SQL_VENTA.format(
        tabla=tabla_venta,
        col_venta=col_monto,
        ruc_valido=sql_ruc_valido("rutcli_lv"),
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
    fid, aviso, intentos = _leer_fidelizacion(client, cfg, bigquery, inicio, fin, tabla_venta)
    if fid is not None:
        venta = aplicar_fidelizacion(venta, fid)
    else:
        venta["fid_ruc"] = pd.to_numeric(venta["tickets_fidelizados"], errors="coerce")
        venta["con_bi"] = False
    venta.attrs["fidelizacion"] = (aviso, fid is not None)
    venta.attrs["fidelizacion_intentos"] = intentos
    venta.attrs["presupuesto"] = aviso_ppto
    venta.attrs["col_venta"] = col_monto or "ventas_query de los secrets"
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


# ---------- Venta del año anterior cargada a mano (p. ej. Azaleia, sin historia en BigQuery) ----------
# Archivo con la venta BRUTA por día y tienda de las fechas del año pasado. Cada día cuenta como venta LY
# del mismo día de la semana 364 días después (igual que el SQL). Se guarda en la tabla de BigQuery
# `venta_ly_table` de los secrets, si hay; si no, en datos/venta_ly_extra.csv (versionable en el repo).
VENTA_LY_ARCHIVO = Path(__file__).parent / "datos" / "venta_ly_extra.csv"
ALIAS_LY = {
    "fecha": ["fecha", "fecha_venta", "dia", "día", "date", "fecmov_lv"],
    "tienda": ["tienda", "nombre_tienda", "local", "nombre_local", "store"],
    "venta": ["venta_bruta", "venta", "venta_total", "venta_con_igv", "venta_con_iva", "monto", "importe",
              "venta_ly"],
}


def _clave(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


_TIENDA_POR_CLAVE = {_clave(t): t for t in TIENDA_A_CASA}


def _numero(x: pd.Series) -> pd.Series:
    """Montos como número, también si vienen como texto ("S/ 1,234.50" o "1.234,50")."""
    if pd.api.types.is_numeric_dtype(x):
        return x.astype(float)
    t = x.astype(str).str.replace(r"[^\d,.\-]", "", regex=True)
    europeo = t.str.contains(r",\d{1,2}$") & ~t.str.contains(r"\.\d{1,2}$")
    t = t.where(~europeo, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    t = t.where(europeo, t.str.replace(",", "", regex=False))
    return pd.to_numeric(t, errors="coerce")


def _fecha(x: pd.Series) -> pd.Series:
    """Fechas de Excel (ya son fecha), ISO (2025-11-03) o día/mes/año (03/11/2025)."""
    if pd.api.types.is_datetime64_any_dtype(x):
        return x
    t = x.astype(str).str.strip().str[:10]
    iso = pd.to_datetime(t, format="%Y-%m-%d", errors="coerce")
    return iso.fillna(pd.to_datetime(t.where(iso.isna()), dayfirst=True, errors="coerce"))


def leer_archivo_venta_ly(archivo, nombre: str) -> tuple[pd.DataFrame, list[str]]:
    """CSV o Excel → (fecha, tienda, venta_ly) y los nombres de tienda que no son del concurso."""
    if nombre.lower().endswith((".xlsx", ".xls")):
        crudo = pd.read_excel(archivo)
    else:
        crudo = pd.read_csv(archivo, sep=None, engine="python", encoding="utf-8-sig")
    cols = {_clave(c).lower().replace(" ", "_"): c for c in crudo.columns}
    mapa = {campo: next((cols[a] for a in alias if a in cols), None) for campo, alias in ALIAS_LY.items()}
    faltan = [c for c, col in mapa.items() if col is None]
    if faltan:
        raise ValueError(f"Al archivo le faltan las columnas {', '.join(faltan)} "
                         f"(tiene: {', '.join(map(str, crudo.columns))}).")
    df = pd.DataFrame({
        "fecha": _fecha(crudo[mapa["fecha"]]),
        "clave": crudo[mapa["tienda"]].map(_clave),
        "venta_ly": _numero(crudo[mapa["venta"]]),
    })
    malas = int(df["fecha"].isna().sum() + df["venta_ly"].isna().sum())
    if malas and malas == len(df):
        raise ValueError("No se pudo leer ninguna fecha o monto del archivo.")
    df["tienda"] = df["clave"].map(_TIENDA_POR_CLAVE)
    desconocidas = sorted(df.loc[df["tienda"].isna(), "clave"].dropna().unique())
    df = df.dropna(subset=["fecha", "tienda", "venta_ly"])
    df = df.groupby([df["fecha"].dt.normalize(), "tienda"], as_index=False)["venta_ly"].sum()
    return df, desconocidas


def _cliente_bq(cfg: dict):
    from google.cloud import bigquery
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    return bigquery, bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                                     credentials=cred, location=cfg.get("location"))


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner=False)
def venta_ly_extra() -> tuple[pd.DataFrame, str]:
    """La venta LY cargada a mano y de dónde salió (tabla de BigQuery o archivo del repo)."""
    vacio = pd.DataFrame(columns=["fecha", "tienda", "venta_ly"])
    cfg = config_bigquery() or {}
    tabla = str(cfg.get("venta_ly_table") or "").strip("`")
    if tabla:
        try:
            _, client = _cliente_bq(cfg)
            df = client.query(f"SELECT fecha, tienda, venta_ly FROM `{tabla}`").to_dataframe()
            df["fecha"] = pd.to_datetime(df["fecha"])
            df["venta_ly"] = pd.to_numeric(df["venta_ly"], errors="coerce").astype(float)
            return df, f"BigQuery `{tabla}`"
        except Exception as e:
            if "Not found" not in str(e):
                return vacio, f"No se pudo leer `{tabla}`: {e}"
            return vacio, f"BigQuery `{tabla}` (todavía vacía)"
    if VENTA_LY_ARCHIVO.exists():
        df = pd.read_csv(VENTA_LY_ARCHIVO, parse_dates=["fecha"])
        return df, f"archivo `{VENTA_LY_ARCHIVO.relative_to(VENTA_LY_ARCHIVO.parent.parent)}`"
    return vacio, ""


def guardar_venta_ly(nuevo: pd.DataFrame) -> str:
    """Suma la carga a lo ya guardado (la carga nueva reemplaza los mismos días y tiendas)."""
    actual, _ = venta_ly_extra()
    todo = (pd.concat([actual, nuevo]).drop_duplicates(["fecha", "tienda"], keep="last")
            .sort_values(["tienda", "fecha"]).reset_index(drop=True))
    todo["fecha"] = pd.to_datetime(todo["fecha"]).dt.date
    cfg = config_bigquery() or {}
    tabla = str(cfg.get("venta_ly_table") or "").strip("`")
    if tabla:
        bigquery, client = _cliente_bq(cfg)
        client.load_table_from_dataframe(todo, tabla, job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            schema=[bigquery.SchemaField("fecha", "DATE"), bigquery.SchemaField("tienda", "STRING"),
                    bigquery.SchemaField("venta_ly", "FLOAT64")])).result()
        destino = f"BigQuery `{tabla}`"
    else:
        VENTA_LY_ARCHIVO.parent.mkdir(exist_ok=True)
        todo.to_csv(VENTA_LY_ARCHIVO, index=False)
        destino = "el servidor (se pierde al reiniciar la app: configura venta_ly_table en los secrets)"
    st.cache_data.clear()
    return f"Guardados {len(todo):,} días-tienda en {destino}."


def aplicar_venta_ly(df: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza venta_ly con la cargada a mano: el día D del año pasado es la LY de D + 364."""
    if extra.empty or df.empty:
        return df
    ly = extra.assign(fecha=pd.to_datetime(extra["fecha"]) + pd.Timedelta(days=364))
    ly = ly.groupby(["fecha", "tienda"], as_index=False)["venta_ly"].sum().rename(columns={"venta_ly": "_ly"})
    attrs = df.attrs
    df = df.merge(ly, on=["fecha", "tienda"], how="left")
    df["venta_ly"] = df["_ly"].where(df["_ly"].notna(), df["venta_ly"])
    df = df.drop(columns="_ly")
    df.attrs = attrs
    return df


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    df["fecha"] = pd.to_datetime(df["fecha"])
    # BigQuery entrega NUMERIC como Decimal (y enteros como Int64 con nulos): todo a float
    for col in COLUMNAS[2:]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float).fillna(0.0)
    df["tienda"] = df["tienda"].astype(str).str.strip().str.upper()
    df["casa"] = df["tienda"].map(TIENDA_A_CASA)
    df = df[df["casa"].notna()].reset_index(drop=True)
    extra, origen = venta_ly_extra()
    df = aplicar_venta_ly(df, extra)
    df.attrs["venta_ly_extra"] = (origen, len(extra))
    df.attrs["consultado"] = datetime.now(LIMA)  # hora de la consulta, para mostrarla en la app
    return df


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner="Consultando la venta…")
def cargar_datos() -> tuple[pd.DataFrame, str]:
    cfg = config_bigquery()
    df, fuente = (_leer_bigquery(cfg), "BigQuery") if cfg else (_ejemplo(), "Datos de ejemplo")
    return _normalizar(df), fuente


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner=False)
def diagnostico_venta() -> str:
    """Qué tiene la tabla de venta cuando la consulta del concurso vuelve vacía: último día cargado,
    filas desde el inicio y nombres de tienda que no cruzan con las del concurso."""
    cfg = config_bigquery()
    if not cfg:
        return ""
    if cfg.get("ventas_query"):
        return ("Ojo: en los secrets hay una `ventas_query` propia, que reemplaza la consulta a "
                f"`{cfg.get('ventas_retail_table', TABLA_VENTA_RETAIL)}`.")
    tabla = cfg.get("ventas_retail_table", TABLA_VENTA_RETAIL)
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
        client = bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                                 credentials=cred, location=cfg.get("location"))
        params = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("inicio", "DATE", INICIO),
            bigquery.ArrayQueryParameter("tiendas", "STRING", list(TIENDA_A_CASA)),
        ])
        r = client.query(f"""
            SELECT MAX(DATE(fecmov_lv)) AS ultimo_dia, MAX(fecmov_lv) AS ultimo_mov,
                   COUNTIF(DATE(fecmov_lv) >= @inicio) AS filas,
                   COUNTIF(DATE(fecmov_lv) >= @inicio
                           AND UPPER(TRIM(nombre_tienda)) IN UNNEST(@tiendas)) AS filas_tiendas,
                   ARRAY_AGG(DISTINCT IF(DATE(fecmov_lv) >= @inicio
                                         AND UPPER(TRIM(nombre_tienda)) NOT IN UNNEST(@tiendas),
                                         UPPER(TRIM(nombre_tienda)), NULL)
                             IGNORE NULLS LIMIT 8) AS otras
            FROM `{tabla}`
            WHERE DATE(fecmov_lv) >= DATE_SUB(@inicio, INTERVAL 7 DAY)""", job_config=params).result()
        f = next(iter(r))
    except Exception as e:  # el diagnóstico nunca debe tumbar la app
        return f"No se pudo revisar `{tabla}`: {e}"
    txt = (f"En `{tabla}` el último día con venta es {f.ultimo_dia:%d/%m/%Y} "
           f"(último movimiento: {f.ultimo_mov}); desde el {INICIO:%d/%m} hay {f.filas:,} filas, "
           f"{f.filas_tiendas:,} de tiendas del concurso.") if f.ultimo_dia else \
        f"`{tabla}` no tiene venta en la última semana."
    if f.otras:
        txt += " Nombres de tienda que no cruzan: " + ", ".join(f.otras) + "."
    return txt


# Simulación: la venta real de septiembre y octubre jugada como si fuera noviembre y diciembre.
# Se corre exactamente 9 semanas para que cada día caiga en el mismo día de la semana que en el
# torneo (lunes vs. lunes): arranca el domingo 30/08 → domingo 01/11 y llega al 29/10 → 31/12.
SIM_DESFASE = timedelta(weeks=9)
SIM_INICIO = INICIO - SIM_DESFASE
SIM_FIN = FIN - SIM_DESFASE


@st.cache_data(ttl=ACTUALIZAR_CADA_MIN * 60 - 30, show_spinner="Armando la simulación…")
def cargar_simulacion() -> tuple[pd.DataFrame, str, date, date, bool]:
    """El torneo completo con la venta real de set–oct, con las fechas corridas a nov–dic.

    Así puntos.py aplica las reglas tal cual (tramos, competencias, bonus). Devuelve también las
    fechas reales usadas y si el presupuesto es referencial (sin presupuesto cargado para esas
    fechas: venta LY + desafío SSS del mes simulado).
    """
    fin = min(datetime.now(LIMA).date() - timedelta(days=1), SIM_FIN)
    cfg = config_bigquery()
    df, fuente = ((_leer_bigquery(cfg, SIM_INICIO, fin), "BigQuery") if cfg
                  else (_ejemplo(inicio=SIM_INICIO, fin=fin), "Datos de ejemplo"))
    df = _normalizar(df)
    if df.empty:
        return df, fuente, SIM_INICIO, fin, False
    hasta = df["fecha"].max().date()
    df = df.copy()  # .copy() conserva attrs (hora de consulta, avisos)
    df["fecha"] += pd.Timedelta(SIM_DESFASE)
    referencial = df["presupuesto"].sum() == 0
    if referencial:
        df["presupuesto"] = df["venta_ly"] * (1 + df["fecha"].dt.month.map(DESAFIOS_SSS).fillna(0))
    return df.reset_index(drop=True), fuente, SIM_INICIO, hasta, referencial
