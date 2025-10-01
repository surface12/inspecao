import io
import os
import re # Importado para a função de auto-incremento
import zipfile
from typing import List, Tuple, Optional, Set
import requests
import streamlit as st
from PIL import Image
from datetime import datetime

# =====================================
# Configuração de Página e Tema
# =====================================
st.set_page_config(
    page_title="Zip & Envie para Telegram",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------- CSS custom (mobile-first) ----------
# (Seu CSS original foi mantido, omitido aqui para brevidade)
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

CREDENCIAIS_OK = bool(BOT_TOKEN and CHAT_ID)

# =====================================
# Header
# =====================================
st.markdown("""
<div class="header">
  <h1>📦 Zip & Envie Fotos para o Telegram</h1>
  <p>Compacte fotos (com Nº de Série no nome de cada arquivo) e envie direto para um chat/grupo/canal no Telegram.</p>
</div>
""", unsafe_allow_html=True)

if not CREDENCIAIS_OK:
    st.error("Credenciais do Telegram ausentes! Configure as variáveis de ambiente ou o `secrets.toml`.", icon="🚨")
else:
    st.success(f"Credenciais do Telegram carregadas com sucesso. (Fonte: {SOURCE})", icon="✅")

# =====================================
# Funções Utilitárias (Seu código original, sem alterações)
# =====================================
def sizeof_fmt(num: Optional[int]) -> str:
    if not num: return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0: return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def split_name_ext(name: str) -> Tuple[str, str]:
    base = os.path.basename(name)
    root, ext = os.path.splitext(base)
    return (root, ext.lower())

def slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)

def unique_photo_name(original_name: str, serial: str, counter: int) -> str:
    root, ext = split_name_ext(original_name or "camera-input.png")
    if ext == "": ext = ".png"
    root = slugify(root)[:40] or "foto"
    serial_tag = f"NS-{slugify(serial)}_" if serial else ""
    return f"{serial_tag}{root}_{counter:03d}{ext}"

def ensure_unique(name: str, used: Set[str]) -> str:
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
    if ext != ".zip": ext = ".zip"
    tag = f"_NS-{slugify(serial)}" if serial else ""
    suffix = f"_parte{part:02d}" if part else ""
    root = slugify(root) or "fotos"
    return f"{root}{tag}{suffix}{ext}"

def try_convert_heic_to_jpg(buffer: bytes) -> Tuple[bytes, bool]:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img = Image.open(io.BytesIO(buffer)).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        out.seek(0)
        return out.getvalue(), True
    except Exception:
        return buffer, False

def make_zip_in_memory(
    file_objs,
    filename: str,
    serial: str = "",
    convert_heic: bool = False,
    compresslevel: int = 9
) -> bytes:
    mem = io.BytesIO()
    used_names: Set[str] = set()
    listed_names: List[str] = []

    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
        for idx, f in enumerate(file_objs, start=1):
            orig = getattr(f, "name", "camera-input.png")
            name = unique_photo_name(orig, serial, idx)
            name = ensure_unique(name, used_names)

            data = f.read()
            f.seek(0)

            _, ext = split_name_ext(name)
            if convert_heic and ext in (".heic", ".heif"):
                data, converted = try_convert_heic_to_jpg(data)
                if converted:
                    name = name.rsplit(ext, 1)[0] + ".jpg"

            zf.writestr(name, data)
            listed_names.append(name)

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
        raise ValueError("ZIP acima de 50 MB (limite da Bot API do Telegram).")
    
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files_payload = {"document": (filename, io.BytesIO(zip_bytes), "application/zip")}
    data = {"chat_id": chat_id, "caption": caption}
    
    resp = requests.post(url, data=data, files=files_payload, timeout=90)
    resp.raise_for_status() # Lança exceção para erros HTTP (4xx ou 5xx)
    
    j = resp.json()
    if not j.get("ok"):
        raise RuntimeError(f"O Telegram retornou um erro: {j.get('description', 'sem detalhes')}")
    return j

def chunk_files_by_size(files, max_bytes=45 * 1024 * 1024):
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
                current, total = [], 0
            batches.append([f])
            continue
        
        if total + size > max_bytes and current:
            batches.append(current)
            current, total = [f], size
        else:
            current.append(f)
            total += size
            
    if current:
        batches.append(current)
        
    return batches

# =====================================
# Lógica Adicional
# =====================================
def increment_serial(serial_str: str) -> str:
    """Encontra o último número no NS e o incrementa, preservando o preenchimento com zeros."""
    match = re.search(r'(\d+)$', serial_str)
    if not match:
        return serial_str # Retorna original se não houver número no final
    
    number_part = match.group(1)
    prefix = serial_str[:-len(number_part)]
    next_number = int(number_part) + 1
    
    # Mantém o mesmo número de dígitos (zero-padding)
    return f"{prefix}{str(next_number).zfill(len(number_part))}"

# Checa se o conversor de HEIC está disponível
try:
    import pillow_heif
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

# =====================================
# Estado da Sessão
# =====================================
if "camera_photos" not in st.session_state: st.session_state.camera_photos = []
if "serial" not in st.session_state: st.session_state.serial = ""
if "auto_increment_serial" not in st.session_state: st.session_state.auto_increment_serial = False
if "last_used_zip_name" not in st.session_state: st.session_state.last_used_zip_name = ""

# =====================================
# Interface do Usuário (UI)
# =====================================
tabs = st.tabs(["🖼️ Adicionar Arquivos", "⚙️ Opções", "❓ Ajuda"])

with tabs[0]:
    # Unificado para galeria e câmera
    st.subheader("1. Adicione suas fotos")
    files = st.file_uploader(
        "Upload de arquivos da galeria",
        type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
        accept_multiple_files=True,
        help="Dica: Em celulares, segure para selecionar múltiplos arquivos.",
    )
    
    photo = st.camera_input("Tire uma foto com a câmera")
    if photo:
        st.session_state.camera_photos.append(photo)

    # Combina as duas fontes de arquivos
    todos_os_arquivos = (files or []) + st.session_state.camera_photos
    
    if todos_os_arquivos:
        total_size = sum(f.getbuffer().nbytes for f in todos_os_arquivos)
        st.info(f"**{len(todos_os_arquivos)}** arquivo(s) na fila. Tamanho total: **{sizeof_fmt(total_size)}**")
    
    if st.session_state.camera_photos:
        if st.button("Limpar fotos da câmera"):
            st.session_state.camera_photos.clear()
            st.rerun()

with tabs[1]:
    st.subheader("2. Defina as opções do envio")
    default_zip_name = f"fotos_{datetime.now():%Y%m%d_%H%M}.zip"
    
    st.session_state.serial = st.text_input(
        "Número de Série (NS)", 
        value=st.session_state.serial, 
        placeholder="Ex: EQ-00123 ou OS-2025-45"
    )
    
    base_zip_name = st.text_input("Nome base do arquivo ZIP", 
        value=st.session_state.get("last_used_zip_name") or default_zip_name
    )
    st.session_state.last_used_zip_name = base_zip_name
        
    caption = st.text_area(
        "Legenda para a mensagem no Telegram", 
        value=f"Fotos do NS {st.session_state.serial}.\nEnviado em {datetime.now():%d/%m/%Y %H:%M}."
    )
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.auto_increment_serial = st.toggle(
            "Incrementar NS após envio", 
            value=st.session_state.auto_increment_serial,
            help="Se o NS terminar com um número (ex: 'ABC-009'), ele se tornará 'ABC-010' após um envio bem-sucedido."
        )
        auto_split = st.toggle("Dividir ZIP > 50 MB", value=True, help="Divide o envio em múltiplos arquivos ZIP para não exceder o limite do Telegram.")
    with col2:
        convert_heic = st.toggle(
            "Converter HEIC para JPEG", 
            value=True, 
            disabled=not HEIC_SUPPORT,
            help="Converte imagens .heic/.heif para .jpg. Requer a biblioteca pillow-heif."
        )
        if not HEIC_SUPPORT:
            st.caption("Instale `pillow-heif` para habilitar.")
            
    compress_level = st.slider("Nível de compressão", 0, 9, 9, help="0 = sem compressão, 9 = máxima compressão.")
    st.caption(f"Exemplo de nome final: **{apply_serial_to_zipname(base_zip_name, st.session_state.serial)}**")
    
with tabs[2]:
    st.markdown("""
    **Como usar:**
    1.  **Adicionar Arquivos**: Faça upload de imagens ou tire fotos com a câmera. Elas serão adicionadas a uma fila.
    2.  **Opções**: Defina o Número de Série (NS), o nome do arquivo ZIP e a legenda da mensagem.
    3.  **Processar e Enviar**: Clique no botão principal abaixo para compactar tudo e enviar para o Telegram.

    **Configuração (`.streamlit/secrets.toml`):**
    ```toml
    [telegram]
    BOT_TOKEN = "SEU_TOKEN_AQUI"
    CHAT_ID = "ID_DO_CHAT_AQUI" # Pode ser um ID de usuário, grupo ou canal
    ```
    """)

# =====================================
# Ação Principal
# =====================================
st.markdown("---")
st.subheader("3. Processe e envie")

if st.button("Compactar e Enviar para o Telegram", type="primary", use_container_width=True, disabled=not todos_os_arquivos or not CREDENCIAIS_OK):
    
    # Validações iniciais
    if not st.session_state.serial:
        st.error("O campo 'Número de Série (NS)' é obrigatório.", icon="🚨")
        st.stop()

    # Define os lotes de arquivos
    if auto_split:
        batches = chunk_files_by_size(todos_os_arquivos)
    else:
        batches = [todos_os_arquivos]
    
    total_batches = len(batches)
    success_count = 0
    
    with st.spinner(f"Processando {len(todos_os_arquivos)} arquivo(s)..."):
        for i, batch_files in enumerate(batches, start=1):
            is_multipart = total_batches > 1
            part_num = i if is_multipart else None
            
            progress_text = f"Processando lote {i} de {total_batches}..."
            st.info(progress_text)
            
            try:
                # 1. Gerar nome do ZIP
                zip_name = apply_serial_to_zipname(base_zip_name, st.session_state.serial, part=part_num)
                
                # 2. Criar o ZIP em memória
                zip_bytes = make_zip_in_memory(
                    file_objs=batch_files,
                    filename=zip_name,
                    serial=st.session_state.serial,
                    convert_heic=convert_heic,
                    compresslevel=compress_level
                )
                
                # 3. Enviar para o Telegram
                final_caption = f"Parte {part_num}\n\n{caption}" if is_multipart else caption
                send_zip_to_telegram(zip_bytes, zip_name, BOT_TOKEN, CHAT_ID, final_caption)
                
                st.success(f"Lote {i} enviado com sucesso como '{zip_name}'!", icon="🎉")
                success_count += 1

            except Exception as e:
                st.error(f"Falha ao enviar o lote {i}: {e}", icon="🔥")
                # Interrompe o processo se um lote falhar
                break

    # Lógica pós-envio
    if success_count == total_batches:
        st.balloons()
        st.header("Envio concluído com sucesso!")

        # Auto-incremento do NS, se habilitado
        if st.session_state.auto_increment_serial:
            novo_serial = increment_serial(st.session_state.serial)
            st.session_state.serial = novo_serial
            st.info(f"Número de série incrementado para: **{novo_serial}**")

        # Limpa a fila de arquivos
        st.session_state.camera_photos.clear()
        # O 'files' do uploader já é limpo automaticamente no rerun,
        # mas limpamos a lista combinada para evitar confusão.
        todos_os_arquivos.clear()
        
        st.info("A fila de arquivos foi limpa. Pronto para o próximo envio.")
        st.button("Ok, recarregar") # Botão para forçar o rerun e limpar a UI
