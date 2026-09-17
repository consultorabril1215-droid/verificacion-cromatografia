"""
Tabla de valores críticos de la prueba de Dixon (Q-test) para rechazo de un
dato sospechoso, al 95% de confianza, n = 4..20.

Fuente: hoja 'Grubbs' (Tabla 2) del formato LA-F-210 del laboratorio.
"""

DIXON_CRITICAL_95 = {
    4: 0.7651,
    5: 0.6423,
    6: 0.5624,
    7: 0.5077,
    8: 0.4673,
    9: 0.4363,
    10: 0.4122,
    11: 0.3922,
    12: 0.3755,
    13: 0.3615,
    14: 0.3490,
    15: 0.3389,
    16: 0.3293,
    17: 0.3208,
    18: 0.3135,
    19: 0.3068,
    20: 0.3005,
}


def dixon_critical(n: int) -> float | None:
    return DIXON_CRITICAL_95.get(n)
