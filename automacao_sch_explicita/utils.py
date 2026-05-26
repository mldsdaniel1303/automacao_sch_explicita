import json
import os
import time
from pathlib import Path

from selenium.webdriver.support.ui import WebDriverWait


MODO_RAPIDO = os.getenv("AUTOMACAO_SCH_MODO_RAPIDO", "1").strip().lower() not in {
    "0",
    "false",
    "nao",
    "não",
    "n",
}

POLL_RAPIDO = 0.05
TIMEOUT_CARREGAMENTO_RAPIDO = 1.2
TIMEOUT_CARREGAMENTO_NORMAL = 4.0


def aguardar_enter(mensagem):
    input(f"{mensagem}\nPressione Enter para continuar...")


def _documento_pronto(driver):
    try:
        estado = driver.execute_script("return document.readyState")
        return estado in {"interactive", "complete"}
    except Exception:
        return True


def _existe_loading_visivel(driver):
    """
    Detecta loaders visíveis sem depender de XPath pesado.

    Evita o problema de procurar por:
    //*[contains(., 'Carregando')]
    porque esse XPath pode bater no body inteiro e atrasar a automação.
    """
    script = """
    const elementos = Array.from(document.querySelectorAll('body *'));

    function visivel(el) {
        const st = window.getComputedStyle(el);
        if (!st) return false;
        if (st.display === 'none') return false;
        if (st.visibility === 'hidden') return false;
        if (parseFloat(st.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    for (const el of elementos) {
        if (!visivel(el)) continue;

        const cls = (el.className || '').toString().toLowerCase();
        const id = (el.id || '').toString().toLowerCase();
        const texto = (el.innerText || el.textContent || '').trim().toLowerCase();

        const marcador = cls + ' ' + id;

        if (
            marcador.includes('loading') ||
            marcador.includes('spinner') ||
            marcador.includes('overlay') ||
            marcador.includes('blockui') ||
            marcador.includes('ui-widget-overlay') ||
            marcador.includes('modal-backdrop')
        ) {
            return true;
        }

        if (
            texto === 'carregando' ||
            texto === 'processando' ||
            texto === 'aguarde' ||
            texto === 'loading' ||
            texto === 'please wait'
        ) {
            return true;
        }
    }

    return false;
    """

    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def esperar_tela_carregar(driver, tempo_extra=0.0, timeout=None):
    """
    Espera inteligente e rápida.

    Antes:
    - Procurava vários XPaths.
    - Depois sempre dormia tempo_extra.

    Agora:
    - Aguarda document.readyState.
    - Aguarda loader visível sumir.
    - Em modo rápido, limita o sleep final a no máximo 0.05s.
    """
    if timeout is None:
        timeout = TIMEOUT_CARREGAMENTO_RAPIDO if MODO_RAPIDO else TIMEOUT_CARREGAMENTO_NORMAL

    try:
        WebDriverWait(driver, timeout, poll_frequency=POLL_RAPIDO).until(
            lambda d: _documento_pronto(d) and not _existe_loading_visivel(d)
        )
    except Exception:
        pass

    try:
        tempo = float(tempo_extra or 0)
    except Exception:
        tempo = 0

    if MODO_RAPIDO:
        tempo = min(tempo, 0.05)

    if tempo > 0:
        time.sleep(tempo)


def salvar_json(caminho, dados):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def carregar_regras(caminho="config/regras.json"):
    base_dir = Path(__file__).resolve().parent
    caminho_regras = base_dir / caminho

    with open(caminho_regras, "r", encoding="utf-8") as f:
        return json.load(f)


def nome_seguro(texto):
    texto = str(texto or "")
    proibidos = '<>:"/\\|?*'

    for c in proibidos:
        texto = texto.replace(c, "_")

    return texto.strip() or "sem_nome"