"""
App: Dashboard BIM (Bio‑Intelligent Modules) por Agricultor y Nº de BIM
Stack: Streamlit + MySQL (registros, diagnosticos, clientes, comentarios) + MongoDB (imagenes/telemetría cruda opcional)
Autor: Technolab / Diego

INSTRUCCIONES RÁPIDAS
1) Prepara entorno
   pip install streamlit sqlalchemy pymysql pandas numpy python-dotenv pymongo pydeck folium streamlit-folium plotly

2) Crea archivo .streamlit/secrets.toml con credenciales (o usa variables de entorno)
   [mysql]
   host = "localhost"
   port = 3306
   user = "root"
   password = "tu_password"
   db = "technolab"

   [mongo]
   uri = "mongodb+srv://usuario:pass@cluster.mongodb.net"
   database = "technolab"
   collection = "imagenes"

3) Ejecuta
   streamlit run app_bim_dashboard.py

NOTAS DE DISEÑO
- El dashboard filtra por Agricultor (cliente) y Nº de BIM. 
- Mapa: muestra BIMs con lat/lon; clic desde listado para navegar.
- KPIs: pH, Temp, O2, Lux, Turbidez (si están disponibles) + estado último dato.
- Series: últimos 14/30/90 días con downsampling.
- Eventos: Diagnósticos y Comentarios relacionados.
- Alertas: reglas simples (ej. pH fuera de [6.5, 9.5], temp fuera de rango, etc.).
- API futura: puedes reemplazar funciones get_* por llamadas a tu API/Make.

ASUNCIONES DE ESQUEMA SQL (ajusta nombres si difieren)
- clientes(id, cliente, agricultor, telefono, direccion, lat, lon)
- bims(id, numero_bim, cliente_id, alias, lat, lon)
- registros(id, bim_id, fecha, ph, temperatura_c, oxigeno_mg_l, lux, turbidez_porcentaje)
- diagnosticos(id, bim_id, fecha, diagnostico, usuario_id)
- comentarios(id, bim_id, fecha, comentario, usuario_id)

Si algunas columnas difieren, ajusta los SELECT correspondientes en las funciones.
"""

from __future__ import annotations
import os
import math
import time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

import streamlit as st
from sqlalchemy import create_engine, text
from pymongo import MongoClient

# =============== Helpers de conexión ==================

def get_mysql_engine():
    if "mysql" in st.secrets:
        cfg = st.secrets["mysql"]
        user = cfg.get("user")
        pwd = cfg.get("password")
        host = cfg.get("host", "localhost")
        port = cfg.get("port", 3306)
        db = cfg.get("db")
    else:
        user = os.getenv("MYSQL_USER", "root")
        pwd = os.getenv("MYSQL_PASSWORD", "")
        host = os.getenv("MYSQL_HOST", "localhost")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        db = os.getenv("MYSQL_DB", "technolab")
    uri = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(uri, pool_pre_ping=True, pool_recycle=1800)


def get_mongo_collection():
    if "mongo" in st.secrets:
        cfg = st.secrets["mongo"]
        uri = cfg.get("uri")
        database = cfg.get("database", "technolab")
        collection = cfg.get("collection", "imagenes")
    else:
        uri = os.getenv("MONGO_URI")
        database = os.getenv("MONGO_DB", "technolab")
        collection = os.getenv("MONGO_COLLECTION", "imagenes")
    if not uri:
        return None
    client = MongoClient(uri)
    return client[database][collection]

# =============== Capa de datos ==================

@st.cache_data(ttl=300)
def load_clientes_y_bims():
    eng = get_mysql_engine()
    # Une clientes y bims; ajusta columnas si tus tablas usan otros nombres
    q = text(
        """
        SELECT 
            bims.id AS bim_id,
            bims.numero_bim AS numero_bim,
            COALESCE(bims.alias, CONCAT('BIM ', bims.numero_bim)) AS alias,
            clientes.id AS cliente_id,
            clientes.cliente AS agricultor,
            COALESCE(bims.lat, clientes.lat) AS lat,
            COALESCE(bims.lon, clientes.lon) AS lon
        FROM bims
        JOIN clientes ON clientes.id = bims.cliente_id
        ORDER BY clientes.cliente, bims.numero_bim
        """
    )
    df = pd.read_sql(q, eng)
    return df

@st.cache_data(ttl=300)
def load_latest_per_bim():
    eng = get_mysql_engine()
    q = text(
        """
        SELECT r1.* FROM registros r1
        JOIN (
            SELECT bim_id, MAX(fecha) AS max_fecha
            FROM registros
            GROUP BY bim_id
        ) r2 ON r1.bim_id = r2.bim_id AND r1.fecha = r2.max_fecha
        """
    )
    df = pd.read_sql(q, eng)
    return df

@st.cache_data(ttl=300)
def load_timeseries(bim_id: int, days: int = 30):
    eng = get_mysql_engine()
    q = text(
        """
        SELECT fecha, ph, temperatura_c, oxigeno_mg_l, lux, turbidez_porcentaje
        FROM registros
        WHERE bim_id = :bim_id AND fecha >= :desde
        ORDER BY fecha
        """
    )
    desde = datetime.utcnow() - timedelta(days=days)
    df = pd.read_sql(q, eng, params={"bim_id": bim_id, "desde": desde})
    # Limpieza básica
    if not df.empty:
        df = df.drop_duplicates(subset=["fecha"]).sort_values("fecha")
        # Downsample si hay muchos puntos
        if len(df) > 2000:
            df = df.iloc[:: max(1, len(df)//2000), :]
    return df

@st.cache_data(ttl=300)
def load_eventos(bim_id: int):
    eng = get_mysql_engine()
    diag = pd.read_sql(text("SELECT fecha, diagnostico AS texto, usuario_id, 'Diagnóstico' AS tipo FROM diagnosticos WHERE bim_id = :bim_id ORDER BY fecha DESC"), eng, params={"bim_id": bim_id})
    com = pd.read_sql(text("SELECT fecha, comentario AS texto, usuario_id, 'Comentario' AS tipo FROM comentarios WHERE bim_id = :bim_id ORDER BY fecha DESC"), eng, params={"bim_id": bim_id})
    out = pd.concat([diag, com], ignore_index=True).sort_values("fecha", ascending=False)
    return out

# =============== Reglas de alertas ==================

def compute_alerts(row: pd.Series) -> list[str]:
    alerts = []
    # Reglas base (ajusta a tu bioproceso)
    ph = row.get("ph")
    if pd.notna(ph) and (ph < 6.5 or ph > 9.5):
        alerts.append(f"pH fuera de rango: {ph:.2f}")
    t = row.get("temperatura_c")
    if pd.notna(t) and (t < 10 or t > 35):
        alerts.append(f"Temperatura atípica: {t:.1f} °C")
    o2 = row.get("oxigeno_mg_l")
    if pd.notna(o2) and (o2 < 3):
        alerts.append(f"O₂ bajo: {o2:.2f} mg/L")
    lux = row.get("lux")
    if pd.notna(lux) and lux < 200:
        alerts.append(f"Lux bajo: {lux:.0f}")
    turb = row.get("turbidez_porcentaje")
    if pd.notna(turb) and (turb < 5 or turb > 95):
        alerts.append(f"Turbidez anómala: {turb:.0f} %")
    return alerts

# =============== UI ==================

st.set_page_config(page_title="Dashboard BIM", page_icon="🧪", layout="wide")
st.title("🧪 Dashboard de BIM por Agricultor y Nº de BIM")

with st.sidebar:
    st.header("Filtros")
    df_cb = load_clientes_y_bims()
    if df_cb.empty:
        st.error("No se encontraron clientes/BIMs. Revisa la conexión y las tablas.")
        st.stop()
    agricultores = sorted(df_cb["agricultor"].unique())
    agricultor = st.selectbox("Agricultor", options=agricultores)
    df_bims = df_cb[df_cb["agricultor"] == agricultor]
    label_bims = df_bims.apply(lambda r: f"{int(r['numero_bim']) if pd.notna(r['numero_bim']) else r['bim_id']} · {r['alias']}", axis=1)
    idx_default = 0
    sel = st.selectbox("BIM", options=label_bims, index=idx_default)
    bim_id = int(df_bims.iloc[label_bims.tolist().index(sel)]["bim_id"]) if len(df_bims)>0 else None
    rango_dias = st.slider("Rango de días", 7, 180, 30)

# Panel superior: mapa + estado general
col_mapa, col_estado = st.columns([1.2, 1])
with col_mapa:
    st.subheader("Mapa de BIMs del agricultor")
    df_map = df_bims[["lat", "lon", "alias", "numero_bim", "bim_id"]].dropna(subset=["lat", "lon"])
    if df_map.empty:
        st.info("Este agricultor no tiene coordenadas registradas para sus BIMs. Agrega lat/lon en la tabla bims o clientes.")
    else:
        # Usa pydeck para un mapa más rico
        try:
            import pydeck as pdk
            layer = pdk.Layer(
                "ScatterplotLayer",
                data=df_map,
                get_position='[lon, lat]',
                get_radius=20,
                pickable=True,
                auto_highlight=True,
            )
            view_state = pdk.ViewState(
                latitude=float(df_map["lat"].mean()),
                longitude=float(df_map["lon"].mean()),
                zoom=10
            )
            st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "{alias}\nBIM {numero_bim}"}))
        except Exception as e:
            st.map(df_map.rename(columns={"lat": "latitude", "lon": "longitude"}))

with col_estado:
    st.subheader("Estado último muestreo (todos los BIMs del agricultor)")
    df_latest = load_latest_per_bim()
    df_latest = df_latest.merge(df_bims[["bim_id", "alias", "numero_bim"]], on="bim_id", how="inner")
    if df_latest.empty:
        st.info("Sin registros recientes para este agricultor.")
    else:
        # KPIs agregados
        def _fmt_avg(col):
            if col in df_latest and df_latest[col].notna().any():
                return float(df_latest[col].mean())
            return None
        kpi_ph = _fmt_avg("ph")
        kpi_t = _fmt_avg("temperatura_c")
        kpi_o2 = _fmt_avg("oxigeno_mg_l")
        kpi_lux = _fmt_avg("lux")
        kpi_turb = _fmt_avg("turbidez_porcentaje")
        c1, c2, c3 = st.columns(3)
        c4, c5 = st.columns(2)
        c1.metric("Prom. pH", f"{kpi_ph:.2f}" if kpi_ph is not None else "–")
        c2.metric("Prom. Temp (°C)", f"{kpi_t:.1f}" if kpi_t is not None else "–")
        c3.metric("Prom. O₂ (mg/L)", f"{kpi_o2:.2f}" if kpi_o2 is not None else "–")
        c4.metric("Prom. Lux", f"{kpi_lux:.0f}" if kpi_lux is not None else "–")
        c5.metric("Prom. Turbidez (%)", f"{kpi_turb:.0f}" if kpi_turb is not None else "–")

# Tabs de detalle del BIM seleccionado
st.markdown("---")
st.subheader(f"Detalle BIM seleccionado")

if bim_id is None:
    st.stop()

# Sidebar de navegación rápida entre BIMs del mismo agricultor
st.caption(f"Agricultor: {agricultor} | BIM ID: {bim_id}")

T1, T2, T3, T4 = st.tabs(["Visión general", "Series de tiempo", "Eventos", "Imágenes (Mongo)"])

with T1:
    st.markdown("### Último registro")
    df_last = load_latest_per_bim()
    row = df_last[df_last["bim_id"] == bim_id]
    if row.empty:
        st.info("Este BIM aún no tiene registros.")
    else:
        r = row.iloc[0]
        colA, colB, colC = st.columns(3)
        colD, colE = st.columns(2)
        colA.metric("pH", f"{r['ph']:.2f}" if pd.notna(r['ph']) else "–")
        colB.metric("Temp (°C)", f"{r['temperatura_c']:.1f}" if pd.notna(r['temperatura_c']) else "–")
        colC.metric("O₂ (mg/L)", f"{r['oxigeno_mg_l']:.2f}" if pd.notna(r['oxigeno_mg_l']) else "–")
        colD.metric("Lux", f"{r['lux']:.0f}" if pd.notna(r['lux']) else "–")
        colE.metric("Turbidez (%)", f"{r['turbidez_porcentaje']:.0f}" if pd.notna(r['turbidez_porcentaje']) else "–")
        st.caption(f"Fecha último dato: {r['fecha']}")

        alerts = compute_alerts(r)
        if alerts:
            st.error("\n".join([f"• {a}" for a in alerts]))
        else:
            st.success("Sin alertas con reglas actuales.")

with T2:
    st.markdown("### Series temporales")
    df_ts = load_timeseries(bim_id, days=int(rango_dias))
    if df_ts.empty:
        st.info("Sin datos en el rango seleccionado.")
    else:
        # Opciones de variables
        variables = [c for c in ["ph", "temperatura_c", "oxigeno_mg_l", "lux", "turbidez_porcentaje"] if c in df_ts.columns]
        sel_vars = st.multiselect("Variables a visualizar", variables, default=variables[:3] if variables else [])
        # Resample opcional
        agg = st.selectbox("Agregación", ["Ninguna", "5 min", "15 min", "1 h", "6 h", "1 d"], index=3)
        plot_df = df_ts.copy()
        plot_df["fecha"] = pd.to_datetime(plot_df["fecha"], errors="coerce")
        plot_df = plot_df.dropna(subset=["fecha"]).set_index("fecha")
        if agg != "Ninguna":
            rule = {
                "5 min": "5min",
                "15 min": "15min",
                "1 h": "1H",
                "6 h": "6H",
                "1 d": "1D",
            }[agg]
            plot_df = plot_df.resample(rule).mean().interpolate(limit=2)
        if sel_vars:
            import plotly.express as px
            for v in sel_vars:
                fig = px.line(plot_df.reset_index(), x="fecha", y=v, title=v)
                st.plotly_chart(fig, use_container_width=True)
        # Tabla cruda descargable
        st.download_button(
            "📥 Descargar CSV (rango y variables actuales)",
            data=plot_df.reset_index()[["fecha"] + sel_vars].to_csv(index=False).encode("utf-8"),
            file_name=f"bim_{bim_id}_timeseries.csv",
            mime="text/csv",
        )

with T3:
    st.markdown("### Diagnósticos y comentarios")
    df_ev = load_eventos(bim_id)
    if df_ev.empty:
        st.info("Sin eventos registrados.")
    else:
        st.dataframe(df_ev, use_container_width=True, hide_index=True)

with T4:
    st.markdown("### Imágenes vinculadas (MongoDB opcional)")
    col = get_mongo_collection()
    if col is None:
        st.info("MongoDB no configurado (opcional). Define mongo.uri en secrets.toml para habilitar.")
    else:
        # Supone documentos con {bim_id, fecha, filename, url|gridfs_id}
        try:
            cur = col.find({"bim_id": int(bim_id)}).sort("fecha", -1).limit(20)
            docs = list(cur)
            if not docs:
                st.info("Sin imágenes para este BIM.")
            else:
                for d in docs:
                    fecha = d.get("fecha")
                    nombre = d.get("filename", "imagen")
                    url = d.get("url")
                    st.write(f"**{nombre}** — {fecha}")
                    if url:
                        st.image(url, use_column_width=True)
                    else:
                        st.caption("Imagen sin URL directa (usa GridFS o genera un endpoint)")
        except Exception as e:
            st.warning(f"No fue posible leer imágenes: {e}")

# =============== SQL Sugerido (opcional) ==================
with st.expander("📄 SQL sugerido para vistas (copiar/pegar en tu MySQL)"):
    st.code(
        """
        -- Último registro por BIM
        CREATE OR REPLACE VIEW vw_bim_latest AS
        SELECT r1.* FROM registros r1
        JOIN (
            SELECT bim_id, MAX(fecha) AS max_fecha
            FROM registros
            GROUP BY bim_id
        ) r2 ON r1.bim_id = r2.bim_id AND r1.fecha = r2.max_fecha;

        -- Series diarias por BIM (promedios)
        CREATE OR REPLACE VIEW vw_bim_daily AS
        SELECT bim_id,
               DATE(fecha) AS dia,
               AVG(ph) AS ph,
               AVG(temperatura_c) AS temperatura_c,
               AVG(oxigeno_mg_l) AS oxigeno_mg_l,
               AVG(lux) AS lux,
               AVG(turbidez_porcentaje) AS turbidez_porcentaje,
               COUNT(*) AS n
        FROM registros
        GROUP BY bim_id, DATE(fecha);
        """,
        language="sql",
    )

st.caption("© Technolab — Este dashboard es un punto de partida: ajústalo a tu esquema real y a tus reglas de negocio.")


---

## 🚀 Infraestructura “todo con código” (local, servidor y despliegue)
A continuación te dejo **archivos listos** para trabajar 100% con código: Docker, docker‑compose, variables de entorno y estructura de repo. Copia/pega en tu proyecto.

### Árbol recomendado del repo
```
technolab-bim-dashboard/
├─ app_bim_dashboard.py            # (ya en este canvas)
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ .env                            # variables locales (no commitear)
├─ .streamlit/
│  └─ secrets.toml                 # credenciales (no commitear)
└─ README.md
```

### requirements.txt
```
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
```

### Dockerfile
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependencias del sistema (seguras y mínimas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos la app
COPY app_bim_dashboard.py /app/
COPY .streamlit /app/.streamlit

# Puerto por defecto de Streamlit
EXPOSE 8501

# Comando de arranque (puedes ajustar --server.address y --server.port)
CMD ["streamlit", "run", "app_bim_dashboard.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

### docker-compose.yml
> Opción A: Conectarte a **tus bases externas** (MySQL/Mongo ya existentes). Solo levanta el servicio `app`.
```yaml
services:
  app:
    build: .
    image: technolab/bim-dashboard:latest
    container_name: bim-dashboard
    ports:
      - "8501:8501"
    env_file: .env
    volumes:
      - ./.streamlit:/app/.streamlit:ro
    restart: unless-stopped
```

> Opción B (opcional para desarrollo): Levantar **MySQL y Mongo** locales dentro del compose. 
```yaml
services:
  app:
    build: .
    image: technolab/bim-dashboard:latest
    container_name: bim-dashboard
    ports: ["8501:8501"]
    env_file: .env
    volumes:
      - ./.streamlit:/app/.streamlit:ro
    depends_on: [mysql, mongo]
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    container_name: mysql-tech
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_PASSWORD}
      - MYSQL_DATABASE=${MYSQL_DB}
    ports: ["3306:3306"]
    volumes:
      - mysql_data:/var/lib/mysql
    restart: unless-stopped

  mongo:
    image: mongo:7
    container_name: mongo-tech
    ports: ["27017:27017"]
    volumes:
      - mongo_data:/data/db
    restart: unless-stopped

volumes:
  mysql_data:
  mongo_data:
```

### .env (ejemplo)
> Este archivo alimenta `docker-compose` y la app por variables de entorno (alternativa a `secrets.toml`).
```
# MySQL externo
MYSQL_HOST=mi.mysql.host
MYSQL_PORT=3306
MYSQL_USER=usuario
MYSQL_PASSWORD=supersecreto
MYSQL_DB=technolab

# Mongo externo (URI completo)
MONGO_URI=mongodb+srv://usuario:pass@cluster.mongodb.net
MONGO_DB=technolab
MONGO_COLLECTION=imagenes
```

> Si prefieres `secrets.toml`, mantén lo que ya dejé en el canvas y simplemente monta la carpeta `.streamlit` dentro del contenedor (como en el compose).

### Comandos útiles
```bash
# 1) Levantar en local con Docker
docker compose up --build -d

# 2) Ver logs
docker compose logs -f app

# 3) Actualizar imagen tras cambios
docker compose build app && docker compose up -d app

# 4) Parar
docker compose down
```

### Flujo de trabajo recomendado (100% código)
1. **Desarrollo local** en VS Code: edita `app_bim_dashboard.py` y prueba con `docker compose up`.
2. **Control de versiones** en Git (GitHub/GitLab/Bitbucket).
3. (Opcional) **CI/CD**: push a `main` dispara build y despliegue al servidor.
4. **Despliegue**: servidor con Docker (Ubuntu), expone puerto `8501` detrás de Nginx si necesitas HTTPS/domino.

### Despliegue rápido en servidor Ubuntu (root o sudo)
```bash
# Instalar Docker
curl -fsSL https://get.docker.com | sh
# Clonar repo y configurar .env + .streamlit/secrets.toml
git clone https://tu-repo.git && cd technolab-bim-dashboard
# Levantar
docker compose up --build -d
```

### ¿Y Make/Integromat?
- Lo seguimos usando para **ingesta** (ESP32 → Make → MySQL/Mongo). 
- El dashboard *solo lee* por SQL/Mongo. Si un día quieres exponer **API** propia (FastAPI), se reemplazan las funciones `load_*` por requests a tu API.

### (Opcional) Plantilla mínima FastAPI si quieres capa API
```python
# api/main.py
from fastapi import FastAPI
from sqlalchemy import create_engine, text
import os

app = FastAPI()
engine = create_engine(f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}@{os.getenv('MYSQL_HOST')}:{os.getenv('MYSQL_PORT')}/{os.getenv('MYSQL_DB')}?charset=utf8mb4", pool_pre_ping=True)

@app.get("/bims/{bim_id}/latest")
def latest(bim_id: int):
    q = text("""
        SELECT r1.* FROM registros r1
        JOIN (SELECT bim_id, MAX(fecha) AS max_fecha FROM registros GROUP BY bim_id) r2
          ON r1.bim_id=r2.bim_id AND r1.fecha=r2.max_fecha
        WHERE r1.bim_id=:bim_id
    """)
    with engine.connect() as c:
        row = c.execute(q, {"bim_id": bim_id}).mappings().first()
    return row or {}
```

`docker-compose.yml` podría agregar un servicio `api` y el `app` consultaría `http://api:8000` en lugar de conectarse directo a MySQL.

---
**Con esto: el “dónde” es Docker (local o servidor), el “software” es Streamlit + MySQL/Mongo, y *todo* se configura por código (.env, compose, Dockerfile).**


---

## 🌐 Despliegue 100% gratuito (web) — Hugging Face Spaces + PlanetScale (MySQL) + MongoDB Atlas

A continuación va una guía **paso a paso** para tener el dashboard público en la web **sin costo**, todo configurable por código.

### 0) Requisitos
- Cuenta gratuita en **Hugging Face** (Spaces).
- Cuenta gratuita en **PlanetScale** (MySQL compatible) — plan Hobby.
- Cuenta gratuita en **MongoDB Atlas** (cluster M0) para imágenes.
- **Git** y **Python 3.11** localmente (solo para pruebas/desarrollo opcional).

### 1) Base de datos MySQL en PlanetScale (gratis)
**Vía CLI (recomendado, infra como código):**
```bash
# Instala pscale CLI (Linux/macOS)
brew install planetscale/tap/pscale  # macOS con Homebrew
# o sigue docs para tu SO

# Autenticación
touch ~/.pscale.cnf && pscale auth login

# Crea base de datos
db_name=technolab
pscale database create $db_name --region aws-us-east-1

# Crea rama de desarrollo y conéctate (túnel local)
pscale branch create $db_name dev
pscale connect $db_name dev --port 3309 &

# Importa el esquema (usa el archivo de abajo schema_mysql.sql)
mysql --host 127.0.0.1 --port 3309 -u root < schema_mysql.sql

# (Opcional) Promociona a producción
pscale branch promote $db_name dev
```
> PlanetScale no soporta **foreign keys**; si tu esquema las usa, elimínalas o maneja integridad en app/consultas.

**Variables para la app (se obtienen en PlanetScale → Connect):**
```
MYSQL_HOST=aws.connect.psdb.cloud
MYSQL_PORT=3306
MYSQL_USER=xxxxxxxx
MYSQL_PASSWORD=xxxxxxxx
MYSQL_DB=technolab
```

### 2) MongoDB Atlas (gratis, M0)
- Crea un **Cluster M0**.
- Crea un usuario de base de datos y anota el **connection string (SRV)**.
- En **Network Access**, permite `0.0.0.0/0` (rápido para pruebas) o agrega IPs que necesites.

**Variables para la app:**
```
MONGO_URI=mongodb+srv://usuario:pass@cluster.mongodb.net
MONGO_DB=technolab
MONGO_COLLECTION=imagenes
```

### 3) Hugging Face Spaces — despliegue de la app Streamlit (gratis)
1. Crea un **Space** nuevo → **Type: Streamlit** → **Public**.
2. Sube estos archivos del repo: `app_bim_dashboard.py`, `requirements.txt` (los ya provistos), y opcionalmente `README.md`.
3. En **Settings → Secrets**, agrega las variables del paso 1 y 2 (no uses `secrets.toml` aquí; usa **Secrets** del Space):
   - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
   - `MONGO_URI`, `MONGO_DB`, `MONGO_COLLECTION`
4. Guarda y deja que el Space **build & deploy** automáticamente.

> HF Spaces mantiene el app público gratis. Si conectas a PlanetScale/Mongo, asegúrate de que permitan conexiones desde Internet.

### 4) (Opcional) Automatiza con Git (CI/CD)
- Crea un repo (GitHub/GitLab). 
- Conecta tu Space al repo (HF Spaces → **Sync with Git**). Cada `git push` redepliega.

### 5) Archivo de esquema (MySQL) — `schema_mysql.sql`
> Úsalo si quieres crear las tablas desde cero en PlanetScale (ajústalo si ya tienes tus tablas).
```sql
CREATE TABLE IF NOT EXISTS clientes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  cliente VARCHAR(190) NOT NULL,
  agricultor VARCHAR(190) NULL,
  telefono VARCHAR(64) NULL,
  direccion VARCHAR(255) NULL,
  lat DECIMAL(10,7) NULL,
  lon DECIMAL(10,7) NULL
) /* charset utf8mb4 */;

CREATE TABLE IF NOT EXISTS bims (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  numero_bim INT NOT NULL,
  cliente_id BIGINT NULL,
  alias VARCHAR(190) NULL,
  lat DECIMAL(10,7) NULL,
  lon DECIMAL(10,7) NULL,
  INDEX (cliente_id)
);

CREATE TABLE IF NOT EXISTS registros (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  bim_id BIGINT NOT NULL,
  fecha DATETIME(6) NOT NULL,
  ph DECIMAL(6,3) NULL,
  temperatura_c DECIMAL(6,3) NULL,
  oxigeno_mg_l DECIMAL(6,3) NULL,
  lux DECIMAL(12,3) NULL,
  turbidez_porcentaje DECIMAL(6,3) NULL,
  INDEX (bim_id),
  INDEX (fecha)
);

CREATE TABLE IF NOT EXISTS diagnosticos (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  bim_id BIGINT NOT NULL,
  fecha DATETIME(6) NOT NULL,
  diagnostico TEXT NULL,
  usuario_id VARCHAR(64) NULL,
  INDEX (bim_id),
  INDEX (fecha)
);

CREATE TABLE IF NOT EXISTS comentarios (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  bim_id BIGINT NOT NULL,
  fecha DATETIME(6) NOT NULL,
  comentario TEXT NULL,
  usuario_id VARCHAR(64) NULL,
  INDEX (bim_id),
  INDEX (fecha)
);
```

### 6) Variables en tiempo de ejecución (ya soportadas en la app)
La app detecta credenciales vía **variables de entorno** (HF Secrets) y **evita** exponer claves en el repo. No necesitas `.streamlit/secrets.toml` en Spaces.

### 7) Consideraciones de costo (todas GRATIS si públicas)
- **Hugging Face Spaces**: gratis para Spaces públicos.
- **PlanetScale Hobby**: gratis; límites de conexiones/almacenamiento razonables para POC.
- **MongoDB Atlas M0**: gratis; 512 MB aprox.

> Si prefieres **no usar MySQL** para mantenerlo simple y 100% gratis: puedes mover todo a **MongoDB Atlas M0** (colecciones `clientes`, `bims`, `registros`, etc.). La app ya trae capa de datos aislada; podemos conmutar a Mongo-only con pocos cambios.

---
**Resultado:** Dashboard web público, 100% gratuito, controlado por código (repo + variables de entorno), con datos en servicios administrados gratuitos.
