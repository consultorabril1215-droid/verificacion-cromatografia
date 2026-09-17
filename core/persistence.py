"""
Persistencia del proyecto de verificación en Google Drive, usando una cuenta
de servicio (no requiere que cada analista otorgue permisos individuales).

Flujo: el analista registra datos y presiona "Guardar en Drive"; el
administrador presiona "Cargar desde Drive" para traer lo último guardado,
revisar resultados/incertidumbre y exportar el Excel/PDF firmado.

Configuración requerida en Streamlit Secrets (Settings > Secrets de la app):

    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "verificacion-app@....iam.gserviceaccount.com"
    client_id = "..."
    token_uri = "https://oauth2.googleapis.com/token"

    [drive]
    folder_id = "13HeurdiKovvtC7GUUJ6LK0weYZ6HDOvp"

(Los valores exactos vienen del archivo JSON descargado al crear la cuenta
de servicio; se copian tal cual, campo por campo, en el formato TOML de
Streamlit Secrets.)
"""
from __future__ import annotations

import io
import json
from dataclasses import asdict
from datetime import date

import streamlit as st

from .models import (
    AcceptanceCriteria, MethodInfo, DesignStructure, Compound, CalibrationCurve,
    ReplicateLevel, CertificateRecord, CertificateAnalyte, ReferenceMaterialCert,
    VolumetricStep, StandardPreparation, VerificationProject,
)

DEFAULT_FOLDER_ID = "13HeurdiKovvtC7GUUJ6LK0weYZ6HDOvp"
DEFAULT_FILENAME = "verificacion_project.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]


def drive_configured() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


def _get_folder_id() -> str:
    try:
        return st.secrets.get("drive", {}).get("folder_id", DEFAULT_FOLDER_ID)
    except Exception:
        return DEFAULT_FOLDER_ID


def _get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_file(service, folder_id: str, filename: str):
    q = f"'{folder_id}' in parents and name='{filename}' and trashed=false"
    res = service.files().list(q=q, fields="files(id,name,modifiedTime)").execute()
    files = res.get("files", [])
    return files[0] if files else None


# ---------------------------------------------------------------------------
# Serialización (dataclasses <-> dict JSON-compatible)
# ---------------------------------------------------------------------------
def _project_to_dict(project: VerificationProject) -> dict:
    d = asdict(project)
    d["method"]["fecha"] = project.method.fecha.isoformat()
    return d


def _project_from_dict(d: dict) -> VerificationProject:
    m = d["method"]
    method = MethodInfo(
        codigo_formato=m.get("codigo_formato", ""), version=m.get("version", "1"),
        fecha=date.fromisoformat(m["fecha"]) if m.get("fecha") else date.today(),
        ensayo=m.get("ensayo", ""), matriz=m.get("matriz", ""),
        procedimiento_interno=m.get("procedimiento_interno", ""), tecnica=m.get("tecnica", ""),
        metodo_referencia=m.get("metodo_referencia", ""), plan_verificacion=m.get("plan_verificacion", ""),
        unidad=m.get("unidad", "mg/L"), laboratorio=m.get("laboratorio", ""),
        analistas=m.get("analistas", []), equipos=m.get("equipos", []),
    )
    criteria = AcceptanceCriteria(**d["criteria"])
    design = DesignStructure(**d["design"])

    certificates = []
    for c in d.get("certificates", []):
        analitos = [CertificateAnalyte(**a) for a in c.get("analitos", [])]
        cd = dict(c)
        cd["analitos"] = analitos
        certificates.append(CertificateRecord(**cd))

    def _prep_from_dict(sp):
        if not sp:
            return None
        rm = ReferenceMaterialCert(**sp["reference_material"])
        steps = [VolumetricStep(**s) for s in sp.get("steps", [])]
        return StandardPreparation(reference_material=rm, steps=steps)

    compounds = []
    for c in d.get("compounds", []):
        curves = [CalibrationCurve(**cc) for cc in c.get("calibration_curves", [])]
        levels = [ReplicateLevel(**rl) for rl in c.get("replicate_levels", [])]
        prep = _prep_from_dict(c.get("standard_preparation"))
        surrogate_prep = _prep_from_dict(c.get("surrogate_preparation"))
        vm = VolumetricStep(**c["volumen_muestra"]) if c.get("volumen_muestra") else None
        compounds.append(Compound(
            nombre=c["nombre"], lc_nominal=c["lc_nominal"], ls_nominal=c["ls_nominal"],
            calibration_curves=curves, replicate_levels=levels,
            standard_preparation=prep, volumen_muestra=vm,
            surrogate_preparation=surrogate_prep,
        ))

    return VerificationProject(method=method, criteria=criteria, design=design,
                                compounds=compounds, certificates=certificates)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def save_project_to_drive(project: VerificationProject, filename: str = DEFAULT_FILENAME) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    service = _get_drive_service()
    folder_id = _get_folder_id()
    payload = json.dumps(_project_to_dict(project), ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json", resumable=False)
    existing = _find_file(service, folder_id, filename)
    if existing:
        service.files().update(fileId=existing["id"], media_body=media).execute()
        return existing["id"]
    meta = {"name": filename, "parents": [folder_id]}
    created = service.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"]


def load_project_from_drive(filename: str = DEFAULT_FILENAME):
    """Devuelve (VerificationProject, modifiedTime) o (None, None) si no existe aún."""
    from googleapiclient.http import MediaIoBaseDownload

    service = _get_drive_service()
    folder_id = _get_folder_id()
    existing = _find_file(service, folder_id, filename)
    if not existing:
        return None, None
    request = service.files().get_media(fileId=existing["id"])
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    data = json.loads(buf.read().decode("utf-8"))
    return _project_from_dict(data), existing.get("modifiedTime")
