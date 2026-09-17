"""
Exportación a Excel del resultado de verificación, con alertas visuales
(relleno verde/rojo según cumplimiento de los criterios de aceptación),
en un formato equivalente al LA-F-319 del laboratorio pero generado
automáticamente para cualquier técnica/compuesto.
"""
from __future__ import annotations

import os

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from core.models import VerificationProject
from core import stats as S
from core import uncertainty as U

GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)


def _write_header(ws, row, headers, col_start=1):
    for i, h in enumerate(headers):
        cell = ws.cell(row=row, column=col_start + i, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _autosize(ws, n_cols):
    for i in range(1, n_cols + 1):
        col = get_column_letter(i)
        maxlen = max((len(str(c.value)) for c in ws[col] if c.value is not None), default=8)
        ws.column_dimensions[col].width = min(max(maxlen + 2, 10), 45)


def build_verification_excel(project: VerificationProject, out_path: str = "data/Verificacion.xlsx") -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    crit = project.criteria

    for compound in project.compounds:
        ws = wb.create_sheet(compound.nombre[:31])
        row = 1
        ws.cell(row=row, column=1, value=f"VERIFICACIÓN — {compound.nombre}").font = Font(bold=True, size=14)
        row += 1
        ws.cell(row=row, column=1, value=f"Ensayo: {project.method.ensayo}  |  Técnica: {project.method.tecnica}  |  "
                                          f"Matriz: {project.method.matriz}")
        row += 2

        # --- Linealidad ---
        ws.cell(row=row, column=1, value="LINEALIDAD").font = BOLD
        row += 1
        _write_header(ws, row, ["Curva", "Pendiente", "Intercepto", "r", "r²", f"Cumple r≥{crit.r_min}"])
        row += 1
        for i, curve in enumerate(compound.calibration_curves):
            if not curve.levels_nominal or not any(curve.responses):
                continue
            try:
                lin = S.linearity(curve.levels_nominal, curve.responses, crit.r_min)
            except Exception:
                continue
            ws.cell(row=row, column=1, value=f"Curva {i + 1}")
            ws.cell(row=row, column=2, value=round(lin.slope, 5))
            ws.cell(row=row, column=3, value=round(lin.intercept, 5))
            ws.cell(row=row, column=4, value=round(lin.r, 5))
            ws.cell(row=row, column=5, value=round(lin.r2, 5))
            cell = ws.cell(row=row, column=6, value="CUMPLE" if lin.cumple_r else "NO CUMPLE")
            cell.fill = GREEN if lin.cumple_r else RED
            row += 1
        row += 1

        # --- Niveles (LC, LS, muestras) ---
        ws.cell(row=row, column=1, value="PRECISIÓN Y VERACIDAD POR NIVEL").font = BOLD
        row += 1
        _write_header(row=row, ws=ws, headers=[
            "Nivel", "n", "Media", "SD", "CV%", f"CV%≤{crit.cv_max_percent}",
            "Error rel.%", "Recuperación%", "Cumple recuperación",
            "t calc", "t tab", "Sesgo signif.", "Sr", "SI", "%Sr", "%SI",
        ])
        row += 1
        for lvl in compound.replicate_levels:
            flat = [v for day in lvl.values for v in day]
            if not any(flat):
                continue
            desc = S.descriptive_stats(flat)
            ws.cell(row=row, column=1, value=lvl.label)
            ws.cell(row=row, column=2, value=desc.n)
            ws.cell(row=row, column=3, value=round(desc.mean, 5))
            ws.cell(row=row, column=4, value=round(desc.sd, 5))
            cv_ok = desc.cv_percent is not None and desc.cv_percent <= crit.cv_max_percent
            if desc.cv_percent is not None:
                ws.cell(row=row, column=5, value=round(desc.cv_percent, 3))
                c = ws.cell(row=row, column=6, value="CUMPLE" if cv_ok else "NO CUMPLE")
                c.fill = GREEN if cv_ok else RED
            if lvl.nominal:
                tr = S.trueness_stats(flat, lvl.nominal, crit.t_alpha)
                rec_min, rec_max = (crit.recovery_lc_min, crit.recovery_lc_max) if lvl.label == "LC" else (crit.recovery_min, crit.recovery_max)
                rec_ok = rec_min <= tr.recovery_percent <= rec_max
                sesgo_ok = tr.t_calculado <= tr.t_tabulado
                ws.cell(row=row, column=7, value=round(tr.error_rel_percent, 3))
                ws.cell(row=row, column=8, value=round(tr.recovery_percent, 3))
                c2 = ws.cell(row=row, column=9, value="CUMPLE" if rec_ok else "NO CUMPLE")
                c2.fill = GREEN if rec_ok else RED
                ws.cell(row=row, column=10, value=round(tr.t_calculado, 3))
                ws.cell(row=row, column=11, value=round(tr.t_tabulado, 3))
                c3 = ws.cell(row=row, column=12, value="NO" if sesgo_ok else "SÍ (revisar)")
                c3.fill = GREEN if sesgo_ok else RED
            if len(lvl.values) >= 2 and all(len(d) == len(lvl.values[0]) for d in lvl.values):
                try:
                    prec = S.repeatability_intermediate_precision(lvl.values)
                    ws.cell(row=row, column=13, value=round(prec.sr, 5))
                    ws.cell(row=row, column=14, value=round(prec.si, 5))
                    ws.cell(row=row, column=15, value=round(prec.cv_sr_percent, 3))
                    ws.cell(row=row, column=16, value=round(prec.cv_si_percent, 3))
                except Exception:
                    pass
            row += 1
        row += 1

        # --- Incertidumbre ---
        if compound.standard_preparation and compound.standard_preparation.steps:
            ws.cell(row=row, column=1, value="INCERTIDUMBRE DE MEDICIÓN (QUAM:2012 CG4)").font = BOLD
            row += 1
            _write_header(ws, row, ["Nivel", "Concentración", "u cal", "u prep", "u vol.muestra",
                                     "u repetibilidad", "uc", "U expandida", "U relativa %", "Resultado"])
            row += 1
            prep_u = U.standard_preparation_uncertainty(compound.standard_preparation)
            u_vm = U.volumetric_step_uncertainty(compound.volumen_muestra) if compound.volumen_muestra else None
            u_vm_rel = u_vm.u_relativa if u_vm else 0.0
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
                all_levels, all_resid = [], []
                for curve in compound.calibration_curves:
                    if not curve.levels_nominal:
                        continue
                    try:
                        lin = S.linearity(curve.levels_nominal, curve.responses, crit.r_min)
                        res_y = S.residuals(curve.levels_nominal, curve.responses, lin.slope, lin.intercept)
                        all_levels += curve.levels_nominal
                        all_resid += [r / lin.slope for r in res_y]
                    except Exception:
                        continue
                try:
                    u_cal_abs = U.calibration_response_uncertainty(all_levels, all_resid, nominal)
                    u_cal_rel = u_cal_abs / nominal if nominal else 0.0
                except Exception:
                    u_cal_rel = 0.0
                budget = U.combine_budget(label, nominal, u_cal_rel, prep_u.u_relativa_combinada,
                                           u_vm_rel, u_rep_rel, k=crit.k_coverage)
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=budget.concentracion)
                ws.cell(row=row, column=3, value=round(budget.u_calibracion_relativa, 5))
                ws.cell(row=row, column=4, value=round(budget.u_preparacion_relativa, 5))
                ws.cell(row=row, column=5, value=round(budget.u_volumen_muestra_relativa, 5))
                ws.cell(row=row, column=6, value=round(budget.u_repetibilidad_relativa, 5))
                ws.cell(row=row, column=7, value=round(budget.uc_relativa, 5))
                ws.cell(row=row, column=8, value=round(budget.u_expandida, 5))
                ws.cell(row=row, column=9, value=round(budget.u_relativa_expandida_percent, 2))
                ws.cell(row=row, column=10, value=f"({budget.concentracion} ± {round(budget.u_expandida,5)}) {project.method.unidad}")
                row += 1

        _autosize(ws, 16)

    wb.save(out_path)
    return out_path
