# app.py — Technolab Data Center (IconLayer 🚜 + ruta óptima con API ORS + MATRIZ)
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
# Casa Matriz Technolab — MATRIZ (punto 0)
# ==========================================================
ORIGIN_LAT = -29.947648
ORIGIN_LON = -71.248671

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

# Distancia haversine
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    lat1_r, lon1_r = radians(lat1), radians(lon1)
    lat2_r, lon2_r = radians(lat2), radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = sin(dlat/2)**2 + cos(lat1_r) * cos(lat2_r) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def build_route_nearest_neighbor(df_points: pd.DataFrame) -> pd.DataFrame:
    if df_points.empty or len(df_points) == 1:
        return df_points.reset_index(drop=True)

    remaining = df_points.copy().reset_index(drop=True)
    route_rows = []

    current_idx = 0
    route_rows.append(remaining.loc[current_idx])
    remaining = remaining.drop(index=current_idx).reset_index(drop=True)

    while not remaining.empty:
        last_lat = route_rows[-1]["latitud"]
        last_lon = route_rows[-1]["longitud"]

        dists = remaining.apply(
            lambda r: haversine_km(last_lat, last_lon, r["latitud"], r["longitud"]),
            axis=1
        )
        next_idx = dists.idxmin()
        route_rows.append(remaining.loc[next_idx])
        remaining = remaining.drop(index=next_idx).reset_index(drop=True)

    return pd.DataFrame(route_rows).reset_index(drop=True)

def get_driving_route_ors(coords):
    if "ors" not in st.secrets or "api_key" not in st.secrets["ors"]:
        st.error("Falta configurar st.secrets['ors']['api_key']")
        return None, None, None

    api_key = st.secrets["ors"]["api_key"]
    url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": coords}

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
        distancia_km = summary["distance"] / 1000
        duracion_h = summary["duration"] / 3600
        geometria = feat["geometry"]["coordinates"]
        return distancia_km, duracion_h, geometria
    except Exception as e:
        st.error(f"Respuesta inesperada de la API: {e}")
        return None, None, None

# ==========================================================
# Consultas con caché
# ==========================================================
@st.cache_data(ttl=180)
def get_clientes() -> pd.DataFrame:
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

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

@st.cache_data(ttl=180)
def get_eventos(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, numero_bim, nombre_evento, fecha, comentarios
        FROM fechas_BIMs
        WHERE numero_bim = :bim
          AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC, id DESC
    """, {"bim": str(bim), "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_diagnosticos(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT d.id, d.usuario_id, d.PreguntaCliente, d.respuestaGPT, d.fecha
        FROM diagnosticos d
        WHERE d.usuario_id IN (SELECT r.usuario_id FROM registros r WHERE r.BIM = :bim)
          AND d.fecha BETWEEN :d1 AND :d2
        ORDER BY d.fecha DESC, d.id DESC
    """, {"bim": str(bim), "d1": d1, "d2": d2})

@st.cache_data(ttl=180)
def get_registros(bim: str, d1: datetime, d2: datetime) -> pd.DataFrame:
    return q("""
        SELECT id, usuario_id, BIM, respuestaGPT, HEX, fecha
        FROM registros
        WHERE BIM = :bim AND fecha BETWEEN :d1 AND :d2
        ORDER BY fecha DESC, id DESC
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

    df_bio = q("SELECT numero_bim FROM biorreactores")
    total_bims = df_bio["numero_bim"].nunique() if not df_bio.empty else 0

    d = q("SELECT COUNT(*) AS c FROM diagnosticos")
    r = q("SELECT COUNT(*) AS c FROM registros")
    e = q("SELECT COUNT(*) AS c FROM fechas_BIMs")

    total_diag = int(d["c"].iloc[0]) if not d.empty else 0
    total_regs = int(r["c"].iloc[0]) if not r.empty else 0
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
    k2.metric("Biorreactores operativos", tb)
    k3.metric("Diagnósticos registrados", td)
    k4.metric("Registros de datos", tr)
    k5.metric("Eventos asociados", te)

    st.sidebar.title("Filtros de visualización")
    bio_df = get_biorreactores()
    bio_df["cliente"] = bio_df["cliente"].astype("string")

    clientes_opts = ["Todos"] + sorted(
        [c for c in bio_df["cliente"].dropna().str.strip().unique().tolist() if c]
    )
    cliente_sel = st.sidebar.selectbox("Cliente", clientes_opts, key="cliente_sel_home")

    if st.sidebar.button("🌍 Abrir mapa de biorreactores"):
        go_map()

    st.divider()
    st.subheader("📋 Listado de biorreactores")

    if cliente_sel != "Todos":
        bio_df = bio_df[bio_df["cliente"].fillna("").str.strip() == cliente_sel]

    if bio_df.empty:
        st.warning("No se encontraron biorreactores para el filtro aplicado.")
    else:
        for cliente, grp in bio_df.groupby(bio_df["cliente"].fillna("").str.strip(), dropna=False):
            if cliente:
                st.markdown(f"### 👤 {cliente}")

            cols = st.columns(3)
            for i, (_, r) in enumerate(grp.iterrows()):
                with cols[i % 3]:
                    btn = f"🌿 BIM {r['numero_bim']}"
                    if st.button(btn, key=f"btn_bim_{cliente}_{r['numero_bim']}"):
                        go_detail(str(r["numero_bim"]))
# ==========================================================
# Página del mapa
# ==========================================================
def view_map():
    st.markdown(
        '<a class="btn-link" href="?page=home" target="_self">⬅️ Volver al Panel General</a>',
        unsafe_allow_html=True,
    )
    st.title("🌍 Mapa de biorreactores")

    df_map = get_biorreactores().copy()
    if df_map.empty:
        st.info("No existen coordenadas registradas para los biorreactores.")
        return

    import pydeck as pdk

    df_map["cliente"] = df_map["cliente"].astype("string").str.strip()
    df_map["numero_bim"] = df_map["numero_bim"].astype("string")
    df_map["latitud"] = df_map["latitud"].map(_to_float_coord)
    df_map["longitud"] = df_map["longitud"].map(_to_float_coord)
    df_map = df_map.dropna(subset=["latitud", "longitud"])

    # Añadir punto de la casa matriz
    matriz_row = {
        "cliente": "Casa Matriz Technolab",
        "numero_bim": "Matriz",
        "latitud": ORIGIN_LAT,
        "longitud": ORIGIN_LON,
        "tipo_microalga": None,
    }
    df_map = pd.concat([df_map, pd.DataFrame([matriz_row])], ignore_index=True)

    # Iconos
    tractor_icon_cfg = {
        "url": "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f69c.png",
        "width": 72, "height": 72, "anchorY": 72
    }
    matriz_icon_cfg = {
        "url": "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f3e0.png",
        "width": 72, "height": 72, "anchorY": 72
    }

    df_map["icon_data"] = df_map["numero_bim"].apply(
        lambda x: matriz_icon_cfg if x == "Matriz" else tractor_icon_cfg
    )
    df_map["title"] = df_map["numero_bim"].astype(str)

    bims_opts = sorted(df_map["numero_bim"].unique().tolist())
    bim_focus = st.selectbox(
        "Selecciona el BIM para centrar el mapa",
        options=bims_opts,
        key="bim_focus_map",
    )

    focus_row = df_map[df_map["numero_bim"] == bim_focus].iloc[0]
    lat0, lon0 = float(focus_row["latitud"]), float(focus_row["longitud"])

    view = pdk.ViewState(latitude=lat0, longitude=lon0, zoom=12)

    layer_icon = pdk.Layer(
        "IconLayer",
        data=df_map,
        get_icon="icon_data",
        get_position="[longitud, latitud]",
        size_scale=15,
        get_size=2,
        pickable=True
    )

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

    st.pydeck_chart(
        pdk.Deck(
            layers=[layer_icon, layer_label],
            initial_view_state=view,
            tooltip={"html": "<b>{title}</b><br/>Cliente: {cliente}"}
        ),
        use_container_width=True,
    )

# ==========================================================
# Detalle del biorreactor
# ==========================================================
def view_detail():
    catalogo = get_biorreactores()
    bim = str(st.session_state.selected_bim) if st.session_state.selected_bim else None

    if not bim or bim not in set(catalogo["numero_bim"].astype("string")):
        st.info("Biorreactor no encontrado. Regresando al panel general…")
        go_home()
        st.stop()

    st.markdown(
        '<a class="btn-link" href="?page=home" target="_self">⬅️ Volver al Panel General</a>',
        unsafe_allow_html=True,
    )
    st.title(f"🧬 Detalle del biorreactor {bim}")

    sel = catalogo[catalogo["numero_bim"].astype("string") == bim].iloc[0]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Cliente:** {sel.get('cliente') or '—'}")
        st.markdown(f"**Microalga cultivada:** {sel.get('tipo_microalga') or '—'}")
        st.markdown(f"**Tipo de aireador:** {sel.get('tipo_aireador') or '—'}")
        st.markdown(f"**Altura del biorreactor:** {sel.get('altura_bim') or '—'} m")
    with c2:
        luz = sel.get('uso_luz_artificial')
        st.markdown(f"**Luz artificial:** {'Sí' if bool(luz) else 'No' if luz is not None else '—'}")
        st.markdown(f"**Fecha de instalación:** {sel.get('fecha_instalacion') or '—'}")
        st.markdown(f"**Coordenadas:** ({sel.get('latitud') or '—'}, {sel.get('longitud') or '—'})")

    st.divider()
    hoy = datetime.utcnow().date()
    d1 = datetime.combine(st.date_input("Desde", hoy - timedelta(days=30), key="d1_detail"), datetime.min.time())
    d2 = datetime.combine(st.date_input("Hasta", hoy, key="d2_detail"), datetime.max.time())

    T1, T2, T3 = st.tabs(["Registros", "Diagnósticos", "Eventos del biorreactor"])

    # ======================================================
    # TAB 1 — REGISTROS
    # ======================================================
    with T1:
        df_r = get_registros(bim, d1, d2)

        st.metric("Total de registros", len(df_r))

        if df_r.empty:
            st.info("Sin registros en el rango indicado.")
        else:
            # Quitar índice visual
            df_r = df_r.reset_index(drop=True)

            st.dataframe(df_r, use_container_width=True)

            st.download_button(
                "Descargar CSV",
                df_r.to_csv(index=False).encode("utf-8"),
                file_name=f"registros_BIM{bim}.csv",
            )

    # ======================================================
    # TAB 2 — DIAGNÓSTICOS
    # ======================================================
    with T2:
        df_d = get_diagnosticos(bim, d1, d2)

        st.metric("Total de diagnósticos", len(df_d))

        if df_d.empty:
            st.info("Sin diagnósticos en el rango indicado.")
        else:
            df_d = df_d.reset_index(drop=True)

            st.dataframe(df_d, use_container_width=True)

            st.download_button(
                "Descargar CSV",
                df_d.to_csv(index=False).encode("utf-8"),
                file_name=f"diagnosticos_BIM{bim}.csv",
            )

    # ======================================================
    # TAB 3 — EVENTOS
    # ======================================================
    with T3:
        df_e = get_eventos(bim, d1, d2)

        st.metric("Total de eventos", len(df_e))

        if df_e.empty:
            st.info("Sin eventos registrados en este rango.")
        else:
            # Quitar índice visual
            df_e = df_e.reset_index(drop=True)

            # Quitar ID y número de BIM
            df_e_visible = df_e.drop(columns=["id", "numero_bim"], errors="ignore")

            # -------------------------
            # RESUMEN — Último evento por tipo
            # -------------------------
            df_resumen = (
                df_e.sort_values(["fecha", "id"])
                    .drop_duplicates(subset=["nombre_evento"], keep="last")
                    .sort_values(["fecha", "id"], ascending=[False, False])
                    .reset_index(drop=True)
            )
            df_resumen_visible = df_resumen.drop(columns=["id", "numero_bim"], errors="ignore")

            st.subheader("🧾 Último evento registrado por tipo")
            st.dataframe(df_resumen_visible, use_container_width=True)

            # -------------------------
            # HISTORIAL COMPLETO
            # -------------------------
            st.subheader("📚 Historial completo")
            st.dataframe(df_e_visible, use_container_width=True)

            st.download_button(
                "Descargar historial completo (CSV)",
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

st.caption("© Technolab — Sistema de Gestión y Monitoreo de biorreactores.")
