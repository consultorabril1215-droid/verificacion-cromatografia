"""
Informe PDF unificado de Verificación de Método + Estimación de Incertidumbre,
inspirado en la estructura del formato LA-P-320 del laboratorio, pero
condensado: pensado para que un auditor externo revise rápidamente lo
esencial (objetivo, alcance, resultados por característica, declaración de
conformidad), sin la densidad de un informe narrativo completo.
"""
from __future__ import annotations

import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

from core.models import VerificationProject
from core import stats as S
from core import uncertainty as U

GREEN = colors.HexColor("#C6EFCE")
RED = colors.HexColor("#FFC7CE")
HEADER_BLUE = colors.HexColor("#1F4E78")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H1", parent=ss["Heading1"], textColor=HEADER_BLUE, spaceAfter=8))
    ss.add(ParagraphStyle("H2", parent=ss["Heading2"], textColor=HEADER_BLUE, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["BodyText"], fontSize=9.5, leading=13))
    return ss


def _table(data, col_widths=None, highlight_rows=None):
    highlight_rows = highlight_rows or {}
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]
    for r, ok in highlight_rows.items():
        style.append(("BACKGROUND", (0, r), (-1, r), GREEN if ok else RED))
    t.setStyle(TableStyle(style))
    return t


def build_pdf_report(project: VerificationProject, out_path: str = "data/Informe_Verificacion.pdf") -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ss = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=letter, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                             leftMargin=1.8 * cm, rightMargin=1.8 * cm)
    story = []
    crit = project.criteria
    m = project.method

    # --- Portada / encabezado ---
    story.append(Paragraph("INFORME DE VERIFICACIÓN DE MÉTODO Y ESTIMACIÓN DE INCERTIDUMBRE", ss["H1"]))
    story.append(Paragraph(
        f"Ensayo: <b>{m.ensayo}</b> &nbsp;|&nbsp; Técnica: <b>{m.tecnica}</b> &nbsp;|&nbsp; "
        f"Matriz: <b>{m.matriz}</b>", ss["Body"]))
    story.append(Paragraph(
        f"Método de referencia: {m.metodo_referencia} &nbsp;|&nbsp; Procedimiento interno: {m.procedimiento_interno}",
        ss["Body"]))
    story.append(Paragraph(
        f"Código: <b>{m.codigo_formato}</b> &nbsp;|&nbsp; Versión: <b>{m.version}</b> &nbsp;|&nbsp; "
        f"Fecha: <b>{m.fecha.isoformat()}</b>", ss["Body"]))
    story.append(Paragraph(f"Laboratorio: {m.laboratorio} &nbsp;|&nbsp; Analista(s): "
                            f"{', '.join(m.analistas)}", ss["Body"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("1. Objetivo", ss["H2"]))
    story.append(Paragraph(
        f"Verificar que el laboratorio genera resultados confiables para {m.ensayo} mediante {m.tecnica} "
        f"en la matriz {m.matriz}, evaluando linealidad, límite de cuantificación (LC), límite superior (LS), "
        f"rango de trabajo, precisión, veracidad e incertidumbre de medición.", ss["Body"]))

    story.append(Paragraph("2. Alcance", ss["H2"]))
    story.append(Paragraph(
        f"Los ensayos de verificación se llevaron a cabo utilizando estándares y muestras de matriz "
        f"{m.matriz}. Al emplearse un método normalizado ({m.metodo_referencia}), se evaluaron: linealidad, "
        f"límite de cuantificación (LC), límite superior (LS), precisión (repetibilidad y precisión "
        f"intermedia), veracidad (sesgo/recuperación) e incertidumbre de medición, conforme a la Guía "
        f"Eurachem \"La Adecuación al Uso de los Métodos Analíticos\" (2ª ed.) y la Guía EURACHEM/CITAC CG4 "
        f"\"Cuantificación de la Incertidumbre en Medidas Analíticas\" (QUAM:2012).", ss["Body"]))

    story.append(Paragraph("3. Recursos utilizados", ss["H2"]))
    story.append(Paragraph(
        f"Todos los ensayos se realizaron siguiendo el procedimiento {m.procedimiento_interno}.", ss["Body"]))
    if m.equipos:
        story.append(Paragraph("Instrumentos de medición", ss["Body"]))
        eq_rows = [["Equipo", "Marca", "Código interno"]] + [
            [e.get("equipo", ""), e.get("marca", ""), e.get("codigo_interno", "")] for e in m.equipos
        ]
        story.append(_table(eq_rows, col_widths=[6 * cm, 4 * cm, 4 * cm]))
        story.append(Spacer(1, 6))
    if project.certificates:
        story.append(Paragraph("Materiales de referencia (MRC) certificados", ss["Body"]))
        cert_rows = [["Proveedor", "Parte/Lote", "Compuestos", "Vence"]]
        for c in project.certificates:
            compuestos = ", ".join(a.nombre_compuesto for a in c.analitos)
            cert_rows.append([c.proveedor, f"{c.numero_parte}/{c.numero_lote}", compuestos, c.fecha_expiracion])
        story.append(_table(cert_rows, col_widths=[3.5 * cm, 3 * cm, 5.5 * cm, 2 * cm]))
        story.append(Spacer(1, 6))

    story.append(Paragraph("4. Criterios de aceptación aplicados", ss["H2"]))
    crit_data = [
        ["Característica", "Criterio"],
        ["Linealidad (r)", f"≥ {crit.r_min}"],
        ["Coeficiente de variación (CV%)", f"≤ {crit.cv_max_percent}%"],
        ["Recuperación en LC", f"{crit.recovery_lc_min}% – {crit.recovery_lc_max}%"],
        ["Recuperación en LS / muestras", f"{crit.recovery_min}% – {crit.recovery_max}%"],
        ["Prueba de Grubbs (datos atípicos)", f"α = {crit.grubbs_alpha}"],
        ["Sesgo (prueba t)", f"α = {crit.t_alpha} (dos colas)"],
        ["Incertidumbre expandida", f"k = {crit.k_coverage} (~{crit.confidence_level_percent:.0f}% confianza)"],
    ]
    story.append(_table(crit_data, col_widths=[8 * cm, 7 * cm]))
    story.append(PageBreak())

    story.append(Paragraph("5. Resultados", ss["H1"]))
    story.append(Paragraph(
        "A continuación se exponen e interpretan los resultados obtenidos en los ensayos de verificación "
        "del método, por compuesto.", ss["Body"]))
    story.append(Spacer(1, 6))

    resumen_rows = [["Compuesto", "r", "LC: Recup.%", "LC: CV%", "LS: Recup.%", "LS: CV%",
                     "U(LC) rel.%", "U(LS) rel.%", "Conclusión"]]
    resumen_highlight = {}

    for compound in project.compounds:
        story.append(Paragraph(compound.nombre, ss["H2"]))

        # Linealidad (modelo agrupado, Simple o Ponderada según ISO 8466-1)
        r_val = None
        modelo_val = None
        all_lv_p = [c.levels_nominal for c in compound.calibration_curves if any(c.responses)]
        all_rs_p = [c.responses for c in compound.calibration_curves if any(c.responses)]
        cal_p = None
        if len(all_lv_p) >= 2 and all(len(l) >= 4 for l in all_lv_p):
            try:
                cal_p = S.analyze_calibration(all_lv_p, all_rs_p, crit.r_min)
                r_val = cal_p.r
                modelo_val = cal_p.modelo_usado
            except Exception:
                pass

        row_summary = {"compuesto": compound.nombre, "r": r_val, "modelo": modelo_val}
        level_data = [["Nivel", "n", "Media", "CV%", "Recuperación%", "Cumple"]]
        level_highlight = {}
        u_summary = {}

        for lvl in compound.replicate_levels:
            flat = [v for day in lvl.values for v in day]
            if not any(flat):
                continue
            desc = S.descriptive_stats(flat)
            recup = None
            ok = True
            if lvl.nominal:
                tr = S.trueness_stats(flat, lvl.nominal, crit.t_alpha)
                recup = tr.recovery_percent
                rec_min, rec_max = (crit.recovery_lc_min, crit.recovery_lc_max) if lvl.label == "LC" else (crit.recovery_min, crit.recovery_max)
                ok = (desc.cv_percent is None or desc.cv_percent <= crit.cv_max_percent) and (rec_min <= recup <= rec_max)
            r_idx = len(level_data)
            level_data.append([
                lvl.label, str(desc.n), f"{desc.mean:.4f}",
                f"{desc.cv_percent:.2f}" if desc.cv_percent is not None else "-",
                f"{recup:.2f}" if recup is not None else "-",
                "SÍ" if ok else "NO",
            ])
            level_highlight[r_idx] = ok
            if lvl.label in ("LC", "LS"):
                row_summary[f"{lvl.label.lower()}_recup"] = recup
                row_summary[f"{lvl.label.lower()}_cv"] = desc.cv_percent

        story.append(_table(level_data, col_widths=[3 * cm, 1.5 * cm, 2.5 * cm, 2 * cm, 3 * cm, 2 * cm],
                             highlight_rows=level_highlight))
        story.append(Spacer(1, 6))

        # Incertidumbre resumida
        if compound.standard_preparation and compound.standard_preparation.steps:
            prep_u = U.standard_preparation_uncertainty(compound.standard_preparation)
            u_vm = U.volumetric_step_uncertainty(compound.volumen_muestra) if compound.volumen_muestra else None
            u_vm_rel = u_vm.u_relativa if u_vm else 0.0
            u_rows = [["Nivel", "Concentración", "U expandida", "U relativa %", "Resultado"]]
            for label, nominal in [("LC", compound.lc_nominal), ("LS", compound.ls_nominal)]:
                lvl = next((r for r in compound.replicate_levels if r.label == label), None)
                if lvl is None:
                    continue
                flat = [v for day in lvl.values for v in day]
                if not any(flat):
                    continue
                try:
                    prec = S.repeatability_intermediate_precision(lvl.values)
                    u_rep_rel = prec.si / (sum(flat) / len(flat))
                except Exception:
                    u_rep_rel = 0.0
                try:
                    if cal_p is None:
                        raise ValueError("Sin modelo de calibración calculado")
                    res_x = [r / cal_p.slope for r in cal_p.residuales]
                    u_cal_abs = U.calibration_response_uncertainty(cal_p.puntos_x, res_x, nominal)
                    u_cal_rel = u_cal_abs / nominal if nominal else 0.0
                except Exception:
                    u_cal_rel = 0.0
                budget = U.combine_budget(label, nominal, u_cal_rel, prep_u.u_relativa_combinada,
                                           u_vm_rel, u_rep_rel, k=crit.k_coverage)
                u_rows.append([
                    label, f"{budget.concentracion} {project.method.unidad}",
                    f"± {budget.u_expandida:.4f}", f"{budget.u_relativa_expandida_percent:.1f}%",
                    f"({budget.concentracion} ± {budget.u_expandida:.4f}) {project.method.unidad}",
                ])
                row_summary[f"u_{label.lower()}"] = budget.u_relativa_expandida_percent
            story.append(Paragraph("Incertidumbre de medición (QUAM:2012 CG4)", ss["Body"]))
            story.append(_table(u_rows, col_widths=[2 * cm, 3 * cm, 2.5 * cm, 2.5 * cm, 4 * cm]))

        conforme = all(v is not False for v in level_highlight.values()) if level_highlight else False
        conclusion = "CONFORME" if all(level_highlight.values()) else "REVISAR"
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Conclusión para {compound.nombre}: {conclusion}</b>", ss["Body"]))
        story.append(Spacer(1, 10))

        r_idx_sum = len(resumen_rows)
        resumen_rows.append([
            compound.nombre,
            f"{row_summary.get('r'):.5f}" if row_summary.get("r") is not None else "-",
            f"{row_summary.get('lc_recup'):.1f}" if row_summary.get("lc_recup") is not None else "-",
            f"{row_summary.get('lc_cv'):.2f}" if row_summary.get("lc_cv") is not None else "-",
            f"{row_summary.get('ls_recup'):.1f}" if row_summary.get("ls_recup") is not None else "-",
            f"{row_summary.get('ls_cv'):.2f}" if row_summary.get("ls_cv") is not None else "-",
            f"{row_summary.get('u_lc'):.1f}" if row_summary.get("u_lc") is not None else "-",
            f"{row_summary.get('u_ls'):.1f}" if row_summary.get("u_ls") is not None else "-",
            conclusion,
        ])
        resumen_highlight[r_idx_sum] = (conclusion == "CONFORME")

    story.append(PageBreak())
    story.append(Paragraph("6. Resumen general y declaración de conformidad", ss["H1"]))
    story.append(_table(resumen_rows, highlight_rows=resumen_highlight))
    story.append(Spacer(1, 10))
    todos_conformes = all(resumen_highlight.values()) if resumen_highlight else False
    veredicto = (
        "El laboratorio DEMUESTRA capacidad para ejecutar el método dentro de los requisitos de desempeño "
        "establecidos, para todos los compuestos evaluados."
        if todos_conformes else
        "Uno o más compuestos NO cumplen la totalidad de los criterios de aceptación establecidos; "
        "revisar el detalle por compuesto antes de declarar conformidad del método."
    )
    story.append(Paragraph(f"<b>{veredicto}</b>", ss["Body"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "Elaboró: ______________________ &nbsp;&nbsp;&nbsp; Revisó: ______________________ &nbsp;&nbsp;&nbsp; "
        "Aprobó: ______________________", ss["Body"]))

    doc.build(story)
    return out_path
