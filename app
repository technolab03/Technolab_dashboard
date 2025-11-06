# app.py — Dashboard Visual por BIM (Make + Forms)
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ───────────────────── CONFIGURACIÓN BASE ─────────────────────
st.set_page_config(page_title="📊 Dashboard BIMs — Technolab", page_icon="🧪", layout="wide")

st.markdown("""
<style>
/* Ocultar el menú superior y el pie de página */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
/* Tarjetas BIM */
div.stButton > button {
    border-radius: 16px;
    background-color: #004B7F;
    color: white;
    font-size: 20px;
    height: 120px;
    width: 100%;
    margin: 8px 0;
    transition: 0.2s;
}
div.stButton > button:hover {
    background-color: #007ACC;
    transform: scale(1.03);
}
</style>
""", unsafe_allow_html=True)

# ───────────────────── CONEXIÓN MYSQL ─────────────────────
def get_engine():
    cfg = st.secrets["mysql"]
    url = URL.create(
        "mysql+pymysql",
        username=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=int(cfg.get("port", 3306)),
        database=cfg["db"],
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True)

ENG = get_engine()

# ───────────────────── FUNCIONES DE CONSULTA ─────────────────────
@st.cache_data(ttl=300)
def q_biorreactores() -> pd.DataFrame:
    sql = """
    SELECT id, cliente, numero_bim, latitud, longitud, altura_bim, tipo_microalga,
           uso_luz_artificial, tipo_aireador, `fecha_instalación` AS fecha_instalacion
    FROM biorreactores ORDER BY cliente, numero_bim
    """
    return pd.read_sql(text(sql), ENG)

@st.cache_data(ttl=300)
def q_registros(bim: int, desde: datetime, hasta: datetime) -> pd.DataFrame:
    sql = """
    SELECT r.id, r.usuario_id, r.BIM, r.respuestaGPT, r.HEX, r.fecha
    FROM registros r
    WHERE r.BIM = :bim AND r.fecha BETWEEN :d1 AND :d2
    ORDER BY r.fecha DESC
    """
    return pd.read_sql(text(sql), ENG, params={"bim": bim, "d1": desde, "d2": hasta})

@st.cache_data(ttl=300)
def q_diagnosticos(bim: int, desde: datetime, hasta: datetime) -> pd.DataFrame:
    sql = """
    SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
    FROM diagnosticos d
    WHERE d.usuario_id IN (
        SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim
    )
    AND d.fecha BETWEEN :d1 AND :d2
    ORDER BY d.fecha DESC
    """
    return pd.read_sql(text(sql), ENG, params={"bim": bim, "d1": desde, "d2": hasta})

@st.cache_data(ttl=300)
def q_fechas_bims(bim: int, desde: datetime, hasta: datetime) -> pd.DataFrame:
    sql = """
    SELECT id, numero_bim, nombre_evento, fecha, comentarios
    FROM fechas_BIMs
    WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
    ORDER BY fecha DESC
    """
    return pd.read_sql(text(sql), ENG, params={"bim": bim, "d1": desde, "d2": hasta})

# ───────────────────── INTERFAZ ─────────────────────
# Inicializamos la variable global del BIM seleccionado
if "bim_seleccionado" not in st.session_state:
    st.session_state.bim_seleccionado = None

# Vista principal — Selección de BIM
if st.session_state.bim_seleccionado is None:
    st.title("🧪 Dashboard de Biorreactores (BIMs)")
    st.caption("Selecciona un BIM para ver sus registros y diagnósticos")

    df_bims = q_biorreactores()

    if df_bims.empty:
        st.warning("No hay datos de biorreactores registrados.")
        st.stop()

    # Mostrar tarjetas por cliente
    for cliente, grupo in df_bims.groupby("cliente"):
        st.subheader(f"👤 {cliente}")
        cols = st.columns(3)
        i = 0
        for _, row in grupo.iterrows():
            with cols[i % 3]:
                if st.button(f"🧩 BIM {int(row['numero_bim'])}\n\nMicroalga: {row['tipo_microalga']}", key=f"bim_{row['numero_bim']}"):
                    st.session_state.bim_seleccionado = int(row["numero_bim"])
                    st.session_state.cliente_actual = cliente
                    st.experimental_rerun()
            i += 1

# Vista de detalle — Información del BIM seleccionado
else:
    bim = st.session_state.bim_seleccionado
    cliente = st.session_state.cliente_actual

    st.markdown(f"### 🔹 BIM {bim} — {cliente}")
    st.markdown("Registros, diagnósticos y eventos asociados a este biorreactor.")
    st.button("⬅️ Volver al listado", on_click=lambda: st.session_state.update({"bim_seleccionado": None}))

    hoy = datetime.utcnow().date()
    d1 = st.date_input("Desde", hoy - timedelta(days=30))
    d2 = st.date_input("Hasta", hoy)
    desde_dt = datetime.combine(d1, datetime.min.time())
    hasta_dt = datetime.combine(d2, datetime.max.time())

    T1, T2, T3 = st.tabs(["📊 Registros", "💬 Diagnósticos", "📅 Fechas BIM"])

    with T1:
        regs = q_registros(bim, desde_dt, hasta_dt)
        if regs.empty:
            st.info("No hay registros disponibles para este BIM.")
        else:
            st.metric("Cantidad de registros", len(regs))
            st.dataframe(regs, use_container_width=True)
            st.download_button("📥 Descargar CSV", regs.to_csv(index=False).encode("utf-8"), file_name=f"registros_BIM{bim}.csv")

    with T2:
        diags = q_diagnosticos(bim, desde_dt, hasta_dt)
        if diags.empty:
            st.info("No hay diagnósticos disponibles para este BIM.")
        else:
            st.metric("Diagnósticos generados", len(diags))
            st.dataframe(diags, use_container_width=True)
            st.download_button("📥 Descargar CSV", diags.to_csv(index=False).encode("utf-8"), file_name=f"diagnosticos_BIM{bim}.csv")

    with T3:
        fb = q_fechas_bims(bim, desde_dt, hasta_dt)
        if fb.empty:
            st.info("Sin eventos asociados en este rango de fechas.")
        else:
            st.metric("Eventos encontrados", len(fb))
            st.dataframe(fb, use_container_width=True)
            st.download_button("📥 Descargar CSV", fb.to_csv(index=False).encode("utf-8"), file_name=f"eventos_BIM{bim}.csv")

st.caption("© Technolab — Dashboard visual por BIM (Make + Forms)")
