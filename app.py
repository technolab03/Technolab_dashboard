# app.py — Technolab Data Center (robusta: funciona aunque biorreactores esté vacío)
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

st.set_page_config(page_title="Technolab Data Center", page_icon="🧪", layout="wide")

# ---------- Estilos ----------
st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
div[data-testid="stMetricValue"] { font-size: 28px; font-weight: bold; color: #00B4D8; }
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
# 🔍 HELPERS SQL
# ==========================================================
def q(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return pd.read_sql(text(sql), ENGINE, params=params)
    except Exception as e:
        st.error(f"Error SQL: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=180)
def get_clientes() -> pd.DataFrame:
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

@st.cache_data(ttl=180)
def get_biorreactores_raw() -> pd.DataFrame:
    # Puede estar vacío; NO paramos la app si no hay filas
    return q("""
        SELECT id, cliente, numero_bim, latitud, longitud, altura_bim,
               tipo_microalga, uso_luz_artificial, tipo_aireador, `fecha_instalación` AS fecha_instalacion
        FROM biorreactores
        ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=180)
def get_distinct_bims_from_registros() -> pd.DataFrame:
    return q("SELECT DISTINCT BIM AS numero_bim FROM registros ORDER BY numero_bim")

@st.cache_data(ttl=180)
def get_distinct_bims_from_eventos() -> pd.DataFrame:
    return q("SELECT DISTINCT numero_bim FROM fechas_BIMs ORDER BY numero_bim")

@st.cache_data(ttl=180)
def get_latest_usuario_por_bim() -> pd.DataFrame:
    # usuario_id más reciente por BIM (para mapear a cliente si falta biorreactores)
    return q("""
        SELECT r.BIM AS numero_bim, r.usuario_id
        FROM registros r
        JOIN (
            SELECT BIM, MAX(fecha) AS max_fecha
            FROM registros
            WHERE fecha IS NOT NULL
            GROUP BY BIM
        ) m ON m.BIM = r.BIM AND m.max_fecha = r.fecha
    """)

@st.cache_data(ttl=180)
def get_eventos(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_diagnosticos(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_registros(bim: int, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": bim, "d1": d1, "d2": d2})

# ==========================================================
# 🧠 ENSAMBLAR “CATÁLOGO DE BIMs” ROBUSTO
# ==========================================================
@st.cache_data(ttl=180)
def construir_catalogo_bims() -> pd.DataFrame:
    clientes = get_clientes()
    br = get_biorreactores_raw()

    if not br.empty:
        # Tenemos biorreactores reales → usar directo
        cat = br.copy()
    else:
        # Fallback: armar listado de BIMs desde registros + eventos
        b1 = get_distinct_bims_from_registros()
        b2 = get_distinct_bims_from_eventos()
        bims = pd.concat([b1, b2], ignore_index=True).drop_duplicates().sort_values("numero_bim")
        if bims.empty:
            return pd.DataFrame(columns=["numero_bim","cliente","tipo_microalga","tipo_aireador",
                                         "uso_luz_artificial","altura_bim","latitud","longitud","fecha_instalacion"])
        # Mapear cliente desde usuario_id más reciente por BIM
        latest = get_latest_usuario_por_bim()
        cat = bims.merge(latest, on="numero_bim", how="left")
        cat = cat.merge(clientes[["usuario_id","cliente"]], on="usuario_id", how="left")
        # Completar columnas técnicas como no registradas
        cat["tipo_microalga"] = None
        cat["tipo_aireador"] = None
        cat["uso_luz_artificial"] = None
        cat["altura_bim"] = None
        cat["latitud"] = None
        cat["longitud"] = None
        cat["fecha_instalacion"] = None
        # Reordenar
        cat = cat[["cliente","numero_bim","latitud","longitud","altura_bim","tipo_microalga",
                   "uso_luz_artificial","tipo_aireador","fecha_instalacion"]].copy()

    # Asegurar tipos suaves
    if "numero_bim" in cat.columns:
        cat["numero_bim"] = cat["numero_bim"].astype(str)
    if "cliente" in cat.columns:
        cat["cliente"] = cat["cliente"].fillna("(Sin cliente)")
    return cat

# ==========================================================
# 📊 KPIs
# ==========================================================
@st.cache_data(ttl=180)
def get_kpis():
    total_clientes = q("SELECT COUNT(*) AS c FROM clientes")["c"].iloc[0] if not q("SELECT COUNT(*) AS c FROM clientes").empty else 0
    total_bims = q("SELECT COUNT(*) AS c FROM (SELECT DISTINCT numero_bim FROM biorreactores UNION SELECT DISTINCT BIM FROM registros UNION SELECT DISTINCT numero_bim FROM fechas_BIMs) t")["c"].iloc[0] if not q("SELECT COUNT(*) AS c FROM (SELECT DISTINCT numero_bim FROM biorreactores UNION SELECT DISTINCT BIM FROM registros UNION SELECT DISTINCT numero_bim FROM fechas_BIMs) t").empty else 0
    total_diag = q("SELECT COUNT(*) AS c FROM diagnosticos")["c"].iloc[0] if not q("SELECT COUNT(*) AS c FROM diagnosticos").empty else 0
    total_regs = q("SELECT COUNT(*) AS c FROM registros")["c"].iloc[0] if not q("SELECT COUNT(*) AS c FROM registros").empty else 0
    total_eventos = q("SELECT COUNT(*) AS c FROM fechas_BIMs")["c"].iloc[0] if not q("SELECT COUNT(*) AS c FROM fechas_BIMs").empty else 0
    return total_clientes, total_bims, total_diag, total_regs, total_eventos

# ==========================================================
# 🌟 UI
# ==========================================================
st.title("🧠 Technolab Data Center")

# KPIs
k1, k2, k3, k4, k5 = st.columns(5)
tc, tb, tdg, trg, tev = get_kpis()
k1.metric("👥 Clientes", tc)
k2.metric("🧩 BIMs", tb)
k3.metric("💬 Diagnósticos", tdg)
k4.metric("📄 Registros", trg)
k5.metric("📅 Eventos", tev)

st.divider()

# Catálogo de BIMs (siempre disponible)
catalogo = construir_catalogo_bims()
if catalogo.empty:
    st.warning("No hay BIMs detectados aún (ni en biorreactores, ni en registros/eventos).")
    st.stop()

# ------- Filtros -------
st.sidebar.title("🎛️ Filtros")
clientes_opts = ["Todos"] + sorted(catalogo["cliente"].dropna().unique().tolist())
cliente_sel = st.sidebar.selectbox("👤 Cliente", clientes_opts)

if cliente_sel != "Todos":
    cat_f = catalogo[catalogo["cliente"] == cliente_sel].copy()
else:
    cat_f = catalogo.copy()

bim_opts = sorted(cat_f["numero_bim"].unique().tolist())
bim_sel = st.sidebar.selectbox("🧬 BIM", bim_opts)

rango = st.sidebar.date_input(
    "📆 Rango de fechas",
    value=(datetime.today() - timedelta(days=30), datetime.today())
)
if isinstance(rango, tuple) and len(rango) == 2:
    D1 = datetime.combine(pd.to_datetime(rango[0]).date(), datetime.min.time())
    D2 = datetime.combine(pd.to_datetime(rango[1]).date(), datetime.max.time())
else:
    D1 = datetime.combine((datetime.today() - timedelta(days=30)).date(), datetime.min.time())
    D2 = datetime.combine(datetime.today().date(), datetime.max.time())

# ------- Tarjetas BIMs -------
st.subheader("🧫 Selección de BIMs")
for cliente, grp in cat_f.groupby("cliente"):
    st.markdown(f"### 👤 {cliente}")
    cols = st.columns(3)
    for i, (_, r) in enumerate(grp.iterrows()):
        with cols[i % 3]:
            label = f"🧬 BIM {r['numero_bim']}\n\nMicroalga: {r.get('tipo_microalga') or '-'}"
            if st.button(label, key=f"btn_bim_{cliente}_{r['numero_bim']}"):
                bim_sel = r["numero_bim"]

st.divider()

# ------- Detalle del BIM seleccionado -------
sel = catalogo[catalogo["numero_bim"] == bim_sel].iloc[0]
st.subheader(f"🧬 BIM {bim_sel} — Cliente: {sel['cliente']}")

c1, c2 = st.columns(2)
with c1:
    st.markdown(f"**Microalga:** {sel.get('tipo_microalga') or '—'}")
    st.markdown(f"**Aireador:** {sel.get('tipo_aireador') or '—'}")
    st.markdown(f"**Altura:** {sel.get('altura_bim') or '—'} m")
with c2:
    luz = sel.get('uso_luz_artificial')
    st.markdown(f"**Luz artificial:** {'Sí' if bool(luz) else 'No' if luz is not None else '—'}")
    st.markdown(f"**Fecha instalación:** {sel.get('fecha_instalacion') or '—'}")
    st.markdown(f"**Coordenadas:** ({sel.get('latitud') or '—'}, {sel.get('longitud') or '—'})")

# ------- Tabs -------
T1, T2, T3 = st.tabs(["📄 Registros", "💬 Diagnósticos", "📅 Eventos BIM"])

with T1:
    df_r = get_registros(int(bim_sel), D1, D2)
    st.metric("Total registros", len(df_r))
    if df_r.empty:
        st.info("Sin registros en este rango.")
    else:
        st.dataframe(df_r, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_r.to_csv(index=False).encode("utf-8"),
                           file_name=f"registros_BIM{bim_sel}.csv")

with T2:
    df_d = get_diagnosticos(int(bim_sel), D1, D2)
    st.metric("Total diagnósticos", len(df_d))
    if df_d.empty:
        st.info("Sin diagnósticos en este rango.")
    else:
        st.dataframe(df_d, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_d.to_csv(index=False).encode("utf-8"),
                           file_name=f"diagnosticos_BIM{bim_sel}.csv")

with T3:
    df_e = get_eventos(int(bim_sel), D1, D2)
    st.metric("Total eventos", len(df_e))
    if df_e.empty:
        st.info("Sin eventos para este BIM.")
    else:
        st.dataframe(df_e, use_container_width=True)
        st.download_button("📥 Descargar CSV", df_e.to_csv(index=False).encode("utf-8"),
                           file_name=f"eventos_BIM{bim_sel}.csv")

st.caption("© Technolab — Dashboard unificado BIMs / Make / WhatsApp.")
