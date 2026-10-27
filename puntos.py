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


def sss(x) -> pd.Series | float:
    """Crecimiento vs. el año pasado solo en días comparables (venta_comp / venta_ly - 1)."""
    ly = x["venta_ly"]
    if isinstance(ly, pd.Series):
        return x["venta_comp"] / ly.replace(0, np.nan) - 1
    return x["venta_comp"] / ly - 1 if ly else np.nan


def puntos_por_tramo(df: pd.DataFrame, hasta=None) -> pd.DataFrame:
    """Una fila por tienda y tramo. Solo puntúan los tramos cerrados (fin <= `hasta`)."""
    d = _asignar(df)
    # SSS = mismas tiendas, mismos días: solo cuentan los días con venta en los dos años. Si no,
    # una tienda que el año pasado vendió pocos días (abrió a mitad de mes, remodelación) compara
    # el mes entero contra esos pocos días y el SSS sale inflado (el "vendemos el doble").
    d = d.assign(venta_comp=d["venta"].where(d["venta_ly"] > 0, 0))
    # Días con tickets que todavía no traen el dato de correo (ventas_bi llega con atraso)
    con_bi = d["con_bi"].fillna(False).astype(bool) if "con_bi" in d else True
    d["dias_sin_correo"] = ((d["tickets"] > 0) & ~con_bi).astype(int)
    g = d.groupby(["tienda", "casa", "tramo", "competencia"], as_index=False)[
        ["venta", "presupuesto", "venta_ly", "venta_comp", "tickets", "tickets_fidelizados", "unidades",
         "dias_sin_correo"]].sum()
    g["inicio"] = g["tramo"].map(lambda i: TRAMOS[i].inicio)
    g["fin"] = g["tramo"].map(lambda i: TRAMOS[i].fin)
    g["cerrado"] = True if hasta is None else g["fin"] <= hasta
    g["cumplimiento"] = g["venta"] / g["presupuesto"].replace(0, np.nan)
    # Sin venta el año pasado no hay SSS (tienda nueva o cerrada): queda vacío y no da bonus
    g["sss"] = sss(g)
    g["fidelizacion"] = g["tickets_fidelizados"] / g["tickets"]
    g["pts_venta"] = np.where(g["cumplimiento"] >= 1, g["tramo"].map(lambda i: TRAMOS[i].puntos), 0)
    # El bonus de fidelización espera a tener el correo de todos los días del tramo: nadie lo gana
    # ni lo pierde por un dato que todavía no llegó. Se otorga solo cuando ventas_bi se pone al día.
    g["fid_pendiente"] = g["dias_sin_correo"] > 0
    g["pts_fidelizacion"] = np.where((g["fidelizacion"] > BONUS_FIDELIZACION["umbral"]) & ~g["fid_pendiente"],
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
        presupuesto=("presupuesto", "sum"), venta_ly=("venta_ly", "sum"), venta_comp=("venta_comp", "sum"),
        tickets=("tickets", "sum"), tickets_fidelizados=("tickets_fidelizados", "sum"),
        unidades=("unidades", "sum"), tramos_ganados=("pts_venta", lambda s: int((s > 0).sum())),
    )
    r["cumplimiento"] = r["venta"] / r["presupuesto"].replace(0, np.nan)
    r["sss"] = sss(r)
    r["fidelizacion"] = r["tickets_fidelizados"] / r["tickets"]
    r["ticket_prom"] = r["venta"] / r["tickets"]
    r["upt"] = r["unidades"] / r["tickets"]
    return r.sort_values(["puntos", "cumplimiento"], ascending=False).reset_index(drop=True)


def resumen_casas(rank: pd.DataFrame) -> pd.DataFrame:
    c = rank.groupby("casa", as_index=False).agg(
        puntos=("puntos", "sum"), magos=("tienda", "count"),
        venta=("venta", "sum"), presupuesto=("presupuesto", "sum"), venta_ly=("venta_ly", "sum"),
        venta_comp=("venta_comp", "sum"))
    c["cumplimiento"] = c["venta"] / c["presupuesto"].replace(0, np.nan)
    c["sss"] = sss(c)
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
    ppto = d["presupuesto"].sum()
    cumpl = d["venta"].sum() / ppto if ppto else 0.0
    f = factor_pago(cumpl)
    r = ranking(d)
    r["puesto"] = r.groupby("casa").cumcount() + 1
    top = r[r["puesto"] <= GANADORES_POR_CASA].copy()
    top["premio_base"] = top["puesto"].map(lambda p: competencia.premios[p - 1])
    top["premio"] = top["premio_base"] * f
    return top, cumpl, f
