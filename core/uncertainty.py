"""
Motor de cálculo de incertidumbre de medición, conforme a la Guía
EURACHEM/CITAC CG4 "Cuantificación de la Incertidumbre en Medidas
Analíticas" (QUAM:2012.P1-ES).

Replica y generaliza (a cualquier técnica/compuesto) la metodología ya
validada por el laboratorio en el formato LA-F-210:

  1. Preparación del estándar (Apéndice A1: pipeteo + aforo, cada uno con
     su componente de calibración/tolerancia, repetibilidad y efecto de
     temperatura), combinados por raíz de suma de cuadrados.
  2. Respuesta de la curva de calibración (Apéndice E.4, Ec. E3.5).
  3. Incertidumbre del volumen de muestra (mismo tratamiento que 1).
  4. Repetibilidad del método (tomada de la precisión intermedia/
     repetibilidad calculada en el módulo de verificación).
  5. Combinación de las 4 fuentes por ley de propagación (Cap. 8.2) y
     expansión con factor de cobertura k (Cap. 8.3).
  6. Modelo de incertidumbre dependiente del nivel de analito
     u(x) = sqrt(s0^2 + (x*s1)^2)  (Apéndice E.5, Ec. [1]).

NOTA IMPORTANTE (revisar con el responsable metrológico del laboratorio):
La hoja LA-F-210 original divide la desviación estándar de repetibilidad
de cada instrumento volumétrico (tomada de una caracterización interna de
10 réplicas) entre sqrt(10). Según el GUM, eso solo es correcto si el uso
de rutina PROMEDIA 10 repeticiones de esa operación volumétrica; si el
analista hace una única pipeteada/aforo por preparación (caso más común),
la incertidumbre de repetibilidad a aplicar es la desviación estándar
directa (sin dividir). Aquí se deja como parámetro configurable
`n_operaciones_promediadas` (por defecto 1 = no se divide) para que el
laboratorio decida conscientemente cuál aplica a su procedimiento real.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import VolumetricStep, StandardPreparation, Compound
from .stats import linearity


def combine_rss(components: list[float]) -> float:
    """Combinación por raíz de suma de cuadrados (fuentes no correlacionadas),
    Cap. 8.2 QUAM."""
    return math.sqrt(sum(c * c for c in components))


# ---------------------------------------------------------------------------
# 1) Incertidumbre de un paso volumétrico (pipeteo / aforo)
# ---------------------------------------------------------------------------
@dataclass
class VolumetricStepUncertainty:
    u_calibracion_o_tolerancia: float   # mL
    u_repetibilidad: float              # mL
    u_temperatura: float                # mL
    u_combinada_abs: float              # mL
    u_relativa: float                   # adimensional (u/V)
    fuente_calibracion: str             # texto para trazabilidad en el informe


def volumetric_step_uncertainty(
    step: VolumetricStep, n_operaciones_promediadas: int = 1
) -> VolumetricStepUncertainty:
    # --- componente de calibración/tolerancia (Tipo B normal o rectangular) ---
    if step.tiene_certificado_calibracion and step.incertidumbre_certificado:
        u_cal = step.incertidumbre_certificado / step.k_certificado
        fuente = f"Certificado de calibración ({step.instrumento}), U/k={step.k_certificado}"
    elif step.tolerancia_fabricante:
        # QUAM Apéndice G: tolerancia de fabricante/clase -> distribución rectangular
        u_cal = step.tolerancia_fabricante / math.sqrt(3)
        fuente = (
            f"Sin certificado disponible: tolerancia de fabricante/clase "
            f"{step.clase_tolerancia or ''} = ±{step.tolerancia_fabricante} mL "
            f"(rectangular, QUAM Apéndice G)"
        )
    else:
        u_cal = 0.0
        fuente = "Sin dato de calibración/tolerancia (revisar)"

    # --- componente de repetibilidad (Tipo A) ---
    if step.sd_repetibilidad:
        u_rep = step.sd_repetibilidad / math.sqrt(max(n_operaciones_promediadas, 1))
    else:
        u_rep = 0.0

    # --- componente de temperatura (Tipo B rectangular) ---
    if step.incluir_efecto_temperatura:
        u_temp = (
            step.coef_expansion_agua * step.rango_temperatura * step.volumen_nominal
        ) / math.sqrt(3)
    else:
        u_temp = 0.0

    u_abs = combine_rss([u_cal, u_rep, u_temp])
    u_rel = u_abs / step.volumen_nominal if step.volumen_nominal else 0.0
    return VolumetricStepUncertainty(u_cal, u_rep, u_temp, u_abs, u_rel, fuente)


# ---------------------------------------------------------------------------
# 2) Incertidumbre de preparación del estándar (MRC + pasos de dilución)
# ---------------------------------------------------------------------------
@dataclass
class StandardPrepUncertainty:
    u_relativa_pureza: float
    u_relativa_certificado_mrc: float
    u_relativa_pasos: list[VolumetricStepUncertainty]
    u_relativa_combinada: float


def standard_preparation_uncertainty_at(prep: StandardPreparation, target_concentration: float) -> StandardPrepUncertainty:
    """Incertidumbre de preparación del estándar EN EL NIVEL de concentración
    que corresponde (p.ej. LC o LS pueden diluirse con volúmenes distintos —
    Tabla 2, LA-P-343/LA-P-340 — así que cada uno tiene su propia u_prep).
    Se usa el DilutionLevel cuya concentración nominal esté más cerca de
    `target_concentration`."""
    if not prep.dilution_levels:
        raise ValueError(
            "Este estándar no tiene niveles de dilución registrados "
            "(ve a la pestaña de preparación y define al menos un nivel: alícuota + aforo)."
        )
    nivel = min(prep.dilution_levels, key=lambda lv: abs(lv.concentracion_nominal - target_concentration))

    rm = prep.reference_material
    # Incertidumbre relativa de la concentración certificada del MRC
    if rm.tiene_certificado and rm.incertidumbre_certificado:
        u_mrc = (rm.incertidumbre_certificado / rm.k_certificado) / rm.concentracion
    else:
        # QUAM Sec. 7.5 / Apéndice G: sin certificado, se sugiere usar la mejor
        # estimación disponible (p.ej. hoja técnica del reactivo) tratada como
        # rectangular; por defecto conservador si no se dispone de nada: 0 (a
        # completar por el analista, nunca se omite silenciosamente en el informe).
        u_mrc = 0.0

    # Incertidumbre relativa de pureza (rectangular, Apéndice A1/G)
    if rm.pureza_percent and rm.incertidumbre_pureza_percent:
        u_pureza = (rm.incertidumbre_pureza_percent / math.sqrt(3)) / rm.pureza_percent
    else:
        u_pureza = 0.0

    pasos_u = [volumetric_step_uncertainty(nivel.alicuota), volumetric_step_uncertainty(nivel.aforo)]
    componentes = [u_mrc, u_pureza] + [p.u_relativa for p in pasos_u]
    u_combinada = combine_rss(componentes)
    return StandardPrepUncertainty(u_pureza, u_mrc, pasos_u, u_combinada)


# ---------------------------------------------------------------------------
# 3) Incertidumbre de la respuesta de la curva de calibración (Apéndice E.4)
# ---------------------------------------------------------------------------
def calibration_response_uncertainty(
    levels_all_points: list[float],
    x_residuals_all_points: list[float],
    x_pred: float,
    p_mediciones_muestra: int = 1,
) -> float:
    """Ec. E3.5 QUAM: var(xpred) = Sx^2 * (1/p + 1/n + (xpred-xbar)^2/Sxx)

    `levels_all_points`: concentración nominal de CADA punto de calibración
        usado (todas las curvas/réplicas, no solo los niveles únicos).
    `x_residuals_all_points`: residual de cada punto anterior, expresado en
        unidades de concentración: (y_obs - y_pred)/pendiente.
    `x_pred`: concentración de la muestra/nivel que se está evaluando.
    `p_mediciones_muestra`: número de lecturas promediadas para obtener el
        resultado de la muestra (1 si es una sola inyección/lectura).
    """
    n = len(levels_all_points)
    if n < 3:
        raise ValueError("Se requieren al menos 3 puntos de calibración para estimar Sx².")
    mean_res = sum(x_residuals_all_points) / n
    s2 = sum((r - mean_res) ** 2 for r in x_residuals_all_points) / (n - 2)
    xbar = sum(levels_all_points) / n
    sxx = sum((x - xbar) ** 2 for x in levels_all_points)
    if sxx == 0:
        raise ValueError("Todos los niveles de calibración son iguales; no se puede estimar Sxx.")
    var_xpred = s2 * (1 / p_mediciones_muestra + 1 / n + ((x_pred - xbar) ** 2) / sxx)
    return math.sqrt(var_xpred)


def calibration_response_uncertainty_averaged_curves(
    curves_levels: list[list[float]], curves_responses: list[list[float]], x_pred: float, p_replicas: int,
) -> float:
    """Variante validada de la Ec. E3.5 (Apéndice E.4 QUAM) para cuando se
    dispone de VARIAS curvas de calibración independientes (p.ej. una por
    día), replicando exactamente la metodología ya usada y validada por el
    laboratorio en su hoja de estimación de incertidumbre (LA-F-210):

      1. Se ajusta cada curva POR SEPARADO (una pendiente/intercepto por
         curva) — no se agrupan los puntos crudos en una sola regresión.
      2. Se promedian las pendientes y los interceptos de las curvas.
      3. Se calcula la respuesta promedio en cada nivel (entre curvas).
      4. Se recalcula la concentración de cada nivel usando la pendiente/
         intercepto PROMEDIO aplicados a la respuesta PROMEDIO de ese nivel,
         y su residual frente al nivel nominal.
      5. Sx² = varianza muestral de esos residuales (uno por nivel, no uno
         por punto crudo) — esto reduce correctamente el ruido entre curvas
         antes de estimar la incertidumbre, en vez de inflarlo agrupando
         puntos que no son observaciones independientes de una única recta.
      6. Se aplica Ec. E3.5 con n = número total de puntos crudos (todas las
         curvas) y p = réplicas de la muestra/resultado reportado (p.ej. el
         diseño día×analista del proyecto), tal como especifica la guía.

    Esto reemplaza el "pooling" ingenuo de todos los puntos crudos en una
    sola regresión (que mezcla incorrectamente la variabilidad entre curvas
    con el ruido de una única recta y sobreestima drásticamente la
    incertidumbre, sobre todo lejos del centro del rango).

    Requiere >=2 curvas con el mismo conjunto de niveles.
    """
    n_curvas = len(curves_levels)
    if n_curvas < 2:
        raise ValueError("Se requieren al menos 2 curvas de calibración independientes para este método.")
    n_niveles = len(curves_levels[0])
    levels = curves_levels[0]

    slopes, intercepts = [], []
    for lv, resp in zip(curves_levels, curves_responses):
        lin = linearity(lv, resp, r_min=0.0)
        slopes.append(lin.slope)
        intercepts.append(lin.intercept)
    slope_avg = sum(slopes) / n_curvas
    intercept_avg = sum(intercepts) / n_curvas

    y_avg_por_nivel = [
        sum(curves_responses[c][j] for c in range(n_curvas)) / n_curvas
        for j in range(n_niveles)
    ]
    x_recalc = [(y - intercept_avg) / slope_avg for y in y_avg_por_nivel]
    residuos = [xr - xn for xr, xn in zip(x_recalc, levels)]

    n_res = len(residuos)
    if n_res < 3:
        raise ValueError("Se requieren al menos 3 niveles de calibración para estimar Sx².")
    mean_res = sum(residuos) / n_res
    s2 = sum((r - mean_res) ** 2 for r in residuos) / (n_res - 1)

    n_total = n_curvas * n_niveles
    xbar = sum(levels) / n_niveles
    sxx_pooled = n_curvas * sum((x - xbar) ** 2 for x in levels)
    if sxx_pooled == 0:
        raise ValueError("Todos los niveles de calibración son iguales; no se puede estimar Sxx.")

    var_xpred = s2 * (1 / p_replicas + 1 / n_total + ((x_pred - xbar) ** 2) / sxx_pooled)
    return math.sqrt(var_xpred)


# ---------------------------------------------------------------------------
# 5) Combinación total + expansión (por nivel: LC, LS, o cualquier concentración)
# ---------------------------------------------------------------------------
@dataclass
class UncertaintyBudgetLevel:
    nivel_label: str
    concentracion: float
    u_calibracion_relativa: float
    u_preparacion_relativa: float
    u_volumen_muestra_relativa: float
    u_repetibilidad_relativa: float
    uc_relativa: float
    uc_absoluta: float
    u_expandida: float
    u_relativa_expandida_percent: float
    k: float


def combine_budget(
    nivel_label: str,
    concentracion: float,
    u_calibracion_relativa: float,
    u_preparacion_relativa: float,
    u_volumen_muestra_relativa: float,
    u_repetibilidad_relativa: float,
    k: float = 2.0,
) -> UncertaintyBudgetLevel:
    uc_rel = combine_rss(
        [u_calibracion_relativa, u_preparacion_relativa, u_volumen_muestra_relativa, u_repetibilidad_relativa]
    )
    uc_abs = uc_rel * concentracion
    u_exp = k * uc_abs
    u_rel_exp_pct = (u_exp / concentracion) * 100 if concentracion else float("nan")
    return UncertaintyBudgetLevel(
        nivel_label, concentracion,
        u_calibracion_relativa, u_preparacion_relativa,
        u_volumen_muestra_relativa, u_repetibilidad_relativa,
        uc_rel, uc_abs, u_exp, u_rel_exp_pct, k,
    )


# ---------------------------------------------------------------------------
# 6) Modelo dependiente del nivel de analito (Apéndice E.5)
# ---------------------------------------------------------------------------
@dataclass
class LevelDependentModel:
    s0: float
    s1: float
    n_puntos_calibracion: int
    metodo: str   # "2 puntos (cierre algebraico)" o "regresión (n>=3 niveles)"

    def u(self, x: float) -> float:
        return math.sqrt(self.s0 ** 2 + (x * self.s1) ** 2)


def fit_level_dependent_model(levels: list[UncertaintyBudgetLevel]) -> LevelDependentModel:
    """Ajusta u(x) = sqrt(s0^2 + (x*s1)^2) a partir de >=2 niveles con su uc
    absoluta ya calculada (LC, LS, y opcionalmente niveles intermedios).

    Con exactamente 2 niveles se resuelve el sistema algebraicamente (como
    hace hoy LA-F-210). Con >=3 niveles se sigue el procedimiento recomendado
    por la guía (E.5.5.2): regresión lineal de u(xi)^2 frente a xi^2, donde
    s1^2 = pendiente y s0^2 = intercepto.
    """
    pts = [(lvl.concentracion, lvl.uc_absoluta) for lvl in levels]
    n = len(pts)
    if n < 2:
        raise ValueError("Se requieren al menos 2 niveles (p.ej. LC y LS) para el modelo dependiente del nivel.")
    if n == 2:
        (x1, u1), (x2, u2) = pts
        s1_2 = (u2 ** 2 - u1 ** 2) / (x2 ** 2 - x1 ** 2)
        s0_2 = max(u1 ** 2 - (x1 ** 2) * s1_2, 0.0)
        s1 = math.sqrt(max(s1_2, 0.0))
        s0 = math.sqrt(s0_2)
        return LevelDependentModel(s0, s1, n, "2 puntos (cierre algebraico, LC/LS)")

    # Regresión lineal de y=u(xi)^2 sobre x=xi^2 -> pendiente=s1^2, intercepto=s0^2
    xs = [x * x for x, _u in pts]
    ys = [u * u for _x, u in pts]
    n_ = len(xs)
    xbar = sum(xs) / n_
    ybar = sum(ys) / n_
    sxx = sum((x - xbar) ** 2 for x in xs)
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = ybar - slope * xbar
    s1 = math.sqrt(max(slope, 0.0))
    s0 = math.sqrt(max(intercept, 0.0))
    return LevelDependentModel(s0, s1, n, "regresión lineal u(xi)² vs xi² (Apéndice E.5.5.2, n>=3)")
