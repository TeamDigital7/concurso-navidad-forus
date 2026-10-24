"""Cálculo de puntos, rankings y premios a partir de la venta diaria por tienda.

Entrada: DataFrame con columnas
    fecha, tienda, casa, venta, presupuesto, venta_ly, tickets, tickets_fidelizados, unidades
"""
import numpy as np
import pandas as pd

from concurso import (BONUS_FIDELIZACION, BONUS_SSS, COMPETENCIAS, GANADORES_POR_CASA,
                      RANGO_PAGO, TRAMOS)


def _asignar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    f = d["fecha"].dt.date
    d["tramo"] = -1
    d["competencia"] = ""
    for i, t in enumerate(TRAMOS):
        d.loc[(f >= t.inicio) & (f <= t.fin), "tramo"] = i
    for c in COMPETENCIAS:
        d.loc[(f >= c.inicio) & (f <= c.fin), "competencia"] = c.nombre
    return d[d["tramo"] >= 0]


def puntos_por_tramo(df: pd.DataFrame, hasta=None) -> pd.DataFrame:
    """Una fila por tienda y tramo. Solo puntúan los tramos cerrados (fin <= `hasta`)."""
    d = _asignar(df)
    g = d.groupby(["tienda", "casa", "tramo", "competencia"], as_index=False)[
        ["venta", "presupuesto", "venta_ly", "tickets", "tickets_fidelizados", "unidades"]].sum()
    g["inicio"] = g["tramo"].map(lambda i: TRAMOS[i].inicio)
    g["fin"] = g["tramo"].map(lambda i: TRAMOS[i].fin)
    g["cerrado"] = True if hasta is None else g["fin"] <= hasta
    g["cumplimiento"] = g["venta"] / g["presupuesto"]
    g["sss"] = g["venta"] / g["venta_ly"] - 1
    g["fidelizacion"] = g["tickets_fidelizados"] / g["tickets"]
    g["pts_venta"] = np.where(g["cumplimiento"] >= 1, g["tramo"].map(lambda i: TRAMOS[i].puntos), 0)
    g["pts_fidelizacion"] = np.where(g["fidelizacion"] > BONUS_FIDELIZACION["umbral"],
                                     BONUS_FIDELIZACION["puntos"], 0)
    g["pts_sss"] = np.where(g["sss"] > BONUS_SSS["umbral"], BONUS_SSS["puntos"], 0)
    pts = ["pts_venta", "pts_fidelizacion", "pts_sss"]
    g.loc[~g["cerrado"], pts] = 0
    g["pts_bonus"] = g["pts_fidelizacion"] + g["pts_sss"]
    g["puntos"] = g[pts].sum(axis=1)
    return g


def ranking(pt: pd.DataFrame) -> pd.DataFrame:
    """Ranking de magos (tiendas) sobre los tramos recibidos. Desempate: % cumplimiento."""
    r = pt.groupby(["tienda", "casa"], as_index=False).agg(
        puntos=("puntos", "sum"), pts_venta=("pts_venta", "sum"),
        pts_bonus=("pts_bonus", "sum"), venta=("venta", "sum"),
        presupuesto=("presupuesto", "sum"), venta_ly=("venta_ly", "sum"),
        tickets=("tickets", "sum"), tickets_fidelizados=("tickets_fidelizados", "sum"),
        unidades=("unidades", "sum"), tramos_ganados=("pts_venta", lambda s: int((s > 0).sum())),
    )
    r["cumplimiento"] = r["venta"] / r["presupuesto"]
    r["sss"] = r["venta"] / r["venta_ly"] - 1
    r["fidelizacion"] = r["tickets_fidelizados"] / r["tickets"]
    r["ticket_prom"] = r["venta"] / r["tickets"]
    r["upt"] = r["unidades"] / r["tickets"]
    return r.sort_values(["puntos", "cumplimiento"], ascending=False).reset_index(drop=True)


def resumen_casas(rank: pd.DataFrame) -> pd.DataFrame:
    c = rank.groupby("casa", as_index=False).agg(
        puntos=("puntos", "sum"), magos=("tienda", "count"),
        venta=("venta", "sum"), presupuesto=("presupuesto", "sum"), venta_ly=("venta_ly", "sum"))
    c["cumplimiento"] = c["venta"] / c["presupuesto"]
    c["sss"] = c["venta"] / c["venta_ly"] - 1
    c["puntos_prom"] = c["puntos"] / c["magos"]
    return c.sort_values("puntos", ascending=False).reset_index(drop=True)


def factor_pago(cumplimiento_retail: float) -> float:
    f = 0.0
    for desde, factor in RANGO_PAGO:
        if cumplimiento_retail >= desde:
            f = factor
    return f


def ganadores(pt: pd.DataFrame, competencia) -> tuple[pd.DataFrame, float, float]:
    """Top 5 por casa de una competencia, con premio ajustado por el cumplimiento del Retail."""
    d = pt[pt["competencia"] == competencia.nombre]
    cumpl = d["venta"].sum() / d["presupuesto"].sum() if len(d) else 0.0
    f = factor_pago(cumpl)
    r = ranking(d)
    r["puesto"] = r.groupby("casa").cumcount() + 1
    top = r[r["puesto"] <= GANADORES_POR_CASA].copy()
    top["premio_base"] = top["puesto"].map(lambda p: competencia.premios[p - 1])
    top["premio"] = top["premio_base"] * f
    return top, cumpl, f
