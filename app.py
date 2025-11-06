# app.py - Lanzador seguro para Streamlit Cloud
# Diego | Technolab Dashboard

import runpy
from pathlib import Path
import streamlit as st
from datetime import datetime, timezone

# --------------------------------------------------------
# Posibles ubicaciones del archivo principal de tu app real
# --------------------------------------------------------
CANDIDATOS = [
    "src/app.py",
    "dashboard/app.py",
    "technolab_dashboard/app_main.py",
    "technolab_dashboard/main.py",
    "technolab_dashboard/app/__init__.py",
]

def intentar_ejecutar_objetivo():
    """Busca y ejecuta la app real si existe en una de las rutas conocidas."""
    for rel in CANDIDATOS:
        p = Path(rel)
        if p.exists():
            st.write(f"🔍 Cargando aplicación desde: `{rel}`")
            runpy.run_path(str(p), run_name="__main__")
            return True
    return False


def app_local_en_raiz():
    """App de respaldo si no se encuentra otra ruta."""
    st.set_page_config(page_title="Technolab Dashboard", layout="wide")

    st.title("Technolab Dashboard")
    st.caption("Cargando desde `app.py` en la raíz del repositorio.")

    hoy = datetime.now(timezone.utc).date()
    st.write("📅 Fecha (UTC):", hoy)

    st.markdown("""
    ### ✅ La aplicación se está ejecutando correctamente.
    Si tu app principal está en otra carpeta, muévela o añade su ruta a la lista **CANDIDATOS**.
    
    ---
    **Ejemplo de estructura recomendada**
    ```
    technolab_dashboard/
    ├── app.py
    ├── .streamlit/
    │   └── secrets.toml
    ├── requirements.txt
    ├── src/
    │   └── app.py  ← tu código real
    └── data/
    ```
    """)

    st.success("Todo listo. Streamlit detectó correctamente el archivo principal (`app.py`).")


# --------------------------------------------------------
# Ejecución principal
# --------------------------------------------------------
if __name__ == "__main__":
    ejecutado = intentar_ejecutar_objetivo()
    if not ejecutado:
        app_local_en_raiz()
