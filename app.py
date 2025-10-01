from __future__ import annotations
import io
import os
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
from PIL import Image
import streamlit as st

# ---------------------------------
# Configurações da página
# ---------------------------------
st.set_page_config(
    page_title="Inspeção de Transformadores",
    page_icon="🔧",
    layout="centered",
)

# ---------------------------------
# Utilidades
# ---------------------------------
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
    # Streamlit devolve UploadedFile; abrimos no PIL
    return Image.open(file).convert('RGB')


def save_image(img: Image.Image, out_path: Path, quality: int = 90) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format='JPEG', quality=quality)


def append_log_row(log_path: Path, row: dict) -> None:
    if log_path.exists():
        df = pd.read_csv(log_path)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(log_path, index=False)


def save_bundle(serial: str, images: List[Image.Image]) -> Path:
    """Salva imagens + CSV e devolve caminho do ZIP para download."""
    serial_dir = ensure_serial_dir(serial)
    log_csv = serial_dir / 'registro.csv'

    saved_files = []
    for i, img in enumerate(images, start=1):
        ts = datetime.now().strftime(DATE_FMT)
        fname = f"{serial}_{ts}_{i:03d}.jpg"
        fpath = serial_dir / fname
        save_image(img, fpath)
        saved_files.append(fpath)
        append_log_row(log_csv, {
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'serial': serial,
            'arquivo': fname
        })

    # cria zip do diretório do serial
    import shutil
    zip_base = DATA_DIR / f"{serial}_inspecao"
    # remove zip antigo se existir
    for ext in ('.zip',):
        if (DATA_DIR / f"{serial}_inspecao{ext}").exists():
            (DATA_DIR / f"{serial}_inspecao{ext}").unlink()
    zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=serial_dir))

    return zip_path


# ---------------------------------
# Estado da sessão
# ---------------------------------
if 'photos' not in st.session_state:
    st.session_state.photos: List[Image.Image] = []


# ---------------------------------
# UI
# ---------------------------------
st.title("📸 Inspeção de Transformadores")
st.caption("Vincule fotos ao número de série, gere um pacote .zip com tudo organizado.")

with st.form("form-inspecao", clear_on_submit=False):
    serial = st.text_input("Número de série", placeholder="Ex.: TRF-2025-001", max_chars=80)

    st.markdown("**Captura pela câmera**")
    cam = st.camera_input("Toque para tirar uma foto (repita para várias)")

    st.markdown("**Ou enviar da galeria (opcional)**")
    uploads = st.file_uploader(
        "Envie imagens da galeria (pode selecionar várias)",
        type=["png", "jpg", "jpeg", "webp", "heic"],
        accept_multiple_files=True,
    )

    col1, col2, col3 = st.columns(3)
    add_cam = col1.form_submit_button("➕ Adicionar foto da câmera")
    add_up = col2.form_submit_button("➕ Adicionar fotos da galeria")
    clear_btn = col3.form_submit_button("🗑️ Limpar fotos")

    # Ações dentro do form
    if add_cam:
        if serial.strip() == "":
            st.warning("Informe o número de série antes de adicionar fotos.")
        elif cam is None:
            st.warning("Tire uma foto para adicionar.")
        else:
            try:
                img = pil_from_uploaded(cam)
                st.session_state.photos.append(img)
                st.success("Foto da câmera adicionada.")
            except Exception as e:
                st.error(f"Erro ao processar a foto da câmera: {e}")

    if add_up:
        if serial.strip() == "":
            st.warning("Informe o número de série antes de adicionar fotos.")
        elif not uploads:
            st.warning("Selecione uma ou mais imagens da galeria.")
        else:
            ok = 0
            for uf in uploads:
                try:
                    img = pil_from_uploaded(uf)
                    st.session_state.photos.append(img)
                    ok += 1
                except Exception as e:
                    st.error(f"Erro com {uf.name}: {e}")
            if ok:
                st.success(f"{ok} imagem(ns) adicionada(s) da galeria.")

    if clear_btn:
        st.session_state.photos = []
        st.info("Lista de fotos esvaziada.")

# Exibição das miniaturas atuais
if st.session_state.photos:
    st.subheader("Fotos na fila")
    for i, img in enumerate(st.session_state.photos, start=1):
        st.image(img, caption=f"Foto #{i}", use_container_width=True)
else:
    st.info("Nenhuma foto adicionada ainda. Tire uma foto ou envie da galeria.")

# Botões finais (fora do form)
st.divider()
colA, colB = st.columns([1,1])

with colA:
    if st.button("💾 Salvar pacote do nº de série", type="primary", use_container_width=True):
        if not st.session_state.photos:
            st.warning("Adicione ao menos uma foto antes de salvar.")
        else:
            # precisamos pedir o serial novamente (fora do form) -> campo persistido acima
            if 'form-inspecao' in st.session_state:
                pass  # garantido
            if 'form-inspecao-serial' in st.session_state:
                serial_cached = st.session_state['form-inspecao-serial']
            # use o valor do campo 'serial' acima (já está na variável local)
            if not serial or serial.strip() == "":
                st.error("Informe o número de série no formulário antes de salvar.")
            else:
                try:
                    zip_path = save_bundle(serial.strip(), st.session_state.photos)
                    st.success("Pacote salvo com sucesso. Baixe abaixo.")
                    with open(zip_path, 'rb') as f:
                        st.download_button(
                            label=f"⬇️ Baixar {zip_path.name}",
                            data=f,
                            file_name=zip_path.name,
                            mime="application/zip",
                            use_container_width=True,
                        )
                except Exception as e:
                    st.error(f"Falha ao salvar: {e}")

with colB:
    if st.button("🔄 Reiniciar sessão", use_container_width=True):
        st.session_state.photos = []
        st.rerun()

# Rodapé
st.markdown(
    """
---
**Dica:** Para uma inspeção com vários transformadores no dia, gere e baixe um .zip para cada nº de série
antes de seguir para o próximo. Assim tudo fica organizado por pasta (um CSV + fotos por serial).

**Integração opcional (dev):** para enviar automaticamente ao Google Drive/S3, adapte a função `save_bundle` 
para, após criar o ZIP, fazer o upload via API e exibir o link.
    """
)
