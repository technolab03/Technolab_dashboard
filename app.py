# app.py — Technolab Dashboard (versión final con conexión directa)
import os
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ==========================================================
# CONFIGURACIÓN INICIAL
# ==========================================================
st.set_page_config(page_title="Technolab Dashboard", page_icon="🧪", layout="wide")

# -------- Estilos visuales --------
st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
div[data-testid="stMetricValue"] {
  font-size: 26px; font-weight: bold; color: #004B7F;
}
div.stButton > button {
  border-radius: 16px; background:#004B7F; color:#fff;
  font-size:20px; height:120px; width:100%; margin:8px 0; transition:.2s;
}
div.stButton > button:hover { background:#007ACC; transform:scale(1.03); }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 🔗 CONEXIÓN DIRECTA A MYSQL (DigitalOcean)
# ==========================================================
try:
    engine = create_engine(
        "mysql+pymysql://makeuser:NUEVA_PASSWORD_SEGURA@143.198.144.39:3306/technolab?charset=utf8mb4",
        pool_pre_ping=True, pool_recycle=1800
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as e:
    st.error(f"❌ Error al conectar con MySQL: {type(e).__name__}: {e}")
    st.stop()

# ==========================================================
# FUNCIONES DE CONSULTA (con cache)
# ==========================================================
@st.cache_data(ttl=300)
def q_biorreactores() -> pd.DataFrame:
    return pd.read_sql("""
        SELECT id, cliente, numero_bim, latitud, longitud, altura_bim, tipo_microalga,
               uso_luz_artificial, tipo_aireador, `fecha_instalación` AS fecha_instalacion
        FROM biorreactores ORDER BY cliente, numero_bim
    """, engine)

@st.cache_data(ttl=300)
def q_registros(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """), engine, params={"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=300)
def q_diagnosticos(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC
    """), engine, params={"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=300)
def q_fechas_bims(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return pd.read_sql(text("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """), engine, params={"bim": bim, "d1": d1, "d2": d2})

# ==========================================================
# ESTADO DE SESIÓN
# ==========================================================
if "bim_sel" not in st.session_state:
    st.session_state.bim_sel = None
if "cliente_sel" not in st.session_state:
    st.session_state.cliente_sel = None

# ==========================================================
# VISTA PRINCIPAL — PORTADA
# ==========================================================
if st.session_state.bim_sel is None:
    st.title("🧠 Technolab Data Center")

    df_bims = q_biorreactores()
    if df_bims.empty:
        st.info("No hay biorreactores registrados.")
        st.stop()

    # Métricas globales
    total_clientes = df_bims["cliente"].nunique()
    total_bims = len(df_bims)
    total_diag = pd.read_sql("SELECT COUNT(*) AS c FROM diagnosticos", engine)["c"].iloc[0]
    total_regs = pd.read_sql("SELECT COUNT(*) AS c FROM registros", engine)["c"].iloc[0]
    total_eventos = pd.read_sql("SELECT COUNT(*) AS c FROM fechas_BIMs", engine)["c"].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("👤 Clientes", total_clientes)
    c2.metric("🧩 BIMs", total_bims)
    c3.metric("💬 Diagnósticos", total_diag)
    c4.metric("📄 Registros", total_regs)
    c5.metric("📅 Eventos", total_eventos)

    st.divider()
    st.subheader("🧫 Selecciona un BIM")

    clientes = ["(Todos)"] + sorted(df_bims["cliente"].dropna().unique().tolist())
    cli = st.selectbox("Cliente", clientes)
    st.session_state.cliente_sel = None if cli == "(Todos)" else cli
    data = df_bims if st.session_state.cliente_sel is None else df_bims[df_bims["cliente"] == st.session_state.cliente_sel]

    for cliente, grp in data.groupby("cliente"):
        st.markdown(f"### 👤 {cliente}")
        cols = st.columns(3)
        i = 0
        for _, r in grp.iterrows():
            with cols[i % 3]:
                label = f"🧬 BIM {int(r['numero_bim'])}\n\nMicroalga: {r.get('tipo_microalga','-')}"
                if st.button(label, key=f"bim_{r['numero_bim']}"):
                    st.session_state.bim_sel = int(r["numero_bim"])
                    st.experimental_rerun()
            i += 1

# ==========================================================
# VISTA DETALLE DE BIM
# ==========================================================
else:
    bim = st.session_state.bim_sel
    st.markdown(f"### 🔹 BIM {bim}  {'— ' + st.session_state.cliente_sel if st.session_state.cliente_sel else ''}")
    st.button("⬅️ Volver", on_click=lambda: st.session_state.update({"bim_sel": None}))

    hoy = datetime.utcnow().date()
    d1 = st.date_input("Desde", hoy - timedelta(days=30))
    d2 = st.date_input("Hasta", hoy)
    D1 = datetime.combine(d1, datetime.min.time())
    D2 = datetime.combine(d2, datetime.max.time())

    T1, T2, T3 = st.tabs(["📊 Registros", "💬 Diagnósticos", "📅 Fechas BIMs"])

    with T1:
        regs = q_registros(bim, D1, D2)
        st.metric("📄 Registros", len(regs))
        st.dataframe(regs, use_container_width=True)
        if not regs.empty:
            st.download_button("📥 Descargar CSV", regs.to_csv(index=False).encode("utf-8"), file_name=f"registros_BIM{bim}.csv")

    with T2:
        diags = q_diagnosticos(bim, D1, D2)
        st.metric("💬 Diagnósticos", len(diags))
        st.dataframe(diags, use_container_width=True)
        if not diags.empty:
            st.download_button("📥 Descargar CSV", diags.to_csv(index=False).encode("utf-8"), file_name=f"diagnosticos_BIM{bim}.csv")

    with T3:
        fb = q_fechas_bims(bim, D1, D2)
        st.metric("📅 Eventos", len(fb))
        st.dataframe(fb, use_container_width=True)
        if not fb.empty:
            st.download_button("📥 Descargar CSV", fb.to_csv(index=False).encode("utf-8"), file_name=f"eventos_BIM{bim}.csv")

st.caption("© Technolab — Dashboard unificado BIMs / Make / WhatsApp.")
