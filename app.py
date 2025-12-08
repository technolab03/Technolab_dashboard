import os,re
from math import radians,sin,cos,asin,sqrt
import pandas as pd,requests,streamlit as st
from sqlalchemy import create_engine,text,event
from datetime import datetime,timedelta

st.set_page_config(page_title="Technolab Data Center",page_icon="🧪",layout="wide")
ORIGIN_LAT=-29.947648;ORIGIN_LON=-71.248671

st.markdown("""
<style>
#MainMenu,header,footer{visibility:hidden;}
div[data-testid="stMetricValue"]{font-size:28px;font-weight:bold;color:#00B4D8;}
div.stButton>button{border-radius:16px;background:#0077B6;color:#fff;font-size:18px;height:110px;width:100%;margin:8px 0;transition:.2s;}
div.stButton>button:hover{background:#0096C7;transform:scale(1.02);}
a.btn-link{display:inline-block;padding:10px 14px;border-radius:10px;background:#0f172a;color:#e2e8f0;text-decoration:none;margin:8px 0;}
a.btn-link:hover{background:#1e293b;}
</style>
""",unsafe_allow_html=True)

def build_engine():
    if "mysql" in st.secrets:
        user=st.secrets["mysql"]["user"];password=st.secrets["mysql"]["password"]
        host=st.secrets["mysql"]["host"];port=st.secrets["mysql"].get("port",3306)
        database=st.secrets["mysql"]["database"]
    else:
        user=os.getenv("MYSQL_USER","makeuser")
        password=os.getenv("MYSQL_PASSWORD","NUEVA_PASSWORD_SEGURA")
        host=os.getenv("MYSQL_HOST","143.198.144.39")
        port=int(os.getenv("MYSQL_PORT","3306"))
        database=os.getenv("MYSQL_DATABASE","technolab")
    url=f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    engine=create_engine(url,pool_pre_ping=True,pool_recycle=1800,connect_args={"charset":"utf8mb4"})
    @event.listens_for(engine,"connect")
    def _set(dbapi_conn,_):
        cur=dbapi_conn.cursor()
        cur.execute("SET NAMES utf8mb4;");cur.execute("SET collation_connection='utf8mb4_unicode_ci';")
        cur.close()
    return engine
ENGINE=build_engine()

def q(sql,params=None):
    try:return pd.read_sql(text(sql),ENGINE,params=params)
    except Exception as e:st.error(f"Error SQL: {e}");return pd.DataFrame()

_coord_pattern=re.compile(r"[-+]?\d+(?:[.,]\d+)?")
def _to_float_coord(v):
    if pd.isna(v):return None
    m=_coord_pattern.search(str(v)); 
    return float(m.group(0).replace(",",".")) if m else None

def haversine_km(a,b,c,d):
    R=6371; a1,r1=radians(a),radians(b); a2,r2=radians(c),radians(d)
    da=a2-a1;dr=r2-r1
    return 2*R*asin(sqrt(sin(da/2)**2+cos(a1)*cos(a2)*sin(dr/2)**2))

def build_route_nearest_neighbor(df):
    if df.empty or len(df)==1:return df.reset_index(drop=True)
    rem=df.copy().reset_index(drop=True);route=[]
    idx=0;route.append(rem.loc[idx]);rem=rem.drop(index=idx).reset_index(drop=True)
    while not rem.empty:
        last=route[-1]
        d=rem.apply(lambda r:haversine_km(last["latitud"],last["longitud"],r["latitud"],r["longitud"]),axis=1)
        m=d.idxmin();route.append(rem.loc[m]);rem=rem.drop(index=m).reset_index(drop=True)
    return pd.DataFrame(route).reset_index(drop=True)

def get_driving_route_ors(coords):
    if "ors" not in st.secrets:return None,None,None
    k=st.secrets["ors"]["api_key"];url="https://api.openrouteservice.org/v2/directions/driving-car/geojson"
    try:
        r=requests.post(url,json={"coordinates":coords},headers={"Authorization":k},timeout=20)
        r.raise_for_status();d=r.json()
        s=d["features"][0]["properties"]["summary"]
        return s["distance"]/1000,s["duration"]/3600,d["features"][0]["geometry"]["coordinates"]
    except:return None,None,None

@st.cache_data(ttl=180)
def get_clientes():return q("SELECT id,usuario_id,usuario_nombre,cliente,BIMs_instalados FROM clientes")

@st.cache_data(ttl=1)
def get_biorreactores():
    return q("""SELECT id,cliente,
        TRIM(CAST(numero_bim AS CHAR CHARACTER SET utf8mb4)) AS numero_bim,
        latitud,longitud,altura_bim,tipo_microalga,uso_luz_artificial,
        tipo_aireador,`fecha_instalación` AS fecha_instalacion
        FROM biorreactores ORDER BY cliente,numero_bim""")

@st.cache_data(ttl=1)
def get_map_df(cli=None):
    df=get_biorreactores().copy()
    if cli and cli!="Todos":df=df[df["cliente"].fillna("").str.strip()==cli]
    df["latitud"]=df["latitud"].map(_to_float_coord)
    df["longitud"]=df["longitud"].map(_to_float_coord)
    df=df.dropna(subset=["latitud","longitud"])
    tr={"url":"https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f69c.png","width":72,"height":72,"anchorY":72}
    mr={"url":"https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f3e0.png","width":72,"height":72,"anchorY":72}
    if not df.empty:
        df["label"]="BIM "+df["numero_bim"].astype("string")
        df["icon_data"]=[tr]*len(df)
    mat={"cliente":"Casa Matriz Technolab","numero_bim":"Matriz","latitud":ORIGIN_LAT,"longitud":ORIGIN_LON,
         "tipo_microalga":None,"label":"Matriz","icon_data":mr}
    df=pd.concat([df,pd.DataFrame([mat])],ignore_index=True)
    return df

@st.cache_data(ttl=180)
def get_eventos(b,d1,d2):
    return q("""SELECT id,numero_bim,nombre_evento,fecha,comentarios
                FROM fechas_BIMs WHERE numero_bim=:b
                AND fecha BETWEEN :d1 AND :d2 ORDER BY fecha DESC,id DESC""",
             {"b":str(b),"d1":d1,"d2":d2})

@st.cache_data(ttl=180)
def get_diagnosticos(b,d1,d2):
    return q("""SELECT d.id,d.usuario_id,d.PreguntaCliente,d.respuestaGPT,d.fecha
                FROM diagnosticos d WHERE d.usuario_id IN
                (SELECT r.usuario_id FROM registros r WHERE r.BIM=:b)
                AND d.fecha BETWEEN :d1 AND :d2 ORDER BY fecha DESC,id DESC""",
             {"b":str(b),"d1":d1,"d2":d2})

@st.cache_data(ttl=180)
def get_registros(b,d1,d2):
    return q("""SELECT id,usuario_id,BIM,respuestaGPT,HEX,fecha
                FROM registros WHERE BIM=:b AND fecha BETWEEN :d1 AND :d2
                ORDER BY fecha DESC,id DESC""",
             {"b":str(b),"d1":d1,"d2":d2})

@st.cache_data(ttl=180)
def get_kpis():
    c=q("SELECT COUNT(*) c FROM clientes");r1=int(c["c"].iloc[0]) if not c.empty else 0
    s=q("SELECT SUM(COALESCE(BIMs_instalados,0)) s FROM clientes")
    s1=int(s["s"].iloc[0]) if not s.empty else 0
    bb=q("SELECT numero_bim FROM biorreactores");tb=bb["numero_bim"].nunique() if not bb.empty else 0
    d=q("SELECT COUNT(*) c FROM diagnosticos");di=int(d["c"].iloc[0]) if not d.empty else 0
    r=q("SELECT COUNT(*) c FROM registros");re=int(r["c"].iloc[0]) if not r.empty else 0
    e=q("SELECT COUNT(*) c FROM fechas_BIMs");ev=int(e["c"].iloc[0]) if not e.empty else 0
    return r1,tb,di,re,ev

def go_home():st.session_state.page="home";st.session_state.selected_bim=None;st.query_params.clear();st.query_params["page"]="home"
def go_detail(b):st.session_state.page="detail";st.session_state.selected_bim=str(b);st.query_params.clear();st.query_params.update({"page":"detail","b":str(b)})
def go_map():st.session_state.page="map";st.query_params.clear();st.query_params["page"]="map"

if "page" not in st.session_state:st.session_state.page=st.query_params.get("page","home")
if "selected_bim" not in st.session_state:st.session_state.selected_bim=st.query_params.get("b",None)

def view_home():
    st.title("🧠 Technolab Data Center — Panel General")
    tc,tb,td,tr,te=get_kpis()
    k1,k2,k3,k4,k5=st.columns(5)
    k1.metric("Clientes activos",tc);k2.metric("Biorreactores operativos",tb)
    k3.metric("Diagnósticos registrados",td);k4.metric("Registros de datos",tr);k5.metric("Eventos asociados",te)
    st.sidebar.title("Filtros")
    df=get_biorreactores();df["cliente"]=df["cliente"].astype("string")
    opts=["Todos"]+sorted([x for x in df["cliente"].dropna().str.strip().unique() if x])
    cs=st.sidebar.selectbox("Cliente",opts)
    if st.sidebar.button("🌍 Abrir mapa"):go_map()
    st.divider();st.subheader("📋 Listado de biorreactores")
    if cs!="Todos":df=df[df["cliente"].fillna("").str.strip()==cs]
    if df.empty:st.warning("No se encontraron biorreactores.")
    else:
        for cli,g in df.groupby(df["cliente"].fillna("").str.strip()):
            st.markdown(f"### 👤 {cli}")
            cols=st.columns(3)
            for i,(_,r) in enumerate(g.iterrows()):
                with cols[i%3]:
                    if st.button(f"🌿 BIM {r['numero_bim']}",key=f"{cli}_{r['numero_bim']}"):
                        go_detail(str(r["numero_bim"]))

def view_map():
    st.markdown('<a class="btn-link" href="?page=home">⬅️ Volver</a>',unsafe_allow_html=True)
    st.title("🌍 Mapa de biorreactores")
    df=get_map_df()
    if df.empty:st.info("No hay coordenadas.");return
    import pydeck as pdk
    df["cliente"]=df["cliente"].astype("string");df["numero_bim"]=df["numero_bim"].astype("string")
    bims=sorted(df["numero_bim"].unique());focus=st.selectbox("Centrar en:",bims)
    r=df[df["numero_bim"]==focus].iloc[0];lat0,lon0=r["latitud"],r["longitud"]
    view=pdk.ViewState(latitude=lat0,longitude=lon0,zoom=12)
    layer_icon=pdk.Layer("IconLayer",data=df,get_icon="icon_data",get_position="[longitud,latitud]",size_scale=15,get_size=2,pickable=True)
    df["title"]=df["label"].astype(str)
    layer_label=pdk.Layer("TextLayer",data=df,get_position="[longitud,latitud]",get_text="title",get_size=14,get_color=[255,255,255],get_text_anchor="start",get_alignment_baseline="center",get_pixel_offset=[18,0])
    st.pydeck_chart(pdk.Deck(layers=[layer_icon,layer_label],initial_view_state=view),use_container_width=True)

def view_detail():
    df=get_biorreactores();b=str(st.session_state.selected_bim)
    if b not in df["numero_bim"].astype("string").values:go_home();return
    st.markdown('<a class="btn-link" href="?page=home">⬅️ Volver</a>',unsafe_allow_html=True)
    st.title(f"🧬 Detalle del biorreactor {b}")
    sel=df[df["numero_bim"]==b].iloc[0]
    c1,c2=st.columns(2)
    with c1:
        st.markdown(f"**Cliente:** {sel['cliente']}");st.markdown(f"**Microalga:** {sel['tipo_microalga']}")
        st.markdown(f"**Aireador:** {sel['tipo_aireador']}");st.markdown(f"**Altura:** {sel['altura_bim']} m")
    with c2:
        luz=sel['uso_luz_artificial'];st.markdown(f"**Luz artificial:** {'Sí' if luz else 'No'}")
        st.markdown(f"**Instalación:** {sel['fecha_instalacion']}")
        st.markdown(f"**Coords:** ({sel['latitud']},{sel['longitud']})")
    st.divider()
    hoy=datetime.utcnow().date()
    d1=datetime.combine(st.date_input("Desde",hoy-timedelta(days=30)),datetime.min.time())
    d2=datetime.combine(st.date_input("Hasta",hoy),datetime.max.time())
    T1,T2,T3=st.tabs(["Registros","Diagnósticos","Eventos"])

    with T1:
        r=get_registros(b,d1,d2).reset_index(drop=True)
        st.metric("Total registros",len(r))
        st.dataframe(r,use_container_width=True)
        st.download_button("Descargar CSV",r.to_csv(index=False).encode("utf-8"))

    with T2:
        d=get_diagnosticos(b,d1,d2).reset_index(drop=True)
        st.metric("Total diagnósticos",len(d))
        st.dataframe(d,use_container_width=True)
        st.download_button("Descargar CSV",d.to_csv(index=False).encode("utf-8"))

    with T3:
        e=get_eventos(b,d1,d2).reset_index(drop=True)
        st.metric("Total eventos",len(e))
        if e.empty:st.info("Sin eventos.");return
        resumen=(e.sort_values(["fecha","id"]).drop_duplicates("nombre_evento",keep="last")
                .sort_values(["fecha","id"],ascending=False).reset_index(drop=True))
        rv=resumen.drop(columns=["id","numero_bim"],errors="ignore")
        ev=e.drop(columns=["id","numero_bim"],errors="ignore")
        st.subheader("🧾 Último evento por tipo");st.dataframe(rv,use_container_width=True)
        st.subheader("📚 Historial completo");st.dataframe(ev,use_container_width=True)
        st.download_button("Descargar CSV",e.to_csv(index=False).encode("utf-8"))

page=st.session_state.get("page","home")
if page=="detail":view_detail()
elif page=="map":view_map()
else:view_home()
st.caption("© Technolab — Sistema de Gestión y Monitoreo de biorreactores.")
