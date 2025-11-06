import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.express as px
import pydeck as pdk

st.set_page_config(page_title="Technolab Dashboard", page_icon="🧪", layout="wide")

# --------------------------------
# Utilidades: generar datos demo
# --------------------------------
def generar_demo():
    np.random.seed(42)
    now = datetime.utcnow()

    bims = pd.DataFrame([
        {"bim_id": 1, "nombre": "BIM-001", "cliente_id": 101, "microalga": "Chlorella", "sistema": "Fotobiorreactor 50L", "lat": -29.90, "lon": -71.26},
        {"bim_id": 2, "nombre": "BIM-002", "cliente_id": 102, "microalga": "Spirulina", "sistema": "Raceway 200L", "lat": -29.95, "lon": -71.30},
        {"bim_id": 3, "nombre": "BIM-003", "cliente_id": 101, "microalga": "Nannochloropsis", "sistema": "Fotobiorreactor 20L", "lat": -29.92, "lon": -71.28},
    ])

    clientes = pd.DataFrame([
        {"cliente_id": 101, "nombre": "Tecnolab Demo", "telefono": "+56 9 1111 1111", "email": "demo@technolab.cl"},
        {"cliente_id": 102, "nombre": "Tierras Nobles", "telefono": "+56 9 2222 2222", "email": "ventas@tierrasnobles.cl"},
    ])

    rows = []
    for _, r in bims.iterrows():
        base_o2 = np.random.uniform(6.5, 9.5)
        base_ph = np.random.uniform(7.2, 8.3)
        base_temp = np.random.uniform(17, 23)
        base_lux = np.random.uniform(1200, 4500)
        t0 = now - timedelta(days=10)
        for i in range(10 * 24):  # 10 días, horario
            ts = t0 + timedelta(hours=i)
            diurnal = np.sin((ts.hour / 24) * 2 * np.pi)  # patrón día-noche
            oxigeno = base_o2 + diurnal * 2 + np.random.normal(0, 0.2)
            ph = base_ph + (0.1 if diurnal > 0 else -0.05) + np.random.normal(0, 0.03)
            temp = base_temp + diurnal * 3 + np.random.normal(0, 0.4)
            lux = max(0, base_lux * (diurnal + 1)) + np.random.normal(0, 80)
            fase = "Adaptación" if i < 24 else ("Crecimiento" if i < 24 * 6 else ("Estacionaria" if i < 24 * 9 else "Declive"))
            rows.append({
                "bim_id": r["bim_id"],
                "timestamp": ts,
                "ph": round(ph, 2),
                "temperatura": round(temp, 2),
                "oxigeno": round(oxigeno, 2),
                "luz": round(lux, 0),
                "fase": fase
            })
    registros = pd.DataFrame(rows)

    diags = []
    gby = registros.copy()
    gby["date"] = pd.to_datetime(gby["timestamp"]).dt.date
    for bim_id, g in gby.groupby(["bim_id", "date"]):
        rr = g.agg({'ph':'mean','temperatura':'mean','oxigeno':'mean','luz':'mean'})
        diag = "OK"
        alerts = []
        if rr['oxigeno'] < 6.5: alerts.append("Oxígeno bajo")
        if rr['ph'] > 8.8: alerts.append("pH alto")
        if rr['temperatura'] > 28: alerts.append("Temperatura alta")
        if alerts: diag = "; ".join(alerts)
        diags.append({"bim_id": bim_id[0], "fecha": pd.to_datetime(str(bim_id[1])), "resumen": diag})
    diagnosticos = pd.DataFrame(diags)

    return clientes, bims, registros, diagnosticos


# --------------------------------
# Carga de datos (DB → CSV → demo)
# --------------------------------
@st.cache_data(show_spinner=False)
def load_data():
    # 1) Intentar MySQL si hay secrets
    try:
        db = st.secrets.get("mysql", {})
    except Exception:
        db = {}

    if db and all(k in db for k in ["host", "user", "password", "database"]):
        try:
            from sqlalchemy import create_engine
            conn_str = f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}"
            engine = create_engine(conn_str, pool_pre_ping=True)

            clientes = pd.read_sql("SELECT id AS cliente_id, nombre, telefono, email FROM clientes", engine)
            bims = pd.read_sql("SELECT id AS bim_id, nombre, cliente_id, microalga, sistema, lat, lon FROM bims", engine)
            registros = pd.read_sql("SELECT bim_id, timestamp, ph, temperatura, oxigeno, luz, fase FROM registros", engine, parse_dates=["timestamp"])
            diagnosticos = pd.read_sql("SELECT bim_id, fecha, resumen FROM diagnosticos", engine, parse_dates=["fecha"])
            return clientes, bims, registros, diagnosticos
        except Exception as e:
            st.warning(f"No se pudo conectar a MySQL. Usando CSV o datos demo. Detalle: {e}")

    # 2) Intentar CSV locales
    try:
        clientes = pd.read_csv("sample_clientes.csv")
        bims = pd.read_csv("sample_bims.csv")
        registros = pd.read_csv("sample_registros.csv", parse_dates=["timestamp"])
        diagnosticos = pd.read_csv("sample_diagnosticos.csv", parse_dates=["fecha"])
        return clientes, bims, registros, diagnosticos
    except Exception:
        # 3) Datos demo en memoria
        st.info("No se encontraron CSV. Usando datos de demostración.")
        return generar_demo()

clientes, bims, registros, diagnosticos = load_data()

# --------------------------------
# Sidebar: filtros
# --------------------------------
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

# Rango de fechas
if not registros.empty:
    max_ts = pd.to_datetime(registros["timestamp"]).max()
    min_ts = pd.to_datetime(registros["timestamp"]).min()
else:
    now = datetime.utcnow()
    min_ts, max_ts = now - timedelta(days=7), now

default_start = max_ts - pd.Timedelta(days=7)
rango = st.sidebar.date_input("Fecha (inicio, fin)", value=(default_start.date(), max_ts.date()))
if isinstance(rango, tuple) and len(rango) == 2:
    start_date = pd.to_datetime(rango[0])
    end_date = pd.to_datetime(rango[1]) + pd.Timedelta(days=1)
else:
    start_date, end_date = default_start, max_ts + pd.Timedelta(days=1)

# Aplicar filtros a BIMs
if micro_sel:
    bims_disp = bims_disp[bims_disp["microalga"].isin(micro_sel)]
if sis_sel:
    bims_disp = bims_disp[bims_disp["sistema"].isin(sis_sel)]

# --------------------------------
# BIM Cards (botones grandes)
# --------------------------------
st.markdown("## BIMs")
cols = st.columns(3, gap="large")

def bim_card(col, row):
    with col:
        c = st.container(border=True)
        with c:
            st.markdown(f"### {row['nombre']}")
            st.caption(f"Microalga: {row['microalga']} · Sistema: {row['sistema']}")
            st.caption(f"Cliente ID: {row['cliente_id']}")
            if st.button("Abrir", key=f"open_{int(row['bim_id'])}"):
                st.session_state['selected_bim_id'] = int(row['bim_id'])

for i, (_, row) in enumerate(bims_disp.iterrows()):
    bim_card(cols[i % 3], row)

# Selección por defecto
if 'selected_bim_id' not in st.session_state and not bims_disp.empty:
    st.session_state['selected_bim_id'] = int(bims_disp.iloc[0]['bim_id'])

selected_bim_id = st.session_state.get('selected_bim_id')

# --------------------------------
# Detalle BIM seleccionado
# --------------------------------
if selected_bim_id is not None and not bims_disp.empty:
    bim_info = bims[bims['bim_id'] == selected_bim_id].iloc[0]
    st.markdown(f"## Detalle {bim_info['nombre']}")

    reg_bim = registros[(registros["bim_id"] == selected_bim_id) &
                        (registros["timestamp"] >= start_date) &
                        (registros["timestamp"] < end_date)].copy()
    diag_bim = diagnosticos[(diagnosticos["bim_id"] == selected_bim_id) &
                            (diagnosticos["fecha"] >= start_date) &
                            (diagnosticos["fecha"] < end_date)].copy()

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("pH medio", f"{reg_bim['ph'].mean():.2f}" if not reg_bim.empty else "–")
    with m2: st.metric("Temperatura media (°C)", f"{reg_bim['temperatura'].mean():.1f}" if not reg_bim.empty else "–")
    with m3: st.metric("O₂ medio (mg/L)", f"{reg_bim['oxigeno'].mean():.2f}" if not reg_bim.empty else "–")
    with m4: st.metric("Lux medio", f"{reg_bim['luz'].mean():.0f}" if not reg_bim.empty else "–")

    tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendencias", "🧪 Diagnóstico", "📋 Registros", "🗺️ Mapa"])

    with tab1:
        st.subheader("Tendencias de sensores")
        colv = st.multiselect("Variables", ["ph", "temperatura", "oxigeno", "luz"], default=["oxigeno", "ph", "temperatura"])
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
        lat = bim_info.get("lat")
        lon = bim_info.get("lon")
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
    st.info("No hay BIMs para los filtros seleccionados.")

st.caption("Technolab · Streamlit · Se conecta a MySQL si configuras secrets.toml; si no, usa CSV o datos demo.")
