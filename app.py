import io
import os
import math
import zipfile
from typing import List

import requests
import streamlit as st
from PIL import Image
from datetime import datetime

# =====================================
# Configuração de página e tema
# =====================================
st.set_page_config(
    page_title="Zip & Envie para Telegram",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------- CSS custom (mobile-first, botões grandes, cards) ----------
CUSTOM_CSS = """
<style>
.main .block-container{max-width:820px;padding-top:1.4rem;padding-bottom:3rem}
.card{border:1px solid #e9ecef;border-radius:16px;padding:16px;margin:8px 0;background:rgba(255,255,255,0.75);backdrop-filter: blur(6px);} 
.card h3{margin-top:0}
.header{border-radius:20px;padding:20px 18px;margin-bottom:14px;color:#0f172a;background:linear-gradient(135deg,#e0f2fe 0%,#f1f5f9 100%);border:1px solid #e2e8f0}
.header h1{margin:0;font-size:1.55rem;}
.header p{margin:.25rem 0 0;color:#334155}
.thumb{border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;background:#fff}
.thumb img{display:block;width:100%;height:140px;object-fit:cover}
.thumb .meta{font-size:.80rem;color:#475569;padding:6px 8px}
@media (max-width: 640px){
  .stButton>button{width:100%; padding:12px 16px;font-size:1rem;border-radius:12px}
  .stDownloadButton>button{width:100%; padding:12px 16px;font-size:1rem;border-radius:12px}
}
div[role="alert"]{border-radius:12px}
.footer{position:fixed;left:0;right:0;bottom:0;padding:8px 14px;background:rgba(248,250,252,.9);border-top:1px solid #e2e8f0;backdrop-filter: blur(6px);}
.footer small{color:#64748b}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# =====================================
# Credenciais (secrets -> fallback env)
# =====================================
try:
    BOT_TOKEN = st.secrets["telegram"]["BOT_TOKEN"]
    CHAT_ID = st.secrets["telegram"]["CHAT_ID"]
    SOURCE = "secrets.toml"
except Exception:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    SOURCE = "env vars"

credenciais_ok = bool(BOT_TOKEN and CHAT_ID)

# =====================================
# Header
# =====================================
with st.container():
    st.markdown(
        """
        <div class=\"header\">
          <h1>📦 Zip & Envie Fotos para o Telegram</h1>
          <p>Selecione imagens da galeria ou tire fotos na hora, compacte em ZIP(s) e envie direto para um chat/grupo/canal.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Banner de credenciais
with st.container():
    if credenciais_ok:
        st.success(f"Credenciais encontradas ✅ (fonte: {SOURCE})")
    else:
        st.warning("Credenciais ausentes. Configure <BOT_TOKEN> e <CHAT_ID> em .streamlit/secrets.toml ou variáveis de ambiente.")

# =====================================
# Helpers
# =====================================

def sizeof_fmt(num: int) -> str:
    if num is None: return "0 B"
    for unit in ['B','KB','MB','GB','TB']:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

@st.cache_data(show_spinner=False)
def make_zip_in_memory(file_objs, filename: str, serial: str = "", compresslevel: int = 9) -> bytes:
    """Gera um ZIP em memória. Inclui MANIFESTO com número de série, data e lista de arquivos."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
        names = []
        for f in file_objs:
            fname = os.path.basename(f.name).replace(" ", "_")
            data = f.read(); f.seek(0)
            zf.writestr(fname, data)
            names.append(fname)
        # Manifesto com metadados do lote
        manifest = [
            f"SERIAL: {serial}",
            f"ARQUIVO_ZIP: {filename}",
            f"CRIADO_EM: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"QTD_ARQUIVOS: {len(names)}",
            "ARQUIVOS:",
            *[f"  - {n}" for n in names]
        ]
        zf.writestr("MANIFESTO.txt", "
".join(manifest))
    mem.seek(0)
    return mem.getvalue()


def send_zip_to_telegram(zip_bytes: bytes, filename: str, bot_token: str, chat_id: str, caption: str = ""):
    if not bot_token or not chat_id:
        raise ValueError("BOT_TOKEN ou CHAT_ID ausentes.")
    if len(zip_bytes) > 50 * 1024 * 1024:
        raise ValueError("ZIP acima de 50 MB (limite da Bot API). Habilite 'Auto dividir'.")
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files_payload = {"document": (filename, io.BytesIO(zip_bytes), "application/zip")}
    data = {"chat_id": chat_id, "caption": caption}
    resp = requests.post(url, data=data, files=files_payload, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"Falha no envio: {resp.status_code} - {resp.text}")
    j = resp.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram retornou erro: {j}")
    return j


def chunk_files_by_size(files, max_bytes=45*1024*1024):
    """Divide a lista de arquivos em lotes cuja soma de bytes não ultrapasse max_bytes."""
    batches, current, total = [], [], 0
    for f in files:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > max_bytes:
            if current:
                batches.append(current); current=[]; total=0
            batches.append([f])
            continue
        if total + size > max_bytes:
            batches.append(current)
            current, total = [f], size
        else:
            current.append(f); total += size
    if current:
        batches.append(current)
    return batches


def apply_serial_to_name(base_name: str, serial: str, part: int | None = None) -> str:
    """Insere o número de série no nome do ZIP. Ex.: fotos.zip -> fotos_NS-1234_parte01.zip"""
    root = base_name[:-4] if base_name.lower().endswith('.zip') else base_name
    tag = f"_NS-{serial.strip()}" if serial else ""
    suffix = f"_parte{part:02d}" if part else ""
    return f"{root}{tag}{suffix}.zip"

# =====================================
# Estado
# =====================================
if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None
if "zip_name" not in st.session_state:
    st.session_state.zip_name = None
if "camera_photos" not in st.session_state:
    st.session_state.camera_photos = []
if "serial" not in st.session_state:
    st.session_state.serial = ""
if "auto_increment_serial" not in st.session_state:
    st.session_state.auto_increment_serial = False

# =====================================
# UI principal (tabs)
# =====================================
with st.container():
    tabs = st.tabs(["🖼️ Galeria", "📷 Câmera", "⚙️ Opções", "❓ Ajuda"])

with tabs[0]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    files = st.file_uploader(
        "Selecione imagens (png, jpg, jpeg, webp, heic, heif)",
        type=["png","jpg","jpeg","webp","heic","heif"],
        accept_multiple_files=True,
        help="Dica: no iPhone/Android, segure para multiseleção."
    )
    if files:
        cols_n = 2 if len(files) <= 6 else 3
        cols = st.columns(cols_n)
        for i, f in enumerate(files):
            with cols[i % cols_n]:
                try:
                    img = Image.open(f).convert("RGB")
                    st.markdown('<div class="thumb">', unsafe_allow_html=True)
                    st.image(img, use_column_width=True)
                    size_attr = getattr(f, 'size', None)
                    st.markdown(f'<div class="meta">{os.path.basename(f.name)}<br><small>{sizeof_fmt(size_attr)}</small></div>', unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                except Exception:
                    st.markdown(f"• {f.name}")
    st.markdown('</div>', unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    photo = st.camera_input("Tire uma foto e ela será adicionada ao ZIP")
    if photo:
        st.session_state.camera_photos.append(photo)
        st.success("Foto adicionada à lista ✅")
    if st.session_state.get("camera_photos"):
        st.caption(f"Fotos da câmera nesta sessão: {len(st.session_state.camera_photos)}")
    st.markdown('</div>', unsafe_allow_html=True)

with tabs[2]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    default_zip_name = f"fotos_{datetime.now():%Y%m%d_%H%M%S}.zip"
    zip_name = st.text_input("Nome base do arquivo ZIP", value=st.session_state.get("zip_name") or default_zip_name, help="O número de série será anexado automaticamente.")
    serial = st.text_input("Número de série (NS)", value=st.session_state.get("serial") or "", placeholder="Ex.: 000123 ou TRF-2025-001")
    st.session_state.serial = serial
    auto_inc = st.toggle("Auto incrementar NS ao finalizar envio", value=st.session_state.get("auto_increment_serial", False))
    st.session_state.auto_increment_serial = auto_inc
    caption = st.text_input("Legenda (opcional)", value=f"Enviado via Streamlit em {datetime.now():%d/%m/%Y %H:%M}")
    auto_split = st.toggle("Auto dividir em múltiplos ZIPs se ultrapassar 50 MB", value=True, help="Cria e envia vários ZIPs (≈45 MB cada).")
    compress_level = st.slider("Compressão do ZIP", 0, 9, 9, help="9 = melhor compressão (mais lento)")
    preview_name = apply_serial_to_name(zip_name, serial)
    st.caption(f"Exemplo de nome final: **{preview_name}**")
    st.markdown('</div>', unsafe_allow_html=True)

with tabs[3]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(
        """
        **Como configurar os segredos (local):**

        ```toml
        [telegram]
        BOT_TOKEN = "123456:ABC..."
        CHAT_ID = "7557997151"      # privado
        # ou: CHAT_ID = "-1001234567890"  # grupo/canal
        ```

        **Rodar:**
        ```bash
        pip install -r requirements.txt
        streamlit run app.py
        ```

        **Dicas de uso no celular:**
        - Use a aba **📷 Câmera** para fotografar sem sair do app.
        - Botões grandes e layout empilhado facilitam o toque.
        - Pré-visualização em grade otimizada para telas pequenas.

        **Limites:** Bot API ≈ 50 MB por arquivo. Ative **Auto dividir** para lotes maiores.
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

# =====================================
# Ações (gerar / enviar)
# =====================================

def get_all_files() -> List:
    base = []
    if files:
        base.extend(files)
    if st.session_state.get("camera_photos"):
        base.extend(st.session_state.camera_photos)
    return base

col_gen, col_send = st.columns(2)

with col_gen:
    if st.button("🗜️ Gerar ZIP", use_container_width=True):
        selected = get_all_files()
        if not selected:
            st.warning("Selecione imagens na aba **Galeria** ou tire uma foto na aba **Câmera**.")
        else:
            with st.spinner("Compactando..."):
                final_name = apply_serial_to_name(zip_name, st.session_state.serial)
                bz = make_zip_in_memory(selected, final_name, serial=st.session_state.serial, compresslevel=compress_level)
                st.session_state.zip_bytes = bz
                st.session_state.zip_name = final_name
            st.success(f"ZIP gerado ({sizeof_fmt(len(st.session_state.zip_bytes))}).")
            st.download_button(
                "⬇️ Baixar ZIP",
                data=st.session_state.zip_bytes,
                file_name=st.session_state.zip_name,
                mime="application/zip",
                use_container_width=True,
            )

with col_send:
    if st.button("📤 Enviar para Telegram", use_container_width=True):
        if not credenciais_ok:
            st.error("Credenciais ausentes. Configure BOT_TOKEN e CHAT_ID.")
        else:
            selected = get_all_files()
            # Se já existe um ZIP gerado e auto_split off, envia direto
            if st.session_state.get("zip_bytes") and not auto_split:
                with st.spinner("Enviando ZIP..."):
                    try:
                        res = send_zip_to_telegram(st.session_state.zip_bytes, st.session_state.zip_name, BOT_TOKEN, CHAT_ID, caption)
                    except Exception as e:
                        st.error(f"Erro: {e}")
                    else:
                        st.success("Enviado com sucesso ✅")
                        st.json(res)
                        if st.session_state.auto_increment_serial and st.session_state.serial.isdigit():
                            st.session_state.serial = str(int(st.session_state.serial) + 1).zfill(len(st.session_state.serial))
            else:
                if not selected:
                    st.warning("Selecione imagens ou gere um ZIP primeiro.")
                else:
                    batches = chunk_files_by_size(selected)
                    progress = st.progress(0.0, text="Enviando lotes...")
                    total = len(batches)
                    sent = 0
                    for i, batch in enumerate(batches, start=1):
                        with st.spinner(f"Compactando lote {i}/{total}..."):
                            name_i = apply_serial_to_name(zip_name, st.session_state.serial, part=i)
                            zip_i = make_zip_in_memory(batch, name_i, serial=st.session_state.serial, compresslevel=compress_level)
                        try:
                            res = send_zip_to_telegram(zip_i, name_i, BOT_TOKEN, CHAT_ID, caption)
                        except Exception as e:
                            st.error(f"Falha ao enviar lote {i}: {e}")
                            break
                        else:
                            sent += 1
                            progress.progress(sent/total, text=f"Enviado {sent}/{total} lote(s)")
                            st.caption(f"✅ Lote {i} enviado ({sizeof_fmt(len(zip_i))}) — {name_i}")
                    if sent == total:
                        st.success("Todos os lotes foram enviados com sucesso ✅")
                        if st.session_state.auto_increment_serial and st.session_state.serial.isdigit():
                            st.session_state.serial = str(int(st.session_state.serial) + 1).zfill(len(st.session_state.serial))

# =====================================
# Toolbar secundária
# =====================================
left, right = st.columns(2)
with left:
    if st.button("🧹 Limpar seleção", use_container_width=True):
        st.session_state.zip_bytes = None
        st.session_state.zip_name = None
        st.session_state.camera_photos = []
        st.experimental_rerun()
with right:
    if st.button("🛠️ Testar credenciais", use_container_width=True):
        if not credenciais_ok:
            st.error("Configure BOT_TOKEN e CHAT_ID.")
        else:
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": "Teste simples via app ✅"},
                    timeout=30,
                )
                if r.ok and r.json().get("ok"):
                    st.success("Mensagem de teste enviada.")
                else:
                    st.error("Falha no teste de credenciais.")
                    st.code(r.text)
            except Exception as e:
                st.error(f"Erro ao testar credenciais: {e}")

# =====================================
# Footer
# =====================================
st.markdown(
    """
    <div class=\"footer\"><small>Feito com Streamlit • Suporte a câmera no mobile • Auto-divisão de lotes • Manifesto com Nº de Série • {dt}</small></div>
    """.format(dt=datetime.now().strftime("%d/%m/%Y %H:%M")),
    unsafe_allow_html=True,
)
