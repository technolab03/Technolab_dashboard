# app.py — Technolab Data Center (Versión Profesional)
# -*- coding: utf-8 -*-
import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text, event
from datetime import datetime, timedelta

st.set_page_config(page_title="Technolab Data Center", page_icon="🧪", layout="wide")

# ==========================================================
# 🎨 Estilos
# ==========================================================
st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
div[data-testid="stMetricValue"] { font-size: 28px; font-weight: bold; color: #00B4D8; }
div.stButton > button {
  border-radius: 16px; background:#0077B6; color:#fff;
  font-size:18px; height:110px; width:100%; margin:8px 0; transition:.2s;
}
div.stButton > button:hover { background:#0096C7; transform:scale(1.02); }
a.btn-link {
  display:inline-block; padding:10px 14px; border-radius:10px;
  background:#0f172a; color:#e2e8f0; text-decoration:none; margin:8px 0;
}
a.btn-link:hover { background:#1e293b; }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 🔗 Conexión MySQL
# ==========================================================
def build_engine():
    if "mysql" in st.secrets:
        user     = st.secrets["mysql"]["user"]
        password = st.secrets["mysql"]["password"]
        host     = st.secrets["mysql"]["host"]
        port     = st.secrets["mysql"].get("port", 3306)
        database = st.secrets["mysql"]["database"]
    else:
        user     = os.getenv("MYSQL_USER", "makeuser")
        password = os.getenv("MYSQL_PASSWORD", "NUEVA_PASSWORD_SEGURA")
        host     = os.getenv("MYSQL_HOST", "143.198.144.39")
        port     = int(os.getenv("MYSQL_PORT", "3306"))
        database = os.getenv("MYSQL_DATABASE", "technolab")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"charset": "utf8mb4"},
    )

    @event.listens_for(engine, "connect")
    def _set_session_collation(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("SET NAMES utf8mb4;")
        cur.execute("SET collation_connection = 'utf8mb4_unicode_ci';")
        cur.close()

    return engine

ENGINE = build_engine()

# ==========================================================
# 🧩 Funciones auxiliares
# ==========================================================
def q(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return pd.read_sql(text(sql), ENGINE, params=params)
    except Exception as e:
        st.error(f"Error de consulta SQL: {e}")
        return pd.DataFrame()

def _norm_cliente(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()

def _norm_bim_series(s: pd.Series) -> pd.Series:
    x = s.astype("string").fillna("").str.strip()
    x = x.str.replace(r"^\s*bim\s*", "", regex=True)
    x = x.str.lower()
    x = x.replace({"none":"", "null":"", "ninguno":""})
    return x

# ==========================================================
# 📦 Consultas con caché
# ==========================================================
@st.cache_data(ttl=180)
def get_clientes() -> pd.DataFrame:
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

@st.cache_data(ttl=180)
def get_biorreactores() -> pd.DataFrame:
    return q("""
        SELECT id, cliente,
               TRIM(CAST(numero_bim AS CHAR CHARACTER SET utf8mb4)) AS numero_bim,
               latitud, longitud, altura_bim,
               tipo_microalga, uso_luz_artificial, tipo_aireador,
               `fecha_instalación` AS fecha_instalacion
        FROM biorreactores
        WHERE cliente IS NOT NULL AND TRIM(cliente) <> ''
        ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=180)
def get_map_df(cliente_sel: str | None = None) -> pd.DataFrame:
    cat = get_biorreactores().copy()
    if cliente_sel and cliente_sel != "Todos":
        cat = cat[cat["cliente"] == cliente_sel]

    cat["latitud"] = pd.to_numeric(cat["latitud"], errors="coerce")
    cat["longitud"] = pd.to_numeric(cat["longitud"], errors="coerce")
    cat = cat.dropna(subset=["latitud", "longitud"])
    cat["label"] = "BIM " + cat["numero_bim"].astype("string")
    return cat[["cliente","numero_bim","latitud","longitud","tipo_microalga","label"]]

# ==========================================================
# 📊 Indicadores generales (KPIs)
# ==========================================================
@st.cache_data(ttl=180)
def get_kpis():
    c = q("SELECT COUNT(*) AS c FROM clientes")
    total_clientes = int(c["c"].iloc[0]) if not c.empty else 0

    sum_cli_df = q("SELECT SUM(COALESCE(BIMs_instalados,0)) AS s FROM clientes")
    sum_clientes = int(sum_cli_df["s"].iloc[0]) if not sum_cli_df.empty else 0

    df_bio = q("SELECT numero_bim FROM biorreactores WHERE numero_bim IS NOT NULL")
    distinct_bims = int(df_bio["numero_bim"].drop_duplicates().shape[0]) if not df_bio.empty else 0

    total_bims = max(sum_clientes, distinct_bims)
    d = q("SELECT COUNT(*) AS c FROM diagnosticos")
    total_diag = int(d["c"].iloc[0]) if not d.empty else 0
    r = q("SELECT COUNT(*) AS c FROM registros")
    total_regs = int(r["c"].iloc[0]) if not r.empty else 0
    e = q("SELECT COUNT(*) AS c FROM fechas_BIMs")
    total_eventos = int(e["c"].iloc[0]) if not e.empty else 0

    return total_clientes, total_bims, total_diag, total_regs, total_eventos

# ==========================================================
# 🔗 Navegación
# ==========================================================
def go_home():
    st.session_state.page = "home"
    st.session_state.selected_bim = None
    st.query_params.clear()
    st.query_params["page"] = "home"

def go_detail(bim: str):
    st.session_state.page = "detail"
    st.session_state.selected_bim = str(bim)
    st.query_params.clear()
    st.query_params.update({"page": "detail", "bim": str(bim)})

if "page" not in st.session_state:
    st.session_state.page = st.query_params.get("page", "home")
if "selected_bim" not in st.session_state:
    st.session_state.selected_bim = st.query_params.get("bim", None)

# ==========================================================
# 🏠 Página principal
# ==========================================================
def view_home():
    st.title("🧠 Technolab Data Center — Panel General")

    tc, tb, td, tr, te = get_kpis()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Clientes activos", tc)
    k2.metric("Bioreactores operativos", tb)
    k3.metric("Diagnósticos registrados", td)
    k4.metric("Registros de datos", tr)
    k5.metric("Eventos asociados", te)

    # --- Filtros laterales ---
    st.sidebar.title("Filtros de visualización")
    bio_df = get_biorreactores()
    clientes_opts = ["Todos"] + sorted(bio_df["cliente"].unique().tolist())
    cliente_sel = st.sidebar.selectbox("Cliente", clientes_opts, key="cliente_sel")

    if st.sidebar.button("🌍 Mostrar mapa de bioreactores"):
        st.session_state["mostrar_mapa"] = not st.session_state.get("mostrar_mapa", False)

    if st.session_state.get("mostrar_mapa", False):
        st.subheader("🌍 Mapa de Bioreactores")
        import pydeck as pdk
        df_map = get_map_df(cliente_sel)
        if df_map.empty:
            st.info("No existen coordenadas registradas para los bioreactores seleccionados.")
        else:
            lat0 = float(df_map["latitud"].mean())
            lon0 = float(df_map["longitud"].mean())
            view = pdk.ViewState(latitude=lat0, longitude=lon0, zoom=8, pitch=0)
            layer_points = pdk.Layer(
                "ScatterplotLayer",
                data=df_map,
                get_position="[longitud, latitud]",
                get_radius=150,
                pickable=True,
                get_fill_color=[0, 148, 255, 160],
            )
            layer_labels = pdk.Layer(
                "TextLayer",
                data=df_map,
                get_position="[longitud, latitud]",
                get_text="label",
                get_size=14,
                get_color=[255, 255, 255],
                get_alignment_baseline="bottom",
            )
            deck = pdk.Deck(
                layers=[layer_points, layer_labels],
                initial_view_state=view,
                tooltip={"html": "<b>{label}</b><br/>Cliente: {cliente}<br/>Microalga: {tipo_microalga}"},
            )
            st.pydeck_chart(deck, use_container_width=True)

    # --- Listado de bioreactores ---
    st.divider()
    st.subheader("📋 Listado de Bioreactores")

    if cliente_sel != "Todos":
        bio_df = bio_df[bio_df["cliente"] == cliente_sel]

    if bio_df.empty:
        st.warning("No se encontraron bioreactores para el filtro aplicado.")
    else:
        for cliente, grp in bio_df.groupby("cliente"):
            st.markdown(f"### 👤 {cliente}")
            cols = st.columns(3)
            for i, (_, r) in enumerate(grp.iterrows()):
                with cols[i % 3]:
                    tipo_microalga = r.get("tipo_microalga") or "—"
                    tipo_aireador = r.get("tipo_aireador") or "—"
                    altura = r.get("altura_bim") or "—"
                    luz = "Sí" if r.get("uso_luz_artificial") else "No"
                    fecha = r.get("fecha_instalacion") or "—"
                    label = (
                        f"🧬 **BIM {r['numero_bim']}**  \n"
                        f"Microalga: {tipo_microalga}  \n"
                        f"Aireador: {tipo_aireador}  \n"
                        f"Altura: {altura} m  \n"
                        f"Luz artificial: {luz}  \n"
                        f"Instalación: {fecha}"
                    )
                    if st.button(label, key=f"btn_bim_{cliente}_{r['numero_bim']}"):
                        go_detail(str(r["numero_bim"]))

# ==========================================================
# 🔎 Detalle del Bioreactor
# ==========================================================
def view_detail():
    catalogo = get_biorreactores()
    bim = str(st.session_state.selected_bim) if st.session_state.selected_bim else None

    if not bim or bim not in set(catalogo["numero_bim"].astype("string")):
        st.info("Bioreactor no encontrado. Regresando al panel principal…")
        go_home()
        st.stop()

    st.markdown('<a class="btn-link" href="?page=home" target="_self">⬅️ Volver al Panel General</a>', unsafe_allow_html=True)
    st.title(f"🧬 Detalle del Bioreactor {bim}")

    sel = catalogo[catalogo["numero_bim"].astype("string") == bim].iloc[0]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Cliente:** {sel['cliente']}")
        st.markdown(f"**Microalga cultivada:** {sel.get('tipo_microalga') or '—'}")
        st.markdown(f"**Tipo de aireador:** {sel.get('tipo_aireador') or '—'}")
        st.markdown(f"**Altura del bioreactor:** {sel.get('altura_bim') or '—'} m")
    with c2:
        luz = sel.get('uso_luz_artificial')
        st.markdown(f"**Luz artificial:** {'Sí' if bool(luz) else 'No' if luz is not None else '—'}")
        st.markdown(f"**Fecha de instalación:** {sel.get('fecha_instalacion') or '—'}")
        st.markdown(f"**Coordenadas:** ({sel.get('latitud') or '—'}, {sel.get('longitud') or '—'})")

# ==========================================================
# 🚦 Routing
# ==========================================================
page = st.session_state.get("page", st.query_params.get("page", "home"))
if page == "detail":
    view_detail()
else:
    view_home()

st.caption("© Technolab — Sistema de Gestión y Monitoreo de Bioreactores.")
