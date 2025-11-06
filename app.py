# app.py — Technolab Dashboard (versión mejorada visual)
import os
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ==========================================================
# CONFIGURACIÓN INICIAL Y ESTILO
# ==========================================================
st.set_page_config(page_title="Technolab Dashboard", page_icon="🧪", layout="wide")

st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
div[data-testid="stMetricValue"] {
  font-size: 26px; font-weight: bold; color: #004B7F;
}
div[data-testid="stMetricDelta"] {
  color: #007ACC !important;
}
div.stButton > button {
  border-radius: 16px; background:#004B7F; color:#fff;
  font-size:20px; height:120px; width:100%; margin:8px 0; transition:.2s;
}
div.stButton > button:hover { background:#007ACC; transform:scale(1.03); }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# CONEXIÓN MYSQL SEGURA (como en tu versión original)
# ==========================================================
def get_engine():
    missing = []
    host = st.secrets.get("mysql", {}).get("host") or os.getenv("MYSQL_HOST")
    user = st.secrets.get("mysql", {}).get("user") or os.getenv("MYSQL_USER")
    pwd  = st.secrets.get("mysql", {}).get("password") or os.getenv("MYSQL_PASSWORD")
    db   = st.secrets.get("mysql", {}).get("db") or os.getenv("MYSQL_DB")
    port = int(st.secrets.get("mysql", {}).get("port", os.getenv("MYSQL_PORT", 3306)))
    if not host: missing.append("host")
    if not user: missing.append("user")
    if pwd is None: missing.append("password")
    if not db: missing.append("db")
    if missing:
        st.error(f"❌ Falta configurar Secrets de MySQL: {', '.join(missing)}.\n"
                 "Ve a Manage app → Settings → Secrets y define [mysql].")
        st.stop()

    url = URL.create("mysql+pymysql", username=user, password=pwd,
                     host=host, port=port, database=db, query={"charset":"utf8mb4"})
    ssl_flag = (st.secrets.get("mysql", {}).get("ssl", "false") or os.getenv("MYSQL_SSL", "false")).lower()
    connect_args = {"ssl": {}} if ssl_flag in ("true","1") else {}

    eng = create_engine(url, pool_pre_ping=True, pool_recycle=1800, connect_args=connect_args)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return eng
    except Exception as e:
        st.error(f"❌ No pude conectar a MySQL (host={host}, db={db}).\n\n{type(e).__name__}: {e}")
        st.stop()

ENG = get_engine()

# ==========================================================
# HELPERS (no revientan la app)
# ==========================================================
def safe_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return pd.read_sql(text(sql), ENG, params=params)
    except Exception as e:
        st.error(f"❌ Error SQL: {type(e).__name__}: {e}\n\nQuery:\n{sql}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def q_biorreactores() -> pd.DataFrame:
    return safe_sql("""
        SELECT id, cliente, numero_bim, latitud, longitud, altura_bim, tipo_microalga,
               uso_luz_artificial, tipo_aireador, `fecha_instalación` AS fecha_instalacion
        FROM biorreactores ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=300)
def q_registros(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return safe_sql("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=300)
def q_diagnosticos(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return safe_sql("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=300)
def q_fechas_bims(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return safe_sql("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

# ==========================================================
# ESTADO DE SESIÓN
# ==========================================================
if "bim_sel" not in st.session_state:
    st.session_state.bim_sel = None
if "cliente_sel" not in st.session_state:
    st.session_state.cliente_sel = None

# ==========================================================
# VISTA PRINCIPAL — PORTADA CON MÉTRICAS GLOBALES
# ==========================================================
if st.session_state.bim_sel is None:
    st.title("🧠 Technolab Data Center")

    df_bims = q_biorreactores()
    total_clientes = df_bims["cliente"].nunique()
    total_bims = len(df_bims)
    total_diag = safe_sql("SELECT COUNT(*) AS c FROM diagnosticos")["c"].iloc[0]
    total_regs = safe_sql("SELECT COUNT(*) AS c FROM registros")["c"].iloc[0]
    total_eventos = safe_sql("SELECT COUNT(*) AS c FROM fechas_BIMs")["c"].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("👤 Clientes", total_clientes)
    c2.metric("🧩 BIMs", total_bims)
    c3.metric("💬 Diagnósticos", total_diag)
    c4.metric("📄 Registros", total_regs)
    c5.metric("📅 Eventos", total_eventos)

    st.divider()
    st.subheader("🧫 Selecciona un BIM")

    if df_bims.empty:
        st.info("No hay biorreactores para mostrar.")
        st.stop()

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
        st.metric("Registros", len(regs))
        st.dataframe(regs, use_container_width=True)
        if not regs.empty:
            st.download_button("📥 Descargar CSV", regs.to_csv(index=False).encode("utf-8"), file_name=f"registros_BIM{bim}.csv")

    with T2:
        diags = q_diagnosticos(bim, D1, D2)
        st.metric("Diagnósticos", len(diags))
        st.dataframe(diags, use_container_width=True)
        if not diags.empty:
            st.download_button("📥 Descargar CSV", diags.to_csv(index=False).encode("utf-8"), file_name=f"diagnosticos_BIM{bim}.csv")

    with T3:
        fb = q_fechas_bims(bim, D1, D2)
        st.metric("Eventos", len(fb))
        st.dataframe(fb, use_container_width=True)
        if not fb.empty:
            st.download_button("📥 Descargar CSV", fb.to_csv(index=False).encode("utf-8"), file_name=f"eventos_BIM{bim}.csv")

st.caption("© Technolab — Dashboard unificado BIMs / Make / WhatsApp.")
