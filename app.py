# -*- coding: utf-8 -*-
"""
Aplicativo de inspeção de transformadores (Streamlit) – com upload opcional ao GitHub
------------------------------------------------------------------------------------

Funciona no celular via navegador (link do Streamlit Cloud ou servidor local).
Permite:
  • Informar o Nº de série do transformador
  • Tirar fotos pela câmera do celular (ou enviar da galeria)
  • Vincular as fotos ao nº de série
  • Baixar um .zip com as imagens e um CSV de registro
  • (Opcional) **Enviar cada imagem e o CSV diretamente para um repositório GitHub**

Como executar localmente:
  1) Crie e ative um ambiente virtual (opcional)
  2) Instale dependências:  pip install -r requirements.txt
  3) Rode:  streamlit run inspecao-transformadores-streamlit.py
  4) No celular na mesma rede, abra o IP da máquina + porta mostrada pelo Streamlit

Como publicar no Streamlit Community Cloud (grátis):
  1) Suba este arquivo e um requirements.txt com:  streamlit
pillow
pandas
requests
  2) Vá em https://share.streamlit.io , conecte seu GitHub, selecione o repositório e este arquivo como entrypoint
  3) O serviço gera um link público que você pode abrir no celular

Configurar upload para GitHub (opcional, recomendado para persistência):
  • Crie um **Personal Access Token (classic)** com escopo `repo` (para repositórios privados ou públicos)
  • No Streamlit Cloud, adicione em **Secrets** (ou localmente no arquivo `.streamlit/secrets.toml`):

    [github]
    token = "ghp_xxx_somente_exemplo"
    owner = "seu-usuario-ou-org"
    repo = "nome-do-repositorio"
    branch = "main"
    base_path = "inspecoes"  # pasta destino dentro do repo

  • Durante o uso, marque a opção **“Enviar para GitHub”** antes de salvar.

Observação sobre persistência: o armazenamento do Streamlit Cloud é efêmero. Com o upload ao GitHub ativado,
as imagens e o CSV ficam versionados no repositório (pasta por número de série).
"""

from __future__ import annotations
import io
import os
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from PIL import Image
import streamlit as st
import requests

# ---------------------------------
# Configurações da página
# ---------------------------------
st.set_page_config(
    page_title="Inspeção de Transformadores",
    page_icon="🔧",
    layout="centered",
)

# ---------------------------------
# Utilidades locais
# ---------------------------------
BASE_DIR = Path('.')
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)

DATE_FMT = "%Y-%m-%d_%H-%M-%S"


def ensure_serial_dir(serial: str) -> Path:
    safe = serial.strip().replace('/', '-').replace('\', '-').replace('..', '-')
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

# ---------------------------------
# Integração GitHub (Contents API)
# ---------------------------------

def gh_conf_from_secrets() -> Optional[dict]:
    if 'github' not in st.secrets:
        return None
    gh = st.secrets['github']
    required = ['token', 'owner', 'repo', 'branch', 'base_path']
    if not all(k in gh and str(gh[k]).strip() for k in required):
        return None
    return {k: gh[k] for k in required}


def gh_headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
    }


def gh_get_file_sha(token: str, owner: str, repo: str, path: str, branch: str) -> Optional[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers=gh_headers(token))
    if r.status_code == 200:
        return r.json().get('sha')
    return None


def gh_put_file(token: str, owner: str, repo: str, path: str, branch: str, content_bytes: bytes, message: str) -> Tuple[bool, str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    b64 = base64.b64encode(content_bytes).decode('utf-8')
    payload = {
        'message': message,
        'content': b64,
        'branch': branch,
    }
    # Se o arquivo já existe, precisamos incluir o SHA
    sha = gh_get_file_sha(token, owner, repo, path, branch)
    if sha:
        payload['sha'] = sha
    r = requests.put(url, headers=gh_headers(token), json=payload)
    if r.status_code in (200, 201):
        return True, r.json().get('content', {}).get('path', path)
    else:
        try:
            err = r.json()
        except Exception:
            err = r.text
        return False, str(err)


def gh_upload_serial_bundle(serial: str, images: List[Tuple[str, bytes]], csv_bytes: bytes) -> None:
    conf = gh_conf_from_secrets()
    if not conf:
        st.warning("Config do GitHub ausente/incompleta em st.secrets['github']. Pulando upload.")
        return
    token = conf['token']
    owner = conf['owner']
    repo = conf['repo']
    branch = conf['branch']
    base_path = conf['base_path'].strip('/')

    # Envia CSV
    csv_path = f"{base_path}/{serial}/registro.csv"
    ok, info = gh_put_file(token, owner, repo, csv_path, branch, csv_bytes, f"Registro {serial}")
    if ok:
        st.success(f"CSV enviado: {csv_path}")
    else:
        st.error(f"Falha ao enviar CSV: {info}")

    # Envia imagens
    for name, b in images:
        img_path = f"{base_path}/{serial}/{name}"
        ok, info = gh_put_file(token, owner, repo, img_path, branch, b, f"Imagem {serial}: {name}")
        if ok:
            st.toast(f"Imagem enviada: {name}")
        else:
            st.error(f"Falha ao enviar {name}: {info}")


# ---------------------------------
# Salvar pacote local + (opcional) enviar a GitHub
# ---------------------------------

def save_bundle(serial: str, images: List[Image.Image], upload_to_github: bool = False) -> Path:
    """Salva imagens + CSV localmente e, se ativado, envia ao GitHub. Retorna caminho do ZIP local."""
    serial_dir = ensure_serial_dir(serial)
    log_csv = serial_dir / 'registro.csv'

    saved_files = []
    raw_pairs: List[Tuple[str, bytes]] = []  # (filename, raw bytes) para upload GitHub

    for i, img in enumerate(images, start=1):
        ts = datetime.now().strftime(DATE_FMT)
        fname = f"{serial}_{ts}_{i:03d}.jpg"
        fpath = serial_dir / fname
        # Salva local
        save_image(img, fpath)
        saved_files.append(fpath)
        # Guarda bytes crus para GitHub
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=90)
        raw_pairs.append((fname, buf.getvalue()))

        append_log_row(log_csv, {
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'serial': serial,
            'arquivo': fname
        })

    # CSV para bytes (para enviar ao GitHub também)
    with open(log_csv, 'rb') as f:
        csv_bytes = f.read()

    # cria zip do diretório do serial
    import shutil
    zip_base = DATA_DIR / f"{serial}_inspecao"
    # remove zip antigo se existir
    for ext in ('.zip',):
        if (DATA_DIR / f"{serial}_inspecao{ext}").exists():
            (DATA_DIR / f"{serial}_inspecao{ext}").unlink()
    zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=serial_dir))

    # Upload opcional ao GitHub
    if upload_to_github:
        gh_upload_serial_bundle(serial, raw_pairs, csv_bytes)

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
st.caption("Vincule fotos ao número de série, gere um pacote .zip e (opcional) envie ao GitHub.")

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

    st.markdown("**Persistência**")
    upload_git = st.checkbox("Enviar para GitHub (requer configurar Secrets)")

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
            if not serial or serial.strip() == "":
                st.error("Informe o número de série no formulário antes de salvar.")
            else:
                try:
                    zip_path = save_bundle(serial.strip(), st.session_state.photos, upload_git)
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
**Fluxo sugerido para 18 trafos:**
1) Para cada número de série, capture/adicione as fotos.
2) Marque "Enviar para GitHub" (se configurado) para persistir online.
3) Clique em "Salvar pacote do nº de série" para também baixar o ZIP local.
4) Avance para o próximo serial.

**Secrets (exemplo) – .streamlit/secrets.toml**

```
[github]
# token com escopo repo (NÃO comite este arquivo)
token = "ghp_xxx_somente_exemplo"
owner = "seu-usuario"
repo  = "seu-repo"
branch = "main"
base_path = "inspecoes"
```

**Observações:**
- Para repositório privado, o token precisa do escopo `repo`.
- Para muitos arquivos, o GitHub pode impor rate limit; o app comita arquivo a arquivo (simples e robusto).
- Se preferir, dá para acumular tudo num único commit criando um ZIP e enviando, mas perde a navegação por arquivos.
    """
)
