# Forus y el Cáliz de los Campeones 🏆

Dashboard en **Streamlit** del concurso navideño Retail de Forus 2026 (noviembre–diciembre).
Las reglas salen del PPT del concurso.

## Estructura

```
app.py                         # pantalla estilo "posiciones" de X: Posiciones (todas o por casa), Competencias, Calendario, Reglas
concurso.py                    # reglamento como datos: casas, tiendas, tramos de puntos, bonus, premios, maestros
puntos.py                      # cálculo de puntos por tramo, rankings, top 5 por casa y factor de pago
data.py                        # fuente de datos: BigQuery (si hay secrets) o datos de ejemplo
auth.py                        # inicio de sesión con Microsoft Entra ID (st.login)
assets/style.css               # tema oscuro y dorado
assets/escudos/*.webp          # escudos de las 5 casas (mini/: recortados, cuadrados, 96 y 256 px)
assets/portada.jpg             # portada del PPT
.streamlit/config.toml         # tema base
.streamlit/secrets.example.toml# plantilla de secrets (auth Microsoft + BigQuery)
```

## Ejecutar en local

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
streamlit run app.py
```

Sin `.streamlit/secrets.toml` la app corre abierta y con datos de ejemplo.

## Secrets

Copia `.streamlit/secrets.example.toml` a `.streamlit/secrets.toml` (no se versiona) o pégalo en
Settings → Secrets de Streamlit Cloud:

- `[auth]` / `[auth.microsoft]`: igual que en **sincronizacion-stock**. Agrega el redirect URI
  `https://<app>/oauth2callback` al registro de la aplicación en Entra ID.
- `[bigquery]` / `[gcp_service_account]`: igual que en **catalogo-control-center**, más
  `ventas_table` o `ventas_query`.

## Cómo se calculan los puntos

| Regla | Dónde |
|---|---|
| Cumplir venta ≥ presupuesto en un tramo da sus puntos (10 a 30) | `concurso.TRAMOS` |
| Bonus: fidelización > 70% (+5) y SSS > 10% (+5) por tramo | `concurso.BONUS_*` |
| 4 competencias, top 5 magos por casa, desempate por % cumplimiento | `concurso.COMPETENCIAS`, `puntos.ganadores` |
| Factor de pago según cumplimiento del canal Retail (50/75/100/110%) | `concurso.RANGO_PAGO` |
| Copa del Mejor Mago: suma de todas las competencias | `puntos.ranking` |

## Datos reales

Con `[bigquery]` y `[gcp_service_account]` en los secrets, `data.py` lee la venta de la tabla de
venta retail que usa Forusight (ForusIQ): `forus-analitica-prod-datalake.silver.ft_pe_venta_retail`.

| Dato | De dónde sale |
|---|---|
| venta | `SUM(venta_total_sin_iva)` por `nombre_tienda` y día (`fecmov_lv`) |
| venta_ly | la misma consulta 364 días antes (mismo día de la semana) |
| tickets | `COUNT(DISTINCT nrodoc_lv)` |
| tickets fidelizados | regla "Registro Válido" de Power BI sobre `bronze.stg_pe_central_ventas_bi` (ver abajo); si no se puede leer, tickets con `rutcli_lv` de un cliente real |
| unidades | `SUM(unidades_venta)` |
| presupuesto | `presupuesto_table` en los secrets (tabla de Perú central: `nlocal_pd`, `periodo_pd` yyyymm + `dia_pd`, `monto_pd`; se suma por clase y marca). Las columnas de fecha, tienda (nombre o código) y monto se detectan solas o se fijan con `presupuesto_col_fecha`, `_tienda`, `_valor`. Si el monto es mensual (fechas en día 1) se reparte parejo por día. Si la tabla falla, la app avisa en vez de caerse |

Las tiendas se cruzan por nombre con `concurso.TIENDAS`; 83 de las 90 coinciden con el maestro
de tiendas de ForusIQ. Faltan los nombres de Parfois (4), Olympikus Mega Plaza, Vans Outlet Jockey
y CLB Outlet Jockey en la tabla de venta.

Sin secrets la app usa datos de ejemplo.

## Fidelización (regla de Power BI)

Un ticket es fidelizado si el cliente dejó un correo real, igual que la medida "Registro Válido":
`ruc_cliente` numérico ≥ 99999991 no cuenta (RUC de empresa y genéricos); tampoco correos que
empiezan con `be@` o contienen `ecommerce@`, `xxx@` o `@forus`; y el correo debe tener `@`.

`ft_pe_venta_retail` no trae el correo, así que el % se calcula en la tabla ventas_bi
(`fidelizacion_table`, o `ventas_table` si apunta a una ventas_bi, o
`forus-analitica-prod-datalake.bronze.stg_pe_central_ventas_bi`) y se aplica a los tickets de la
venta. Las columnas se detectan solas; si alguna no se encuentra se fija en los secrets con
`fidelizacion_col_fecha`, `_tienda`, `_documento`, `_tipo_documento`, `_ruc` o `_correo`.
Los días que ventas_bi todavía no trae quedan con la regla por RUC. La app muestra arriba qué
regla está usando o por qué no pudo leer la tabla.

## En vivo

La app se refresca sola cada 10 minutos (`data.ACTUALIZAR_CADA_MIN`) y muestra arriba la hora de
la última consulta a BigQuery. Sirve para dejarla abierta en una pantalla. Los datos son tan
frescos como la carga de `ft_pe_venta_retail`.

## Pronóstico antes del 01/11

Mientras no hay venta del concurso, la app muestra un **pronóstico**: toma los últimos 15 días con
venta (lo que dura La Copa de Quidditch), los juega como si fueran esa competencia con las mismas
reglas de puntos y los muestra en Ranking, Gran Salón, Casas, Competencias y Copa con un aviso
🔮. Si todavía no hay presupuesto cargado, la meta es referencial: venta del año pasado + el
desafío SSS de noviembre (+24%). Desde el 01/11 la app pasa sola a la venta real del concurso
(`data.cargar_pronostico`).
