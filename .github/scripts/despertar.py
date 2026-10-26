"""Abre la app en un navegador real y, si Streamlit Cloud la durmió, la despierta.

Streamlit Community Cloud duerme las apps sin visitas por varias horas. Una petición HTTP simple no
cuenta como visita: hace falta un navegador que abra la sesión. Uso: python despertar.py <url>
"""
import os
import sys

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://concurso-navidad-forus.streamlit.app/"
# Textos que solo aparecen cuando la app ya corre (portada o pantalla de ingreso con Microsoft)
SENALES = ["Cáliz de los Campeones", "Ingresar con Microsoft"]


def app_viva(page) -> bool:
    for frame in page.frames:
        try:
            texto = frame.inner_text("body", timeout=2000)
        except Exception:
            continue
        if any(s in texto for s in SENALES):
            return True
    return False


def esperar_app(page, segundos: int) -> bool:
    for _ in range(segundos // 5):
        if app_viva(page):
            return True
        page.wait_for_timeout(5000)
    return app_viva(page)


def main() -> int:
    with sync_playwright() as p:
        # En GitHub se usa el Google Chrome que ya trae la máquina (NAVEGADOR=chrome): no hay que
        # instalar ningún navegador, que es lo lento y lo que se puede trabar.
        page = p.chromium.launch(channel=os.environ.get("NAVEGADOR") or None).new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(10_000)
        boton = page.get_by_role("button", name="get this app back up")
        try:
            boton.wait_for(timeout=8000)
            print("La app estaba dormida: despertándola…")
            boton.click()
            ok = esperar_app(page, 240)
        except PWTimeout:
            ok = esperar_app(page, 90)
        print("La app está despierta ✅" if ok else "No se pudo confirmar que la app esté despierta ❌")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
