"""Fuente de datos del concurso.

Si `.streamlit/secrets.toml` tiene [bigquery] + [gcp_service_account] (mismo formato que el
Catalog Control Center), lee la venta diaria de BigQuery. Si no, genera datos de ejemplo.

La consulta debe devolver estas columnas (una fila por tienda y día):
    fecha, tienda, venta, presupuesto, venta_ly, tickets, tickets_fidelizados, unidades
La `casa` se asigna con concurso.TIENDA_A_CASA (por nombre de tienda).
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from concurso import FIN, INICIO, TIENDA_A_CASA

COLUMNAS = ["fecha", "tienda", "venta", "presupuesto", "venta_ly", "tickets",
            "tickets_fidelizados", "unidades"]
FECHA_DEMO = date(2026, 12, 9)  # hasta dónde llegan los datos de ejemplo


def config_bigquery() -> dict | None:
    try:
        cfg = dict(st.secrets.get("bigquery", {}))
    except FileNotFoundError:
        return None
    if not cfg.get("enabled", True) or not (cfg.get("ventas_query") or cfg.get("ventas_table")):
        return None
    return cfg


def _leer_bigquery(cfg: dict) -> pd.DataFrame:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = bigquery.Client(project=cfg.get("job_project_id") or cfg.get("project_id"),
                             credentials=cred, location=cfg.get("location"))
    sql = cfg.get("ventas_query") or f"""
        SELECT {', '.join(COLUMNAS)} FROM `{cfg['ventas_table']}`
        WHERE fecha BETWEEN @inicio AND @fin"""
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("inicio", "DATE", INICIO),
        bigquery.ScalarQueryParameter("fin", "DATE", FIN),
    ]))
    return job.to_dataframe()


def _ejemplo(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    filas = []
    dias = (FECHA_DEMO - INICIO).days + 1
    for tienda in TIENDA_A_CASA:
        base = rng.uniform(4000, 22000)
        sesgo = rng.normal(1.0, 0.05)
        for d in range(dias):
            dia = INICIO + timedelta(days=d)
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


@st.cache_data(ttl=900, show_spinner="Consultando la venta…")
def cargar_datos() -> tuple[pd.DataFrame, str]:
    cfg = config_bigquery()
    df, fuente = (_leer_bigquery(cfg), "BigQuery") if cfg else (_ejemplo(), "Datos de ejemplo")
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["tienda"] = df["tienda"].astype(str).str.strip().str.upper()
    df["casa"] = df["tienda"].map(TIENDA_A_CASA)
    return df[df["casa"].notna()].reset_index(drop=True), fuente
