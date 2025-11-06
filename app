# app.py
import traceback
import platform
import sys
from typing import Callable, List, Tuple

import streamlit as st

st.set_page_config(page_title="BIM Dashboard - Diagnóstico rápido", layout="wide")

# ---------- Utilidad para encapsular secciones y mostrar traceback en la UI ----------
def run_section(title: str, fn: Callable[[], None]):
    with st.container():
        st.subheader(title)
        try:
            fn()
            st.success(f"✅ {title}: OK")
        except Exception as e:
            st.error(f"❌ {title}: {e}")
            st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            st.stop()  # evita que errores en una sección cascaden al resto

# ---------- Sección 1: Entorno y versiones ----------
def check_environment():
    import importlib
    required: List[Tuple[str, str]] = [
        ("streamlit", "1.39.0"),
        ("sqlalchemy", "2.0.35"),
        ("pymysql", "1.1.1"),
        ("pandas", "2.2.3"),
        ("numpy", "2.1.1"),
        ("pydeck", "0.9.1"),
        ("plotly", "5.24.1"),
        ("streamlit_folium", "0.22.0"),
        ("pymongo", "4.9.1"),
        ("python_dotenv", "1.0.1"),  # package es python-dotenv pero módulo es python_dotenv
    ]

    rows = []
    for mod, expected in required:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "desconocida")
            ok = "OK" if (ver.startswith(expected)) else f"⚠ espera {expected}"
        except ModuleNotFoundError:
            ver = "NO INSTALADO"
            ok = "❌ falta en requirements.txt"
        rows.append((mod, ver, ok))
    st.table(rows)
    st.caption(f"Python {platform.python_version()} | {sys.executable}")

# ---------- Sección 2: Cargar secrets ----------
def load_secrets():
    required_keys = ["MYSQL_URL", "MONGO_URL"]
    missing = [k for k in required_keys if k not in st.secrets]
    if missing:
        raise RuntimeError(
            f"Faltan secrets: {missing}. Crea .streamlit/secrets.toml con, por ejemplo:\n"
            'MYSQL_URL = "mysql+pymysql://user:pass@host:3306/db"\n'
            'MONGO_URL = "mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority"\n'
            'MAPBOX_API_KEY = "opcional"'
        )

# ---------- Sección 3: Probar MySQL ----------
def test_mysql():
    from sqlalchemy import create_engine, text
    mysql_url = st.secrets["MYSQL_URL"]
    engine = create_engine(mysql_url, pool_pre_ping=True, pool_recycle=1800)
    with engine.connect() as conn:
        st.write("Ping:", conn.execute(text("SELECT 1")).scalar())
        # Si quieres listar tablas (PlanetScale/MySQL):
        res = conn.execute(text("SHOW TABLES"))
        st.write("Tablas:", [r[0] for r in res.fetchall()[:20]])

# ---------- Sección 4: Probar MongoDB ----------
def test_mongo():
    from pymongo import MongoClient
    client = MongoClient(st.secrets["MONGO_URL"], serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    db_names = client.list_database_names()
    st.write("Bases Mongo (primeras):", db_names[:10])

# ---------- Sección 5: Demo UI segura (no depende de DB) ----------
def demo_ui():
    import pandas as pd
    import numpy as np
    st.markdown("Prueba de UI (gráfico y tabla) para confirmar que la app renderiza correctamente.")
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(end=pd.Timestamp.utcnow(), periods=24, freq="h"),
            "oxigeno": np.random.normal(8.5, 0.8, 24),
            "ph": np.random.normal(8.0, 0.2, 24),
            "temperatura": np.random.normal(22.0, 1.5, 24),
        }
    )
    st.line_chart(df.set_index("timestamp")[["oxigeno", "ph", "temperatura"]])
    st.dataframe(df.tail(10), use_container_width=True)

# ---------- Sidebar: controles rápidos ----------
with st.sidebar:
    st.header("Diagnóstico")
    run_env = st.checkbox("Entorno y versiones", value=True)
    run_secrets = st.checkbox("Cargar secrets", value=True)
    run_mysql = st.checkbox("Probar MySQL", value=True)
    run_mongo = st.checkbox("Probar MongoDB", value=True)
    run_demo = st.checkbox("Render UI demo", value=True)

    st.divider()
    st.caption("Sugerencia: ejecuta con logs verbosos en la terminal:")
    st.code("streamlit run app.py --logger.level=debug", language="bash")

st.title("BIM Dashboard — Diagnóstico rápido")

# ---------- Ejecución ordenada ----------
if run_env:
    run_section("Entorno y versiones", check_environment)

if run_secrets:
    run_section("Cargar secrets", load_secrets)

if run_mysql:
    run_section("Probar conexión MySQL", test_mysql)

if run_mongo:
    run_section("Probar conexión MongoDB", test_mongo)

if run_demo:
    run_section("Render UI demo", demo_ui)

st.success("Listo. Activa/desactiva bloques en la barra lateral para aislar el error.")
st.caption("Si una sección falla verás el traceback completo arriba. Copia ese error y te paso el fix exacto.")
