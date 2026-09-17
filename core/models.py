"""
Modelos de datos para la aplicación de verificación de métodos analíticos +
estimación de incertidumbre, conforme a:
  - Guía Eurachem "La Adecuación al Uso de los Métodos Analíticos" (2ª ed., 2016)
  - Guía EURACHEM/CITAC CG4 "Cuantificación de la Incertidumbre en Medidas
    Analíticas" (QUAM:2012.P1)

Estos modelos son agnósticos a la técnica analítica: los criterios de
aceptación y la estructura de niveles/réplicas se definen una sola vez al
inicio y se replican para cada compuesto que el analista quiera verificar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# ---------------------------------------------------------------------------
# Criterios de aceptación (definidos una vez, cambian según técnica/método)
# ---------------------------------------------------------------------------
@dataclass
class AcceptanceCriteria:
    r_min: float = 0.995                     # Coef. correlación mínimo (linealidad)
    cv_max_percent: float = 30.0             # CV% máximo (precisión)
    recovery_lc_min: float = 50.0            # % recuperación mínima en LC
    recovery_lc_max: float = 150.0
    recovery_min: float = 70.0               # % recuperación mínima (LS y muestras)
    recovery_max: float = 130.0
    error_rel_max_percent: float | None = None  # Si es distinto de CV%, se puede fijar aparte
    grubbs_alpha: float = 0.05               # Nivel de significancia prueba Grubbs
    t_alpha: float = 0.05                    # Nivel de significancia prueba t (dos colas)
    k_coverage: int = 2                      # Factor de cobertura incertidumbre expandida
    confidence_level_percent: float = 95.0


# ---------------------------------------------------------------------------
# Información general del método / verificación
# ---------------------------------------------------------------------------
@dataclass
class MethodInfo:
    codigo_formato: str = ""
    version: str = "1"
    fecha: date = field(default_factory=date.today)
    ensayo: str = ""
    matriz: str = ""
    procedimiento_interno: str = ""
    tecnica: str = ""
    metodo_referencia: str = ""
    plan_verificacion: str = ""
    unidad: str = "mg/L"
    laboratorio: str = ""
    analistas: list[str] = field(default_factory=list)
    equipos: list[dict] = field(default_factory=list)   # [{equipo, marca, codigo_interno}]


# ---------------------------------------------------------------------------
# Estructura de niveles y réplicas (una sola vez, aplica a todos los compuestos)
#
# El "grupo" (unidad del ANOVA de precisión, Eurachem 6.6.4 / Ref. Rápida 7c)
# es la combinación día × analista: cada grupo se mide en condiciones de
# repetibilidad (mismo analista, mismo equipo, corto plazo), y la variación
# ENTRE grupos (que ahora sí representa un cambio real de condición: día
# distinto y/o analista distinto) es lo que estima la precisión intermedia.
# Por defecto: 2 días × 2 analistas = 4 grupos (df=3 para SI). La guía
# recomienda 6-15 grupos para una estimación robusta; con 4 grupos la
# estimación es válida pero con menor robustez — limitación aceptada por
# restricción de costos, debe documentarse como tal en el informe.
# ---------------------------------------------------------------------------
@dataclass
class DesignStructure:
    n_dias: int = 3
    analistas: list[str] = field(default_factory=lambda: ["Analista A", "Analista B"])
    replicas_por_grupo: int = 2
    n_niveles_curva: int = 6

    @property
    def n_grupos(self) -> int:
        return self.n_dias * max(len(self.analistas), 1)

    @property
    def n_replicas_total(self) -> int:
        return self.n_grupos * self.replicas_por_grupo

    @property
    def grupos(self) -> list[dict]:
        """Lista ordenada de grupos: [{'dia': 1, 'analista': 'Analista A'}, ...]"""
        return [
            {"dia": d + 1, "analista": a}
            for d in range(self.n_dias)
            for a in (self.analistas or ["Analista único"])
        ]

    @property
    def df_si(self) -> int:
        """Grados de libertad para la componente entre-grupos de la SI."""
        return max(self.n_grupos - 1, 0)


# ---------------------------------------------------------------------------
# Curva de calibración: una réplica de la curva (p.ej. un día) con n niveles
# ---------------------------------------------------------------------------
@dataclass
class CalibrationCurve:
    levels_nominal: list[float]      # concentración teórica por nivel
    responses: list[float]           # señal instrumental (área) por nivel
    retention_time_min: float | None = None


# ---------------------------------------------------------------------------
# Conjunto de réplicas a un nivel de concentración (LC, LS, muestra, etc.)
# ---------------------------------------------------------------------------
@dataclass
class ReplicateLevel:
    label: str                       # p.ej. "LC", "LS", "Muestra SUP", "Muestra SUP+LC"
    nominal: float | None            # valor teórico esperado (None si no aplica, p.ej. blanco)
    values: list[list[float]]        # [dia][replica] -> concentración medida


# ---------------------------------------------------------------------------
# Certificado de un material de referencia (MRC) — registro reutilizable.
# Un mismo certificado (p.ej. un mix multi-compuesto de un proveedor) puede
# tener varios "CertificateAnalyte" (uno por compuesto certificado en él) y
# ser referenciado por distintos compuestos del proyecto.
# ---------------------------------------------------------------------------
@dataclass
class CertificateAnalyte:
    """Un analito dentro de un certificado (una fila de la tabla del CRM)."""
    nombre_compuesto: str
    concentracion_nominal: float = 0.0
    concentracion_real: float = 0.0          # "Actual/Final Conc." del certificado
    unidad: str = "µg/mL"
    incertidumbre_expandida: float | None = None   # "(+/-)" del certificado, misma unidad
    k_certificado: float = 2.0                      # no siempre viene explícito -> por defecto k=2 (NIST TN1297)
    k_supuesto: bool = True                         # True si k=2 fue asumido (no venía en el certificado)
    pureza_percent: float | None = None
    incertidumbre_pureza_percent: float | None = None


@dataclass
class CertificateRecord:
    """Certificado completo de un MRC/CRM, tal como lo emite el proveedor.
    Se registra UNA vez y se reutiliza en todos los compuestos/lotes que
    provengan del mismo certificado (frecuente cuando varios analitos vienen
    en un mismo estándar mezcla, p.ej. 'EPA Method 601 - Purgeables Mix #2')."""
    proveedor: str                    # p.ej. "Absolute Standards, Inc."
    numero_parte: str = ""
    numero_lote: str = ""
    descripcion: str = ""             # p.ej. "Trihalomethanes - 4 components"
    fecha_expiracion: str = ""
    solvente: str = ""
    volumen_disolucion_ml: float | None = None
    norma_acreditacion: str = ""      # p.ej. "ANAB ISO 17034 - AR-1539"
    referencia_trazabilidad: str = "" # p.ej. "NIST Technical Note 1297"
    archivo_pdf_path: str = ""        # ruta/local o URL en Drive al PDF del certificado cargado
    analitos: list[CertificateAnalyte] = field(default_factory=list)


@dataclass
class ReferenceMaterialCert:
    """Vínculo entre un compuesto del proyecto y el analito específico dentro
    de un CertificateRecord ya registrado (o datos sueltos si no hay
    certificado disponible, en cuyo caso se aplica QUAM Apéndice G)."""
    nombre: str
    certificate_record_id: str | None = None   # referencia al CertificateRecord reutilizado
    marca_lote: str = ""
    concentracion: float = 0.0
    concentracion_unidad: str = "µg/mL"
    tiene_certificado: bool = True
    incertidumbre_certificado: float | None = None   # U del certificado (misma unidad que concentración)
    k_certificado: float = 2.0                        # factor de cobertura reportado (o asumido) en el certificado
    pureza_percent: float | None = None
    incertidumbre_pureza_percent: float | None = None
    # Si NO hay certificado disponible, se aplican valores por defecto sugeridos
    # por la guía QUAM (Apéndice G): tolerancia del fabricante como rectangular.


# ---------------------------------------------------------------------------
# Paso volumétrico (pipeteo, aforo) dentro de la preparación de un estándar
# ---------------------------------------------------------------------------
@dataclass
class VolumetricStep:
    descripcion: str                 # p.ej. "Volumen de alícuota de estándar MRC"
    volumen_nominal: float           # mL
    instrumento: str = ""            # p.ej. "Pipeta LA-116", "Balón aforado clase A"
    tiene_certificado_calibracion: bool = False
    incertidumbre_certificado: float | None = None   # U del certificado (mL)
    k_certificado: float = 2.0
    # Si no hay certificado: usar tolerancia de clase (ISO 8655 / ISO 1042) -> rectangular
    clase_tolerancia: str | None = None              # "A", "B", "A/S" ...
    tolerancia_fabricante: float | None = None       # mL, semi-intervalo
    # Repetibilidad (Tipo A) del uso del instrumento, si se dispone del dato interno
    sd_repetibilidad: float | None = None            # mL, desviación estándar de n réplicas
    n_repetibilidad: int = 10
    # Efecto de la temperatura (Tipo B, rectangular)
    incluir_efecto_temperatura: bool = True
    coef_expansion_agua: float = 2.1e-4               # /°C (QUAM Tabla E3.3)
    rango_temperatura: float = 3.0                    # °C, semi-intervalo (±ΔT del laboratorio)


# ---------------------------------------------------------------------------
# Presupuesto de preparación de un estándar (conjunto de pasos volumétricos)
# ---------------------------------------------------------------------------
@dataclass
class StandardPreparation:
    reference_material: ReferenceMaterialCert
    steps: list[VolumetricStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Compuesto: agrupa toda la información de verificación + incertidumbre
# ---------------------------------------------------------------------------
@dataclass
class Compound:
    nombre: str
    lc_nominal: float
    ls_nominal: float
    calibration_curves: list[CalibrationCurve] = field(default_factory=list)
    replicate_levels: list[ReplicateLevel] = field(default_factory=list)
    standard_preparation: StandardPreparation | None = None
    # Volumen de muestra usado en el ensayo de rutina (para u(volumen muestra))
    volumen_muestra: VolumetricStep | None = None


@dataclass
class VerificationProject:
    method: MethodInfo
    criteria: AcceptanceCriteria
    design: DesignStructure
    compounds: list[Compound] = field(default_factory=list)
    # Registro reutilizable de certificados de MRC (uno por certificado de
    # proveedor, aunque contenga varios analitos/compuestos)
    certificates: list[CertificateRecord] = field(default_factory=list)

    def get_certificate(self, certificate_record_id: str) -> CertificateRecord | None:
        return next((c for c in self.certificates if c.numero_parte + "|" + c.numero_lote == certificate_record_id), None)
