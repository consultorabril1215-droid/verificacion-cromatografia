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
