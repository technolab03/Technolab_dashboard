# app.py — Technolab Data Center (IconLayer 🚜 + ruta óptima con API ORS)
# -*- coding: utf-8 -*-
import os
import re
from math import radians, sin, cos, asin, sqrt

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text, event
from datetime import datetime, timedelta

st.set_page_config(page_title="Technolab Data Center", page_icon="🧪", layout="wide")

# ==========================================================
# Estilos
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
# Conexión MySQL
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
# Utilitarios
# ==========================================================
def q(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return pd.read_sql(text(sql), ENGINE, params=params)
    except Exception as e:
        st.error(f"Error de consulta SQL: {e}")
        return pd.DataFrame()

def _norm_bim_series(s: pd.Series) -> pd.Series:
    x = s.astype("string").fillna("").str.strip()
    x = x.str.replace(r"^\s*bim\s*", "", regex=True)
    x = x.str.lower().replace({"none":"", "null":"", "ninguno":""})
    return x

_coord_pattern = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
def _to_float_coord(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    m = _coord_pattern.search(s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except Exception:
        return None

# --- Distancia y orden aproximado (para TSP básico) ---
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia aproximada en km entre dos puntos (lat, lon) usando haversine."""
    R = 6371.0  # radio de la Tierra en km
    lat1_r, lon1_r = radians(lat1), radians(lon1)
    lat2_r, lon2_r = radians(lat2), radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = sin(dlat / 2)**2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def build_route_nearest_neighbor(df_points: pd.DataFrame) -> pd.DataFrame:
    """
    Recibe un DataFrame con columnas: cliente, numero_bim, latitud, longitud
    Devuelve el mismo DataFrame ordenado según una ruta aproximada (nearest neighbor).
    """
    if df_points.empty or len(df_points) == 1:
        return df_points.reset_index(drop=True)

    remaining = df_points.copy().reset_index(drop=True)
    route_rows = []

    # Partimos desde el primer punto (puedes cambiar la lógica de partida si quieres)
    current_idx = 0
    route_rows.append(remaining.loc[current_idx])
    remaining = remaining.drop(index=current_idx).reset_index(drop=True)

    while not remaining.empty:
        last_lat = route_rows[-1]["latitud"]
        last_lon = route_rows[-1]["longitud"]

        # Encontrar el más cercano
        dists = remaining.apply(
            lambda r: haversine_km(last_lat, last_lon, r["latitud"], r["longitud"]),
            axis=1
        )
        next_idx = dists.idxmin()
        route_rows.append(remaining.loc[next_idx])
        remaining = remaining.drop(index=next_idx).reset_index(drop=True)

    route_df = pd.DataFrame(route_rows).reset_index(drop=True)
    return route_df

def get_driving_route_ors(coords):
    """
    Llama a la API de OpenRouteService para obtener la ruta por carretera.
    coords debe ser una lista de [lon, lat] en el orden de visita.
    Devuelve (distancia_km, duracion_horas, geometria_coords) o (None, None, None) si hay error.
    """
    if "ors" not in st.secrets or "api_key" not in st.secrets["ors"]:
        st.error("Falta configurar st.secrets['ors']['api_key'] con tu API Key de OpenRouteService.")
        return None, None, None

    api_key = st.secrets["ors"]["api_key"]
    url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "coordinates": coords,
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        st.error(f"Error al llamar a la API de rutas: {e}")
        return None, None, None

    try:
        feat = data["features"][0]
        summary = feat["properties"]["summary"]
        distancia_km = summary["distance"] / 1000.0      # metros → km
        duracion_h  = summary["duration"] / 3600.0       # segundos → horas
        geometria   = feat["geometry"]["coordinates"]    # lista [lon, lat]
        return distancia_km, duracion_h, geometria
    except Exception as e:
        st.error(f"Respuesta inesperada de la API de rutas: {e}")
        return None, None, None

# ==========================================================
# Consultas con caché
# ==========================================================
@st.cache_data(ttl=180)
def get_clientes() -> pd.DataFrame:
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

# ↓↓↓ biorreactores y mapa con TTL = 1s para ver cambios rápido ↓↓↓
@st.cache_data(ttl=1)
def get_biorreactores() -> pd.DataFrame:
    return q("""
        SELECT
           id,
           cliente,
           TRIM(CAST(numero_bim AS CHAR CHARACTER SET utf8mb4)) AS numero_bim,
           latitud, longitud, altura_bim,
           tipo_microalga, uso_luz_artificial, tipo_aireador,
           `fecha_instalación` AS fecha_instalacion
        FROM biorreactores
        ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=1)
def get_map_df(cliente_sel: str | None = None) -> pd.DataFrame:
    cat = get_biorreactores().copy()
    if cliente_sel and cliente_sel != "Todos":
        cat = cat[cat["cliente"].fillna("").str.strip() == cliente_sel]

    cat["latitud"]  = cat["latitud"].map(_to_float_coord)
    cat["longitud"] = cat["longitud"].map(_to_float_coord)
    cat = cat.dropna(subset=["latitud","longitud"])
    if cat.empty:
        return cat

    cat["label"] = "BIM " + cat["numero_bim"].astype("string")

    # Icono tipo emoji 🚜 usando Twemoji
    icon_cfg = {
        "url": "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f69c.png",  # 🚜
        "width": 72,
        "height": 72,
        "anchorY": 72,
    }
    cat["icon_data"] = [icon_cfg] * len(cat)

    return cat[["cliente","numero_bim","latitud","longitud","tipo_microalga","label","icon_data"]]

@st.cache_data(ttl=180)
def get_eventos(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": str(bim), "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_diagnosticos(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC
    """, {"bim": str(bim), "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_registros(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC
    """, {"bim": str(bim), "d1": d1, "d2": d2})

# ==========================================================
# KPIs
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
# Navegación
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

def go_map():
    st.session_state.page = "map"
    st.query_params.clear()
    st.query_params["page"] = "map"

if "page" not in st.session_state:
    st.session_state.page = st.query_params.get("page", "home")
if "selected_bim" not in st.session_state:
    st.session_state.selected_bim = st.query_params.get("bim", None)

# ==========================================================
# Página principal
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

    # --- Filtros laterales + acceso al mapa ---
    st.sidebar.title("Filtros de visualización")
    bio_df = get_biorreactores().copy()
    bio_df["cliente"] = bio_df["cliente"].astype("string")

    clientes_opts = ["Todos"] + sorted(
        [c for c in bio_df["cliente"].dropna().str.strip().unique().tolist() if c != ""]
    )
    cliente_sel = st.sidebar.selectbox("Cliente", clientes_opts, key="cliente_sel_home")

    if st.sidebar.button("🌍 Abrir mapa de bioreactores"):
        go_map()

    # --- Listado de bioreactores ---
    st.divider()
    st.subheader("📋 Listado de Bioreactores")

    if cliente_sel != "Todos":
        bio_df = bio_df[bio_df["cliente"].fillna("").str.strip() == cliente_sel]

    if bio_df.empty:
        st.warning("No se encontraron bioreactores para el filtro aplicado.")
    else:
        for cliente, grp in bio_df.groupby(bio_df["cliente"].fillna("").str.strip(), dropna=False):
            if cliente:
                st.markdown(f"### 👤 {cliente}")

            cols = st.columns(3)
            for i, (_, r) in enumerate(grp.iterrows()):
                with cols[i % 3]:
                    label_btn = f"🌿 BIM {r['numero_bim']}"
                    if st.button(label_btn, key=f"btn_bim_{cliente or 'sin_cliente'}_{r['numero_bim']}"):
                        go_detail(str(r["numero_bim"]))

# ==========================================================
# Página del mapa (ventana propia) + ruta óptima real por carretera
# ==========================================================
def view_map():
    st.markdown(
        '<a class="btn-link" href="?page=home" target="_self">⬅️ Volver al Panel General</a>',
        unsafe_allow_html=True,
    )
    st.title("🌍 Mapa de Bioreactores")

    base = get_biorreactores()
    base["cliente"] = base["cliente"].astype("string").str.strip()

    # --- Selección múltiple de agricultores ---
    clientes_unicos = sorted([c for c in base["cliente"].dropna().unique().tolist() if c != ""])
    clientes_sel = st.multiselect(
        "Seleccionar agricultores (clientes) para visualizar",
        clientes_unicos,
        default=clientes_unicos,
        key="clientes_sel_map",
    )

    if not clientes_sel:
        st.info("Selecciona al menos un agricultor para visualizar en el mapa.")
        return

    # Dataframe de bioreactores filtrado por los clientes seleccionados
    df_map = get_map_df()  # sin filtro para poder aplicar varios clientes
    df_map["cliente"] = df_map["cliente"].astype("string").str.strip()
    df_map = df_map[df_map["cliente"].isin(clientes_sel)]

    if df_map.empty:
        st.info("No existen coordenadas registradas para los bioreactores de los agricultores seleccionados.")
        return

    import pydeck as pdk

    # Centro del mapa según los BIMs filtrados
    lat0 = float(df_map["latitud"].mean())
    lon0 = float(df_map["longitud"].mean())
    zoom = 8 if len(clientes_sel) > 1 else 12

    view = pdk.ViewState(latitude=lat0, longitude=lon0, zoom=zoom, pitch=0)

    # Capa de iconos 🚜
    layer_icon = pdk.Layer(
        "IconLayer",
        data=df_map,
        get_icon="icon_data",
        get_position="[longitud, latitud]",
        size_scale=15,
        get_size=2,
        pickable=True,
    )

    # Capa de labels "BIM X"
    df_map["title"] = df_map["label"].astype(str)
    layer_label = pdk.Layer(
        "TextLayer",
        data=df_map,
        get_position="[longitud, latitud]",
        get_text="title",
        get_size=14,
        get_color=[255, 255, 255],
        get_text_anchor="start",
        get_alignment_baseline="center",
        get_pixel_offset=[18, 0],
    )

    # --- Planificador de ruta por carretera (API ORS) ---
    st.subheader("🧭 Planificador de ruta por carretera (OpenRouteService)")

    # Seleccionar BIMs específicos dentro de los clientes filtrados
    df_map["numero_bim"] = df_map["numero_bim"].astype("string")
    bims_disponibles = sorted(df_map["numero_bim"].unique().tolist())
    bims_sel = st.multiselect(
        "Selecciona los BIMs que quieres incluir en la ruta",
        options=bims_disponibles,
        default=bims_disponibles,
        key="bims_sel_ruta",
    )

    calcular_ruta = st.button("Calcular ruta óptima aproximada y trazado real por carretera")

    route_df = None
    ruta_coords = None
    distancia_km = None
    duracion_h = None

    if calcular_ruta:
        stops = (
            df_map[df_map["numero_bim"].isin(bims_sel)][["cliente", "numero_bim", "latitud", "longitud"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )

        if len(stops) < 2:
            st.info("Se necesita al menos 2 BIMs para calcular una ruta.")
        else:
            # 1) Orden aproximado (heurística vecino más cercano) con haversine
            route_df = build_route_nearest_neighbor(stops)

            # 2) Coordenadas en el orden calculado para la API de rutas (lon, lat)
            coords = [
                [float(row["longitud"]), float(row["latitud"])]
                for _, row in route_df.iterrows()
            ]

            # 3) Ruta real por carretera con ORS
            distancia_km, duracion_h, ruta_coords = get_driving_route_ors(coords)

            if distancia_km is not None and duracion_h is not None and ruta_coords:
                st.metric("Distancia total por carretera (km)", f"{distancia_km:,.1f}")
                st.metric("Tiempo total estimado (horas)", f"{duracion_h:,.2f}")

                st.markdown("**Orden sugerido de visita (después de optimización aproximada):**")
                st.dataframe(
                    route_df[["cliente", "numero_bim", "latitud", "longitud"]],
                    use_container_width=True,
                )

    # --- Capas del mapa (iconos + etiquetas + ruta si existe) ---
    layers = [layer_icon, layer_label]

    if ruta_coords:
        path_data = [{"path": ruta_coords}]
        layer_path = pdk.Layer(
            "PathLayer",
            data=path_data,
            get_path="path",
            get_width=50,
            get_color=[0, 255, 0],
            pickable=False,
        )
        layers.append(layer_path)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        tooltip={"html": "<b>{label}</b><br/>Cliente: {cliente}<br/>Microalga: {tipo_microalga}"},
    )
    st.pydeck_chart(deck, use_container_width=True)

# ==========================================================
# Detalle del Bioreactor
# ==========================================================
def view_detail():
    catalogo = get_biorreactores()
    bim = str(st.session_state.selected_bim) if st.session_state.selected_bim else None

    if not bim or bim not in set(catalogo["numero_bim"].astype("string")):
        st.info("Bioreactor no encontrado. Regresando al panel general…")
        go_home()
        st.stop()

    st.markdown(
        '<a class="btn-link" href="?page=home" target="_self">⬅️ Volver al Panel General</a>',
        unsafe_allow_html=True,
    )
    st.title(f"🧬 Detalle del Bioreactor {bim}")

    sel = catalogo[catalogo["numero_bim"].astype("string") == bim].iloc[0]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Cliente:** {sel.get('cliente') or '—'}")
        st.markdown(f"**Microalga cultivada:** {sel.get('tipo_microalga') or '—'}")
        st.markdown(f"**Tipo de aireador:** {sel.get('tipo_aireador') or '—'}")
        st.markdown(f"**Altura del bioreactor:** {sel.get('altura_bim') or '—'} m")
    with c2:
        luz = sel.get('uso_luz_artificial')
        st.markdown(f"**Luz artificial:** {'Sí' if bool(luz) else 'No' if luz is not None else '—'}")
        st.markdown(f"**Fecha de instalación:** {sel.get('fecha_instalacion') or '—'}")
        st.markdown(f"**Coordenadas:** ({sel.get('latitud') or '—'}, {sel.get('longitud') or '—'})")

    st.divider()
    hoy = datetime.utcnow().date()
    d1 = datetime.combine(st.date_input("Desde", hoy - timedelta(days=30), key="d1_detail"), datetime.min.time())
    d2 = datetime.combine(st.date_input("Hasta", hoy, key="d2_detail"), datetime.max.time())

    T1, T2, T3 = st.tabs(["Registros", "Diagnósticos", "Eventos del bioreactor"])

    with T1:
        df_r = get_registros(bim, d1, d2)
        st.metric("Total de registros", len(df_r))
        if df_r.empty:
            st.info("Sin registros en el rango indicado.")
        else:
            st.dataframe(df_r, use_container_width=True)
            st.download_button(
                "Descargar CSV",
                df_r.to_csv(index=False).encode("utf-8"),
                file_name=f"registros_BIM{bim}.csv",
            )

    with T2:
        df_d = get_diagnosticos(bim, d1, d2)
        st.metric("Total de diagnósticos", len(df_d))
        if df_d.empty:
            st.info("Sin diagnósticos en el rango indicado.")
        else:
            st.dataframe(df_d, use_container_width=True)
            st.download_button(
                "Descargar CSV",
                df_d.to_csv(index=False).encode("utf-8"),
                file_name=f"diagnosticos_BIM{bim}.csv",
            )

    with T3:
        df_e = get_eventos(bim, d1, d2)
        st.metric("Total de eventos", len(df_e))
        if df_e.empty:
            st.info("Sin eventos registrados para este bioreactor en el rango indicado.")
        else:
            st.dataframe(df_e, use_container_width=True)
            st.download_button(
                "Descargar CSV",
                df_e.to_csv(index=False).encode("utf-8"),
                file_name=f"eventos_BIM{bim}.csv",
            )

# ==========================================================
# Routing
# ==========================================================
page = st.session_state.get("page", st.query_params.get("page", "home"))
if page == "detail":
    view_detail()
elif page == "map":
    view_map()
else:
    view_home()

st.caption("© Technolab — Sistema de Gestión y Monitoreo de Bioreactores.")
