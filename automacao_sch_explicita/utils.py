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
TIMEOUT_CARREGAMENTO_RAPIDO = 3.0
TIMEOUT_CARREGAMENTO_NORMAL = 6.0


def aguardar_enter(mensagem):
    input(f"{mensagem}\nPressione Enter para continuar...")


def _documento_pronto(driver):
    """
    Considera a página pronta somente quando o documento principal terminou
    de carregar completamente.

    Em caso de falha na consulta, retorna False para evitar que a automação
    avance antes da hora.
    """
    try:
        estado = driver.execute_script(
            "return document.readyState || '';"
        )
        return estado == "complete"
    except Exception:
        return False


def _ajax_primefaces_pronto(driver):
    """
    Verifica se ainda há requisições AJAX do jQuery ou do PrimeFaces.

    O SCH usa atualizações AJAX que não alteram document.readyState.
    Por isso, essa verificação é necessária antes de procurar novos elementos.
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


def _existe_loading_visivel(driver):
    """
    Detecta indicadores reais de carregamento visíveis.

    Evita pesquisar todo o body com XPath pesado e não considera qualquer
    overlay como carregamento, pois o SCH pode manter overlays legítimos
    durante modais e telas de edição.
    """
    script = """
    const seletores = [
        '.ui-blockui:not([style*="display: none"])',
        '.ui-blockui-content:not([style*="display: none"])',
        '.ui-loading:not([style*="display: none"])',
        '.ui-spinner:not([style*="display: none"])',
        '.loading:not([style*="display: none"])',
        '.spinner:not([style*="display: none"])',
        '[id*="loading"]:not([style*="display: none"])',
        '[class*="loading"]:not([style*="display: none"])'
    ];

    function visivel(el) {
        if (!el) return false;

        const st = window.getComputedStyle(el);

        if (!st) return false;
        if (st.display === 'none') return false;
        if (st.visibility === 'hidden') return false;
        if (Number(st.opacity || 1) === 0) return false;

        const rect = el.getBoundingClientRect();

        return rect.width > 0 && rect.height > 0;
    }

    for (const seletor of seletores) {
        let elementos = [];

        try {
            elementos = document.querySelectorAll(seletor);
        } catch (e) {
            continue;
        }

        for (const el of elementos) {
            if (visivel(el)) {
                return true;
            }
        }
    }

    const textosLoading = new Set([
        'carregando',
        'processando',
        'aguarde',
        'loading',
        'please wait'
    ]);

    const elementosTexto = document.querySelectorAll(
        'span, div, p, label'
    );

    for (const el of elementosTexto) {
        if (!visivel(el)) continue;

        const texto = String(
            el.innerText ||
            el.textContent ||
            ''
        ).trim().toLowerCase();

        if (textosLoading.has(texto)) {
            return true;
        }
    }

    return false;
    """

    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def esperar_tela_carregar(
    driver,
    tempo_extra=0.0,
    timeout=None,
    exigir_estabilidade=True,
):
    """
    Aguarda a estabilização da tela do SCH.

    Verifica:
    1. document.readyState completo;
    2. fila AJAX do jQuery/PrimeFaces vazia;
    3. loaders visíveis encerrados;
    4. duas confirmações consecutivas de estabilidade.

    O tempo_extra informado pelo fluxo é respeitado. Ele não é mais reduzido
    automaticamente para 0,05 segundo no modo rápido.
    """
    if timeout is None:
        timeout = (
            TIMEOUT_CARREGAMENTO_RAPIDO
            if MODO_RAPIDO
            else TIMEOUT_CARREGAMENTO_NORMAL
        )

    confirmacoes_necessarias = 2 if exigir_estabilidade else 1
    confirmacoes = 0

    def tela_estavel(d):
        nonlocal confirmacoes

        pronto = (
            _documento_pronto(d)
            and _ajax_primefaces_pronto(d)
            and not _existe_loading_visivel(d)
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
        ).until(tela_estavel)

    except Exception:
        print(
            "[SCH][WARN] A tela não confirmou estabilidade dentro de "
            f"{float(timeout):.1f}s."
        )

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
