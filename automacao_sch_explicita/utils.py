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

POLL_RAPIDO = 0.08
TIMEOUT_CARREGAMENTO_RAPIDO = 1.2
TIMEOUT_CARREGAMENTO_NORMAL = 3.0


def aguardar_enter(mensagem):
    input(f"{mensagem}\nPressione Enter para continuar...")


def _documento_pronto(driver):
    """
    Considera a página pronta quando o documento principal terminou
    de carregar.

    Em caso de falha na consulta, retorna False para evitar que a
    automação avance antes da hora.
    """
    try:
        estado = driver.execute_script(
            "return document.readyState || '';"
        )
        return estado in {"interactive", "complete"}
    except Exception:
        return False


def _ajax_primefaces_pronto(driver):
    """
    Verifica se ainda há requisições AJAX do jQuery ou do PrimeFaces.

    O SCH usa atualizações AJAX que não alteram document.readyState.
    """
    script = """
    try {
        if (
            window.jQuery &&
            typeof window.jQuery.active === 'number' &&
            window.jQuery.active > 0
        ) {
            return false;
        }
    } catch (e) {}

    try {
        if (
            window.PrimeFaces &&
            PrimeFaces.ajax &&
            PrimeFaces.ajax.Queue &&
            typeof PrimeFaces.ajax.Queue.isEmpty === 'function' &&
            !PrimeFaces.ajax.Queue.isEmpty()
        ) {
            return false;
        }
    } catch (e) {}

    return true;
    """

    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def esperar_tela_carregar(
    driver,
    tempo_extra=0.0,
    timeout=None,
    exigir_estabilidade=False,
):
    """
    Executa uma espera genérica e leve para o SCH.

    A função verifica somente:
    1. document.readyState;
    2. fila AJAX do jQuery/PrimeFaces.

    Não procura loaders, spinners ou textos genéricos na página, pois isso
    causava falsos positivos e esperas desnecessárias de vários segundos.

    As funções específicas do fluxo continuam responsáveis por confirmar:
    - iframe disponível;
    - botão clicável;
    - aba aberta;
    - tabela carregada;
    - campo visível;
    - modal exibido.

    Parâmetros:
    - tempo_extra: pausa adicional solicitada explicitamente pelo fluxo;
    - timeout: limite da espera genérica;
    - exigir_estabilidade: quando True, exige duas confirmações consecutivas.
      O padrão é False para priorizar velocidade.
    """
    if timeout is None:
        timeout = (
            TIMEOUT_CARREGAMENTO_RAPIDO
            if MODO_RAPIDO
            else TIMEOUT_CARREGAMENTO_NORMAL
        )

    try:
        timeout = max(0.1, float(timeout))
    except Exception:
        timeout = (
            TIMEOUT_CARREGAMENTO_RAPIDO
            if MODO_RAPIDO
            else TIMEOUT_CARREGAMENTO_NORMAL
        )

    confirmacoes_necessarias = 2 if exigir_estabilidade else 1
    confirmacoes = 0

    def tela_pronta(d):
        nonlocal confirmacoes

        pronto = (
            _documento_pronto(d)
            and _ajax_primefaces_pronto(d)
        )

        if pronto:
            confirmacoes += 1
        else:
            confirmacoes = 0

        return confirmacoes >= confirmacoes_necessarias

    try:
        WebDriverWait(
            driver,
            timeout,
            poll_frequency=POLL_RAPIDO,
        ).until(tela_pronta)
    except Exception:
        # Esta é apenas uma espera genérica.
        # A função específica seguinte validará o elemento necessário.
        pass

    try:
        tempo = max(0.0, float(tempo_extra or 0))
    except Exception:
        tempo = 0.0

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
