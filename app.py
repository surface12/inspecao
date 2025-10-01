# -*- coding: utf-8 -*-
"""
App Streamlit: Inspeção de Transformadores (Google Drive)
--------------------------------------------------------
- Tira fotos pelo celular (câmera) ou envia da galeria
- Vincula ao Nº de Série
- Gera ZIP (fotos + registro.csv)
- Envia automaticamente para o Google Drive, em subpastas por Nº de Série

Requisitos (requirements.txt):
    streamlit
    pillow
    pandas
    google-api-python-client
    google-auth
    google-auth-httplib2
    httplib2

Secrets (.streamlit/secrets.toml) — exemplo:
    [google]
    type = "service_account"
    project_id = "SEU_PROJETO"
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "sua-conta@seu-projeto.iam.gserviceaccount.com"
    client_id = "..."
    token_uri = "https://oauth2.googleapis.com/token"
    drive_folder_id = "ID_DA_PASTA_RAIZ_NO_DRIVE"

Uso local:
    streamlit run inspecao-transformadores-drive.py

Publicação (Streamlit Community Cloud):
    Configure os Secrets do Google, suba este arquivo e o requirements.txt e publique.
"""

from __future__ import annotations
import io
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from PIL import Image
import streamlit as st

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -----------------------------
# Config da página
# -----------------------------
st.set_page_config(page_title="Inspeção • Google Drive", page_icon="📁", layout="centered")

# -----------------------------
# Constantes e utilidades
# -----------------------------
BASE_DIR = Path('.')
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
DATE_FMT = "%Y-%m-%d_%H-%M-%S"


def ensure_serial_dir(serial: str) -> Path:
    safe = serial.strip().replace('/', '-').replace('\\', '-').replace('..', '-')
    d = DATA_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def pil_from_uploaded(file) -> Image.Image:
    return Image.open(file).convert('RGB')


def drive_service_from_secrets():
    if 'google' not in st.secrets:
        st.stop()
    scopes = ['https://www.googleapis.com/auth/drive']
    info = dict(st.secrets['google'])
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return build('drive', 'v3', credentials=creds)


def drive_ensure_subfolder(service, parent_id: str, name: str) -> Optional[str]:
    q = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    res = service.files().list(q=q, spaces='drive', fields='files(id,name)', pageSize=1).execute()
    files = res.get('files', [])
    if files:
        return files[0]['id']
    meta = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=meta, fields='id').execute()
    return folder.get('id')


def drive_upload_bytes(service, parent_id: str, filename: str, data: bytes, mime: str):
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    meta = {'name': filename, 'parents': [parent_id]}
    return service.files().create(body=meta, media_body=media, fields='id,webViewLink').execute()


def save_and_upload(serial: str, images: List[Image.Image]) -> Path:
    """Salva local (ZIP + CSV) e sobe CSV + JPGs ao Drive na subpasta do serial."""
    serial_dir = ensure_serial_dir(serial)
    log_csv = serial_dir / 'registro.csv'

    # Salva local e prepara bytes para upload
    raw_pairs: List[Tuple[str, bytes]] = []
    for i, img in enumerate(images, start=1):
        ts = datetime.now().strftime(DATE_FMT)
        fname = f"{serial}_{ts}_{i:03d}.jpg"
        fpath = serial_dir / fname
        img.save(fpath, format='JPEG', quality=90)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=90)
        raw_pairs.append((fname, buf.getvalue()))

        # Atualiza CSV
        row = {
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'serial': serial,
            'arquivo': fname,
        }
        if log_csv.exists():
            df = pd.read_csv(log_csv)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_csv(log_csv, index=False)

    # ZIP local do serial
    import shutil
    zip_base = DATA_DIR / f"{serial}_inspecao"
    for ext in ('.zip',):
        zc = DATA_DIR / f"{serial}_inspecao{ext}"
        if zc.exists():
            zc.unlink()
    zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=serial_dir))

    # Upload ao Drive
    service = drive_service_from_secrets()
    parent = st.secrets['google'].get('drive_folder_id')
    if not parent:
        st.error("'drive_folder_id' não definido em [google] nos Secrets.")
        return zip_path

    sub_id = drive_ensure_subfolder(service, parent, serial)

    # Envia CSV
    with open(log_csv, 'rb') as f:
        _ = drive_upload_bytes(service, sub_id, 'registro.csv', f.read(), 'text/csv')
    st.success("CSV enviado ao Drive.")

    # Envia fotos
    for name, data in raw_pairs:
        _ = drive_upload_bytes(service, sub_id, name, data, 'image/jpeg')
        st.toast(f"Imagem enviada: {name}")

    return zip_path

# -----------------------------
# Estado da sessão
# -----------------------------
if 'photos' not in st.session_state:
    st.session_state.photos: List[Image.Image] = []

# -----------------------------
# UI
# -----------------------------
st.title("📸 Inspeção • Google Drive")
st.caption("Nº de série → Fotos → ZIP + Upload automático para o Drive")

with st.form("frm", clear_on_submit=False):
    serial = st.text_input("Número de série", placeholder="Ex.: TRF-2025-001", max_chars=100)

    st.markdown("**Câmera do celular**")
    cam = st.camera_input("Toque para tirar a foto (repita quantas quiser)")

    st.markdown("**Galeria (opcional)**")
    uploads = st.file_uploader(
        "Selecione imagens da galeria (pode várias)",
        type=["png", "jpg", "jpeg", "webp", "heic"],
        accept_multiple_files=True,
    )

    c1, c2, c3 = st.columns(3)
    add_cam = c1.form_submit_button("➕ Add foto da câmera")
    add_up = c2.form_submit_button("➕ Add da galeria")
    clear_ = c3.form_submit_button("🗑️ Limpar lista")

    if add_cam:
        if not serial.strip():
            st.warning("Informe o número de série antes de adicionar fotos.")
        elif cam is None:
            st.warning("Tire uma foto para adicionar.")
        else:
            try:
                img = pil_from_uploaded(cam)
                st.session_state.photos.append(img)
                st.success("Foto adicionada.")
            except Exception as e:
                st.error(f"Erro ao processar a foto: {e}")

    if add_up:
        if not serial.strip():
            st.warning("Informe o número de série antes de adicionar fotos.")
        elif not uploads:
            st.warning("Selecione uma ou mais imagens.")
        else:
            ok = 0
            for uf in uploads:
                try:
                    img = pil_from_uploaded(uf)
                    st.session_state.photos.append(img)
                    ok += 1
                except Exception as e:
                    st.error(f"Erro com {getattr(uf, 'name', 'arquivo')}: {e}")
            if ok:
                st.success(f"{ok} imagem(ns) adicionada(s).")

    if clear_:
        st.session_state.photos = []
        st.info("Lista de fotos esvaziada.")

# Lista de miniaturas
if st.session_state.photos:
    st.subheader("Fotos na fila")
    for i, img in enumerate(st.session_state.photos, start=1):
        st.image(img, caption=f"Foto #{i}", use_container_width=True)
else:
    st.info("Nenhuma foto adicionada ainda.")

st.divider()

colA, colB = st.columns(2)
with colA:
    if st.button("💾 Salvar & Enviar ao Drive", type="primary", use_container_width=True):
        if not serial.strip():
            st.error("Informe o número de série no formulário.")
        elif not st.session_state.photos:
            st.warning("Adicione pelo menos uma foto.")
        else:
            try:
                zip_path = save_and_upload(serial.strip(), st.session_state.photos)
                st.success("Concluído! Baixe o ZIP abaixo e confira no Drive.")
                with open(zip_path, 'rb') as f:
                    st.download_button(
                        "⬇️ Baixar pacote ZIP",
                        f,
                        file_name=zip_path.name,
                        mime="application/zip",
                        use_container_width=True,
                    )
            except Exception as e:
                st.error(f"Falha: {e}")

with colB:
    if st.button("🔄 Reiniciar sessão", use_container_width=True):
        st.session_state.photos = []
        st.rerun()

st.markdown(
    """
---
**Dicas**
- Compartilhe sua pasta raiz do Drive (ID em `drive_folder_id`) com o e-mail da conta de serviço, como **Editor**.
- Para 18 trafos: gere e envie um pacote por série, depois avance para o próximo.
    """
)
