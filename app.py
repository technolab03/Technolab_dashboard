# app.py — Technolab Data Center (versión final unificada)
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

# ==========================================================
# CONFIGURACIÓN Y ESTILOS
# ==========================================================
st.set_page_config(page_title="Technolab Data Center", page_icon="🧪", layout="wide")

st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
h1, h2, h3 { color: #E5EAF2 !important; }
div[data-testid="stMetricValue"] {
  font-size: 28px; font-weight: bold; color: #00B4D8;
}
div.stButton > button {
  border-radius: 16px; background:#0077B6; color:#fff;
  font-size:20px; height:120px; width:100%; margin:8px 0; transition:.2s;
}
div.stButton > button:hover { background:#0096C7; transform:scale(1.03); }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 🔗 CONEXIÓN DIRECTA MYSQL (DigitalOcean)
# ==========================================================
ENGINE = create_engine(
    "mysql+pymysql://makeuser:NUEVA_PASSWORD_SEGURA@143.198.144.39:3306/technolab?charset=utf8mb4",
    pool_pre_ping=True, pool_recycle=1800
)

# ==========================================================
# 🔍 FUNCIONES DE CONSULTA
# ==========================================================
def q(sql, params=None):
    """Consulta SQL segura y devuelve DataFrame (sin romper la app)."""
    try:
        return pd.read_sql(text(sql), ENGINE, params=params)
    except Exception as e:
        st.error(f"Error SQL: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=120)
def get_clientes():
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

@st.cache_data(ttl=120)
def get_biorreactores():
    return q("""
        SELECT id, cliente, numero_bim, latitud, longitud, altura_bim,
               tipo_microalga, uso_luz_artificial, tipo_aireador, fecha_instalación
        FROM biorreactores ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=120)
def get_eventos(bim, d1, d2):
    return q("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=120)
def get_diagnosticos(bim, d1, d2):
    return q("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=120)
def get_registros(bim, d1, d2):
    return q("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

# ==========================================================
# 📊 DATOS BASE
# ==========================================================
clientes = get_clientes()
bior = get_biorreactores()

if bior.empty:
    st.error("⚠️ No se encontraron registros en la tabla `biorreactores`.")
    st.stop()

# ==========================================================
# 🎛️ SIDEBAR FILTROS
# ==========================================================
st.sidebar.title("🎛️ Filtros")
clientes_lista = ["Todos"] + sorted(bior["cliente"].dropna().unique().tolist())
cliente_sel = st.sidebar.selectbox("👤 Cliente", clientes_lista)

if cliente_sel != "Todos":
    bior_f = bior[bior["cliente"] == cliente_sel]
else:
    bior_f = bior.copy()

bim_lista = sorted(bior_f["numero_bim"].unique().tolist())
bim_sel = st.sidebar.selectbox("🧬 BIM", bim_lista)

rango = st.sidebar.date_input("📆 Rango de fechas",
    value=(datetime.today() - timedelta(days=30), datetime.today()))
if isinstance(rango, tuple) and len(rango) == 2:
    d1, d2 = pd.to_datetime(rango[0]), pd.to_datetime(rango[1]) + timedelta(days=1)
else:
    d1, d2 = datetime.today() - timedelta(days=30), datetime.today()

# ==========================================================
# 🧭 PORTADA (MÉTRICAS)
# ==========================================================
st.title("🧠 Technolab Data Center")

total_clientes = len(clientes)
total_bims = len(bior)
total_diag = q("SELECT COUNT(*) AS c FROM diagnosticos")["c"].iloc[0]
total_regs = q("SELECT COUNT(*) AS c FROM registros")["c"].iloc[0]
total_eventos = q("SELECT COUNT(*) AS c FROM fechas_BIMs")["c"].iloc[0]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("👥 Clientes", total_clientes)
c2.metric("🧩 BIMs", total_bims)
c3.metric("💬 Diagnósticos", total_diag)
c4.metric("📄 Registros", total_regs)
c5.metric("📅 Eventos", total_eventos)

st.divider()

# ==========================================================
# 🧫 DETALLE DEL BIM SELECCIONADO
# ==========================================================
sel = bior[bior["numero_bim"] == bim_sel].iloc[0]
st.subheader(f"🧬 BIM {bim_sel} — Cliente: {sel['cliente']}")

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**Microalga:** {sel['tipo_microalga']}")
    st.markdown(f"**Aireador:** {sel['tipo_aireador']}")
    st.markdown(f"**Altura:** {sel['altura_bim']} m")
with col2:
    st.markdown(f"**Luz artificial:** {'Sí' if sel['uso_luz_artificial'] else 'No'}")
    st.markdown(f"**Fecha instalación:** {sel['fecha_instalación']}")
    st.markdown(f"**Coordenadas:** ({sel['latitud']}, {sel['longitud']})")

st.divider()

# ==========================================================
# 🗂️ TABS DE CONTENIDO
# ==========================================================
T1, T2, T3 = st.tabs(["📄 Registros", "💬 Diagnósticos", "📅 Eventos BIM"])

# ---------- TAB REGISTROS ----------
with T1:
    df_r = get_registros(bim_sel, d1, d2)
    st.metric("Total registros", len(df_r))
    if df_r.empty:
        st.info("Sin registros en este rango.")
    else:
        st.dataframe(df_r, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_r.to_csv(index=False).encode("utf-8"),
                           file_name=f"registros_BIM{bim_sel}.csv")

# ---------- TAB DIAGNÓSTICOS ----------
with T2:
    df_d = get_diagnosticos(bim_sel, d1, d2)
    st.metric("Total diagnósticos", len(df_d))
    if df_d.empty:
        st.info("Sin diagnósticos en este rango.")
    else:
        st.dataframe(df_d, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_d.to_csv(index=False).encode("utf-8"),
                           file_name=f"diagnosticos_BIM{bim_sel}.csv")

# ---------- TAB EVENTOS ----------
with T3:
    df_e = get_eventos(bim_sel, d1, d2)
    st.metric("Total eventos", len(df_e))
    if df_e.empty:
        st.info("Sin eventos para este BIM.")
    else:
        st.dataframe(df_e, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_e.to_csv(index=False).encode("utf-8"),
                           file_name=f"eventos_BIM{bim_sel}.csv")

st.divider()
st.caption("© Technolab — Dashboard unificado BIMs / Make / WhatsApp.")

