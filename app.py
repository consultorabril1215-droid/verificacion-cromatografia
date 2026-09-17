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
)
from core import stats as S
from core import uncertainty as U

st.set_page_config(page_title="Verificación de Métodos + Incertidumbre", layout="wide")


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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
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
            project.method.version = st.text_input("Versión", project.method.version)
            project.method.unidad = st.text_input("Unidad de trabajo", project.method.unidad)
            project.method.laboratorio = st.text_input("Laboratorio", project.method.laboratorio)
            analistas_txt = st.text_input("Analista(s) (separados por coma)", ", ".join(project.method.analistas))
            project.method.analistas = [a.strip() for a in analistas_txt.split(",") if a.strip()]

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

        st.form_submit_button("Guardar", type="primary")

    render_design_panel(project.design)


# =============================================================================
# 2. Certificados de materiales de referencia
# =============================================================================
elif page.startswith("2"):
    st.header("2. Registro de certificados de materiales de referencia (MRC)")
    st.caption(
        "Registra aquí cada certificado de proveedor UNA vez (puede contener varios compuestos, "
        "como un estándar mezcla). Luego se reutiliza al configurar cada compuesto, sin necesidad "
        "de volver a digitar los datos si vienen del mismo certificado/lote."
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

            st.markdown("**Analitos certificados en este documento** (una fila por compuesto)")
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
            st.dataframe(pd.DataFrame(rows), use_container_width=True)


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
            f"Ingresa {project.design.n_dias} curvas (una por día), con {project.design.n_niveles_curva} "
            "niveles cada una. La concentración nominal debe ser igual entre curvas (mismo diseño)."
        )
        if not compound.calibration_curves:
            compound.calibration_curves = [
                CalibrationCurve(levels_nominal=[0.0] * project.design.n_niveles_curva,
                                  responses=[0.0] * project.design.n_niveles_curva)
                for _ in range(project.design.n_dias)
            ]
        for i, curve in enumerate(compound.calibration_curves):
            st.markdown(f"**Curva / Día {i + 1}**")
            df = pd.DataFrame({"nivel_nominal": curve.levels_nominal, "respuesta": curve.responses})
            df_edit = st.data_editor(df, key=f"curve_{compound.nombre}_{i}", num_rows="fixed")
            curve.levels_nominal = df_edit["nivel_nominal"].tolist()
            curve.responses = df_edit["respuesta"].tolist()
            curve.retention_time_min = st.number_input(
                f"Tiempo de retención curva {i + 1} (min)", 0.0, key=f"rt_{compound.nombre}_{i}",
                value=curve.retention_time_min or 0.0,
            )

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
                    label=label, nominal=getattr(compound, nominal_attr),
                    values=[[0.0] * project.design.replicas_por_grupo for _ in range(project.design.n_grupos)],
                )
                compound.replicate_levels.append(existing)
            existing.nominal = getattr(compound, nominal_attr)
            st.markdown(f"**{label}** (nominal = {existing.nominal})")
            cols_labels = [f"Rep {j+1}" for j in range(project.design.replicas_por_grupo)]
            df = pd.DataFrame(existing.values, columns=cols_labels, index=grupo_labels)
            df_edit = st.data_editor(df, key=f"level_{compound.nombre}_{label}")
            existing.values = df_edit.values.tolist()

    # --- Muestras ---
    with tabs[2]:
        st.caption(
            "Muestras de matriz (blanco de matriz, y matriz fortificada) usadas para evaluar precisión "
            "y veracidad en condiciones reales. Agrega una fila por cada muestra/nivel adicional que "
            "quieras verificar."
        )
        sample_labels = [r.label for r in compound.replicate_levels if r.label not in ("LC", "LS")]
        new_label = st.text_input("Nombre de nueva muestra/nivel (p.ej. 'Matriz SUP + LC')", key=f"newlbl_{compound.nombre}")
        new_nominal = st.number_input("Valor nominal esperado (0 si es blanco sin adición)", 0.0, key=f"newnom_{compound.nombre}")
        if st.button("Agregar muestra/nivel", key=f"addlvl_{compound.nombre}") and new_label:
            compound.replicate_levels.append(
                ReplicateLevel(
                    label=new_label, nominal=new_nominal,
                    values=[[0.0] * project.design.replicas_por_grupo for _ in range(project.design.n_grupos)],
                )
            )
            st.rerun()

        for lvl in compound.replicate_levels:
            if lvl.label in ("LC", "LS"):
                continue
            st.markdown(f"**{lvl.label}** (nominal = {lvl.nominal})")
            cols_labels = [f"Rep {j+1}" for j in range(project.design.replicas_por_grupo)]
            df = pd.DataFrame(lvl.values, columns=cols_labels, index=grupo_labels)
            df_edit = st.data_editor(df, key=f"sample_{compound.nombre}_{lvl.label}")
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
        st.caption(
            "Desglose de la preparación del patrón usado para este compuesto: material de referencia "
            "(certificado) + pasos de dilución (pipeteo, aforo). Esto alimenta el módulo de incertidumbre."
        )
        cert_options = ["(sin certificado disponible)"] + [
            f"{c.proveedor} | {c.numero_parte} | {c.numero_lote}" for c in project.certificates
        ]
        sel_cert = st.selectbox("Certificado de MRC a usar", cert_options, key=f"selcert_{compound.nombre}")

        rm = ReferenceMaterialCert(nombre=compound.nombre)
        if sel_cert != "(sin certificado disponible)":
            idx = cert_options.index(sel_cert) - 1
            cert = project.certificates[idx]
            analito_names = [a.nombre_compuesto for a in cert.analitos]
            sel_analito = st.selectbox("Analito dentro del certificado", analito_names, key=f"selan_{compound.nombre}")
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
            rm.concentracion = st.number_input("Concentración estimada", 0.0, key=f"rmconc_{compound.nombre}")
            rm.incertidumbre_certificado = st.number_input(
                "Mejor estimación de U disponible (hoja técnica, etc.)", 0.0, key=f"rmU_{compound.nombre}"
            )

        st.markdown("**Pasos de dilución / preparación**")
        n_steps = st.number_input("Número de pasos volumétricos", 0, 10,
                                   len(compound.standard_preparation.steps) if compound.standard_preparation else 2,
                                   key=f"nsteps_{compound.nombre}")
        steps = []
        for i in range(int(n_steps)):
            with st.container(border=True):
                st.write(f"Paso {i+1}")
                c1, c2, c3 = st.columns(3)
                with c1:
                    desc = st.text_input("Descripción", key=f"stepdesc_{compound.nombre}_{i}")
                    vol = st.number_input("Volumen nominal (mL)", 0.0, key=f"stepvol_{compound.nombre}_{i}")
                    instr = st.text_input("Instrumento", key=f"stepinstr_{compound.nombre}_{i}")
                with c2:
                    tiene_cal = st.checkbox("Tiene certificado de calibración", key=f"stepcal_{compound.nombre}_{i}")
                    u_cert = st.number_input("U del certificado (mL)", 0.0, key=f"stepUcert_{compound.nombre}_{i}") if tiene_cal else None
                    k_cert = st.number_input("k del certificado", 1.0, 3.0, 2.0, key=f"stepk_{compound.nombre}_{i}") if tiene_cal else 2.0
                    tol = None if tiene_cal else st.number_input(
                        "Tolerancia de fabricante/clase (mL, semi-intervalo)", 0.0, key=f"steptol_{compound.nombre}_{i}"
                    )
                with c3:
                    sd_rep = st.number_input("SD de repetibilidad (mL, opcional)", 0.0, key=f"stepsd_{compound.nombre}_{i}")
                    incl_temp = st.checkbox("Incluir efecto de temperatura", value=True, key=f"steptemp_{compound.nombre}_{i}")
                    rango_t = st.number_input("Rango de temperatura ±°C", 0.0, 10.0, 3.0, key=f"stepdt_{compound.nombre}_{i}")
                steps.append(VolumetricStep(
                    descripcion=desc, volumen_nominal=vol or 1.0, instrumento=instr,
                    tiene_certificado_calibracion=tiene_cal, incertidumbre_certificado=u_cert, k_certificado=k_cert,
                    tolerancia_fabricante=tol, sd_repetibilidad=sd_rep or None,
                    incluir_efecto_temperatura=incl_temp, rango_temperatura=rango_t,
                ))
        compound.standard_preparation = StandardPreparation(reference_material=rm, steps=steps)

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

        # --- Linealidad ---
        all_levels, all_responses = [], []
        for curve in compound.calibration_curves:
            all_levels += curve.levels_nominal
            all_responses += curve.responses
        if all_levels and any(all_responses):
            try:
                lin = S.linearity(all_levels, all_responses, crit.r_min)
                c1, c2, c3 = st.columns(3)
                c1.metric("Pendiente", f"{lin.slope:.4f}")
                c2.metric("Intercepto", f"{lin.intercept:.4f}")
                c3.metric("r", f"{lin.r:.5f}")
                alert(lin.cumple_r, f"Cumple r ≥ {crit.r_min}", f"NO cumple r ≥ {crit.r_min} (r={lin.r:.5f})")
            except Exception as e:
                st.warning(f"No se pudo calcular linealidad: {e}")

        # --- Grubbs por nivel de calibración (a través de las curvas) ---
        niveles_unicos = sorted(set(all_levels)) if all_levels else []
        with st.expander("Prueba de Grubbs (linealidad, por nivel)"):
            for lvl in niveles_unicos:
                vals = [curve.responses[curve.levels_nominal.index(lvl)] for curve in compound.calibration_curves
                        if lvl in curve.levels_nominal]
                if len(vals) >= 3:
                    g = S.grubbs_test(vals, crit.grubbs_alpha)
                    ok = not (g.hay_atipico_bajo or g.hay_atipico_alto)
                    alert(ok, f"Nivel {lvl}: sin datos atípicos (Gcrit={g.g_critico})",
                          f"Nivel {lvl}: POSIBLE DATO ATÍPICO (Gbajo={g.g_bajo:.2f}, Galto={g.g_alto:.2f}, Gcrit={g.g_critico})")

        # --- LC / LS / muestras: descriptivos + veracidad + precisión ---
        for lvl in compound.replicate_levels:
            flat = [v for day in lvl.values for v in day]
            if not any(flat):
                continue
            st.markdown(f"**{lvl.label}**")
            desc = S.descriptive_stats(flat)
            cols = st.columns(4)
            cols[0].metric("n", desc.n)
            cols[1].metric("Media", f"{desc.mean:.5f}")
            cols[2].metric("SD", f"{desc.sd:.5f}")
            cols[3].metric("CV%", f"{desc.cv_percent:.2f}" if desc.cv_percent is not None else "-")
            if desc.cv_percent is not None:
                alert(desc.cv_percent <= crit.cv_max_percent,
                      f"CV% ({desc.cv_percent:.2f}%) dentro del criterio (≤{crit.cv_max_percent}%)",
                      f"CV% ({desc.cv_percent:.2f}%) EXCEDE el criterio (≤{crit.cv_max_percent}%)")

            if lvl.nominal:
                tr = S.trueness_stats(flat, lvl.nominal, crit.t_alpha)
                cols2 = st.columns(4)
                cols2[0].metric("Error relativo %", f"{tr.error_rel_percent:.2f}")
                cols2[1].metric("Recuperación %", f"{tr.recovery_percent:.2f}")
                cols2[2].metric("t calculado", f"{tr.t_calculado:.3f}")
                cols2[3].metric("t tabulado", f"{tr.t_tabulado:.3f}")
                rec_min, rec_max = (crit.recovery_lc_min, crit.recovery_lc_max) if lvl.label == "LC" else (crit.recovery_min, crit.recovery_max)
                ok_rec = rec_min <= tr.recovery_percent <= rec_max
                alert(ok_rec, f"Recuperación dentro de {rec_min}-{rec_max}%",
                      f"Recuperación FUERA de {rec_min}-{rec_max}%")
                alert(tr.t_calculado <= tr.t_tabulado,
                      "t calculado ≤ t tabulado: no hay sesgo significativo",
                      "t calculado > t tabulado: SESGO ESTADÍSTICAMENTE SIGNIFICATIVO")

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

            g = S.grubbs_test(flat, crit.grubbs_alpha)
            ok = not (g.hay_atipico_bajo or g.hay_atipico_alto)
            alert(ok, "Sin datos atípicos (Grubbs)",
                  f"POSIBLE DATO ATÍPICO — Gbajo={g.g_bajo:.2f}, Galto={g.g_alto:.2f}, Gcrit={g.g_critico}")
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
        if compound.standard_preparation is None or not compound.standard_preparation.steps:
            st.warning("Falta configurar la preparación del estándar en la sección 3 (pestaña de incertidumbre).")
            continue

        prep_u = U.standard_preparation_uncertainty(compound.standard_preparation)
        st.write(f"**u relativa de preparación del estándar (uprep):** {prep_u.u_relativa_combinada:.5f}")
        with st.expander("Detalle de la preparación"):
            st.write(f"- u relativa por pureza del MRC: {prep_u.u_relativa_pureza:.5f}")
            st.write(f"- u relativa por concentración certificada del MRC: {prep_u.u_relativa_certificado_mrc:.5f}")
            for i, p in enumerate(prep_u.u_relativa_pasos):
                st.write(f"- Paso {i+1}: u = {p.u_relativa:.5f}  ({p.fuente_calibracion})")

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
            prec = None
            try:
                prec = S.repeatability_intermediate_precision(lvl.values)
            except Exception:
                pass
            u_repeat_rel = (prec.si / (sum(flat) / len(flat))) if prec and sum(flat) else 0.0

            # incertidumbre de la respuesta de la curva (Ec. E3.5)
            all_levels, all_resid = [], []
            for curve in compound.calibration_curves:
                if not curve.levels_nominal:
                    continue
                lin = S.linearity(curve.levels_nominal, curve.responses, project.criteria.r_min)
                res_y = S.residuals(curve.levels_nominal, curve.responses, lin.slope, lin.intercept)
                res_x = [r / lin.slope for r in res_y]
                all_levels += curve.levels_nominal
                all_resid += res_x
            try:
                u_cal_abs = U.calibration_response_uncertainty(all_levels, all_resid, nominal)
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
            st.dataframe(df, use_container_width=True)

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
    st.caption("Genera el Excel de verificación (con alertas visuales) y el informe PDF unificado.")

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
