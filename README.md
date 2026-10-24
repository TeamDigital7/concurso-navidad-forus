# Forus y el Cáliz de los Campeones 🏆

Dashboard en **Streamlit** del concurso navideño Retail de Forus 2026 (noviembre–diciembre).
Las reglas salen del PPT del concurso.

## Estructura

```
app.py                         # páginas: Gran Salón, Casas, Competencias, Copa, Calendario, Reglamento, Maestros
concurso.py                    # reglamento como datos: casas, tiendas, tramos de puntos, bonus, premios, maestros
puntos.py                      # cálculo de puntos por tramo, rankings, top 5 por casa y factor de pago
data.py                        # fuente de datos: BigQuery (si hay secrets) o datos de ejemplo
auth.py                        # inicio de sesión con Microsoft Entra ID (st.login)
assets/style.css               # tema oscuro y dorado
assets/escudos/*.webp          # escudos de las 5 casas
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

`data.py` espera una fila por tienda y día con:
`fecha, tienda, venta, presupuesto, venta_ly, tickets, tickets_fidelizados, unidades`.
La casa se asigna por el nombre de la tienda (`concurso.TIENDA_A_CASA`).
