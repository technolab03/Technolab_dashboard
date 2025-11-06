# app.py
import os
import streamlit as st
import pandas as pd
from datetime import timedelta
import plotly.express as px
import pydeck as pdk
from sqlalchemy import create_engine
import pymysql

st.set_page_config(page_title="Technolab Dashboard", page_icon="🧪", layout="wide")

# -----------------------
# 1) Obtener credenciales
# -----------------------
# Primero intentar leer desde variables de entorno (recomendado en deploys)
MYSQL_HOST = os.environ.get("TECHNOLAB_MYSQL_HOST")
MYSQL_PORT = os.environ.get("TECHNOLAB_MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("TECHNOLAB_MYSQL_USER")
MYSQL_PASSWORD = os.environ.get("TECHNOLAB_MYSQL_PASSWORD")
MYSQL_DB = os.environ.get("TECHNOLAB_MYSQL_DB")

# Si no están en variables de entorno, intentar leer desde st.secrets (Streamlit Cloud / .streamlit/secrets.toml)
if not (MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD and MYSQL_DB):
    mysql_secrets = st.secrets.get("mysql", {}) if hasattr(st, "secrets") else {}
    MYSQL_HOST = MYSQL_HOST or mysql_secrets.get("host")
    MYSQL_PORT = MYSQL_PORT or mysql_secrets.get("port", "3306")
    MYSQL_USER = MYSQL_USER or mysql_secrets.get("user")
    MYSQL_PASSWORD = MYSQL_PASSWORD or mysql_secrets.get("password")
    MYSQL_DB = MYSQL_DB or mysql_secrets.get("database")

# Si aún no están, mostrar instrucción y detener ejecución
if not (MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD and MYSQL_DB):
    st.error(
        "No se han proporcionado credenciales MySQL.\n\n"
        "Proporciona las credenciales mediante 1) variables de entorno (recomendado) "
        "o 2) Streamlit secrets (.streamlit/secrets.toml o la interfaz 'Settings → Secrets').\n\n"
        "Variables de entorno esperadas (ejemplo):\n"
        "  TECHNOLAB_MYSQL_HOST\n  TECHNOLAB_MYSQL_PORT (opcional, default 3306)\n"
        "  TECHNOLAB_MYSQL_USER\n  TECHNOLAB_MYSQL_PASSWORD\n  TECHNOLAB_MYSQL_DB\n\n"
        "O en Streamlit secrets con el bloque [mysql] (host,user,password,database)."
    )
    st.stop()

# -----------------------
# 2) Crear engine SQLAlchemy
# -----------------------
conn_str = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
@st.cache_resource(show_spinner=False)
def get_engine(connection_string: str):
    return create_engine(connection_string, pool_pre_ping=True)

engine = get_engine(conn_str)

# -----------------------
# 3) Cargar datos (solo MySQL)
# -----------------------
@st.cache_data(show_spinner=False)
def load_data():
    # Ajusta las consultas a tu esquema real (nombres de tablas/columnas)
    clientes = pd.read_sql("SELECT id AS cliente_id, nombre, telefono, email FROM clientes", engine)
    bims = pd.read_sql("SELECT id AS bim_id, nombre, cliente_id, microalga, sistema, lat, lon FROM bims", engine)
    registros = pd.read_sql(
        "SELECT bim_id, timestamp, ph, temperatura, oxigeno, luz, fase FROM registros",
        engine,
        parse_dates=["timestamp"]
    )
    diagnosticos = pd.read_sql("SELECT bim_id, fecha, resumen FROM diagnosticos", engine, parse_dates=["fecha"])
    return clientes, bims, registros, diagnosticos

try:
    clientes, bims, registros, diagnosticos = load_data()
except Exception as e:
    st.error(f"Error leyendo datos desde MySQL: {e}")
    st.stop()

# -----------------------
# 4) Sidebar - filtros
# -----------------------
st.sidebar.title("Filtros")

cliente_opciones = ["Todos"] + sorted(clientes["nombre"].unique().tolist())
cliente_sel = st.sidebar.selectbox("Cliente", cliente_opciones, index=0)

if cliente_sel != "Todos":
    cliente_ids = clientes.loc[clientes["nombre"] == cliente_sel, "cliente_id"].tolist()
    bims_disp = bims[bims["cliente_id"].isin(cliente_ids)].copy()
else:
    bims_disp = bims.copy()

micro_sel = st.sidebar.multiselect("Microalga", sorted(bims_disp["microalga"].dropna().unique().tolist()))
sis_sel = st.sidebar.multiselect("Sistema", sorted(bims_disp["sistema"].dropna().unique().tolist()))

if registros.empty:
    st.warning("No hay registros en la base de datos.")
    st.stop()

max_ts = pd.to_datetime(registros["timestamp"]).max()
default_start = max_ts - pd.Timedelta(days=7)
rango = st.sidebar.date_input("Fecha (inicio, fin)", value=(default_start.date(), max_ts.date()))
if isinstance(rango, tuple) and len(rango) == 2:
    start_date = pd.to_datetime(rango[0])
    end_date = pd.to_datetime(rango[1]) + pd.Timedelta(days=1)
else:
    start_date, end_date = default_start, max_ts + pd.Timedelta(days=1)

if micro_sel:
    bims_disp = bims_disp[bims_disp["microalga"].isin(micro_sel)]
if sis_sel:
    bims_disp = bims_disp[bims_disp["sistema"].isin(sis_sel)]

# -----------------------
# 5) Mostrar BIMs (botones)
# -----------------------
st.markdown("## BIMs")
cols = st.columns(3, gap="large")

def bim_card(col, row):
    with col:
        c = st.container()
        with c:
            st.markdown(f"### {row['nombre']}")
            st.caption(f"Microalga: {row['microalga']} · Sistema: {row['sistema']}")
            st.caption(f"Cliente ID: {row['cliente_id']}")
            if st.button("Abrir", key=f"open_{int(row['bim_id'])}"):
                st.session_state['selected_bim_id'] = int(row['bim_id'])

if bims_disp.empty:
    st.info("No hay BIMs para los filtros seleccionados.")
else:
    for i, (_, row) in enumerate(bims_disp.iterrows()):
        bim_card(cols[i % 3], row)

if 'selected_bim_id' not in st.session_state and not bims_disp.empty:
    st.session_state['selected_bim_id'] = int(bims_disp.iloc[0]['bim_id'])

selected_bim_id = st.session_state.get('selected_bim_id')

# -----------------------
# 6) Detalle BIM
# -----------------------
if selected_bim_id is not None and not bims_disp.empty:
    bim_info = bims[bims['bim_id'] == selected_bim_id].iloc[0]
    st.markdown(f"## Detalle {bim_info['nombre']}")

    reg_bim = registros[
        (registros["bim_id"] == selected_bim_id)
        & (registros["timestamp"] >= start_date)
        & (registros["timestamp"] < end_date)
    ].copy()

    diag_bim = diagnosticos[
        (diagnosticos["bim_id"] == selected_bim_id)
        & (diagnosticos["fecha"] >= start_date)
        & (diagnosticos["fecha"] < end_date)
    ].copy()

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("pH medio", f"{reg_bim['ph'].mean():.2f}" if not reg_bim.empty else "–")
    with m2: st.metric("Temp media (°C)", f"{reg_bim['temperatura'].mean():.1f}" if not reg_bim.empty else "–")
    with m3: st.metric("O₂ medio (mg/L)", f"{reg_bim['oxigeno'].mean():.2f}" if not reg_bim.empty else "–")
    with m4: st.metric("Lux medio", f"{reg_bim['luz'].mean():.0f}" if not reg_bim.empty else "–")

    tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendencias", "🧪 Diagnóstico", "📋 Registros", "🗺️ Mapa"])

    with tab1:
        st.subheader("Tendencias de sensores")
        colv = st.multiselect("Variables", ["ph", "temperatura", "oxigeno", "luz"], default=["oxigeno", "ph"])
        if not reg_bim.empty:
            for v in colv:
                fig = px.line(reg_bim, x="timestamp", y=v, title=v.capitalize())
                st.plotly_chart(fig, use_container_width=True)
            if "fase" in reg_bim.columns:
                fcount = reg_bim.groupby(["fase"]).size().reset_index(name="horas")
                bar = px.bar(fcount, x="fase", y="horas", title="Distribución de horas por fase")
                st.plotly_chart(bar, use_container_width=True)
        else:
            st.info("No hay registros en el rango seleccionado.")

    with tab2:
        st.subheader("Diagnóstico (resumen diario)")
        if not diag_bim.empty:
            st.dataframe(diag_bim.sort_values("fecha", ascending=False), use_container_width=True)
        else:
            st.info("Sin diagnósticos en el rango.")

    with tab3:
        st.subheader("Registros (detalle)")
        st.dataframe(reg_bim.sort_values("timestamp", ascending=False), use_container_width=True, height=420)

    with tab4:
        st.subheader("Ubicación del BIM")
        lat, lon = bim_info.get("lat"), bim_info.get("lon")
        if pd.notnull(lat) and pd.notnull(lon):
            layer = pdk.Layer(
                "ScatterplotLayer",
                data=pd.DataFrame([{"lat": lat, "lon": lon}]),
                get_position='[lon, lat]',
                get_radius=50,
                pickable=True
            )
            st.pydeck_chart(pdk.Deck(
                map_style=None,
                initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=12, pitch=0),
                layers=[layer]
            ))
        else:
            st.info("Sin coordenadas para este BIM.")
else:
    st.info("Selecciona un BIM para ver el detalle.")

st.caption("Technolab · Dashboard · Fuente: MySQL (Forms · WhatsApp · Make).")
