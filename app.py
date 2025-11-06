# Create a complete Streamlit app with sample data and a requirements file.
# Files:
# - /mnt/data/app.py
# - /mnt/data/sample_clientes.csv
# - /mnt/data/sample_bims.csv
# - /mnt/data/sample_registros.csv
# - /mnt/data/sample_diagnosticos.csv
# - /mnt/data/requirements.txt
# - /mnt/data/secrets.example.toml

from textwrap import dedent
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import json
import os

# Create sample CSV data
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

# Time series registros (sensor data)
rows = []
for _, r in bims.iterrows():
    base_o2 = np.random.uniform(6.5, 9.5)
    base_ph = np.random.uniform(7.2, 8.3)
    base_temp = np.random.uniform(17, 23)
    base_lux = np.random.uniform(1200, 4500)
    t0 = now - timedelta(days=10)
    for i in range(10*24):  # 10 days, hourly
        ts = t0 + timedelta(hours=i)
        diurnal = np.sin((ts.hour/24)*2*np.pi)  # simple day-night pattern
        oxigeno = base_o2 + diurnal*2 + np.random.normal(0, 0.2)
        ph = base_ph + (0.1 if diurnal>0 else -0.05) + np.random.normal(0, 0.03)
        temp = base_temp + diurnal*3 + np.random.normal(0, 0.4)
        lux = max(0, base_lux*(diurnal+1)) + np.random.normal(0, 80)
        fase = "Adaptación" if i<24 else ("Crecimiento" if i<24*6 else ("Estacionaria" if i<24*9 else "Declive"))
        rows.append({
            "bim_id": r["bim_id"],
            "timestamp": ts.isoformat(),
            "ph": round(ph, 2),
            "temperatura": round(temp, 2),
            "oxigeno": round(oxigeno, 2),
            "luz": round(lux, 0),
            "fase": fase
        })
registros = pd.DataFrame(rows)

# Diagnósticos (resúmenes por día y BIM)
diags = []
for bim_id, g in registros.groupby("bim_id"):
    g['date'] = pd.to_datetime(g['timestamp']).dt.date
    daily = g.groupby('date').agg({
        'ph':'mean','temperatura':'mean','oxigeno':'mean','luz':'mean'
    }).reset_index()
    for _, rr in daily.iterrows():
        diag = "OK"
        alerts = []
        if rr['oxigeno'] < 6.5: alerts.append("Oxígeno bajo")
        if rr['ph'] > 8.8: alerts.append("pH alto")
        if rr['temperatura'] > 28: alerts.append("Temperatura alta")
        if alerts: diag = "; ".join(alerts)
        diags.append({
            "bim_id": bim_id,
            "fecha": rr['date'].isoformat(),
            "resumen": diag
        })
diagnosticos = pd.DataFrame(diags)

# Save CSVs
clientes.to_csv("/mnt/data/sample_clientes.csv", index=False)
bims.to_csv("/mnt/data/sample_bims.csv", index=False)
registros.to_csv("/mnt/data/sample_registros.csv", index=False)
diagnosticos.to_csv("/mnt/data/sample_diagnosticos.csv", index=False)

# Create app.py content
app_code = dedent('''
    import streamlit as st
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta
    import plotly.express as px
    import pydeck as pdk

    st.set_page_config(page_title="Technolab Dashboard", page_icon="🧪", layout="wide")

    # -------------------------------
    # Data loaders
    # -------------------------------
    @st.cache_data(show_spinner=False)
    def load_data():
        # Try DB connection if secrets are present, else fall back to CSV
        use_db = False
        engine = None
        try:
            db = st.secrets.get("mysql", {})
            if db and all(k in db for k in ["host","user","password","database"]):
                from sqlalchemy import create_engine
                conn_str = f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}"
                engine = create_engine(conn_str, pool_pre_ping=True)
                use_db = True
        except Exception:
            use_db = False
            engine = None

        if use_db:
            clientes = pd.read_sql("SELECT id AS cliente_id, nombre, telefono, email FROM clientes", engine)
            bims = pd.read_sql("SELECT id AS bim_id, nombre, cliente_id, microalga, sistema, lat, lon FROM bims", engine)
            registros = pd.read_sql("SELECT bim_id, timestamp, ph, temperatura, oxigeno, luz, fase FROM registros", engine, parse_dates=["timestamp"])
            diagnosticos = pd.read_sql("SELECT bim_id, fecha, resumen FROM diagnosticos", engine, parse_dates=["fecha"])
        else:
            clientes = pd.read_csv("sample_clientes.csv")
            bims = pd.read_csv("sample_bims.csv")
            registros = pd.read_csv("sample_registros.csv", parse_dates=["timestamp"])
            diagnosticos = pd.read_csv("sample_diagnosticos.csv", parse_dates=["fecha"])

        return clientes, bims, registros, diagnosticos

    clientes, bims, registros, diagnosticos = load_data()

    # -------------------------------
    # UI - Sidebar filters
    # -------------------------------
    st.sidebar.title("Filtros")
    # Cliente filter
    cliente_opciones = ["Todos"] + sorted(clientes["nombre"].unique().tolist())
    cliente_sel = st.sidebar.selectbox("Cliente", cliente_opciones, index=0)

    # Derive BIM options based on client
    if cliente_sel != "Todos":
        cliente_ids = clientes.loc[clientes["nombre"]==cliente_sel, "cliente_id"].tolist()
        bims_disp = bims[bims["cliente_id"].isin(cliente_ids)]
    else:
        bims_disp = bims.copy()

    # Microalga / Sistema filters
    micro_sel = st.sidebar.multiselect("Microalga", sorted(bims_disp["microalga"].unique().tolist()))
    sis_sel = st.sidebar.multiselect("Sistema", sorted(bims_disp["sistema"].unique().tolist()))

    # Fecha filtro
    st.sidebar.subheader("Rango de tiempo")
    max_ts = registros["timestamp"].max()
    min_ts = registros["timestamp"].min()
    default_start = max_ts - pd.Timedelta(days=7)
    rango = st.sidebar.date_input("Fecha (inicio, fin)", value=(default_start.date(), max_ts.date()))
    if isinstance(rango, tuple) and len(rango)==2:
        start_date = pd.to_datetime(rango[0])
        end_date = pd.to_datetime(rango[1]) + pd.Timedelta(days=1)
    else:
        start_date, end_date = default_start, max_ts

    # Apply sidebar filters to BIMs
    if micro_sel:
        bims_disp = bims_disp[bims_disp["microalga"].isin(micro_sel)]
    if sis_sel:
        bims_disp = bims_disp[bims_disp["sistema"].isin(sis_sel)]

    # -------------------------------
    # BIM Cards (giant buttons)
    # -------------------------------
    st.markdown("## BIMs")
    cols = st.columns(3, gap="large")
    selected_bim_id = st.session_state.get("selected_bim_id")

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

    # If none selected yet, pick first available
    if 'selected_bim_id' not in st.session_state and not bims_disp.empty:
        st.session_state['selected_bim_id'] = int(bims_disp.iloc[0]['bim_id'])

    selected_bim_id = st.session_state.get('selected_bim_id')

    # -------------------------------
    # Main area tabs for selected BIM
    # -------------------------------
    if selected_bim_id is not None and not bims_disp.empty:
        bim_info = bims[bims['bim_id']==selected_bim_id].iloc[0]
        st.markdown(f"## Detalle {bim_info['nombre']}")

        # Filter registros for this BIM and date range
        reg_bim = registros[(registros["bim_id"]==selected_bim_id) &
                            (registros["timestamp"]>=start_date) &
                            (registros["timestamp"]<end_date)].copy()
        diag_bim = diagnosticos[(diagnosticos["bim_id"]==selected_bim_id) &
                                (diagnosticos["fecha"]>=start_date) &
                                (diagnosticos["fecha"]<end_date)].copy()

        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric("pH medio", f"{reg_bim['ph'].mean():.2f}")
        with m2: st.metric("Temperatura media (°C)", f"{reg_bim['temperatura'].mean():.1f}")
        with m3: st.metric("O₂ medio (mg/L)", f"{reg_bim['oxigeno'].mean():.2f}")
        with m4: st.metric("Lux medio", f"{reg_bim['luz'].mean():.0f}")

        tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendencias", "🧪 Diagnóstico", "📋 Registros", "🗺️ Mapa"])

        with tab1:
            st.subheader("Tendencias de sensores")
            colv = st.multiselect("Variables", ["ph","temperatura","oxigeno","luz"], default=["oxigeno","ph","temperatura"])
            if not reg_bim.empty:
                for v in colv:
                    fig = px.line(reg_bim, x="timestamp", y=v, title=v.capitalize())
                    st.plotly_chart(fig, use_container_width=True)
                # Fase apilada por tiempo
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
            if pd.notnull(bim_info.get("lat")) and pd.notnull(bim_info.get("lon")):
                layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=pd.DataFrame([{"lat": bim_info["lat"], "lon": bim_info["lon"]}]),
                    get_position='[lon, lat]',
                    get_radius=50,
                    pickable=True
                )
                st.pydeck_chart(pdk.Deck(
                    map_style=None,
                    initial_view_state=pdk.ViewState(latitude=bim_info["lat"], longitude=bim_info["lon"], zoom=12, pitch=0),
                    layers=[layer]
                ))
            else:
                st.info("Sin coordenadas para este BIM.")

    else:
        st.info("No hay BIMs para los filtros seleccionados.")

    # -------------------------------
    # Footer
    # -------------------------------
    st.caption("Technolab · Demo Streamlit · Conexión automática a MySQL si se configuran credenciales en secrets.toml")
''')

with open("/mnt/data/app.py", "w", encoding="utf-8") as f:
    f.write(app_code)

# Create requirements.txt based on user's list
requirements = dedent('''
streamlit==1.39.0
sqlalchemy==2.0.35
pymysql==1.1.1
pandas==2.2.3
numpy==2.1.1
python-dotenv==1.0.1
pymongo==4.9.1
pydeck==0.9.1
plotly==5.24.1
streamlit-folium==0.22.0
''')
with open("/mnt/data/requirements.txt", "w") as f:
    f.write(requirements)

# Create secrets.example.toml
secrets = dedent('''
# Rename this file to .streamlit/secrets.toml in your project
[mysql]
host = "YOUR_HOST"
user = "YOUR_USER"
password = "YOUR_PASSWORD"
database = "YOUR_DB"
''')
with open("/mnt/data/secrets.example.toml", "w") as f:
    f.write(secrets)

# Show dataframes to user visually
from caas_jupyter_tools import display_dataframe_to_user
display_dataframe_to_user("Sample BIMs", bims)
display_dataframe_to_user("Sample Registros (first 200 rows)", registros.head(200))

# Return paths so the notebook prints something useful
{
    "files": [
        "/mnt/data/app.py",
        "/mnt/data/sample_clientes.csv",
        "/mnt/data/sample_bims.csv",
        "/mnt/data/sample_registros.csv",
        "/mnt/data/sample_diagnosticos.csv",
        "/mnt/data/requirements.txt",
        "/mnt/data/secrets.example.toml"
    ]
}
