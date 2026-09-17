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
    # % Error máximo aceptable por punto de la curva (concentración recalculada
    # vs. nominal) — no es un criterio explícito de Eurachem, pero es práctica
    # común (EPA/ASTM) para señalar puntos de la curva que se desvían mucho.
    # [CRITERIO TÉCNICO PROPUESTO] editable en la Sección 1.
    error_rel_max_percent: float = 20.0
    grubbs_alpha: float = 0.05               # Nivel de significancia prueba Grubbs
    t_alpha: float = 0.05                    # Nivel de significancia prueba t (dos colas)
    k_coverage: int = 2                      # Factor de cobertura incertidumbre expandida
    confidence_level_percent: float = 95.0
    # Esquema de control de calidad por lote de muestras (LA-P-343/LA-P-340,
    # Tabla 5 — idéntico para todas las técnicas cromatográficas del
    # laboratorio, no depende del método/analito):
    rpd_max_percent: float = 30.0            # Duplicados (DM / LFMD)
    mb_debe_ser_menor_que_lc: bool = True     # Blanco del método (MB) < LC


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
    dia: int = 0                     # día en que se corrió esta curva (para trazabilidad)
    analista: str = ""               # analista que corrió esta curva


# ---------------------------------------------------------------------------
# Conjunto de réplicas a un nivel de concentración (LC, LS, muestra, etc.)
# ---------------------------------------------------------------------------
@dataclass
class ReplicateLevel:
    label: str                       # p.ej. "LC", "LS", "Muestra SUP", "Muestra SUP+LC"
    nominal: float | None            # valor teórico esperado (None si no aplica, p.ej. blanco)
    values: list[list[float]]        # [dia][replica] -> concentración medida
    # Tipo de control de calidad (Tabla 5, LA-P-343/LA-P-340). Determina qué
    # cálculo y criterio aplica — no todos los niveles se comparan igual:
    #   "LC", "LS", "LFB"  -> recuperación simple (media/nominal), 1 vez/mes
    #   "MB"               -> blanco del método, debe ser < LC, siempre
    #   "Muestra"          -> resultado nativo, sin valor esperado, solo se reporta
    #   "Subrogado"        -> recuperación simple por muestra (agregado en cantidad
    #                         conocida a CADA muestra), 70-130%, siempre
    #   "LFM"              -> matriz de laboratorio fortificada: recuperación NETA,
    #                         (media_LFM - media_muestra_nativa)/adicionado, 70-130%
    #   "LFMD"             -> duplicado de LFM: igual cálculo que LFM, más RPD vs. LFM
    #   "DM"               -> duplicado de muestra nativa: RPD vs. la muestra nativa
    tipo: str = "Muestra"
    # Para "LFM"/"LFMD"/"DM": label de OTRO ReplicateLevel del mismo compuesto
    # contra el cual se resta (LFM/LFMD) o se calcula el RPD (DM/LFMD)
    referencia_nativa: str | None = None
    referencia_duplicado: str | None = None


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


# ---------------------------------------------------------------------------
# Registro de material volumétrico (equivalente a la hoja "M" de LA-F-210):
# pipetas, balones aforados, etc. con su calibración/tolerancia y
# repetibilidad ya caracterizadas. Se registra UNA vez por instrumento y se
# selecciona por nombre al armar cada dilución, en vez de digitar los
# valores cada vez.
# ---------------------------------------------------------------------------
@dataclass
class VolumetricEquipmentRecord:
    nombre: str                          # p.ej. "Pipeta LA-116", "Balón aforado 5 mL clase A"
    tipo: str = "Pipeta"                 # "Pipeta", "Balón aforado", "Probeta", ...
    clase: str = "A"                     # clase de exactitud (ISO 8655 / ISO 1042)
    capacidad_nominal: float = 0.0       # en `unidad_capacidad` (p.ej. pipetas de precisión suelen certificarse en µL)
    unidad_capacidad: str = "mL"         # "mL" o "µL" — unidad en la que se registran capacidad/certificado/resolución
    codigo_interno: str = ""
    tiene_certificado_calibracion: bool = False
    incertidumbre_certificado: float | None = None   # U del certificado, en `unidad_capacidad`
    k_certificado: float = 2.0
    # Resolución del instrumento (p.ej. última cifra del visor de una pipeta digital
    # o graduación de un balón/probeta), en `unidad_capacidad` — componente Tipo B
    # rectangular independiente de la tolerancia y de la calibración (QUAM Apéndice E2).
    resolucion: float | None = None
    fecha_calibracion: str = ""
    # Si no hay certificado: tolerancia de clase/fabricante (QUAM Apéndice G, rectangular)
    tolerancia_fabricante: float | None = None
    # Repetibilidad (Tipo A): réplicas crudas de llenado/vaciado (Hoja M, columnas E:N) —
    # se registran SIEMPRE que se quiera verificar el instrumento por repetibilidad,
    # tenga o no certificado de calibración (verificación intermedia sin calibración).
    # `sd_repetibilidad`/`n_repetibilidad` quedan como respaldo manual (compatibilidad
    # con registros antiguos) cuando no se cargan réplicas crudas.
    repeticiones: list[float] = field(default_factory=list)   # en `unidad_capacidad`
    sd_repetibilidad: float | None = None
    n_repetibilidad: int = 10

    @property
    def factor_a_ml(self) -> float:
        return 0.001 if self.unidad_capacidad == "µL" else 1.0

    @property
    def promedio_repeticiones(self) -> float | None:
        return sum(self.repeticiones) / len(self.repeticiones) if self.repeticiones else None

    @property
    def sd_repeticiones(self) -> float | None:
        n = len(self.repeticiones)
        if n < 2:
            return None
        m = self.promedio_repeticiones
        return (sum((v - m) ** 2 for v in self.repeticiones) / (n - 1)) ** 0.5

    @property
    def sd_efectiva_ml(self) -> float | None:
        """SD de repetibilidad a usar, en mL: prioriza las réplicas crudas
        registradas (Hoja M); si no hay, cae al SD manual digitado."""
        sd = self.sd_repeticiones if self.repeticiones else self.sd_repetibilidad
        return sd * self.factor_a_ml if sd is not None else None

    @property
    def n_efectivo(self) -> int:
        return len(self.repeticiones) if self.repeticiones else self.n_repetibilidad

    @property
    def capacidad_nominal_ml(self) -> float:
        return self.capacidad_nominal * self.factor_a_ml

    @property
    def incertidumbre_certificado_ml(self) -> float | None:
        return self.incertidumbre_certificado * self.factor_a_ml if self.incertidumbre_certificado is not None else None

    @property
    def resolucion_ml(self) -> float | None:
        return self.resolucion * self.factor_a_ml if self.resolucion is not None else None

    @property
    def tolerancia_fabricante_ml(self) -> float | None:
        return self.tolerancia_fabricante * self.factor_a_ml if self.tolerancia_fabricante is not None else None


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
    equipment_record_id: str | None = None   # nombre del VolumetricEquipmentRecord seleccionado (Hoja M)
    tiene_certificado_calibracion: bool = False
    incertidumbre_certificado: float | None = None   # U del certificado (mL)
    k_certificado: float = 2.0
    # Si no hay certificado: usar tolerancia de clase (ISO 8655 / ISO 1042) -> rectangular
    clase_tolerancia: str | None = None              # "A", "B", "A/S" ...
    tolerancia_fabricante: float | None = None       # mL, semi-intervalo
    # Resolución del instrumento (mL) — componente Tipo B rectangular independiente
    # de la tolerancia/calibración (QUAM Apéndice E2), tomada de la Hoja M si el
    # instrumento se seleccionó del registro, o digitada manualmente.
    resolucion: float | None = None
    # Repetibilidad (Tipo A) del uso del instrumento, si se dispone del dato interno
    sd_repetibilidad: float | None = None            # mL, desviación estándar de n réplicas
    n_repetibilidad: int = 10
    # Efecto de la temperatura (Tipo B, rectangular)
    incluir_efecto_temperatura: bool = True
    coef_expansion_agua: float = 2.1e-4               # /°C (QUAM Tabla E3.3)
    rango_temperatura: float = 3.0                    # °C, semi-intervalo (±ΔT del laboratorio)


# ---------------------------------------------------------------------------
# Un nivel de dilución de la curva de calibración (Tabla 2, LA-P-343/LA-P-340):
# volumen de alícuota tomado del MRC + volumen de aforo, hasta llegar a la
# concentración final de ESE nivel. Cada nivel de la curva tiene su propio
# esquema de dilución (y por tanto su propia incertidumbre de preparación).
# ---------------------------------------------------------------------------
@dataclass
class DilutionLevel:
    nivel_label: str                  # "Nivel 1", "Nivel 2", ... (o "LC"/"LS" si coincide)
    concentracion_nominal: float      # concentración final de este nivel
    alicuota: VolumetricStep          # volumen tomado del MRC (o de la solución de trabajo)
    aforo: VolumetricStep             # volumen final (balón aforado)


# ---------------------------------------------------------------------------
# Presupuesto de preparación de un estándar: el MRC + el esquema de
# dilución completo (un DilutionLevel por cada nivel de la curva).
# ---------------------------------------------------------------------------
@dataclass
class StandardPreparation:
    reference_material: ReferenceMaterialCert
    dilution_levels: list[DilutionLevel] = field(default_factory=list)


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
    # Preparación del estándar SUBROGADO — es también un MRC certificado y se
    # diluye junto con el estándar del analito (ver Tabla 2, LA-P-343/LA-P-340).
    # Se documenta aquí por trazabilidad; NO se combina en la incertidumbre del
    # analito objetivo (son solutos independientes en la misma dilución), pero
    # sí se necesitaría si en el futuro se quiere estimar U del subrogado.
    surrogate_preparation: StandardPreparation | None = None

    def curve_arrays(self):
        """Curvas con datos (respuesta no vacía), listas para S.analyze_calibration:
        (niveles, respuestas, días, analistas) — un elemento por curva."""
        curves = [c for c in self.calibration_curves if any(c.responses)]
        levels = [c.levels_nominal for c in curves]
        responses = [c.responses for c in curves]
        dias = [c.dia or (i + 1) for i, c in enumerate(curves)]
        analistas = [c.analista for c in curves]
        return levels, responses, dias, analistas


@dataclass
class VerificationProject:
    method: MethodInfo
    criteria: AcceptanceCriteria
    design: DesignStructure
    compounds: list[Compound] = field(default_factory=list)
    # Registro reutilizable de certificados de MRC (uno por certificado de
    # proveedor, aunque contenga varios analitos/compuestos)
    certificates: list[CertificateRecord] = field(default_factory=list)
    # Registro reutilizable de material volumétrico (Hoja M): pipetas,
    # balones aforados, etc., con su calibración/tolerancia y repetibilidad
    equipment: list[VolumetricEquipmentRecord] = field(default_factory=list)

    def get_certificate(self, certificate_record_id: str) -> CertificateRecord | None:
        return next((c for c in self.certificates if c.numero_parte + "|" + c.numero_lote == certificate_record_id), None)

    def get_equipment(self, nombre: str) -> VolumetricEquipmentRecord | None:
        return next((e for e in self.equipment if e.nombre == nombre), None)
