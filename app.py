# app.py — Technolab Data Center (Home + Detalle, KPIs correctos y catálogo robusto)
# -*- coding: utf-8 -*-
import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text, event
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
a.btn-link {
  display:inline-block; padding:10px 14px; border-radius:10px;
  background:#0f172a; color:#e2e8f0; text-decoration:none; margin:8px 0;
}
a.btn-link:hover { background:#1e293b; }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# 🔗 CONEXIÓN DIRECTA MYSQL (con sesión en utf8mb4_unicode_ci)
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
# 🔍 HELPERS SQL
# ==========================================================
def q(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return pd.read_sql(text(sql), ENGINE, params=params)
    except Exception as e:
        st.error(f"Error SQL: {e}")
        return pd.DataFrame()

def _norm_cliente(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()

def _norm_bim(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()

# ==========================================================
# 📦 CONSULTAS CON CACHE
# ==========================================================
@st.cache_data(ttl=180)
def get_clientes() -> pd.DataFrame:
    return q("SELECT id, usuario_id, usuario_nombre, cliente, BIMs_instalados FROM clientes")

@st.cache_data(ttl=180)
def get_biorreactores_raw() -> pd.DataFrame:
    return q("""
        SELECT id, cliente, numero_bim, latitud, longitud, altura_bim,
               tipo_microalga, uso_luz_artificial, tipo_aireador, `fecha_instalación` AS fecha_instalacion
        FROM biorreactores
        ORDER BY cliente, numero_bim
    """)

@st.cache_data(ttl=180)
def get_distinct_bims_from_registros() -> pd.DataFrame:
    return q("SELECT DISTINCT BIM AS numero_bim FROM registros WHERE BIM IS NOT NULL ORDER BY numero_bim")

@st.cache_data(ttl=180)
def get_distinct_bims_from_eventos() -> pd.DataFrame:
    return q("SELECT DISTINCT numero_bim FROM fechas_BIMs WHERE numero_bim IS NOT NULL ORDER BY numero_bim")

@st.cache_data(ttl=180)
def get_latest_usuario_por_bim() -> pd.DataFrame:
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
# 🧠 CATÁLOGO DE BIMs
# ==========================================================
@st.cache_data(ttl=180)
def construir_catalogo_bims() -> pd.DataFrame:
    clientes = get_clientes()
    br = get_biorreactores_raw()

    if not br.empty:
        br["cliente"] = _norm_cliente(br["cliente"])
        br["numero_bim"] = _norm_bim(br["numero_bim"])
        cat = br.copy()
    else:
        b1 = get_distinct_bims_from_registros()
        b2 = get_distinct_bims_from_eventos()
        bims = pd.concat([b1, b2], ignore_index=True).dropna().drop_duplicates()
        if bims.empty:
            return pd.DataFrame(columns=[
                "cliente","numero_bim","latitud","longitud","altura_bim",
                "tipo_microalga","uso_luz_artificial","tipo_aireador","fecha_instalacion"
            ])
        latest = get_latest_usuario_por_bim()
        cat = (bims.merge(latest, on="numero_bim", how="left")
                    .merge(clientes[["usuario_id","cliente"]], on="usuario_id", how="left"))
        cat["cliente"] = _norm_cliente(cat["cliente"].fillna("(Sin cliente)"))
        cat["numero_bim"] = _norm_bim(cat["numero_bim"])
        for c in ["tipo_microalga","tipo_aireador","uso_luz_artificial",
                  "altura_bim","latitud","longitud","fecha_instalacion"]:
            if c not in cat.columns:
                cat[c] = None
        cat = cat[["cliente","numero_bim","latitud","longitud","altura_bim",
                   "tipo_microalga","uso_luz_artificial","tipo_aireador","fecha_instalacion"]].copy()

    cat = cat.dropna(subset=["numero_bim"]).drop_duplicates(subset=["cliente","numero_bim"])
    return cat

# ==========================================================
# 📊 KPIs (sin UNION en SQL → sin colation mix)
# ==========================================================
@st.cache_data(ttl=180)
def get_kpis():
    # Clientes
    c = q("SELECT COUNT(*) AS c FROM clientes")
    total_clientes = int(c["c"].iloc[0]) if not c.empty else 0

    # 1) Cliente–BIM desde biorreactores (no hay joins de texto)
    df_bio = q("""
        SELECT TRIM(COALESCE(cliente,'')) AS cliente,
               TRIM(CAST(numero_bim AS CHAR)) AS bim
        FROM biorreactores
        WHERE numero_bim IS NOT NULL
    """)

    # 2) Cliente–BIM desde registros (join por usuario_id, no por cadenas)
    df_reg = q("""
        SELECT TRIM(COALESCE(c.cliente,'')) AS cliente,
               TRIM(CAST(r.BIM AS CHAR))    AS bim
        FROM registros r
        LEFT JOIN clientes c ON c.usuario_id = r.usuario_id
        WHERE r.BIM IS NOT NULL
    """)

    # 3) BIM desde fechas_BIMs, mapeando cliente por biorreactores en Python
    df_evt_bim = q("""
        SELECT TRIM(CAST(numero_bim AS CHAR)) AS bim
        FROM fechas_BIMs
        WHERE numero_bim IS NOT NULL
    """)
    map_bio = q("""
        SELECT TRIM(CAST(numero_bim AS CHAR)) AS bim,
               TRIM(COALESCE(cliente,''))     AS cliente
        FROM biorreactores
        WHERE numero_bim IS NOT NULL
    """)
    df_evt = df_evt_bim.merge(map_bio, on="bim", how="left")

    # Normalización en Pandas (evita comparaciones de colación en MySQL)
    def _clean(df):
        if df.empty:
            return pd.DataFrame(columns=["cliente","bim"])
        df["cliente"] = _norm_cliente(df["cliente"].fillna(""))
        df["bim"] = _norm_bim(df["bim"].fillna(""))
        df = df[(df["bim"].notna()) & (df["bim"] != "")]
        return df[["cliente","bim"]]

    df_all = pd.concat([_clean(df_bio), _clean(df_reg), _clean(df_evt)], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["cliente","bim"])
    total_bims = int(len(df_all))

    # Otros contadores
    d = q("SELECT COUNT(*) AS c FROM diagnosticos"); total_diag = int(d["c"].iloc[0]) if not d.empty else 0
    r = q("SELECT COUNT(*) AS c FROM registros");     total_regs = int(r["c"].iloc[0]) if not r.empty else 0
    e = q("SELECT COUNT(*) AS c FROM fechas_BIMs");   total_eventos = int(e["c"].iloc[0]) if not e.empty else 0
    return total_clientes, total_bims, total_diag, total_regs, total_eventos

# ==========================================================
# 🔗 ROUTER (Home / Detalle) con query params (API 1.39+)
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
# 🏠 HOME
# ==========================================================
def view_home():
    st.title("🧠 Technolab Data Center")

    tc, tb, td, tr, te = get_kpis()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("👥 Clientes", tc)
    k2.metric("🧩 BIMs", tb)
    k3.metric("💬 Diagnósticos", td)
    k4.metric("📄 Registros", tr)
    k5.metric("📅 Eventos", te)

    st.divider()

    catalogo = construir_catalogo_bims()
    if catalogo.empty:
        st.warning("No hay BIMs detectados aún (ni en biorreactores, ni en registros/eventos).")
        return

    st.sidebar.title("🎛️ Filtros")
    clientes_opts = ["Todos"] + sorted(catalogo["cliente"].dropna().unique().tolist())
    cliente_sel = st.sidebar.selectbox("👤 Cliente", clientes_opts)

    if cliente_sel != "Todos":
        cat_f = catalogo[catalogo["cliente"] == cliente_sel].copy()
    else:
        cat_f = catalogo.copy()

    st.subheader("🧫 Selección de BIMs")
    for cliente, grp in cat_f.groupby("cliente"):
        st.markdown(f"### 👤 {cliente}")
        cols = st.columns(3)
        for i, (_, r) in enumerate(grp.iterrows()):
            with cols[i % 3]:
                label = f"🧬 BIM {r['numero_bim']}\n\nMicroalga: {r.get('tipo_microalga') or '-'}"
                if st.button(label, key=f"btn_bim_{cliente}_{r['numero_bim']}"):
                    go_detail(str(r["numero_bim"]))

# ==========================================================
# 🔎 DETALLE
# ==========================================================
def view_detail():
    catalogo = construir_catalogo_bims()
    bim = str(st.session_state.selected_bim) if st.session_state.selected_bim is not None else None

    if not bim or bim not in set(catalogo["numero_bim"].astype("string")):
        st.info("BIM no encontrado. Volviendo al inicio…")
        go_home()
        st.stop()

    st.markdown('<a class="btn-link" href="?page=home" target="_self">⬅️ Volver</a>', unsafe_allow_html=True)
    st.title(f"🧬 BIM {bim}")

    sel = catalogo[catalogo["numero_bim"].astype("string") == bim].iloc[0]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Cliente:** {sel['cliente']}")
        st.markdown(f"**Microalga:** {sel.get('tipo_microalga') or '—'}")
        st.markdown(f"**Aireador:** {sel.get('tipo_aireador') or '—'}")
        st.markdown(f"**Altura:** {sel.get('altura_bim') or '—'} m")
    with c2:
        luz = sel.get('uso_luz_artificial')
        st.markdown(f"**Luz artificial:** {'Sí' if bool(luz) else 'No' if luz is not None else '—'}")
        st.markdown(f"**Fecha instalación:** {sel.get('fecha_instalacion') or '—'}")
        st.markdown(f"**Coordenadas:** ({sel.get('latitud') or '—'}, {sel.get('longitud') or '—'})")

    st.divider()

    hoy = datetime.utcnow().date()
    cold1, cold2 = st.columns(2)
    with cold1:
        d1 = st.date_input("Desde", hoy - timedelta(days=30), key="d1_detail")
    with cold2:
        d2 = st.date_input("Hasta", hoy, key="d2_detail")
    D1 = datetime.combine(d1, datetime.min.time())
    D2 = datetime.combine(d2, datetime.max.time())

    T1, T2, T3 = st.tabs(["📄 Registros", "💬 Diagnósticos", "📅 Eventos BIM"])

    with T1:
        df_r = get_registros(bim, D1, D2)
        st.metric("Total registros", len(df_r))
        if df_r.empty:
            st.info("Sin registros en este rango.")
        else:
            st.dataframe(df_r, use_container_width=True)
            st.download_button("📥 Descargar CSV", df_r.to_csv(index=False).encode("utf-8"),
                               file_name=f"registros_BIM{bim}.csv")

    with T2:
        df_d = get_diagnosticos(bim, D1, D2)
        st.metric("Total diagnósticos", len(df_d))
        if df_d.empty:
            st.info("Sin diagnósticos en este rango.")
        else:
            st.dataframe(df_d, use_container_width=True)
            st.download_button("📥 Descargar CSV", df_d.to_csv(index=False).encode("utf-8"),
                               file_name=f"diagnosticos_BIM{bim}.csv")

    with T3:
        df_e = get_eventos(bim, D1, D2)
        st.metric("Total eventos", len(df_e))
        if df_e.empty:
            st.info("Sin eventos para este BIM.")
        else:
            st.dataframe(df_e, use_container_width=True)
            st.download_button("📥 Descargar CSV", df_e.to_csv(index=False).encode("utf-8"),
                               file_name=f"eventos_BIM{bim}.csv")

    st.caption("Tip: puedes compartir esta vista; la URL ya incluye el BIM seleccionado.")

# ==========================================================
# 🚦 ROUTING
# ==========================================================
page = st.session_state.get("page", st.query_params.get("page", "home"))
if page == "detail":
    view_detail()
else:
    view_home()

st.caption("© Technolab — Dashboard unificado BIMs / Make / WhatsApp.")
