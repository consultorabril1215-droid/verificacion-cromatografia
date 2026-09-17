"""
Motor de cálculo estadístico para la verificación de métodos analíticos,
conforme a la Guía Eurachem "La Adecuación al Uso de los Métodos Analíticos"
(2ª ed., 2016) — capítulo 6.

Todas las funciones son puras (no dependen de Excel ni de la UI) para poder
probarse de forma independiente y para que el resultado sea trazable:
fórmula -> variables -> sustitución -> resultado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats as _stats

from .grubbs_table import grubbs_critical
from .dixon_table import dixon_critical


# ---------------------------------------------------------------------------
# 6.3 / Ref. Rápida 5 — Linealidad de la curva de calibración
# ---------------------------------------------------------------------------
@dataclass
class LinearityResult:
    slope: float
    intercept: float
    r: float
    r2: float
    cumple_r: bool


def linearity(levels: list[float], responses: list[float], r_min: float) -> LinearityResult:
    """Regresión lineal simple señal=f(concentración). Ref. Rápida 5, Eurachem."""
    n = len(levels)
    if n < 2:
        raise ValueError("Se requieren al menos 2 niveles para calcular una recta de calibración.")
    slope, intercept, r, _p, _se = _stats.linregress(levels, responses)
    return LinearityResult(slope=slope, intercept=intercept, r=r, r2=r * r, cumple_r=(r >= r_min))


def residuals(levels: list[float], responses: list[float], slope: float, intercept: float) -> list[float]:
    """Residuales y_obs - y_pred, en unidades de la señal."""
    return [y - (slope * x + intercept) for x, y in zip(levels, responses)]


# ---------------------------------------------------------------------------
# ISO 8466-1:1990 — Decisión del modelo de calibración (homogeneidad de
# varianzas §4.1.2 y linealidad, prueba PG de Mandel §4.1.3), tal como las
# aplica el laboratorio en su hoja de estimación de incertidumbre (LA-F-210).
# Esto complementa la Ref. Rápida 5 de Eurachem (que solo pide inspección
# visual + r) con un criterio estadístico objetivo para decidir si la curva
# debe ajustarse con regresión simple o ponderada.
# ---------------------------------------------------------------------------
@dataclass
class HomogeneityResult:
    s_nivel_bajo: float
    s_nivel_alto: float
    f_calc: float
    f_crit: float
    homogenea: bool
    decision: str


def homogeneity_variance_test(level_replicates: dict[float, list[float]], alpha: float = 0.01) -> HomogeneityResult:
    """ISO 8466-1 §4.1.2: compara la varianza de las réplicas en el nivel más
    bajo y en el más alto de la curva (los niveles se replican una vez por
    cada curva de calibración, p.ej. una vez por día).

    `level_replicates`: {concentración_nivel: [respuesta en cada curva]}
    """
    niveles = sorted(level_replicates.keys())
    nivel_bajo, nivel_alto = niveles[0], niveles[-1]
    vals_bajo = level_replicates[nivel_bajo]
    vals_alto = level_replicates[nivel_alto]
    s_bajo = _sample_sd(vals_bajo)
    s_alto = _sample_sd(vals_alto)
    f_calc = (max(s_bajo, s_alto) / min(s_bajo, s_alto)) ** 2 if min(s_bajo, s_alto) > 0 else float("inf")
    df = len(vals_bajo) - 1
    f_crit = _stats.f.ppf(1 - alpha, df, df)
    homogenea = f_calc <= f_crit
    decision = "Homogénea: regresión simple (sin ponderar) es válida" if homogenea else "NO homogénea: usar regresión PONDERADA"
    return HomogeneityResult(s_bajo, s_alto, f_calc, f_crit, homogenea, decision)


@dataclass
class MandelLinearityResult:
    ds2: float
    pg: float
    f_crit: float
    es_lineal: bool
    decision: str


def mandel_linearity_test(levels: list[float], responses: list[float], alpha: float = 0.01) -> MandelLinearityResult:
    """ISO 8466-1 §4.1.3 (prueba PG de Mandel): compara el ajuste lineal
    contra uno cuadrático. Si el término cuadrático no mejora
    significativamente el ajuste, el modelo lineal es adecuado."""
    n = len(levels)
    if n < 4:
        raise ValueError("Se requieren al menos 4 puntos de calibración para la prueba de Mandel.")
    import numpy as np

    x = np.array(levels, dtype=float)
    y = np.array(responses, dtype=float)

    lin_coefs = np.polyfit(x, y, 1)
    y_pred_lin = np.polyval(lin_coefs, x)
    ss_res_lin = float(np.sum((y - y_pred_lin) ** 2))
    sy2_lin = ss_res_lin / (n - 2)

    quad_coefs = np.polyfit(x, y, 2)
    y_pred_quad = np.polyval(quad_coefs, x)
    ss_res_quad = float(np.sum((y - y_pred_quad) ** 2))
    sy2_quad = ss_res_quad / (n - 3)

    ds2 = (n - 2) * sy2_lin - (n - 3) * sy2_quad
    pg = max(0.0, ds2) / sy2_lin if sy2_lin else 0.0
    f_crit = _stats.f.ppf(1 - alpha, 1, n - 3)
    es_lineal = pg <= f_crit
    decision = "LINEAL: aplica ISO 8466-1 Parte 1" if es_lineal else "NO LINEAL: revisar rango de trabajo o usar ajuste de 2° orden"
    return MandelLinearityResult(ds2, pg, f_crit, es_lineal, decision)


@dataclass
class WeightedLinearityResult:
    slope: float
    intercept: float
    r: float
    r2: float
    cumple_r: bool
    weights: list[float]


def weighted_linear_regression(levels: list[float], responses: list[float], weights: list[float], r_min: float) -> WeightedLinearityResult:
    """Regresión lineal ponderada por mínimos cuadrados (usada cuando la
    prueba de homogeneidad de varianzas indica heterocedasticidad),
    consistente con ISO 8466-1 Parte 2. Pesos recomendados: wi = 1/si²
    (inversa de la varianza de las réplicas en cada nivel)."""
    import numpy as np

    x = np.array(levels, dtype=float)
    y = np.array(responses, dtype=float)
    w = np.array(weights, dtype=float)
    sw = w.sum()
    xw = (w * x).sum() / sw
    yw = (w * y).sum() / sw
    sxxw = (w * (x - xw) ** 2).sum()
    sxyw = (w * (x - xw) * (y - yw)).sum()
    slope = sxyw / sxxw
    intercept = yw - slope * xw
    y_pred = slope * x + intercept
    # r ponderado (coeficiente de correlación ponderado)
    ss_res_w = (w * (y - y_pred) ** 2).sum()
    ss_tot_w = (w * (y - yw) ** 2).sum()
    r2 = 1 - ss_res_w / ss_tot_w if ss_tot_w else 0.0
    r = math.copysign(math.sqrt(abs(r2)), slope)
    return WeightedLinearityResult(slope, intercept, r, r2, r >= r_min, list(weights))


@dataclass
class CalibrationAnalysis:
    homogeneidad: HomogeneityResult
    linealidad_mandel: MandelLinearityResult
    modelo_usado: str                    # "Simple" o "Ponderada"
    slope: float
    intercept: float
    r: float
    r2: float
    cumple_r: bool
    puntos_x: list[float]
    puntos_y: list[float]
    residuales: list[float]              # y_obs - y_pred (unidades de señal)
    x_recalculada: list[float]           # concentración recalculada desde la curva
    error_percent: list[float]           # % error de la concentración recalculada vs. nominal
    dias: list[int]                      # día de origen de cada punto (trazabilidad)
    analistas: list[str]                 # analista de origen de cada punto (trazabilidad)


def analyze_calibration(
    all_curves_levels: list[list[float]], all_curves_responses: list[list[float]], r_min: float,
    dias: list[int] | None = None, analistas: list[str] | None = None,
) -> CalibrationAnalysis:
    """Orquesta el análisis completo de la(s) curva(s) de calibración de un
    compuesto: homogeneidad de varianzas -> linealidad de Mandel -> decide y
    ajusta el modelo (simple o ponderado) -> calcula residuales, concentración
    recalculada y % error para cada punto.

    `all_curves_levels`/`all_curves_responses`: una lista por curva (p.ej. una
    por día), cada una con los niveles/respuestas de esa curva.
    `dias`/`analistas`: opcional, un valor por CURVA (no por punto) para
    trazabilidad — se repite automáticamente para cada punto de esa curva.
    """
    pooled_levels = [x for curve in all_curves_levels for x in curve]
    pooled_responses = [y for curve in all_curves_responses for y in curve]
    pooled_dias = [
        (dias[i] if dias and i < len(dias) else i + 1)
        for i, curve in enumerate(all_curves_levels) for _ in curve
    ]
    pooled_analistas = [
        (analistas[i] if analistas and i < len(analistas) else "")
        for i, curve in enumerate(all_curves_levels) for _ in curve
    ]

    level_replicates: dict[float, list[float]] = {}
    for curve_levels, curve_responses in zip(all_curves_levels, all_curves_responses):
        for lvl, resp in zip(curve_levels, curve_responses):
            level_replicates.setdefault(lvl, []).append(resp)

    homog = homogeneity_variance_test(level_replicates)
    mandel = mandel_linearity_test(pooled_levels, pooled_responses)

    if homog.homogenea:
        lin = linearity(pooled_levels, pooled_responses, r_min)
        slope, intercept, r, r2, cumple = lin.slope, lin.intercept, lin.r, lin.r2, lin.cumple_r
        modelo = "Simple"
    else:
        # peso por punto = 1 / varianza de las réplicas de SU nivel
        weights = []
        for lvl in pooled_levels:
            s = _sample_sd(level_replicates[lvl])
            weights.append(1.0 / (s ** 2) if s > 0 else 1.0)
        wlin = weighted_linear_regression(pooled_levels, pooled_responses, weights, r_min)
        slope, intercept, r, r2, cumple = wlin.slope, wlin.intercept, wlin.r, wlin.r2, wlin.cumple_r
        modelo = "Ponderada"

    res = residuals(pooled_levels, pooled_responses, slope, intercept)
    x_recalc = [(y - intercept) / slope for y in pooled_responses]
    err_pct = [((xr - xn) / xn) * 100 if xn else float("nan") for xr, xn in zip(x_recalc, pooled_levels)]

    return CalibrationAnalysis(
        homogeneidad=homog, linealidad_mandel=mandel, modelo_usado=modelo,
        slope=slope, intercept=intercept, r=r, r2=r2, cumple_r=cumple,
        puntos_x=pooled_levels, puntos_y=pooled_responses,
        residuales=res, x_recalculada=x_recalc, error_percent=err_pct,
        dias=pooled_dias, analistas=pooled_analistas,
    )


# ---------------------------------------------------------------------------
# Prueba de Grubbs (dato anómalo único) — usada en linealidad, LC, LS, precisión
# ---------------------------------------------------------------------------
@dataclass
class GrubbsResult:
    n: int
    g_critico: float | None
    g_bajo: float
    g_alto: float
    hay_atipico_bajo: bool
    hay_atipico_alto: bool


def grubbs_test(values: list[float], alpha: float = 0.05) -> GrubbsResult:
    n = len(values)
    mean = sum(values) / n
    sd = _sample_sd(values)
    g_crit = grubbs_critical(n, alpha)
    if sd == 0:
        return GrubbsResult(n, g_crit, 0.0, 0.0, False, False)
    g_bajo = (mean - min(values)) / sd
    g_alto = (max(values) - mean) / sd
    hay_bajo = g_crit is not None and g_bajo > g_crit
    hay_alto = g_crit is not None and g_alto > g_crit
    return GrubbsResult(n, g_crit, g_bajo, g_alto, hay_bajo, hay_alto)


@dataclass
class DixonResult:
    n: int
    q_critico: float | None
    q_bajo: float
    q_alto: float
    hay_atipico_bajo: bool
    hay_atipico_alto: bool


def dixon_test(values: list[float]) -> DixonResult:
    """Prueba Q de Dixon (rechazo de UN dato sospechoso), tabla del formato
    LA-F-210, n=4..20. Q = brecha con el vecino más cercano / rango total."""
    n = len(values)
    q_crit = dixon_critical(n)
    ordered = sorted(values)
    rango = ordered[-1] - ordered[0]
    if rango == 0:
        return DixonResult(n, q_crit, 0.0, 0.0, False, False)
    q_bajo = (ordered[1] - ordered[0]) / rango
    q_alto = (ordered[-1] - ordered[-2]) / rango
    hay_bajo = q_crit is not None and q_bajo > q_crit
    hay_alto = q_crit is not None and q_alto > q_crit
    return DixonResult(n, q_crit, q_bajo, q_alto, hay_bajo, hay_alto)


@dataclass
class OutlierTestResult:
    prueba_usada: str        # "Dixon" o "Grubbs"
    n: int
    valor_critico: float | None
    estadistico_bajo: float
    estadistico_alto: float
    hay_atipico: bool
    detalle: object           # DixonResult o GrubbsResult completo


def outlier_test_auto(values: list[float], alpha: float = 0.05) -> OutlierTestResult:
    """Selecciona automáticamente la prueba de dato atípico según el número
    de datos disponibles: Dixon (Q) para muestras pequeñas (n=4 a 7, donde es
    la prueba clásicamente recomendada por su mayor potencia con pocos datos)
    y Grubbs para n=8 en adelante. [CRITERIO TÉCNICO PROPUESTO — convención
    habitual en química analítica; ambas tablas provienen del formato
    LA-F-210 del laboratorio]. Con n<4 ninguna prueba es aplicable."""
    n = len(values)
    if n < 4:
        return OutlierTestResult("Ninguna (n<4)", n, None, 0.0, 0.0, False, None)
    if n <= 7:
        d = dixon_test(values)
        return OutlierTestResult("Dixon", n, d.q_critico, d.q_bajo, d.q_alto,
                                  d.hay_atipico_bajo or d.hay_atipico_alto, d)
    g = grubbs_test(values, alpha)
    return OutlierTestResult("Grubbs", n, g.g_critico, g.g_bajo, g.g_alto,
                              g.hay_atipico_bajo or g.hay_atipico_alto, g)


def _sample_sd(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# 6.2 (verificación LC/LS) y 6.5 (veracidad) — estadística descriptiva + sesgo
# ---------------------------------------------------------------------------
@dataclass
class DescriptiveResult:
    n: int
    mean: float
    sd: float
    cv_percent: float | None


def descriptive_stats(values: list[float]) -> DescriptiveResult:
    n = len(values)
    mean = sum(values) / n
    sd = _sample_sd(values)
    cv = (sd / mean) * 100 if mean else None
    return DescriptiveResult(n=n, mean=mean, sd=sd, cv_percent=cv)


@dataclass
class TruenessResult:
    error_abs: float
    error_rel_percent: float
    recovery_percent: float
    t_calculado: float
    t_tabulado: float
    ic_bajo: float
    ic_alto: float


def trueness_stats(values: list[float], nominal: float, alpha: float = 0.05) -> TruenessResult:
    """Ec. 1-4 (sesgo/recuperación) + prueba t de una muestra vs. valor nominal,
    e intervalo de confianza de la media (Guía Eurachem, Ref. Rápida 6)."""
    desc = descriptive_stats(values)
    n = desc.n
    error_abs = desc.mean - nominal
    error_rel = (error_abs / nominal) * 100 if nominal else float("nan")
    recovery = (desc.mean / nominal) * 100 if nominal else float("nan")
    se = desc.sd / math.sqrt(n)
    t_calc = abs(error_abs) / se if se else 0.0
    t_tab = _stats.t.ppf(1 - alpha / 2, df=n - 1)
    margen = t_tab * se
    return TruenessResult(
        error_abs=error_abs,
        error_rel_percent=error_rel,
        recovery_percent=recovery,
        t_calculado=t_calc,
        t_tabulado=t_tab,
        ic_bajo=desc.mean - margen,
        ic_alto=desc.mean + margen,
    )


# ---------------------------------------------------------------------------
# Control de calidad por lote de muestras (LA-P-343/LA-P-340, Tabla 5):
# recuperación NETA de matriz fortificada (LFM/LFMD) y RPD de duplicados
# (DM/LFMD). Esto NO viene textualmente de la guía Eurachem (que trata la
# verificación con estándares, no con matrices reales sin valor de
# referencia) pero es la práctica estándar de control de calidad por lote
# en química analítica ambiental (EPA 8000 series) y es la que ya usa el
# laboratorio en sus procedimientos [CRITERIO DEL PROCEDIMIENTO INTERNO].
# ---------------------------------------------------------------------------
@dataclass
class NetRecoveryResult:
    mean_spiked: float
    mean_native: float
    net_recovery_percent: float


def net_recovery_stats(spiked_values: list[float], native_values: list[float], added_amount: float) -> NetRecoveryResult:
    """Recuperación neta de una matriz fortificada (LFM/LFMD):
    R(%) = (media_adicionada - media_nativa) / cantidad_adicionada * 100
    """
    m_sp = sum(spiked_values) / len(spiked_values)
    m_na = sum(native_values) / len(native_values) if native_values else 0.0
    net = ((m_sp - m_na) / added_amount) * 100 if added_amount else float("nan")
    return NetRecoveryResult(mean_spiked=m_sp, mean_native=m_na, net_recovery_percent=net)


@dataclass
class RPDResult:
    mean_a: float
    mean_b: float
    rpd_percent: float


def rpd_stats(values_a: list[float], values_b: list[float]) -> RPDResult:
    """Diferencia porcentual relativa (RPD) entre dos resultados/duplicados:
    RPD(%) = |media_a - media_b| / ((media_a + media_b)/2) * 100
    """
    m_a = sum(values_a) / len(values_a)
    m_b = sum(values_b) / len(values_b)
    denom = (m_a + m_b) / 2
    rpd = abs(m_a - m_b) / denom * 100 if denom else float("nan")
    return RPDResult(mean_a=m_a, mean_b=m_b, rpd_percent=rpd)


# ---------------------------------------------------------------------------
# 6.6.4 — Repetibilidad (Sr) y Precisión intermedia (SI) por ANOVA anidado
# de un factor (día/grupo), diseño balanceado. Ec. general ISO 5725-3.
# ---------------------------------------------------------------------------
@dataclass
class PrecisionResult:
    n_grupos: int
    replicas_por_grupo: int
    sr: float                # desviación estándar de repetibilidad
    si: float                # desviación estándar de precisión intermedia
    cv_sr_percent: float
    cv_si_percent: float
    ms_dentro: float
    ms_entre: float


def repeatability_intermediate_precision(groups: list[list[float]]) -> PrecisionResult:
    """`groups`: lista de grupos (p.ej. días), cada uno con el mismo número de
    réplicas. Implementa el ANOVA de un factor de la Sección 6.6.4 / Anexo C
    de la guía Eurachem (equivalente a las fórmulas de la hoja DATOS del
    formato LA-F-319, generalizado a cualquier número de días/réplicas)."""
    d = len(groups)
    r = len(groups[0])
    if any(len(g) != r for g in groups):
        raise ValueError("El diseño debe ser balanceado: mismo número de réplicas por grupo.")
    all_values = [v for g in groups for v in g]
    n = d * r
    total = sum(all_values)
    ct = total * total / n
    ss_total = sum(v * v for v in all_values) - ct
    ss_entre = sum((sum(g) ** 2) / r for g in groups) - ct
    ss_dentro = ss_total - ss_entre
    df_entre = d - 1
    df_dentro = d * (r - 1)
    ms_dentro = ss_dentro / df_dentro if df_dentro else 0.0
    ms_entre = ss_entre / df_entre if df_entre else 0.0
    sr = math.sqrt(max(ms_dentro, 0.0))
    var_entre_componente = max((ms_entre - ms_dentro) / r, 0.0)
    si = math.sqrt(var_entre_componente + sr ** 2)
    mean = total / n
    cv_sr = (sr / mean) * 100 if mean else float("nan")
    cv_si = (si / mean) * 100 if mean else float("nan")
    return PrecisionResult(
        n_grupos=d, replicas_por_grupo=r, sr=sr, si=si,
        cv_sr_percent=cv_sr, cv_si_percent=cv_si,
        ms_dentro=ms_dentro, ms_entre=ms_entre,
    )


# ---------------------------------------------------------------------------
# Ventanas de retención (control cromatográfico adicional, no exigido por
# Eurachem pero de uso estándar en métodos EPA 8000 series) [CRITERIO INTERNO]
# ---------------------------------------------------------------------------
@dataclass
class RetentionWindowResult:
    promedio: float
    sd: float
    desde: float
    hasta: float


def retention_window(retention_times: list[float], n_sd: float = 3.0) -> RetentionWindowResult:
    desc = descriptive_stats(retention_times)
    return RetentionWindowResult(
        promedio=desc.mean, sd=desc.sd,
        desde=desc.mean - n_sd * desc.sd, hasta=desc.mean + n_sd * desc.sd,
    )
