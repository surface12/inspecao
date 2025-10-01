import io
import os
import zipfile
import requests
import streamlit as st
from datetime import datetime

# --------------------
# Configuração / Segredos
# --------------------
# Defina em .streamlit/secrets.toml:
# [telegram]
# BOT_TOKEN = "123456:ABC..."
# CHAT_ID = "-1001234567890"  # seu chat privado ou grupo/canal

BOT_TOKEN = st.secrets.get("telegram", {}).get("BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", ""))
CHAT_ID = st.secrets.get("telegram", {}).get("CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))

st.set_page_config(page_title="Zip & Envia para Telegram", page_icon="📦", layout="centered")

st.title("📦 Zip & Envie Fotos para o Telegram")
st.write("Selecione várias fotos, gere um .zip e envie para o seu bot no Telegram.")

# --------------------
# Upload de arquivos
# --------------------
files = st.file_uploader(
    "Envie suas imagens (png, jpg, jpeg, webp)",
    type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
    accept_multiple_files=True,
)

zip_name_default = f"fotos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
zip_name = st.text_input("Nome do arquivo ZIP", value=zip_name_default)

col1, col2 = st.columns(2)
with col1:
    gerar = st.button("Gerar ZIP")
with col2:
    enviar = st.button("Gerar e Enviar para Telegram")

@st.cache_data(show_spinner=False)
def make_zip_in_memory(file_objs, zip_filename: str) -> bytes:
    """Compacta uma lista de arquivos enviados (UploadedFile) em um ZIP em memória."""
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in file_objs:
            # Normaliza nome
            fname = os.path.basename(f.name)
            # Algumas câmeras criam nomes com espaços/caracteres especiais
            fname = fname.replace(" ", "_")
            # Lê bytes do arquivo
            data = f.read()
            # Retorna o cursor do arquivo para início (caso seja reutilizado)
            f.seek(0)
            zf.writestr(fname, data)
    # Retorna bytes do zip
    mem_zip.seek(0)
    return mem_zip.getvalue()


def send_zip_to_telegram(zip_bytes: bytes, filename: str, bot_token: str, chat_id: str, caption: str = ""):
    """Envia um ZIP como documento para o Telegram usando a Bot API."""
    if not bot_token or not chat_id:
        raise ValueError("BOT_TOKEN ou CHAT_ID ausentes. Configure em st.secrets ou variáveis de ambiente.")

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files = {"document": (filename, io.BytesIO(zip_bytes), "application/zip")}
    data = {"chat_id": chat_id, "caption": caption}
    resp = requests.post(url, data=data, files=files, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Falha no envio: {resp.status_code} - {resp.text}")
    return resp.json()


if files and (gerar or enviar):
    with st.spinner("Gerando ZIP..."):
        try:
            zip_bytes = make_zip_in_memory(files, zip_name)
        except Exception as e:
            st.error(f"Erro ao gerar ZIP: {e}")
            st.stop()

    st.success("ZIP gerado com sucesso!")
    st.download_button("⬇️ Baixar ZIP", data=zip_bytes, file_name=zip_name, mime="application/zip")

    if enviar:
        caption = st.text_input("Legenda (opcional)", value=f"Enviado via Streamlit em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        go = st.button("Confirmar envio")
        if go:
            with st.spinner("Enviando para o Telegram..."):
                try:
                    result = send_zip_to_telegram(zip_bytes, zip_name, BOT_TOKEN, CHAT_ID, caption)
                except Exception as e:
                    st.error(f"Erro no envio: {e}")
                else:
                    st.success("Enviado com sucesso para o Telegram!")
                    st.json(result)

# --------------------
# Ajuda / Diagnóstico
# --------------------
with st.expander("⚙️ Diagnóstico / Como configurar"):
    st.markdown(
        """
        **1) Criar o bot e pegar o token**
        - No Telegram, fale com **@BotFather**
        - Comando `/newbot` → siga as instruções e copie o **BOT TOKEN**

        **2) Descobrir seu `chat_id`** (onde o ZIP será entregue)
        - Opção simples: adicione o bot a um **grupo**, envie uma mensagem qualquer no grupo e depois acesse:
          `https://api.telegram.org/botSEU_TOKEN/getUpdates` e procure por `chat":{"id": ...}
        - Para chat privado, inicie conversa com o bot e repita o `getUpdates`.

        **3) Colocar credenciais no Streamlit Cloud**
        - Vá em *Settings → Secrets* e cole:

          ```toml
          [telegram]
          BOT_TOKEN = "123456:ABC-DEF..."
          CHAT_ID = "-1001234567890"
          ```

        **4) Rodar localmente**
        ```bash
        pip install -r requirements.txt
        streamlit run app.py
        ```

        **Requisitos (requirements.txt)**
        ```
        streamlit>=1.37
        requests>=2.31
        ```

        **Notas**
        - Limite do Telegram: documentos até **50 MB** (em alguns clientes 2000 MB), mas via Bot API normalmente **50 MB** por arquivo; se seu ZIP for maior, divida-o.
        - Para fotos .heic/.heif, o app envia como estão. Se precisar converter para .jpg, faça a conversão antes do upload.
        - Segurança: nunca exponha o token do bot no código público; use `st.secrets`.
        - Se quiser enviar também como álbum de fotos (sem zip), use `sendMediaGroup` da Bot API.
        """
    )
