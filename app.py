import io
import os
import zipfile
import requests
import streamlit as st
from datetime import datetime

# --------------------
# Credenciais (secrets -> fallback env)
# --------------------
try:
    BOT_TOKEN = st.secrets["telegram"]["BOT_TOKEN"]
    CHAT_ID = st.secrets["telegram"]["CHAT_ID"]
except Exception:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

st.set_page_config(page_title="📦 Zip & Envie para o Telegram", page_icon="📦", layout="centered")
st.title("📦 Zip & Envie Fotos para o Telegram")
st.caption("Gere um .zip em memória com suas imagens e envie para um chat/grupo/canal do Telegram.")

# Indicador de credenciais
credenciais_ok = bool(BOT_TOKEN and CHAT_ID)
with st.container():
    if credenciais_ok:
        st.success("Credenciais encontradas ✅")
    else:
        st.info("Configure BOT_TOKEN e CHAT_ID em .streamlit/secrets.toml ou nas variáveis de ambiente.")

# --------------------
# Estado (para não perder o ZIP entre reruns)
# --------------------
if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None
if "zip_name" not in st.session_state:
    st.session_state.zip_name = None

# --------------------
# Upload + parâmetros
# --------------------
files = st.file_uploader(
    "Envie suas imagens (png, jpg, jpeg, webp, heic, heif)",
    type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
    accept_multiple_files=True,
)

default_zip_name = f"fotos_{datetime.now():%Y%m%d_%H%M%S}.zip"
zip_name = st.text_input("Nome do arquivo ZIP", value=default_zip_name)
caption = st.text_input("Legenda (opcional)", value=f"Enviado via Streamlit em {datetime.now():%d/%m/%Y %H:%M}")


# --------------------
# Utilidades
# --------------------
@st.cache_data(show_spinner=False)
def make_zip_in_memory(file_objs) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in file_objs:
            fname = os.path.basename(f.name).replace(" ", "_")
            data = f.read()
            f.seek(0)
            zf.writestr(fname, data)
    mem.seek(0)
    return mem.getvalue()


def send_zip_to_telegram(zip_bytes: bytes, filename: str, bot_token: str, chat_id: str, caption: str = ""):
    if not bot_token or not chat_id:
        raise ValueError("BOT_TOKEN ou CHAT_ID ausentes. Configure em st.secrets ou variáveis de ambiente.")
    # Limite típico da Bot API: ~50 MB por arquivo
    if len(zip_bytes) > 50 * 1024 * 1024:
        raise ValueError("ZIP acima de 50 MB. Divida em arquivos menores.")

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


# --------------------
# Ações (usa session_state para não perder o ZIP)
# --------------------
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Gerar ZIP"):
        if not files:
            st.warning("Selecione arquivos antes de gerar o ZIP.")
        else:
            with st.spinner("Gerando ZIP..."):
                st.session_state.zip_bytes = make_zip_in_memory(files)
                st.session_state.zip_name = zip_name
            st.success("ZIP gerado com sucesso!")

            st.download_button(
                "⬇️ Baixar ZIP",
                data=st.session_state.zip_bytes,
                file_name=st.session_state.zip_name,
                mime="application/zip",
            )

with col2:
    if st.button("Enviar para Telegram"):
        if not (st.session_state.zip_bytes and st.session_state.zip_name):
            st.warning("Gere o ZIP primeiro.")
        elif not credenciais_ok:
            st.error("Credenciais ausentes. Defina BOT_TOKEN e CHAT_ID.")
        else:
            with st.spinner("Enviando para o Telegram..."):
                try:
                    result = send_zip_to_telegram(
                        st.session_state.zip_bytes,
                        st.session_state.zip_name,
                        BOT_TOKEN,
                        CHAT_ID,
                        caption,
                    )
                except Exception as e:
                    st.error(f"Erro no envio: {e}")
                else:
                    st.success("Enviado com sucesso para o Telegram!")
                    st.json(result)

with col3:
    if st.button("Testar credenciais"):
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
                    st.success("Mensagem de teste enviada com sucesso.")
                    st.json(r.json())
                else:
                    st.error("Falha no teste de credenciais.")
                    st.code(r.text)
            except Exception as e:
                st.error(f"Erro ao testar credenciais: {e}")

# --------------------
# Ajuda / Diagnóstico
# --------------------
with st.expander("⚙️ Ajuda e Diagnóstico"):
    st.markdown(
        """
        **Como configurar os segredos (local):**

        Crie `.streamlit/secrets.toml` na raiz do projeto com:

        ```toml
        [telegram]
        BOT_TOKEN = "123456:ABC..."
        CHAT_ID = "7557997151"      # privado
        # ou: CHAT_ID = "-1001234567890"  # grupo/canal
        ```

        **Rodar localmente:**

        ```bash
        pip install -r requirements.txt
        streamlit run app.py
        ```

        **Limite de tamanho:** a Bot API aceita ~50 MB por arquivo. Se o ZIP passar disso, divida-o.

        **Se não chegar no Telegram:**
        - Confirme que o teste de credenciais funciona (botão acima).
        - Em chat privado, envie `/start` para o bot.
        - Em grupo, adicione o bot (desative privacy no @BotFather se necessário) e envie nova mensagem.
        - Em canal, promova o bot a **admin**.
        - Verifique o `CHAT_ID` (grupos/canais costumam começar com `-100`).
        - Veja o JSON de erro retornado no app.

        **Dica:** Se aparecer aviso `NotOpenSSLWarning` no macOS, é só um *warning*. Opcionalmente, atualize para Python 3.11+ ou use `pip install "urllib3<2"`.
        """
    )
