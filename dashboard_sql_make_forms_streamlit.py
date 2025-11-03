from __future__ import annotations
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

"""
Dashboard SQL (Make + Forms)
---------------------------------
Objetivo: Visualizar datos de las tablas que alimenta Make (formularios y flujos),
con filtros por cliente, fecha y tipo de registro. Minimalista, 100% compatible
con Streamlit Cloud (gratis) + MySQL (PlanetScale/MariaDB/MySQL)

Cómo configurar credenciales (elige uno):
- Streamlit Cloud → Settings → Secrets:
  MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB
- Local .env/.streamlit/secrets.toml (mismo nombre de claves)

Ajusta el mapeo de tablas y columnas en CONFIG_SCHEMA más abajo para calzar
con tu base actual (asistente de Make + formularios).
"""

# =============================
# Config general de la app
# =============================
st.set_page_config(page_title="Dashboard SQL: Make + Forms", page_icon="📊", layout="wide")

# =============================
# Conexión a MySQL
# =============================

def get_mysql_engine():
    if "mysql" in st.secrets:
        cfg = st.secrets["mysql"]
        host = cfg.get("host", "localhost")
        port = int(cfg.get("port", 3306))
        user = cfg.get("user")
        password = cfg.get("password")
        db = cfg.get("db")
    else:
        host = os.getenv("MYSQL_HOST", "localhost")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        user = os.getenv("MYSQL_USER", "root")
        password = os.getenv("MYSQL_PASSWORD", "")
        db = os.getenv("MYSQL_DB", "technolab")
    uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(uri, pool_pre_ping=True, pool_recycle=1800)

# =============================
# Mapeo de tablas/columnas (ADÁPTALO a tu esquema real)
# =============================
CONFIG_SCHEMA: Dict[str, Dict[str, str]] = {
    # Tabla de clientes/prospectos que llegan desde formularios o CRM
    "clientes": {
        "table": "clientes",           # nombre real de la tabla
        "id": "id",                    # PK
        "nombre": "cliente",           # nombre/razón social/cliente
        "telefono": "telefono",        # puede no existir
        "direccion": "direccion",      # puede no existir
        "creado": "created_at"         # puede no existir; si no lo tienes, deja string vacío ""
    },
    # Tabla de formularios enviados (desde Make)
    "formularios": {
        "table": "formularios",        # si no tienes esta tabla unificada, usa la que corresponda
        "id": "id",
        "cliente_id": "cliente_id",
        "tipo": "tipo_form",           # por ej: "contacto", "postventa", "soporte"
        "fecha": "fecha",
        "payload": "payload"           # JSON/texto con respuestas; si no existe, deja ""
    },
    # Tabla de diagnósticos/acciones del asistente
    "diagnosticos": {
        "table": "diagnosticos",
        "id": "id",
        "cliente_id": "cliente_id",
        "fecha": "fecha",
        "texto": "diagnostico",
        "usuario_id": "usuario_id"
    },
    # Tabla de comentarios/observaciones (vinculada a cliente)
    "comentarios": {
        "table": "comentarios",
        "id": "id",
        "cliente_id": "cliente_id",
        "fecha": "fecha",
        "texto": "comentario",
        "usuario_id": "usuario_id"
    },
    # (Opcional) registros genéricos (eventos, acciones, logs)
    "registros": {
        "table": "registros",
        "id": "id",
        "cliente_id": "cliente_id",    # si tu tabla registra por cliente
        "fecha": "fecha",
        "estado": "estado",            # opcional
        "valor": "valor"               # opcional
    }
}

# =============================
# Helpers de consulta
# =============================
@st.cache_data(ttl=300)
def df_clientes() -> pd.DataFrame:
    cfg = CONFIG_SCHEMA["clientes"]
    tbl = cfg["table"]
    cols = [c for c in [cfg.get("id"), cfg.get("nombre"), cfg.get("telefono"), cfg.get("direccion"), cfg.get("creado")] if c]
    q = text(f"SELECT {', '.join(cols)} FROM {tbl} ORDER BY {cfg.get('nombre')}")
    return pd.read_sql(q, get_mysql_engine())

@st.cache_data(ttl=300)
def df_formularios(cliente_id: int | None = None, tipo: str | None = None, desde: datetime | None = None, hasta: datetime | None = None) -> pd.DataFrame:
    cfg = CONFIG_SCHEMA["formularios"]
    tbl = cfg["table"]
    where = ["1=1"]
    params: Dict[str, Any] = {}
    if cliente_id is not None:
        where.append(f"{cfg['cliente_id']} = :cid")
        params["cid"] = cliente_id
    if tipo:
        where.append(f"{cfg['tipo']} = :tipo")
        params["tipo"] = tipo
    if desde:
        where.append(f"{cfg['fecha']} >= :desde")
        params["desde"] = desde
    if hasta:
        where.append(f"{cfg['fecha']} <= :hasta")
        params["hasta"] = hasta
    cols = [c for c in [cfg.get("id"), cfg.get("cliente_id"), cfg.get("tipo"), cfg.get("fecha"), cfg.get("payload")] if c]
    q = text(f"SELECT {', '.join(cols)} FROM {tbl} WHERE {' AND '.join(where)} ORDER BY {cfg['fecha']} DESC")
    return pd.read_sql(q, get_mysql_engine(), params=params)

@st.cache_data(ttl=300)
def df_eventos(nombre: str, cliente_id: int | None = None, desde: datetime | None = None, hasta: datetime | None = None) -> pd.DataFrame:
    cfg = CONFIG_SCHEMA[nombre]
    tbl = cfg["table"]
    where = ["1=1"]
    params: Dict[str, Any] = {}
    if cliente_id is not None and cfg.get("cliente_id"):
        where.append(f"{cfg['cliente_id']} = :cid")
        params["cid"] = cliente_id
    if desde:
        where.append(f"{cfg['fecha']} >= :desde")
        params["desde"] = desde
    if hasta:
        where.append(f"{cfg['fecha']} <= :hasta")
        params["hasta"] = hasta
    # columnas mínimas
    cols = [c for c in [cfg.get("id"), cfg.get("cliente_id"), cfg.get("fecha"), cfg.get("texto"), cfg.get("usuario_id"), cfg.get("estado"), cfg.get("valor")] if c]
    q = text(f"SELECT {', '.join(cols)} FROM {tbl} WHERE {' AND '.join(where)} ORDER BY {cfg.get('fecha', 'id')} DESC")
    return pd.read_sql(q, get_mysql_engine(), params=params)

# =============================
# UI – Sidebar: filtros globales
# =============================
st.title("📊 Dashboard SQL — Make + Forms")

with st.sidebar:
    st.header("Filtros")
    clientes = df_clientes()
    if clientes.empty:
        st.error("No hay clientes. Revisa la conexión y el mapeo de columnas en CONFIG_SCHEMA.")
        st.stop()
    opciones = ["(Todos)"] + [f"#{int(row[CONFIG_SCHEMA['clientes']['id']])} – {row[CONFIG_SCHEMA['clientes']['nombre']]}" for _, row in clientes.iterrows()]
    sel_cliente = st.selectbox("Cliente", opciones)
    cliente_id = None if sel_cliente == "(Todos)" else int(sel_cliente.split("–")[0].replace("#", "").strip())

    # Rango de fechas
    hoy = datetime.utcnow().date()
    desde = st.date_input("Desde", hoy - timedelta(days=30))
    hasta = st.date_input("Hasta", hoy)

    # Tipo de formulario (si existe)
    tipos = sorted([t for t in df_formularios().get(CONFIG_SCHEMA['formularios']['tipo'], pd.Series()).dropna().unique().tolist()])
    tipo_sel = st.selectbox("Tipo de formulario", ["(Todos)"] + tipos)
    tipo_form = None if tipo_sel == "(Todos)" else tipo_sel

# =============================
# Tabs principales
# =============================
T1, T2, T3, T4 = st.tabs(["Resumen", "Formularios", "Diagnósticos", "Comentarios"])

# ---------- Resumen ----------
with T1:
    col1, col2, col3 = st.columns(3)
    # Totales formularios en rango
    forms = df_formularios(cliente_id, tipo_form, datetime.combine(desde, datetime.min.time()), datetime.combine(hasta, datetime.max.time()))
    col1.metric("Formularios", len(forms))

    # Totales diagnósticos
    diags = df_eventos("diagnosticos", cliente_id, datetime.combine(desde, datetime.min.time()), datetime.combine(hasta, datetime.max.time()))
    col2.metric("Diagnósticos", len(diags))

    # Totales comentarios
    comms = df_eventos("comentarios", cliente_id, datetime.combine(desde, datetime.min.time()), datetime.combine(hasta, datetime.max.time()))
    col3.metric("Comentarios", len(comms))

    st.markdown("---")
    st.subheader("Últimos eventos")
    cA, cB = st.columns(2)
    with cA:
        st.caption("Diagnósticos recientes")
        st.dataframe(diags.head(20), use_container_width=True)
    with cB:
        st.caption("Comentarios recientes")
        st.dataframe(comms.head(20), use_container_width=True)

# ---------- Formularios ----------
with T2:
    st.subheader("Formularios")
    if forms.empty:
        st.info("Sin formularios en el rango/cliente seleccionado.")
    else:
        # Vista tabla
        st.dataframe(forms, use_container_width=True)
        # Detalle JSON/payload si existe
        cfgf = CONFIG_SCHEMA["formularios"]
        if cfgf.get("payload") and cfgf["payload"] in forms.columns:
            st.markdown("### Detalle de un envío")
            idx = st.number_input("Fila (índice)", min_value=0, max_value=len(forms)-1, value=0, step=1)
            registro = forms.iloc[int(idx)].to_dict()
            st.json(registro.get(cfgf["payload"], {}))
        st.download_button("📥 CSV", data=forms.to_csv(index=False).encode("utf-8"), file_name="formularios.csv")

# ---------- Diagnósticos ----------
with T3:
    st.subheader("Diagnósticos")
    if diags.empty:
        st.info("Sin diagnósticos en el rango/cliente seleccionado.")
    else:
        st.dataframe(diags, use_container_width=True)
        st.download_button("📥 CSV", data=diags.to_csv(index=False).encode("utf-8"), file_name="diagnosticos.csv")

# ---------- Comentarios ----------
with T4:
    st.subheader("Comentarios")
    if comms.empty:
        st.info("Sin comentarios en el rango/cliente seleccionado.")
    else:
        st.dataframe(comms, use_container_width=True)
        st.download_button("📥 CSV", data=comms.to_csv(index=False).encode("utf-8"), file_name="comentarios.csv")

st.caption("© Dashboard SQL (Make + Forms) — Ajusta CONFIG_SCHEMA para calzar con tus tablas reales.")
