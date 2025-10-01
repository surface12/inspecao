import io
import os
import zipfile
from typing import List, Tuple, Optional, Set
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

# ---------- CSS custom (mobile-first) ----------
st.markdown("""
<style>
.main .block-container{max-width:820px;padding-top:1.4rem;padding-bottom:3rem}
.card{border:1px solid #e9ecef;border-radius:16px;padding:16px;margin:8px 0;background:rgba(255,255,255,0.75);backdrop-filter: blur(6px);} 
.header{border-radius:20px;padding:20px 18px;margin-bottom:14px;color:#0f172a;background:linear-gradient(135deg,#e0f2fe 0%,#f1f5f9 100%);border:1px solid #e2e8f0}
.header h1{margin:0;font-size:1.55rem;}
.header p{margin:.25rem 0 0;color:#334155}
@media (max-width: 640px){
  .stButton>button,.stDownloadButton>button{width:100%; padding:12px 16px;font-size:1rem;border-radius:12px}
}
div[role="alert"]{border-radius:12px}
.footer{position:fixed;left:0;right:0;bottom:0;padding:8px 14px;background:rgba(248,250,252,.9);border-top:1px solid #e2e8f0;backdrop-filter: blur(6px);}
.footer small{color:#64748b}
</style>
""", unsafe_allow_html=True)

# =====================================
# Credenciais (secrets -> env)
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
st.markdown("""
<div class="header">
  <h1>📦 Zip & Envie Fotos para o Telegram</h1>
  <p>Compacte fotos (com Nº de Série no nome de cada arquivo) e envie direto para um chat/grupo/canal no Telegram.</p>
</div>
""", unsafe_allow_html=True)

if credenciais_ok:
    st.success(f"Credenciais encontradas ✅ (fonte: {SOURCE})")
else:
    st.warning("Credenciais ausentes. Configure BOT_TOKEN e CHAT_ID.")

# =====================================
# Utilidades
# =====================================
def sizeof_fmt(num: Optional[int]) -> str:
    if not num:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def split_name_ext(name: str) -> Tuple[str, str]:
    base = os.path.basename(name)
    root, ext = os.path.splitext(base)
    return (root, ext.lower())

def slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)

def unique_photo_name(original_name: str, serial: str, counter: int) -> str:
    """Gera nome único e prefixado com NS: NS-<serial>_<root>_<###><ext>."""
    root, ext = split_name_ext(original_name or "camera-input.png")
    if ext == "":
        ext = ".png"  # camera_input geralmente é PNG
    root = slugify(root)[:40] or "foto"
    serial_tag = f"NS-{slugify(serial)}_" if serial else ""
    return f"{serial_tag}{root}_{counter:03d}{ext}"

def ensure_unique(name: str, used: Set[str]) -> str:
    """Evita colisão dentro do ZIP."""
    if name not in used:
        used.add(name)
        return name
    root, ext = split_name_ext(name)
    i = 2
    new_name = f"{root}({i}){ext}"
    while new_name in used:
        i += 1
        new_name = f"{root}({i}){ext}"
    used.add(new_name)
    return new_name

def apply_serial_to_zipname(base_zip: str, serial: str, part: Optional[int] = None) -> str:
    root, ext = split_name_ext(base_zip if base_zip else "fotos.zip")
    if ext != ".zip":
        ext = ".zip"
    tag = f"_NS-{slugify(serial)}" if serial else ""
    suffix = f"_parte{part:02d}" if part else ""
    root = slugify(root) or "fotos"
    return f"{root}{tag}{suffix}{ext}"

def try_convert_heic_to_jpg(buffer: bytes) -> bytes:
    """Converte HEIC/HEIF → JPG se pillow-heif estiver disponível; caso contrário, retorna original."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img = Image.open(io.BytesIO(buffer)).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        out.seek(0)
        return out.getvalue()
    except Exception:
        return buffer  # sem conversão se falhar

def make_zip_in_memory(
    file_objs,
    filename: str,
    serial: str = "",
    convert_heic: bool = False,
    compresslevel: int = 9
) -> bytes:
    """Gera um ZIP em memória. Prefixa cada foto com NS e adiciona MANIFESTO.txt."""
    mem = io.BytesIO()
    used_names: Set[str] = set()
    listed_names: List[str] = []

    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
        for idx, f in enumerate(file_objs, start=1):
            # Definir nome único + prefixo NS
            orig = getattr(f, "name", "camera-input.png")
            name = unique_photo_name(orig, serial, idx)
            name = ensure_unique(name, used_names)

            # Leitura dos bytes
            data = f.read()
            f.seek(0)

            # Conversão HEIC/HEIF se habilitada
            _, ext = split_name_ext(name)
            if convert_heic and ext in (".heic", ".heif"):
                data = try_convert_heic_to_jpg(data)
                name = name.rsplit(ext, 1)[0] + ".jpg"

            # Escreve no ZIP
            zf.writestr(name, data)
            listed_names.append(name)

        # Manifesto
        manifest = [
            f"SERIAL: {serial}",
            f"ARQUIVO_ZIP: {filename}",
            f"CRIADO_EM: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"QTD_ARQUIVOS: {len(listed_names)}",
            "ARQUIVOS:",
            *[f"  - {n}" for n in listed_names],
        ]
        zf.writestr("MANIFESTO.txt", "\n".join(manifest))

    mem.seek(0)
    return mem.getvalue()

def send_zip_to_telegram(zip_bytes: bytes, filename: str, bot_token: str, chat_id: str, caption: str = ""):
    if not bot_token or not chat_id:
        raise ValueError("BOT_TOKEN ou CHAT_ID ausentes.")
    if len(zip_bytes) > 50 * 1024 * 1024:
        raise ValueError("ZIP acima de 50 MB (limite da Bot API).")
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

def chunk_files_by_size(files, max_bytes=45 * 1024 * 1024):
    """Divide arquivos em lotes cuja soma não exceda max_bytes (para contornar limite da Bot API)."""
    batches: List[List] = []
    current: List = []
    total = 0
    for f in files:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > max_bytes:
            if current:
                batches.append(current)
                current = []
                total = 0
            batches.append([f])
            continue
        if total + size > max_bytes:
            batches.append(current)
            current, total = [f], size
        else:
            current.append(f)
            total += size
    if current:
        batches.append(current)
    return batches

# =====================================
# Estado
# =====================================
if "zip_bytes" not in st.session_state: st.session_state.zip_bytes = None
if "zip_name" not in st.session_state: st.session_state.zip_name = None
if "camera_photos" not in st.session_state: st.session_state.camera_photos = []
if "serial" not in st.session_state: st.session_state.serial = ""
if "auto_increment_serial" not in st.session_state: st.session_state.auto_increment_serial = False

# =====================================
# UI principal
# =====================================
tabs = st.tabs(["🖼️ Galeria", "📷 Câmera", "⚙️ Opções", "❓ Ajuda"])

with tabs[0]:
    files = st.file_uploader(
        "Selecione imagens (png, jpg, jpeg, webp, heic, heif)",
        type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
        accept_multiple_files=True,
        help="Dica: segure para multiseleção no iPhone/Android.",
    )
    if files:
        st.caption(f"{len(files)} arquivo(s) selecionado(s).")

with tabs[1]:
    photo = st.camera_input("Tire uma foto (repita para várias)")
    if photo:
        # Cada clique gera um UploadedFile. Guardamos todos.
        st.session_state.camera_photos.append(photo)
        st.success(f"Foto adicionada ✅ (total: {len(st.session_state.camera_photos)})")
    if st.session_state.camera_photos:
        st.caption(f"Fotos da câmera nesta sessão: {len(st.session_state.camera_photos)}")

with tabs[2]:
    default_zip_name = f"fotos_{datetime.now():%Y%m%d_%H%M%S}.zip"
    base_zip_name = st.text_input("Nome base do ZIP", value=st.session_state.get("zip_name") or default_zip_name)
    serial = st.text_input("Número de série (NS)", value=st.session_state.get("serial") or "", placeholder="Ex.: 000123 ou TRF-2025-001")
    st.session_state.serial = serial
    auto_inc = st.toggle("Auto incrementar NS ao finalizar envio", value=st.session_state.get("auto_increment_serial", False))
    st.session_state.auto_increment_serial = auto_inc
    caption = st.text_input("Legenda", value=f"Enviado em {datetime.now():%d/%m/%Y %H:%M}")
    auto_split = st.toggle("Auto dividir se ultrapassar 50 MB", value=True)
    convert_heic = st.toggle("Converter HEIC/HEIF para JPEG (requer pillow-heif)", value=False,
                             help="Se não instalado, os HEIC serão mantidos como estão.")
    compress_level = st.slider("Compressão do ZIP", 0, 9, 9)
    st.caption(f"Exemplo de nome final: **{apply_serial_to_zipname(base_zip_name, serial)}**")

with tabs[3]:
    st.markdown('''
**Configuração local (.streamlit/secrets.toml):**
```toml
[telegram]
BOT_TOKEN = "123456:ABC..."
CHAT_ID = "7557997151"      # privado
# ou: CHAT_ID = "-1001234567890"  # grupo/canal
