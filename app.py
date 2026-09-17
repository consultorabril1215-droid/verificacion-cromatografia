"""
Aplicación de Verificación de Métodos Analíticos + Estimación de Incertidumbre
Conforme a:
  - Guía Eurachem "La Adecuación al Uso de los Métodos Analíticos" (2ª ed., 2016)
  - Guía EURACHEM/CITAC CG4 "Cuantificación de la Incertidumbre en Medidas
    Analíticas" (QUAM:2012.P1-ES)

Genérica para cualquier técnica analítica: los criterios de aceptación y la
estructura de niveles/réplicas se configuran una sola vez al inicio.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import (
    AcceptanceCriteria, MethodInfo, DesignStructure, Compound,
    CalibrationCurve, ReplicateLevel, CertificateRecord, CertificateAnalyte,
    ReferenceMaterialCert, VolumetricStep, StandardPreparation, VerificationProject,
    DilutionLevel, VolumetricEquipmentRecord,
)
from core import stats as S
from core import uncertainty as U

st.set_page_config(page_title="Verificación de Métodos + Incertidumbre", layout="wide")

# =============================================================================
# Control de acceso a la descarga (solo administrador)
#
# Usa el mismo mecanismo de acceso de Streamlit Community Cloud (Settings >
# Sharing > "Only specific people can view this app"): cuando está activo,
# la plataforma identifica al usuario que inició sesión con Google y lo
# expone aquí en `st.user`. No requiere crear ningún proyecto aparte en
# Google Cloud Console. En local (sin ese login), no hay `st.user` con
# email, así que se trata como "no administrador" — pero se puede probar
# forzando ADMIN_EMAILS a tu correo en local si lo necesitas.
# =============================================================================
try:
    ADMIN_EMAILS = list(st.secrets.get("admin_emails", ["consultorabril1215@gmail.com"]))
except Exception:
    ADMIN_EMAILS = ["consultorabril1215@gmail.com"]


def get_viewer_email() -> str | None:
    # Prueba primero la API moderna (st.user), y si no existe o no trae
    # email, cae a la API antigua (st.experimental_user) — cubre distintas
    # versiones de Streamlit que puede tener instaladas Community Cloud.
    for accessor in ("user", "experimental_user"):
        try:
            u = getattr(st, accessor, None)
            if u is None:
                continue
            if getattr(u, "is_logged_in", True) is False:
                continue
            email = getattr(u, "email", None)
            if email:
                return email
        except Exception:
            continue
    return None


def is_admin_user() -> bool:
    email = get_viewer_email()
    return bool(email) and email.lower() in [e.lower() for e in ADMIN_EMAILS]


# =============================================================================
# Estado de la aplicación
# =============================================================================
def _init_state():
    if "project" not in st.session_state:
        st.session_state.project = VerificationProject(
            method=MethodInfo(),
            criteria=AcceptanceCriteria(),
            design=DesignStructure(),
        )
    if "active_compound" not in st.session_state:
        st.session_state.active_compound = None


_init_state()
project: VerificationProject = st.session_state.project


def to_float(val) -> float:
    """Convierte un valor pegado/escrito en la grilla a número, aceptando
    tanto coma decimal (configuración regional de Excel en Colombia, p.ej.
    "0,1001") como punto decimal ("0.1001"), y también miles con el
    separador contrario (p.ej. "1.234,56" o "1,234.56")."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def numeric_data_editor(df: pd.DataFrame, numeric_cols: list[str], **kwargs) -> pd.DataFrame:
    """Envuelve st.data_editor para que las columnas numéricas se editen como
    texto (así el pegado desde Excel con coma decimal no se rechaza ni se
    trunca) y devuelve el DataFrame ya con esas columnas convertidas a float."""
    df_txt = df.copy()
    for c in numeric_cols:
        df_txt[c] = df_txt[c].apply(lambda v: "" if v is None else str(v))
    df_edit = st.data_editor(df_txt, **kwargs)
    for c in numeric_cols:
        df_edit[c] = df_edit[c].apply(to_float)
    return df_edit


def alert(ok: bool, texto_ok: str, texto_fail: str):
    if ok:
        st.success(f"✅ {texto_ok}")
    else:
        st.error(f"⚠️ {texto_fail}")


def render_design_panel(design):
    """Panel visible del diseño experimental que el analista debe cumplir al
    registrar datos: qué grupo (día × analista) hace cada réplica, cuántas
    réplicas por grupo y cuántos niveles debe tener la curva de calibración."""
    with st.container(border=True):
        st.markdown("### 📋 Diseño experimental a cumplir")
        st.caption(
            "Cada analista debe generar SUS réplicas en el grupo que le corresponde (mismo equipo, "
            "corto plazo dentro del grupo). No mezclar réplicas de un grupo con las de otro."
        )
        rows = [
            {"Grupo": i + 1, "Día": g["dia"], "Analista responsable": g["analista"],
             "Réplicas que debe generar": design.replicas_por_grupo}
            for i, g in enumerate(design.grupos)
        ]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Grupos totales", design.n_grupos)
        c2.metric("Réplicas totales / nivel", design.n_replicas_total)
        c3.metric("Niveles curva calibración", design.n_niveles_curva)
        c4.metric("Curvas de calibración", design.n_dias)
        st.caption(
            f"Grados de libertad para la precisión intermedia (SI): df = {design.df_si}. "
            + ("Adecuado según la guía (recomendado ≥5)." if design.df_si >= 5 else
               "⚠️ Por debajo de lo recomendado por la guía (6-15 grupos); queda como limitación "
               "documentada del estudio, aceptada por restricción de costos.")
        )


# =============================================================================
# Navegación
# =============================================================================
st.sidebar.title("Verificación + Incertidumbre")
page = st.sidebar.radio(
    "Sección",
    [
        "1. Método y criterios de aceptación",
        "2. Certificados de materiales de referencia",
        "3. Compuestos y datos de verificación",
        "4. Resultados de verificación (alertas)",
        "5. Estimación de incertidumbre",
        "6. Exportar (Excel / PDF)",
    ],
)

# =============================================================================
# Guardado / carga en Drive (compartido entre analistas y administrador)
# =============================================================================
st.sidebar.divider()
st.sidebar.markdown("### ☁️ Guardado compartido")
try:
    from core.persistence import drive_configured, save_project_to_drive, load_project_from_drive
    if drive_configured():
        if "last_saved" not in st.session_state:
            st.session_state.last_saved = None
        if st.sidebar.button("💾 Guardar en Drive", width='stretch'):
            try:
                save_project_to_drive(project)
                st.session_state.last_saved = "ahora mismo"
                st.sidebar.success("Guardado.")
            except Exception as e:
                st.sidebar.error(f"No se pudo guardar: {e}")
        if st.sidebar.button("📥 Cargar último guardado", width='stretch'):
            try:
                loaded, modified = load_project_from_drive()
                if loaded is None:
                    st.sidebar.warning("Todavía no hay nada guardado en Drive.")
                else:
                    st.session_state.project = loaded
                    st.sidebar.success(f"Cargado (última modificación: {modified}).")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"No se pudo cargar: {e}")
        if st.session_state.last_saved:
            st.sidebar.caption(f"Último guardado: {st.session_state.last_saved}")
    else:
        st.sidebar.caption(
            "No configurado todavía (falta agregar la cuenta de servicio en Secrets). "
            "Mientras tanto, los datos solo viven en esta sesión del navegador."
        )
except ImportError:
    st.sidebar.caption("Módulo de Drive no disponible (faltan dependencias).")

# =============================================================================
# 1. Método y criterios
# =============================================================================
if page.startswith("1"):
    st.header("1. Información del método y criterios de aceptación")
    st.caption(
        "Estos criterios se definen UNA sola vez y cambian según la técnica/método. "
        "Se aplicarán a todos los compuestos que registres."
    )

    with st.form("form_metodo"):
        c1, c2 = st.columns(2)
        with c1:
            project.method.ensayo = st.text_input("Ensayo", project.method.ensayo)
            project.method.matriz = st.text_input("Matriz", project.method.matriz)
            project.method.tecnica = st.text_input("Técnica", project.method.tecnica)
            project.method.metodo_referencia = st.text_input("Método de referencia", project.method.metodo_referencia)
            project.method.procedimiento_interno = st.text_input(
                "Procedimiento interno", project.method.procedimiento_interno
            )
        with c2:
            project.method.codigo_formato = st.text_input("Código del formato", project.method.codigo_formato)
            cv1, cv2 = st.columns(2)
            with cv1:
                project.method.version = st.text_input("Versión", project.method.version)
            with cv2:
                project.method.fecha = st.date_input("Fecha", project.method.fecha)
            project.method.unidad = st.text_input("Unidad de trabajo", project.method.unidad)
            project.method.laboratorio = st.text_input("Laboratorio", project.method.laboratorio)
            analistas_txt = st.text_input("Analista(s) (separados por coma)", ", ".join(project.method.analistas))
            project.method.analistas = [a.strip() for a in analistas_txt.split(",") if a.strip()]

        st.subheader("Equipos utilizados")
        st.caption("Instrumentos de medición usados en la verificación — se incluyen en el informe final.")
        df_equipos_default = pd.DataFrame(
            project.method.equipos or [{"equipo": "", "marca": "", "codigo_interno": ""}]
        )
        df_equipos = st.data_editor(df_equipos_default, num_rows="dynamic", key="equipos_editor",
                                     column_config={
                                         "equipo": "Equipo", "marca": "Marca", "codigo_interno": "Código interno",
                                     })

        st.subheader("Estructura del diseño experimental (grupos = día × analista)")
        st.caption(
            "Cada 'grupo' se mide en condiciones de repetibilidad (mismo analista, mismo equipo, "
            "corto plazo). La variación ENTRE grupos (día y/o analista distinto) es lo que estima la "
            "precisión intermedia (Eurachem 6.6.4 / Ref. Rápida 7c). La guía recomienda 6-15 grupos; "
            "con menos, la SI queda documentada como una estimación de menor robustez estadística."
        )
        d1, d2, d3 = st.columns(3)
        with d1:
            project.design.n_dias = st.number_input("Número de días", 1, 20, project.design.n_dias)
            analistas_design_txt = st.text_input(
                "Analistas que rotan por día (separados por coma)", ", ".join(project.design.analistas)
            )
            project.design.analistas = [a.strip() for a in analistas_design_txt.split(",") if a.strip()] or ["Analista único"]
        with d2:
            project.design.replicas_por_grupo = st.number_input(
                "Réplicas por grupo (duplicado)", 1, 10, project.design.replicas_por_grupo
            )
        with d3:
            project.design.n_niveles_curva = st.number_input(
                "Niveles de la curva de calibración", 2, 15, project.design.n_niveles_curva
            )
        st.caption(
            f"→ {project.design.n_dias} días × {len(project.design.analistas)} analistas = "
            f"**{project.design.n_grupos} grupos** (df = {project.design.df_si} para SI) × "
            f"{project.design.replicas_por_grupo} réplicas = {project.design.n_replicas_total} réplicas totales."
        )

        st.subheader("Criterios de aceptación")
        e1, e2, e3 = st.columns(3)
        with e1:
            project.criteria.r_min = st.number_input(
                "r mínimo (linealidad)", 0.0, 1.0, project.criteria.r_min, format="%.4f"
            )
            project.criteria.cv_max_percent = st.number_input(
                "CV% máximo (precisión)", 0.0, 100.0, project.criteria.cv_max_percent
            )
            project.criteria.error_rel_max_percent = st.number_input(
                "% Error máximo por punto de la curva", 0.0, 100.0, project.criteria.error_rel_max_percent
            )
        with e2:
            project.criteria.recovery_lc_min = st.number_input(
                "Recuperación mín. en LC (%)", 0.0, 200.0, project.criteria.recovery_lc_min
            )
            project.criteria.recovery_lc_max = st.number_input(
                "Recuperación máx. en LC (%)", 0.0, 300.0, project.criteria.recovery_lc_max
            )
        with e3:
            project.criteria.recovery_min = st.number_input(
                "Recuperación mín. LS/muestras (%)", 0.0, 200.0, project.criteria.recovery_min
            )
            project.criteria.recovery_max = st.number_input(
                "Recuperación máx. LS/muestras (%)", 0.0, 300.0, project.criteria.recovery_max
            )

        f1, f2, f3 = st.columns(3)
        with f1:
            project.criteria.grubbs_alpha = st.selectbox(
                "Alfa prueba Grubbs", [0.05, 0.01],
                index=0 if project.criteria.grubbs_alpha == 0.05 else 1,
            )
        with f2:
            project.criteria.k_coverage = st.number_input(
                "Factor de cobertura k (incertidumbre)", 1.0, 3.0, float(project.criteria.k_coverage)
            )
        with f3:
            project.criteria.confidence_level_percent = st.number_input(
                "Nivel de confianza (%)", 50.0, 99.99, project.criteria.confidence_level_percent
            )

        if st.form_submit_button("Guardar", type="primary"):
            project.method.equipos = [
                r for r in df_equipos.to_dict("records") if r.get("equipo")
            ]
            st.rerun()

    render_design_panel(project.design)


# =============================================================================
# 2. Certificados de materiales de referencia
# =============================================================================
elif page.startswith("2"):
    st.header("2. Certificados y material volumétrico")
    tab_cert, tab_equip = st.tabs(["📜 Certificados de MRC", "🧪 Material volumétrico (Hoja M)"])

    with tab_cert:
        st.caption(
            "Registra aquí cada certificado de proveedor UNA vez (puede contener varios compuestos, "
            "como un estándar mezcla, o el estándar subrogado). Luego se reutiliza al configurar cada "
            "compuesto, sin necesidad de volver a digitar los datos si vienen del mismo certificado/lote."
        )

        with st.expander("➕ Registrar nuevo certificado", expanded=len(project.certificates) == 0):
            with st.form("form_cert"):
                c1, c2 = st.columns(2)
                with c1:
                    proveedor = st.text_input("Proveedor", "Absolute Standards, Inc.")
                    numero_parte = st.text_input("Número de parte (Part Number)")
                    numero_lote = st.text_input("Número de lote (Lot Number)")
                    descripcion = st.text_input("Descripción")
                    fecha_expiracion = st.text_input("Fecha de expiración")
                with c2:
                    solvente = st.text_input("Solvente")
                    volumen_disolucion = st.number_input("Volumen de disolución (mL)", 0.0, 10000.0, 0.0)
                    norma_acreditacion = st.text_input("Acreditación del proveedor", "ANAB ISO 17034")
                    referencia_trazabilidad = st.text_input(
                        "Referencia de trazabilidad", "NIST Technical Note 1297"
                    )
                archivo = st.file_uploader("Adjuntar PDF del certificado (opcional, queda como soporte)", type=["pdf"])

                st.markdown("**Analitos certificados en este documento** (una fila por compuesto — incluye el "
                            "subrogado si su certificado es el mismo documento)")
                df_default = pd.DataFrame(
                    [{"compuesto": "", "conc_nominal": 0.0, "conc_real": 0.0, "unidad": "µg/mL",
                      "U_expandida": 0.0, "k_certificado": 2.0, "k_asumido": True,
                      "pureza_%": None, "U_pureza_%": None}]
                )
                df_analitos = st.data_editor(df_default, num_rows="dynamic", key="cert_analitos_editor")

                if st.form_submit_button("Guardar certificado", type="primary"):
                    analitos = [
                        CertificateAnalyte(
                            nombre_compuesto=row["compuesto"],
                            concentracion_nominal=row["conc_nominal"] or 0.0,
                            concentracion_real=row["conc_real"] or 0.0,
                            unidad=row["unidad"] or "µg/mL",
                            incertidumbre_expandida=row["U_expandida"],
                            k_certificado=row["k_certificado"] or 2.0,
                            k_supuesto=bool(row["k_asumido"]),
                            pureza_percent=row["pureza_%"],
                            incertidumbre_pureza_percent=row["U_pureza_%"],
                        )
                        for _, row in df_analitos.iterrows() if row["compuesto"]
                    ]
                    pdf_path = ""
                    if archivo is not None:
                        pdf_path = f"data/certificados/{numero_parte}_{numero_lote}_{archivo.name}"
                        import os
                        os.makedirs("data/certificados", exist_ok=True)
                        with open(pdf_path, "wb") as f:
                            f.write(archivo.getbuffer())
                    project.certificates.append(
                        CertificateRecord(
                            proveedor=proveedor, numero_parte=numero_parte, numero_lote=numero_lote,
                            descripcion=descripcion, fecha_expiracion=fecha_expiracion, solvente=solvente,
                            volumen_disolucion_ml=volumen_disolucion, norma_acreditacion=norma_acreditacion,
                            referencia_trazabilidad=referencia_trazabilidad, archivo_pdf_path=pdf_path,
                            analitos=analitos,
                        )
                    )
                    st.success("Certificado guardado.")
                    st.rerun()

        st.subheader("Certificados registrados")
        if not project.certificates:
            st.info("Aún no hay certificados registrados.")
        for cert in project.certificates:
            with st.expander(f"{cert.proveedor} — Parte {cert.numero_parte}, Lote {cert.numero_lote}"):
                st.write(f"**Descripción:** {cert.descripcion}  |  **Vence:** {cert.fecha_expiracion}")
                st.write(f"**Trazabilidad:** {cert.referencia_trazabilidad}  |  **Acreditación:** {cert.norma_acreditacion}")
                if cert.archivo_pdf_path:
                    st.write(f"📎 PDF adjunto: `{cert.archivo_pdf_path}`")
                rows = [
                    {
                        "Compuesto": a.nombre_compuesto, "Conc. real": a.concentracion_real, "Unidad": a.unidad,
                        "U expandida": a.incertidumbre_expandida, "k": a.k_certificado,
                        "k asumido": "Sí" if a.k_supuesto else "No (del certificado)",
                        "Pureza %": a.pureza_percent, "U pureza %": a.incertidumbre_pureza_percent,
                    }
                    for a in cert.analitos
                ]
                st.dataframe(pd.DataFrame(rows), width='stretch')

    with tab_equip:
        st.caption(
            "Registro de material volumétrico (pipetas, balones aforados, etc.) — equivalente a tu "
            "'Hoja M'. Regístralo UNA vez por instrumento; luego lo seleccionas por nombre al armar la "
            "dilución de cada compuesto, sin digitar los valores de nuevo."
        )
        df_eq_default = pd.DataFrame(
            [{"nombre": e.nombre, "tipo": e.tipo, "clase": e.clase, "capacidad_nominal": e.capacidad_nominal,
              "codigo_interno": e.codigo_interno, "tiene_certificado_calibracion": e.tiene_certificado_calibracion,
              "incertidumbre_certificado": e.incertidumbre_certificado, "k_certificado": e.k_certificado,
              "fecha_calibracion": e.fecha_calibracion, "tolerancia_fabricante": e.tolerancia_fabricante,
              "sd_repetibilidad": e.sd_repetibilidad, "n_repetibilidad": e.n_repetibilidad}
             for e in project.equipment] or
            [{"nombre": "", "tipo": "Pipeta", "clase": "A", "capacidad_nominal": 0.0,
              "codigo_interno": "", "tiene_certificado_calibracion": False,
              "incertidumbre_certificado": None, "k_certificado": 2.0,
              "fecha_calibracion": "", "tolerancia_fabricante": None,
              "sd_repetibilidad": None, "n_repetibilidad": 10}]
        )
        df_eq = st.data_editor(
            df_eq_default, num_rows="dynamic", key="equipment_editor", width='stretch',
            column_config={
                "tipo": st.column_config.SelectboxColumn(options=["Pipeta", "Balón aforado", "Probeta", "Jeringa", "Otro"]),
                "clase": st.column_config.SelectboxColumn(options=["A", "B", "A/S", "N/A"]),
            },
        )
        if st.button("💾 Guardar registro de material volumétrico", type="primary"):
            project.equipment = [
                VolumetricEquipmentRecord(
                    nombre=r["nombre"], tipo=r.get("tipo") or "Pipeta", clase=r.get("clase") or "A",
                    capacidad_nominal=to_float(r.get("capacidad_nominal")),
                    codigo_interno=r.get("codigo_interno") or "",
                    tiene_certificado_calibracion=bool(r.get("tiene_certificado_calibracion")),
                    incertidumbre_certificado=to_float(r.get("incertidumbre_certificado")) or None,
                    k_certificado=to_float(r.get("k_certificado")) or 2.0,
                    fecha_calibracion=r.get("fecha_calibracion") or "",
                    tolerancia_fabricante=to_float(r.get("tolerancia_fabricante")) or None,
                    sd_repetibilidad=to_float(r.get("sd_repetibilidad")) or None,
                    n_repetibilidad=int(r.get("n_repetibilidad") or 10),
                )
                for r in df_eq.to_dict("records") if r.get("nombre")
            ]
            st.success(f"Guardado ({len(project.equipment)} instrumentos).")
            st.rerun()


# =============================================================================
# 3. Compuestos y datos de verificación
# =============================================================================
elif page.startswith("3"):
    st.header("3. Compuestos y datos de verificación")
    render_design_panel(project.design)

    with st.expander("➕ Agregar compuesto", expanded=len(project.compounds) == 0):
        with st.form("form_add_compound"):
            nombre = st.text_input("Nombre del compuesto")
            c1, c2 = st.columns(2)
            with c1:
                lc = st.number_input("LC nominal (Límite de cuantificación)", 0.0, value=0.1, format="%.5f")
            with c2:
                ls = st.number_input("LS nominal (Límite superior)", 0.0, value=2.0, format="%.5f")
            if st.form_submit_button("Agregar", type="primary") and nombre:
                project.compounds.append(Compound(nombre=nombre, lc_nominal=lc, ls_nominal=ls))
                st.session_state.active_compound = nombre
                st.rerun()

    if not project.compounds:
        st.info("Agrega al menos un compuesto para continuar.")
        st.stop()

    nombres = [c.nombre for c in project.compounds]
    sel = st.selectbox("Compuesto a editar", nombres, index=max(0, nombres.index(st.session_state.active_compound))
                        if st.session_state.active_compound in nombres else 0)
    st.session_state.active_compound = sel
    compound = next(c for c in project.compounds if c.nombre == sel)

    tabs = st.tabs(["Curvas de calibración", "LC / LS (verificación)", "Muestras", "Ventanas de retención",
                     "Preparación del estándar (incertidumbre)"])

    # --- Curvas de calibración ---
    with tabs[0]:
        st.caption(
            f"{project.design.n_dias} curvas (una por día), {project.design.n_niveles_curva} niveles cada una. "
            "💡 Puedes **copiar un bloque de celdas desde Excel** (columna de niveles + una columna por curva) "
            "y pegarlo aquí: haz clic en la primera celda de la tabla y presiona Ctrl+V."
        )
        if not compound.calibration_curves:
            compound.calibration_curves = [
                CalibrationCurve(levels_nominal=[0.0] * project.design.n_niveles_curva,
                                  responses=[0.0] * project.design.n_niveles_curva)
                for _ in range(project.design.n_dias)
            ]
        n_niv = project.design.n_niveles_curva
        wide = {"nivel_nominal": compound.calibration_curves[0].levels_nominal[:n_niv]}
        for i, curve in enumerate(compound.calibration_curves):
            wide[f"Curva {i + 1} (día {i + 1})"] = curve.responses[:n_niv]
        df_wide = pd.DataFrame(wide)
        df_edit = numeric_data_editor(df_wide, list(wide.keys()),
                                       key=f"curves_wide_{compound.nombre}", num_rows="fixed",
                                       width='stretch')
        levels_col = df_edit["nivel_nominal"].tolist()
        for i, curve in enumerate(compound.calibration_curves):
            curve.levels_nominal = levels_col
            curve.responses = df_edit[f"Curva {i + 1} (día {i + 1})"].tolist()

        analistas_opts = project.design.analistas or ["(sin asignar)"]
        rt_cols = st.columns(len(compound.calibration_curves))
        for i, (curve, col) in enumerate(zip(compound.calibration_curves, rt_cols)):
            with col:
                curve.dia = i + 1
                curve.retention_time_min = st.number_input(
                    f"T. retención curva {i + 1} (min)", 0.0, key=f"rt_{compound.nombre}_{i}",
                    value=curve.retention_time_min or 0.0,
                )
                idx_default = analistas_opts.index(curve.analista) if curve.analista in analistas_opts else 0
                curve.analista = st.selectbox(
                    f"Analista curva {i + 1}", analistas_opts, index=idx_default, key=f"analista_curva_{compound.nombre}_{i}"
                )

        st.divider()
        st.markdown("#### Pruebas estadísticas de la curva (ISO 8466-1:1990, decisión del modelo)")
        try:
            all_lv, all_rs, dias_c, analistas_c = compound.curve_arrays()
            if len(all_lv) >= 2 and all(len(l) >= 4 for l in all_lv):
                cal = S.analyze_calibration(all_lv, all_rs, project.criteria.r_min, dias_c, analistas_c)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**1. Homogeneidad de varianzas (§4.1.2)**")
                    st.write(f"Fcalc = {cal.homogeneidad.f_calc:.3f}  |  Fcrit(99%) = {cal.homogeneidad.f_crit:.3f}")
                    alert(cal.homogeneidad.homogenea, cal.homogeneidad.decision, cal.homogeneidad.decision)
                with c2:
                    st.markdown("**2. Linealidad — prueba de Mandel (§4.1.3)**")
                    st.write(f"PG = {cal.linealidad_mandel.pg:.4f}  |  Fcrit(99%) = {cal.linealidad_mandel.f_crit:.3f}")
                    alert(cal.linealidad_mandel.es_lineal, cal.linealidad_mandel.decision, cal.linealidad_mandel.decision)

                st.info(f"**Modelo aplicado: regresión {cal.modelo_usado}**  →  "
                        f"pendiente = {cal.slope:.5f}, intercepto = {cal.intercept:.5f}, r = {cal.r:.5f}, r² = {cal.r2:.5f}")
                alert(cal.cumple_r, f"Cumple r ≥ {project.criteria.r_min}", f"NO cumple r ≥ {project.criteria.r_min}")

                df_pts = pd.DataFrame({
                    "Día": cal.dias, "Analista": cal.analistas,
                    "Nivel nominal": cal.puntos_x, "Respuesta": cal.puntos_y,
                    "Residual (señal)": [round(v, 5) for v in cal.residuales],
                    "Conc. recalculada": [round(v, 5) for v in cal.x_recalculada],
                    "% Error": [round(v, 2) for v in cal.error_percent],
                })
                err_max = project.criteria.error_rel_max_percent
                st.dataframe(
                    df_pts.style.map(
                        lambda v: "background-color:#FFC7CE" if isinstance(v, (int, float)) and abs(v) > err_max else "",
                        subset=["% Error"],
                    ),
                    width='stretch',
                )
                puntos_excedidos = [
                    (d, a, n, e) for d, a, n, e in zip(cal.dias, cal.analistas, cal.puntos_x, cal.error_percent)
                    if abs(e) > err_max
                ]
                if puntos_excedidos:
                    detalle = "; ".join(f"día {d} ({a or 's/analista'}), nivel {n}: {e:.1f}%" for d, a, n, e in puntos_excedidos)
                    st.error(f"⚠️ {len(puntos_excedidos)} punto(s) de la curva exceden ±{err_max}% de error: {detalle}")
                else:
                    st.success(f"✅ Todos los puntos de la curva dentro de ±{err_max}% de error.")
                st.markdown("**Gráfica de residuales**")
                st.scatter_chart(df_pts, x="Nivel nominal", y="Residual (señal)")

                st.markdown("**Datos atípicos por nivel (Dixon/Grubbs automático según n)**")
                niveles_unicos = sorted(set(cal.puntos_x))
                for lvl in niveles_unicos:
                    vals = [y for x, y in zip(cal.puntos_x, cal.puntos_y) if x == lvl]
                    if len(vals) >= 3:
                        ot = S.outlier_test_auto(vals, project.criteria.grubbs_alpha)
                        ok = not ot.hay_atipico
                        alert(ok, f"Nivel {lvl}: sin atípicos ({ot.prueba_usada}, n={ot.n})",
                              f"Nivel {lvl}: POSIBLE ATÍPICO ({ot.prueba_usada}, n={ot.n}, crítico={ot.valor_critico})")
            else:
                st.caption("Ingresa datos en al menos 2 curvas (mín. 4 niveles) para calcular las pruebas.")
        except Exception as e:
            st.warning(f"No se pudo completar el análisis de la curva: {e}")

    grupo_labels = [f"Día {g['dia']} — {g['analista']}" for g in project.design.grupos]

    # --- LC / LS ---
    with tabs[1]:
        st.caption(
            f"Réplicas de blancos fortificados a LC y LS: {project.design.n_grupos} grupos "
            f"(día × analista) × {project.design.replicas_por_grupo} réplicas."
        )
        for label, nominal_attr in [("LC", "lc_nominal"), ("LS", "ls_nominal")]:
            existing = next((r for r in compound.replicate_levels if r.label == label), None)
            if existing is None:
                existing = ReplicateLevel(
                    label=label, nominal=getattr(compound, nominal_attr), tipo=label,
                    values=[[0.0] * project.design.replicas_por_grupo for _ in range(project.design.n_grupos)],
                )
                compound.replicate_levels.append(existing)
            existing.nominal = getattr(compound, nominal_attr)
            st.markdown(f"**{label}** (nominal = {existing.nominal})")
            cols_labels = [f"Rep {j+1}" for j in range(project.design.replicas_por_grupo)]
            df = pd.DataFrame(existing.values, columns=cols_labels, index=grupo_labels)
            df_edit = numeric_data_editor(df, cols_labels, key=f"level_{compound.nombre}_{label}")
            existing.values = df_edit.values.tolist()

    # --- Muestras (control de calidad por lote, Tabla 5 LA-P-343/LA-P-340) ---
    with tabs[2]:
        st.caption(
            "Controles de calidad con muestras reales — Tabla 5 de tu procedimiento (LA-P-343/LA-P-340), "
            "igual para todas las técnicas. Las muestras nativas NO tienen valor esperado; el subrogado y "
            "la matriz fortificada sí, pero se evalúan de forma distinta (ver tipo)."
        )
        TIPOS_MUESTRA = ["Muestra", "MB", "LFB", "Subrogado", "LFM", "LFMD", "DM"]
        TIPO_AYUDA = {
            "Muestra": "Resultado nativo de la muestra, sin adición — solo se reporta (no lleva recuperación).",
            "MB": "Blanco del método — debe dar resultado < LC.",
            "LFB": "Blanco de laboratorio fortificado (~50% del rango de trabajo) — recuperación simple 70-130%.",
            "Subrogado": "Estándar subrogado agregado a la muestra en cantidad conocida — recuperación simple 70-130%.",
            "LFM": "Matriz de laboratorio fortificada — recuperación NETA vs. una muestra nativa de referencia, 70-130%.",
            "LFMD": "Duplicado de LFM — igual que LFM, más RPD contra el LFM de referencia, ≤30%.",
            "DM": "Duplicado de una muestra nativa — RPD contra esa muestra de referencia, ≤30%.",
        }
        existing_labels = [r.label for r in compound.replicate_levels if r.label not in ("LC", "LS")]

        with st.form(f"addlvl_form_{compound.nombre}"):
            c1, c2 = st.columns(2)
            with c1:
                new_label = st.text_input("Nombre (p.ej. 'Muestra SUP', 'LFM SUP')")
                new_tipo = st.selectbox("Tipo de control", TIPOS_MUESTRA, format_func=lambda t: f"{t} — {TIPO_AYUDA[t]}"[:60] + "…")
            with c2:
                new_nominal = st.number_input(
                    "Valor esperado / adicionado (deja 0 si es 'Muestra' nativa)", 0.0, format="%.5f"
                )
                ref_options = ["(ninguna)"] + existing_labels
                new_ref_nativa = st.selectbox("Muestra nativa de referencia (para LFM/LFMD)", ref_options)
                new_ref_dup = st.selectbox("Referencia para RPD (para DM/LFMD)", ref_options)
            st.caption(TIPO_AYUDA[new_tipo])
            if st.form_submit_button("➕ Agregar", type="primary") and new_label:
                compound.replicate_levels.append(
                    ReplicateLevel(
                        label=new_label, nominal=new_nominal, tipo=new_tipo,
                        referencia_nativa=None if new_ref_nativa == "(ninguna)" else new_ref_nativa,
                        referencia_duplicado=None if new_ref_dup == "(ninguna)" else new_ref_dup,
                        values=[[0.0] * project.design.replicas_por_grupo for _ in range(project.design.n_grupos)],
                    )
                )
                st.rerun()

        for lvl in compound.replicate_levels:
            if lvl.label in ("LC", "LS"):
                continue
            refs = []
            if lvl.referencia_nativa:
                refs.append(f"nativa: {lvl.referencia_nativa}")
            if lvl.referencia_duplicado:
                refs.append(f"RPD vs: {lvl.referencia_duplicado}")
            refs_txt = f" ({', '.join(refs)})" if refs else ""
            st.markdown(f"**{lvl.label}** — tipo `{lvl.tipo}`, valor esperado/adicionado = {lvl.nominal}{refs_txt}")
            cols_labels = [f"Rep {j+1}" for j in range(project.design.replicas_por_grupo)]
            df = pd.DataFrame(lvl.values, columns=cols_labels, index=grupo_labels)
            df_edit = numeric_data_editor(df, cols_labels, key=f"sample_{compound.nombre}_{lvl.label}")
            lvl.values = df_edit.values.tolist()

    # --- Ventanas de retención ---
    with tabs[3]:
        rts = [c.retention_time_min for c in compound.calibration_curves if c.retention_time_min]
        if rts:
            rw = S.retention_window(rts)
            st.write(f"Promedio: **{rw.promedio:.3f} min**  |  SD: **{rw.sd:.4f}**  |  "
                     f"Ventana (±3SD): **{rw.desde:.3f} – {rw.hasta:.3f} min**")
        else:
            st.info("Ingresa los tiempos de retención en la pestaña de curvas de calibración.")

    # --- Preparación del estándar (incertidumbre) ---
    with tabs[4]:
        def render_volumetric_step_ui(key_prefix: str, descripcion: str, default_vol: float) -> VolumetricStep:
            """Un volumen (alícuota o aforo): se selecciona el instrumento del
            registro (Hoja M) o se digita manualmente si no está registrado."""
            eq_options = ["(digitar manualmente)"] + [e.nombre for e in project.equipment]
            c1, c2 = st.columns([1, 1])
            with c1:
                vol = st.number_input(f"{descripcion} — volumen (mL)", 0.0, value=default_vol, format="%.4f",
                                       key=f"vol_{key_prefix}")
            with c2:
                sel_eq = st.selectbox(f"{descripcion} — instrumento", eq_options, key=f"eq_{key_prefix}")

            if sel_eq != "(digitar manualmente)":
                eq = project.get_equipment(sel_eq)
                st.caption(
                    f"{eq.tipo} clase {eq.clase}, {eq.capacidad_nominal} mL  |  "
                    + (f"U cert. ±{eq.incertidumbre_certificado} mL (k={eq.k_certificado})"
                       if eq.tiene_certificado_calibracion else
                       f"tolerancia ±{eq.tolerancia_fabricante} mL")
                    + (f"  |  SD repetibilidad {eq.sd_repetibilidad} mL" if eq.sd_repetibilidad else "")
                )
                return VolumetricStep(
                    descripcion=descripcion, volumen_nominal=vol or 1.0, instrumento=eq.nombre,
                    equipment_record_id=eq.nombre,
                    tiene_certificado_calibracion=eq.tiene_certificado_calibracion,
                    incertidumbre_certificado=eq.incertidumbre_certificado, k_certificado=eq.k_certificado,
                    tolerancia_fabricante=eq.tolerancia_fabricante, sd_repetibilidad=eq.sd_repetibilidad,
                    n_repetibilidad=eq.n_repetibilidad,
                )
            c3, c4 = st.columns(2)
            with c3:
                tiene_cal = st.checkbox("Tiene certificado de calibración", key=f"stepcal_{key_prefix}")
                u_cert = st.number_input("U del certificado (mL)", 0.0, key=f"stepUcert_{key_prefix}") if tiene_cal else None
                k_cert = st.number_input("k del certificado", 1.0, 3.0, 2.0, key=f"stepk_{key_prefix}") if tiene_cal else 2.0
                tol = None if tiene_cal else st.number_input(
                    "Tolerancia de fabricante/clase (mL, semi-intervalo)", 0.0, key=f"steptol_{key_prefix}"
                )
            with c4:
                sd_rep = st.number_input("SD de repetibilidad (mL, opcional)", 0.0, key=f"stepsd_{key_prefix}")
            return VolumetricStep(
                descripcion=descripcion, volumen_nominal=vol or 1.0,
                tiene_certificado_calibracion=tiene_cal, incertidumbre_certificado=u_cert, k_certificado=k_cert,
                tolerancia_fabricante=tol, sd_repetibilidad=sd_rep or None,
            )

        def render_standard_prep_ui(key_prefix: str, nombre_hint: str, niveles_ref: list[float]) -> StandardPreparation:
            cert_options = ["(sin certificado disponible)"] + [
                f"{c.proveedor} | {c.numero_parte} | {c.numero_lote}" for c in project.certificates
            ]
            sel_cert = st.selectbox("Certificado de MRC a usar", cert_options, key=f"selcert_{key_prefix}")

            rm = ReferenceMaterialCert(nombre=nombre_hint)
            if sel_cert != "(sin certificado disponible)":
                idx = cert_options.index(sel_cert) - 1
                cert = project.certificates[idx]
                analito_names = [a.nombre_compuesto for a in cert.analitos]
                sel_analito = st.selectbox("Analito dentro del certificado", analito_names, key=f"selan_{key_prefix}")
                an = next(a for a in cert.analitos if a.nombre_compuesto == sel_analito)
                rm.certificate_record_id = cert.numero_parte + "|" + cert.numero_lote
                rm.marca_lote = f"{cert.proveedor} {cert.numero_lote}"
                rm.concentracion = an.concentracion_real
                rm.concentracion_unidad = an.unidad
                rm.tiene_certificado = True
                rm.incertidumbre_certificado = an.incertidumbre_expandida
                rm.k_certificado = an.k_certificado
                rm.pureza_percent = an.pureza_percent
                rm.incertidumbre_pureza_percent = an.incertidumbre_pureza_percent
                st.info(
                    f"Concentración: {rm.concentracion} {rm.concentracion_unidad}  |  "
                    f"U: ±{rm.incertidumbre_certificado} (k={rm.k_certificado}"
                    f"{' asumido' if an.k_supuesto else ''})  |  Pureza: {rm.pureza_percent}%"
                )
            else:
                st.warning(
                    "Sin certificado disponible: se aplicará el tratamiento sugerido por la guía QUAM "
                    "(Apéndice G) usando la mejor estimación disponible como distribución rectangular."
                )
                rm.tiene_certificado = False
                rm.concentracion = st.number_input("Concentración estimada", 0.0, key=f"rmconc_{key_prefix}")
                rm.incertidumbre_certificado = st.number_input(
                    "Mejor estimación de U disponible (hoja técnica, etc.)", 0.0, key=f"rmU_{key_prefix}"
                )

            st.markdown("**Esquema de dilución — un nivel por cada punto de la curva (Tabla 2)**")
            niveles = []
            for i, conc in enumerate(niveles_ref):
                with st.expander(f"Nivel {i + 1} — {conc}", expanded=(i == 0)):
                    alicuota = render_volumetric_step_ui(
                        f"{key_prefix}_alic_{i}", f"Alícuota de MRC (nivel {i+1})", 0.005 * (i + 1)
                    )
                    aforo = render_volumetric_step_ui(
                        f"{key_prefix}_aforo_{i}", f"Volumen de aforo (nivel {i+1})", 5.0
                    )
                    niveles.append(DilutionLevel(
                        nivel_label=f"Nivel {i+1}", concentracion_nominal=conc, alicuota=alicuota, aforo=aforo,
                    ))
            return StandardPreparation(reference_material=rm, dilution_levels=niveles)

        st.caption(
            "Desglose de la preparación del patrón del analito: material de referencia (certificado) + "
            "esquema de dilución (alícuota + aforo) para CADA nivel de la curva. Esto alimenta la "
            "incertidumbre de calibración de forma específica para LC y para LS (no un valor único)."
        )
        niveles_ref = compound.calibration_curves[0].levels_nominal if compound.calibration_curves else \
            [compound.lc_nominal, compound.ls_nominal]
        compound.standard_preparation = render_standard_prep_ui(compound.nombre, compound.nombre, niveles_ref)

        st.divider()
        st.markdown("### Estándar subrogado (también es un MRC — Tabla 1/2, LA-P-343/LA-P-340)")
        st.caption(
            "El subrogado (p.ej. 2-bromo-1-cloropropano) es OTRO material de referencia certificado, que "
            "se diluye junto con el estándar del analito para la curva y se agrega a cada muestra como "
            "control de calidad. Se registra aquí por trazabilidad; su incertidumbre NO se combina con la "
            "del analito objetivo (son solutos independientes) — se guarda para uso futuro si se necesita "
            "estimar U del subrogado o para dejar constancia auditable del MRC usado."
        )
        usa_subrogado = st.checkbox("Este compuesto usa estándar subrogado", value=compound.surrogate_preparation is not None,
                                     key=f"usasubrog_{compound.nombre}")
        if usa_subrogado:
            compound.surrogate_preparation = render_standard_prep_ui(
                f"{compound.nombre}_subrogado", f"Subrogado ({compound.nombre})", niveles_ref
            )
        else:
            compound.surrogate_preparation = None

        st.markdown("**Volumen de muestra en el ensayo de rutina**")
        vm_col1, vm_col2 = st.columns(2)
        with vm_col1:
            vm_vol = st.number_input("Volumen nominal de muestra (mL)", 0.0, value=5.0, key=f"vmvol_{compound.nombre}")
            vm_tol = st.number_input("Tolerancia del instrumento (mL)", 0.0, value=0.025, key=f"vmtol_{compound.nombre}")
        with vm_col2:
            vm_sd = st.number_input("SD repetibilidad (mL, opcional)", 0.0, key=f"vmsd_{compound.nombre}")
        compound.volumen_muestra = VolumetricStep(
            descripcion="Volumen de muestra", volumen_nominal=vm_vol or 1.0,
            tolerancia_fabricante=vm_tol or None, sd_repetibilidad=vm_sd or None,
        )


# =============================================================================
# 4. Resultados de verificación
# =============================================================================
elif page.startswith("4"):
    st.header("4. Resultados de verificación")
    if not project.compounds:
        st.info("No hay compuestos registrados.")
        st.stop()

    crit = project.criteria
    for compound in project.compounds:
        st.subheader(compound.nombre)

        # --- Linealidad (con decisión ISO 8466-1 Simple/Ponderada) ---
        all_lv, all_rs, dias_c, analistas_c = compound.curve_arrays()
        cal = None
        if len(all_lv) >= 2 and all(len(l) >= 4 for l in all_lv):
            try:
                cal = S.analyze_calibration(all_lv, all_rs, crit.r_min, dias_c, analistas_c)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Modelo", cal.modelo_usado)
                c2.metric("Pendiente", f"{cal.slope:.4f}")
                c3.metric("Intercepto", f"{cal.intercept:.4f}")
                c4.metric("r", f"{cal.r:.5f}")
                alert(cal.cumple_r, f"Cumple r ≥ {crit.r_min}", f"NO cumple r ≥ {crit.r_min} (r={cal.r:.5f})")
                alert(cal.homogeneidad.homogenea, "Homogeneidad de varianzas: OK (§4.1.2)",
                      "NO homogénea — se aplicó regresión PONDERADA (§4.1.2)")
                alert(cal.linealidad_mandel.es_lineal, "Linealidad confirmada (Mandel §4.1.3)",
                      "Mandel indica NO linealidad — revisar rango de trabajo")
                puntos_excedidos = [
                    (d, a, n, e) for d, a, n, e in zip(cal.dias, cal.analistas, cal.puntos_x, cal.error_percent)
                    if abs(e) > crit.error_rel_max_percent
                ]
                alert(not puntos_excedidos,
                      f"Todos los puntos de la curva dentro de ±{crit.error_rel_max_percent}% de error",
                      f"{len(puntos_excedidos)} punto(s) exceden ±{crit.error_rel_max_percent}%: " +
                      "; ".join(f"día {d} ({a or 's/analista'}), nivel {n}: {e:.1f}%" for d, a, n, e in puntos_excedidos))
            except Exception as e:
                st.warning(f"No se pudo calcular linealidad: {e}")

        # --- Datos atípicos por nivel de calibración (Dixon/Grubbs automático) ---
        with st.expander("Datos atípicos en la curva (Dixon/Grubbs automático por nivel)"):
            if cal:
                niveles_unicos = sorted(set(cal.puntos_x))
                for lvl in niveles_unicos:
                    vals = [y for x, y in zip(cal.puntos_x, cal.puntos_y) if x == lvl]
                    if len(vals) >= 3:
                        ot = S.outlier_test_auto(vals, crit.grubbs_alpha)
                        ok = not ot.hay_atipico
                        alert(ok, f"Nivel {lvl}: sin atípicos ({ot.prueba_usada}, n={ot.n})",
                              f"Nivel {lvl}: POSIBLE ATÍPICO ({ot.prueba_usada}, n={ot.n}, crítico={ot.valor_critico})")

        # --- LC / LS / controles de calidad por lote (Tabla 5): por tipo ---
        def _flat(level_label):
            l = next((r for r in compound.replicate_levels if r.label == level_label), None)
            if l is None:
                return None
            f = [v for day in l.values for v in day]
            return f if any(f) else None

        for lvl in compound.replicate_levels:
            flat = _flat(lvl.label)
            if flat is None:
                continue
            st.markdown(f"**{lvl.label}** — tipo `{lvl.tipo}`")
            desc = S.descriptive_stats(flat)
            cols = st.columns(4)
            cols[0].metric("n", desc.n)
            cols[1].metric("Media", f"{desc.mean:.5f}")
            cols[2].metric("SD", f"{desc.sd:.5f}")
            cols[3].metric("CV%", f"{desc.cv_percent:.2f}" if desc.cv_percent is not None else "-")

            if lvl.tipo in ("LC", "LS", "LFB", "Subrogado") and lvl.nominal:
                tr = S.trueness_stats(flat, lvl.nominal, crit.t_alpha)
                cols2 = st.columns(4)
                cols2[0].metric("Error relativo %", f"{tr.error_rel_percent:.2f}")
                cols2[1].metric("Recuperación %", f"{tr.recovery_percent:.2f}")
                cols2[2].metric("t calculado", f"{tr.t_calculado:.3f}")
                cols2[3].metric("t tabulado", f"{tr.t_tabulado:.3f}")
                rec_min, rec_max = (crit.recovery_lc_min, crit.recovery_lc_max) if lvl.tipo == "LC" else (crit.recovery_min, crit.recovery_max)
                ok_rec = rec_min <= tr.recovery_percent <= rec_max
                alert(ok_rec, f"Recuperación dentro de {rec_min}-{rec_max}%",
                      f"Recuperación FUERA de {rec_min}-{rec_max}%")
                alert(tr.t_calculado <= tr.t_tabulado,
                      "t calculado ≤ t tabulado: no hay sesgo significativo",
                      "t calculado > t tabulado: SESGO ESTADÍSTICAMENTE SIGNIFICATIVO")

            elif lvl.tipo == "MB":
                alert(desc.mean < compound.lc_nominal,
                      f"Blanco del método ({desc.mean:.5f}) < LC ({compound.lc_nominal})",
                      f"Blanco del método ({desc.mean:.5f}) NO es < LC ({compound.lc_nominal})")

            elif lvl.tipo in ("LFM", "LFMD"):
                native_flat = _flat(lvl.referencia_nativa) if lvl.referencia_nativa else None
                if native_flat is None:
                    st.warning("Falta seleccionar/registrar la muestra nativa de referencia para calcular la recuperación neta.")
                else:
                    nr = S.net_recovery_stats(flat, native_flat, lvl.nominal or 1.0)
                    cols2 = st.columns(3)
                    cols2[0].metric("Media nativa", f"{nr.mean_native:.5f}")
                    cols2[1].metric("Media adicionada", f"{nr.mean_spiked:.5f}")
                    cols2[2].metric("Recuperación neta %", f"{nr.net_recovery_percent:.2f}")
                    ok_rec = crit.recovery_min <= nr.net_recovery_percent <= crit.recovery_max
                    alert(ok_rec, f"Recuperación neta dentro de {crit.recovery_min}-{crit.recovery_max}%",
                          f"Recuperación neta FUERA de {crit.recovery_min}-{crit.recovery_max}%")
                if lvl.tipo == "LFMD" and lvl.referencia_duplicado:
                    dup_flat = _flat(lvl.referencia_duplicado)
                    if dup_flat:
                        rpd = S.rpd_stats(flat, dup_flat)
                        alert(rpd.rpd_percent <= crit.rpd_max_percent,
                              f"RPD ({rpd.rpd_percent:.2f}%) ≤ {crit.rpd_max_percent}%",
                              f"RPD ({rpd.rpd_percent:.2f}%) EXCEDE {crit.rpd_max_percent}%")

            elif lvl.tipo == "DM":
                if lvl.referencia_duplicado:
                    dup_flat = _flat(lvl.referencia_duplicado)
                    if dup_flat:
                        rpd = S.rpd_stats(flat, dup_flat)
                        cols2 = st.columns(1)
                        cols2[0].metric("RPD %", f"{rpd.rpd_percent:.2f}")
                        alert(rpd.rpd_percent <= crit.rpd_max_percent,
                              f"RPD ({rpd.rpd_percent:.2f}%) ≤ {crit.rpd_max_percent}%",
                              f"RPD ({rpd.rpd_percent:.2f}%) EXCEDE {crit.rpd_max_percent}%")
                    else:
                        st.warning("Falta registrar datos en la muestra de referencia para calcular el RPD.")
                else:
                    st.warning("Falta seleccionar la muestra de referencia para el duplicado (RPD).")

            elif lvl.tipo == "Muestra":
                st.caption("Muestra nativa: sin valor esperado, se reporta el resultado tal cual.")

            if len(lvl.values) >= 2 and all(len(d) == len(lvl.values[0]) for d in lvl.values):
                try:
                    prec = S.repeatability_intermediate_precision(lvl.values)
                    cols3 = st.columns(4)
                    cols3[0].metric("Sr", f"{prec.sr:.5f}")
                    cols3[1].metric("SI", f"{prec.si:.5f}")
                    cols3[2].metric("%Sr", f"{prec.cv_sr_percent:.2f}")
                    cols3[3].metric("%SI", f"{prec.cv_si_percent:.2f}")
                except Exception as e:
                    st.caption(f"(No se pudo calcular ANOVA de precisión: {e})")

            ot = S.outlier_test_auto(flat, crit.grubbs_alpha)
            alert(not ot.hay_atipico, f"Sin datos atípicos ({ot.prueba_usada}, n={ot.n})",
                  f"POSIBLE DATO ATÍPICO — prueba {ot.prueba_usada} (n={ot.n}, "
                  f"estadístico bajo={ot.estadistico_bajo:.3f}, alto={ot.estadistico_alto:.3f}, "
                  f"crítico={ot.valor_critico})")
            st.divider()


# =============================================================================
# 5. Estimación de incertidumbre
# =============================================================================
elif page.startswith("5"):
    st.header("5. Estimación de incertidumbre de medición (QUAM:2012 CG4)")
    if not project.compounds:
        st.info("No hay compuestos registrados.")
        st.stop()

    k = project.criteria.k_coverage
    for compound in project.compounds:
        st.subheader(compound.nombre)
        if compound.standard_preparation is None or not compound.standard_preparation.dilution_levels:
            st.warning("Falta configurar el esquema de dilución del estándar en la Sección 3 "
                       "(pestaña 'Preparación del estándar').")
            continue

        u_vm = U.volumetric_step_uncertainty(compound.volumen_muestra) if compound.volumen_muestra else None
        u_vm_rel = u_vm.u_relativa if u_vm else 0.0

        budget_levels = []
        for label, nominal in [("LC", compound.lc_nominal), ("LS", compound.ls_nominal)]:
            lvl = next((r for r in compound.replicate_levels if r.label == label), None)
            if lvl is None:
                continue
            flat = [v for day in lvl.values for v in day]
            if not any(flat):
                continue

            try:
                prep_u = U.standard_preparation_uncertainty_at(compound.standard_preparation, nominal)
            except Exception as e:
                st.warning(f"No se pudo calcular u de preparación en {label}: {e}")
                continue
            with st.expander(f"Detalle de la preparación en {label} ({nominal})"):
                st.write(f"- u relativa combinada: {prep_u.u_relativa_combinada:.5f}")
                st.write(f"- u relativa por pureza del MRC: {prep_u.u_relativa_pureza:.5f}")
                st.write(f"- u relativa por concentración certificada del MRC: {prep_u.u_relativa_certificado_mrc:.5f}")
                for p, nombre_paso in zip(prep_u.u_relativa_pasos, ["alícuota", "aforo"]):
                    st.write(f"- {nombre_paso}: u = {p.u_relativa:.5f}  ({p.fuente_calibracion})")

            prec = None
            try:
                prec = S.repeatability_intermediate_precision(lvl.values)
            except Exception:
                pass
            u_repeat_rel = (prec.si / (sum(flat) / len(flat))) if prec and sum(flat) else 0.0

            # incertidumbre de la respuesta de la curva (Ec. E3.4/E3.5), usando
            # el MISMO modelo (simple/ponderado) decidido por ISO 8466-1 en la
            # pestaña de curvas — un solo ajuste agrupando todas las curvas,
            # no un ajuste distinto por curva.
            all_lv_u, all_rs_u, _, _ = compound.curve_arrays()
            try:
                cal_u = S.analyze_calibration(all_lv_u, all_rs_u, project.criteria.r_min)
                res_x = [r / cal_u.slope for r in cal_u.residuales]
                u_cal_abs = U.calibration_response_uncertainty(cal_u.puntos_x, res_x, nominal)
                u_cal_rel = u_cal_abs / nominal if nominal else 0.0
            except Exception as e:
                u_cal_rel = 0.0
                st.caption(f"(No se pudo calcular u de calibración en {label}: {e})")

            budget = U.combine_budget(
                label, nominal, u_cal_rel, prep_u.u_relativa_combinada, u_vm_rel, u_repeat_rel, k=k,
            )
            budget_levels.append(budget)

        if budget_levels:
            df = pd.DataFrame([{
                "Nivel": b.nivel_label, "Concentración": b.concentracion,
                "u cal (rel)": round(b.u_calibracion_relativa, 5),
                "u prep (rel)": round(b.u_preparacion_relativa, 5),
                "u vol. muestra (rel)": round(b.u_volumen_muestra_relativa, 5),
                "u repetibilidad (rel)": round(b.u_repetibilidad_relativa, 5),
                "uc (rel)": round(b.uc_relativa, 5),
                "U expandida (abs)": round(b.u_expandida, 5),
                "U relativa (%)": round(b.u_relativa_expandida_percent, 2),
            } for b in budget_levels])
            st.dataframe(df, width='stretch')

            if len(budget_levels) >= 2:
                model = U.fit_level_dependent_model(budget_levels)
                st.success(
                    f"Modelo dependiente del nivel (Apéndice E.5): u(x) = √(s0² + (x·s1)²)  →  "
                    f"s0 = {model.s0:.6f}, s1 = {model.s1:.6f}  ({model.metodo})"
                )
                x_test = st.number_input(
                    f"Probar el modelo con una concentración de {compound.nombre}", 0.0,
                    value=float(compound.lc_nominal), key=f"xtest_{compound.nombre}",
                )
                u_x = model.u(x_test)
                st.write(f"u({x_test}) = {u_x:.6f}   →   U = {k*u_x:.6f}   →   "
                         f"Resultado = ({x_test} ± {k*u_x:.5f}) {project.method.unidad}   "
                         f"({(k*u_x/x_test*100) if x_test else 0:.1f}% relativo)")
        st.divider()


# =============================================================================
# 6. Exportar
# =============================================================================
elif page.startswith("6"):
    st.header("6. Exportar resultados")

    viewer = get_viewer_email()
    if viewer is None:
        st.info("La descarga está reservada al administrador. Inicia sesión con Google para verificar tu acceso.")
        if hasattr(st, "login") and st.button("🔐 Iniciar sesión con Google", type="primary"):
            st.login()
        st.stop()

    if not is_admin_user():
        st.warning(
            "🔒 La descarga de archivos está reservada al administrador del sistema. "
            "Puedes revisar todos los resultados y alertas en la Sección 4 (Resultados de "
            "verificación) y Sección 5 (Incertidumbre) — solo la exportación a Excel/PDF está "
            "restringida."
        )
        st.caption(f"Conectado como: {viewer}")
        st.stop()

    st.caption(f"✅ Sesión de administrador: {viewer}")
    if hasattr(st, "logout") and st.button("Cerrar sesión"):
        st.logout()

    st.caption(
        "Genera el Excel de verificación (con fórmulas vivas, no solo valores — para que un "
        "auditor pueda revisar el detalle del cálculo directamente en el archivo) y el informe "
        "PDF unificado."
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📊 Generar Excel de verificación", type="primary"):
            from export.excel_export import build_verification_excel
            path = build_verification_excel(project)
            with open(path, "rb") as f:
                st.download_button("Descargar Excel", f, file_name="Verificacion.xlsx")
    with c2:
        if st.button("📄 Generar informe PDF", type="primary"):
            from export.pdf_report import build_pdf_report
            path = build_pdf_report(project)
            with open(path, "rb") as f:
                st.download_button("Descargar PDF", f, file_name="Informe_Verificacion.pdf")
