import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timedelta

st.set_page_config(page_title="Technolab Data Center", page_icon="🧪", layout="wide")

# ======================================================
# 🔗 CONEXIÓN DIRECTA A MYSQL (DigitalOcean)
# ======================================================
engine = create_engine(
    "mysql+pymysql://makeuser:NUEVA_PASSWORD_SEGURA@143.198.144.39:3306/technolab",
    pool_pre_ping=True
)

# ======================================================
# 📦 CARGA DE DATOS CON CONVERSIÓN DE FECHAS
# ======================================================
@st.cache_data(show_spinner=False)
def load_data():
    clientes = pd.read_sql("SELECT * FROM clientes", engine)
    biorreactores = pd.read_sql("SELECT * FROM biorreactores", engine)
    fechas_bims = pd.read_sql("SELECT * FROM fechas_BIMs", engine)
    diagnosticos = pd.read_sql("SELECT * FROM diagnosticos", engine)
    registros = pd.read_sql("SELECT * FROM registros", engine)

    # 🔧 Convertir columnas 'fecha' en todas las tablas si existen
    for df in [fechas_bims, diagnosticos, registros]:
        if "fecha" in df.columns:
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    return clientes, biorreactores, fechas_bims, diagnosticos, registros


clientes, biorreactores, fechas_bims, diagnosticos, registros = load_data()

# ======================================================
# 🎛️ SIDEBAR: FILTROS
# ======================================================
st.sidebar.title("🎛️ Filtros de visualización")

clientes_lista = sorted(clientes["cliente"].dropna().unique().tolist())
cliente_sel = st.sidebar.selectbox("👤 Cliente", ["Todos"] + clientes_lista)

if cliente_sel != "Todos":
    bims_cliente = biorreactores[biorreactores["cliente"] == cliente_sel]["numero_bim"].unique().tolist()
else:
    bims_cliente = sorted(biorreactores["numero_bim"].unique().tolist())

bim_sel = st.sidebar.selectbox("🧫 BIM", ["Todos"] + [str(x) for x in bims_cliente])

rango = st.sidebar.date_input(
    "📆 Rango de fechas",
    value=(datetime.today() - timedelta(days=30), datetime.today())
)
if isinstance(rango, tuple) and len(rango) == 2:
    start_date, end_date = pd.to_datetime(rango[0]), pd.to_datetime(rango[1]) + timedelta(days=1)
else:
    start_date, end_date = datetime.today() - timedelta(days=30), datetime.today()

# ======================================================
# 🧮 APLICAR FILTROS CON VALIDACIÓN DE TIPOS
# ======================================================
biorreactores_f = biorreactores.copy()
fechas_f = fechas_bims.copy()
diag_f = diagnosticos.copy()
reg_f = registros.copy()

# Filtros por cliente
if cliente_sel != "Todos":
    biorreactores_f = biorreactores_f[biorreactores_f["cliente"] == cliente_sel]
    if "numero_bim" in fechas_f.columns:
        fechas_f = fechas_f.merge(biorreactores_f[["numero_bim"]], on="numero_bim", how="inner")
    if "usuario_id" in diag_f.columns and "usuario_id" in clientes.columns:
        diag_f = diag_f.merge(clientes[clientes["cliente"] == cliente_sel][["usuario_id"]], on="usuario_id", how="inner")
    if "usuario_id" in reg_f.columns and "usuario_id" in clientes.columns:
        reg_f = reg_f.merge(clientes[clientes["cliente"] == cliente_sel][["usuario_id"]], on="usuario_id", how="inner")

# Filtros por BIM
if bim_sel != "Todos":
    biorreactores_f = biorreactores_f[biorreactores_f["numero_bim"].astype(str) == bim_sel]
    if "numero_bim" in fechas_f.columns:
        fechas_f = fechas_f[fechas_f["numero_bim"].astype(str) == bim_sel]
    if "BIM" in reg_f.columns:
        reg_f = reg_f[reg_f["BIM"].astype(str) == bim_sel]

# 🧹 Limpieza de fechas
for df in [fechas_f, diag_f, reg_f]:
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
        df = df[df["fecha"].notna()]
        # asegurar tipo datetime64
        if not pd.api.types.is_datetime64_any_dtype(df["fecha"]):
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

# ✅ Filtrar por rango de fechas SOLO si la columna es datetime
def filtrar_por_fecha(df):
    if "fecha" in df.columns and pd.api.types.is_datetime64_any_dtype(df["fecha"]):
        return df[(df["fecha"] >= start_date) & (df["fecha"] < end_date)]
    return df

fechas_f = filtrar_por_fecha(fechas_f)
diag_f = filtrar_por_fecha(diag_f)
reg_f = filtrar_por_fecha(reg_f)

# ======================================================
# 🧠 ENCABEZADO
# ======================================================
st.markdown("""
# 🧪 Technolab Data Center  
Visualizador de clientes, BIMs y diagnósticos automáticos.
""")

# ======================================================
# 🧫 TARJETAS DE BIORREACTORES
# ======================================================
st.markdown("### 🧬 Biorreactores disponibles")

if biorreactores_f.empty:
    st.info("No hay biorreactores para los filtros seleccionados.")
else:
    cols = st.columns(3)
    for i, (_, row) in enumerate(biorreactores_f.iterrows()):
        with cols[i % 3]:
            c = st.container(border=True)
            with c:
                st.markdown(f"### 🧫 BIM #{row['numero_bim']}")
                st.markdown(f"**Cliente:** {row['cliente']}")
                st.markdown(f"**Microalga:** {row['tipo_microalga']}")
                st.markdown(f"**Instalado:** {row['fecha_instalación']}")
                if st.button("🔍 Ver detalles", key=f"bim_{row['numero_bim']}"):
                    st.session_state["bim_actual"] = row["numero_bim"]

if "bim_actual" not in st.session_state:
    if not biorreactores_f.empty:
        st.session_state["bim_actual"] = biorreactores_f.iloc[0]["numero_bim"]

bim_actual = st.session_state.get("bim_actual")

# ======================================================
# 🧫 DETALLE DEL BIM
# ======================================================
if bim_actual is None or bim_actual not in biorreactores["numero_bim"].values:
    st.stop()

bior = biorreactores[biorreactores["numero_bim"] == bim_actual].iloc[0]
st.markdown(f"## 🧫 Detalles del BIM #{bim_actual}")

tab1, tab2, tab3, tab4 = st.tabs([
    "🧬 Datos del Biorreactor",
    "📅 Eventos BIM",
    "💬 Diagnósticos GPT",
    "📄 Registros GPT/Make"
])

# ---------- TAB 1 ----------
with tab1:
    st.subheader("📋 Información técnica")
    st.markdown(f"""
    **Cliente:** {bior['cliente']}  
    **Tipo de microalga:** {bior['tipo_microalga']}  
    **Aireador:** {bior['tipo_aireador']}  
    **Luz artificial:** {'Sí' if bior['uso_luz_artificial'] else 'No'}  
    **Altura:** {bior['altura_bim']} m  
    **Fecha instalación:** {bior['fecha_instalación']}  
    """)
    if pd.notnull(bior["latitud"]) and pd.notnull(bior["longitud"]):
        st.pydeck_chart(pdk.Deck(
            map_style="mapbox://styles/mapbox/light-v9",
            initial_view_state=pdk.ViewState(
                latitude=bior["latitud"],
                longitude=bior["longitud"],
                zoom=12,
                pitch=45
            ),
            layers=[
                pdk.Layer(
                    "ScatterplotLayer",
                    data=pd.DataFrame([{
                        "lat": bior["latitud"],
                        "lon": bior["longitud"]
                    }]),
                    get_position='[lon, lat]',
                    get_radius=60,
                    get_color='[0, 150, 200, 200]'
                )
            ]
        ))
    else:
        st.info("🌍 Este BIM no tiene coordenadas registradas.")

# ---------- TAB 2 ----------
with tab2:
    st.subheader("📅 Eventos asociados")
    if not fechas_f.empty:
        st.dataframe(fechas_f.sort_values("fecha", ascending=False), use_container_width=True)
    else:
        st.info("No hay eventos registrados en este rango.")

# ---------- TAB 3 ----------
with tab3:
    st.subheader("💬 Diagnósticos automáticos (GPT)")
    if not diag_f.empty:
        st.dataframe(
            diag_f.sort_values("fecha", ascending=False)[["PreguntaCliente", "respuestaGPT", "fecha"]],
            use_container_width=True, height=420
        )
    else:
        st.info("Sin diagnósticos en el rango seleccionado.")

# ---------- TAB 4 ----------
with tab4:
    st.subheader("📄 Registros GPT / Make")
    if not reg_f.empty:
        st.dataframe(
            reg_f.sort_values("fecha", ascending=False)[["BIM", "respuestaGPT", "HEX", "fecha"]],
            use_container_width=True, height=420
        )
    else:
        st.info("Sin registros disponibles.")

st.caption("🧠 Technolab · Panel de Control Integrado · Datos recolectados por Make y WhatsApp.")
