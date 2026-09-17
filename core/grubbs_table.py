"""
Tabla de valores críticos de la prueba de Grubbs (test de un solo valor atípico),
según ISO 5725-2 / ASTM E178, para n = 3..30, alfa = 0.05 y alfa = 0.01.

Fuente: hoja 'Prueba GRUBBS' de los formatos LA-F-319 / LA-F-210 del laboratorio
(valores tabulados estándar de Grubbs, consistentes con las tablas publicadas en
ISO 5725-2 Anexo B).
"""

GRUBBS_CRITICAL = {
    3: {0.05: 1.15, 0.01: 1.15},
    4: {0.05: 1.48, 0.01: 1.496},
    5: {0.05: 1.71, 0.01: 1.764},
    6: {0.05: 1.89, 0.01: 1.973},
    7: {0.05: 2.02, 0.01: 2.139},
    8: {0.05: 2.13, 0.01: 2.274},
    9: {0.05: 2.21, 0.01: 2.387},
    10: {0.05: 2.29, 0.01: 2.482},
    11: {0.05: 2.35, 0.01: 2.564},
    12: {0.05: 2.41, 0.01: 2.636},
    13: {0.05: 2.46, 0.01: 2.699},
    14: {0.05: 2.51, 0.01: 2.755},
    15: {0.05: 2.55, 0.01: 2.806},
    16: {0.05: 2.59, 0.01: 2.852},
    17: {0.05: 2.62, 0.01: 2.894},
    18: {0.05: 2.65, 0.01: 2.932},
    19: {0.05: 2.68, 0.01: 2.968},
    20: {0.05: 2.71, 0.01: 3.001},
    21: {0.05: 2.73, 0.01: 3.031},
    22: {0.05: 2.76, 0.01: 3.06},
    23: {0.05: 2.78, 0.01: 3.087},
    24: {0.05: 2.80, 0.01: 3.112},
    25: {0.05: 2.82, 0.01: 3.135},
    26: {0.05: 2.84, 0.01: 3.158},
    27: {0.05: 2.86, 0.01: 3.179},
    28: {0.05: 2.88, 0.01: 3.199},
    29: {0.05: 2.89, 0.01: 3.218},
    30: {0.05: 2.91, 0.01: 3.236},
}


def grubbs_critical(n: int, alpha: float = 0.05) -> float | None:
    """Valor G crítico para n datos y nivel de significancia alpha (0.05 o 0.01).

    Devuelve None si n está fuera del rango tabulado (3..30) o n<3, ya que la
    prueba de Grubbs de un solo valor atípico no es aplicable / no está tabulada.
    """
    if n in GRUBBS_CRITICAL:
        return GRUBBS_CRITICAL[n][alpha]
    return None
