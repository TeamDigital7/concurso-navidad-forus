"""Inicio de sesión con Microsoft Entra ID (OIDC nativo de Streamlit, igual que sincronizacion-stock).

Si los secrets no tienen [auth.microsoft], la app queda abierta (útil en local).
"""
import streamlit as st


def auth_configurada() -> bool:
    try:
        return "microsoft" in st.secrets.get("auth", {})
    except FileNotFoundError:
        return False


def usuario() -> str:
    if not auth_configurada() or not st.user.is_logged_in:
        return ""
    return str(st.user.get("name") or st.user.get("preferred_username") or st.user.get("email") or "")


def requerir_login() -> bool:
    """Devuelve True si se puede mostrar la app; si no, dibuja la pantalla de ingreso."""
    if not auth_configurada() or st.user.is_logged_in:
        return True
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.markdown(
            '<div class="login"><div class="login-title">Forus y el Cáliz de los Campeones</div>'
            '<div class="login-copy">Ingresa con tu cuenta corporativa para ver el torneo.</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Ingresar con Microsoft", type="primary", icon=":material/login:",
                     use_container_width=True):
            st.login("microsoft")
    return False
