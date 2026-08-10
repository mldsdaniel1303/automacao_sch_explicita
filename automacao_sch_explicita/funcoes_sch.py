import re
import shutil
import time
import unicodedata

from pathlib import Path
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

from utils import esperar_tela_carregar, nome_seguro

XPATH_IFRAME_DETALHE = (
    "//iframe[@id='__frameDetalhe' or @name='__frameDetalhe' "
    "or contains(@src,'/analise/requerimento')]"
)

XPATH_TABELA_FILA = (
    "//table[.//th[contains(., 'Requerimento')] "
    "or .//td[contains(., 'Requerimento')]]"
)

XPATHS_TABELA_ANEXOS = [
    "//table[.//th[normalize-space()='ID'] and .//th[contains(., 'Anexo')]]",
    "//table[.//th[contains(., 'Tipo de Documento')] and .//th[contains(., 'Anexo')]]",
    "//table[.//th[contains(., 'Análise da Anatel')]]",
    "//table[.//th[contains(., 'Tipo')] or .//td[contains(., 'Tipo')]]",
]

FILA_SCH_ATUAL = "Em Análise"

FILAS_SCH_SUPORTADAS = {
    "Em Análise": [
        "Em Análise",
        "Em Analise",
    ],
    "Retorno Para Estudo": [
        "Retorno Para Estudo",
        "Retorno para Estudo",
        "Retorno Pra Estudo",
        "Retorno pra Estudo",
    ],
}

OBS_RADIACAO_RESTRITA = (
    "Na instalação do produto devem ser observadas as condições de uso "
    "conforme estabelecido no Regulamento sobre Equipamentos de "
    "Radiocomunicação de Radiação Restrita."
)

OBS_PRODUTO_NAO_ACABADO = (
    "Produto não acabado, de uso interno, cuja integração em outros "
    "equipamentos passíveis de homologação pode requerer nova avaliação."
)


def _valor_vazio_ou_traco(valor):
    texto = str(valor or "").strip()
    texto = re.sub(r"\s+", " ", texto)

    vazios = {
        "",
        "-",
        "--",
        "---",
        "–",
        "—",
        "n/a",
        "N/A",
        "na",
        "NA",
        "não informado",
        "nao informado",
        "não identificado",
        "nao identificado",
    }

    return texto in vazios


def _texto_limpo(valor):
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()

    if _valor_vazio_ou_traco(texto):
        return ""

    return texto


def _somente_digitos(valor):
    return re.sub(r"\D+", "", valor or "")


def _extrair_numero_requerimento_de_linha(texto_linha, celulas=None):
    """
    Extrai o número do requerimento preservando o ano quando vier no formato 04334/26.

    Exemplos:
    - 04334/26 -> 04334/26
    - 4334/26  -> 04334/26
    - 04334    -> 04334
    """
    candidatos = []

    texto_linha = _texto_limpo(texto_linha)
    if texto_linha:
        candidatos.append(texto_linha)

    for cel in celulas or []:
        try:
            txt = _texto_limpo(cel.text)
            if txt:
                candidatos.append(txt)
        except Exception:
            continue

    # Prioridade: requerimento com ano, exemplo 04334/26.
    padroes_com_ano = [
        r"requerimento\s*[:#\-]?\s*(\d{4,6})\s*/\s*(\d{2,4})\b",
        r"\b(\d{4,6})\s*/\s*(\d{2,4})\b",
    ]

    for texto in candidatos:
        for padrao in padroes_com_ano:
            m = re.search(padrao, texto, re.I)
            if not m:
                continue

            numero = _somente_digitos(m.group(1))
            ano = _somente_digitos(m.group(2))

            if not numero or not ano:
                continue

            if len(numero) < 5:
                numero = numero.zfill(5)

            if len(ano) == 4:
                ano = ano[-2:]

            return f"{numero}/{ano}"

    # Fallback: somente número.
    padroes_sem_ano = [
        r"requerimento\s*[:#\-]?\s*(\d{4,6})",
        r"^\s*(\d{4,6})\s*$",
        r"\b(\d{5,6})\b",
    ]

    for texto in candidatos:
        for padrao in padroes_sem_ano:
            m = re.search(padrao, texto, re.I)
            if not m:
                continue

            numero = _somente_digitos(m.group(1))

            if len(numero) >= 4:
                if len(numero) < 5:
                    numero = numero.zfill(5)

                return numero

    return ""


def _extrair_ano_requerimento_por_contexto(dados):
    """
    Tenta descobrir o ano do requerimento quando a fila trouxe só 04510.

    Prioridade:
    1. Homologação: 04225-26-01654 -> 26
    2. Texto completo da linha
    3. Data de conclusão: 29/05/2026 -> 26
    """
    dados = dados or {}

    candidatos = [
        dados.get("homologacao", ""),
        dados.get("texto_linha", ""),
        dados.get("certificado", ""),
    ]

    for valor in candidatos:
        texto = str(valor or "").strip()

        m = re.search(
            r"\b\d{4,6}\s*[-–—]\s*(\d{2})\s*[-–—]\s*\d{4,6}\b",
            texto,
        )

        if m:
            return m.group(1)

    data_conclusao = str(dados.get("data_conclusao", "") or "").strip()
    m_data = re.search(r"\b\d{2}/\d{2}/(\d{4})\b", data_conclusao)

    if m_data:
        return m_data.group(1)[-2:]

    return ""


def _garantir_ano_no_requerimento(dados):
    """
    Garante que o requerimento fique como 04510/26 quando possível.
    """
    dados = dados or {}

    requerimento = str(dados.get("requerimento", "") or "").strip()

    if not requerimento:
        return dados

    if "/" in requerimento:
        partes = requerimento.split("/", 1)
        numero = _somente_digitos(partes[0])
        ano = _somente_digitos(partes[1])

        if len(numero) < 5:
            numero = numero.zfill(5)

        if len(ano) == 4:
            ano = ano[-2:]

        if numero and ano:
            dados["requerimento"] = f"{numero}/{ano}"

        return dados

    numero = _somente_digitos(requerimento)

    if not numero:
        return dados

    if len(numero) < 5:
        numero = numero.zfill(5)

    ano = _extrair_ano_requerimento_por_contexto(dados)

    if ano:
        dados["requerimento"] = f"{numero}/{ano}"
    else:
        dados["requerimento"] = numero

    return dados


def _clicar_com_fallback(driver, elemento):
    try:
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elemento)


def _aguardar_iframe_detalhe(driver, timeout=8):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, XPATH_IFRAME_DETALHE))
    )


def _aguardar_tabela_fila(driver, timeout=6):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
    )


def _capturar_novas_abas(driver, handles_antes, timeout=1.0, poll=0.08):
    inicio = time.time()
    while time.time() - inicio < timeout:
        handles_depois = set(driver.window_handles)
        novas = [h for h in handles_depois if h not in handles_antes]
        if novas:
            return novas
        time.sleep(poll)
    return []


def fechar_abas_extras_sem_travar(driver, aba_principal=None, abas_para_fechar=None):
    """
    Fecha abas extras abertas durante o download sem derrubar o fluxo.

    Em alguns casos, Edge/Chrome trava ao executar driver.close().
    Quando isso acontecer, a automação apenas registra o aviso e tenta
    voltar para a aba principal.
    """
    try:
        handles_atuais = list(driver.window_handles)
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível listar abas abertas: {e}")
        return False

    if not handles_atuais:
        return False

    if not aba_principal:
        try:
            aba_principal = driver.current_window_handle
        except Exception:
            aba_principal = handles_atuais[0]

    if abas_para_fechar is None:
        abas_para_fechar = [
            h for h in handles_atuais
            if h != aba_principal
        ]

    fechou_alguma = False

    for handle in list(dict.fromkeys(abas_para_fechar)):
        try:
            handles_atuais = list(driver.window_handles)

            if handle not in handles_atuais:
                continue

            if handle == aba_principal:
                continue

            driver.switch_to.window(handle)
            esperar_tela_carregar(driver, 0.1)

            try:
                driver.close()
                fechou_alguma = True
            except Exception as e:
                print(
                    "[SCH][WARN] Não foi possível fechar aba extra. "
                    f"Ignorando e tentando continuar: {e}"
                )

        except Exception as e:
            print(f"[SCH][WARN] Falha ao tratar aba extra. Ignorando: {e}")

    try:
        handles_restantes = list(driver.window_handles)

        if aba_principal in handles_restantes:
            driver.switch_to.window(aba_principal)
        elif handles_restantes:
            driver.switch_to.window(handles_restantes[0])

        esperar_tela_carregar(driver, 0.1)
        return True

    except Exception as e:
        print(f"[SCH][WARN] Não foi possível retornar para aba principal: {e}")
        return fechou_alguma


def _classe_ativa(elemento):
    try:
        classe = (elemento.get_attribute("class") or "").lower()
        aria_selected = (elemento.get_attribute("aria-selected") or "").lower()
        aria_expanded = (elemento.get_attribute("aria-expanded") or "").lower()
        return (
            "botao-ativo" in classe
            or "active" in classe
            or "ui-state-hover" in classe
            or aria_selected == "true"
            or aria_expanded == "true"
        )
    except StaleElementReferenceException:
        return False


def _ha_tabela_anexos(driver):
    for xpath in XPATHS_TABELA_ANEXOS:
        try:
            if driver.find_elements(By.XPATH, xpath):
                return True
        except Exception:
            continue
    return False


def _ha_botoes_de_categoria_anexos(driver):
    xpaths = [
        "//button[.//span[normalize-space()='Certificado de Conformidade Técnica - CCT']]",
        "//button[.//span[normalize-space()='Manual do Produto']]",
        "//button[.//span[normalize-space()='Outros']]",
        "//button[contains(., 'CCT')]",
    ]
    for xpath in xpaths:
        try:
            if driver.find_elements(By.XPATH, xpath):
                return True
        except Exception:
            continue
    return False


def _ha_campo_caracteristicas(driver):
    xpaths = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'OBSERVA')]"
        "/following::*[self::textarea or self::input][1]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
    ]
    for xp in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xp)
            if any(el.is_displayed() for el in elementos):
                return True
        except Exception:
            continue
    return False


def _ha_campo_informacoes_adicionais(driver):
    xpaths = [
        "//label[contains(normalize-space(), 'Desejo acompanhar este processo')]",
        "//*[contains(normalize-space(), 'Desejo acompanhar este processo')]",
        "//textarea[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
        "//textarea[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
        "(//textarea[not(@disabled)])[1]",
    ]
    for xp in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xp)
            if any(el.is_displayed() for el in elementos):
                return True
        except Exception:
            continue
    return False


def _categoria_esta_ativa(driver, categoria_txt):
    xpaths = [
        f'//button[.//span[normalize-space()="{categoria_txt}"]]',
        f'//span[normalize-space()="{categoria_txt}"]/ancestor::button[1]',
        f'//button[contains(normalize-space(), "{categoria_txt}")]',
    ]
    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
            for el in elementos:
                if _classe_ativa(el):
                    return True
        except Exception:
            continue
    return False


def _preencher_html_em_elemento(driver, elemento, html):
    driver.execute_script(
        """
        arguments[0].innerHTML = arguments[1];
        arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
        arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
        arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
        """,
        elemento,
        html,
    )


def _tentar_preencher_editor_rico(driver, xpaths_editor, html):
    for xpath in xpaths_editor:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue

        for editor in elementos:
            try:
                if not editor.is_displayed():
                    continue

                tag = (editor.tag_name or "").lower()
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)

                if tag == "iframe":
                    driver.switch_to.frame(editor)

                    candidatos = driver.find_elements(
                        By.XPATH,
                        "//*[@contenteditable='true'] | "
                        "//body[normalize-space(.)='' or *] | "
                        "//div[contains(@class,'ql-editor')]"
                    )

                    for alvo in candidatos:
                        try:
                            if alvo.is_displayed():
                                _preencher_html_em_elemento(driver, alvo, html)
                                driver.switch_to.default_content()
                                return True
                        except Exception:
                            continue

                    driver.switch_to.default_content()
                    continue

                _preencher_html_em_elemento(driver, editor, html)
                return True

            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
                continue

    return False


def abrir_sch(driver):
    url = "https://sistemasnet.anatel.gov.br/mosaico/sch/worklist/visualizar"
    print(f"[SCH] Abrindo {url}")
    driver.get(url)
    esperar_tela_carregar(driver, 2)


def _normalizar_texto_login(valor):
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _esta_na_tela_login_sch(driver):
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    try:
        url = (driver.current_url or "").lower()
    except Exception:
        url = ""

    sinais_url_login = [
        "login",
        "sso",
        "cas",
        "autentic",
        "oauth",
        "openid",
    ]

    if any(sinal in url for sinal in sinais_url_login):
        return True

    try:
        campos_senha = driver.find_elements(By.XPATH, "//input[@type='password']")
        if any(campo.is_displayed() for campo in campos_senha):
            return True
    except Exception:
        pass

    try:
        body = driver.find_element(By.TAG_NAME, "body")
        texto = _normalizar_texto_login(body.text)

        sinais_texto_login = [
            "usuario",
            "senha",
            "entrar",
            "acessar",
            "login",
            "gov.br",
            "certificado digital",
            "autenticacao",
        ]

        qtd_sinais = sum(1 for sinal in sinais_texto_login if sinal in texto)

        if qtd_sinais >= 2 and "requerimento" not in texto:
            return True

    except Exception:
        pass

    return False



def garantir_sessao_ativa_sch(driver, wait, contexto="", reabrir_fila=True, nome_fila=None):
    """
    Verifica se o SCH caiu na tela de login.
    Se caiu, pausa para o usuário logar novamente e reabre a fila correta.

    A fila correta pode ser:
    - Em Análise
    - Retorno Para Estudo
    """
    if not _esta_na_tela_login_sch(driver):
        return False

    fila_para_reabrir = _resolver_nome_fila_sch(nome_fila or FILA_SCH_ATUAL or "Em Análise")

    print("=" * 90)
    print("[SCH][LOGIN] A sessão do SCH parece ter expirado ou voltou para a tela de login.")
    if contexto:
        print(f"[SCH][LOGIN] Contexto: {contexto}")
    print("[SCH][LOGIN] Faça o login novamente no navegador.")
    print("[SCH][LOGIN] Depois de concluir o login, volte ao terminal.")
    print("=" * 90)

    for tentativa in range(1, 4):
        input(f"[SCH][LOGIN] Tentativa {tentativa}/3 - pressione Enter após refazer o login...")

        esperar_tela_carregar(driver, 1.5)

        if reabrir_fila:
            try:
                abrir_sch(driver)
                esperar_tela_carregar(driver, 1.5)
            except Exception as e:
                print(f"[SCH][WARN] Não foi possível reabrir a página principal do SCH: {e}")

        if not _esta_na_tela_login_sch(driver):
            if reabrir_fila:
                try:
                    clicar_fila_sch(driver, wait, fila_para_reabrir)
                except Exception as e:
                    print(
                        "[SCH][WARN] Login refeito, mas não foi possível clicar "
                        f"na fila '{fila_para_reabrir}' automaticamente: {e}"
                    )

            print("[SCH][LOGIN] Sessão restaurada. Continuando fluxo.")
            return True

        print("[SCH][WARN] A tela ainda parece estar no login.")

    raise Exception("Sessão SCH expirada. Não foi possível restaurar o login após 3 tentativas.")


def _resolver_nome_fila_sch(nome_fila):
    nome_fila = str(nome_fila or "").strip()

    if not nome_fila:
        return "Em Análise"

    nome_norm = _normalizar_texto_comparacao(nome_fila)

    if nome_norm in {"em analise", "analise"}:
        return "Em Análise"

    if nome_norm in {
        "retorno para estudo",
        "retorno pra estudo",
        "retorno estudo",
    }:
        return "Retorno Para Estudo"

    return nome_fila


def clicar_fila_sch(driver, wait, nome_fila="Em Análise"):
    """
    Abre uma fila do menu lateral do SCH/Mosaico.

    Exemplos:
    - Em Análise
    - Retorno Para Estudo

    O restante do fluxo usa a mesma coleta da tabela.
    """
    global FILA_SCH_ATUAL

    nome_fila = _resolver_nome_fila_sch(nome_fila)
    rotulos = FILAS_SCH_SUPORTADAS.get(nome_fila, [nome_fila])

    print(f"[SCH] Clicando na fila {nome_fila}...")

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    xpaths = []

    for rotulo in rotulos:
        xpaths.extend(
            [
                f"//a[normalize-space()='{rotulo}' or contains(normalize-space(), '{rotulo}')]",
                f"//span[normalize-space()='{rotulo}' or contains(normalize-space(), '{rotulo}')]/ancestor::a[1]",
                f"//*[self::a or self::button][normalize-space()='{rotulo}' or contains(normalize-space(), '{rotulo}')]",
                f"//*[contains(normalize-space(), '{rotulo}')]/ancestor::*[self::a or self::button][1]",
            ]
        )

    ultimo_erro = None

    for tentativa in range(1, 4):
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        for xpath in xpaths:
            try:
                elementos = WebDriverWait(driver, 3, poll_frequency=0.1).until(
                    EC.presence_of_all_elements_located((By.XPATH, xpath))
                )

                for elemento in elementos:
                    try:
                        alvo = elemento
                        tag = (alvo.tag_name or "").lower()

                        if tag not in {"a", "button"}:
                            try:
                                alvo = elemento.find_element(
                                    By.XPATH,
                                    "./ancestor::*[self::a or self::button][1]",
                                )
                            except Exception:
                                alvo = elemento

                        if not alvo.is_displayed() or not alvo.is_enabled():
                            continue

                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            alvo,
                        )

                        _clicar_com_fallback(driver, alvo)
                        esperar_tela_carregar(driver, 1.2)

                        try:
                            _aguardar_tabela_fila(driver, timeout=6)
                        except Exception:
                            pass

                        FILA_SCH_ATUAL = nome_fila

                        print(f"[SCH] Fila aberta: {nome_fila}")
                        return True

                    except Exception as e:
                        ultimo_erro = e
                        continue

            except Exception as e:
                ultimo_erro = e
                continue

        esperar_tela_carregar(driver, 0.5)

    raise Exception(f"Não foi possível abrir a fila '{nome_fila}'. Último erro: {ultimo_erro}")


def clicar_fila_em_analise(driver, wait):
    return clicar_fila_sch(driver, wait, "Em Análise")


def clicar_fila_retorno_para_estudo(driver, wait):
    return clicar_fila_sch(driver, wait, "Retorno Para Estudo")



VALORES_REGISTROS_POR_PAGINA_SCH = tuple(range(5, 101, 5))


def selecionar_quantidade_registros_fila(
    driver,
    wait,
    quantidade=100,
):
    """
    Define quantos requerimentos o paginator do SCH exibirá por página.

    Funciona nas filas "Em Análise" e "Retorno Para Estudo". O seletor
    identificado no SCH é um <select> nativo com a classe PrimeFaces:
    select.ui-paginator-rpp-options.
    """
    try:
        quantidade = int(quantidade)
    except (TypeError, ValueError):
        raise ValueError(
            f"Quantidade de registros inválida: {quantidade!r}."
        )

    if quantidade not in VALORES_REGISTROS_POR_PAGINA_SCH:
        valores = ", ".join(
            str(valor)
            for valor in VALORES_REGISTROS_POR_PAGINA_SCH
        )
        raise ValueError(
            f"Quantidade inválida: {quantidade}. Valores aceitos: {valores}."
        )

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    seletor_css = "select.ui-paginator-rpp-options"

    seletores = WebDriverWait(
        driver,
        8,
        poll_frequency=0.1,
    ).until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, seletor_css)
        )
    )

    campo = None

    for elemento in seletores:
        try:
            if elemento.is_displayed() and elemento.is_enabled():
                campo = elemento
                break
        except StaleElementReferenceException:
            continue

    if campo is None:
        raise RuntimeError(
            "O seletor de quantidade de registros da fila foi localizado, "
            "mas nenhum campo está visível e habilitado."
        )

    valor_atual = str(campo.get_attribute("value") or "").strip()

    if valor_atual == str(quantidade):
        print(
            "[SCH] Registros por página já configurados em "
            f"{quantidade}."
        )
        return {
            "alterado": False,
            "confirmado": True,
            "valor_anterior": valor_atual,
            "valor_final": quantidade,
        }

    try:
        tabela_antes = _aguardar_tabela_fila(driver, timeout=5)
    except Exception:
        tabela_antes = None

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        campo,
    )

    Select(campo).select_by_value(str(quantidade))

    # O PrimeFaces normalmente atualiza a tabela por AJAX. Aguarda tanto a
    # sincronização dos paginadores superior/inferior quanto a tabela pronta.
    def _quantidade_confirmada(d):
        try:
            elementos = d.find_elements(By.CSS_SELECTOR, seletor_css)
            visiveis = [
                elemento
                for elemento in elementos
                if elemento.is_displayed()
            ]

            return bool(visiveis) and all(
                str(elemento.get_attribute("value") or "").strip()
                == str(quantidade)
                for elemento in visiveis
            )
        except (StaleElementReferenceException, Exception):
            return False

    WebDriverWait(
        driver,
        10,
        poll_frequency=0.1,
    ).until(_quantidade_confirmada)

    if tabela_antes is not None:
        try:
            WebDriverWait(driver, 2, poll_frequency=0.1).until(
                EC.staleness_of(tabela_antes)
            )
        except Exception:
            # Alguns eventos AJAX substituem apenas o tbody e mantêm a table.
            pass

    esperar_tela_carregar(driver, 0.4)
    _aguardar_tabela_fila(driver, timeout=8)

    print(
        "[SCH] Quantidade de registros por página alterada: "
        f"{valor_atual or 'não identificada'} -> {quantidade}."
    )

    return {
        "alterado": True,
        "confirmado": True,
        "valor_anterior": valor_atual,
        "valor_final": quantidade,
    }

def coletar_requerimentos(driver, wait, regras):
    xpath_tabela = "//table[.//th[contains(., 'Requerimento')] or .//td[contains(., 'Requerimento')]]"
    xpath_linhas = ".//tbody/tr[td]"

    colunas_regras = regras.get("colunas_fila", {})

    idx_requerimento = colunas_regras.get("requerimento", 0)
    idx_homologacao = colunas_regras.get("homologacao", 1)
    idx_certificado = colunas_regras.get("certificado", 2)
    idx_tipo_produto = colunas_regras.get("tipo_produto", 3)
    idx_modelo = colunas_regras.get("modelo", 4)
    idx_solicitante = colunas_regras.get("solicitante", 5)
    idx_fabricante = colunas_regras.get("fabricante", 6)
    idx_data_conclusao = colunas_regras.get("data_conclusao", 7)

    print("[SCH] Coletando requerimentos da fila...")
    tabela = wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
    linhas = tabela.find_elements(By.XPATH, xpath_linhas)

    requerimentos = []

    for idx, linha in enumerate(linhas, start=1):
        try:
            colunas = linha.find_elements(By.XPATH, "./td")

            def valor_coluna(posicao):
                return _texto_limpo(colunas[posicao].text) if len(colunas) > posicao else ""

            textos_colunas = [_texto_limpo(td.text) for td in colunas]
            texto_linha = " | ".join([t for t in textos_colunas if t])

            requerimento_coluna = valor_coluna(idx_requerimento)
            requerimento_extraido = _extrair_numero_requerimento_de_linha(
                texto_linha,
                colunas,
            )

            numero_requerimento = requerimento_extraido or requerimento_coluna
            if not numero_requerimento:
                numero_requerimento = f"sem_numero_linha_{idx}"

            dados = {
                "row_index": idx,
                "requerimento": numero_requerimento,
                "homologacao": valor_coluna(idx_homologacao),
                "certificado": valor_coluna(idx_certificado),
                "tipo_produto": valor_coluna(idx_tipo_produto),
                "modelo": valor_coluna(idx_modelo),
                "solicitante": valor_coluna(idx_solicitante),
                "fabricante": valor_coluna(idx_fabricante),
                "data_conclusao": valor_coluna(idx_data_conclusao),
                "texto_linha": texto_linha,
                "fila_sch": FILA_SCH_ATUAL,
            }

            dados = _garantir_ano_no_requerimento(dados)
            
            requerimentos.append(dados)



        except Exception as e:
            print(f"[SCH][WARN] Falha ao ler linha {idx}: {e}")

    print(f"[SCH] {len(requerimentos)} requerimentos encontrados.")
    for item in requerimentos:
        print(
            f"[SCH] Linha {item['row_index']}: "
            f"requerimento={item.get('requerimento', '')} | "
            f"homologacao={item.get('homologacao', '')} | "
            f"certificado={item.get('certificado', '')}"
        )

    return requerimentos



def _localizar_linha_requerimento_na_fila(driver, req):
    numero_alvo = _somente_digitos(req.get("requerimento", ""))

    tabela = _aguardar_tabela_fila(driver, timeout=8)
    linhas = tabela.find_elements(By.XPATH, ".//tbody/tr[td]")

    if numero_alvo:
        for linha in linhas:
            try:
                celulas = linha.find_elements(By.XPATH, "./td")
                numero_linha = _extrair_numero_requerimento_de_linha(
                    linha.text,
                    celulas,
                )

                if _somente_digitos(numero_linha) == numero_alvo:
                    return linha

            except StaleElementReferenceException:
                raise
            except Exception:
                continue

    linha_idx = int(req.get("row_index"))
    return tabela.find_element(By.XPATH, f"(.//tbody/tr[td])[{linha_idx}]")


def abrir_requerimento(driver, wait, req):
    numero = req.get("requerimento", "")
    ultimo_erro = None

    print(f"[SCH] Abrindo requerimento {numero}...")

    for tentativa in range(1, 5):
        try:
            refez_login = garantir_sessao_ativa_sch(
                driver,
                wait,
                contexto=f"antes de abrir o requerimento {numero}",
                reabrir_fila=True,
            )

            if refez_login:
                print(
                    f"[SCH][LOGIN] Login refeito antes de abrir o requerimento {numero}. "
                    "Refazendo busca na fila..."
                )

            esperar_tela_carregar(driver, 0.2)

            linha = _localizar_linha_requerimento_na_fila(driver, req)

            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                linha,
            )

            candidatos = linha.find_elements(
                By.XPATH,
                ".//a[img] | .//img/ancestor::a[1] | .//button | .//*[@role='button']",
            )

            for el in candidatos:
                try:
                    if el.is_displayed() and el.is_enabled():
                        _clicar_com_fallback(driver, el)
                        esperar_tela_carregar(driver, 0.15)

                        refez_login = garantir_sessao_ativa_sch(
                            driver,
                            wait,
                            contexto=f"após clicar no requerimento {numero}",
                            reabrir_fila=True,
                        )

                        if refez_login:
                            print(
                                f"[SCH][LOGIN] Login refeito após clique no requerimento {numero}. "
                                "Refazendo abertura do requerimento..."
                            )
                            raise StaleElementReferenceException(
                                "Sessão restaurada após clique. Refazer busca da linha."
                            )

                        _aguardar_iframe_detalhe(driver, timeout=5)
                        print("[SCH] Requerimento aberto. Tela de detalhes pronta.")
                        return

                except StaleElementReferenceException as e:
                    ultimo_erro = e
                    print(
                        f"[SCH][WARN] Elemento antigo ao clicar no requerimento {numero}. "
                        f"Refazendo busca da linha... tentativa {tentativa}/4"
                    )
                    raise

                except Exception as e:
                    ultimo_erro = e
                    continue

            try:
                _clicar_com_fallback(driver, linha)
                esperar_tela_carregar(driver, 0.15)

                refez_login = garantir_sessao_ativa_sch(
                    driver,
                    wait,
                    contexto=f"após clicar na linha do requerimento {numero}",
                    reabrir_fila=True,
                )

                if refez_login:
                    print(
                        f"[SCH][LOGIN] Login refeito após clique na linha do requerimento {numero}. "
                        "Refazendo abertura do requerimento..."
                    )
                    raise StaleElementReferenceException(
                        "Sessão restaurada após clique na linha. Refazer busca da linha."
                    )

                _aguardar_iframe_detalhe(driver, timeout=5)
                print("[SCH] Requerimento aberto por clique na linha. Tela de detalhes pronta.")
                return

            except StaleElementReferenceException as e:
                ultimo_erro = e
                print(
                    f"[SCH][WARN] Linha ficou antiga ao abrir requerimento {numero}. "
                    f"Refazendo busca... tentativa {tentativa}/4"
                )
                raise

            except Exception as e:
                ultimo_erro = e

        except StaleElementReferenceException as e:
            ultimo_erro = e
            esperar_tela_carregar(driver, 0.6)
            continue

        except Exception as e:
            ultimo_erro = e

            texto_erro = str(e).lower()

            if "stale element reference" in texto_erro:
                print(
                    f"[SCH][WARN] Elemento antigo detectado no requerimento {numero}. "
                    f"Nova tentativa {tentativa}/4."
                )
                esperar_tela_carregar(driver, 0.6)
                continue

            if _esta_na_tela_login_sch(driver):
                garantir_sessao_ativa_sch(
                    driver,
                    wait,
                    contexto=f"erro ao abrir requerimento {numero}",
                    reabrir_fila=True,
                )
                esperar_tela_carregar(driver, 0.6)
                continue

            esperar_tela_carregar(driver, 0.4)

    raise Exception(
        f"Não foi possível abrir o requerimento {numero}. Último erro: {ultimo_erro}"
    )


def entrar_iframe_detalhe_analise(driver, wait=None):
    driver.switch_to.default_content()
    iframe = _aguardar_iframe_detalhe(driver, timeout=8)
    driver.switch_to.frame(iframe)
    return iframe


def _clicar_aba_por_rotulo(
    driver,
    wait,
    rotulo_principal,
    rotulos_alternativos=None,
    condicao_pronta=None,
    timeout_click=1.4,
    timeout_pronta=1.4,
):
    rotulos = [rotulo_principal]
    if rotulos_alternativos:
        rotulos.extend(rotulos_alternativos)

    candidatos = []
    for rotulo in rotulos:
        candidatos.extend(
            [
                f"//button[.//span[normalize-space()='{rotulo}']]",
                f"//span[normalize-space()='{rotulo}']/ancestor::button[1]",
                f"//a[normalize-space()='{rotulo}']",
                f"//span[normalize-space()='{rotulo}']/ancestor::a[1]",
                f"//*[self::a or self::button][contains(normalize-space(), '{rotulo}')]",
            ]
        )

    ultimo_erro = None

    for _ in range(2):
        entrar_iframe_detalhe_analise(driver, wait)
        esperar_tela_carregar(driver, 0.02)

        for xpath in candidatos:
            try:
                aba = WebDriverWait(driver, timeout_click, poll_frequency=0.08).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", aba)
                _clicar_com_fallback(driver, aba)

                def _confirmar(d):
                    try:
                        entrar_iframe_detalhe_analise(d, wait)

                        if condicao_pronta is not None:
                            return condicao_pronta(d)

                        els = d.find_elements(By.XPATH, xpath)
                        return any(_classe_ativa(el) for el in els)
                    except Exception:
                        return False

                WebDriverWait(driver, timeout_pronta, poll_frequency=0.08).until(_confirmar)
                esperar_tela_carregar(driver, 0.02)

                print(f"[SCH] Aba '{rotulo_principal}' aberta.")
                return xpath

            except Exception as e:
                ultimo_erro = e
                continue

    raise Exception(f"Não foi possível abrir a aba '{rotulo_principal}'. Último erro: {ultimo_erro}")



def clicar_aba_dados_gerais(driver, wait):
    """
    Abre a aba Dados Gerais dentro do requerimento.
    """
    print("[SCH] Abrindo aba Dados Gerais...")

    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Dados Gerais",
        rotulos_alternativos=[
            "Dados Gerais",
            "Dados gerais",
            "Dados",
        ],
        condicao_pronta=lambda d: _ha_bloco_dados_certificado(d),
        timeout_click=1.5,
        timeout_pronta=1.5,
    )


def _texto_visivel_sch(driver):
    """
    Captura o texto visível da tela atual do SCH.
    """
    try:
        return driver.execute_script(
            "return document.body.innerText || document.body.textContent || '';"
        ) or ""
    except Exception:
        return ""


def _ha_bloco_dados_certificado(driver):
    """
    Verifica se a aba Dados Gerais carregou a seção Dados do Certificado.
    """
    try:
        texto = _texto_visivel_sch(driver)
        texto_norm = _normalizar_texto_comparacao(texto)

        return (
            "dados do certificado" in texto_norm
            and (
                "data do certificado" in texto_norm
                or "data de validade" in texto_norm
                or "n do certificado" in texto_norm
                or "numero do certificado" in texto_norm
            )
        )
    except Exception:
        return False


def _recortar_bloco_dados_certificado(texto):
    """
    Recorta somente a seção 'Dados do Certificado',
    evitando capturar dados do fabricante/produto.
    """
    texto = texto or ""

    m = re.search(
        r"Dados\s+do\s+Certificado(?P<bloco>.*?)(?:\n\s*Produto\b|\n\s*Dados\s+do\s+Produto\b|$)",
        texto,
        flags=re.I | re.S,
    )

    if m:
        return "Dados do Certificado\n" + m.group("bloco")

    return texto


def _deduplicar_lista_preservando_ordem(valores):
    saida = []
    vistos = set()

    for valor in valores or []:
        valor = _texto_limpo(valor)

        if not valor:
            continue

        chave = _normalizar_texto_comparacao(valor)

        if not chave or chave in vistos:
            continue

        vistos.add(chave)
        saida.append(valor)

    return saida


def _recortar_bloco_produto_sch(texto):
    """
    Recorta a seção Produto da aba Dados Gerais.

    Exemplo esperado no SCH:
    Produto
    Modelo: L1100    Nome Comercial: L1100BT
    Modelo: L1120    Nome Comercial: L1120BT
    """
    texto = texto or ""

    m = re.search(
        r"(?:^|\n)\s*Produto\s*(?P<bloco>.*?)(?:\n\s*(?:Dados\s+da\s+Especifica[cç][aã]o|Caracter[ií]sticas\s+T[eé]cnicas|Outras\s+Unidades|Exig[eê]ncias|Informa[cç][oõ]es\s+Adicionais)\b|$)",
        texto,
        flags=re.I | re.S,
    )

    if m:
        return "Produto\n" + m.group("bloco")

    return ""


def _extrair_produtos_sch_do_texto(texto, req=None):
    """
    Extrai modelo(s) e nome(s) comercial(is) do bloco Produto no SCH.
    Se Nome Comercial não for encontrado, usa o Modelo como fallback,
    para nunca deixar o relatório vazio.
    """
    req = req or {}
    bloco = _recortar_bloco_produto_sch(texto)

    modelos = []
    nomes_comerciais = []

    if bloco:
        texto_bloco = re.sub(r"\r", "\n", bloco)
        texto_bloco = re.sub(r"[ \t]+", " ", texto_bloco)

        padrao_pares = re.compile(
            r"Modelo\s*:?\s*(?P<modelo>.*?)\s+Nome\s+Comercial\s*:?\s*(?P<nome>.*?)(?=(?:\s+Modelo\s*:)|(?:\n)|$)",
            flags=re.I | re.S,
        )

        for m in padrao_pares.finditer(texto_bloco):
            modelo = _texto_limpo(m.group("modelo"))
            nome = _texto_limpo(m.group("nome"))

            if modelo:
                modelos.append(modelo)

            if nome:
                nomes_comerciais.append(nome)

        # Fallback para caso venha em linhas separadas.
        if not nomes_comerciais:
            for linha in texto_bloco.splitlines():
                linha_limpa = _texto_limpo(linha)

                if not linha_limpa:
                    continue

                m_nome = re.search(
                    r"Nome\s+Comercial\s*:?\s*(.+)$",
                    linha_limpa,
                    flags=re.I,
                )

                if m_nome:
                    nomes_comerciais.append(_texto_limpo(m_nome.group(1)))

                m_modelo = re.search(
                    r"Modelo\s*:?\s*(.+?)(?:\s+Nome\s+Comercial\s*:|$)",
                    linha_limpa,
                    flags=re.I,
                )

                if m_modelo:
                    modelos.append(_texto_limpo(m_modelo.group(1)))

    modelos = _deduplicar_lista_preservando_ordem(modelos)
    nomes_comerciais = _deduplicar_lista_preservando_ordem(nomes_comerciais)

    modelo_txt = "; ".join(modelos).strip()
    nome_comercial_txt = "; ".join(nomes_comerciais).strip()

    modelo_req = _texto_limpo(req.get("modelo", ""))

    if not modelo_txt:
        modelo_txt = modelo_req

    # Regra importante: Nome Comercial nunca deve ficar vazio.
    # Se o SCH não trouxer Nome Comercial, usa Modelo.
    if not nome_comercial_txt:
        nome_comercial_txt = modelo_txt or modelo_req

    return {
        "modelo_sch_dados_gerais": modelo_txt,
        "nome_comercial": nome_comercial_txt,
        "nomes_comerciais": nomes_comerciais,
        "modelos_produto_sch": modelos,
        "texto_bloco_produto": bloco,
    }


def _extrair_valor_sch_por_rotulo(texto, rotulos):
    texto = texto or ""

    for rotulo in rotulos:
        padrao = rf"{rotulo}\s*[:\-]?\s*([^\n\r]+)"
        m = re.search(padrao, texto, flags=re.I)

        if not m:
            continue

        valor = str(m.group(1) or "").strip()

        valor = re.split(
            r"\s+(?:Nome|CNPJ|CPF/CNPJ|N[º°o]\s*do\s*Certificado|Data\s+do\s+Certificado|Data\s+de\s+Validade|Produto)\s*:",
            valor,
            maxsplit=1,
            flags=re.I,
        )[0]

        valor = re.sub(r"\s+", " ", valor).strip(" :-;")

        if valor:
            return valor

    return ""


def _extrair_data_sch_por_rotulo(texto, rotulos):
    texto = texto or ""

    for rotulo in rotulos:
        padrao = rf"{rotulo}[^\d]{{0,80}}(\d{{2}}/\d{{2}}/\d{{4}})"
        m = re.search(padrao, texto, flags=re.I)

        if m:
            return m.group(1)

    return ""


def extrair_dados_certificado_sch(driver, wait):
    """
    Extrai os dados da seção:
    Dados Gerais > Dados do Certificado

    Campos esperados:
    - Nome
    - CNPJ
    - Nº do Certificado
    - Data do Certificado
    - Data de Validade
    """
    print("[SCH] Extraindo dados do certificado na aba Dados Gerais...")

    clicar_aba_dados_gerais(driver, wait)

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.05)

    texto = _texto_visivel_sch(driver)
    bloco = _recortar_bloco_dados_certificado(texto)
    produto_sch = _extrair_produtos_sch_do_texto(texto)

    dados = {
        "nome": _extrair_valor_sch_por_rotulo(
            bloco,
            [
                r"Nome",
            ],
        ),
        "cnpj": _extrair_valor_sch_por_rotulo(
            bloco,
            [
                r"CNPJ",
                r"CPF/CNPJ",
            ],
        ),
        "numero_certificado": _extrair_valor_sch_por_rotulo(
            bloco,
            [
                r"N[º°o]\s*do\s*Certificado",
                r"N[uú]mero\s+do\s+Certificado",
            ],
        ),
        "data_certificado": _extrair_data_sch_por_rotulo(
            bloco,
            [
                r"Data\s+do\s+Certificado",
                r"Data\s+de\s+Emiss[aã]o",
                r"Emiss[aã]o",
            ],
        ),
        "data_validade": _extrair_data_sch_por_rotulo(
            bloco,
            [
                r"Data\s+de\s+Validade",
                r"Validade",
            ],
        ),
        "origem": "SCH - Dados Gerais - Dados do Certificado",
        "texto_bloco": bloco,
    }
    dados.update(produto_sch)

    print(
        "[SCH] Dados do certificado no SCH: "
        f"certificado={dados.get('numero_certificado', '')} | "
        f"emissão={dados.get('data_certificado', '')} | "
        f"validade={dados.get('data_validade', '')}"
        f"nome_comercial={dados.get('nome_comercial', '')}"
    )

    return dados




def clicar_aba_anexos(driver, wait):
    print("[SCH] Abrindo aba Anexos...")
    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Anexos",
        condicao_pronta=lambda d: _ha_tabela_anexos(d) or _ha_botoes_de_categoria_anexos(d),
        timeout_click=1.2,
        timeout_pronta=1.2,
    )


def clicar_categoria_anexo(driver, wait, categoria):
    categoria_txt = categoria.replace('"', "").strip()
    xpaths = [
        f'//button[.//span[normalize-space()="{categoria_txt}"]]',
        f'//span[normalize-space()="{categoria_txt}"]/ancestor::button[1]',
        f'//button[contains(normalize-space(), "{categoria_txt}")]',
    ]

    print(f"[SCH] Abrindo categoria de anexos: {categoria}")
    ultimo_erro = None

    for _ in range(2):
        entrar_iframe_detalhe_analise(driver, wait)
        esperar_tela_carregar(driver, 0.02)

        for xpath in xpaths:
            try:
                botao = WebDriverWait(driver, 1.8, poll_frequency=0.08).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
                driver.execute_script("arguments[0].click();", botao)

                def _categoria_pronta(d):
                    try:
                        entrar_iframe_detalhe_analise(d, wait)
                        return _categoria_esta_ativa(d, categoria_txt)
                    except Exception:
                        return False

                WebDriverWait(driver, 1.4, poll_frequency=0.08).until(_categoria_pronta)
                esperar_tela_carregar(driver, 0.03)

                print(f"[SCH] Categoria aberta: {categoria}")
                return

            except Exception as e:
                ultimo_erro = e
                continue

    raise Exception(
        f"Não foi possível abrir a categoria {categoria}. Último erro: {ultimo_erro}"
    )


def localizar_tabela_anexos(driver, wait):
    for xpath in XPATHS_TABELA_ANEXOS:
        try:
            tabela = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return tabela
        except Exception:
            pass

    raise Exception("Não foi possível localizar a tabela da categoria atual.")


def listar_arquivos_estaveis(pasta_download):
    pasta = Path(pasta_download)
    if not pasta.exists():
        return set()

    return {
        p.resolve()
        for p in pasta.iterdir()
        if p.is_file() and p.suffix.lower() not in {".crdownload", ".tmp", ".part"}
    }


def esperar_novo_arquivo_baixado(pasta_download, arquivos_antes, timeout=8, poll=0.08):
    inicio = time.time()
    pasta = Path(pasta_download)
    ultimo_tamanho = {}
    confirmacoes_estaveis = {}

    while time.time() - inicio < timeout:
        temporarios = (
            list(pasta.glob("*.crdownload"))
            + list(pasta.glob("*.tmp"))
            + list(pasta.glob("*.part"))
        )

        atuais = listar_arquivos_estaveis(pasta_download)
        novos = [p for p in atuais if p not in arquivos_antes]

        for arquivo in novos:
            try:
                tamanho = arquivo.stat().st_size
            except Exception:
                continue

            tamanho_anterior = ultimo_tamanho.get(arquivo)
            if tamanho_anterior is None:
                ultimo_tamanho[arquivo] = tamanho
                confirmacoes_estaveis[arquivo] = 0
                continue

            if tamanho_anterior == tamanho:
                confirmacoes_estaveis[arquivo] = confirmacoes_estaveis.get(arquivo, 0) + 1
            else:
                ultimo_tamanho[arquivo] = tamanho
                confirmacoes_estaveis[arquivo] = 0

        candidatos_prontos = [
            a for a in novos
            if confirmacoes_estaveis.get(a, 0) >= 1
        ]

        if candidatos_prontos and not temporarios:
            candidatos_prontos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidatos_prontos[0]

        time.sleep(poll)

    return None


def mover_arquivo_para_requerimento(arquivo_origem, pasta_destino, nome_destino=None):
    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    origem = Path(arquivo_origem)
    destino = pasta_destino / (nome_destino or origem.name)

    if destino.exists():
        stem = destino.stem
        suffix = destino.suffix
        i = 2
        while destino.exists():
            destino = pasta_destino / f"{stem}_{i}{suffix}"
            i += 1

    shutil.move(str(origem), str(destino))
    return destino


def baixar_anexos_da_categoria_atual(driver, wait, req, pasta_saida, pasta_download, categoria):
    pasta_req = Path(pasta_saida)
    pasta_categoria = pasta_req / nome_seguro(categoria)
    pasta_categoria.mkdir(parents=True, exist_ok=True)

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.03)

    tabela = localizar_tabela_anexos(driver, wait)
    total_linhas = len(tabela.find_elements(By.XPATH, ".//tr[td]"))

    print(f"[SCH] {total_linhas} linha(s) na categoria {categoria}.")
    anexos_categoria = []
    vistos_categoria = set()

    for i in range(1, total_linhas + 1):
        try:
            entrar_iframe_detalhe_analise(driver, wait)
            tabela = localizar_tabela_anexos(driver, wait)
            linhas = tabela.find_elements(By.XPATH, ".//tr[td]")

            if len(linhas) < i:
                break

            linha = linhas[i - 1]
            tds = linha.find_elements(By.XPATH, "./td")

            id_linha = tds[0].text.strip() if len(tds) > 0 else str(i)
            tipo_documento = tds[1].text.strip() if len(tds) > 1 else ""
            detalhamento = tds[2].text.strip() if len(tds) > 2 else ""
            data_hora = tds[3].text.strip() if len(tds) > 3 else ""
            nome_anexo = tds[4].text.strip() if len(tds) > 4 else id_linha
            entidade = tds[5].text.strip() if len(tds) > 5 else ""
            contato = tds[6].text.strip() if len(tds) > 6 else ""

            registro = {
                "categoria": categoria,
                "linha": i,
                "id": id_linha,
                "tipo_documento": tipo_documento,
                "detalhamento": detalhamento,
                "data_hora": data_hora,
                "nome_anexo": nome_anexo,
                "entidade": entidade,
                "contato": contato,
                "status": "pendente",
            }

            chave_doc = (
                str(id_linha).strip(),
                str(tipo_documento).strip().lower(),
                str(nome_anexo).strip().lower(),
            )

            if chave_doc in vistos_categoria:
                registro["status"] = "duplicado_ignorado"
                anexos_categoria.append(registro)
                continue

            vistos_categoria.add(chave_doc)

            nome_limpo_existente = nome_seguro(nome_anexo) or f"anexo_{i}"
            arquivos_existentes = list(pasta_categoria.glob(f"{nome_limpo_existente}.*"))
            if arquivos_existentes:
                registro["status"] = "ja_existente"
                registro["arquivo"] = str(arquivos_existentes[0])
                anexos_categoria.append(registro)
                print(f"[SCH] Anexo já existente, ignorando novo download: {arquivos_existentes[0].name}")
                continue

            xpaths_download = [
                ".//td[5]//a",
                ".//a[contains(@href,'download')]",
                ".//img/ancestor::a[1]",
                ".//a",
            ]

            link = None
            for xp in xpaths_download:
                encontrados = linha.find_elements(By.XPATH, xp)
                if encontrados:
                    link = encontrados[0]
                    break

            if link is None:
                registro["status"] = "sem_link"
                anexos_categoria.append(registro)
                continue

            print(f"[SCH] Baixando anexo {i} da categoria {categoria}: {nome_anexo}")

            janela_principal = driver.current_window_handle
            handles_antes = set(driver.window_handles)
            arquivos_antes = listar_arquivos_estaveis(pasta_download)

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            _clicar_com_fallback(driver, link)

            novas_abas = _capturar_novas_abas(driver, handles_antes, timeout=0.8)

            if novas_abas:
                fechar_abas_extras_sem_travar(
                    driver=driver,
                    aba_principal=janela_principal,
                    abas_para_fechar=novas_abas,
                )

                entrar_iframe_detalhe_analise(driver, wait)

            novo_arquivo = esperar_novo_arquivo_baixado(
                pasta_download,
                arquivos_antes,
                timeout=8,
                poll=0.08,
            )

            if novo_arquivo:
                nome_limpo = nome_seguro(nome_anexo) or f"anexo_{i}"
                nome_destino = f"{nome_limpo}{novo_arquivo.suffix.lower()}"
                arquivo_final = mover_arquivo_para_requerimento(
                    novo_arquivo,
                    pasta_categoria,
                    nome_destino,
                )

                registro["status"] = "baixado"
                registro["arquivo"] = str(arquivo_final)
                print(f"[SCH] Baixado: {arquivo_final.name}")
            else:
                registro["status"] = "nao_identificado"
                print(f"[SCH][WARN] Download não identificado para o anexo {nome_anexo}")

            anexos_categoria.append(registro)

        except Exception as e:
            print(f"[SCH][WARN] Falha no anexo {i} da categoria {categoria}: {e}")
            anexos_categoria.append(
                {
                    "categoria": categoria,
                    "linha": i,
                    "id": str(i),
                    "nome_anexo": "",
                    "status": "erro",
                    "erro": str(e),
                }
            )

    return anexos_categoria


def baixar_todos_os_anexos_de_todas_as_categorias(
    driver, wait, req, pasta_saida, pasta_download=None, regras=None
):
    categorias = []
    if regras:
        categorias = regras.get("categorias_anexos", [])

    if not categorias:
        categorias = [
            "Outros",
            "ART",
            "Selo ANATEL",
            "Relatório de Avaliação da Conformidade - RACT",
            "Manual do Produto",
            "Certificado de Conformidade Técnica - CCT",
            "Contrato Social",
            "Fotos internas",
            "Relatório de Ensaio",
            "Fotos do produto",
        ]

    categorias = list(dict.fromkeys(categorias))
    categorias = sorted(categorias, key=lambda x: 0 if "CCT" in x.upper() else 1)

    print(f"[SCH] Iniciando download das categorias de anexos: {len(categorias)} categorias.")
    anexos_baixados = []

    for categoria in categorias:
        try:
            clicar_categoria_anexo(driver, wait, categoria)
            anexos_categoria = baixar_anexos_da_categoria_atual(
                driver=driver,
                wait=wait,
                req=req,
                pasta_saida=pasta_saida,
                pasta_download=pasta_download,
                categoria=categoria,
            )
            anexos_baixados.extend(anexos_categoria)
        except Exception as e:
            print(f"[SCH][WARN] Falha na categoria {categoria}: {e}")
            anexos_baixados.append(
                {
                    "categoria": categoria,
                    "status": "erro_categoria",
                    "erro": str(e),
                }
            )

    print("[SCH] Download de todas as categorias finalizado.")
    return anexos_baixados

def localizar_pdf_cct_do_requerimento(pasta_req, regras=None):
    pasta_req = Path(pasta_req)
    if not pasta_req.exists():
        return None

    pasta_cct = pasta_req / nome_seguro("Certificado de Conformidade Técnica - CCT")
    if pasta_cct.exists():
        pdfs_cct = list(pasta_cct.rglob("*.pdf"))
        if pdfs_cct:
            pdfs_cct.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return pdfs_cct[0]

    pdfs = list(pasta_req.rglob("*.pdf"))
    if not pdfs:
        return None

    palavras_cct = ["cct", "certificado", "conformidade", "tecnica", "técnica"]

    if regras:
        palavras_regras = (
            regras.get("palavras_chave_documentos", {}).get("cct", [])
            if isinstance(regras.get("palavras_chave_documentos", {}), dict)
            else []
        )
        palavras_cct.extend([str(p).lower() for p in palavras_regras])

    candidatos = [p for p in pdfs if any(k in p.name.lower() for k in palavras_cct)]
    if candidatos:
        candidatos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidatos[0]

    return None


def _texto_total_dados_pdf(dados_pdf):
    partes = []

    def percorrer(valor):
        if valor is None:
            return

        if isinstance(valor, dict):
            for v in valor.values():
                percorrer(v)
            return

        if isinstance(valor, list):
            for v in valor:
                percorrer(v)
            return

        partes.append(str(valor))

    percorrer(dados_pdf or {})
    return " ".join(partes)


def _extrair_primeira_data_por_rotulos(texto, rotulos):
    texto = texto or ""

    for rotulo in rotulos:
        padrao = rf"{rotulo}[^\d]{{0,40}}(\d{{2}}/\d{{2}}/\d{{4}})"
        m = re.search(padrao, texto, re.I)
        if m:
            return m.group(1)

    return ""


def _converter_data_br(valor):
    if not valor:
        return None

    valor = str(valor).strip()

    formatos = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ]

    for formato in formatos:
        try:
            return datetime.strptime(valor[:10], formato).date()
        except Exception:
            continue

    return None


def _somar_anos(data, anos):
    try:
        return data.replace(year=data.year + anos)
    except ValueError:
        return data.replace(month=2, day=28, year=data.year + anos)


def avaliar_validade_cct(dados_pdf):
    dados_pdf = dados_pdf or {}

    emissao_bruta = (
        dados_pdf.get("data_emissao")
        or dados_pdf.get("emissao")
        or dados_pdf.get("data_de_emissao")
        or dados_pdf.get("emitido_em")
        or ""
    )

    validade_bruta = (
        dados_pdf.get("data_validade")
        or dados_pdf.get("validade")
        or dados_pdf.get("data_de_validade")
        or dados_pdf.get("valido_ate")
        or dados_pdf.get("válido_até")
        or ""
    )

    texto_total = _texto_total_dados_pdf(dados_pdf)

    if not emissao_bruta:
        emissao_bruta = _extrair_primeira_data_por_rotulos(
            texto_total,
            [
                "emiss[aã]o",
                "data de emiss[aã]o",
                "emitido em",
            ],
        )

    if not validade_bruta:
        validade_bruta = _extrair_primeira_data_por_rotulos(
            texto_total,
            [
                "validade",
                "data de validade",
                "v[aá]lido at[eé]",
                "valido ate",
            ],
        )

    data_emissao = _converter_data_br(emissao_bruta)
    data_validade = _converter_data_br(validade_bruta)

    resultado = {
        "data_emissao_bruta": emissao_bruta,
        "data_validade_bruta": validade_bruta,
        "data_emissao": data_emissao.isoformat() if data_emissao else "",
        "data_validade": data_validade.isoformat() if data_validade else "",
        "status": "nao_verificado",
        "mensagem": "",
    }

    if not data_emissao or not data_validade:
        resultado["status"] = "alerta"
        resultado["mensagem"] = "Não foi possível identificar emissão e/ou validade do CCT."
        return resultado

    limite = _somar_anos(data_emissao, 2)

    resultado["limite_2_anos"] = limite.isoformat()
    resultado["dias_entre_emissao_validade"] = (data_validade - data_emissao).days

    if data_validade <= limite:
        resultado["status"] = "ok"
        resultado["mensagem"] = "Validade do CCT dentro do limite de até 2 anos após a emissão."
    else:
        resultado["status"] = "alerta"
        resultado["mensagem"] = "Validade do CCT superior a 2 anos após a emissão. Conferir manualmente."

    return resultado


def comparar_datas_certificado_sch_x_cct(dados_certificado_sch, dados_pdf):
    """
    Compara as datas do certificado no SCH com as datas extraídas do CCT.

    A validação de prazo de 2 anos continua usando as datas do SCH.
    Esta função apenas gera alerta caso o SCH e o CCT estejam divergentes.
    """
    dados_certificado_sch = dados_certificado_sch or {}
    dados_pdf = dados_pdf or {}

    emissao_sch_bruta = (
        dados_certificado_sch.get("data_certificado")
        or dados_pdf.get("data_emissao_sch")
        or ""
    )

    validade_sch_bruta = (
        dados_certificado_sch.get("data_validade")
        or dados_pdf.get("data_validade_sch")
        or ""
    )

    emissao_cct_bruta = (
        dados_pdf.get("data_emissao_cct")
        or dados_pdf.get("data_emissao")
        or ""
    )

    validade_cct_bruta = (
        dados_pdf.get("data_validade_cct")
        or dados_pdf.get("data_validade")
        or ""
    )

    def comparar_um_campo(nome_campo, valor_sch, valor_cct):
        data_sch = _converter_data_br(valor_sch)
        data_cct = _converter_data_br(valor_cct)

        if not data_sch and not data_cct:
            status = "ausente_nos_dois"
            diverge = False
            mensagem = "Data não identificada no SCH nem no CCT."

        elif not data_sch:
            status = "ausente_no_sch"
            diverge = True
            mensagem = "Data identificada no CCT, mas não identificada no SCH."

        elif not data_cct:
            status = "ausente_no_cct"
            diverge = False
            mensagem = (
                "Data identificada no SCH, mas não identificada no CCT. "
                "Não gera divergência automática, mas recomenda conferência manual."
            )

        elif data_sch == data_cct:
            status = "ok"
            diverge = False
            mensagem = "Data do SCH confere com a data do CCT."

        else:
            status = "divergente"
            diverge = True
            mensagem = "Data do SCH difere da data extraída do CCT."

        return {
            "campo": nome_campo,
            "valor_sch": valor_sch or "",
            "valor_cct": valor_cct or "",
            "data_sch_normalizada": data_sch.isoformat() if data_sch else "",
            "data_cct_normalizada": data_cct.isoformat() if data_cct else "",
            "status": status,
            "diverge": diverge,
            "mensagem": mensagem,
        }

    comparacoes = [
        comparar_um_campo(
            "data_emissao",
            emissao_sch_bruta,
            emissao_cct_bruta,
        ),
        comparar_um_campo(
            "data_validade",
            validade_sch_bruta,
            validade_cct_bruta,
        ),
    ]

    divergencias = [
        item for item in comparacoes
        if item.get("diverge")
    ]

    ausentes_no_cct = [
        item for item in comparacoes
        if item.get("status") == "ausente_no_cct"
    ]

    if divergencias:
        status_geral = "divergente"
        mensagem_geral = (
            "Há divergência entre as datas do SCH e as datas extraídas do CCT. "
            "Revisão manual recomendada."
        )

    elif ausentes_no_cct:
        status_geral = "parcial"
        mensagem_geral = (
            "As datas do SCH foram identificadas, mas uma ou mais datas não foram "
            "encontradas no CCT. Conferir manualmente se necessário."
        )

    else:
        status_geral = "ok"
        mensagem_geral = "Datas do SCH conferem com as datas extraídas do CCT."

    return {
        "status_geral": status_geral,
        "mensagem": mensagem_geral,
        "comparacoes": comparacoes,
        "divergencias": divergencias,
        "origem_sch": dados_certificado_sch.get(
            "origem",
            "SCH - Dados Gerais - Dados do Certificado",
        ),
        "origem_cct": "CCT extraído pelo parser",
    }



def _normalizar_texto_rapido(texto):
    texto = (texto or "").lower()
    texto = texto.replace("não", "nao")
    texto = texto.replace("módulo", "modulo")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _remover_acentos(texto):
    texto = str(texto or "")
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(ch)
    )


def _normalizar_texto_comparacao(texto):
    texto = _texto_limpo(texto)
    texto = _remover_acentos(texto).lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _normalizar_numero_comparacao(texto):
    return _somente_digitos(texto)


def _comparar_valores(sch_valor, cct_valor, campo, modo="texto"):
    sch_bruto = _texto_limpo(sch_valor)
    cct_bruto = _texto_limpo(cct_valor)

    if not sch_bruto and not cct_bruto:
        return {
            "campo": campo,
            "status": "ausente_nos_dois",
            "valor_sch": sch_bruto,
            "valor_cct": cct_bruto,
            "valor_sch_normalizado": "",
            "valor_cct_normalizado": "",
            "diverge": False,
        }

    if not sch_bruto or not cct_bruto:
        return {
            "campo": campo,
            "status": "ausente_em_um_dos_lados",
            "valor_sch": sch_bruto,
            "valor_cct": cct_bruto,
            "valor_sch_normalizado": "",
            "valor_cct_normalizado": "",
            "diverge": True,
        }

    if modo == "numero":
        sch_norm = _normalizar_numero_comparacao(sch_bruto)
        cct_norm = _normalizar_numero_comparacao(cct_bruto)
        iguais = bool(sch_norm and cct_norm and sch_norm == cct_norm)

    elif modo == "texto_flex":
        sch_norm = _normalizar_texto_comparacao(sch_bruto)
        cct_norm = _normalizar_texto_comparacao(cct_bruto)
        iguais = bool(
            sch_norm and cct_norm and (
                sch_norm == cct_norm
                or sch_norm in cct_norm
                or cct_norm in sch_norm
            )
        )

    else:
        sch_norm = _normalizar_texto_comparacao(sch_bruto)
        cct_norm = _normalizar_texto_comparacao(cct_bruto)
        iguais = bool(sch_norm and cct_norm and sch_norm == cct_norm)

    return {
        "campo": campo,
        "status": "ok" if iguais else "divergente",
        "valor_sch": sch_bruto,
        "valor_cct": cct_bruto,
        "valor_sch_normalizado": sch_norm,
        "valor_cct_normalizado": cct_norm,
        "diverge": not iguais,
    }



def _normalizar_texto_tabela(valor):
    valor = _texto_limpo(valor)
    valor = _remover_acentos(valor).lower()
    valor = re.sub(r"\s+", " ", valor).strip()
    return valor


def _cabecalho_canonico(valor):
    texto = _normalizar_texto_tabela(valor)

    mapeamentos = {
        "faixa_freq_tx": [
            "faixa de frequencias tx mhz",
            "faixa de frequencia tx mhz",
            "faixa de frequencias tx",
            "faixa de frequencia tx",
            "faixa de frequencias mhz",
            "faixa de frequencia mhz",
            "faixa de frequencias",
            "faixa de frequencia",
            "frequency range mhz",
            "frequency range",
            "range mhz",
        ],
        "potencia_max_saida": [
            "potencia maxima de saida w",
            "potencia maxima saida w",
            "potencia maxima de saida",
            "potencia maxima saida",
            "potencia de saida w",
            "potencia saida w",
            "potencia de saida",
            "potencia saida",
            "saida w",
            "maximum output power w",
            "maximum output power",
            "maximum power w",
            "maximum power",
            "output power w",
            "output power",
            "transmitter output power",
            "transmit power",
            "tx power",
            "power w",
        ],
        "intensidade_campo": [
            "intensidade de campo uv m",
            "intensidade campo uv m",
            "intensidade de campo µv m",
            "intensidade campo µv m",
            "intensidade de campo",
            "intensidade campo",
            "field strength uv m",
            "field strength µv m",
            "field strength",
            "electric field strength",
        ],
        "designacao_emissoes": [
            "designacao de emissoes",
            "designacao de emissao",
            "designation of emission",
            "designation of emissions",
            "emissoes",
            "emission",
        ],
        "tecnologias": [
            "tecnologias",
            "tecnologia",
            "tecnologia e espalhamento",
            "tecnologia espalhamento",
            "espalhamento espectral",
            "espalhamento",
            "technology",
            "technologies",
            "spread spectrum",
            "technology spread spectrum",
        ],
        "tipo_modulacao": [
            "tipo de modulacao",
            "tipo modulacao",
            "modulacao",
            "modulation",
            "type of modulation",
        ],
        "taxa_transmissao": [
            "taxa de transmissao",
            "taxa transmissao",
            "transmission rate",
            "data rate",
            "bit rate",
            "mbit s",
            "mbps",
        ],
    }

    for canonico, aliases in mapeamentos.items():
        for alias in aliases:
            if alias in texto:
                return canonico

    return ""


def _formatar_float_tabela(numero):
    try:
        valor = float(numero)
    except Exception:
        return str(numero or "").strip()

    texto = f"{valor:.10f}".rstrip("0").rstrip(".")

    if texto == "-0":
        texto = "0"

    return texto


def _normalizar_decimal_tabela(valor):
    texto = str(valor or "").strip()
    texto = texto.replace(" ", "")

    if not texto:
        return ""

    # Formato brasileiro: 2.400,0 -> 2400.0 / 0,0063 -> 0.0063
    if "," in texto:
        texto = texto.replace(".", "")
        texto = texto.replace(",", ".")
    else:
        # Se tiver vários pontos, trata os primeiros como separador de milhar.
        if texto.count(".") > 1:
            partes = texto.split(".")
            texto = "".join(partes[:-1]) + "." + partes[-1]

    texto = re.sub(r"[^0-9.\-]", "", texto)

    if not texto or texto in {"-", ".", "-."}:
        return ""

    return _formatar_float_tabela(texto)


def _normalizar_faixa_frequencia_tabela(valor):
    texto_original = str(valor or "").strip()

    if not texto_original:
        return ""

    texto = _normalizar_texto_tabela(texto_original)

    if not texto:
        return ""

    numeros = re.findall(r"\d[\d.,]*", texto_original)

    # Se não tiver número, não é faixa de frequência.
    if not numeros:
        return ""

    texto = texto.replace("mhz", "")
    texto = texto.replace("até", "a")
    texto = texto.replace("ate", "a")
    texto = texto.replace("–", "-")
    texto = texto.replace("—", "-")
    texto = texto.replace("−", "-")

    numeros = re.findall(r"\d[\d.,]*", texto)

    if len(numeros) >= 2:
        inicio = _normalizar_decimal_tabela(numeros[0])
        fim = _normalizar_decimal_tabela(numeros[1])

        if inicio and fim:
            try:
                if abs(float(inicio) - float(fim)) < 0.000001:
                    return inicio
            except Exception:
                pass

            return f"{inicio}-{fim}"

    if len(numeros) == 1:
        valor_unico = _normalizar_decimal_tabela(numeros[0])

        if valor_unico:
            return valor_unico

    return ""


def _normalizar_potencia_tabela(valor):
    texto_original = str(valor or "").strip()

    if not texto_original:
        return ""

    texto = _normalizar_texto_tabela(texto_original)
    texto = texto.replace("watts", "")
    texto = re.sub(r"\bw\b", "", texto).strip()

    numeros = re.findall(r"\d[\d.,]*", texto_original)

    if numeros:
        return _normalizar_decimal_tabela(numeros[0])

    # Se não houver número, não é potência.
    return ""


def _normalizar_valor_tabela_por_campo(campo, valor):
    texto = _normalizar_texto_tabela(valor)

    if not texto:
        return ""

    if campo == "faixa_freq_tx":
        return _normalizar_faixa_frequencia_tabela(valor)

    if campo == "potencia_max_saida":
        return _normalizar_potencia_tabela(valor)

    if campo == "intensidade_campo":
        return _normalizar_intensidade_campo_tabela(valor)

    if campo == "designacao_emissoes":
        texto = texto.upper()
        texto = re.sub(r"[^A-Z0-9]", "", texto)
        return texto

    if campo == "tecnologias":
        texto = texto.replace("fhss", "salto em frequencia")
        texto = texto.replace("dsss", "sequencia direta")

        if "salto em frequencia" in texto:
            return "salto em frequencia"

        if "sequencia direta" in texto:
            return "sequencia direta"

        if "ofdma" in texto:
            return "ofdma"

        if "ofdm" in texto:
            return "ofdm"

        if "bluetooth low energy" in texto or "bluetooth le" in texto or "ble" == texto:
            return "bluetooth le"

        texto = re.sub(r"\s+", " ", texto).strip()
        return texto

    if campo == "tipo_modulacao":
        texto = texto.upper()
        texto = texto.replace(" ", "")
        texto = texto.replace("\\", "/")
        texto = re.sub(r"/+", "/", texto)
        texto = texto.strip("/")
        return texto

    return texto

def _normalizar_intensidade_campo_tabela(valor):
    texto = str(valor or "").strip()

    if not texto:
        return ""

    texto = texto.replace("µ", "u")
    texto = texto.replace("μ", "u")

    texto_norm = _normalizar_texto_tabela(texto)

    if texto_norm in {
        "",
        "-",
        "--",
        "---",
        "na",
        "n a",
        "n/a",
        "nao aplicavel",
        "not applicable",
    }:
        return ""

    numeros = re.findall(r"\d[\d.,]*", texto)

    if not numeros:
        return ""

    comparador = ""
    m_comp = re.search(r"(<=|>=|<|>)", texto)
    if m_comp:
        comparador = m_comp.group(1)

    numero = _normalizar_decimal_tabela(numeros[0])

    if not numero:
        return ""

    return f"{comparador}{numero}uv/m"


def _mapear_colunas_relevantes(cabecalho):
    mapeamento = {}

    for idx, col in enumerate(cabecalho or []):
        col_texto = str(col or "").strip()

        if not col_texto:
            continue

        canonico = _cabecalho_canonico(col_texto)

        if canonico and canonico not in mapeamento:
            mapeamento[canonico] = idx

        col_norm = _normalizar_texto_comparacao(col_texto)
        col_sem_espaco = re.sub(r"\s+", "", col_norm)

        if (
            "faixa de frequencia" in col_norm
            or "faixa de frequencias" in col_norm
            or "faixa frequencia" in col_norm
            or "faixa frequencias" in col_norm
            or "faixa de frequencia tx" in col_norm
            or "faixa de frequencias tx" in col_norm
            or "frequency range" in col_norm
            or "range mhz" in col_norm
            or "faixadefrequencia" in col_sem_espaco
            or "faixadefrequencias" in col_sem_espaco
            or "frequencyrange" in col_sem_espaco
        ):
            if "faixa_freq_tx" not in mapeamento:
                mapeamento["faixa_freq_tx"] = idx
            continue

        if (
            "sar" not in col_norm
            and (
                "potencia maxima de saida" in col_norm
                or "potencia maxima saida" in col_norm
                or "potencia maxima" in col_norm
                or "potencia de saida" in col_norm
                or "potencia saida" in col_norm
                or "saida w" in col_norm
                or "maximum output power" in col_norm
                or "output power" in col_norm
                or "tx power" in col_norm
                or "power w" in col_norm
                or "potenciamaximadesaida" in col_sem_espaco
                or "potenciadesaida" in col_sem_espaco
                or "maximumoutputpower" in col_sem_espaco
                or "outputpower" in col_sem_espaco
            )
        ):
            if "potencia_max_saida" not in mapeamento:
                mapeamento["potencia_max_saida"] = idx
            continue

        if (
            "intensidade de campo" in col_norm
            or "intensidade campo" in col_norm
            or "field strength" in col_norm
            or "electric field strength" in col_norm
            or "uv m" in col_norm
            or "uv/m" in col_norm
            or "intensidadedecampo" in col_sem_espaco
            or "fieldstrength" in col_sem_espaco
            or "electricfieldstrength" in col_sem_espaco
        ):
            if "intensidade_campo" not in mapeamento:
                mapeamento["intensidade_campo"] = idx
            continue

        if (
            "designacao de emissoes" in col_norm
            or "designacao das emissoes" in col_norm
            or "designacao emissoes" in col_norm
            or ("emissoes" in col_norm and "designacao" in col_norm)
            or "designation of emission" in col_norm
            or "designation of emissions" in col_norm
            or "emission designation" in col_norm
            or "emissions designation" in col_norm
            or "designacaodeemissoes" in col_sem_espaco
            or "designacaodasemissoes" in col_sem_espaco
            or "designationofemission" in col_sem_espaco
            or "designationofemissions" in col_sem_espaco
            or "emissiondesignation" in col_sem_espaco
            or "emissionsdesignation" in col_sem_espaco
        ):
            if "designacao_emissoes" not in mapeamento:
                mapeamento["designacao_emissoes"] = idx
            continue

        if (
            "tecnologia" in col_norm
            or "technology" in col_norm
            or "spread spectrum" in col_norm
            or "espalhamento" in col_norm
            or "tecnologiaespalhamento" in col_sem_espaco
            or "technologyspread" in col_sem_espaco
        ):
            if "tecnologias" not in mapeamento:
                mapeamento["tecnologias"] = idx
            continue

        if (
            "tipo de modulacao" in col_norm
            or "modulacao" in col_norm
            or "type of modulation" in col_norm
            or "modulation" in col_norm
            or "tipodemodulacao" in col_sem_espaco
            or "typeofmodulation" in col_sem_espaco
        ):
            if "tipo_modulacao" not in mapeamento:
                mapeamento["tipo_modulacao"] = idx
            continue

        if (
            "sar cabeca" in col_norm
            or "sar cabeça" in col_norm
            or "sar head" in col_norm
            or "sarcabeca" in col_sem_espaco
            or "sarhead" in col_sem_espaco
        ):
            if "sar_cabeca" not in mapeamento:
                mapeamento["sar_cabeca"] = idx
            continue

        if (
            "sar corpo" in col_norm
            or "sar body" in col_norm
            or "sarcorpo" in col_sem_espaco
            or "sarbody" in col_sem_espaco
        ):
            if "sar_corpo" not in mapeamento:
                mapeamento["sar_corpo"] = idx
            continue

        if (
            "taxa de transmissao" in col_norm
            or "taxa transmissao" in col_norm
            or "transmission rate" in col_norm
            or "taxadetransmissao" in col_sem_espaco
            or "transmissionrate" in col_sem_espaco
        ):
            if "taxa_transmissao" not in mapeamento:
                mapeamento["taxa_transmissao"] = idx
            continue

        if (
            "padrao" in col_norm
            or "standard" in col_norm
        ):
            if "padrao" not in mapeamento:
                mapeamento["padrao"] = idx
            continue

    return mapeamento


def _tabela_tem_coluna_intensidade(tabela):
    tabela = tabela or {}
    cabecalho = list(tabela.get("cabecalho", []) or [])
    mapa_colunas = _mapear_colunas_relevantes(cabecalho)

    return "intensidade_campo" in mapa_colunas


def _tabela_tem_coluna_potencia(tabela):
    tabela = tabela or {}
    cabecalho = list(tabela.get("cabecalho", []) or [])
    mapa_colunas = _mapear_colunas_relevantes(cabecalho)

    return "potencia_max_saida" in mapa_colunas


def _extrair_linhas_comparaveis(tabela, usar_potencia=True, usar_intensidade=False):
    tabela = tabela or {}
    cabecalho = list(tabela.get("cabecalho", []) or [])
    linhas = [list(l) for l in (tabela.get("linhas", []) or [])]

    mapa_colunas = _mapear_colunas_relevantes(cabecalho)

    linhas_saida = []
    ultima_faixa_valida = ""

    for linha in linhas:
        idx_faixa = mapa_colunas.get("faixa_freq_tx")
        valor_faixa = (
            linha[idx_faixa]
            if idx_faixa is not None and idx_faixa < len(linha)
            else ""
        )

        faixa = _normalizar_valor_tabela_por_campo(
            "faixa_freq_tx",
            valor_faixa,
        )

        # CCT pode vir com célula mesclada:
        # primeira linha tem a faixa e as próximas vêm vazias.
        if faixa:
            ultima_faixa_valida = faixa
        else:
            faixa = ultima_faixa_valida

        potencia = ""

        if usar_potencia:
            idx_potencia = mapa_colunas.get("potencia_max_saida")
            valor_potencia = (
                linha[idx_potencia]
                if idx_potencia is not None and idx_potencia < len(linha)
                else ""
            )

            potencia = _normalizar_valor_tabela_por_campo(
                "potencia_max_saida",
                valor_potencia,
            )

        intensidade = ""

        if usar_intensidade:
            idx_intensidade = mapa_colunas.get("intensidade_campo")
            valor_intensidade = (
                linha[idx_intensidade]
                if idx_intensidade is not None and idx_intensidade < len(linha)
                else ""
            )

            intensidade = _normalizar_valor_tabela_por_campo(
                "intensidade_campo",
                valor_intensidade,
            )

        if not faixa:
            continue

        if usar_potencia and not potencia:
            continue

        registro = {
            "faixa_freq_tx": faixa,
        }

        if usar_potencia:
            registro["potencia_max_saida"] = potencia

        if usar_intensidade:
            registro["intensidade_campo"] = intensidade

        linhas_saida.append(registro)

    return linhas_saida


def _assinatura_linha_tabela(registro, usar_potencia=True, usar_intensidade=False):
    faixa = registro.get("faixa_freq_tx", "")
    potencia = registro.get("potencia_max_saida", "") if usar_potencia else ""
    intensidade = registro.get("intensidade_campo", "") if usar_intensidade else ""

    return (
        faixa,
        potencia,
        intensidade,
    )


def _assinaturas_unicas_tabela(linhas, usar_potencia=True, usar_intensidade=False):
    assinaturas = set()

    for linha in linhas or []:
        assinatura = _assinatura_linha_tabela(
            linha,
            usar_potencia=usar_potencia,
            usar_intensidade=usar_intensidade,
        )

        faixa, potencia, intensidade = assinatura

        if not faixa:
            continue

        if usar_potencia and not potencia:
            continue

        assinaturas.add(assinatura)

    return sorted(assinaturas)


def comparar_tabelas_tecnicas_sch_cct(tabela_sch, tabela_cct):
    tem_potencia_sch = _tabela_tem_coluna_potencia(tabela_sch)
    tem_potencia_cct = _tabela_tem_coluna_potencia(tabela_cct)

    tem_intensidade_sch = _tabela_tem_coluna_intensidade(tabela_sch)
    tem_intensidade_cct = _tabela_tem_coluna_intensidade(tabela_cct)

    usar_potencia = bool(tem_potencia_sch or tem_potencia_cct)
    usar_intensidade = bool(tem_intensidade_sch or tem_intensidade_cct)

    linhas_sch = _extrair_linhas_comparaveis(
        tabela_sch,
        usar_potencia=usar_potencia,
        usar_intensidade=usar_intensidade,
    )

    linhas_cct = _extrair_linhas_comparaveis(
        tabela_cct,
        usar_potencia=usar_potencia,
        usar_intensidade=usar_intensidade,
    )

    # Se a coluna de intensidade existe, mas nenhum valor real foi extraído,
    # volta para comparação sem intensidade.
    if usar_intensidade:
        existe_valor_intensidade = any(
            linha.get("intensidade_campo")
            for linha in linhas_sch + linhas_cct
        )

        if not existe_valor_intensidade:
            usar_intensidade = False

            linhas_sch = _extrair_linhas_comparaveis(
                tabela_sch,
                usar_potencia=usar_potencia,
                usar_intensidade=False,
            )

            linhas_cct = _extrair_linhas_comparaveis(
                tabela_cct,
                usar_potencia=usar_potencia,
                usar_intensidade=False,
            )

    if not linhas_sch and not linhas_cct:
        return {
            "status": "sem_tabela",
            "motivo": "nenhuma_tabela_disponivel",
            "divergencias": [],
        }

    assinaturas_sch = _assinaturas_unicas_tabela(
        linhas_sch,
        usar_potencia=usar_potencia,
        usar_intensidade=usar_intensidade,
    )

    assinaturas_cct = _assinaturas_unicas_tabela(
        linhas_cct,
        usar_potencia=usar_potencia,
        usar_intensidade=usar_intensidade,
    )

    set_sch = set(assinaturas_sch)
    set_cct = set(assinaturas_cct)

    divergencias = []

    faltando_no_cct = sorted(set_sch - set_cct)
    faltando_no_sch = sorted(set_cct - set_sch)

    campos_comparados = [
        "Faixa de Frequências Tx (MHz)",
    ]

    if usar_potencia:
        campos_comparados.append(
            "Potência de Saída / Potência Máxima de Saída (W)"
        )

    if usar_intensidade:
        campos_comparados.append("Intensidade de Campo (µV/m)")

    nome_coluna = " / ".join(campos_comparados)

    def _descricao_assinatura(faixa, potencia, intensidade):
        partes = [f"Faixa={faixa or 'vazio'}"]

        if usar_potencia:
            partes.append(f"Potência={potencia or 'vazio'}")

        if usar_intensidade:
            partes.append(f"Intensidade={intensidade or 'vazio'}")

        return " | ".join(partes)

    for faixa, potencia, intensidade in faltando_no_cct:
        divergencias.append(
            {
                "tipo": "combinacao_ausente_no_cct",
                "linha": "",
                "coluna": nome_coluna,
                "nome_coluna": nome_coluna,
                "valor_sch": _descricao_assinatura(faixa, potencia, intensidade),
                "valor_cct": "Não encontrada no CCT",
            }
        )

    for faixa, potencia, intensidade in faltando_no_sch:
        divergencias.append(
            {
                "tipo": "combinacao_ausente_no_sch",
                "linha": "",
                "coluna": nome_coluna,
                "nome_coluna": nome_coluna,
                "valor_sch": "Não encontrada no SCH",
                "valor_cct": _descricao_assinatura(faixa, potencia, intensidade),
            }
        )

    return {
        "status": "ok" if not divergencias else "divergente",
        "motivo": (
            "comparacao_por_faixa_potencia_e_intensidade"
            if usar_intensidade
            else "comparacao_por_faixa_e_potencia"
            if usar_potencia
            else "comparacao_por_faixa_de_frequencia"
        ),
        "linhas_sch": len(assinaturas_sch),
        "linhas_cct": len(assinaturas_cct),
        "linhas_extraidas_sch": len(linhas_sch),
        "linhas_extraidas_cct": len(linhas_cct),
        "usar_potencia": usar_potencia,
        "usar_intensidade": usar_intensidade,
        "campos_comparados": campos_comparados,
        "colunas_ignoradas_do_cct": [
            "Designação de Emissões / Designation of Emissions",
            "Tecnologia / Technology",
            "Tipo de Modulação / Type of Modulation",
            "SAR Cabeça / SAR head",
            "SAR Corpo / SAR body",
            "Padrão / Standard",
            "Taxa de transmissão / Transmission rate",
        ],
        "assinaturas_sch": [
            {
                "faixa_freq_tx": faixa,
                "potencia_max_saida": potencia,
                "intensidade_campo": intensidade,
            }
            for faixa, potencia, intensidade in assinaturas_sch
        ],
        "assinaturas_cct": [
            {
                "faixa_freq_tx": faixa,
                "potencia_max_saida": potencia,
                "intensidade_campo": intensidade,
            }
            for faixa, potencia, intensidade in assinaturas_cct
        ],
        "divergencias": divergencias,
    }


def extrair_tabela_tecnica_sch(driver, wait):
    clicar_aba_caracteristicas_tecnicas(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    def _extrair_tabela_html_basica(tabela):
        trs = tabela.find_elements(By.XPATH, "./thead/tr | ./tbody/tr | ./tr")
        if not trs:
            trs = tabela.find_elements(By.XPATH, ".//tr")

        cabecalho = []
        linhas = []

        for tr in trs:
            celulas = tr.find_elements(By.XPATH, "./th | ./td")
            valores = [_texto_limpo(c.text) for c in celulas]

            if not any(valores):
                continue

            if not cabecalho and _eh_linha_cabecalho_tabela_sch(valores):
                cabecalho = valores
                continue

            linhas.append(valores)

        if not cabecalho and linhas:
            primeira = linhas[0]
            if _eh_linha_cabecalho_tabela_sch(primeira):
                cabecalho = primeira
                linhas = linhas[1:]

        return _limpar_tabela_tecnica_sch(cabecalho, linhas)

    def _pontuar_tabela_sch(tabela_limpa):
        tabela_limpa = tabela_limpa or {}
        cabecalho = tabela_limpa.get("cabecalho", []) or []

        mapa = _mapear_colunas_relevantes(cabecalho)

        tem_faixa = "faixa_freq_tx" in mapa
        tem_potencia = "potencia_max_saida" in mapa
        tem_intensidade = "intensidade_campo" in mapa

        if not tem_faixa:
            return -1, []

        usar_potencia = tem_potencia
        usar_intensidade = tem_intensidade

        linhas_comp = _extrair_linhas_comparaveis(
            tabela_limpa,
            usar_potencia=usar_potencia,
            usar_intensidade=usar_intensidade,
        )

        assinaturas = _assinaturas_unicas_tabela(
            linhas_comp,
            usar_potencia=usar_potencia,
            usar_intensidade=usar_intensidade,
        )

        pontuacao = 0
        pontuacao += 50 if tem_faixa else 0
        pontuacao += 35 if tem_potencia else 0
        pontuacao += 25 if tem_intensidade else 0
        pontuacao += len(linhas_comp) * 10
        pontuacao += len(assinaturas) * 5

        return pontuacao, linhas_comp

    xpaths_tabela = [
        "//table[.//th[contains(., 'Faixa')] and .//th[contains(., 'Pot')]]",
        "//table[.//th[contains(., 'Frequ')] and .//th[contains(., 'Pot')]]",
        "//table[.//td[contains(., 'Faixa')] and .//td[contains(., 'Pot')]]",
        "//table[.//td[contains(., 'Frequ')] and .//td[contains(., 'Pot')]]",

        "//table[.//th[contains(., 'Faixa')] and .//th[contains(., 'Intensidade')]]",
        "//table[.//th[contains(., 'Frequ')] and .//th[contains(., 'Campo')]]",
        "//table[.//td[contains(., 'Faixa')] and .//td[contains(., 'Intensidade')]]",
        "//table[.//td[contains(., 'Frequ')] and .//td[contains(., 'Campo')]]",

        "//table[.//th[contains(., 'Frequ')] and .//th[contains(., 'Emiss')]]",
        "//table[.//td[contains(., 'Frequ')] and .//td[contains(., 'Emiss')]]",
    ]

    candidatos = []

    for xp in xpaths_tabela:
        try:
            candidatos.extend(driver.find_elements(By.XPATH, xp))
        except Exception:
            continue

    # Fallback: avalia todas as tabelas visíveis, mas escolhe a melhor por pontuação.
    try:
        candidatos.extend(driver.find_elements(By.XPATH, "//table"))
    except Exception:
        pass

    candidatos_unicos = []
    vistos = set()

    for tabela in candidatos:
        try:
            chave = tabela.id
        except Exception:
            chave = None

        if chave and chave in vistos:
            continue

        if chave:
            vistos.add(chave)

        candidatos_unicos.append(tabela)

    melhor_tabela = None
    melhor_pontuacao = -1

    for tabela in candidatos_unicos:
        try:
            if not tabela.is_displayed():
                continue

            tabela_limpa = _extrair_tabela_html_basica(tabela)
            pontuacao, linhas_comp = _pontuar_tabela_sch(tabela_limpa)

            if pontuacao > melhor_pontuacao and linhas_comp:
                melhor_pontuacao = pontuacao
                melhor_tabela = tabela_limpa

        except Exception:
            continue

    if melhor_tabela:
        return melhor_tabela

    return {"cabecalho": [], "linhas": []}


def _normalizar_cabecalho_tabela_sch(texto):
    texto = _texto_limpo(texto)
    texto = _remover_acentos(texto).lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _eh_linha_cabecalho_tabela_sch(celulas):
    if not celulas:
        return False

    texto = " | ".join(_normalizar_cabecalho_tabela_sch(c) for c in celulas if c)

    tem_faixa = (
        "faixa" in texto
        or "frequencia" in texto
        or "frequencias" in texto
        or "frequency range" in texto
    )

    tem_potencia = (
        "potencia" in texto
        or "potência" in texto
        or "saida" in texto
        or "saída" in texto
        or "output power" in texto
        or "power" in texto
    )

    tem_intensidade = (
        "intensidade" in texto
        or "field strength" in texto
        or "uv/m" in texto
        or "µv/m" in texto
    )

    if tem_faixa and (tem_potencia or tem_intensidade):
        return True

    sinais = [
        "faixa",
        "frequencia",
        "frequencias",
        "frequency range",
        "potencia",
        "saida",
        "output power",
        "power",
        "intensidade",
        "field strength",
        "uv/m",
        "µv/m",
    ]

    return sum(1 for s in sinais if s in texto) >= 2


def _limpar_tabela_tecnica_sch(cabecalho, linhas):
    cabecalho = [_texto_limpo(c) for c in (cabecalho or [])]
    linhas = [[_texto_limpo(c) for c in (linha or [])] for linha in (linhas or [])]

    total_colunas = max([len(cabecalho)] + [len(l) for l in linhas] + [0])
    if total_colunas == 0:
        return {"cabecalho": [], "linhas": []}

    cabecalho = cabecalho + [""] * (total_colunas - len(cabecalho))
    linhas = [l + [""] * (total_colunas - len(l)) for l in linhas]

    manter = []
    for idx in range(total_colunas):
        valores_coluna = [cabecalho[idx]] + [linha[idx] for linha in linhas]
        if any(_texto_limpo(v) for v in valores_coluna):
            manter.append(idx)

    cabecalho = [cabecalho[idx] for idx in manter]
    linhas = [[linha[idx] for idx in manter] for linha in linhas]

    return {
        "cabecalho": cabecalho,
        "linhas": [linha for linha in linhas if any(_texto_limpo(c) for c in linha)],
    }


def _normalizar_modelo_item(valor):
    texto = str(valor or "").strip().upper()

    if not texto:
        return ""

    texto = texto.replace(",", " ")
    texto = texto.replace(";", " ")
    texto = texto.replace("/", " ")
    texto = re.sub(r"\s+", " ", texto).strip()

    # Mantém letras, números, hífen e ponto.
    texto = re.sub(r"[^A-Z0-9.\-]+", "", texto)

    return texto


def _extrair_modelos_unicos(valor):
    """
    Extrai modelos únicos de textos como:
    'A6S A6S A6S A6S'
    'TC320B-G, TC320C-G1, TC321B-G e TC321C-G'
    """
    texto = str(valor or "").strip()

    if not texto:
        return []

    texto = texto.replace(",", " ")
    texto = texto.replace(";", " ")
    texto = texto.replace("\n", " ")
    texto = re.sub(r"\s+e\s+", " ", texto, flags=re.I)
    texto = re.sub(r"\s+and\s+", " ", texto, flags=re.I)
    texto = re.sub(r"\s+", " ", texto).strip()

    candidatos = texto.split(" ")

    modelos = []

    for item in candidatos:
        modelo = _normalizar_modelo_item(item)

        if not modelo:
            continue

        if len(modelo) < 2:
            continue

        if modelo not in modelos:
            modelos.append(modelo)

    return modelos


def _comparar_modelos_sch_x_cct(modelo_sch, modelo_cct):
    modelos_sch = _extrair_modelos_unicos(modelo_sch)
    modelos_cct = _extrair_modelos_unicos(modelo_cct)

    if not modelos_sch and not modelos_cct:
        return {
            "campo": "modelo",
            "status": "ausente_nos_dois",
            "valor_sch": modelo_sch or "",
            "valor_cct": modelo_cct or "",
            "valor_sch_normalizado": "",
            "valor_cct_normalizado": "",
            "modelos_sch_unicos": modelos_sch,
            "modelos_cct_unicos": modelos_cct,
            "diverge": False,
            "observacao": "Modelo não identificado no SCH nem no CCT.",
        }

    if not modelos_sch or not modelos_cct:
        return {
            "campo": "modelo",
            "status": "ausente_em_um_dos_lados",
            "valor_sch": modelo_sch or "",
            "valor_cct": modelo_cct or "",
            "valor_sch_normalizado": " ".join(modelos_sch),
            "valor_cct_normalizado": " ".join(modelos_cct),
            "modelos_sch_unicos": modelos_sch,
            "modelos_cct_unicos": modelos_cct,
            "diverge": True,
            "observacao": "Modelo identificado apenas em um dos lados.",
        }

    set_sch = set(modelos_sch)
    set_cct = set(modelos_cct)

    if set_sch == set_cct:
        return {
            "campo": "modelo",
            "status": "ok",
            "valor_sch": modelo_sch or "",
            "valor_cct": modelo_cct or "",
            "valor_sch_normalizado": " ".join(modelos_sch),
            "valor_cct_normalizado": " ".join(modelos_cct),
            "modelos_sch_unicos": modelos_sch,
            "modelos_cct_unicos": modelos_cct,
            "diverge": False,
            "observacao": "Modelos conferem após remover repetições.",
        }

    faltando_no_cct = sorted(set_sch - set_cct)
    faltando_no_sch = sorted(set_cct - set_sch)
    
    if _modelo_generico_ou_incompleto(modelo_sch) and not _modelo_generico_ou_incompleto(modelo_cct):
        return{
            "campo": "modelo",
            "status": "NC",
            "valor_sch": modelo_sch,
            "valor_cct": modelo_cct,
            "valor_sch_normalizado": modelo_sch,
            "valor_cct_normalizado": modelo_cct,
            "diverge": True,
            "observacao": (
                "Modelo do SCH parece incompleto/genérico."
                "Conferir manualmente contra o modelo completo do CCT."
            ),
        }
    if _modelo_generico_ou_incompleto(modelo_cct) and not _modelo_generico_ou_incompleto(modelo_sch):
        return{
            "campo": "modelo",
            "status": "NC",
            "valor_sch": modelo_sch,
            "valor_cct": modelo_cct,
            "valor_sch_normalizado": modelo_sch,
            "valor_cct_normalizado": modelo_cct,
            "diverge": True,
            "observacao": (
                "Modelo extraido do CCT parece incompleto/genérico."
                "Conferir manualmente a extração do PDF."
            ),
        }



    return {
        "campo": "modelo",
        "status": "divergente",
        "valor_sch": modelo_sch or "",
        "valor_cct": modelo_cct or "",
        "valor_sch_normalizado": " ".join(modelos_sch),
        "valor_cct_normalizado": " ".join(modelos_cct),
        "modelos_sch_unicos": modelos_sch,
        "modelos_cct_unicos": modelos_cct,
        "faltando_no_cct": faltando_no_cct,
        "faltando_no_sch": faltando_no_sch,
        "diverge": True,
        "observacao": (
            "Modelos divergentes após remover repetições. "
            f"Faltando no CCT: {', '.join(faltando_no_cct) or 'nenhum'}. "
            f"Faltando no SCH: {', '.join(faltando_no_sch) or 'nenhum'}."
        ),
    }
def _modelo_generico_ou_incompleto(valor):
    valor_norm = _normalizar_texto_comparacao(valor)
    valor_sem_espaco = re.sub(r"[^a-z0-9]+", "", valor_norm)

    if not valor_sem_espaco:
        return True

    genericos = {
        "ai",
        "ia",
        "wifi",
        "bluetooth",
        "ble",
        "bt",
        "model",
        "modelo",
        "models",
        "modelos",
    }

    if valor_sem_espaco in genericos:
        return True

    # Um modelo muito curto sem número geralmente é inseguro.
    if len(valor_sem_espaco) <= 2 and not re.search(r"\d", valor_sem_espaco):
        return True

    return False


def comparar_dados_sch_x_cct(req, dados_pdf):
    req = req or {}
    dados_pdf = dados_pdf or {}

    comparacoes = [
        _comparar_valores(
            req.get("certificado", ""),
            dados_pdf.get("numero_certificado", ""),
            "certificado",
            modo="texto_flex",
        ),
        _comparar_valores(
            req.get("homologacao", ""),
            dados_pdf.get("homologacao", ""),
            "homologacao",
            modo="numero",
        ),
        _comparar_modelos_sch_x_cct(
            req.get("modelo", ""),
            dados_pdf.get("modelo", ""),
        ),
        _comparar_valores(
            req.get("fabricante", ""),
            dados_pdf.get("fabricante", ""),
            "fabricante",
            modo="texto_flex",
        ),
        _comparar_valores(
            req.get("tipo_produto", ""),
            dados_pdf.get("tipo_produto", ""),
            "tipo_produto",
            modo="texto_flex",
        ),
    ]

    divergencias = [item for item in comparacoes if item.get("diverge")]
    campos_ausentes = [
        item for item in comparacoes
        if item.get("status") in {"ausente_nos_dois", "ausente_em_um_dos_lados"}
    ]

    comparacao_tabela = comparar_tabelas_tecnicas_sch_cct(
        req.get("tabela_tecnica_sch"),
        dados_pdf.get("tabela_tecnica_cct"),
    )

    if comparacao_tabela.get("status") == "divergente":
        divergencias.append(
            {
                "campo": "tabela_tecnica",
                "status": "divergente",
                "valor_sch": "Tabela técnica do SCH",
                "valor_cct": "Tabela técnica do CCT",
                "diverge": True,
                "detalhes_tabela": comparacao_tabela,
            }
        )

    if divergencias:
        status_geral = "divergente"
    elif campos_ausentes:
        status_geral = "parcial"
    else:
        status_geral = "ok"

    return {
        "status_geral": status_geral,
        "comparacoes": comparacoes,
        "divergencias": divergencias,
        "campos_ausentes": campos_ausentes,
        "comparacao_tabela_tecnica": comparacao_tabela,
        "requerimento": req.get("requerimento", ""),
    }


def avisar_resultado_conferencia_sch_cct(resultado):
    resultado = resultado or {}
    requerimento = resultado.get("requerimento", "") or "sem_numero"
    divergencias = resultado.get("divergencias", []) or []

    if not divergencias:
        print(f"[SCH] Conferência SCH x CCT OK no requerimento {requerimento}.")
        resultado["mensagens_humanas"] = []
        return

    mensagens_humanas = []

    print(f"[SCH][INCONGRUÊNCIA] Requerimento {requerimento}")

    nomes_campos = {
        "certificado": "Certificado",
        "homologacao": "Homologação",
        "modelo": "Modelo",
        "fabricante": "Fabricante",
        "tipo_produto": "Tipo do produto",
        "tabela_tecnica": "Tabela técnica",
    }

    for item in divergencias:
        campo = item.get("campo", "")
        nome_campo = nomes_campos.get(campo, campo.replace("_", " ").title())

        if campo == "tabela_tecnica":
            detalhes = item.get("detalhes_tabela", {}) or {}
            diverg_tabela = detalhes.get("divergencias", []) or []

            if not diverg_tabela:
                mensagem = "Tabela técnica: divergência identificada, mas sem detalhes disponíveis."
                print(f"[SCH][INCONGRUÊNCIA] - {mensagem}")
                mensagens_humanas.append(mensagem)
                continue

            for div in diverg_tabela:
                tipo = div.get("tipo", "")

                if tipo == "quantidade_linhas_diferente":
                    mensagem = (
                        "Tabela técnica: quantidade de linhas diferente. "
                        f"No SCH há {div.get('linhas_sch', 0)} linha(s) e no CCT há {div.get('linhas_cct', 0)} linha(s)."
                    )
                elif tipo == "quantidade_colunas_diferente_na_linha":
                    mensagem = (
                        f"Tabela técnica: quantidade de colunas diferente na linha {div.get('linha', '')}. "
                        f"No SCH há {div.get('colunas_sch', 0)} coluna(s) e no CCT há {div.get('colunas_cct', 0)} coluna(s)."
                    )
                elif tipo == "valor_diferente":
                    mensagem = (
                        f"Tabela técnica, linha {div.get('linha', '')}, campo '{div.get('nome_coluna', '')}': "
                        f'no SCH está "{div.get("valor_sch", "")}", mas no CCT está "{div.get("valor_cct", "")}".'
                    )
                else:
                    mensagem = f"Tabela técnica: divergência detectada ({tipo})."

                print(f"[SCH][INCONGRUÊNCIA] - {mensagem}")
                mensagens_humanas.append(mensagem)

            continue

        valor_sch = (item.get("valor_sch") or "").strip()
        valor_cct = (item.get("valor_cct") or "").strip()

        if not valor_sch:
            valor_sch = "não foi identificado"
        if not valor_cct:
            valor_cct = "não foi identificado"

        mensagem = (
            f'{nome_campo}: no SCH está "{valor_sch}", '
            f'mas no CCT está "{valor_cct}".'
        )

        print(f"[SCH][INCONGRUÊNCIA] - {mensagem}")
        mensagens_humanas.append(mensagem)

    resultado["mensagens_humanas"] = mensagens_humanas


def decidir_texto_observacao_por_cct(dados_pdf):
    classificacao = (dados_pdf or {}).get("observacao_classificacao", "").strip()
    texto = (dados_pdf or {}).get("observacao_texto", "").strip()
    motivos = (dados_pdf or {}).get("observacao_motivos", []) or []

    if texto:
        return {
            "classificacao": classificacao or "extraido_do_cct",
            "texto": texto,
            "motivos": motivos,
            "origem": "cct",
        }

    print("[SCH][WARN] Não foi possível identificar a observação pelo CCT. Aplicando texto padrão.")
    return {
        "classificacao": "radiacao_restrita_padrao_fallback",
        "texto": OBS_RADIACAO_RESTRITA,
        "motivos": [],
        "origem": "fallback",
    }


def clicar_aba_caracteristicas_tecnicas(driver, wait):
    print("[SCH] Abrindo aba Características Técnicas...")
    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Características Técnicas",
        rotulos_alternativos=["Caracteristicas Tecnicas", "Características", "Caracteristicas"],
        condicao_pronta=_ha_campo_caracteristicas,
        timeout_click=1.2,
        timeout_pronta=1.2,
    )


def _preencher_texto_em_area(driver, wait, texto, descricao, xpaths_input, xpaths_editor=None):
    if not texto:
        print(f"[SCH][WARN] Texto vazio para {descricao}.")
        return False

    texto_plano = texto.replace("<br>", "\n").strip()
    html = texto.replace("\n", "<br>")

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    for xpath in xpaths_input:
        try:
            elementos = WebDriverWait(driver, 3).until(
                EC.presence_of_all_elements_located((By.XPATH, xpath))
            )

            for campo in elementos:
                try:
                    if not campo.is_displayed() or not campo.is_enabled():
                        continue

                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo)
                    _clicar_com_fallback(driver, campo)

                    try:
                        campo.send_keys(Keys.CONTROL, "a")
                        campo.send_keys(Keys.DELETE)
                        campo.send_keys(texto_plano)
                    except Exception:
                        driver.execute_script("arguments[0].value = arguments[1];", campo, texto_plano)

                    driver.execute_script(
                        """
                        arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                        """,
                        campo,
                    )

                    try:
                        campo.send_keys(Keys.TAB)
                    except Exception:
                        pass

                    esperar_tela_carregar(driver, 0.08)
                    return True

                except Exception:
                    continue

        except Exception:
            pass

    xpaths_editor = xpaths_editor or [
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//div[contains(@class,'ui-editor')]//*[@contenteditable='true']",
    ]

    entrar_iframe_detalhe_analise(driver, wait)

    if _tentar_preencher_editor_rico(driver, xpaths_editor, html):
        esperar_tela_carregar(driver, 0.08)
        return True

    raise Exception(f"Não foi possível localizar o campo de texto: {descricao}")

def preencher_observacao_caracteristicas(driver, wait, texto):
    print(f"[SCH] Preenchendo observação técnica: {texto}")

    xpaths_input = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'OBSERVA')]"
        "/following::*[self::textarea or self::input][1]",

        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",

        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CARACTERISTICA')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CARACTERISTICA')]",
    ]

    return _preencher_texto_em_area(
        driver,
        wait,
        texto,
        "observação em Características Técnicas",
        xpaths_input,
    )



TITULOS_CARACTERISTICAS_SECUNDARIAS = [
    {
        "categoria": "Carregador Indutivo para Telefone Celular",
        "aliases": [
            "carregador indutivo para telefone celular",
            "carregador indutivo",
            "wireless charger",
        ],
        "titulo": (
            "O produto incorpora um módulo “Carregador Indutivo para "
            "Telefone Celular” com as seguintes características técnicas:"
        ),
    },
    {
        "categoria": "Dispositivo de Operação Periódica",
        "aliases": [
            "dispositivo de operacao periodica",
            "periodic operation device",
        ],
        "titulo": (
            "O produto incorpora um módulo “Dispositivo de Operação "
            "Periódica” com as seguintes características técnicas:"
        ),
    },
    {
        "categoria": "Estação Terminal de Acesso",
        "aliases": [
            "estacao terminal de acesso",
            "terminal de acesso",
            "access terminal",
        ],
        "titulo": (
            'O produto incorpora um módulo "Estação Terminal de Acesso" '
            "com as seguintes características:"
        ),
    },
    {
        "categoria": "Sistema de Identificação por Radiofrequências",
        "aliases": [
            "sistema de identificacao por radiofrequencias",
            "sistemas de identificacao por radiofrequencias",
            "identificacao por radiofrequencias",
            "rfid",
        ],
        "titulo": (
            "O produto incorpora Sistema de Identificação por "
            "Radiofrequências com as seguintes características:"
        ),
    },
    {
        "categoria": "Sistemas Operando nas Faixas de RF Ultra Larga",
        "aliases": [
            "sistemas operando nas faixas de rf ultra larga",
            "faixas de rf ultra larga",
            "ultra larga",
            "ultra wideband",
            "uwb",
        ],
        "titulo": (
            "O produto incorpora Sistemas Operando nas Faixas de RF Ultra "
            "Larga com as seguintes características:"
        ),
    },
    {
        "categoria": "Transceptor Mpo",
        "aliases": [
            "transceptor mpo",
        ],
        "titulo": (
            "O produto incorpora Transceptor Mpo com as seguintes "
            "características:"
        ),
    },
    {
        "categoria": (
            "Transceptor para Sistema Automático de Identificação de Navios"
        ),
        "aliases": [
            "transceptor para sistema automatico de identificacao de navios",
            "sistema automatico de identificacao de navios",
            "automatic identification system",
        ],
        "titulo": (
            "O produto incorpora Transceptor para Sistema Automático de "
            "Identificação de Navios com as seguintes características:"
        ),
    },
    {
        "categoria": "Transceptor Móvel por Satélite",
        "aliases": [
            "transceptor movel por satelite",
            "movel por satelite",
            "mobile satellite transceiver",
        ],
        "titulo": (
            "O produto incorpora Transceptor Móvel por Satélite com as "
            "seguintes características:"
        ),
    },
    {
        "categoria": "Sistema de Aplicações Médicas",
        "aliases": [
            "sistema de aplicacoes medicas",
            "aplicacoes medicas",
            "aplicacao medica",
            "medical application system",
        ],
        "titulo": (
            "O produto incorpora Sistema de Aplicações Médicas com as "
            "seguintes características:"
        ),
    },
    {
        "categoria": (
            "Equipamento de Radiocomunicação de Radiação Restrita"
        ),
        "aliases": [
            "equipamento de radiocomunicacao de radiacao restrita",
            "radiocomunicacao de radiacao restrita",
        ],
        "titulo": (
            "O produto incorpora Equipamento de Radiocomunicação de "
            "Radiação Restrita com as seguintes características:"
        ),
    },
    {
        "categoria": "Transceptor de Radiação Restrita",
        "aliases": [
            "transceptor de radiacao restrita",
        ],
        "titulo": (
            "O produto incorpora Transceptor de Radiação Restrita com as "
            "seguintes características:"
        ),
    },
]


def _registro_titulo_secundario_por_texto(valor):
    """
    Converte uma categoria, título ou trecho do CCT em um registro canônico.
    Evita devolver diretamente uma frase inferida incorretamente pelo parser.
    """
    valor_norm = _normalizar_texto_comparacao(valor)

    if not valor_norm:
        return None

    melhor = None
    melhor_tamanho = -1

    for registro in TITULOS_CARACTERISTICAS_SECUNDARIAS:
        termos = [
            registro.get("categoria", ""),
            registro.get("titulo", ""),
            *(registro.get("aliases") or []),
        ]

        for termo in termos:
            termo_norm = _normalizar_texto_comparacao(termo)

            if not termo_norm or termo_norm not in valor_norm:
                continue

            # Prefere a expressão mais específica. Isso impede que uma
            # ocorrência genérica de "radiação restrita" vença uma categoria
            # completa como Equipamento de Radiocomunicação.
            if len(termo_norm) > melhor_tamanho:
                melhor = registro
                melhor_tamanho = len(termo_norm)

    return melhor


def _pontuar_categoria_secundaria(
    pontos,
    origens,
    registro,
    valor,
    peso,
    origem,
):
    if registro is None:
        return

    categoria = registro["categoria"]
    valor_norm = _normalizar_texto_comparacao(valor)

    if not valor_norm:
        return

    termos = [
        registro.get("categoria", ""),
        registro.get("titulo", ""),
        *(registro.get("aliases") or []),
    ]

    melhor_termo = ""

    for termo in termos:
        termo_norm = _normalizar_texto_comparacao(termo)
        if termo_norm and termo_norm in valor_norm:
            if len(termo_norm) > len(melhor_termo):
                melhor_termo = termo_norm

    if not melhor_termo:
        return

    pontos[categoria] = pontos.get(categoria, 0) + int(peso)
    origens.setdefault(categoria, []).append(
        {
            "origem": origem,
            "peso": int(peso),
            "termo": melhor_termo,
        }
    )


def _extrair_titulos_explicitos_secundarios_cct(texto_cct):
    """
    Procura títulos explícitos do CCT, por exemplo:

    Características como Equipamento de Radiocomunicação de Radiação Restrita:

    A busca é feita por linha e também no texto contínuo, para tolerar PDFs
    cuja extração quebre o título em mais de uma linha.
    """
    texto_cct = str(texto_cct or "")
    encontrados = []

    linhas = [
        re.sub(r"\s+", " ", linha).strip()
        for linha in texto_cct.splitlines()
        if str(linha or "").strip()
    ]

    janelas = list(linhas)

    for indice in range(len(linhas)):
        janelas.append(" ".join(linhas[indice:indice + 3]))

    texto_continuo = re.sub(r"\s+", " ", texto_cct).strip()
    if texto_continuo:
        janelas.append(texto_continuo)

    marcadores = [
        "caracteristicas como",
        "caracteristicas tecnicas como",
        "caracteristicas de",
        "caracteristicas tecnicas de",
    ]

    for janela in janelas:
        janela_norm = _normalizar_texto_comparacao(janela)

        if not any(marcador in janela_norm for marcador in marcadores):
            continue

        registro = _registro_titulo_secundario_por_texto(janela)

        if registro and registro not in encontrados:
            encontrados.append(registro)

    return encontrados


def _contexto_tabela_secundaria_sch(driver, campo):
    """
    Captura o contexto da tabela técnica secundária localizada logo após o
    campo de título no SCH.

    Esse contexto não decide sozinho a categoria, mas serve como confirmação.
    No caso de Equipamento de Radiocomunicação, normalmente aparecem
    Intensidade de Campo e Distância da Medida.
    """
    try:
        tabela = campo.find_element(By.XPATH, "./following::table[1]")
        texto_tabela = _texto_limpo(tabela.text)

        return {
            "texto": texto_tabela,
            "cabecalho_normalizado": _normalizar_texto_comparacao(
                texto_tabela
            ),
        }
    except Exception:
        return {
            "texto": "",
            "cabecalho_normalizado": "",
        }


def diagnosticar_titulo_caracteristicas_secundarias(
    req=None,
    dados_pdf=None,
    contexto_sch=None,
):
    """
    Escolhe a categoria secundária usando fontes em ordem de confiança:

    1. Título explícito no texto do CCT;
    2. Categoria/título estruturado pelo parser;
    3. Contexto da tabela secundária do SCH;
    4. Ocorrências gerais no CCT, somente como último apoio.

    O tipo principal do requerimento não é usado como categoria secundária
    por simples ocorrência no texto. Ele recebe penalidade nas evidências
    fracas, evitando o falso positivo "Transceptor de Radiação Restrita".
    """
    req = req or {}
    dados_pdf = dados_pdf or {}
    contexto_sch = contexto_sch or {}

    pontos = {}
    origens = {}

    texto_cct = str(
        dados_pdf.get("texto_completo")
        or dados_pdf.get("texto")
        or dados_pdf.get("conteudo")
        or ""
    )

    caracteristicas_sec = (
        dados_pdf.get("caracteristicas_secundarias")
        if isinstance(dados_pdf.get("caracteristicas_secundarias"), dict)
        else {}
    ) or {}

    fontes_estruturadas = [
        (
            caracteristicas_sec.get("categoria"),
            110,
            "parser.caracteristicas_secundarias.categoria",
        ),
        (
            caracteristicas_sec.get("tipo"),
            105,
            "parser.caracteristicas_secundarias.tipo",
        ),
        (
            caracteristicas_sec.get("titulo"),
            100,
            "parser.caracteristicas_secundarias.titulo",
        ),
        (
            dados_pdf.get("titulo_caracteristicas_secundarias"),
            100,
            "parser.titulo_caracteristicas_secundarias",
        ),
        (
            dados_pdf.get("texto_caracteristicas_secundarias"),
            80,
            "parser.texto_caracteristicas_secundarias",
        ),
    ]

    # O título explícito do CCT tem a maior prioridade.
    for registro in _extrair_titulos_explicitos_secundarios_cct(texto_cct):
        categoria = registro["categoria"]
        pontos[categoria] = pontos.get(categoria, 0) + 180
        origens.setdefault(categoria, []).append(
            {
                "origem": "cct.titulo_explicito_caracteristicas_como",
                "peso": 180,
                "termo": _normalizar_texto_comparacao(
                    registro["categoria"]
                ),
            }
        )

    for valor, peso, origem in fontes_estruturadas:
        registro = _registro_titulo_secundario_por_texto(valor)
        _pontuar_categoria_secundaria(
            pontos,
            origens,
            registro,
            valor,
            peso,
            origem,
        )

    contexto_norm = _normalizar_texto_comparacao(
        contexto_sch.get("texto")
        or contexto_sch.get("cabecalho_normalizado")
        or ""
    )

    # Evidência típica da tabela de Equipamento de Radiocomunicação.
    if (
        "intensidade de campo" in contexto_norm
        and "distancia da medida" in contexto_norm
    ):
        registro = _registro_titulo_secundario_por_texto(
            "Equipamento de Radiocomunicação de Radiação Restrita"
        )
        categoria = registro["categoria"]
        pontos[categoria] = pontos.get(categoria, 0) + 75
        origens.setdefault(categoria, []).append(
            {
                "origem": "sch.tabela_secundaria_intensidade_e_distancia",
                "peso": 75,
                "termo": "intensidade de campo + distancia da medida",
            }
        )

    # Ocorrência geral no CCT: peso baixo, pois o texto também contém a
    # característica principal.
    for registro in TITULOS_CARACTERISTICAS_SECUNDARIAS:
        _pontuar_categoria_secundaria(
            pontos,
            origens,
            registro,
            texto_cct,
            15,
            "cct.texto_completo_ocorrencia_geral",
        )

    tipo_principal_norm = _normalizar_texto_comparacao(
        req.get("tipo_produto")
        or dados_pdf.get("tipo_produto")
        or ""
    )

    # Penaliza somente quando a categoria principal apareceu por evidência
    # fraca. Um título explícito do CCT continua podendo indicar a mesma
    # categoria como secundária.
    for registro in TITULOS_CARACTERISTICAS_SECUNDARIAS:
        categoria = registro["categoria"]
        categoria_norm = _normalizar_texto_comparacao(categoria)

        if not categoria_norm or not tipo_principal_norm:
            continue

        mesma_categoria = (
            categoria_norm == tipo_principal_norm
            or categoria_norm in tipo_principal_norm
            or tipo_principal_norm in categoria_norm
        )

        if not mesma_categoria:
            continue

        tem_titulo_explicito = any(
            item.get("origem")
            == "cct.titulo_explicito_caracteristicas_como"
            for item in origens.get(categoria, [])
        )

        if not tem_titulo_explicito:
            pontos[categoria] = pontos.get(categoria, 0) - 90
            origens.setdefault(categoria, []).append(
                {
                    "origem": "penalidade_tipo_principal_do_requerimento",
                    "peso": -90,
                    "termo": tipo_principal_norm,
                }
            )

    if not pontos:
        return {
            "titulo": "",
            "categoria": "",
            "status": "nao_identificado",
            "pontuacoes": {},
            "origens": {},
        }

    ordenados = sorted(
        pontos.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    categoria_escolhida, maior_pontuacao = ordenados[0]
    segunda_pontuacao = ordenados[1][1] if len(ordenados) > 1 else None

    registro_escolhido = next(
        (
            registro
            for registro in TITULOS_CARACTERISTICAS_SECUNDARIAS
            if registro["categoria"] == categoria_escolhida
        ),
        None,
    )

    # Exige evidência mínima. Ocorrência solta no texto completo não basta.
    seguro = bool(
        registro_escolhido
        and maior_pontuacao >= 70
        and (
            segunda_pontuacao is None
            or maior_pontuacao - segunda_pontuacao >= 20
        )
    )

    return {
        "titulo": (
            registro_escolhido["titulo"]
            if seguro and registro_escolhido
            else ""
        ),
        "categoria": categoria_escolhida if seguro else "",
        "status": "identificado" if seguro else "revisar",
        "pontuacao": maior_pontuacao,
        "segunda_pontuacao": segunda_pontuacao,
        "pontuacoes": pontos,
        "origens": origens,
        "tipo_principal": (
            req.get("tipo_produto")
            or dados_pdf.get("tipo_produto")
            or ""
        ),
    }


def escolher_titulo_caracteristicas_secundarias(
    req=None,
    dados_pdf=None,
    contexto_sch=None,
):
    diagnostico = diagnosticar_titulo_caracteristicas_secundarias(
        req=req,
        dados_pdf=dados_pdf,
        contexto_sch=contexto_sch,
    )

    return str(diagnostico.get("titulo") or "").strip()


def _localizar_campo_titulo_caracteristicas_secundarias(driver, timeout=1.5):
    """
    Localiza o campo opcional:
    'Título/Descrição para Características Técnicas Secundárias'.
    Se não existir, retorna None.
    """
    xpaths = [
        "//*[contains(normalize-space(), 'Título/Descrição para Características Técnicas Secundárias')]/following::textarea[1]",
        "//*[contains(normalize-space(), 'Titulo/Descricao para Caracteristicas Tecnicas Secundarias')]/following::textarea[1]",
        "//*[contains(normalize-space(), 'Características Técnicas Secundárias')]/following::textarea[1]",
        "//*[contains(normalize-space(), 'Caracteristicas Tecnicas Secundarias')]/following::textarea[1]",

        "//*[contains(normalize-space(), 'Título/Descrição para Características Técnicas Secundárias')]/following::input[not(@type='hidden')][1]",
        "//*[contains(normalize-space(), 'Titulo/Descricao para Caracteristicas Tecnicas Secundarias')]/following::input[not(@type='hidden')][1]",
        "//*[contains(normalize-space(), 'Características Técnicas Secundárias')]/following::input[not(@type='hidden')][1]",
        "//*[contains(normalize-space(), 'Caracteristicas Tecnicas Secundarias')]/following::input[not(@type='hidden')][1]",
    ]

    entrar_iframe_detalhe_analise(driver, None)

    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for campo in elementos:
                try:
                    if campo.is_displayed() and campo.is_enabled():
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            campo,
                        )
                        return campo
                except Exception:
                    continue

        except Exception:
            continue

    return None


def _preencher_campo_sem_apagar_se_ja_tem_valor(driver, campo, texto):
    """
    Mantém o nome antigo por compatibilidade, mas corrige o comportamento:

    - se o valor atual já estiver correto, não altera;
    - se estiver vazio, preenche;
    - se estiver preenchido com frase errada, substitui pelo título do CCT.

    A rotina antiga recusava qualquer campo já preenchido, impedindo corrigir
    exatamente o caso mostrado: Transceptor no SCH quando o CCT indicava
    Equipamento de Radiocomunicação.
    """
    texto = str(texto or "").strip()

    if not texto:
        return {
            "preenchido": False,
            "alterado": False,
            "motivo": "texto_vazio",
        }

    try:
        tag = str(campo.tag_name or "").lower()
    except Exception:
        tag = ""

    try:
        if tag in {"textarea", "input"}:
            valor_atual = driver.execute_script(
                """
                return arguments[0].value == null
                    ? ''
                    : String(arguments[0].value).trim();
                """,
                campo,
            ) or ""
        else:
            valor_atual = driver.execute_script(
                """
                return String(
                    arguments[0].innerText ||
                    arguments[0].textContent ||
                    ''
                ).trim();
                """,
                campo,
            ) or ""
    except Exception:
        valor_atual = ""

    atual_norm = _normalizar_texto_comparacao(valor_atual)
    esperado_norm = _normalizar_texto_comparacao(texto)

    if atual_norm and atual_norm == esperado_norm:
        return {
            "preenchido": True,
            "alterado": False,
            "corrigido": False,
            "motivo": "campo_ja_correto",
            "valor_atual": valor_atual,
            "texto": texto,
        }

    havia_valor = bool(atual_norm)

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        campo,
    )

    try:
        campo.click()
    except Exception:
        pass

    if tag in {"textarea", "input"}:
        try:
            campo.send_keys(Keys.CONTROL, "a")
            campo.send_keys(Keys.DELETE)
            campo.send_keys(texto)
        except Exception:
            driver.execute_script(
                """
                const campo = arguments[0];
                const valor = arguments[1];

                const proto = Object.getPrototypeOf(campo);
                const desc = Object.getOwnPropertyDescriptor(
                    proto,
                    'value'
                );

                if (desc && typeof desc.set === 'function') {
                    desc.set.call(campo, valor);
                } else {
                    campo.value = valor;
                }
                """,
                campo,
                texto,
            )
    else:
        driver.execute_script(
            "arguments[0].textContent = arguments[1];",
            campo,
            texto,
        )

    driver.execute_script(
        """
        arguments[0].dispatchEvent(
            new Event('input', {bubbles:true})
        );
        arguments[0].dispatchEvent(
            new Event('change', {bubbles:true})
        );
        arguments[0].dispatchEvent(
            new Event('blur', {bubbles:true})
        );
        """,
        campo,
    )

    try:
        campo.send_keys(Keys.TAB)
    except Exception:
        pass

    try:
        if tag in {"textarea", "input"}:
            valor_final = driver.execute_script(
                """
                return arguments[0].value == null
                    ? ''
                    : String(arguments[0].value).trim();
                """,
                campo,
            ) or ""
        else:
            valor_final = driver.execute_script(
                """
                return String(
                    arguments[0].innerText ||
                    arguments[0].textContent ||
                    ''
                ).trim();
                """,
                campo,
            ) or ""
    except Exception:
        valor_final = ""

    confirmado = (
        _normalizar_texto_comparacao(valor_final)
        == esperado_norm
    )

    return {
        "preenchido": confirmado,
        "alterado": confirmado,
        "corrigido": bool(confirmado and havia_valor),
        "motivo": (
            "campo_corrigido"
            if confirmado and havia_valor
            else "campo_preenchido"
            if confirmado
            else "valor_nao_confirmado"
        ),
        "valor_anterior": valor_atual,
        "valor_final": valor_final,
        "texto": texto,
    }


def preencher_titulo_caracteristicas_secundarias_se_existir(
    driver,
    wait,
    req=None,
    dados_pdf=None,
):
    """
    Preenche ou corrige o campo opcional de características secundárias.

    A decisão combina:
    - título explícito no CCT;
    - estrutura retornada pelo parser;
    - tipo principal do requerimento;
    - cabeçalhos da tabela secundária exibida no SCH.
    """
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    campo = _localizar_campo_titulo_caracteristicas_secundarias(
        driver,
        timeout=1.5,
    )

    if not campo:
        return {
            "campo_encontrado": False,
            "preenchido": False,
            "status": "nao_aplicavel",
            "motivo": (
                "Campo de características técnicas secundárias não "
                "encontrado na tela."
            ),
        }

    contexto_sch = _contexto_tabela_secundaria_sch(driver, campo)

    diagnostico = diagnosticar_titulo_caracteristicas_secundarias(
        req=req,
        dados_pdf=dados_pdf,
        contexto_sch=contexto_sch,
    )

    titulo = str(diagnostico.get("titulo") or "").strip()

    print(
        "[SCH][SECUNDÁRIAS] Diagnóstico: "
        f"categoria={diagnostico.get('categoria') or 'não identificada'} | "
        f"pontuação={diagnostico.get('pontuacao')} | "
        f"tipo principal={diagnostico.get('tipo_principal') or 'não identificado'}"
    )

    if not titulo:
        print(
            "[SCH][WARN] Campo de características secundárias encontrado, "
            "mas CCT e SCH não forneceram evidência segura para o título."
        )

        return {
            "campo_encontrado": True,
            "preenchido": False,
            "status": "revisar",
            "motivo": (
                "Campo encontrado, mas a categoria secundária não foi "
                "identificada com segurança."
            ),
            "diagnostico": diagnostico,
            "contexto_sch": contexto_sch,
        }

    resultado = _preencher_campo_sem_apagar_se_ja_tem_valor(
        driver,
        campo,
        titulo,
    )

    if resultado.get("motivo") == "campo_ja_correto":
        print(
            "[SCH][SECUNDÁRIAS] Título já estava correto: "
            f"{titulo}"
        )
    elif resultado.get("corrigido"):
        print(
            "[SCH][SECUNDÁRIAS] Título incorreto substituído por: "
            f"{titulo}"
        )
    elif resultado.get("preenchido"):
        print(
            "[SCH][SECUNDÁRIAS] Título preenchido: "
            f"{titulo}"
        )
    else:
        print(
            "[SCH][WARN] Não foi possível confirmar o título de "
            f"características secundárias: {resultado.get('motivo')}"
        )

    resultado.update(
        {
            "campo_encontrado": True,
            "status": (
                "corrigido"
                if resultado.get("corrigido")
                else "preenchido"
                if resultado.get("preenchido")
                else "erro"
            ),
            "categoria": diagnostico.get("categoria", ""),
            "titulo_esperado": titulo,
            "diagnostico": diagnostico,
            "contexto_sch": contexto_sch,
        }
    )

    return resultado


def salvar_caracteristicas_tecnicas(
    driver,
    wait,
    texto_esperado="",
    titulo_secundario_esperado="",
):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.08)

    xpaths_salvar = [
        "//button[normalize-space()='Salvar']",
        "//a[normalize-space()='Salvar']",
        "//input[@type='submit' and contains(@value,'Salvar')]",
        "//input[@type='button' and contains(@value,'Salvar')]",
        "//span[normalize-space()='Salvar']/ancestor::button[1]",
        "//span[normalize-space()='Salvar']/ancestor::a[1]",
        "//*[@title='Salvar']",
        "//*[self::a or self::button][contains(normalize-space(), 'Salvar')]",
    ]

    botao_salvar = None

    for xpath in xpaths_salvar:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
            for el in elementos:
                try:
                    if el.is_displayed() and el.is_enabled():
                        botao_salvar = el
                        break
                except Exception:
                    continue

            if botao_salvar:
                break

        except Exception:
            continue

    if not botao_salvar:
        print("[SCH][WARN] Botão Salvar não encontrado em Características Técnicas.")
        return {
            "salvo": False,
            "motivo": "botao_salvar_nao_encontrado",
        }

    print("[SCH] Salvando Características Técnicas...")

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao_salvar)
    _clicar_com_fallback(driver, botao_salvar)

    esperar_tela_carregar(driver, 0.8)

    try:
        alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
        print(f"[SCH] Alerta após salvar Características Técnicas: {alert.text}")
        alert.accept()
        esperar_tela_carregar(driver, 0.5)
    except Exception:
        pass

    confirmado = False

    if texto_esperado:
        try:
            entrar_iframe_detalhe_analise(driver, wait)

            texto_esperado_norm = _normalizar_texto_comparacao(texto_esperado)

            xpaths_validacao = [
                "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
                "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
                "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
                "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
                "//*[@contenteditable='true']",
                "//div[contains(@class,'ql-editor')]",
            ]

            for xpath in xpaths_validacao:
                elementos = driver.find_elements(By.XPATH, xpath)

                for el in elementos:
                    try:
                        if not el.is_displayed():
                            continue

                        valor = driver.execute_script(
                            "return (arguments[0].value || arguments[0].innerText || arguments[0].textContent || '').trim();",
                            el,
                        )

                        if texto_esperado_norm and texto_esperado_norm in _normalizar_texto_comparacao(valor):
                            confirmado = True
                            break

                    except Exception:
                        continue

                if confirmado:
                    break

        except Exception:
            confirmado = False

    titulo_secundario_confirmado = True

    if titulo_secundario_esperado:
        titulo_secundario_confirmado = False

        try:
            entrar_iframe_detalhe_analise(driver, wait)

            campo_titulo = (
                _localizar_campo_titulo_caracteristicas_secundarias(
                    driver,
                    timeout=2.5,
                )
            )

            if campo_titulo is not None:
                valor_titulo = driver.execute_script(
                    """
                    return arguments[0].value == null
                        ? String(
                            arguments[0].innerText ||
                            arguments[0].textContent ||
                            ''
                        ).trim()
                        : String(arguments[0].value).trim();
                    """,
                    campo_titulo,
                ) or ""

                titulo_secundario_confirmado = (
                    _normalizar_texto_comparacao(valor_titulo)
                    == _normalizar_texto_comparacao(
                        titulo_secundario_esperado
                    )
                )
        except Exception:
            titulo_secundario_confirmado = False

    confirmado_geral = bool(
        confirmado
        and titulo_secundario_confirmado
    )

    if confirmado_geral:
        print(
            "[SCH] Características Técnicas salvas e conferidas "
            "com sucesso."
        )
    else:
        print(
            "[SCH][WARN] Características Técnicas salvas, mas a "
            "confirmação após salvar ficou incompleta. "
            f"Observação={confirmado} | "
            f"Título secundário={titulo_secundario_confirmado}"
        )

    return {
        "salvo": True,
        "confirmado_apos_salvar": confirmado_geral,
        "observacao_confirmada": confirmado,
        "titulo_secundario_confirmado": (
            titulo_secundario_confirmado
        ),
    }


FRASE_SAR_NAO_APLICAVEL = "Ensaio de SAR não aplicável."

def _dados_pdf_tem_ato_1630(dados_pdf):
    texto = _normalizar_texto_comparacao(_texto_total_dados_pdf(dados_pdf or {}))

    padroes = [
        r"\bato\s*(?:n|no|numero)?\s*1630\b",
    ]

    return any(re.search(padrao, texto, flags=re.I) for padrao in padroes)


def _dados_pdf_indica_produto_nao_acabado(dados_pdf):
    texto = _normalizar_texto_comparacao(_texto_total_dados_pdf(dados_pdf or {}))

    termos = [
        "produto nao acabado",
        "uso interno",
        "integracao em outros equipamentos",
        "pode requerer nova avaliacao",
        "modulo",
        "module",
        "oem",
    ]

    return any(termo in texto for termo in termos)


def _extrair_frase_sar_nao_aplicavel(dados_pdf):
    """
    Quando o CCT indicar SAR não aplicável, a frase padrão a preencher
    na Corrigir Minuta deve ser somente:
    'Ensaio de SAR não aplicável'
    """
    return FRASE_SAR_NAO_APLICAVEL


def _dados_pdf_tem_frase_sar_nao_aplicavel(dados_pdf):
    texto = _normalizar_texto_comparacao(_texto_total_dados_pdf(dados_pdf or {}))

    termos = [
        "ensaio de sar nao aplicavel",
        "sar nao aplicavel",
        "ensaio sar nao aplicavel",
        "nao se aplica sar",
        "sar nao se aplica",
    ]

    return any(t in texto for t in termos)


def _dados_pdf_tem_coluna_sar(dados_pdf):
    tabela = (dados_pdf or {}).get("tabela_tecnica_cct", {}) or {}
    cabecalho = tabela.get("cabecalho", []) or []

    texto_cabecalho = _normalizar_texto_comparacao(
        " ".join(str(c or "") for c in cabecalho)
    )

    termos_coluna_sar = [
        "sar",
        "sar cabeca",
        "sar corpo",
        "sar head",
        "sar body",
        "taxa de absorcao especifica",
    ]

    return any(termo in texto_cabecalho for termo in termos_coluna_sar)


def _cabecalho_eh_coluna_sar_para_valor(cabecalho):
    """
    Identifica coluna de SAR de forma restritiva.

    Evita confundir:
    - Taxa de Transmissão / Transmission Rate
    - Mbit/s
    - Rate
    - Bit rate

    com SAR.
    """
    texto = _normalizar_texto_comparacao(cabecalho)

    if not texto:
        return False

    termos_bloqueio = [
        "taxa de transmissao",
        "transmission rate",
        "rate mbit",
        "mbit",
        "mbit s",
        "mbps",
        "bit rate",
        "data rate",
        "taxa maxima de transmissao",
    ]

    if any(termo in texto for termo in termos_bloqueio):
        return False

    termos_sar_fortes = [
        "sar cabeca",
        "sar corpo",
        "sar head",
        "sar body",
        "taxa de absorcao especifica",
    ]

    if any(termo in texto for termo in termos_sar_fortes):
        return True

    # Aceita SAR apenas se vier com unidade W/kg.
    if "sar" in texto and ("w kg" in texto or "wkg" in texto):
        return True

    return False


def _valor_sar_preenchido(valor):
    """
    Retorna True somente para valor real de SAR.

    Não aceita:
    - "-"
    - "---"
    - "1"
    - "2"
    - valores inteiros típicos de taxa de transmissão
    """
    texto = str(valor or "").strip()

    if not texto:
        return False

    texto = texto.replace("–", "-").replace("—", "-")
    texto_norm = _normalizar_texto_comparacao(texto)

    vazios = {
        "",
        "-",
        "--",
        "---",
        "----",
        "na",
        "n a",
        "n/a",
        "nao aplicavel",
        "nao se aplica",
        "not applicable",
    }

    if texto_norm in vazios:
        return False

    if re.fullmatch(r"[-\s./]+", texto):
        return False

    termos_bloqueio = [
        "mbit",
        "mbps",
        "kbps",
        "taxa",
        "transmissao",
        "transmission",
        "rate",
    ]

    if any(termo in texto_norm for termo in termos_bloqueio):
        return False

    # SAR real normalmente vem como decimal: 0,123 / 1,23 / 0.45.
    # Não aceitar inteiro puro como "1" ou "2", pois isso costuma ser taxa de bits.
    m = re.search(r"(?<!\d)(\d+[,.]\d+)(?!\d)", texto)

    if not m:
        return False

    try:
        valor_float = float(m.group(1).replace(",", "."))
    except Exception:
        return False

    # Faixa ampla apenas para eliminar lixo absurdo.
    return 0 < valor_float <= 20


def _dados_pdf_tem_valor_sar(dados_pdf):
    """
    Retorna True somente se houver valor real de SAR nas colunas corretas de SAR.

    Coluna SAR com "-", "---" ou vazia não conta.
    Coluna de taxa de transmissão depois de SAR não conta.
    """
    tabela = (dados_pdf or {}).get("tabela_tecnica_cct", {}) or {}
    cabecalho = tabela.get("cabecalho", []) or []
    linhas = tabela.get("linhas", []) or []

    indices_sar = []

    for i, col in enumerate(cabecalho):
        if _cabecalho_eh_coluna_sar_para_valor(col):
            indices_sar.append(i)

    if not indices_sar:
        return False

    for linha in linhas:
        for idx in indices_sar:
            if idx < len(linha):
                valor = linha[idx]

                if _valor_sar_preenchido(valor):
                    return True

    return False



def _norm_sar(texto):
    texto = str(texto or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = texto.replace("µ", "u").replace("μ", "u")
    texto = re.sub(r"[^a-z0-9.,/() -]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _valor_sar_real(valor):
    texto = str(valor or "").strip()

    if not texto:
        return False

    texto_norm = _norm_sar(texto)

    if texto_norm in {
        "-",
        "--",
        "---",
        "na",
        "n/a",
        "n a",
        "nao aplicavel",
        "not applicable",
        "aplicavel",
        "sim",
        "nao",
    }:
        return False

    numeros = re.findall(r"\d+[,.]\d+", texto)

    if not numeros:
        return False

    for numero in numeros:
        try:
            numero_txt = str(numero).strip()

            # 0,174 -> 0.174 / 0.174 -> 0.174
            # 1.234,56 -> 1234.56, se algum OCD usar separador de milhar.
            if "," in numero_txt and "." in numero_txt:
                numero_txt = numero_txt.replace(".", "").replace(",", ".")
            else:
                numero_txt = numero_txt.replace(",", ".")

            valor_float = float(numero_txt)
        except Exception:
            continue

        # Valor real de SAR costuma ser pequeno.
        # Evita confundir com frequência ou taxa.
        if 0 < valor_float <= 20:
            return True

    return False


def _indice_colunas_sar(cabecalho):
    indices = []

    for idx, col in enumerate(cabecalho or []):
        col_norm = _norm_sar(col)

        if "sar" not in col_norm:
            continue

        if any(
            termo in col_norm
            for termo in [
                "cabeca",
                "head",
                "corpo",
                "body",
                "tronco",
                "limb",
                "membro",
                "w/kg",
                "w kg",
            ]
        ):
            indices.append(idx)

    return indices


def _tabela_tem_valores_sar(tabela):
    tabela = tabela or {}
    cabecalho = tabela.get("cabecalho", []) or []
    linhas = tabela.get("linhas", []) or []

    indices_sar = _indice_colunas_sar(cabecalho)

    if not indices_sar:
        return {
            "tem_sar": False,
            "valores": [],
            "motivo": "sem_coluna_sar",
        }

    valores = []

    for linha in linhas:
        for idx in indices_sar:
            if idx >= len(linha):
                continue

            valor = linha[idx]

            if _valor_sar_real(valor):
                valores.append(
                    {
                        "coluna": cabecalho[idx],
                        "valor": str(valor).strip(),
                    }
                )

    return {
        "tem_sar": bool(valores),
        "valores": valores,
        "motivo": "valores_sar_encontrados" if valores else "coluna_sar_sem_valores",
    }


def _texto_tem_valores_sar_em_contexto(texto):
    texto = texto or ""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]

    valores = []

    for i, linha in enumerate(linhas):
        linha_norm = _norm_sar(linha)

        if "sar" not in linha_norm:
            continue

        if not any(
            termo in linha_norm
            for termo in [
                "corpo",
                "body",
                "cabeca",
                "head",
                "w/kg",
                "w kg",
            ]
        ):
            continue

        janela = " ".join(linhas[i:i + 30])

        for numero in re.findall(r"\d+[,.]\d+", janela):
            try:
                valor_float = float(numero.replace(".", "").replace(",", "."))
            except Exception:
                continue

            if 0 < valor_float <= 20:
                valores.append(numero)

    return {
        "tem_sar": bool(valores),
        "valores": valores,
    }





def analisar_sar_cct(dados_pdf):
    """
    Analisa se deve preencher 'Ensaio de SAR não aplicável.' na Corrigir Minuta.

    Regra:
    1. Valor real em coluna SAR Cabeça/Corpo => SAR aplicável.
    2. Valor explícito de SAR em texto corrido => SAR aplicável.
    3. Frase segura de SAR não aplicável => preencher frase.
    4. Coluna SAR existente, mas vazia/traço/N/A => SAR não aplicável e preencher frase.
    5. Sem coluna SAR e sem frase segura => revisar manualmente.
    """
    dados_pdf = dados_pdf or {}

    texto = dados_pdf.get("texto_completo", "") or ""
    texto_norm = _norm_sar(texto)

    tabela_cct = dados_pdf.get("tabela_tecnica_cct") or {}

    resultado_tabela = _tabela_tem_valores_sar(tabela_cct)

    if resultado_tabela.get("tem_sar"):
        return {
            "status": "sar_aplicavel",
            "mensagem": (
                "SAR aplicável: foram encontrados valores numéricos reais "
                "em coluna SAR do CCT. Não preencher 'Ensaio de SAR não aplicável.'."
            ),
            "preencher_frase": False,
            "frase": "",
            "sar_aplicavel": True,
            "sar_nao_aplicavel": False,
            "valores_sar_encontrados": resultado_tabela.get("valores", []),
            "origem": "tabela_tecnica_cct",
        }

    resultado_texto = _texto_tem_valores_sar_em_contexto(texto)

    if resultado_texto.get("tem_sar"):
        return {
            "status": "sar_aplicavel",
            "mensagem": (
                "SAR aplicável: foram encontrados valores explícitos de SAR "
                "no texto do CCT. Não preencher 'Ensaio de SAR não aplicável.'."
            ),
            "preencher_frase": False,
            "frase": "",
            "sar_aplicavel": True,
            "sar_nao_aplicavel": False,
            "valores_sar_encontrados": resultado_texto.get("valores", []),
            "origem": "texto_completo_explicito",
        }

    frases_sar_nao_aplicavel = [
        "ensaio de sar nao aplicavel",
        "sar nao aplicavel",
        "sar n/a",
        "sar na",
        "not applicable sar",
        "sar not applicable",
        "equipamento nao e terminal portatil",
        "equipamento nao terminal portatil",
        "nao e terminal portatil",
        "potencia media de transmissao em 6 minutos inferior",
        "potencia de pico inferior",
    ]

    encontrou_frase_nao_aplicavel = any(
        frase in texto_norm
        for frase in frases_sar_nao_aplicavel
    )

    if encontrou_frase_nao_aplicavel:
        return {
            "status": "sar_nao_aplicavel",
            "mensagem": (
                "SAR não aplicável identificado no CCT. "
                "Não foram encontrados valores numéricos reais de SAR."
            ),
            "preencher_frase": True,
            "frase": FRASE_SAR_NAO_APLICAVEL,
            "sar_aplicavel": False,
            "sar_nao_aplicavel": True,
            "valores_sar_encontrados": [],
            "origem": "texto_completo",
        }

    if _dados_pdf_tem_coluna_sar(dados_pdf):
        return {
            "status": "sar_nao_aplicavel",
            "mensagem": (
                "O CCT possui coluna SAR, mas não foram encontrados valores reais "
                "nas colunas SAR Cabeça/Corpo. Considerado SAR não aplicável."
            ),
            "preencher_frase": True,
            "frase": FRASE_SAR_NAO_APLICAVEL,
            "sar_aplicavel": False,
            "sar_nao_aplicavel": True,
            "valores_sar_encontrados": [],
            "origem": "coluna_sar_sem_valor",
        }

    return {
        "status": "revisar",
        "mensagem": (
            "Não foram encontrados valores reais de SAR, coluna SAR ou frase segura "
            "de SAR não aplicável. Revisar manualmente."
        ),
        "preencher_frase": False,
        "frase": "",
        "sar_aplicavel": None,
        "sar_nao_aplicavel": None,
        "valores_sar_encontrados": [],
        "origem": "nao_identificado",
    }



def _ha_tela_corrigir_minuta_aberta(driver):
    """
    Confirma a tela real de Corrigir Minuta.

    O clique não abre nova aba e não muda a URL. A tela é carregada por AJAX
    dentro do mesmo iframe do requerimento. Por isso, a confirmação exige dois
    sinais exclusivos:
    - seção "Especificação";
    - botão "Salvar Minuta".
    """
    try:
        texto = _normalizar_texto_comparacao(_texto_visivel_sch(driver))
    except Exception:
        texto = ""

    tem_especificacao = bool(
        "especificacao" in texto
        and any(
            termo in texto
            for termo in [
                "fabricante",
                "solicitante",
                "produto",
            ]
        )
    )

    xpaths_salvar_minuta = [
        "//button[normalize-space(.)='Salvar Minuta']",
        "//a[normalize-space(.)='Salvar Minuta']",
        "//input[(@type='button' or @type='submit') and normalize-space(@value)='Salvar Minuta']",
        "//span[normalize-space(.)='Salvar Minuta']/ancestor::*[self::button or self::a][1]",
    ]

    tem_salvar_minuta = False

    for xpath in xpaths_salvar_minuta:
        try:
            if any(
                el.is_displayed()
                for el in driver.find_elements(By.XPATH, xpath)
            ):
                tem_salvar_minuta = True
                break
        except Exception:
            continue

    return bool(tem_especificacao and tem_salvar_minuta)



# Mantém compatibilidade com chamadas antigas.
def _ha_campo_corrigir_minuta(driver):
    return _ha_tela_corrigir_minuta_aberta(driver)


def _janela_atual_tem_requerimento_sch(driver):
    """
    Confirma se a janela atual é a tela principal do requerimento no SCH.

    Não considera about:blank nem a página independente de Comparar Versões.
    """
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    try:
        url = str(driver.current_url or "").strip().lower()
    except Exception:
        url = ""

    if not url or url.startswith("about:blank"):
        return False

    try:
        if driver.find_elements(By.XPATH, XPATH_IFRAME_DETALHE):
            return True
    except Exception:
        pass

    try:
        texto = _normalizar_texto_comparacao(
            driver.execute_script(
                "return document.body ? (document.body.innerText || '') : '';"
            )
            or ""
        )

        return (
            "corrigir minuta" in texto
            and "visualizar requerimento" in texto
            and "comparar versoes" in texto
        )
    except Exception:
        return False


def _preparar_janela_sch_para_corrigir_minuta(
    driver,
    aba_original_sch=None,
):
    """
    Posiciona o Selenium diretamente na aba original do SCH.

    Esta função não procura o requerimento alternando entre todas as abas.
    No fluxo Retorno Para Estudo, a aba original deve ser capturada antes de
    abrir Comparar Versões e informada aqui. Em "Em Análise", usa a aba atual.
    """
    try:
        handles = list(driver.window_handles)
    except Exception:
        handles = []

    if not handles:
        raise RuntimeError("Nenhuma janela do navegador está disponível.")

    if aba_original_sch and aba_original_sch in handles:
        alvo = aba_original_sch
    else:
        try:
            alvo = driver.current_window_handle
        except Exception:
            alvo = handles[0]

        if alvo not in handles:
            alvo = handles[0]

    try:
        driver.switch_to.window(alvo)
        driver.switch_to.default_content()
    except Exception as e:
        raise RuntimeError(
            f"Não foi possível acessar a aba original do SCH: {e}"
        )

    entrar_iframe_detalhe_analise(driver, None)
    return alvo



def _entrar_contexto_corrigir_minuta_aberta(driver, profundidade_max=4):
    """
    Procura a tela Corrigir Minuta somente na janela SCH já selecionada.

    Ao retornar True, o driver fica no frame que contém a tela. A função não
    percorre outras abas, impedindo a alternância visual entre SCH e comparação.
    """
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    def procurar(profundidade=0):
        try:
            if _ha_tela_corrigir_minuta_aberta(driver):
                return True
        except Exception:
            pass

        if profundidade >= profundidade_max:
            return False

        try:
            quantidade = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
        except Exception:
            quantidade = 0

        for indice in range(quantidade):
            try:
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
                if indice >= len(frames):
                    continue

                driver.switch_to.frame(frames[indice])

                if procurar(profundidade + 1):
                    return True

                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass

        return False

    encontrado = procurar(0)

    if not encontrado:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    return encontrado


def _elemento_eh_corrigir_minuta(driver, elemento):
    try:
        texto = " ".join(
            [
                elemento.text or "",
                elemento.get_attribute("value") or "",
                elemento.get_attribute("title") or "",
                elemento.get_attribute("aria-label") or "",
            ]
        )
        return _normalizar_texto_comparacao(texto) == "corrigir minuta"
    except Exception:
        return False


def _localizar_botao_corrigir_minuta_no_contexto(driver):
    """
    Localiza somente o controle exato "Corrigir Minuta".

    Não procura divs/containers genéricos, pois um container da página inteira
    também contém esse texto e fazia o terminal imprimir todo o conteúdo da tela.
    """
    xpaths = [
        "//button[normalize-space(.)='Corrigir Minuta']",
        "//a[normalize-space(.)='Corrigir Minuta']",
        "//input[(@type='button' or @type='submit') and normalize-space(@value)='Corrigir Minuta']",
        "//span[normalize-space(.)='Corrigir Minuta']/ancestor::*[self::button or self::a][1]",
        "//*[@role='button' and normalize-space(.)='Corrigir Minuta']",
        "//*[self::button or self::a][.//*[normalize-space(.)='Corrigir Minuta']]",
    ]

    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue

        for elemento in elementos:
            try:
                if not elemento.is_displayed() or not elemento.is_enabled():
                    continue

                if _elemento_eh_corrigir_minuta(driver, elemento):
                    return elemento
            except Exception:
                continue

    return None


def _entrar_contexto_com_botao_corrigir_minuta(driver, profundidade_max=4):
    """
    Procura o botão exato somente na janela atual do SCH e em seus frames.
    """
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    def procurar(profundidade=0):
        botao = _localizar_botao_corrigir_minuta_no_contexto(driver)
        if botao is not None:
            return botao

        if profundidade >= profundidade_max:
            return None

        try:
            quantidade = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
        except Exception:
            quantidade = 0

        for indice in range(quantidade):
            try:
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
                if indice >= len(frames):
                    continue

                driver.switch_to.frame(frames[indice])
                botao = procurar(profundidade + 1)

                if botao is not None:
                    return botao

                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass

        return None

    botao = procurar(0)

    if botao is None:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    return botao


def _acionar_elemento_corrigir_minuta(driver, elemento):
    """Executa clique nativo e fallbacks de mouse/JavaScript."""
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        elemento,
    )

    erros = []

    try:
        elemento.click()
        return True
    except Exception as e:
        erros.append(e)

    try:
        ActionChains(driver).move_to_element(elemento).pause(0.15).click().perform()
        return True
    except Exception as e:
        erros.append(e)

    try:
        driver.execute_script("arguments[0].click();", elemento)
        return True
    except Exception as e:
        erros.append(e)

    try:
        driver.execute_script(
            """
            const el = arguments[0];
            ['mouseover', 'mousedown', 'mouseup', 'click'].forEach(function(nome) {
                el.dispatchEvent(new MouseEvent(nome, {
                    bubbles: true,
                    cancelable: true,
                    view: window
                }));
            });
            """,
            elemento,
        )
        return True
    except Exception as e:
        erros.append(e)

    raise RuntimeError(
        "Falha em todas as formas de clique em Corrigir Minuta: "
        + " | ".join(str(e) for e in erros)
    )


def clicar_corrigir_minuta(
    driver,
    wait,
    aba_original_sch=None,
):
    """
    Abre Corrigir Minuta na mesma aba e no mesmo iframe do requerimento.

    Não procura nova janela, não espera mudança de URL e não percorre abas.
    Depois do clique, aguarda o conteúdo AJAX exclusivo da minuta.
    """
    print("[SCH][MINUTA] Preparando a aba original do requerimento...")

    aba_original_sch = _preparar_janela_sch_para_corrigir_minuta(
        driver,
        aba_original_sch=aba_original_sch,
    )

    if _ha_tela_corrigir_minuta_aberta(driver):
        print("[SCH][MINUTA] Corrigir Minuta já está aberta.")
        return True

    xpaths = [
        "//button[normalize-space(.)='Corrigir Minuta']",
        "//a[normalize-space(.)='Corrigir Minuta']",
        "//input[(@type='button' or @type='submit') and normalize-space(@value)='Corrigir Minuta']",
        "//span[normalize-space(.)='Corrigir Minuta']/ancestor::*[self::button or self::a][1]",
    ]

    ultimo_erro = None

    for tentativa in range(1, 4):
        try:
            _preparar_janela_sch_para_corrigir_minuta(
                driver,
                aba_original_sch=aba_original_sch,
            )

            botao = None

            for xpath in xpaths:
                try:
                    elementos = WebDriverWait(
                        driver,
                        3,
                        poll_frequency=0.1,
                    ).until(
                        EC.presence_of_all_elements_located(
                            (By.XPATH, xpath)
                        )
                    )
                except Exception:
                    elementos = []

                for elemento in elementos:
                    try:
                        if elemento.is_displayed() and elemento.is_enabled():
                            botao = elemento
                            break
                    except Exception:
                        continue

                if botao is not None:
                    break

            if botao is None:
                raise RuntimeError(
                    "Botão exato 'Corrigir Minuta' não encontrado no "
                    "iframe do requerimento."
                )

            print("[SCH][MINUTA] Botão localizado: Corrigir Minuta")
            _acionar_elemento_corrigir_minuta(driver, botao)

            def _minuta_carregou(d):
                try:
                    _preparar_janela_sch_para_corrigir_minuta(
                        d,
                        aba_original_sch=aba_original_sch,
                    )
                    return _ha_tela_corrigir_minuta_aberta(d)
                except Exception:
                    return False

            WebDriverWait(
                driver,
                20,
                poll_frequency=0.2,
            ).until(_minuta_carregou)

            print(
                "[SCH][MINUTA] Corrigir Minuta carregada por AJAX "
                "na mesma aba do SCH."
            )
            return True

        except Exception as e:
            ultimo_erro = e
            print(
                "[SCH][MINUTA][WARN] Corrigir Minuta não abriu. "
                f"Tentativa {tentativa}/3: {e}"
            )
            esperar_tela_carregar(
                driver,
                0.8,
                timeout=5,
            )

    raise RuntimeError(
        "Não foi possível abrir Corrigir Minuta. "
        f"Último erro: {ultimo_erro}"
    )


def _inserir_texto_sem_apagar(driver, wait, texto, descricao, xpaths_input, xpaths_editor=None):
    if not texto:
        print(f"[SCH][WARN] Texto vazio para {descricao}.")
        return False

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.08)

    texto_norm = _normalizar_texto_comparacao(texto)

    for xpath in xpaths_input:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for campo in elementos:
                try:
                    if not campo.is_displayed() or not campo.is_enabled():
                        continue

                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo)

                    valor_atual = driver.execute_script(
                        "return (arguments[0].value || arguments[0].innerText || arguments[0].textContent || '').trim();",
                        campo,
                    ) or ""

                    if texto_norm in _normalizar_texto_comparacao(valor_atual):
                        print(f"[SCH] Texto já existente em {descricao}.")
                        return True

                    novo_texto = f"{valor_atual}\n{texto}".strip() if valor_atual else texto
                    tag = (campo.tag_name or "").lower()

                    if tag in {"textarea", "input"}:
                        driver.execute_script("arguments[0].value = arguments[1];", campo, novo_texto)
                    else:
                        novo_html = novo_texto.replace("\n", "<br>")
                        driver.execute_script("arguments[0].innerHTML = arguments[1];", campo, novo_html)

                    driver.execute_script(
                        """
                        arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                        """,
                        campo,
                    )

                    try:
                        campo.send_keys(Keys.TAB)
                    except Exception:
                        pass

                    esperar_tela_carregar(driver, 0.08)
                    print(f"[SCH] Texto inserido em {descricao}.")
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    xpaths_editor = xpaths_editor or [
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//div[contains(@class,'ui-editor')]//*[@contenteditable='true']",
    ]

    for xpath in xpaths_editor:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for editor in elementos:
                try:
                    if not editor.is_displayed():
                        continue

                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)

                    valor_atual = driver.execute_script(
                        "return (arguments[0].innerText || arguments[0].textContent || '').trim();",
                        editor,
                    ) or ""

                    if texto_norm in _normalizar_texto_comparacao(valor_atual):
                        print(f"[SCH] Texto já existente em {descricao}.")
                        return True

                    novo_texto = f"{valor_atual}\n{texto}".strip() if valor_atual else texto
                    novo_html = novo_texto.replace("\n", "<br>")

                    _preencher_html_em_elemento(driver, editor, novo_html)
                    esperar_tela_carregar(driver, 0.08)

                    print(f"[SCH] Texto inserido em {descricao}.")
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    raise Exception(f"Não foi possível localizar o campo para inserir texto: {descricao}")


def _substituir_texto_campo(driver, wait, texto, descricao, xpaths_input, xpaths_editor=None):
    """
    Substitui completamente o conteúdo do campo pelo texto informado.

    Use esta função quando o SCH já deixa uma frase automática no campo
    e a automação precisa trocar pelo texto correto.
    """
    if not texto:
        print(f"[SCH][WARN] Texto vazio para {descricao}.")
        return False

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.08)

    texto_plano = str(texto).strip()
    html = texto_plano.replace("\n", "<br>")

    for xpath in xpaths_input:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for campo in elementos:
                try:
                    if not campo.is_displayed() or not campo.is_enabled():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        campo,
                    )

                    _clicar_com_fallback(driver, campo)

                    tag = (campo.tag_name or "").lower()

                    if tag in {"textarea", "input"}:
                        try:
                            campo.send_keys(Keys.CONTROL, "a")
                            campo.send_keys(Keys.DELETE)
                            campo.send_keys(texto_plano)
                        except Exception:
                            driver.execute_script(
                                "arguments[0].value = arguments[1];",
                                campo,
                                texto_plano,
                            )
                    else:
                        driver.execute_script(
                            "arguments[0].innerHTML = arguments[1];",
                            campo,
                            html,
                        )

                    driver.execute_script(
                        """
                        arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                        arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                        """,
                        campo,
                    )

                    try:
                        campo.send_keys(Keys.TAB)
                    except Exception:
                        pass

                    esperar_tela_carregar(driver, 0.08)
                    print(f"[SCH] Texto substituído em {descricao}.")
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    xpaths_editor = xpaths_editor or [
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//div[contains(@class,'ui-editor')]//*[@contenteditable='true']",
    ]

    for xpath in xpaths_editor:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for editor in elementos:
                try:
                    if not editor.is_displayed():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        editor,
                    )

                    _preencher_html_em_elemento(driver, editor, html)
                    esperar_tela_carregar(driver, 0.08)

                    print(f"[SCH] Texto substituído em {descricao}.")
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    raise Exception(f"Não foi possível localizar o campo para substituir texto: {descricao}")



def _mensagens_erro_corrigir_minuta(driver):
    """
    Coleta mensagens visíveis que indiquem bloqueio/erro no salvamento.
    """
    mensagens = []

    xpaths = [
        "//*[contains(@class,'ui-messages-error')]",
        "//*[contains(@class,'ui-message-error')]",
        "//*[contains(@class,'alert-danger')]",
        "//*[contains(@class,'validation-error')]",
        "//*[contains(@class,'error') and not(self::script) and not(self::style)]",
    ]

    for xpath in xpaths:
        try:
            for el in driver.find_elements(By.XPATH, xpath):
                try:
                    if not el.is_displayed():
                        continue
                    texto = _texto_limpo(el.text)
                    if texto:
                        mensagens.append(texto)
                except Exception:
                    continue
        except Exception:
            continue

    mensagens = _deduplicar_lista_preservando_ordem(mensagens)

    termos_erro = [
        "erro",
        "obrigatorio",
        "obrigatoria",
        "invalido",
        "invalida",
        "nao foi possivel",
        "não foi possível",
        "deve ser informado",
        "data",
        "falha",
    ]

    saida = []
    for msg in mensagens:
        msg_norm = _normalizar_texto_comparacao(msg)
        if any(_normalizar_texto_comparacao(t) in msg_norm for t in termos_erro):
            saida.append(msg)

    return saida


def _localizar_botao_salvar_minuta(driver):
    """
    Localiza especificamente "Salvar Minuta".

    Existem outros botões Salvar no SCH; por isso o seletor genérico não é
    usado. Quando há botão no topo e no fim da página, prefere o mais abaixo.
    """
    xpaths = [
        "//button[normalize-space(.)='Salvar Minuta']",
        "//a[normalize-space(.)='Salvar Minuta']",
        "//input[(@type='submit' or @type='button') and normalize-space(@value)='Salvar Minuta']",
        "//span[normalize-space(.)='Salvar Minuta']/ancestor::*[self::button or self::a][1]",
        "//*[@title='Salvar Minuta' and (self::button or self::a or self::input)]",
        "//*[self::button or self::a or self::input]"
        "[normalize-space(.)='Salvar' or normalize-space(@value)='Salvar']"
        "[contains(translate(concat(@id,' ',@name,' ',@title,' ',@class),"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'minuta')]",
    ]

    candidatos = []
    vistos = set()

    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception:
            elementos = []

        for elemento in elementos:
            try:
                if not elemento.is_displayed() or not elemento.is_enabled():
                    continue

                chave = elemento.id
                if chave in vistos:
                    continue
                vistos.add(chave)

                posicao = driver.execute_script(
                    """
                    const r = arguments[0].getBoundingClientRect();
                    return r.top + window.scrollY;
                    """,
                    elemento,
                )

                candidatos.append((float(posicao or 0), elemento))
            except Exception:
                continue

    if not candidatos:
        return None

    candidatos.sort(key=lambda item: item[0], reverse=True)
    return candidatos[0][1]



def _confirmar_dialogo_salvar_minuta(driver, wait, timeout=5):
    """
    Confirma o aviso exibido pelo SCH depois de clicar em Salvar Minuta.

    Suporta alert nativo e modal HTML/PrimeFaces. A ausência de confirmação
    não é tratada como erro, pois alguns requerimentos salvam diretamente.
    """
    try:
        alerta = WebDriverWait(
            driver,
            min(float(timeout), 2.5),
        ).until(EC.alert_is_present())

        texto = _texto_limpo(alerta.text)
        alerta.accept()
        esperar_tela_carregar(driver, 0.6, timeout=5)

        return {
            "confirmado": True,
            "tipo": "alert",
            "mensagem": texto,
        }
    except Exception:
        pass

    inicio = time.time()
    ultimo_erro = None

    xpaths = [
        "//*[@role='dialog' or contains(@class,'ui-dialog') or contains(@class,'modal')]"
        "//*[self::button or self::a]"
        "[normalize-space(.)='Sim' or normalize-space(.)='Confirmar' "
        "or normalize-space(.)='OK' or normalize-space(.)='Salvar']",
        "//*[@role='dialog' or contains(@class,'ui-dialog') or contains(@class,'modal')]"
        "//span[normalize-space(.)='Sim' or normalize-space(.)='Confirmar' "
        "or normalize-space(.)='OK' or normalize-space(.)='Salvar']"
        "/ancestor::*[self::button or self::a][1]",
    ]

    while time.time() - inicio < timeout:
        try:
            entrar_iframe_detalhe_analise(driver, wait)
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        for xpath in xpaths:
            try:
                elementos = driver.find_elements(By.XPATH, xpath)
            except Exception as e:
                ultimo_erro = e
                elementos = []

            for botao in elementos:
                try:
                    if not botao.is_displayed() or not botao.is_enabled():
                        continue

                    texto = _texto_limpo(
                        botao.text
                        or botao.get_attribute("value")
                        or botao.get_attribute("title")
                    )

                    _clicar_com_fallback(driver, botao)
                    esperar_tela_carregar(driver, 0.7, timeout=5)

                    return {
                        "confirmado": True,
                        "tipo": "modal_html",
                        "botao": texto,
                    }
                except Exception as e:
                    ultimo_erro = e
                    continue

        time.sleep(0.15)

    return {
        "confirmado": False,
        "tipo": "nenhuma_confirmacao_exibida",
        "erro": str(ultimo_erro or ""),
    }


def salvar_minuta_corrigida(
    driver,
    wait,
    texto_esperado=None,
    confirmar_vazio=False,
):
    """
    Clica em "Salvar Minuta", confirma eventual aviso e valida o campo.

    - texto_esperado: confirma que o campo contém o texto.
    - confirmar_vazio=True: confirma que Especificações Complementares ficou vazio.
    """
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.2, timeout=5)

    botao_salvar = _localizar_botao_salvar_minuta(driver)

    if botao_salvar is None:
        print(
            "[SCH][MINUTA][WARN] Botão 'Salvar Minuta' não encontrado."
        )
        return {
            "salvo": False,
            "confirmado_apos_salvar": False,
            "motivo": "botao_salvar_minuta_nao_encontrado",
            "mensagens_erro": [],
        }

    print("[SCH][MINUTA] Clicando em Salvar Minuta...")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        botao_salvar,
    )
    _clicar_com_fallback(driver, botao_salvar)

    confirmacao = _confirmar_dialogo_salvar_minuta(
        driver,
        wait,
        timeout=5,
    )

    esperar_tela_carregar(driver, 1.0, timeout=8)

    try:
        entrar_iframe_detalhe_analise(driver, wait)
        mensagens_erro = _mensagens_erro_corrigir_minuta(driver)
    except Exception:
        mensagens_erro = []

    mensagens_bloqueio = []

    for mensagem in _deduplicar_lista_preservando_ordem(mensagens_erro):
        msg_norm = _normalizar_texto_comparacao(mensagem)

        if any(
            termo in msg_norm
            for termo in [
                "salvo com sucesso",
                "salva com sucesso",
                "gravado com sucesso",
                "operacao realizada com sucesso",
            ]
        ):
            continue

        mensagens_bloqueio.append(mensagem)

    confirmado = False
    valor_apos_salvar = None

    if confirmar_vazio or texto_esperado is not None:
        try:
            if not abrir_secao_especificacao_minuta(driver, wait):
                raise RuntimeError(
                    "A seção Especificação não reabriu após salvar."
                )

            entrar_iframe_detalhe_analise(driver, wait)

            campo = _localizar_campo_especificacoes_complementares_minuta(
                driver,
                timeout=5,
            )

            if campo is None:
                raise RuntimeError(
                    "Campo Especificações Complementares não encontrado "
                    "para confirmação após salvar."
                )

            valor_apos_salvar = _ler_valor_campo_minuta(driver, campo)

            if confirmar_vazio:
                confirmado = not bool(
                    _normalizar_texto_comparacao(valor_apos_salvar)
                )
            else:
                esperado_norm = _normalizar_texto_comparacao(
                    texto_esperado
                )
                valor_norm = _normalizar_texto_comparacao(
                    valor_apos_salvar
                )
                confirmado = bool(
                    esperado_norm
                    and esperado_norm in valor_norm
                )

        except Exception as e:
            confirmado = False
            mensagens_bloqueio.append(
                f"Falha ao confirmar o conteúdo após salvar: {e}"
            )
    else:
        confirmado = not bool(mensagens_bloqueio)

    salvo = bool(
        not mensagens_bloqueio
        and (
            confirmado
            if (confirmar_vazio or texto_esperado is not None)
            else True
        )
    )

    if salvo:
        print(
            "[SCH][MINUTA] Minuta salva e conteúdo confirmado."
        )
    else:
        print(
            "[SCH][MINUTA][WARN] O salvamento da minuta não foi "
            f"confirmado. Mensagens: {mensagens_bloqueio or 'nenhuma'}"
        )

    return {
        "salvo": salvo,
        "confirmado_apos_salvar": confirmado,
        "valor_apos_salvar": valor_apos_salvar,
        "confirmacao_dialogo": confirmacao,
        "mensagens_erro": mensagens_bloqueio,
        "motivo": (
            "salvo_e_confirmado"
            if salvo
            else "erro_ou_confirmacao_falhou"
        ),
    }



def voltar_da_tela_corrigir_minuta(driver, wait):
    """
    Clica em Voltar e confirma o retorno à tela principal do requerimento.
    """
    print("[SCH][MINUTA] Voltando para o requerimento...")

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.2, timeout=5)

    xpaths_voltar = [
        "//button[normalize-space(.)='Voltar']",
        "//a[normalize-space(.)='Voltar']",
        "//input[@type='button' and normalize-space(@value)='Voltar']",
        "//span[normalize-space(.)='Voltar']/ancestor::*[self::button or self::a][1]",
    ]

    ultimo_erro = None

    for xpath in xpaths_voltar:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception as e:
            ultimo_erro = e
            elementos = []

        for botao in elementos:
            try:
                if not botao.is_displayed() or not botao.is_enabled():
                    continue

                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    botao,
                )
                _clicar_com_fallback(driver, botao)

                def _requerimento_pronto(d):
                    try:
                        entrar_iframe_detalhe_analise(d, wait)
                    except Exception:
                        return False

                    xpaths_corrigir = [
                        "//button[normalize-space(.)='Corrigir Minuta']",
                        "//a[normalize-space(.)='Corrigir Minuta']",
                        "//input[normalize-space(@value)='Corrigir Minuta']",
                        "//span[normalize-space(.)='Corrigir Minuta']/ancestor::*[self::button or self::a][1]",
                    ]

                    for xp in xpaths_corrigir:
                        try:
                            if any(
                                el.is_displayed()
                                for el in d.find_elements(By.XPATH, xp)
                            ):
                                return True
                        except Exception:
                            continue

                    return False

                WebDriverWait(
                    driver,
                    15,
                    poll_frequency=0.2,
                ).until(_requerimento_pronto)

                print(
                    "[SCH][MINUTA] Retorno ao requerimento confirmado."
                )
                return True

            except Exception as e:
                ultimo_erro = e
                continue

    print(
        "[SCH][MINUTA][WARN] Não foi possível voltar da minuta. "
        f"Último erro: {ultimo_erro}"
    )
    return False





def _valor_campo_minuta(driver, campo):
    """Compatibilidade: lê somente o valor real do campo."""
    return _ler_valor_campo_minuta(driver, campo)

def _ler_valor_campo_minuta(driver, campo):
    """
    Lê o valor atual real do campo.

    Para textarea e input, utiliza somente a propriedade value.
    Não usa textContent como fallback, pois o textContent de um textarea
    pode manter o valor original mesmo depois de o campo ser apagado.
    """
    try:
        tag = str(campo.tag_name or "").lower()
    except Exception:
        tag = ""

    try:
        if tag in {"textarea", "input"}:
            valor = driver.execute_script(
                """
                return arguments[0].value == null
                    ? ''
                    : String(arguments[0].value);
                """,
                campo,
            )
        else:
            valor = driver.execute_script(
                """
                return String(
                    arguments[0].innerText ||
                    arguments[0].textContent ||
                    ''
                );
                """,
                campo,
            )

        return str(valor or "").strip()

    except Exception:
        try:
            if tag in {"textarea", "input"}:
                return str(campo.get_attribute("value") or "").strip()

            return str(campo.text or "").strip()

        except Exception:
            return ""




def _localizar_campo_especificacoes_complementares_minuta(driver, timeout=0):
    """
    Localiza especificamente o textarea do bloco
    "Especificações Complementares".

    O parâmetro timeout é aceito porque as chamadas do fluxo já o utilizam.
    A busca é repetida durante esse período para aguardar a renderização AJAX.
    """
    try:
        timeout = max(0.0, float(timeout or 0))
    except Exception:
        timeout = 0.0

    limite = time.time() + timeout
    primeira_passagem = True

    xpaths = [
        "//*[normalize-space(.)='Especificações Complementares:' or normalize-space(.)='Especificacoes Complementares:']/following::textarea[not(@disabled)][1]",
        "//label[contains(normalize-space(.), 'Especificações Complementares') or contains(normalize-space(.), 'Especificacoes Complementares')]/following::textarea[not(@disabled)][1]",
        "//*[normalize-space(.)='Especificações Complementares' or normalize-space(.)='Especificacoes Complementares']/ancestor::*[self::div or self::fieldset or self::td][1]//textarea[not(@disabled)][1]",
        "//textarea[not(@disabled) and contains(translate(concat(@id,' ',@name),'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ','abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç'),'especific') and contains(translate(concat(@id,' ',@name),'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ','abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç'),'complement')]",
        "//*[contains(normalize-space(.), 'Especificações Complementares') or contains(normalize-space(.), 'Especificacoes Complementares')]/following::textarea[not(@disabled)][1]",
    ]

    while primeira_passagem or time.time() <= limite:
        primeira_passagem = False

        for xpath in xpaths:
            try:
                elementos = driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue

            for campo in elementos:
                try:
                    if str(campo.tag_name or '').lower() != 'textarea':
                        continue
                    if not campo.is_displayed() or not campo.is_enabled():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                        campo,
                    )
                    print(
                        "[SCH][MINUTA] Campo Especificações Complementares "
                        f"localizado. id={campo.get_attribute('id') or '-'} | "
                        f"name={campo.get_attribute('name') or '-'}"
                    )
                    return campo
                except Exception:
                    continue

        try:
            campo_js = driver.execute_script(
                """
                function visivel(el) {
                    if (!el) return false;
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.display !== 'none' && st.visibility !== 'hidden' &&
                           Number(st.opacity || 1) !== 0 && r.width > 0 &&
                           r.height > 0 && !el.disabled;
                }

                const norm = s => String(s || '')
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .trim()
                    .toLowerCase();

                const textos = Array.from(
                    document.querySelectorAll('label, span, td, div, legend')
                ).filter(el => norm(el.innerText || el.textContent)
                    .includes('especificacoes complementares'));

                for (const rotulo of textos) {
                    const raiz = rotulo.closest('tr, td, fieldset, .ui-panel, div') || rotulo.parentElement;
                    if (raiz) {
                        const interno = Array.from(
                            raiz.querySelectorAll('textarea:not([disabled])')
                        ).find(visivel);
                        if (interno) return interno;
                    }

                    let atual = rotulo;
                    for (let i = 0; i < 12 && atual; i++, atual = atual.nextElementSibling) {
                        if (atual.matches && atual.matches('textarea:not([disabled])') && visivel(atual)) {
                            return atual;
                        }
                        const filho = atual.querySelector
                            ? Array.from(atual.querySelectorAll('textarea:not([disabled])')).find(visivel)
                            : null;
                        if (filho) return filho;
                    }
                }
                return null;
                """
            )
            if campo_js is not None:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    campo_js,
                )
                print(
                    "[SCH][MINUTA] Campo Especificações Complementares "
                    f"localizado por fallback DOM. id={campo_js.get_attribute('id') or '-'} | "
                    f"name={campo_js.get_attribute('name') or '-'}"
                )
                return campo_js
        except Exception:
            pass

        if time.time() <= limite:
            time.sleep(0.12)

    return None


def abrir_secao_especificacao_minuta(driver, wait):
    """
    Abre exclusivamente o controle de expansão da linha "Especificação".

    O rótulo não é clicado como container genérico. A função procura o botão,
    link ou ícone de expansão pertencente à mesma linha/painel e aguarda o
    campo "Especificações Complementares".
    """
    ultimo_erro = None

    def _campo_pronto(d):
        try:
            entrar_iframe_detalhe_analise(d, wait)
            return (
                _localizar_campo_especificacoes_complementares_minuta(
                    d,
                    timeout=0.35,
                )
                is not None
            )
        except Exception:
            return False

    for tentativa in range(1, 4):
        entrar_iframe_detalhe_analise(driver, wait)
        esperar_tela_carregar(driver, 0.15, timeout=5)

        campo = _localizar_campo_especificacoes_complementares_minuta(
            driver,
            timeout=0.6,
        )

        if campo is not None:
            return True

        entrar_iframe_detalhe_analise(driver, wait)

        rotulo = (
            "//*[normalize-space(.)='Especificação' "
            "or normalize-space(.)='Especificacao']"
        )

        xpaths_controle = [
            rotulo
            + "/ancestor::tr[1]"
            + "//*[self::button or self::a or @role='button' "
            + "or (self::input and (@type='button' or @type='submit'))][last()]",
            rotulo
            + "/ancestor::*[contains(@class,'ui-panel') "
            + "or contains(@class,'panel') "
            + "or contains(@class,'accordion')][1]"
            + "//*[self::button or self::a or @role='button' "
            + "or contains(@class,'ui-icon-plus') "
            + "or contains(@class,'fa-plus') "
            + "or contains(@class,'toggler')][1]",
            rotulo
            + "/ancestor::*[self::div or self::li][1]"
            + "//*[self::button or self::a or @role='button' "
            + "or contains(@class,'ui-icon-plus') "
            + "or contains(@class,'fa-plus') "
            + "or contains(@class,'toggler')][1]",
            rotulo
            + "/following::*[self::button or self::a or @role='button' "
            + "or contains(@class,'ui-icon-plus') "
            + "or contains(@class,'fa-plus')][1]",
            "//*[self::button or self::a or @role='button']"
            "[normalize-space(.)='Especificação' "
            "or normalize-space(.)='Especificacao']",
        ]

        candidatos = []
        vistos = set()

        for xpath in xpaths_controle:
            try:
                for elemento in driver.find_elements(By.XPATH, xpath):
                    try:
                        chave = elemento.id
                    except Exception:
                        chave = None

                    if chave and chave in vistos:
                        continue

                    if chave:
                        vistos.add(chave)

                    candidatos.append(elemento)
            except Exception as e:
                ultimo_erro = e

        # Fallback DOM: procura o controle visível dentro do menor bloco que
        # contém o rótulo exato "Especificação".
        if not candidatos:
            try:
                candidato_js = driver.execute_script(
                    """
                    const labels = Array.from(
                        document.querySelectorAll('span, label, td, th, div, a, button')
                    ).filter(el => {
                        const t = String(el.innerText || el.textContent || '').trim();
                        return t === 'Especificação' || t === 'Especificacao';
                    });

                    function visible(el) {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.display !== 'none'
                            && st.visibility !== 'hidden'
                            && Number(st.opacity || 1) !== 0
                            && r.width > 0
                            && r.height > 0;
                    }

                    for (const label of labels) {
                        const root = label.closest(
                            'tr, .ui-panel, .panel, .ui-accordion-header, li, fieldset'
                        ) || label.parentElement;

                        if (!root) continue;

                        const controls = Array.from(
                            root.querySelectorAll(
                                'button, a, [role="button"], input[type="button"], '
                                + 'input[type="submit"], .ui-icon-plus, .fa-plus, .toggler'
                            )
                        ).filter(visible);

                        if (controls.length) {
                            return controls[controls.length - 1];
                        }
                    }

                    return null;
                    """
                )

                if candidato_js is not None:
                    candidatos.append(candidato_js)
            except Exception as e:
                ultimo_erro = e

        for candidato in candidatos:
            try:
                if not candidato.is_displayed() or not candidato.is_enabled():
                    continue

                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    candidato,
                )
                _clicar_com_fallback(driver, candidato)

                WebDriverWait(
                    driver,
                    12,
                    poll_frequency=0.2,
                ).until(_campo_pronto)

                print(
                    "[SCH][MINUTA] Seção 'Especificação' aberta "
                    "pelo controle de expansão."
                )
                return True

            except Exception as e:
                ultimo_erro = e
                try:
                    entrar_iframe_detalhe_analise(driver, wait)
                except Exception:
                    pass
                continue

        print(
            "[SCH][MINUTA][WARN] A seção Especificação ainda não abriu. "
            f"Tentativa {tentativa}/3."
        )
        esperar_tela_carregar(driver, 0.7, timeout=5)

    print(
        "[SCH][MINUTA][WARN] Não foi possível abrir a seção "
        f"'Especificação'. Último erro: {ultimo_erro}"
    )
    return False



TIPOS_PRODUTO_LIMPAR_ESPECIFICACOES_COMPLEMENTARES = [
    "Transceptor de Radiação Restrita",
    "Estação Terminal de Acesso",
    "Dispositivo de Operação Periódica",
    "Sistemas de Identificação por Radiofrequências",
    "Sistema de Identificação por Radiofrequências",
    "Equipamento de Radiocomunicação de Radiação Restrita",
]


# Tipos que NÃO devem ser analisados automaticamente na fila
# Retorno Para Estudo. O filtro deve ocorrer ainda na lista da fila,
# antes de abrir o requerimento ou executar qualquer etapa da análise.
TIPOS_PRODUTO_NAO_AVALIADOS_AUTOMATICAMENTE_RETORNO = [
    "Telefone Móvel Celular",
]


def listar_tipos_produto_tratamento_minuta_retorno():
    """Retorna os tipos que exigem tratamento da minuta no Retorno."""
    return list(TIPOS_PRODUTO_LIMPAR_ESPECIFICACOES_COMPLEMENTARES)


def listar_tipos_produto_nao_avaliados_retorno():
    """Retorna a lista oficial configurada como fora da avaliação automática."""
    return list(TIPOS_PRODUTO_NAO_AVALIADOS_AUTOMATICAMENTE_RETORNO)


def tipo_produto_nao_avaliado_automaticamente_retorno(tipo_produto):
    tipo_norm = _normalizar_tipo_produto_minuta(tipo_produto)

    if not tipo_norm:
        return False

    for tipo_bloqueado in TIPOS_PRODUTO_NAO_AVALIADOS_AUTOMATICAMENTE_RETORNO:
        bloqueado_norm = _normalizar_tipo_produto_minuta(tipo_bloqueado)

        if tipo_norm == bloqueado_norm:
            return True

        if len(bloqueado_norm) >= 12 and bloqueado_norm in tipo_norm:
            return True

        if len(tipo_norm) >= 12 and tipo_norm in bloqueado_norm:
            return True

    return False


def _normalizar_tipo_produto_minuta(valor):
    texto = _normalizar_texto_comparacao(valor)
    texto = texto.replace("radio frequencias", "radiofrequencias")
    texto = texto.replace("radio frequencia", "radiofrequencia")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _tipo_produto_deve_limpar_especificacoes_complementares(tipo_produto):
    """
    Aceita o nome exato e pequenas variações do texto retornado pelo SCH.
    """
    tipo_norm = _normalizar_tipo_produto_minuta(tipo_produto)

    if not tipo_norm:
        return False

    for tipo_permitido in TIPOS_PRODUTO_LIMPAR_ESPECIFICACOES_COMPLEMENTARES:
        permitido_norm = _normalizar_tipo_produto_minuta(tipo_permitido)

        if tipo_norm == permitido_norm:
            return True

        # O SCH pode acrescentar observações/categoria ao nome do produto.
        if len(permitido_norm) >= 12 and permitido_norm in tipo_norm:
            return True

        if len(tipo_norm) >= 12 and tipo_norm in permitido_norm:
            return True

    return False


def tipo_produto_deve_limpar_especificacoes_complementares(tipo_produto):
    """
    Interface pública para consultar a regra de limpeza da Corrigir Minuta.

    Pode ser usada pelo fluxo antes do processamento para manter no escopo
    todos os tipos de produto que exigem a limpeza automática.
    """
    return _tipo_produto_deve_limpar_especificacoes_complementares(tipo_produto)


def _limpar_elemento_especificacoes_complementares(driver, campo):
    """
    Apaga o textarea e confirma pela propriedade real ``value``.

    Primeiro simula a ação manual. Se o navegador não entregar as teclas ao
    textarea, usa o setter nativo do HTMLTextAreaElement e dispara os eventos
    que o SCH/PrimeFaces utiliza para reconhecer a alteração.
    """
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        campo,
    )

    valor_antes = _ler_valor_campo_minuta(driver, campo)
    print(
        "[SCH][MINUTA] Limpando Especificações Complementares. "
        f"Quantidade anterior: {len(valor_antes)} caractere(s)."
    )

    try:
        driver.execute_script("arguments[0].focus();", campo)
        campo.click()
        campo.send_keys(Keys.CONTROL, "a")
        time.sleep(0.15)
        campo.send_keys(Keys.DELETE)
        campo.send_keys(Keys.BACKSPACE)
        time.sleep(0.25)
    except Exception as e:
        print(
            "[SCH][MINUTA][WARN] Falha na limpeza pelo teclado: "
            f"{type(e).__name__}: {e}"
        )

    if not _ler_valor_campo_minuta(driver, campo):
        try:
            campo.send_keys(Keys.TAB)
        except Exception:
            pass
        print("[SCH][MINUTA] Campo apagado pelo teclado e conferido.")
        return True

    try:
        resultado_js = driver.execute_script(
            """
            const campo = arguments[0];
            campo.focus();

            const proto = Object.getPrototypeOf(campo);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value') ||
                         Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');

            if (desc && typeof desc.set === 'function') {
                desc.set.call(campo, '');
            } else {
                campo.value = '';
            }

            campo.defaultValue = '';
            campo.dispatchEvent(new Event('input', {bubbles: true}));
            campo.dispatchEvent(new Event('change', {bubbles: true}));
            campo.dispatchEvent(new KeyboardEvent('keyup', {
                bubbles: true,
                key: 'Backspace',
                code: 'Backspace'
            }));
            campo.dispatchEvent(new Event('blur', {bubbles: true}));

            return {
                valor: String(campo.value == null ? '' : campo.value),
                id: campo.id || '',
                name: campo.name || ''
            };
            """,
            campo,
        ) or {}
        print(f"[SCH][MINUTA] Resultado da limpeza por JavaScript: {resultado_js}")
    except Exception as e:
        print(
            "[SCH][MINUTA][WARN] Falha na limpeza por JavaScript: "
            f"{type(e).__name__}: {e}"
        )

    time.sleep(0.35)
    valor_final = _ler_valor_campo_minuta(driver, campo)

    if valor_final:
        print(
            "[SCH][MINUTA][WARN] O textarea ainda possui "
            f"{len(valor_final)} caractere(s) após a limpeza."
        )
        return False

    print("[SCH][MINUTA] Conteúdo do textarea removido e conferido.")
    return True


TEXTO_MINUTA_IPV6 = "Suporta o protocolo IPv6."

TEXTO_MINUTA_EIRP = (
    "Valores de potência indicados nas faixas de 5150 – 5350 MHz, "
    "5470 - 5725 MHz e 5925 – 7125 MHz referem-se à potência média "
    "em E.I.R.P."
)


def _extrair_especificacoes_complementares_do_texto_direita(texto_direita):
    """
    Extrai, do documento da direita em Comparar Versões, o texto de
    Dados Técnicos do Produto > Especificações Complementares.

    Quando o recorte específico não for possível, devolve o texto completo
    do lado direito como fallback, permitindo detectar IPv6/E.I.R.P.
    """
    texto = str(texto_direita or "").replace("\r", "\n")

    if not texto.strip():
        return ""

    padroes = [
        r"Dados\s+T[eé]cnicos\s+do\s+Produto(?P<bloco>.*?)(?:\n\s*(?:Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos|Garantias|Outras\s+Unidades\s+Fabris)\b|$)",
        r"Especifica[cç][oõ]es\s+Complementares\s*[:\-]?\s*(?P<bloco>.*?)(?:\n\s*(?:Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos|Garantias|Outras\s+Unidades\s+Fabris)\b|$)",
    ]

    bloco_dados = texto

    m_dados = re.search(padroes[0], texto, flags=re.I | re.S)
    if m_dados:
        bloco_dados = m_dados.group("bloco") or ""

    m_especificacoes = re.search(
        r"Especifica[cç][oõ]es\s+Complementares\s*[:\-]?\s*(?P<bloco>.*?)(?:\n\s*(?:Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos|Garantias|Outras\s+Unidades\s+Fabris)\b|$)",
        bloco_dados,
        flags=re.I | re.S,
    )

    if m_especificacoes:
        recorte = str(m_especificacoes.group("bloco") or "").strip()
        if recorte:
            return recorte

    return texto.strip()


def _detectar_regras_especificacoes_complementares_retorno(conteudo):
    """
    Detecta palavras especiais no conteúdo original da minuta.

    Regras:
    - IPv6, IPV6, ipv6 e variações com espaço/pontuação;
    - E.I.R.P., E.I.R.P, EIRP, eirp e variações com espaços/pontos.

    Quando ambas aparecem, as duas frases são mantidas, uma por linha.
    """
    conteudo = str(conteudo or "")
    conteudo_norm = _normalizar_texto_comparacao(conteudo)

    tem_ipv6 = bool(
        re.search(r"\bip\s*v?\s*6\b", conteudo_norm, flags=re.I)
        or "ipv6" in conteudo_norm
    )

    tem_eirp = bool(
        re.search(r"\be\s*i\s*r\s*p\b", conteudo_norm, flags=re.I)
        or re.search(r"\beirp\b", conteudo_norm, flags=re.I)
    )

    palavras = []
    frases = []

    if tem_ipv6:
        palavras.append("ipv6")
        frases.append(TEXTO_MINUTA_IPV6)

    if tem_eirp:
        palavras.append("eirp")
        frases.append(TEXTO_MINUTA_EIRP)

    if tem_ipv6 and tem_eirp:
        acao = "substituir_por_ipv6_e_eirp"
    elif tem_ipv6:
        acao = "substituir_por_ipv6"
    elif tem_eirp:
        acao = "substituir_por_eirp"
    else:
        acao = "limpar_conteudo"

    return {
        "tem_ipv6": tem_ipv6,
        "tem_eirp": tem_eirp,
        "palavras_identificadas": palavras,
        "acao": acao,
        "texto_final": "\n".join(frases).strip(),
    }


def _definir_valor_campo_minuta(driver, campo, texto):
    """
    Substitui integralmente o valor do textarea/input e confirma o resultado.
    """
    texto = str(texto or "")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        campo,
    )

    try:
        driver.execute_script("arguments[0].focus();", campo)
        campo.click()
        campo.send_keys(Keys.CONTROL, "a")
        time.sleep(0.1)
        campo.send_keys(Keys.DELETE)
        campo.send_keys(Keys.BACKSPACE)

        if texto:
            campo.send_keys(texto)

        time.sleep(0.2)
    except Exception as e:
        print(
            "[SCH][MINUTA][WARN] Falha ao substituir pelo teclado: "
            f"{type(e).__name__}: {e}"
        )

    valor_atual = _ler_valor_campo_minuta(driver, campo)

    if (
        _normalizar_texto_comparacao(valor_atual)
        == _normalizar_texto_comparacao(texto)
    ):
        try:
            campo.send_keys(Keys.TAB)
        except Exception:
            pass
        return True

    try:
        driver.execute_script(
            """
            const campo = arguments[0];
            const valor = arguments[1];

            campo.focus();

            const proto = Object.getPrototypeOf(campo);
            const desc =
                Object.getOwnPropertyDescriptor(proto, 'value') ||
                Object.getOwnPropertyDescriptor(
                    HTMLTextAreaElement.prototype,
                    'value'
                ) ||
                Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype,
                    'value'
                );

            if (desc && typeof desc.set === 'function') {
                desc.set.call(campo, valor);
            } else {
                campo.value = valor;
            }

            campo.defaultValue = valor;
            campo.dispatchEvent(new Event('input', {bubbles: true}));
            campo.dispatchEvent(new Event('change', {bubbles: true}));
            campo.dispatchEvent(new KeyboardEvent('keyup', {
                bubbles: true,
                key: valor ? 'a' : 'Backspace',
                code: valor ? 'KeyA' : 'Backspace'
            }));
            campo.dispatchEvent(new Event('blur', {bubbles: true}));
            """,
            campo,
            texto,
        )
    except Exception as e:
        print(
            "[SCH][MINUTA][WARN] Falha ao substituir por JavaScript: "
            f"{type(e).__name__}: {e}"
        )

    time.sleep(0.35)
    valor_final = _ler_valor_campo_minuta(driver, campo)

    confirmado = (
        _normalizar_texto_comparacao(valor_final)
        == _normalizar_texto_comparacao(texto)
    )

    if confirmado:
        print(
            "[SCH][MINUTA] Conteúdo substituído e conferido: "
            f"{texto or '[vazio]'}"
        )
    else:
        print(
            "[SCH][MINUTA][WARN] Valor final não corresponde ao esperado. "
            f"Esperado={texto!r} | Obtido={valor_final!r}"
        )

    return confirmado


def limpar_especificacoes_complementares_minuta_se_necessario(
    driver,
    wait,
    req=None,
    aba_original_sch=None,
    texto_especificacoes_versao_nova="",
):
    """
    Tratamento de Especificações Complementares na fila Retorno Para Estudo.

    O tipo do produto continua decidindo se Corrigir Minuta deve ser aberto.

    Após abrir o campo:
    - se encontrar IPv6, substitui todo o conteúdo por:
      "Suporta o protocolo IPv6.";
    - se encontrar E.I.R.P./EIRP, substitui todo o conteúdo pela frase
      padronizada de potência média em E.I.R.P.;
    - se encontrar ambos, grava as duas frases, uma por linha;
    - se não encontrar nenhum, mantém a regra anterior e apaga tudo.
    """
    req = req or {}

    tipo_produto = (
        req.get("tipo_produto")
        or req.get("tipo")
        or ""
    )

    resultado = {
        "aplicavel": False,
        "regra_aplicada": "tratamento_por_tipo_produto_e_palavras_chave",
        "tipo_produto": tipo_produto,
        "campo_encontrado": False,
        "conteudo_anterior": "",
        "texto_especificacoes_versao_nova": str(
            texto_especificacoes_versao_nova or ""
        ),
        "texto_analisado_palavras_chave": "",
        "fontes_analisadas": [],
        "conteudo_final_esperado": "",
        "conteudo_final_confirmado": "",
        "palavras_identificadas": [],
        "acao_minuta": "",
        "tratado": False,
        "limpo": False,
        "substituido": False,
        "salvo": False,
        "confirmado_apos_salvar": False,
        "retornou_para_requerimento": False,
        "preenchido_automaticamente": False,
        "frase": "",
        "status": "nao_aplicavel",
    }

    if not _tipo_produto_deve_limpar_especificacoes_complementares(
        tipo_produto
    ):
        resultado["motivo"] = "tipo_produto_fora_da_regra_de_tratamento"
        resultado["mensagem"] = (
            "Tipo de produto fora da lista de tratamento automático. "
            "A análise de Retorno Para Estudo permanece válida."
        )

        print(
            "[SCH][MINUTA] Tipo fora da lista de tratamento; "
            "Corrigir Minuta não será aberto: "
            f"{tipo_produto or 'não identificado'}"
        )
        return resultado

    resultado["aplicavel"] = True

    print(
        "[SCH][MINUTA] Tipo exige tratamento de Especificações "
        f"Complementares: {tipo_produto}"
    )

    abriu_minuta = False

    try:
        clicar_corrigir_minuta(
            driver,
            wait,
            aba_original_sch=aba_original_sch,
        )
        abriu_minuta = True

        if not abrir_secao_especificacao_minuta(driver, wait):
            raise RuntimeError(
                "Não foi possível abrir a seção Especificação."
            )

        entrar_iframe_detalhe_analise(driver, wait)

        campo = _localizar_campo_especificacoes_complementares_minuta(
            driver,
            timeout=5,
        )

        if campo is None:
            raise RuntimeError(
                "Campo Especificações Complementares não encontrado."
            )

        resultado["campo_encontrado"] = True

        conteudo_anterior = _ler_valor_campo_minuta(driver, campo)
        resultado["conteudo_anterior"] = conteudo_anterior

        fontes_analisadas = []
        partes_para_analisar = []

        texto_versao_nova = str(
            texto_especificacoes_versao_nova or ""
        ).strip()

        if texto_versao_nova:
            fontes_analisadas.append(
                "Comparar Versões - documento da direita"
            )
            partes_para_analisar.append(texto_versao_nova)

        if conteudo_anterior.strip():
            fontes_analisadas.append(
                "Corrigir Minuta - Especificações Complementares"
            )
            partes_para_analisar.append(conteudo_anterior)

        texto_para_analisar = "\n".join(partes_para_analisar).strip()

        resultado["fontes_analisadas"] = fontes_analisadas
        resultado["texto_analisado_palavras_chave"] = texto_para_analisar

        regra = _detectar_regras_especificacoes_complementares_retorno(
            texto_para_analisar
        )

        print(
            "[SCH][MINUTA] Fonte Comparar Versões - lado direito: "
            f"{'capturada' if texto_versao_nova else 'não capturada'}"
        )
        print(
            "[SCH][MINUTA] Fonte Corrigir Minuta: "
            f"{'capturada' if conteudo_anterior.strip() else 'vazia'}"
        )
        print(
            "[SCH][MINUTA] IPv6 encontrado: "
            f"{'SIM' if regra.get('tem_ipv6') else 'NÃO'}"
        )
        print(
            "[SCH][MINUTA] E.I.R.P. encontrado: "
            f"{'SIM' if regra.get('tem_eirp') else 'NÃO'}"
        )

        texto_final = regra["texto_final"]
        acao_minuta = regra["acao"]

        resultado["palavras_identificadas"] = list(
            regra["palavras_identificadas"]
        )
        resultado["acao_minuta"] = acao_minuta
        resultado["conteudo_final_esperado"] = texto_final
        resultado["frase"] = texto_final

        print(
            "[SCH][MINUTA] Regra detectada: "
            f"{acao_minuta} | palavras="
            f"{resultado['palavras_identificadas'] or 'nenhuma'}"
        )

        if acao_minuta == "limpar_conteudo":
            if conteudo_anterior.strip():
                campo_confirmado = (
                    _limpar_elemento_especificacoes_complementares(
                        driver,
                        campo,
                    )
                )
            else:
                campo_confirmado = True
                print(
                    "[SCH][MINUTA] Especificações Complementares "
                    "já estavam vazias."
                )

            resultado["limpo"] = bool(campo_confirmado)
            resultado["substituido"] = False
        else:
            campo_confirmado = _definir_valor_campo_minuta(
                driver,
                campo,
                texto_final,
            )
            resultado["limpo"] = False
            resultado["substituido"] = bool(campo_confirmado)

        resultado["tratado"] = bool(campo_confirmado)

        if not resultado["tratado"]:
            raise RuntimeError(
                "Não foi possível confirmar o conteúdo esperado antes "
                "de salvar a minuta."
            )

        entrar_iframe_detalhe_analise(driver, wait)

        resultado_salvar = salvar_minuta_corrigida(
            driver=driver,
            wait=wait,
            texto_esperado=(
                texto_final
                if acao_minuta != "limpar_conteudo"
                else None
            ),
            confirmar_vazio=(
                acao_minuta == "limpar_conteudo"
            ),
        )

        resultado["resultado_salvamento"] = resultado_salvar
        resultado["salvo"] = bool(resultado_salvar.get("salvo"))
        resultado["confirmado_apos_salvar"] = bool(
            resultado_salvar.get("confirmado_apos_salvar")
        )
        resultado["conteudo_final_confirmado"] = str(
            resultado_salvar.get("valor_apos_salvar") or ""
        )

        resultado["retornou_para_requerimento"] = bool(
            voltar_da_tela_corrigir_minuta(driver, wait)
        )

        sucesso = bool(
            resultado["tratado"]
            and resultado["salvo"]
            and resultado["confirmado_apos_salvar"]
            and resultado["retornou_para_requerimento"]
        )

        resultado["preenchido_automaticamente"] = sucesso

        if sucesso:
            if acao_minuta == "limpar_conteudo":
                resultado["status"] = "limpo_e_salvo"
                resultado["mensagem"] = (
                    "Especificações Complementares apagadas, salvas e "
                    "confirmadas com sucesso."
                )
            else:
                resultado["status"] = "substituido_e_salvo"
                resultado["mensagem"] = (
                    "Especificações Complementares substituídas, salvas e "
                    "confirmadas com sucesso."
                )
        else:
            resultado["status"] = "tratamento_nao_confirmado"
            resultado["motivo"] = (
                "Não foi possível confirmar todas as etapas do tratamento."
            )
            resultado["mensagem"] = resultado["motivo"]

        return resultado

    except Exception as e:
        resultado["status"] = "erro"
        resultado["erro"] = str(e)
        resultado["mensagem"] = (
            "Falha ao tratar Especificações Complementares."
        )

        print(
            "[SCH][MINUTA][WARN] Falha ao tratar "
            f"Especificações Complementares: {e}"
        )

        if abriu_minuta:
            try:
                resultado["retornou_para_requerimento"] = bool(
                    voltar_da_tela_corrigir_minuta(driver, wait)
                )
            except Exception:
                resultado["retornou_para_requerimento"] = False

        return resultado

def processar_corrigir_minuta_por_regras(
    driver,
    wait,
    req=None,
    dados_pdf=None,
    fila_sch="Em Análise",
    aba_original_sch=None,
):
    """
    Compatibilidade para chamadas externas, respeitando os dois fluxos:

    - Retorno Para Estudo:
      consulta o tipo do produto e, quando estiver na lista configurada,
      apaga Especificações Complementares e salva.

    - Em Análise:
      não usa a lista de tipos para limpeza; analisa o CCT e decide o
      tratamento de SAR.

    O fluxo_sch.py atualizado chama as funções específicas diretamente,
    mas esta função permanece protegida contra mistura entre as filas.
    """
    req = req or {}
    dados_pdf = dados_pdf or {}

    fila_norm = _normalizar_texto_comparacao(fila_sch)
    eh_retorno = fila_norm in {
        "retorno para estudo",
        "retorno pra estudo",
        "retorno estudo",
    }

    tipo_produto = (
        req.get("tipo_produto")
        or req.get("tipo")
        or ""
    )

    if eh_retorno:
        resultado = limpar_especificacoes_complementares_minuta_se_necessario(
            driver=driver,
            wait=wait,
            req=req,
            aba_original_sch=aba_original_sch,
        )
        resultado["regra_aplicada"] = (
            "limpeza_especificacoes_complementares_retorno_para_estudo"
        )
        resultado["fila_sch"] = "Retorno Para Estudo"
        resultado["analise_sar_executada"] = False
        return resultado

    resultado = preencher_minuta_sar_se_necessario(
        driver=driver,
        wait=wait,
        dados_pdf=dados_pdf,
    )
    resultado["regra_aplicada"] = "analise_sar_cct_em_analise"
    resultado["fila_sch"] = "Em Análise"
    resultado["tipo_produto"] = tipo_produto
    resultado["limpeza_por_tipo_executada"] = False
    return resultado


def preencher_minuta_sar_se_necessario(driver, wait, dados_pdf):
    analise = analisar_sar_cct(dados_pdf)

    print(
        f"[SCH] Análise SAR: {analise.get('status')} | "
        f"{analise.get('mensagem')}"
    )

    if not analise.get("preencher_frase") or not analise.get("frase"):
        analise["preenchido_automaticamente"] = False
        analise["salvo"] = False
        analise["confirmado_apos_salvar"] = False
        analise["retornou_para_requerimento"] = False
        return analise

    frase_sar = str(analise.get("frase") or "").strip()

    if _normalizar_texto_comparacao(frase_sar) == _normalizar_texto_comparacao(
        "Ensaio de SAR não aplicável"
    ):
        frase_sar = FRASE_SAR_NAO_APLICAVEL

    if frase_sar and not frase_sar.endswith("."):
        frase_sar = frase_sar + "."

    analise["frase"] = frase_sar

    try:
        clicar_corrigir_minuta(driver, wait)

        secao_aberta = abrir_secao_especificacao_minuta(driver, wait)

        if not secao_aberta:
            raise Exception(
                "Não foi possível abrir o caminho: "
                "Corrigir Minuta > Especificação > Especificações Complementares."
            )

        xpaths_minuta = [
            "//*[contains(normalize-space(), 'Especificações Complementares')]/following::textarea[1]",
            "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::textarea[1]",

            "//*[contains(normalize-space(), 'Especificações Complementares')]/following::input[not(@type='hidden')][1]",
            "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::input[not(@type='hidden')][1]",

            "//*[contains(normalize-space(), 'Especificações Complementares')]/following::*[@contenteditable='true'][1]",
            "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::*[@contenteditable='true'][1]",

            "//*[contains(normalize-space(), 'Especificações Complementares')]/following::div[contains(@class,'ql-editor')][1]",
            "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::div[contains(@class,'ql-editor')][1]",
        ]

        preenchido = _substituir_texto_campo(
            driver=driver,
            wait=wait,
            texto=analise["frase"],
            descricao="Corrigir Minuta > Especificação > Especificações Complementares",
            xpaths_input=xpaths_minuta,
        )

        resultado_salvar = salvar_minuta_corrigida(
            driver=driver,
            wait=wait,
            texto_esperado=analise["frase"],
        )

        retornou_minuta = voltar_da_tela_corrigir_minuta(driver, wait)

        analise["status"] = "preenchido"
        analise["preenchido_automaticamente"] = bool(preenchido)
        analise["salvo"] = bool(resultado_salvar.get("salvo"))
        analise["confirmado_apos_salvar"] = bool(
            resultado_salvar.get("confirmado_apos_salvar")
        )
        analise["retornou_para_requerimento"] = bool(retornou_minuta)
        analise["resultado_salvamento"] = resultado_salvar

        return analise

    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher a frase de SAR na minuta: {e}")

        try:
            voltou = voltar_da_tela_corrigir_minuta(driver, wait)
        except Exception:
            voltou = False

        analise["status"] = "erro"
        analise["erro"] = str(e)
        analise["preenchido_automaticamente"] = False
        analise["salvo"] = False
        analise["confirmado_apos_salvar"] = False
        analise["retornou_para_requerimento"] = bool(voltou)
        analise["mensagem"] = (
            "Não foi possível preencher automaticamente a frase de SAR no caminho "
            "Corrigir Minuta > Especificação > Especificações Complementares."
        )

        return analise

def preencher_caracteristicas_tecnicas_com_analise(driver, wait, req, anexos_baixados, dados_pdf):
    analise = decidir_texto_observacao_por_cct(dados_pdf)

    print(
        f"[SCH] Análise rápida: {analise['classificacao']} "
        f"| motivos={analise.get('motivos', [])}"
    )

    clicar_aba_caracteristicas_tecnicas(driver, wait)

    preenchido = preencher_observacao_caracteristicas(
        driver,
        wait,
        analise["texto"],
    )

    titulo_secundario = preencher_titulo_caracteristicas_secundarias_se_existir(
        driver=driver,
        wait=wait,
        req=req,
        dados_pdf=dados_pdf,
    )

    resultado_salvamento = salvar_caracteristicas_tecnicas(
        driver,
        wait,
        texto_esperado=analise["texto"],
        titulo_secundario_esperado=(
            titulo_secundario.get("titulo_esperado", "")
            if titulo_secundario.get("campo_encontrado")
            else ""
        ),
    )

    analise["preenchido_automaticamente"] = bool(preenchido)
    analise["titulo_caracteristicas_secundarias"] = titulo_secundario
    analise["salvo"] = bool(resultado_salvamento.get("salvo"))
    analise["confirmado_apos_salvar"] = bool(
        resultado_salvamento.get("confirmado_apos_salvar")
    )
    analise["resultado_salvamento"] = resultado_salvamento

    return analise



def clicar_aba_informacoes_adicionais(driver, wait):
    """
    Abre a aba Informações Adicionais de forma tolerante ao retorno do
    Comparar Versões.

    Após fechar a comparação, o SCH pode mostrar a tela do requerimento antes
    de os componentes internos da aba estarem completamente clicáveis.
    Por isso esta rotina:
    - confirma primeiro se a aba já está aberta;
    - relocaliza o iframe a cada tentativa;
    - aceita estruturas PrimeFaces com a/span/li;
    - usa timeout maior do que o fluxo rápido normal;
    - confirma a abertura pelo conteúdo real de Acompanhar Processo.
    """
    print("[SCH] Abrindo aba Informações Adicionais...")

    xpaths_aba = [
        "//a[normalize-space(.)='Informações Adicionais']",
        "//a[normalize-space(.)='Informacoes Adicionais']",
        "//span[normalize-space(.)='Informações Adicionais']/ancestor::a[1]",
        "//span[normalize-space(.)='Informacoes Adicionais']/ancestor::a[1]",
        "//li[.//*[normalize-space(.)='Informações Adicionais']]//a[1]",
        "//li[.//*[normalize-space(.)='Informacoes Adicionais']]//a[1]",
        "//*[self::a or self::button][contains(normalize-space(.), 'Informações Adicionais')]",
        "//*[self::a or self::button][contains(normalize-space(.), 'Informacoes Adicionais')]",
    ]

    ultimo_erro = None

    for tentativa in range(1, 5):
        try:
            entrar_iframe_detalhe_analise(driver, wait)
        except Exception as e:
            ultimo_erro = e
            esperar_tela_carregar(driver, 0.5)
            continue

        # Se o conteúdo da aba já estiver visível, não precisamos clicar.
        try:
            if _ha_campo_informacoes_adicionais(driver):
                print("[SCH] Aba 'Informações Adicionais' já está aberta.")
                return True
        except Exception:
            pass

        alvo = None

        for xpath in xpaths_aba:
            try:
                elementos = WebDriverWait(
                    driver,
                    3.5,
                    poll_frequency=0.12,
                ).until(
                    EC.presence_of_all_elements_located((By.XPATH, xpath))
                )

                for el in elementos:
                    try:
                        if el.is_displayed() and el.is_enabled():
                            alvo = el
                            break
                    except Exception:
                        continue

                if alvo is not None:
                    break

            except Exception as e:
                ultimo_erro = e
                continue

        if alvo is None:
            print(
                "[SCH][RETORNO][WARN] Aba Informações Adicionais ainda não "
                f"clicável. Tentativa {tentativa}/4."
            )
            esperar_tela_carregar(driver, 0.6)
            continue

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                alvo,
            )
        except Exception:
            pass

        try:
            _clicar_com_fallback(driver, alvo)
        except Exception as e:
            ultimo_erro = e
            esperar_tela_carregar(driver, 0.5)
            continue

        # O clique pode disparar AJAX; aguarda o conteúdo real.
        inicio = time.time()

        while time.time() - inicio < 6:
            try:
                entrar_iframe_detalhe_analise(driver, wait)

                if _ha_campo_informacoes_adicionais(driver):
                    print("[SCH] Aba 'Informações Adicionais' aberta.")
                    return True

            except Exception as e:
                ultimo_erro = e

            time.sleep(0.2)

        print(
            "[SCH][RETORNO][WARN] Clique em Informações Adicionais foi "
            f"executado, mas o conteúdo ainda não apareceu. Tentativa {tentativa}/4."
        )
        esperar_tela_carregar(driver, 0.6)

    raise Exception(
        "Não foi possível abrir a aba 'Informações Adicionais' após o "
        "retorno do Comparar Versões. "
        f"Último erro: {ultimo_erro}"
    )

TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES = (
    "Este processo foi analisado conforme Portaria n° 2257, "
    "de 03 de março de 2022 (Análise Simplificada)."
)


def _achar_primeiro_elemento_visivel(driver, xpaths, descricao, timeout=4):
    for xpath in xpaths:
        try:
            elementos = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.XPATH, xpath))
            )
            for el in elementos:
                try:
                    if el.is_displayed() and el.is_enabled():
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            el,
                        )
                        return el
                except Exception:
                    continue
        except Exception:
            continue

    raise Exception(f"Elemento não encontrado/visível: {descricao}")


def _checkbox_esta_marcado(elemento):
    try:
        tag = (elemento.tag_name or "").lower()

        if tag == "input":
            tipo = (elemento.get_attribute("type") or "").lower()
            if tipo == "checkbox":
                return elemento.is_selected()

        checked = (elemento.get_attribute("checked") or "").lower()
        aria_checked = (elemento.get_attribute("aria-checked") or "").lower()
        classe = (elemento.get_attribute("class") or "").lower()

        return (
            checked in {"true", "checked"}
            or aria_checked == "true"
            or "checked" in classe
            or "selected" in classe
        )
    except Exception:
        return False



def _localizar_textarea_acompanhar_processo(driver, wait=None, timeout=6):
    """
    Localiza SOMENTE o textarea grande da seção 'Acompanhar Processo'.

    A tela do Retorno Para Estudo possui outros textareas:
    - Justificativa do OCD;
    - Descrição da seção inferior Informações Adicionais.

    Por segurança, esta função nunca usa '(//textarea)[1]' como fallback.
    """
    entrar_iframe_detalhe_analise(driver, wait)

    try:
        timeout = max(0.5, float(timeout or 6))
    except Exception:
        timeout = 6.0

    xpaths = [
        "//label[contains(normalize-space(.), 'Desejo acompanhar este processo')]/following::textarea[not(@disabled)][1]",
        "//*[self::span or self::div or self::td][contains(normalize-space(.), 'Desejo acompanhar este processo')]/following::textarea[not(@disabled)][1]",
        "//*[normalize-space(.)='Acompanhar Processo']/following::textarea[not(@disabled)][1]",
        "//*[contains(normalize-space(.), 'Acompanhar Processo')]/following::textarea[not(@disabled)][1]",
        "//textarea[not(@disabled) and contains(translate(concat(@id,' ',@name),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
    ]

    inicio = time.time()

    while time.time() - inicio < timeout:
        entrar_iframe_detalhe_analise(driver, wait)

        for xpath in xpaths:
            try:
                elementos = driver.find_elements(By.XPATH, xpath)
            except Exception:
                elementos = []

            for campo in elementos:
                try:
                    if (
                        str(campo.tag_name or "").lower() == "textarea"
                        and campo.is_displayed()
                        and campo.is_enabled()
                    ):
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                            campo,
                        )
                        return campo
                except Exception:
                    continue

        # Fallback DOM controlado:
        # procura o primeiro textarea VISÍVEL que aparece DEPOIS do texto
        # "Desejo acompanhar este processo", sem usar posição global da página.
        try:
            campo_js = driver.execute_script(
                """
                function norm(s) {
                    return String(s || '')
                        .normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '')
                        .replace(/\\s+/g, ' ')
                        .trim()
                        .toLowerCase();
                }

                function visivel(el) {
                    if (!el || el.disabled) return false;
                    const st = getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.display !== 'none'
                        && st.visibility !== 'hidden'
                        && Number(st.opacity || 1) !== 0
                        && r.width > 0
                        && r.height > 0;
                }

                const todos = Array.from(
                    document.querySelectorAll('label, span, div, td, th')
                );

                const marcador = todos.find(el =>
                    norm(el.innerText || el.textContent)
                        .includes('desejo acompanhar este processo')
                );

                if (!marcador) return null;

                const textareas = Array.from(
                    document.querySelectorAll('textarea:not([disabled])')
                ).filter(visivel);

                for (const ta of textareas) {
                    const pos = marcador.compareDocumentPosition(ta);

                    if (pos & Node.DOCUMENT_POSITION_FOLLOWING) {
                        return ta;
                    }
                }

                return null;
                """
            )

            if campo_js is not None:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    campo_js,
                )
                return campo_js

        except Exception:
            pass

        time.sleep(0.15)

    raise RuntimeError(
        "Textarea da seção 'Acompanhar Processo' não foi localizado "
        "com segurança."
    )



def marcar_acompanhar_processo(driver, wait):
    """
    Marca especificamente:
    'Desejo acompanhar este processo.'

    Não usa checkbox genérico da página.
    """
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.05)

    checkbox_xpaths = [
        "//label[contains(normalize-space(.), 'Desejo acompanhar este processo')]/preceding::input[@type='checkbox'][1]",
        "//label[contains(normalize-space(.), 'Desejo acompanhar este processo')]/ancestor::*[self::td or self::div or self::span][1]//input[@type='checkbox'][1]",
        "//input[@type='checkbox' and contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
        "//input[@type='checkbox' and contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
    ]

    label_xpaths = [
        "//label[contains(normalize-space(.), 'Desejo acompanhar este processo')]",
        "//*[self::span or self::div or self::td][contains(normalize-space(.), 'Desejo acompanhar este processo')]",
    ]

    def localizar_checkbox():
        entrar_iframe_detalhe_analise(driver, wait)

        for xpath in checkbox_xpaths:
            try:
                for el in driver.find_elements(By.XPATH, xpath):
                    try:
                        if el.is_enabled():
                            return el
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    checkbox = localizar_checkbox()

    if checkbox is not None and _checkbox_esta_marcado(checkbox):
        print("[SCH] Opção 'Desejo acompanhar este processo' já está marcada.")
        return True

    # Em alguns layouts PrimeFaces o input real pode ficar visualmente oculto;
    # nesses casos o clique correto é no label.
    alvo = None

    for xpath in label_xpaths:
        try:
            for el in driver.find_elements(By.XPATH, xpath):
                try:
                    if el.is_displayed():
                        alvo = el
                        break
                except Exception:
                    continue
            if alvo is not None:
                break
        except Exception:
            continue

    if alvo is None:
        alvo = checkbox

    if alvo is None:
        raise RuntimeError(
            "Controle 'Desejo acompanhar este processo' não foi localizado."
        )

    for tentativa in range(1, 3):
        entrar_iframe_detalhe_analise(driver, wait)

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                alvo,
            )
        except Exception:
            pass

        _clicar_com_fallback(driver, alvo)
        esperar_tela_carregar(driver, 0.18)

        checkbox = localizar_checkbox()

        if checkbox is not None and _checkbox_esta_marcado(checkbox):
            print(
                "[SCH] Opção 'Desejo acompanhar este processo' "
                "marcada com sucesso."
            )
            return True

        # Relocaliza o label após eventual AJAX.
        alvo = None
        entrar_iframe_detalhe_analise(driver, wait)

        for xpath in label_xpaths:
            try:
                for el in driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        alvo = el
                        break
                if alvo is not None:
                    break
            except Exception:
                continue

        if alvo is None:
            alvo = checkbox

    print(
        "[SCH][WARN] Não foi possível confirmar que "
        "'Desejo acompanhar este processo' ficou marcado."
    )
    return False


def preencher_acompanhar_processo(driver, wait, texto):
    """
    Substitui TODO o conteúdo do textarea grande de Acompanhar Processo
    pelo texto informado.

    Não altera Justificativa nem o campo Descrição inferior.
    """
    texto = str(texto or "").strip()

    if not texto:
        print("[SCH][WARN] Texto vazio para Acompanhar Processo.")
        return False

    clicar_aba_informacoes_adicionais(driver, wait)

    if not marcar_acompanhar_processo(driver, wait):
        raise RuntimeError(
            "Não foi possível marcar 'Desejo acompanhar este processo'."
        )

    campo = _localizar_textarea_acompanhar_processo(
        driver,
        wait,
        timeout=6,
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        campo,
    )

    # 1) Simula a ação manual.
    try:
        campo.click()
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.DELETE)
        campo.send_keys(texto)
    except Exception as e:
        print(
            "[SCH][RETORNO][WARN] Preenchimento pelo teclado falhou; "
            f"aplicando setter nativo: {e}"
        )

    # 2) Sempre reforça o valor com o setter nativo do textarea.
    # Isso evita casos em que o texto aparece visualmente mas o JSF/PrimeFaces
    # não reconhece a alteração.
    driver.execute_script(
        """
        const campo = arguments[0];
        const valor = arguments[1];

        campo.focus();

        const proto = HTMLTextAreaElement.prototype;
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');

        if (desc && typeof desc.set === 'function') {
            desc.set.call(campo, valor);
        } else {
            campo.value = valor;
        }

        campo.defaultValue = valor;

        campo.dispatchEvent(new Event('input', {
            bubbles: true
        }));
        campo.dispatchEvent(new Event('change', {
            bubbles: true
        }));
        campo.dispatchEvent(new KeyboardEvent('keyup', {
            bubbles: true,
            key: 'a'
        }));
        campo.dispatchEvent(new Event('blur', {
            bubbles: true
        }));
        """,
        campo,
        texto,
    )

    try:
        campo.send_keys(Keys.TAB)
    except Exception:
        pass

    esperar_tela_carregar(driver, 0.20)

    # O AJAX pode recriar o textarea. Relocalizamos antes de validar.
    campo = _localizar_textarea_acompanhar_processo(
        driver,
        wait,
        timeout=4,
    )

    valor = str(
        driver.execute_script(
            "return arguments[0].value == null ? '' : String(arguments[0].value);",
            campo,
        )
        or ""
    ).strip()

    confirmado = (
        _normalizar_texto_comparacao(valor)
        == _normalizar_texto_comparacao(texto)
    )

    if confirmado:
        print(
            "[SCH][RETORNO] Frase preenchida no campo correto "
            "'Acompanhar Processo'."
        )
        return True

    print(
        "[SCH][RETORNO][WARN] O textarea correto foi localizado, "
        "mas o valor exato da frase não pôde ser confirmado."
    )
    return False


def salvar_informacoes_adicionais(driver, wait):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.05)

    xpaths_salvar = [
        "//button[normalize-space()='Salvar']",
        "//a[normalize-space()='Salvar']",
        "//input[(@type='submit' or @type='button') and normalize-space(@value)='Salvar']",
        "//span[normalize-space()='Salvar']/ancestor::button[1]",
        "//span[normalize-space()='Salvar']/ancestor::a[1]",
        "//*[@title='Salvar']",
    ]

    botao = _achar_primeiro_elemento_visivel(
        driver,
        xpaths_salvar,
        "botão Salvar em Informações Adicionais",
        timeout=5,
    )

    print("[SCH][RETORNO] Salvando Informações Adicionais...")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        botao,
    )
    _clicar_com_fallback(driver, botao)

    # Alguns casos apresentam alert nativo; outros atualizam por AJAX.
    try:
        alerta = WebDriverWait(driver, 1.5).until(
            EC.alert_is_present()
        )
        print(
            "[SCH][RETORNO] Confirmação após Salvar: "
            f"{alerta.text}"
        )
        alerta.accept()
    except Exception:
        pass

    esperar_tela_carregar(driver, 0.8)

    print("[SCH][RETORNO] Clique em Salvar executado.")
    return True

def montar_texto_informacoes_adicionais(req, anexos_baixados, dados_pdf, analise_rapida):
    return TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES


def preencher_texto_informacoes_adicionais(driver, wait, texto):
    return preencher_acompanhar_processo(driver, wait, texto)


def preencher_informacoes_adicionais_com_analise(
    driver,
    wait,
    req,
    anexos_baixados,
    dados_pdf,
    analise_rapida=None,
):
    texto = montar_texto_informacoes_adicionais(
        req=req,
        anexos_baixados=anexos_baixados,
        dados_pdf=dados_pdf,
        analise_rapida=analise_rapida or {},
    )

    try:
        clicar_aba_informacoes_adicionais(driver, wait)
        acompanhar_marcado = marcar_acompanhar_processo(driver, wait)
        preenchido = preencher_texto_informacoes_adicionais(driver, wait, texto)
        salvo = salvar_informacoes_adicionais(driver, wait)

        return {
            "texto": texto,
            "classificacao": "analise_simplificada_portaria_2257",
            "motivos": [],
            "preenchido_automaticamente": preenchido,
            "acompanhar_processo_marcado": acompanhar_marcado,
            "salvo": salvo,
            "modo_preenchimento": "acompanhar_processo",
        }

    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher Informações Adicionais automaticamente: {e}")
        return {
            "texto": texto,
            "classificacao": "analise_simplificada_portaria_2257",
            "motivos": [],
            "preenchido_automaticamente": False,
            "acompanhar_processo_marcado": False,
            "salvo": False,
            "modo_preenchimento": "acompanhar_processo",
            "erro": str(e),
        }


FRASE_MARCACAO_AUTOMACAO_RETORNO = (
    "Este processo foi avaliado por automação, quando em Retorno para Estudo."
)



def registrar_avaliacao_automacao_informacoes_adicionais_retorno(
    driver,
    wait,
    frase=FRASE_MARCACAO_AUTOMACAO_RETORNO,
    texto_original_analisado="",
    analise_tipos_re=None,
):
    """
    Registra a frase da automação SOMENTE em:
    Informações Adicionais > Acompanhar Processo.

    A Justificativa do OCD permanece intacta.

    A rotina:
    - marca 'Desejo acompanhar este processo';
    - substitui qualquer conteúdo anterior (ex.: 'AS') pela frase exata;
    - salva;
    - relê o campo depois do AJAX;
    - se a frase não persistir, repete o preenchimento/salvamento uma vez;
    - só retorna confirmada_apos_salvar=True quando o texto exato persistiu.
    """
    frase = str(frase or "").strip()
    texto_original_analisado = str(texto_original_analisado or "").strip()

    resultado = {
        "exigida": True,
        "frase": frase,
        "campo_destino": "Acompanhar Processo",
        "justificativa_preservada": True,
        "conteudo_original_analisado": texto_original_analisado,
        "analise_tipos_re": analise_tipos_re or {},
        "texto_original_capturado_antes_do_registro": bool(
            texto_original_analisado
        ),
        "tipo_re_analisado_antes_do_registro": bool(
            isinstance(analise_tipos_re, dict)
        ),
        "acompanhar_processo_marcado": False,
        "campo_encontrado": False,
        "conteudo_anterior": "",
        "conteudo_final": "",
        "conteudo_confirmado": "",
        "ja_existia": False,
        "substituida": False,
        "preenchida": False,
        "salva": False,
        "confirmada_apos_salvar": False,
        "tentativas_preenchimento": 0,
        "status": "pendente",
    }

    if not frase:
        resultado["status"] = "frase_vazia"
        resultado["erro"] = "Frase de marcação vazia."
        return resultado

    if not isinstance(analise_tipos_re, dict):
        resultado["status"] = "bloqueado_sem_analise_previa_tipo_re"
        resultado["erro"] = (
            "A marcação não foi executada porque a análise prévia "
            "do tipo RE não foi informada."
        )
        return resultado

    if analise_tipos_re.get("tem_numero_nao_permitido"):
        resultado["status"] = "bloqueado_tipo_re_fora_escopo"
        resultado["erro"] = (
            "A marcação não foi executada porque o tipo RE atual "
            "está fora do escopo de aprovação automática."
        )
        return resultado

    if not analise_tipos_re.get("combinacao_ok", True):
        resultado["status"] = "bloqueado_combinacao_tipo_re_nao_permitida"
        resultado["erro"] = (
            "A marcação não foi executada porque a combinação atual "
            "de tipos RE não está no escopo de aprovação automática."
        )
        return resultado

    frase_norm = _normalizar_texto_comparacao(frase)

    def ler_campo():
        clicar_aba_informacoes_adicionais(driver, wait)

        campo = _localizar_textarea_acompanhar_processo(
            driver,
            wait,
            timeout=6,
        )

        valor = str(
            driver.execute_script(
                "return arguments[0].value == null ? '' : String(arguments[0].value);",
                campo,
            )
            or ""
        ).strip()

        return campo, valor

    try:
        clicar_aba_informacoes_adicionais(driver, wait)

        marcado = marcar_acompanhar_processo(driver, wait)
        resultado["acompanhar_processo_marcado"] = bool(marcado)

        if not marcado:
            raise RuntimeError(
                "Não foi possível confirmar a opção "
                "'Desejo acompanhar este processo'."
            )

        campo, conteudo_anterior = ler_campo()

        resultado["campo_encontrado"] = True
        resultado["conteudo_anterior"] = conteudo_anterior
        resultado["ja_existia"] = bool(
            frase_norm
            and _normalizar_texto_comparacao(conteudo_anterior)
            == frase_norm
        )

        # Até 2 tentativas: preenchimento inicial + 1 retry pós-save.
        for tentativa in range(1, 3):
            resultado["tentativas_preenchimento"] = tentativa

            _, valor_atual = ler_campo()

            if (
                frase_norm
                and _normalizar_texto_comparacao(valor_atual)
                == frase_norm
            ):
                preenchido = True
            else:
                preenchido = preencher_acompanhar_processo(
                    driver,
                    wait,
                    frase,
                )

            resultado["preenchida"] = bool(preenchido)

            if not preenchido:
                if tentativa < 2:
                    print(
                        "[SCH][RETORNO][WARN] Primeira tentativa de "
                        "preenchimento não confirmou. Tentando novamente..."
                    )
                    continue

                raise RuntimeError(
                    "Não foi possível confirmar o preenchimento "
                    "do campo Acompanhar Processo."
                )

            resultado["conteudo_final"] = frase
            resultado["substituida"] = bool(
                conteudo_anterior
                and _normalizar_texto_comparacao(conteudo_anterior)
                != frase_norm
            )

            resultado["salva"] = bool(
                salvar_informacoes_adicionais(driver, wait)
            )

            if not resultado["salva"]:
                if tentativa < 2:
                    continue

                raise RuntimeError(
                    "Não foi possível executar o salvamento "
                    "de Informações Adicionais."
                )

            # Aguarda o AJAX e relê o MESMO campo correto.
            esperar_tela_carregar(driver, 0.8)

            marcado_apos = marcar_acompanhar_processo(
                driver,
                wait,
            )
            resultado["acompanhar_processo_marcado"] = bool(
                marcado_apos
            )

            _, valor_confirmado = ler_campo()
            resultado["conteudo_confirmado"] = valor_confirmado

            resultado["confirmada_apos_salvar"] = bool(
                frase_norm
                and _normalizar_texto_comparacao(valor_confirmado)
                == frase_norm
                and marcado_apos
            )

            if resultado["confirmada_apos_salvar"]:
                break

            if tentativa < 2:
                print(
                    "[SCH][RETORNO][WARN] A frase não persistiu após "
                    "o primeiro Salvar. Repetindo preenchimento e salvamento..."
                )

        if resultado["confirmada_apos_salvar"]:
            resultado["status"] = (
                "frase_ja_existia_salva_e_confirmada"
                if resultado["ja_existia"]
                else "acompanhar_processo_preenchido_salvo_e_confirmado"
            )

            print(
                "[SCH][RETORNO] Acompanhar Processo confirmado: "
                f"'{frase}'"
            )
        else:
            resultado["status"] = "marcacao_nao_confirmada"
            resultado["erro"] = (
                "A frase não permaneceu gravada no campo "
                "Acompanhar Processo após duas tentativas."
            )

        return resultado

    except Exception as e:
        resultado["status"] = "erro"
        resultado["erro"] = str(e)

        print(
            "[SCH][RETORNO][WARN] Não foi possível registrar a frase "
            f"em Acompanhar Processo: {e}"
        )
        return resultado

# =============================================================================
# RETORNO PARA ESTUDO - Comparar Versões
# =============================================================================

def _texto_visivel_atual_sem_travar(driver):
    try:
        return driver.execute_script(
            "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
        ) or ""
    except Exception:
        return ""


def _normalizar_texto_retorno(valor):
    texto = str(valor or "")
    texto = _remover_acentos(texto).lower()
    texto = texto.replace("º", "o")
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"[^a-z0-9.,:/()\- ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto




TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS = [
    "Transceptor de Radiação Restrita",
    "Estação Terminal de Acesso",
    "Dispositivo de Operação Periódica",
    "Sistemas de Identificação por Radiofrequências",
    "Sistema de Identificação por Radiofrequências",
    "Equipamento de Radiocomunicação de Radiação Restrita",
]


def _normalizar_tipo_produto_retorno(valor):
    texto = _normalizar_texto_comparacao(valor)
    texto = texto.replace("radio frequencias", "radiofrequencias")
    texto = texto.replace("radio frequencia", "radiofrequencia")
    texto = texto.replace("radio frequência", "radiofrequencia")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def tipo_produto_retorno_para_estudo_no_escopo(tipo_produto):
    """
    Verifica se o tipo de produto do requerimento está dentro do escopo
    permitido para análise automática de Retorno Para Estudo.
    """

    tipo_norm = _normalizar_tipo_produto_retorno(tipo_produto)

    if not tipo_norm:
        return {
            "no_escopo": False,
            "tipo_produto": str(tipo_produto or "").strip(),
            "motivo": "tipo_produto_nao_identificado",
            "permitidos": TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS,
        }

    permitidos_norm = [
        _normalizar_tipo_produto_retorno(t)
        for t in TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS
    ]

    for permitido_norm, permitido_original in zip(
        permitidos_norm,
        TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS,
    ):
        if tipo_norm == permitido_norm:
            return {
                "no_escopo": True,
                "tipo_produto": str(tipo_produto or "").strip(),
                "tipo_produto_aceito": permitido_original,
                "motivo": "tipo_produto_permitido",
                "permitidos": TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS,
            }

        # Aceita pequenas variações textuais do SCH.
        if permitido_norm in tipo_norm or tipo_norm in permitido_norm:
            return {
                "no_escopo": True,
                "tipo_produto": str(tipo_produto or "").strip(),
                "tipo_produto_aceito": permitido_original,
                "motivo": "tipo_produto_permitido_por_equivalencia",
                "permitidos": TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS,
            }

    return {
        "no_escopo": False,
        "tipo_produto": str(tipo_produto or "").strip(),
        "motivo": "tipo_produto_fora_do_escopo_retorno_para_estudo",
        "permitidos": TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS,
    }


def aplicar_filtro_tipo_produto_retorno_para_estudo(req, resultado):
    """
    Aplica o filtro inicial de escopo por tipo de produto.

    Se o tipo não estiver permitido, bloqueia a aprovação automática
    e encerra a análise como fora de escopo.
    """

    req = req or {}
    resultado = resultado or {}

    tipo_produto = (
        req.get("tipo_produto")
        or req.get("tipo")
        or resultado.get("tipo_produto")
        or ""
    )

    filtro = tipo_produto_retorno_para_estudo_no_escopo(tipo_produto)

    resultado["filtro_tipo_produto_retorno"] = filtro
    resultado["tipo_produto"] = str(tipo_produto or "").strip()

    if filtro.get("no_escopo"):
        resultado["tipo_produto_no_escopo"] = True

        print(
            "[SCH][RETORNO] Tipo de produto dentro do escopo de Retorno Para Estudo: "
            f"{filtro.get('tipo_produto_aceito') or tipo_produto}"
        )

        return True

    resultado["tipo_produto_no_escopo"] = False
    resultado["status_comparacao"] = "fora_escopo_tipo_produto"
    resultado["resultado"] = (
        "Requerimento não analisado automaticamente porque o tipo de produto "
        "não está dentro do escopo configurado para Retorno Para Estudo."
    )
    resultado["acao_recomendada"] = "Não enviar para aprovação / Revisar manualmente"
    resultado["pode_enviar_para_aprovacao"] = False
    resultado["deve_enviar_para_aprovacao"] = False
    resultado["documentos_novos_detectados"] = False
    resultado["documentos_obrigatorios_ok"] = False
    resultado["envio_para_aprovacao"] = {
        "executado": False,
        "motivo": "tipo_produto_fora_do_escopo_retorno_para_estudo",
        "tipo_produto": str(tipo_produto or "").strip(),
    }

    mensagem = (
        "Tipo de produto fora do escopo automático de Retorno Para Estudo: "
        f"{tipo_produto or 'não identificado'}."
    )

    resultado.setdefault("alertas", []).append(mensagem)

    print(f"[SCH][RETORNO][ESCOPO] {mensagem}")
    print(
        "[SCH][RETORNO][ESCOPO] Tipos permitidos: "
        + "; ".join(TIPOS_PRODUTO_RETORNO_PARA_ESTUDO_PERMITIDOS)
    )

    return False

def _lista_unica_retorno(valores):
    saida = []
    vistos = set()

    for valor in valores or []:
        texto = _texto_limpo(valor)
        if not texto:
            continue

        chave = _normalizar_texto_retorno(texto)
        if not chave or chave in vistos:
            continue

        vistos.add(chave)
        saida.append(texto)

    return saida


def _recortar_secao_retorno(texto, titulos_inicio, titulos_fim=None):
    texto = str(texto or "")
    if not texto:
        return ""

    titulos_fim = titulos_fim or []
    texto_norm = _normalizar_texto_retorno(texto)

    inicio_pos = -1
    titulo_encontrado = ""

    for titulo in titulos_inicio or []:
        titulo_norm = _normalizar_texto_retorno(titulo)
        pos = texto_norm.find(titulo_norm)

        if pos >= 0 and (inicio_pos < 0 or pos < inicio_pos):
            inicio_pos = pos
            titulo_encontrado = titulo_norm

    if inicio_pos < 0:
        return ""

    fim_pos = len(texto_norm)

    for titulo in titulos_fim:
        titulo_norm = _normalizar_texto_retorno(titulo)
        pos = texto_norm.find(titulo_norm, inicio_pos + len(titulo_encontrado))

        if pos >= 0 and pos < fim_pos:
            fim_pos = pos

    # Como o texto normalizado muda acentos, mas mantém ordem/tamanho aproximados,
    # fazemos uma segunda extração por linhas no texto original.
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    saida = []
    coletando = False

    for linha in linhas:
        linha_norm = _normalizar_texto_retorno(linha)

        if not coletando and any(_normalizar_texto_retorno(t) in linha_norm for t in titulos_inicio):
            coletando = True

        if coletando:
            if saida and any(_normalizar_texto_retorno(t) in linha_norm for t in titulos_fim):
                break
            saida.append(linha)

    if saida:
        return "\n".join(saida).strip()

    return texto_norm[inicio_pos:fim_pos].strip()


def _extrair_especificacoes_complementares_retorno(texto):
    texto = str(texto or "")
    if not texto:
        return ""

    padroes = [
        r"Especifica[cç][oõ]es\s+Complementares\s*:?\s*(.+?)(?=\n\s*(?:Laborat[oó]rio|Rela[cç][aã]o|Garantias|Dados\s+T[eé]cnicos|$))",
        r"Especificacoes\s+Complementares\s*:?\s*(.+?)(?=\n\s*(?:Laboratorio|Relacao|Garantias|Dados\s+Tecnicos|$))",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" -;:")

    # Fallback linha a linha
    for linha in texto.splitlines():
        if "especific" not in _normalizar_texto_retorno(linha):
            continue
        if "complement" not in _normalizar_texto_retorno(linha):
            continue

        partes = re.split(r":", linha, maxsplit=1)
        if len(partes) == 2:
            return re.sub(r"\s+", " ", partes[1]).strip(" -;:")

        return re.sub(r"\s+", " ", linha).strip()

    return ""



def _remover_especificacoes_do_bloco_dados_tecnicos(texto):
    """
    Remove a parte de 'Especificações Complementares' do bloco
    'Dados Técnicos do Produto'.

    Regra:
    - A tabela técnica continua sendo analisada.
    - Textos complementares como Alimentação, Antena, SAR não aplicável
      e produto não acabado não devem fazer a automação concluir que houve
      alteração real nos Dados Técnicos do Produto.
    """

    texto = str(texto or "")

    if not texto.strip():
        return ""

    texto_limpo = texto.replace("\r", "\n")

    # 1) Remove bloco completo a partir de "Especificações Complementares"
    # até o próximo título relevante da tela de comparação.
    padroes_bloco = [
        r"(?is)(?:^|\n)\s*Especifica[cç][oõ]es\s+Complementares\s*:?.*?(?=\n\s*(?:Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos|Garantias|Dados\s+do\s+Certificado|Outras\s+Unidades|Produto|Solicitante|Fabricante)\b|$)",
        r"(?is)(?:^|\n)\s*Especificacoes\s+Complementares\s*:?.*?(?=\n\s*(?:Laboratorios?|Relacao\s+de\s+Arquivos|Garantias|Dados\s+do\s+Certificado|Outras\s+Unidades|Produto|Solicitante|Fabricante)\b|$)",
    ]

    for padrao in padroes_bloco:
        texto_limpo = re.sub(padrao, "\n", texto_limpo)

    # 2) Fallback para quando o SCH traz tudo em uma linha só.
    # Remove o trecho "Especificações Complementares: ..." até um próximo
    # título conhecido ou até o fim.
    padroes_linha_unica = [
        r"(?is)Especifica[cç][oõ]es\s+Complementares\s*:?.*?(?=(?:Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos|Garantias|Dados\s+do\s+Certificado|Outras\s+Unidades|Solicitante|Fabricante)\b|$)",
        r"(?is)Especificacoes\s+Complementares\s*:?.*?(?=(?:Laboratorios?|Relacao\s+de\s+Arquivos|Garantias|Dados\s+do\s+Certificado|Outras\s+Unidades|Solicitante|Fabricante)\b|$)",
    ]

    for padrao in padroes_linha_unica:
        texto_limpo = re.sub(padrao, " ", texto_limpo)

    # 3) Segurança: remove linhas soltas que normalmente pertencem às
    # Especificações Complementares, caso tenham escapado do recorte.
    termos_apagar = [
        "especificacoes complementares",
        "especificacao complementar",
        "alimentacao:",
        "alimentação:",
        "antena:",
        "ensaio de sar nao aplicavel",
        "ensaio de sar não aplicável",
        "sar nao aplicavel",
        "sar não aplicável",
        "produto nao acabado",
        "produto não acabado",
        "integracao em outro equipamento",
        "integração em outro equipamento",
        "integracao em outros equipamentos",
        "integração em outros equipamentos",
        "pode requerer nova avaliacao",
        "pode requerer nova avaliação",
        "o produto e alimentado pelo host",
        "o produto é alimentado pelo host",
        "produto possui antena integrada",
    ]

    termos_apagar_norm = [
        _normalizar_texto_retorno(t)
        for t in termos_apagar
    ]

    linhas = []

    for linha in texto_limpo.splitlines():
        linha_norm = _normalizar_texto_retorno(linha)

        if any(t and t in linha_norm for t in termos_apagar_norm):
            continue

        linhas.append(linha)

    texto_limpo = "\n".join(linhas)
    texto_limpo = re.sub(r"[ \t]+", " ", texto_limpo)
    texto_limpo = re.sub(r"\n{3,}", "\n\n", texto_limpo)

    return texto_limpo.strip()


def _extrair_documentos_comparar_versoes(texto):
    """
    Extrai documentos SOMENTE da seção/tabela 'Relação de Arquivos Anexos'.

    Não deve capturar texto vermelho de outros blocos, como:
    - Laboratórios
    - Responsável Técnico
    - Garantias
    - Produto
    - Dados Técnicos
    """
    texto = str(texto or "")

    if not texto.strip():
        return []

    linhas = [
        _texto_limpo(linha)
        for linha in texto.replace("\r", "\n").splitlines()
        if _texto_limpo(linha)
    ]

    def _eh_inicio_relacao(linha):
        linha_norm = _normalizar_texto_retorno(linha)
        return (
            "relacao de arquivos anexos" in linha_norm
            or "relação de arquivos anexos" in linha_norm
        )

    def _eh_fim_relacao(linha):
        linha_norm = _normalizar_texto_retorno(linha)

        finais = [
            "garantias",
            "declaracoes",
            "declarações",
            "solicitante declara",
            "historico",
            "histórico",
            "produto",
            "dados tecnicos do produto",
            "dados técnicos do produto",
            "laboratorios",
            "laboratórios",
            "outras unidades fabris",
            "dados do certificado",
        ]

        return any(
            linha_norm == fim or linha_norm.startswith(fim + ":")
            for fim in finais
        )

    def _ignorar_linha_relacao(linha):
        linha_norm = _normalizar_texto_retorno(linha)

        if not linha_norm:
            return True

        ignorar_exatos = {
            "relacao de arquivos anexos",
            "relação de arquivos anexos",
            "nome do arquivo",
            "descricao",
            "descrição",
            "nome do arquivo descricao",
            "nome do arquivo descrição",
        }

        if linha_norm in ignorar_exatos:
            return True

        # Cabeçalhos misturados numa linha só.
        if "nome do arquivo" in linha_norm and "descr" in linha_norm:
            return True

        # Evita que campos de outras seções entrem como documento.
        bloqueios = [
            "responsavel tecnico",
            "responsável técnico",
            "laboratorio",
            "laboratório",
            "email",
            "telefone",
            "endereco",
            "endereço",
            "cidade",
            "bairro",
            "cep",
            "cnpj",
            "cpf/cnpj",
            "solicitante",
            "fabricante",
            "garantia",
            "garantira",
            "declaro que",
            "local e data",
        ]

        if any(b in linha_norm for b in bloqueios):
            return True

        # Linha composta só por nomes de pessoas, comum no bloco Laboratórios.
        # Documento real normalmente contém termos/códigos, PDF, ART, CCT, RACT,
        # fotos, relatório, declaração etc.
        if "," in linha and not _texto_parece_documento_anexo_retorno(linha):
            return True

        if len(linha_norm) <= 2:
            return True

        return False

    bloco = []
    coletando = False

    for linha in linhas:
        if not coletando:
            if _eh_inicio_relacao(linha):
                coletando = True
            continue

        if _eh_fim_relacao(linha):
            break

        if _ignorar_linha_relacao(linha):
            continue

        bloco.append(linha)

    # Fallback para quando o texto vem todo em uma linha só.
    if not bloco:
        plano = re.sub(r"\s+", " ", texto).strip()

        m = re.search(
            r"Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos\s*(?P<bloco>.*?)(?=\s+(?:Garantias|Declara[cç][oõ]es|Solicitante\s+declara|Hist[oó]rico|Laborat[oó]rios?)\b|$)",
            plano,
            flags=re.I | re.S,
        )

        if m:
            trecho = m.group("bloco")

            # Divide antes de categorias comuns da tabela.
            trecho = re.sub(
                r"\s+(ART|Certificado\s+de\s+Conformidade\s+T[eé]cnica\s*-\s*CCT|Fotos\s+do\s+produto|Fotos\s+internas|Manual\s+do\s+Produto|Outros\s*\(OCD\)|Relat[oó]rio\s+de\s+Avalia[cç][aã]o\s+da\s+Conformidade\s*-\s*RACT|Relat[oó]rio\s+de\s+Ensaio|Contrato\s+Social|Selo\s+ANATEL|Cart[aã]o\s+CNPJ|Carta\s+de\s+Representa[cç][aã]o\s+Comercial)\b",
                r"\n\1",
                trecho,
                flags=re.I,
            )

            for linha in trecho.splitlines():
                linha = _texto_limpo(linha)
                if linha and not _ignorar_linha_relacao(linha):
                    bloco.append(linha)

    return _lista_unica_retorno(bloco)


def _eh_cor_vermelha_retorno(cor):
    texto = str(cor or "").strip().lower()

    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", texto)
    if not m:
        return "red" in texto or "#f00" in texto or "#ff0000" in texto

    r, g, b = [int(m.group(i)) for i in range(1, 4)]

    return r >= 150 and g <= 90 and b <= 90


def _coletar_visao_comparar_versoes(driver):
    """
    Coleta textos da tela Comparar Versões.

    Além do texto por lado, captura a tabela real "Relação de Arquivos Anexos"
    por lado. Isso é importante porque documentos novos/removidos devem vir
    somente dessa tabela, e não de outros textos vermelhos da página.
    """
    script = r"""
    const vw = Math.max(
        window.innerWidth || 0,
        document.documentElement ? document.documentElement.clientWidth : 0,
        1
    );

    function normText(txt) {
        return String(txt || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
            .replace(/\s+/g, ' ')
            .trim();
    }

    function visible(el) {
        const st = window.getComputedStyle(el);
        if (!st || st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity || 1) === 0) {
            return false;
        }
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function isRed(color) {
        if (!color) return false;
        const txt = String(color).toLowerCase();
        const m = txt.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (!m) return txt.includes('red') || txt.includes('#f00') || txt.includes('#ff0000');
        const r = Number(m[1]), g = Number(m[2]), b = Number(m[3]);
        return r >= 150 && g <= 90 && b <= 90;
    }

    function sideOf(el) {
        const r = el.getBoundingClientRect();
        return (r.left + (r.width / 2)) < (vw / 2) ? 'esquerda' : 'direita';
    }

    function elementIsRed(el) {
        try {
            const st = window.getComputedStyle(el);
            return isRed((st && st.color) || el.getAttribute('color') || '');
        } catch (e) {
            return false;
        }
    }

    function rowIsRed(tr) {
        try {
            const nodes = [
                tr,
                ...Array.from(tr.querySelectorAll('*'))
            ];

            return nodes.some(el => {
                try {
                    const st = window.getComputedStyle(el);
                    const color =
                        (st && st.color) ||
                        el.getAttribute('color') ||
                        '';

                    return isRed(color);
                } catch (e) {
                    return false;
                }
            });
        } catch (e) {
            return false;
        }
    }

    function clean(txt) {
        return String(txt || '').replace(/\s+/g, ' ').trim();
    }


    function getAttachmentTables() {
        return Array.from(document.querySelectorAll('table'))
            .filter(table => {
                try {
                    if (!visible(table)) return false;

                    const tableText = clean(
                        table.innerText ||
                        table.textContent ||
                        ''
                    );

                    const tableNorm = normText(tableText);

                    return (
                        tableNorm.includes('nome do arquivo') &&
                        tableNorm.includes('descr')
                    );
                } catch (e) {
                    return false;
                }
            })
            .sort((a, b) => {
                const ra = a.getBoundingClientRect();
                const rb = b.getBoundingClientRect();

                return (
                    (ra.left - rb.left) ||
                    (ra.top - rb.top)
                );
            });
    }

    function extractAttachmentRows(sideWanted) {
        const out = [];
        const tables = getAttachmentTables();

        for (let index = 0; index < tables.length; index++) {
            const table = tables[index];

            try {
                let side;

                // Quando as duas tabelas estão no mesmo documento:
                // primeira = versão anterior; segunda = versão nova.
                if (tables.length >= 2) {
                    side = index === 0 ? 'esquerda' : 'direita';
                } else {
                    side = sideOf(table);
                }

                if (side !== sideWanted) continue;

                const trs = Array.from(table.querySelectorAll('tr'));

                for (const tr of trs) {
                    if (!visible(tr)) continue;

                    const cells = Array.from(
                        tr.querySelectorAll('th, td')
                    );

                    const vals = cells
                        .map(c => clean(
                            c.innerText ||
                            c.textContent ||
                            ''
                        ))
                        .filter(Boolean);

                    if (!vals.length) continue;

                    const linhaNorm = normText(vals.join(' '));

                    if (!linhaNorm) continue;

                    if (
                        linhaNorm === 'nome do arquivo descricao' ||
                        (
                            linhaNorm.includes('nome do arquivo') &&
                            linhaNorm.includes('descr')
                        )
                    ) {
                        continue;
                    }

                    const nome = vals[0] || '';
                    const descricao = vals.slice(1).join(' | ') || '';
                    const texto = descricao
                        ? `${nome} | ${descricao}`
                        : nome;

                    if (!texto || normText(texto).length <= 2) {
                        continue;
                    }

                    const r = tr.getBoundingClientRect();

                    out.push({
                        texto: texto,
                        nome: nome,
                        descricao: descricao,
                        red: rowIsRed(tr),
                        side: side,
                        top: r.top + window.scrollY,
                        left: r.left,
                        width: r.width,
                        height: r.height,
                        origem: 'tabela_relacao_arquivos_anexos'
                    });
                }

            } catch (e) {}
        }

        out.sort((a, b) => (a.top - b.top) || (a.left - b.left));

        // Não remover duplicados: uma linha preta pode reaparecer em vermelho.
        return out;
    }

    const nodes = Array.from(document.querySelectorAll('td, th, span, font, div, p, li, label, a, b, strong, legend'));
    const items = [];

    for (const el of nodes) {
        try {
            if (!visible(el)) continue;

            let text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            if (!text || text.length > 700) continue;

            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            const color = st.color || el.getAttribute('color') || '';
            const side = (r.left + (r.width / 2)) < (vw / 2) ? 'esquerda' : 'direita';

            items.push({
                texto: text,
                side: side,
                left: r.left,
                top: r.top + window.scrollY,
                width: r.width,
                height: r.height,
                color: color,
                red: isRed(color),
                tag: el.tagName
            });
        } catch (e) {}
    }

    items.sort((a, b) => (a.top - b.top) || (a.left - b.left));

    function extractProductBlock(sideWanted) {
        const arr = items.filter(x => x.side === sideWanted).sort((a, b) => (a.top - b.top) || (a.left - b.left));

        function isTitleProduct(txt) {
            const n = normText(txt);
            if (!n) return false;
            if (n.includes('nome do produto')) return false;
            if (n.includes('dados tecnicos do produto')) return false;
            if (n.includes('homologacao de produto')) return false;
            if (n.includes('produto para telecomunicacoes')) return false;
            return n === 'produto' || n === 'produto:';
        }

        function isEndProduct(txt) {
            const n = normText(txt);
            return n === 'dados tecnicos do produto' ||
                   n.startsWith('dados tecnicos do produto') ||
                   n === 'laboratorios' || n === 'laboratorio' ||
                   n.startsWith('laboratorios') || n.startsWith('laboratorio') ||
                   n.startsWith('relacao de arquivos anexos') ||
                   n.startsWith('garantias') ||
                   n.startsWith('outras unidades fabris') ||
                   n.startsWith('dados do certificado');
        }

        for (let i = 0; i < arr.length; i++) {
            if (!isTitleProduct(arr[i].texto)) continue;

            const baseTop = arr[i].top;
            const lines = [arr[i].texto];

            for (let j = i + 1; j < arr.length; j++) {
                const it = arr[j];
                if ((it.top - baseTop) > 450) break;
                if (isEndProduct(it.texto)) break;

                const n = normText(it.texto);
                if (n.includes('modelo') || n.includes('tipo') || n.includes('categoria') || n.includes('descontinuado')) {
                    lines.push(it.texto);
                    continue;
                }

                if (lines.length > 1 && it.top > baseTop + 180) break;
            }

            const joined = clean(lines.join('\n'));
            const normJoined = normText(joined);
            if (normJoined.includes('modelo') && (normJoined.includes('tipo') || normJoined.includes('categoria'))) {
                return lines.join('\n');
            }
        }

        // Fallback: procurar diretamente uma sequência Modelo/Tipo/Categoria no texto do lado.
        const sideText = arr.map(x => x.texto).join('\n');
        const flat = clean(sideText);
        const m = flat.match(/Produto\s*:?\s*Modelo\s*:.*?(?=\s+(?:Dados\s+T[eé]cnicos\s+do\s+Produto|Laborat[oó]rios?|Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos|Garantias)\b|$)/i);
        if (m && normText(m[0]).includes('modelo')) {
            return m[0];
        }

        return '';
    }

    function joinSide(side) {
        const seen = new Set();
        const lines = [];
        for (const it of items) {
            if (it.side !== side) continue;
            const key = it.texto;
            if (seen.has(key)) continue;
            seen.add(key);
            lines.push(it.texto);
        }
        return lines.join('\n');
    }

    const docsEsquerda = extractAttachmentRows('esquerda');
    const docsDireita = extractAttachmentRows('direita');

    return {
        url: String(window.location.href || ''),
        title: String(document.title || ''),
        texto_total: document.body ? (document.body.innerText || document.body.textContent || '') : '',
        texto_esquerda: joinSide('esquerda'),
        texto_direita: joinSide('direita'),
        vermelhos_esquerda: items.filter(x => x.side === 'esquerda' && x.red),
        vermelhos_direita: items.filter(x => x.side === 'direita' && x.red),
        documentos_anexos_esquerda: docsEsquerda,
        documentos_anexos_direita: docsDireita,
        documentos_anexos_vermelhos_esquerda: docsEsquerda.filter(x => x.red),
        documentos_anexos_vermelhos_direita: docsDireita.filter(x => x.red),
        produto_esquerda: extractProductBlock('esquerda'),
        produto_direita: extractProductBlock('direita')
    };
    """

    try:
        return driver.execute_script(script) or {}
    except Exception:
        return {}



def _capturar_comparar_versoes(driver, wait=None, timeout=45):
    """
    Captura a tela Comparar Versões sem exigir leituras consecutivas iguais.

    Assim que as tabelas de anexos dos dois lados forem localizadas, a captura
    é aceita imediatamente. O tempo restante é usado apenas quando a página
    ainda não disponibilizou uma captura completa.
    """
    inicio = time.time()
    melhor_captura = {}
    melhor_pontuacao = -1
    tentativa = 0

    def pontuacao(cap):
        if not isinstance(cap, dict):
            return -1

        docs_esquerda = cap.get("documentos_anexos_esquerda", []) or []
        docs_direita = cap.get("documentos_anexos_direita", []) or []
        vermelhos_esquerda = cap.get("documentos_anexos_vermelhos_esquerda", []) or []
        vermelhos_direita = cap.get("documentos_anexos_vermelhos_direita", []) or []

        texto = " ".join([
            str(cap.get("texto_total", "")),
            str(cap.get("texto_esquerda", "")),
            str(cap.get("texto_direita", "")),
        ])
        texto_norm = _normalizar_texto_retorno(texto)

        pontos = 0
        pontos += len(docs_esquerda) * 100
        pontos += len(docs_direita) * 100
        pontos += len(vermelhos_direita) * 10000
        pontos += len(vermelhos_esquerda) * 5000

        if "relacao de arquivos anexos" in texto_norm:
            pontos += 100
        if "dados tecnicos" in texto_norm:
            pontos += 50
        if "requerimento para homologacao" in texto_norm:
            pontos += 25

        return pontos

    while time.time() - inicio < timeout:
        tentativa += 1
        capturas = []

        try:
            driver.switch_to.default_content()
            cap = _coletar_visao_comparar_versoes(driver)
            if isinstance(cap, dict):
                cap["_contexto_captura"] = "documento_principal"
                capturas.append(cap)
        except Exception:
            pass

        try:
            entrar_iframe_detalhe_analise(driver, wait)
            cap = _coletar_visao_comparar_versoes(driver)
            if isinstance(cap, dict):
                cap["_contexto_captura"] = "iframe_detalhe"
                capturas.append(cap)
        except Exception:
            pass

        try:
            driver.switch_to.default_content()
            quantidade_frames = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))

            for indice in range(quantidade_frames):
                try:
                    driver.switch_to.default_content()
                    frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")

                    if indice >= len(frames):
                        continue

                    driver.switch_to.frame(frames[indice])
                    cap = _coletar_visao_comparar_versoes(driver)

                    if isinstance(cap, dict):
                        cap["_contexto_captura"] = f"iframe_direto_{indice}"
                        capturas.append(cap)
                except Exception:
                    continue
        except Exception:
            pass

        # A primeira captura que contiver as tabelas dos dois lados é aceita.
        # Não há uma segunda leitura para confirmar estabilidade da página.
        for cap in capturas:
            pontos = pontuacao(cap)

            if pontos > melhor_pontuacao:
                melhor_pontuacao = pontos
                melhor_captura = cap

            docs_esquerda = cap.get("documentos_anexos_esquerda", []) or []
            docs_direita = cap.get("documentos_anexos_direita", []) or []

            if docs_esquerda and docs_direita:
                cap["_captura_completa"] = True
                cap["_tentativas_captura"] = tentativa
                cap["_tempo_captura_segundos"] = round(time.time() - inicio, 2)

                print(
                    "[SCH][RETORNO][CAPTURA] "
                    f"tentativa={tentativa} | "
                    f"contexto={cap.get('_contexto_captura', '')} | "
                    f"anexos_esquerda={len(docs_esquerda)} | "
                    f"anexos_direita={len(docs_direita)} | "
                    "captura_completa=SIM"
                )

                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

                return cap

        docs_esquerda = melhor_captura.get("documentos_anexos_esquerda", []) or []
        docs_direita = melhor_captura.get("documentos_anexos_direita", []) or []
        vermelhos_direita = melhor_captura.get("documentos_anexos_vermelhos_direita", []) or []

        print(
            "[SCH][RETORNO][CAPTURA] "
            f"tentativa={tentativa} | "
            f"contexto={melhor_captura.get('_contexto_captura', '')} | "
            f"anexos_esquerda={len(docs_esquerda)} | "
            f"anexos_direita={len(docs_direita)} | "
            f"anexos_vermelhos_direita={len(vermelhos_direita)} | "
            "captura_completa=NÃO"
        )

        time.sleep(0.5)

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    melhor_captura["_captura_completa"] = bool(
        melhor_captura.get("documentos_anexos_esquerda")
        and melhor_captura.get("documentos_anexos_direita")
    )
    melhor_captura["_tentativas_captura"] = tentativa
    melhor_captura["_tempo_captura_segundos"] = round(time.time() - inicio, 2)

    print(
        "[SCH][RETORNO][WARN] A captura da comparação terminou sem localizar "
        "as tabelas de anexos dos dois lados. Será usada a melhor captura disponível."
    )

    return melhor_captura


def _texto_pagina_com_iframes(driver):
    """
    Coleta texto do documento principal e de todos os iframes acessíveis.
    A tela de Comparar Versões pode carregar dentro de iframe diferente do __frameDetalhe.
    """
    textos = []

    def coletar_no_contexto():
        try:
            texto = driver.execute_script(
                "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
            ) or ""
            if texto.strip():
                textos.append(texto)
        except Exception:
            pass

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    coletar_no_contexto()

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        iframes = []

    for iframe in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(iframe)
            coletar_no_contexto()
        except Exception:
            continue

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    return "\n".join(textos)


def _eh_tela_real_comparacao_versoes(driver, wait=None):
    """
    Confirma se a tela real de comparação de versões carregou.
    A comparação pode abrir em nova aba, na mesma aba ou dentro de iframe.
    """
    try:
        texto = _texto_pagina_com_iframes(driver)
    except Exception:
        texto = ""

    texto_norm = _normalizar_texto_comparacao(texto)

    if not texto_norm:
        return False

    # Se ainda está no modal, não é a comparação.
    if "selecionar requerimento" in texto_norm and "comparar versao" in texto_norm:
        return False

    sinais = [
        "requerimento para homologacao",
        "dados tecnicos do produto",
        "dados tecnicos",
        "especificacoes complementares",
        "relacao de arquivos anexos",
        "solicitante",
        "fabricante",
    ]

    qtd_sinais = sum(1 for sinal in sinais if sinal in texto_norm)

    if qtd_sinais >= 3:
        return True

    # Na comparação lado a lado, alguns títulos aparecem duplicados.
    if (
        texto_norm.count("requerimento para homologacao") >= 2
        or texto_norm.count("dados tecnicos do produto") >= 2
        or texto_norm.count("dados tecnicos") >= 2
        or texto_norm.count("relacao de arquivos anexos") >= 2
    ):
        return True

    return False



def _pagina_proxy_error_sch(driver):
    """
    Detecta erro temporário do SCH/Proxy na página de Comparar Versões.

    Exemplo visual:
    - Proxy Error
    - The proxy server received an invalid response from an upstream server
    - Reason: Error reading from remote server
    """

    try:
        url = str(driver.current_url or "").lower()
    except Exception:
        url = ""

    try:
        texto = _texto_pagina_com_iframes(driver)
    except Exception:
        texto = ""

    texto_lower = str(texto or "").lower()
    texto_norm = _normalizar_texto_comparacao(texto)

    sinais = [
        "proxy error",
        "invalid response from an upstream server",
        "error reading from remote server",
        "the proxy server could not handle the request",
        "bad gateway",
        "gateway timeout",
        "service unavailable",
    ]

    if any(sinal in texto_lower for sinal in sinais):
        return True

    if any(_normalizar_texto_comparacao(sinal) in texto_norm for sinal in sinais):
        return True

    if "compareversoesrequerimento.xhtml" in url and "proxy" in texto_lower:
        return True

    return False


def _instalar_captura_popup_comparacao_retorno(driver, wait=None):
    """
    Instala um monitor no contexto do SCH para capturar a URL que o PrimeFaces
    tenta abrir em window.open/abrirPopup(args). Isso ajuda quando a aba abre
    como about:blank.
    """
    script = """
    (function () {
        function pickUrl(args) {
            try {
                if (!args) return '';
                if (typeof args === 'string') return args;

                var keys = [
                    'url', 'URL', 'href', 'link', 'caminho', 'path',
                    'pagina', 'page', 'src', 'view', 'targetUrl'
                ];

                for (var i = 0; i < keys.length; i++) {
                    var k = keys[i];
                    if (args[k] && typeof args[k] === 'string') {
                        return args[k];
                    }
                }

                for (var p in args) {
                    try {
                        if (typeof args[p] === 'string') {
                            var v = args[p];
                            if (
                                v.indexOf('/') >= 0 ||
                                v.indexOf('mosaico') >= 0 ||
                                v.indexOf('compar') >= 0 ||
                                v.indexOf('requerimento') >= 0
                            ) {
                                return v;
                            }
                        }
                    } catch (e) {}
                }
            } catch (e) {}
            return '';
        }

        function absolutizar(url) {
            try {
                if (!url) return '';
                return new URL(url, window.location.href).href;
            } catch (e) {
                return url || '';
            }
        }

        window.__sch_popup_comparacao = {
            instalado: true,
            url: '',
            args: '',
            windowOpenUrl: '',
            windowOpenTarget: '',
            erros: []
        };

        if (!window.__sch_window_open_wrapped) {
            window.__sch_original_window_open = window.open;

            window.open = function (url, target, features) {
                try {
                    window.__sch_popup_comparacao.windowOpenUrl = absolutizar(url || '');
                    window.__sch_popup_comparacao.windowOpenTarget = target || '';

                    if (url) {
                        window.__sch_popup_comparacao.url = absolutizar(url);
                    }
                } catch (e) {
                    try {
                        window.__sch_popup_comparacao.erros.push(String(e));
                    } catch (e2) {}
                }

                return window.__sch_original_window_open.apply(window, arguments);
            };

            window.__sch_window_open_wrapped = true;
        }

        if (typeof window.abrirPopup === 'function' && !window.__sch_abrir_popup_wrapped) {
            window.__sch_original_abrirPopup = window.abrirPopup;

            window.abrirPopup = function (args) {
                try {
                    var url = pickUrl(args);
                    window.__sch_popup_comparacao.args = JSON.stringify(args || {});

                    if (url) {
                        window.__sch_popup_comparacao.url = absolutizar(url);
                    }
                } catch (e) {
                    try {
                        window.__sch_popup_comparacao.erros.push(String(e));
                    } catch (e2) {}
                }

                return window.__sch_original_abrirPopup.apply(this, arguments);
            };

            window.__sch_abrir_popup_wrapped = true;
        }

        return window.__sch_popup_comparacao;
    })();
    """

    for usar_iframe in [True, False]:
        try:
            if usar_iframe:
                entrar_iframe_detalhe_analise(driver, wait)
            else:
                driver.switch_to.default_content()

            info = driver.execute_script(script) or {}

            if isinstance(info, dict) and info.get("instalado"):
                return True

        except Exception:
            continue

    return False


def _obter_popup_comparacao_capturado(driver, wait=None):
    """
    Lê a URL capturada pelo monitor instalado antes do clique.
    """
    script = "return window.__sch_popup_comparacao || {};"

    melhor = {}

    for usar_iframe in [True, False]:
        try:
            if usar_iframe:
                entrar_iframe_detalhe_analise(driver, wait)
            else:
                driver.switch_to.default_content()

            info = driver.execute_script(script) or {}

            if not isinstance(info, dict):
                continue

            url = str(info.get("url") or info.get("windowOpenUrl") or "").strip()

            if url and url.lower() not in {
                "about:blank",
                "about:blank#blocked",
                "undefined",
                "null",
            }:
                return info

            if info and not melhor:
                melhor = info

        except Exception:
            continue

    return melhor


def _clicar_elemento_por_cdp(driver, elemento):
    """
    Clique mais próximo de um clique real do Chrome/Edge.
    Se o elemento estiver dentro de iframe, soma a posição do iframe para
    clicar nas coordenadas corretas da janela principal.
    """
    try:
        rect = driver.execute_script(
            """
            var el = arguments[0];
            var r = el.getBoundingClientRect();
            var x = r.left + (r.width / 2);
            var y = r.top + (r.height / 2);

            try {
                if (window.frameElement) {
                    var fr = window.frameElement.getBoundingClientRect();
                    x += fr.left;
                    y += fr.top;
                }
            } catch (e) {}

            return {x: x, y: y};
            """,
            elemento,
        )

        x = float(rect["x"])
        y = float(rect["y"])

        driver.switch_to.default_content()

        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
                "clickCount": 0,
            },
        )

        time.sleep(0.15)

        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )

        time.sleep(0.15)

        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )

        return True

    except Exception:
        return False


def _clicar_botao_comparar_versao_modal(driver, wait):
    """
    Clica no botão interno 'Comparar Versão' usando o mesmo comando
    que funcionou no DevTools:

    document.getElementById("formAnalise:j_idt10:j_idt26").click()
    """

    id_botao = "formAnalise:j_idt10:j_idt26"

    try:
        entrar_iframe_detalhe_analise(driver, wait)
    except Exception:
        pass

    print("[SCH][RETORNO] Clicando no botão interno 'Comparar Versão' via DOM click...")

    try:
        WebDriverWait(driver, 20, poll_frequency=0.2).until(
            lambda d: d.execute_script(
                """
                var el = document.getElementById(arguments[0]);

                if (!el) return false;

                var style = window.getComputedStyle(el);

                return (
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    !el.disabled
                );
                """,
                id_botao,
            )
        )

        driver.execute_script(
            """
            var el = document.getElementById(arguments[0]);

            if (!el) {
                throw new Error("Botão Comparar Versão não encontrado pelo ID.");
            }

            el.scrollIntoView({block:'center', inline:'center'});
            el.focus();
            el.click();

            try {
                el.blur();
            } catch(e) {}

            return true;
            """,
            id_botao,
        )

        print("[SCH][RETORNO] DOM click executado no botão interno 'Comparar Versão'.")
        return True

    except Exception as e:
        print(f"[SCH][RETORNO][WARN] DOM click no botão interno falhou: {e}")
        return False


def _corrigir_url_comparacao_sch(driver, url):
    """
    Corrige URL capturada pelo popup do SCH.

    O SCH pode retornar:
    - http://sistemasnet/mosaico/...
    - https://sistemasnet/mosaico/...
    - sistemasnet/mosaico/...
    - /mosaico/sch/publicView/compare/...
    """

    url = str(url or "").strip()

    if not url:
        return ""

    url = url.replace("\\", "/")
    url_lower = url.lower()

    if url_lower.startswith("http://sistemasnet/"):
        return url.replace(
            "http://sistemasnet/",
            "https://sistemasnet.anatel.gov.br/",
            1,
        )

    if url_lower.startswith("https://sistemasnet/"):
        return url.replace(
            "https://sistemasnet/",
            "https://sistemasnet.anatel.gov.br/",
            1,
        )

    if url_lower.startswith("sistemasnet/"):
        resto = url.split("/", 1)[1] if "/" in url else ""
        return "https://sistemasnet.anatel.gov.br/" + resto

    if url.startswith("/"):
        return "https://sistemasnet.anatel.gov.br" + url

    if (
        "mosaico/sch/publicview/compare/compareversoesrequerimento.xhtml"
        in url_lower
        and not url_lower.startswith("http")
    ):
        if url_lower.startswith("mosaico/"):
            return "https://sistemasnet.anatel.gov.br/" + url
        return "https://sistemasnet.anatel.gov.br/" + url.lstrip("/")

    return url





def _descricao_elemento_acao_retorno(elemento):
    """
    Monta uma descrição curta de um botão/ícone da linha do Retorno Para Estudo.
    Serve para escolher o ícone correto e também para deixar o terminal mais claro.
    """
    partes = []

    for attr in ["title", "alt", "aria-label", "onclick", "href", "src", "class", "id"]:
        try:
            valor = elemento.get_attribute(attr)
            if valor:
                partes.append(f"{attr}={valor}")
        except Exception:
            pass

    try:
        imgs = elemento.find_elements(By.XPATH, ".//img")
        for img in imgs:
            for attr in ["title", "alt", "src", "class", "id"]:
                try:
                    valor = img.get_attribute(attr)
                    if valor:
                        partes.append(f"img_{attr}={valor}")
                except Exception:
                    pass
    except Exception:
        pass

    try:
        texto = _texto_limpo(elemento.text)
        if texto:
            partes.append(f"text={texto}")
    except Exception:
        pass

    return " | ".join(partes)


def abrir_requerimento_retorno_para_estudo(driver, wait, req, indice_icone=2):
    """
    Abre o requerimento da fila Retorno Para Estudo clicando no ícone de ação da linha.

    Pelo caminho validado por print, o ícone correto é o verde, normalmente o 2º ícone
    de ação da linha. A função primeiro tenta identificar por atributos fortes; se não
    conseguir, usa indice_icone=2 como fallback seguro.
    """
    numero = req.get("requerimento", "") if isinstance(req, dict) else str(req or "")
    print(f"[SCH][RETORNO] Abrindo requerimento {numero} pelo ícone de ação...")

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    linha = _localizar_linha_requerimento_na_fila(driver, req)

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        linha,
    )

    candidatos = linha.find_elements(
        By.XPATH,
        ".//a[.//img] | .//img/ancestor::a[1] | .//button | .//*[@role='button']"
    )

    candidatos_unicos = []
    vistos = set()

    for el in candidatos:
        try:
            chave = el.id
        except Exception:
            chave = None

        if chave and chave in vistos:
            continue

        if chave:
            vistos.add(chave)

        try:
            if el.is_displayed() and el.is_enabled():
                candidatos_unicos.append(el)
        except Exception:
            continue

    if not candidatos_unicos:
        raise Exception(
            f"Não encontrei ícones/botões clicáveis na linha do requerimento {numero}."
        )

    print(f"[SCH][RETORNO] {len(candidatos_unicos)} ícone(s) de ação encontrados na linha.")

    melhor = None
    melhor_pontuacao = -1

    for idx, el in enumerate(candidatos_unicos, start=1):
        desc = _descricao_elemento_acao_retorno(el)
        desc_norm = _normalizar_texto_comparacao(desc)

        print(f"[SCH][RETORNO] Ícone {idx}: {desc[:300]}")

        pontuacao = 0

        termos_fortes = [
            "analisar",
            "analise",
            "editar",
            "abrir",
            "visualizar",
            "detalhar",
            "requerimento",
            "homologacao",
            "homologacao produto",
        ]

        for termo in termos_fortes:
            if termo in desc_norm:
                pontuacao += 10

        termos_ruins = [
            "excluir",
            "cancelar",
            "remover",
            "delete",
            "historico",
            "history",
        ]

        for termo in termos_ruins:
            if termo in desc_norm:
                pontuacao -= 50

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor = el

    # Fallback principal: pelo print enviado, o botão correto é o 2º ícone verde da linha.
    if melhor_pontuacao <= 0:
        pos = max(1, int(indice_icone)) - 1

        if pos < len(candidatos_unicos):
            melhor = candidatos_unicos[pos]
            print(f"[SCH][RETORNO] Usando fallback pelo índice do ícone: {indice_icone}.")
        else:
            melhor = candidatos_unicos[0]
            print("[SCH][RETORNO] Índice solicitado não existe. Usando primeiro ícone clicável.")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        melhor,
    )

    try:
        ActionChains(driver).move_to_element(melhor).pause(0.2).click().perform()
    except Exception:
        _clicar_com_fallback(driver, melhor)

    esperar_tela_carregar(driver, 0.8)

    _aguardar_iframe_detalhe(driver, timeout=8)

    print("[SCH][RETORNO] Requerimento aberto com sucesso.")
    return True


def executar_caminho_retorno_para_estudo_teste(
    driver,
    wait,
    regras,
    pasta_saida=None,
    pasta_download=None,
    categorias_baixar=None,
    requerimento_alvo=None,
    abrir_comparacao=True,
):
    """
    Executa somente o caminho de navegação do Retorno Para Estudo.

    Não analisa ainda os dois documentos. Esta função serve para validar se os cliques
    estão corretos antes de partir para a análise lado esquerdo x lado direito.

    Fluxo:
    1. Abre SCH.
    2. Entra em Retorno Para Estudo.
    3. Abre o requerimento pelo ícone verde da linha.
    4. Entra em Anexos.
    5. Baixa somente as categorias informadas pelo usuário, se houver.
    6. Volta para Dados Gerais.
    7. Clica em Comparar Versões.
    8. Clica no botão do modal Comparar Versão.
    9. Aguarda a nova aba dos dois documentos.
    """
    resultado = {
        "status": "iniciado",
        "requerimento": "",
        "anexos": [],
        "comparacao": {},
        "erro": "",
    }

    try:
        abrir_sch(driver)
        garantir_sessao_ativa_sch(
            driver,
            wait,
            contexto="início do caminho Retorno Para Estudo",
            reabrir_fila=False,
        )

        clicar_fila_retorno_para_estudo(driver, wait)

        requerimentos = coletar_requerimentos(driver, wait, regras)

        if not requerimentos:
            raise Exception("Nenhum requerimento encontrado em Retorno Para Estudo.")

        req = None

        if requerimento_alvo:
            alvo_digitos = _somente_digitos(str(requerimento_alvo))

            for item in requerimentos:
                if _somente_digitos(item.get("requerimento", "")) == alvo_digitos:
                    req = item
                    break

            if not req:
                raise Exception(
                    f"Requerimento alvo {requerimento_alvo} não encontrado na fila."
                )
        else:
            req = requerimentos[0]

        resultado["requerimento"] = req.get("requerimento", "")

        abrir_requerimento_retorno_para_estudo(
            driver,
            wait,
            req,
            indice_icone=2,
        )

        clicar_aba_anexos(driver, wait)

        categorias_baixar = categorias_baixar or []

        if categorias_baixar:
            if not pasta_saida or not pasta_download:
                raise Exception(
                    "Para baixar anexos, informe pasta_saida e pasta_download."
                )

            for categoria in categorias_baixar:
                clicar_categoria_anexo(driver, wait, categoria)

                anexos_categoria = baixar_anexos_da_categoria_atual(
                    driver=driver,
                    wait=wait,
                    req=req,
                    pasta_saida=pasta_saida,
                    pasta_download=pasta_download,
                    categoria=categoria,
                )

                resultado["anexos"].extend(anexos_categoria)
        else:
            print(
                "[SCH][RETORNO] Nenhuma categoria de anexo informada para download. "
                "Apenas validando o caminho."
            )

        # Para ficar igual ao caminho validado: antes de Comparar Versões, volta para Dados Gerais.
        clicar_aba_dados_gerais(driver, wait)

        if abrir_comparacao:
            info_comparacao = clicar_comparar_versoes(driver, wait)
            resultado["comparacao"] = info_comparacao

            print(
                "[SCH][RETORNO] Caminho até a tela de comparação concluído. "
                f"URL: {info_comparacao.get('url_comparacao', '')}"
            )

        resultado["status"] = "ok"
        return resultado

    except Exception as e:
        resultado["status"] = "erro"
        resultado["erro"] = str(e)

        print(f"[SCH][RETORNO][ERRO] Falha no caminho Retorno Para Estudo: {e}")

        return resultado



def _aguardar_primefaces_estavel_no_iframe(driver, wait=None, timeout=60):
    inicio = time.time()
    estavel_seguidas = 0

    while time.time() - inicio < timeout:
        try:
            entrar_iframe_detalhe_analise(driver, wait)

            info = driver.execute_script(
                """
                var jq = null;
                var pf = null;

                try {
                    jq = window.jQuery ? window.jQuery.active : 0;
                } catch (e) {
                    jq = 0;
                }

                try {
                    if (window.PrimeFaces && PrimeFaces.ajax && PrimeFaces.ajax.Queue) {
                        pf = PrimeFaces.ajax.Queue.isEmpty();
                    } else {
                        pf = true;
                    }
                } catch (e) {
                    pf = true;
                }

                return {
                    jqueryActive: jq,
                    pfQueueEmpty: pf,
                    ok: (jq === 0 && pf === true)
                };
                """
            ) or {}

            if info.get("ok"):
                estavel_seguidas += 1
                if estavel_seguidas >= 3:
                    print("[SCH][RETORNO] Ajax/PrimeFaces do iframe estabilizado.")
                    return True
            else:
                estavel_seguidas = 0
                print(
                    "[SCH][RETORNO] Aguardando Ajax do iframe: "
                    f"jqueryActive={info.get('jqueryActive')} | "
                    f"pfQueueEmpty={info.get('pfQueueEmpty')}"
                )

        except Exception as e:
            estavel_seguidas = 0
            print(f"[SCH][RETORNO][WARN] Não consegui ler estado Ajax do iframe: {e}")

        time.sleep(0.8)

    print("[SCH][RETORNO][WARN] Timeout aguardando Ajax/PrimeFaces do iframe.")
    return False



def _clicar_botao_interno_comparar_versao_robusto(driver, wait, tentativas=8):
    """
    Clica no botão interno "Comparar Versão" preservando o comportamento
    real do navegador.

    O popup do SCH é sensível à forma do clique. Um ``element.click()``
    disparado dentro de JavaScript pode abrir somente ``about:blank``.
    Por isso, o clique físico/nativo é sempre tentado antes do JavaScript.
    """
    ultimo_erro = None

    xpaths = [
        "//*[@id='formAnalise:j_idt10:j_idt26']",
        "//button[normalize-space(.)='Comparar Versão']",
        "//a[normalize-space(.)='Comparar Versão']",
        "//input[normalize-space(@value)='Comparar Versão']",
        "//span[normalize-space(.)='Comparar Versão']/ancestor::*[self::button or self::a][1]",
    ]

    for tentativa in range(1, tentativas + 1):
        botao = None

        try:
            print(
                f"[SCH][RETORNO] Tentando clique nativo em 'Comparar Versão' "
                f"- tentativa {tentativa}/{tentativas}"
            )

            for contexto in ("iframe", "default"):
                try:
                    if contexto == "iframe":
                        entrar_iframe_detalhe_analise(driver, wait)
                    else:
                        driver.switch_to.default_content()
                except Exception:
                    continue

                for xpath in xpaths:
                    try:
                        elementos = driver.find_elements(By.XPATH, xpath)
                    except Exception:
                        elementos = []

                    for el in elementos:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                botao = el
                                break
                        except Exception:
                            continue

                    if botao is not None:
                        break

                if botao is not None:
                    break

            if botao is None:
                ultimo_erro = "botao_interno_nao_encontrado"
                time.sleep(0.35)
                continue

            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                botao,
            )
            time.sleep(0.2)

            try:
                ActionChains(driver).move_to_element(botao).pause(0.2).click().perform()
                print(
                    "[SCH][RETORNO] Clique físico executado no botão interno "
                    "'Comparar Versão'."
                )
                return True
            except Exception as e_action:
                ultimo_erro = e_action

            try:
                botao.click()
                print(
                    "[SCH][RETORNO] Clique nativo do WebElement executado no "
                    "botão interno 'Comparar Versão'."
                )
                return True
            except Exception as e_native:
                ultimo_erro = e_native

            try:
                driver.execute_script(
                    """
                    arguments[0].scrollIntoView({block:'center', inline:'center'});
                    arguments[0].focus();
                    arguments[0].click();
                    """,
                    botao,
                )
                print(
                    "[SCH][RETORNO][WARN] Clique JavaScript usado somente como "
                    "último fallback em 'Comparar Versão'."
                )
                return True
            except Exception as e_js:
                ultimo_erro = e_js

        except Exception as e:
            ultimo_erro = e

        time.sleep(0.45)

    raise Exception(
        "Não foi possível clicar no botão interno 'Comparar Versão'. "
        f"Último erro: {ultimo_erro}"
    )


def clicar_comparar_versoes(driver, wait, timeout_resultado=240):
    """
    Fluxo Retorno Para Estudo:

    1. Clica no botão superior "Comparar Versões".
    2. Confirma o modal "Selecionar Requerimento" pelo texto OU pelo botão interno.
    3. Instala captura da URL do popup.
    4. Clica no botão interno "Comparar Versão".
    5. Espera a aba aberta pelo próprio SCH.
    6. Carrega a URL capturada nessa mesma aba via CDP, sem criar nova aba.
    7. Confirma se a tela real de comparação carregou.
    """

    print("[SCH][RETORNO] Clicando no botão superior 'Comparar Versões'...")

    try:
        aba_origem = driver.current_window_handle
    except Exception:
        aba_origem = None

    def _normalizar_comp_local(valor):
        try:
            return _normalizar_texto_comparacao(valor)
        except Exception:
            return str(valor or "").lower().strip()

    def _contextos_comparacao():
        """Tenta default content e iframe de detalhe, preservando robustez."""
        yield "default"
        yield "iframe"

    def _ir_contexto(nome):
        try:
            if nome == "iframe":
                entrar_iframe_detalhe_analise(driver, wait)
            else:
                driver.switch_to.default_content()
            return True
        except Exception:
            return False

    def _elemento_clicavel(el):
        try:
            return el.is_displayed() and el.is_enabled()
        except Exception:
            return False

    def _localizar_botao_superior():
        xpaths_botao_superior = [
            "//button[normalize-space()='Comparar Versões']",
            "//a[normalize-space()='Comparar Versões']",
            "//input[@type='button' and normalize-space(@value)='Comparar Versões']",
            "//input[@type='submit' and normalize-space(@value)='Comparar Versões']",
            "//span[normalize-space()='Comparar Versões']/ancestor::button[1]",
            "//span[normalize-space()='Comparar Versões']/ancestor::a[1]",
            "//*[self::a or self::button][normalize-space()='Comparar Versões']",
            "//*[self::a or self::button or self::input][contains(normalize-space(), 'Comparar Versões') or contains(@value, 'Comparar Versões')]",
            "//*[contains(normalize-space(), 'Comparar Versões')]/ancestor::*[self::a or self::button][1]",
        ]

        ultimo_erro = None

        for contexto in _contextos_comparacao():
            if not _ir_contexto(contexto):
                continue

            for xpath in xpaths_botao_superior:
                try:
                    elementos = driver.find_elements(By.XPATH, xpath)

                    for el in elementos:
                        try:
                            if not _elemento_clicavel(el):
                                continue

                            texto_el = " ".join(
                                [
                                    el.text or "",
                                    el.get_attribute("value") or "",
                                    el.get_attribute("title") or "",
                                    el.get_attribute("aria-label") or "",
                                ]
                            )

                            texto_norm = _normalizar_comp_local(texto_el)

                            # Evita confundir com o botão interno singular do modal.
                            if "comparar versao" in texto_norm and "comparar versoes" not in texto_norm:
                                continue

                            return el

                        except Exception as e:
                            ultimo_erro = e
                            continue

                except Exception as e:
                    ultimo_erro = e
                    continue

        if ultimo_erro:
            print(f"[SCH][RETORNO][WARN] Último erro localizando botão superior: {ultimo_erro}")

        return None

    def _texto_contexto_atual():
        try:
            return driver.execute_script(
                """
                return document.body
                    ? (document.body.innerText || document.body.textContent || '')
                    : '';
                """
            ) or ""
        except Exception:
            return ""

    def _modal_por_texto():
        for contexto in _contextos_comparacao():
            if not _ir_contexto(contexto):
                continue

            texto_norm = _normalizar_comp_local(_texto_contexto_atual())

            if (
                "selecionar requerimento" in texto_norm
                and "comparar versao" in texto_norm
            ):
                return True

        return False

    def _localizar_botao_interno_comparar():
        id_botao_interno = "formAnalise:j_idt10:j_idt26"

        xpaths_interno = [
            f"//*[@id='{id_botao_interno}']",
            "//button[normalize-space()='Comparar Versão']",
            "//a[normalize-space()='Comparar Versão']",
            "//input[normalize-space(@value)='Comparar Versão']",
            "//span[normalize-space()='Comparar Versão']/ancestor::button[1]",
            "//span[normalize-space()='Comparar Versão']/ancestor::a[1]",
            "//*[self::a or self::button][contains(normalize-space(), 'Comparar Versão')]",
            "//input[contains(@value, 'Comparar Versão')]",
        ]

        for contexto in ["iframe", "default"]:
            if not _ir_contexto(contexto):
                continue

            # Primeiro tenta o ID validado no DevTools.
            try:
                el = driver.execute_script(
                    "return document.getElementById(arguments[0]);",
                    id_botao_interno,
                )

                if el is not None and _elemento_clicavel(el):
                    return el
            except Exception:
                pass

            for xpath in xpaths_interno:
                try:
                    elementos = driver.find_elements(By.XPATH, xpath)

                    for el in elementos:
                        try:
                            if _elemento_clicavel(el):
                                return el
                        except Exception:
                            continue

                except Exception:
                    continue

        return None

    def _modal_ou_botao_interno_disponivel():
        if _modal_por_texto():
            return True

        return _localizar_botao_interno_comparar() is not None

    def _clicar_botao_superior_com_retry():
        ultimo_erro = None

        for tentativa in range(1, 5):
            botao = _localizar_botao_superior()

            if not botao:
                ultimo_erro = "botao_superior_nao_encontrado"
                print(
                    f"[SCH][RETORNO][WARN] Botão superior 'Comparar Versões' não encontrado "
                    f"na tentativa {tentativa}/4."
                )
                esperar_tela_carregar(driver, 0.8)
                continue

            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    botao,
                )
                time.sleep(0.2)

                try:
                    ActionChains(driver).move_to_element(botao).pause(0.15).click().perform()
                except Exception:
                    try:
                        botao.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", botao)

                esperar_tela_carregar(driver, 1.0)

                print(f"[SCH][RETORNO] Clique superior executado. Tentativa {tentativa}/4.")
                print("[SCH][RETORNO] Aguardando modal 'Selecionar Requerimento'...")

                inicio = time.time()
                while time.time() - inicio < 12:
                    if _modal_ou_botao_interno_disponivel():
                        return True
                    time.sleep(0.3)

                print(
                    "[SCH][RETORNO][WARN] Modal ainda não detectado após clique superior. "
                    "Tentando novamente..."
                )
                ultimo_erro = "modal_nao_detectado_apos_clique"

            except Exception as e:
                ultimo_erro = e
                print(
                    f"[SCH][RETORNO][WARN] Falha no clique superior tentativa {tentativa}/4: {e}"
                )
                esperar_tela_carregar(driver, 0.8)

        raise Exception(
            "Cliquei em 'Comparar Versões', mas o modal 'Selecionar Requerimento' "
            f"não apareceu. Último erro: {ultimo_erro}"
        )

    def _clicar_botao_interno_comparar():
        botao_interno = _localizar_botao_interno_comparar()

        if not botao_interno:
            raise Exception("Botão interno 'Comparar Versão' não encontrado no modal.")

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                botao_interno,
            )
            time.sleep(0.2)
        except Exception:
            pass

        try:
            driver.execute_script(
                """
                var el = arguments[0];
                el.focus();
                el.click();
                try { el.blur(); } catch(e) {}
                return true;
                """,
                botao_interno,
            )
            print("[SCH][RETORNO] DOM click executado no botão interno 'Comparar Versão'.")
            return True

        except Exception as e_js:
            print(f"[SCH][RETORNO][WARN] DOM click no botão interno falhou: {e_js}")

        try:
            ActionChains(driver).move_to_element(botao_interno).pause(0.15).click().perform()
            print("[SCH][RETORNO] Clique físico executado no botão interno 'Comparar Versão'.")
            return True
        except Exception as e_action:
            raise Exception(
                f"Falha ao clicar no botão interno 'Comparar Versão': {e_action}"
            )

    _clicar_botao_superior_com_retry()

    print("[SCH][RETORNO] Modal detectado.")
    print("[SCH][RETORNO] Instalando captura da URL de comparação...")

    try:
        handles_antes_modal = set(driver.window_handles)
    except Exception:
        handles_antes_modal = set()

    try:
        _instalar_captura_popup_comparacao_retorno(driver, wait)
        print("[SCH][RETORNO] Captura de popup instalada.")
    except Exception as e:
        print(f"[SCH][RETORNO][WARN] Não foi possível instalar captura do popup: {e}")

    print("[SCH][RETORNO] Preparando clique DOM no botão interno 'Comparar Versão'...")

    _clicar_botao_interno_comparar_versao_robusto(driver, wait)

    print("[SCH][RETORNO] Clique interno executado. Capturando URL da comparação...")

    url_comparacao_resolvida = ""

    try:
        try:
            if (
                aba_origem
                and aba_origem in driver.window_handles
                and driver.current_window_handle != aba_origem
            ):
                driver.switch_to.window(aba_origem)
        except Exception:
            pass

        for _ in range(40):
            info_popup = _obter_popup_comparacao_capturado(driver, wait) or {}

            url_bruta = (
                info_popup.get("url")
                or info_popup.get("windowOpenUrl")
                or ""
            )

            url_comparacao_resolvida = _corrigir_url_comparacao_sch(
                driver,
                url_bruta,
            )

            if url_comparacao_resolvida:
                print(
                    "[SCH][RETORNO] URL da comparação capturada: "
                    f"{url_comparacao_resolvida}"
                )
                break

            time.sleep(0.25)

    except Exception as e:
        print(f"[SCH][RETORNO][WARN] Falha ao capturar URL da comparação: {e}")

    print("[SCH][RETORNO] Aguardando aba aberta pelo SCH...")

    nova_aba = None
    inicio_abertura = time.time()

    while time.time() - inicio_abertura < 60:
        try:
            handles_agora = set(driver.window_handles)

            novas = [
                h for h in handles_agora
                if h not in handles_antes_modal
            ]

            if novas:
                nova_aba = novas[-1]
                print("[SCH][RETORNO] Nova aba aberta pelo SCH detectada.")
                break

        except Exception:
            pass

        time.sleep(0.5)

    if not nova_aba:
        raise Exception(
            "Cliquei em 'Comparar Versão', mas nenhuma nova aba foi detectada."
        )

    try:
        driver.switch_to.window(nova_aba)
    except Exception as e:
        raise Exception(
            f"Nova aba foi detectada, mas não consegui alternar para ela: {e}"
        )

    print("[SCH][RETORNO] Aguardando carregamento da aba de comparação...")

    def _url_atual_segura():
        try:
            return str(driver.current_url or "").strip()
        except Exception:
            return ""

    def _navegar_url_capturada_na_aba_atual():
        """
        Carrega a URL capturada na própria aba que o SCH abriu.
        Não cria nova aba e não usa driver.get().
        """
        if not url_comparacao_resolvida:
            return False

        print(
            "[SCH][RETORNO] Carregando URL capturada na própria aba aberta pelo SCH..."
        )

        try:
            driver.execute_cdp_cmd("Page.stopLoading", {})
        except Exception:
            pass

        time.sleep(0.3)

        try:
            driver.execute_cdp_cmd(
                "Page.navigate",
                {"url": url_comparacao_resolvida},
            )

            print("[SCH][RETORNO] Navegação CDP enviada para a aba do SCH.")
            return True

        except Exception as e:
            texto_erro = str(e).lower()

            if (
                "read timed out" in texto_erro
                or "timed out receiving message from renderer" in texto_erro
                or "timeout" in texto_erro
            ):
                print(
                    "[SCH][RETORNO][WARN] ChromeDriver deu timeout ao enviar "
                    "a navegação, mas a página pode continuar carregando. Vou aguardar."
                )
                return True

            print("[SCH][RETORNO][WARN] Page.navigate falhou sem timeout conhecido.")
            return False

    url_forcada_na_mesma_aba = False

    if url_comparacao_resolvida:
        url_forcada_na_mesma_aba = _navegar_url_capturada_na_aba_atual()
        time.sleep(3.0)

    inicio_carregamento = time.time()
    avisou_blank = False
    avisou_url = False
    inicio_blank = None

    while time.time() - inicio_carregamento < timeout_resultado:
        try:
            try:
                if nova_aba in driver.window_handles:
                    driver.switch_to.window(nova_aba)
            except Exception:
                pass

            try:
                if _pagina_proxy_error_sch(driver):
                    raise Exception(
                        "Proxy Error detectado ao abrir Comparar Versões. "
                        "Erro temporário do SCH/servidor da Anatel. "
                        "A automação não deve analisar nem aprovar este requerimento nesta tentativa."
                    )

                if _eh_tela_real_comparacao_versoes(driver, wait):
                    esperar_tela_carregar(driver, 2)

                    print("[SCH][RETORNO] Página de comparação carregada com sucesso.")

                    url_final = _url_atual_segura() or url_comparacao_resolvida

                    return {
                        "abriu": True,
                        "aba_origem": aba_origem,
                        "aba_atual": driver.current_window_handle,
                        "nova_aba": True,
                        "url_comparacao": url_final,
                        "url_capturada": url_comparacao_resolvida,
                    }

            except Exception as e:
                if "Proxy Error detectado" in str(e):
                    raise

                if url_comparacao_resolvida and not url_forcada_na_mesma_aba:
                    url_forcada_na_mesma_aba = _navegar_url_capturada_na_aba_atual()
                    time.sleep(3.0)
                    continue

            url_atual = _url_atual_segura()
            url_norm = url_atual.lower()

            if url_norm in {"", "about:blank"}:
                if inicio_blank is None:
                    inicio_blank = time.time()

                if not avisou_blank:
                    print("[SCH][RETORNO] Aba ainda em about:blank.")
                    avisou_blank = True

                if url_comparacao_resolvida and not url_forcada_na_mesma_aba:
                    url_forcada_na_mesma_aba = _navegar_url_capturada_na_aba_atual()
                    time.sleep(2.0)
                    continue

                tempo_blank = time.time() - inicio_blank

                # Não deixa a automação parada por minutos em uma aba vazia.
                # Sem URL capturada, 12 s de about:blank já caracteriza falha.
                # Com URL capturada/navegação tentada, tolera até 25 s.
                limite_blank = 25 if url_comparacao_resolvida else 12

                if tempo_blank >= limite_blank:
                    print(
                        "[SCH][RETORNO][WARN] Comparar Versões permaneceu em "
                        f"about:blank por {tempo_blank:.1f}s. Abortando esta "
                        "comparação e retornando ao requerimento."
                    )

                    try:
                        if nova_aba in driver.window_handles:
                            driver.close()
                    except Exception:
                        pass

                    try:
                        if aba_origem and aba_origem in driver.window_handles:
                            driver.switch_to.window(aba_origem)
                    except Exception:
                        pass

                    raise RuntimeError(
                        "Comparar Versões abriu somente about:blank. "
                        "A comparação foi interrompida para não travar o fluxo."
                    )

            else:
                inicio_blank = None

                if not avisou_url:
                    print(f"[SCH][RETORNO] URL atual da aba de comparação: {url_atual}")
                    avisou_url = True

            if url_norm not in {"", "about:blank"} and not avisou_url:
                print(f"[SCH][RETORNO] URL atual da aba de comparação: {url_atual}")
                avisou_url = True

            time.sleep(0.7)

        except Exception as e:
            erro_loop = str(e)

            if (
                "Proxy Error detectado" in erro_loop
                or "Comparar Versões abriu somente about:blank" in erro_loop
            ):
                raise

            print(f"[SCH][RETORNO][WARN] Erro aguardando aba de comparação: {e}")
            time.sleep(0.7)

    raise Exception(
        "A aba de comparação abriu, mas a página não carregou dentro do tempo limite."
    )

def restaurar_tela_requerimento_apos_comparacao(
    driver,
    wait,
    aba_original_sch=None,
    info_abertura=None,
    timeout=15,
):
    """
    Encerra Comparar Versões e retorna de forma determinística ao requerimento.

    A função percorre as abas somente uma vez:
    - fecha a aba conhecida de comparação;
    - fecha abas órfãs about:blank;
    - volta à aba original do SCH;
    - entra novamente no iframe __frameDetalhe;
    - confirma o botão exato "Corrigir Minuta".
    """
    info_abertura = info_abertura or {}

    aba_original = (
        aba_original_sch
        or info_abertura.get("aba_origem")
    )

    aba_comparacao = (
        info_abertura.get("aba_atual")
        or info_abertura.get("aba_comparacao")
    )

    try:
        handles = list(driver.window_handles)
    except Exception:
        handles = []

    if not handles:
        raise RuntimeError(
            "Nenhuma aba disponível para restaurar o requerimento."
        )

    if not aba_original:
        # Quando a comparação já foi fechada anteriormente, a aba atual deve
        # ser a aba original do SCH.
        try:
            aba_original = driver.current_window_handle
        except Exception:
            aba_original = handles[0]

    fechadas = []

    for handle in list(handles):
        if handle == aba_original:
            continue

        deve_fechar = handle == aba_comparacao

        try:
            driver.switch_to.window(handle)
            url = str(driver.current_url or "").strip().lower()

            if not url or url.startswith("about:blank"):
                deve_fechar = True

            if (
                "comparar" in url
                or "comparacao" in url
                or "comparação" in url
            ):
                deve_fechar = True

            if deve_fechar:
                driver.close()
                fechadas.append(handle)

        except Exception:
            continue

    try:
        handles_restantes = list(driver.window_handles)
    except Exception:
        handles_restantes = []

    if aba_original not in handles_restantes:
        raise RuntimeError(
            "A aba original do SCH não está mais aberta."
        )

    driver.switch_to.window(aba_original)
    driver.switch_to.default_content()
    esperar_tela_carregar(driver, 0.6, timeout=8)

    def _requerimento_pronto(d):
        try:
            entrar_iframe_detalhe_analise(d, wait)
        except Exception:
            return False

        xpaths = [
            "//button[normalize-space(.)='Corrigir Minuta']",
            "//a[normalize-space(.)='Corrigir Minuta']",
            "//input[normalize-space(@value)='Corrigir Minuta']",
            "//span[normalize-space(.)='Corrigir Minuta']/ancestor::*[self::button or self::a][1]",
        ]

        for xpath in xpaths:
            try:
                if any(
                    el.is_displayed()
                    for el in d.find_elements(By.XPATH, xpath)
                ):
                    return True
            except Exception:
                continue

        return False

    WebDriverWait(
        driver,
        timeout,
        poll_frequency=0.2,
    ).until(_requerimento_pronto)

    print(
        "[SCH][RETORNO] Tela do requerimento restaurada após "
        "Comparar Versões."
    )

    return {
        "restaurado": True,
        "aba_original_sch": aba_original,
        "abas_fechadas": len(fechadas),
        "handles_fechados": fechadas,
    }


def _fechar_comparacao_se_abriu_nova_aba(driver, info_abertura):
    """
    Compatibilidade com chamadas antigas.
    """
    try:
        resultado = restaurar_tela_requerimento_apos_comparacao(
            driver=driver,
            wait=None,
            aba_original_sch=(
                info_abertura.get("aba_origem")
                if isinstance(info_abertura, dict)
                else None
            ),
            info_abertura=info_abertura,
        )
        return bool(resultado.get("restaurado"))
    except Exception as e:
        print(
            "[SCH][RETORNO][WARN] Não foi possível restaurar a tela "
            f"do requerimento: {e}"
        )
        return False



def _montar_alteracao_retorno(campo, anterior, novo):
    return {
        "campo": campo,
        "anterior": str(anterior or "").strip(),
        "novo": str(novo or "").strip(),
    }


def _texto_parece_documento_anexo_retorno(texto):
    texto_norm = _normalizar_texto_retorno(texto)

    if not texto_norm:
        return False

    termos_documento = [
        "art",
        "cct",
        "certificado de conformidade tecnica",
        "ract",
        "relatorio de avaliacao da conformidade",
        "relatorio de ensaio",
        "manual",
        "foto",
        "fotos",
        "declaracao",
        "decl",
        "contrato social",
        "selo anatel",
        "carta de representacao",
        "outros",
        "ocd",
        "maintenance",
        "maintenance declaration",
        "declaration of maintenance",
        ".pdf",
        "_nov",
        "_m1",
        "_01a",
        "_2a",
    ]

    return any(t in texto_norm for t in termos_documento)


def _texto_parece_alteracao_tecnica_retorno(texto):
    texto_norm = _normalizar_texto_retorno(texto)

    if not texto_norm:
        return False

    termos_tecnicos = [
        "dados tecnicos do produto",
        "especificacoes complementares",
        "especificacao complementar",
        "tensao",
        "tensao de entrada",
        "tensao de saida",
        "corrente",
        "potencia",
        "frequencia",
        "faixa de frequencia",
        "faixa de frequencias",
        "mhz",
        "ghz",
        "w",
        "vdc",
        "vac",
        "usb",
        "modelo",
        "nome comercial",
        "carregador",
        "produto",
        "categoria",
    ]

    return any(t in texto_norm for t in termos_tecnicos)


def _extrair_textos_vermelhos_por_lado_retorno(captura, lado="direita"):
    chave = "vermelhos_direita" if lado == "direita" else "vermelhos_esquerda"

    saida = []

    for item in captura.get(chave, []) or []:
        if isinstance(item, dict):
            texto = item.get("texto", "")
        else:
            texto = str(item or "")

        texto = _texto_limpo(texto)

        if texto:
            saida.append(texto)

    return _lista_unica_retorno(saida)


def _normalizar_dados_tecnicos_para_comparacao_retorno(texto):
    """
    Normaliza Dados Técnicos para evitar falso positivo quando o OCD apenas
    reescreve a mesma especificação elétrica com unidades/formatos diferentes.

    Exemplo tratado como equivalente:
    - 5,0 VDC (3,0 A) == 5V/3A
    - 9,0 VDC (2,77 A) == 9V/2,77A
    - 3,3 VDC - 11,0 VDC (2,25 A) == 3,3V - 11V / 2,25A
    - VDC/VCC/VAC/VCA são normalizados para V quando a comparação é de grandeza.
    """
    texto = _normalizar_texto_retorno(texto)

    if not texto:
        return ""

    texto = texto.replace("dados tecnicos do produto", " ")
    texto = texto.replace("especificacoes complementares", " ")
    texto = texto.replace("especificacao complementar", " ")

    texto = re.sub(r"(\d),(\d)", r"\1.\2", texto)

    # Unidades equivalentes no contexto da comparação de especificações.
    texto = re.sub(r"\bvca\b|\bvac\b|\bvcc\b|\bvdc\b", "v", texto)

    # Frequência de rede e termos comerciais não devem bloquear sozinhos.
    texto = re.sub(r"\b\d+\s*-\s*\d+\s*hz\b", " ", texto)
    texto = re.sub(r"\b(pdo|pps|usb|type|tipo|carregador|saida|entrada|tensao|com|uma|um|01|1|de|da|do|e|ou)\b", " ", texto)

    # Remove espaços em faixas e entre número/unidade.
    texto = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", texto)
    texto = re.sub(r"(\d)\s+(v|a|ma|w|kw|hz|khz|mhz|ghz)", r"\1\2", texto)

    # 5.0v -> 5v | 3.0a -> 3a | 11.0v -> 11v
    texto = re.sub(r"(?<!\d)(\d+)\.0+(?=(v|a|ma|w|kw|hz|khz|mhz|ghz|\b))", r"\1", texto)

    texto = texto.replace(";", " ")
    texto = texto.replace(":", " ")
    texto = texto.replace(",", " ")
    texto = texto.replace("/", " ")
    texto = texto.replace("(", " ").replace(")", " ")

    texto = re.sub(r"[^a-z0-9\.\-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto



def _comparar_blocos_dados_tecnicos_retorno(texto_antigo, texto_novo):
    dados_antigos = _recortar_secao_retorno(
        texto_antigo,
        ["Dados Técnicos do Produto", "Dados Tecnicos do Produto"],
        [
            "Laboratório",
            "Laboratorio",
            "Relação de Arquivos Anexos",
            "Relacao de Arquivos Anexos",
            "Garantias",
        ],
    )

    dados_novos = _recortar_secao_retorno(
        texto_novo,
        ["Dados Técnicos do Produto", "Dados Tecnicos do Produto"],
        [
            "Laboratório",
            "Laboratorio",
            "Relação de Arquivos Anexos",
            "Relacao de Arquivos Anexos",
            "Garantias",
        ],
    )

    espec_antiga = _extrair_especificacoes_complementares_retorno(
        dados_antigos or texto_antigo
    )

    espec_nova = _extrair_especificacoes_complementares_retorno(
        dados_novos or texto_novo
    )

    dados_antigos_sem_espec = _remover_especificacoes_do_bloco_dados_tecnicos(
        dados_antigos
    )

    dados_novos_sem_espec = _remover_especificacoes_do_bloco_dados_tecnicos(
        dados_novos
    )

    alteracoes_dados_tecnicos = []
    alteracoes_especificacoes = []

    norm_dados_antigos = _normalizar_dados_tecnicos_para_comparacao_retorno(
        dados_antigos_sem_espec
    )

    norm_dados_novos = _normalizar_dados_tecnicos_para_comparacao_retorno(
        dados_novos_sem_espec
    )

    norm_espec_antiga = _normalizar_dados_tecnicos_para_comparacao_retorno(
        espec_antiga
    )

    norm_espec_nova = _normalizar_dados_tecnicos_para_comparacao_retorno(
        espec_nova
    )

    if norm_dados_antigos != norm_dados_novos:
        if dados_antigos_sem_espec or dados_novos_sem_espec:
            alteracoes_dados_tecnicos.append(
                _montar_alteracao_retorno(
                    "Dados Técnicos do Produto",
                    dados_antigos_sem_espec,
                    dados_novos_sem_espec,
                )
            )

    # Especificações Complementares são registradas à parte.
    # Elas não entram em "alteracoes" para não bloquear a aprovação automática
    # como se fossem alteração real da tabela/dados técnicos principais.
    if norm_espec_antiga != norm_espec_nova:
        if espec_antiga or espec_nova:
            alteracoes_especificacoes.append(
                _montar_alteracao_retorno(
                    "Especificações Complementares",
                    espec_antiga,
                    espec_nova,
                )
            )

    return {
        "dados_antigos": dados_antigos,
        "dados_novos": dados_novos,
        "dados_antigos_sem_especificacoes": dados_antigos_sem_espec,
        "dados_novos_sem_especificacoes": dados_novos_sem_espec,
        "especificacoes_antigas": espec_antiga,
        "especificacoes_novas": espec_nova,
        "normalizado_dados_antigos": norm_dados_antigos,
        "normalizado_dados_novos": norm_dados_novos,
        "normalizado_especificacoes_antigas": norm_espec_antiga,
        "normalizado_especificacoes_novas": norm_espec_nova,

        # Mantido para compatibilidade: aqui ficam SOMENTE alterações técnicas reais.
        "alteracoes": alteracoes_dados_tecnicos,
        "alterado": bool(alteracoes_dados_tecnicos),

        # Campo separado para relatório.
        "alteracoes_especificacoes_complementares": alteracoes_especificacoes,
        "especificacoes_complementares_alteradas": bool(alteracoes_especificacoes),
    }


def _texto_documento_anexo_capturado_retorno(item):
    """
    Converte uma linha capturada da tabela Relação de Arquivos Anexos em texto.
    Aceita tanto strings quanto dicionários vindos do JavaScript.
    """
    if isinstance(item, dict):
        nome = _texto_limpo(item.get("nome") or "")
        descricao = _texto_limpo(item.get("descricao") or "")
        texto = _texto_limpo(item.get("texto") or "")

        if nome and descricao:
            return f"{nome} | {descricao}"

        return texto or nome or descricao

    return _texto_limpo(item)


def _lista_docs_capturados_tabela_retorno(valores, somente_vermelhos=False):
    docs = []

    for item in valores or []:
        if somente_vermelhos and isinstance(item, dict) and not item.get("red"):
            continue

        texto = _texto_documento_anexo_capturado_retorno(item)

        if not texto:
            continue

        docs.append(texto)

    return _lista_unica_retorno(docs)


def _comparar_documentos_anexos_retorno(
    texto_antigo,
    texto_novo,
    vermelhos_direita,
    vermelhos_esquerda,
    docs_tabela_esquerda=None,
    docs_tabela_direita=None,
    docs_tabela_vermelhos_esquerda=None,
    docs_tabela_vermelhos_direita=None,
):
    """
    Compara somente a seção/tabela 'Relação de Arquivos Anexos'.

    Remoção só é considerada confirmada quando está associada ao lado antigo
    da tabela. Diferenças puramente textuais são registradas como inconclusivas,
    evitando afirmar que uma alteração técnica ou um documento incluído foi
    removido.
    """
    documentos_antigos_tabela = _lista_docs_capturados_tabela_retorno(
        docs_tabela_esquerda,
        somente_vermelhos=False,
    )
    documentos_novos_tabela = _lista_docs_capturados_tabela_retorno(
        docs_tabela_direita,
        somente_vermelhos=False,
    )

    documentos_antigos = (
        documentos_antigos_tabela
        or _extrair_documentos_comparar_versoes(texto_antigo)
    )
    documentos_novos = (
        documentos_novos_tabela
        or _extrair_documentos_comparar_versoes(texto_novo)
    )

    adicionados_por_vermelho_tabela = _lista_docs_capturados_tabela_retorno(
        docs_tabela_vermelhos_direita,
        somente_vermelhos=False,
    ) or _lista_docs_capturados_tabela_retorno(
        docs_tabela_direita,
        somente_vermelhos=True,
    )

    removidos_por_vermelho_tabela = _lista_docs_capturados_tabela_retorno(
        docs_tabela_vermelhos_esquerda,
        somente_vermelhos=False,
    ) or _lista_docs_capturados_tabela_retorno(
        docs_tabela_esquerda,
        somente_vermelhos=True,
    )

    set_antigos = {
        _normalizar_texto_retorno(x)
        for x in documentos_antigos
        if _normalizar_texto_retorno(x)
    }
    set_novos = {
        _normalizar_texto_retorno(x)
        for x in documentos_novos
        if _normalizar_texto_retorno(x)
    }

    adicionados_por_diff = [
        x for x in documentos_novos
        if _normalizar_texto_retorno(x) not in set_antigos
    ]
    removidos_por_diff = [
        x for x in documentos_antigos
        if _normalizar_texto_retorno(x) not in set_novos
    ]

    set_adicionados_diff = {
        _normalizar_texto_retorno(x)
        for x in adicionados_por_diff
        if _normalizar_texto_retorno(x)
    }
    set_removidos_diff = {
        _normalizar_texto_retorno(x)
        for x in removidos_por_diff
        if _normalizar_texto_retorno(x)
    }

    vermelhos_docs_direita_na_relacao = []
    for item in vermelhos_direita or []:
        texto = _texto_documento_anexo_capturado_retorno(item)
        texto_norm = _normalizar_texto_retorno(texto)
        if texto_norm and texto_norm in set_adicionados_diff:
            vermelhos_docs_direita_na_relacao.append(texto)

    vermelhos_docs_esquerda_na_relacao = []
    for item in vermelhos_esquerda or []:
        texto = _texto_documento_anexo_capturado_retorno(item)
        texto_norm = _normalizar_texto_retorno(texto)
        if texto_norm and texto_norm in set_removidos_diff:
            vermelhos_docs_esquerda_na_relacao.append(texto)

    tem_tabelas_dom = bool(documentos_antigos_tabela and documentos_novos_tabela)

    # Inclusões podem usar a linha vermelha do lado novo ou, quando a tabela foi
    # capturada por completo, a diferença entre as listas.
    docs_adicionados = _lista_unica_retorno(
        adicionados_por_vermelho_tabela
        or vermelhos_docs_direita_na_relacao
        or adicionados_por_diff
    )

    # Exclusões exigem evidência do lado antigo. O simples desaparecimento de
    # uma linha em captura textual/possivelmente parcial não basta.
    docs_removidos = _lista_unica_retorno(
        removidos_por_vermelho_tabela
        or vermelhos_docs_esquerda_na_relacao
    )

    norm_rem_confirmados = {
        _normalizar_texto_retorno(x)
        for x in docs_removidos
        if _normalizar_texto_retorno(x)
    }
    removidos_inconclusivos = _lista_unica_retorno([
        x for x in removidos_por_diff
        if _normalizar_texto_retorno(x) not in norm_rem_confirmados
    ])

    norm_add = {
        _normalizar_texto_retorno(x)
        for x in docs_adicionados
        if _normalizar_texto_retorno(x)
    }
    norm_rem = {
        _normalizar_texto_retorno(x)
        for x in docs_removidos
        if _normalizar_texto_retorno(x)
    }

    if norm_add and norm_add == norm_rem:
        removidos_inconclusivos = _lista_unica_retorno(
            removidos_inconclusivos + docs_removidos
        )
        docs_removidos = []
        norm_rem = set()

    if docs_removidos:
        confianca_remocao = "alta"
        metodo_remocao = "linha_vermelha_lado_antigo"
    elif removidos_inconclusivos:
        confianca_remocao = "inconclusiva"
        metodo_remocao = "diferenca_sem_confirmacao_visual"
    else:
        confianca_remocao = "sem_indicio"
        metodo_remocao = "nenhuma_remocao_identificada"

    return {
        "documentos_antigos": documentos_antigos,
        "documentos_novos": documentos_novos,
        "documentos_adicionados": docs_adicionados,
        "documentos_removidos": docs_removidos,
        "documentos_removidos_inconclusivos": removidos_inconclusivos,
        "tem_documento_adicionado": bool(docs_adicionados),
        "tem_documento_removido": bool(docs_removidos),
        "tem_remocao_inconclusiva": bool(removidos_inconclusivos),
        "remocao_confirmada": bool(docs_removidos),
        "confianca_remocao": confianca_remocao,
        "metodo_remocao": metodo_remocao,
        "origem_documentos": (
            "tabela_dom_relacao_arquivos_anexos"
            if tem_tabelas_dom
            else "texto_recortado_relacao_arquivos_anexos"
        ),
        "captura_tabelas_completa": tem_tabelas_dom,
        "qtd_linhas_tabela_antiga": len(documentos_antigos_tabela),
        "qtd_linhas_tabela_nova": len(documentos_novos_tabela),
        "qtd_linhas_vermelhas_tabela_nova": len(adicionados_por_vermelho_tabela),
        "qtd_linhas_vermelhas_tabela_antiga": len(removidos_por_vermelho_tabela),
    }



def _normalizar_bloco_para_comparacao_retorno(texto):
    texto = _normalizar_texto_retorno(texto)

    if not texto:
        return ""

    texto = texto.replace(":", " ")
    texto = texto.replace(";", " ")
    texto = texto.replace(",", " ")
    texto = texto.replace(".", " ")
    texto = texto.replace("/", " ")

    texto = re.sub(r"[^a-z0-9\-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def _formatar_bloco_produto_retorno(bloco):
    bloco = str(bloco or "").strip()

    if not bloco:
        return ""

    bloco = re.sub(r"\s+", " ", bloco).strip()

    bloco = re.sub(
        r"^\s*Produto\s*:?\s*",
        "Produto:\n",
        bloco,
        flags=re.I,
    )

    bloco = re.sub(r"\s+(Modelo\s*:)", r"\n\1", bloco, flags=re.I)
    bloco = re.sub(r"\s+(Tipo\s*:)", r"\n\1", bloco, flags=re.I)
    bloco = re.sub(r"\s+(Categoria\s*:)", r"\n\1", bloco, flags=re.I)

    linhas = [
        linha.strip()
        for linha in bloco.splitlines()
        if linha.strip()
    ]

    return "\n".join(linhas).strip()


def _recortar_bloco_produto_retorno(texto):
    """
    Recorta somente a seção real:

    Produto:
    Modelo: ...
    Modelo: ...
    Tipo: ...
    Categoria: ...

    Ignora ocorrências como:
    - Nome do Produto
    - Dados Técnicos do Produto
    - REQUERIMENTO PARA HOMOLOGAÇÃO DE PRODUTO...
    """
    texto = str(texto or "").replace("\r", "\n")

    if not texto.strip():
        return ""

    texto = re.sub(r"[ \t]+", " ", texto)

    def _eh_titulo_produto_isolado(linha):
        linha_norm = _normalizar_texto_retorno(linha)

        if not linha_norm:
            return False

        bloqueios = [
            "nome do produto",
            "dados tecnicos do produto",
            "homologacao de produto",
            "produto para telecomunicacoes",
            "requerimento para homologacao de produto",
        ]

        if any(b in linha_norm for b in bloqueios):
            return False

        return bool(re.fullmatch(r"produto\s*:?", linha_norm))

    def _eh_fim_bloco_produto(linha):
        linha_norm = _normalizar_texto_retorno(linha)

        finais = [
            "dados tecnicos do produto",
            "dados tecnicos",
            "especificacoes complementares",
            "laboratorio",
            "relacao de arquivos anexos",
            "garantias",
            "declaracoes",
            "solicitante declara",
            "historico",
            "outras unidades fabris",
            "dados do certificado",
        ]

        return any(
            re.fullmatch(rf"{re.escape(fim)}\s*:?", linha_norm)
            for fim in finais
        )

    # Tentativa 1: texto com quebras de linha.
    linhas = [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip()
    ]

    for idx, linha in enumerate(linhas):
        if not _eh_titulo_produto_isolado(linha):
            continue

        bloco = [linha]

        for prox in linhas[idx + 1:]:
            if _eh_fim_bloco_produto(prox):
                break

            prox_norm = _normalizar_texto_retorno(prox)

            # Mantém somente linhas realmente relacionadas ao Produto.
            if (
                "modelo" in prox_norm
                or "tipo" in prox_norm
                or "categoria" in prox_norm
                or "descontinuado" in prox_norm
            ):
                bloco.append(prox)
                continue

            # Se já coletou algo útil e encontrou linha estranha, encerra.
            if len(bloco) > 1:
                break

        bloco_txt = "\n".join(bloco).strip()
        bloco_norm = _normalizar_texto_retorno(bloco_txt)

        if "modelo" in bloco_norm and (
            "tipo" in bloco_norm or "categoria" in bloco_norm
        ):
            return _formatar_bloco_produto_retorno(bloco_txt)

    # Tentativa 2: texto veio todo em uma linha só.
    plano = re.sub(r"\s+", " ", texto).strip()

    padrao = re.compile(
        r"(Produto\s*:?\s*Modelo\s*:.*?)(?=\s+"
        r"(?:Dados\s+T[eé]cnicos\s+do\s+Produto|Dados\s+Tecnicos\s+do\s+Produto|"
        r"Dados\s+T[eé]cnicos|Dados\s+Tecnicos|"
        r"Especifica[cç][oõ]es\s+Complementares|Especificacoes\s+Complementares|"
        r"Laborat[oó]rio|Laboratorio|"
        r"Rela[cç][aã]o\s+de\s+Arquivos\s+Anexos|Relacao\s+de\s+Arquivos\s+Anexos|"
        r"Garantias|Declara[cç][oõ]es|Declaracoes|"
        r"Solicitante\s+declara|Hist[oó]rico|Historico|"
        r"Outras\s+Unidades\s+Fabris)"
        r"\b|$)",
        flags=re.I | re.S,
    )

    m = padrao.search(plano)

    if m:
        bloco_txt = m.group(1).strip()
        bloco_norm = _normalizar_texto_retorno(bloco_txt)

        if "modelo" in bloco_norm and (
            "tipo" in bloco_norm or "categoria" in bloco_norm
        ):
            return _formatar_bloco_produto_retorno(bloco_txt)

    return ""


def _normalizar_produto_para_comparacao_retorno(texto):
    texto = _normalizar_texto_retorno(texto)

    if not texto:
        return ""

    texto = texto.replace("produto", " ")
    texto = texto.replace("modelo s", "modelo")
    texto = texto.replace("modelo:", "modelo ")
    texto = texto.replace("tipo:", "tipo ")
    texto = texto.replace("categoria:", "categoria ")

    texto = re.sub(r"\bdescontinuado\b", " ", texto)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def _comparar_bloco_produto_retorno(texto_antigo, texto_novo):
    produto_antigo = _recortar_bloco_produto_retorno(texto_antigo)
    produto_novo = _recortar_bloco_produto_retorno(texto_novo)

    norm_antigo = _normalizar_produto_para_comparacao_retorno(produto_antigo)
    norm_novo = _normalizar_produto_para_comparacao_retorno(produto_novo)

    captura_incompleta = not produto_antigo or not produto_novo

    alterado = captura_incompleta or norm_antigo != norm_novo

    alteracoes = []

    if alterado:
        if captura_incompleta:
            alteracoes.append(
                {
                    "campo": "Produto",
                    "anterior": produto_antigo or "Produto não identificado com segurança na versão anterior.",
                    "novo": produto_novo or "Produto não identificado com segurança na versão nova.",
                }
            )
        else:
            alteracoes.append(
                _montar_alteracao_retorno(
                    "Produto",
                    produto_antigo,
                    produto_novo,
                )
            )

    return {
        "produto_antigo": produto_antigo,
        "produto_novo": produto_novo,
        "normalizado_antigo": norm_antigo,
        "normalizado_novo": norm_novo,
        "captura_incompleta": captura_incompleta,
        "alterado": alterado,
        "alteracoes": alteracoes,
    }


def _comparar_bloco_unidade_fabril_retorno(texto_antigo, texto_novo):
    unidade_antiga = _recortar_secao_retorno(
        texto_antigo,
        ["Outras Unidades Fabris", "Unidades Fabris"],
        [
            "Dados do Certificado",
            "Produto",
            "Dados Técnicos do Produto",
            "Dados Tecnicos do Produto",
            "Laboratório",
            "Laboratorio",
        ],
    )

    unidade_nova = _recortar_secao_retorno(
        texto_novo,
        ["Outras Unidades Fabris", "Unidades Fabris"],
        [
            "Dados do Certificado",
            "Produto",
            "Dados Técnicos do Produto",
            "Dados Tecnicos do Produto",
            "Laboratório",
            "Laboratorio",
        ],
    )

    norm_antiga = _normalizar_bloco_para_comparacao_retorno(unidade_antiga)
    norm_nova = _normalizar_bloco_para_comparacao_retorno(unidade_nova)

    alterada = bool(norm_antiga or norm_nova) and norm_antiga != norm_nova

    alteracoes = []

    if alterada:
        alteracoes.append(
            _montar_alteracao_retorno(
                "Outras Unidades Fabris",
                unidade_antiga,
                unidade_nova,
            )
        )

    return {
        "unidade_fabril_antiga": unidade_antiga,
        "unidade_fabril_nova": unidade_nova,
        "normalizado_antigo": norm_antiga,
        "normalizado_novo": norm_nova,
        "alterada": alterada,
        "alteracoes": alteracoes,
    }


def _doc_match_retorno(documento, aliases):
    doc_norm = _normalizar_texto_retorno(documento)

    if not doc_norm:
        return False

    for alias in aliases:
        alias_norm = _normalizar_texto_retorno(alias)

        if not alias_norm:
            continue

        # Aliases curtos, como ART, CCT e ISO, precisam bater como termo isolado.
        # Isso evita falso positivo como ART dentro de "Carta de Representação".
        if len(alias_norm) <= 4 and re.fullmatch(r"[a-z0-9]+", alias_norm):
            if re.search(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", doc_norm):
                return True
            continue

        if alias_norm in doc_norm:
            return True

    return False


def _extrair_texto_informacoes_adicionais_retorno(driver, wait):
    """
    Lê SOMENTE a Justificativa atual do OCD na aba Informações Adicionais.

    Essa Justificativa é a fonte usada para identificar o(s) tipo(s) RE.
    Não mistura:
    - histórico da tabela inferior;
    - Motivação do Retorno para Estudo;
    - textarea de Acompanhar Processo;
    - campo Descrição de Informações Adicionais;
    - texto geral do body.

    Se a Justificativa atual não puder ser localizada com segurança, retorna
    capturado=False em vez de inferir o tipo RE a partir de outros textos.
    """
    resultado = {
        "capturado": False,
        "texto": "",
        "origem": "justificativa_atual_ocd",
        "campo": "Justificativa",
        "erro": "",
    }

    try:
        print(
            "[SCH][RETORNO] Capturando somente a Justificativa atual "
            "do OCD em Informações Adicionais..."
        )

        clicar_aba_informacoes_adicionais(driver, wait)
        esperar_tela_carregar(driver, 0.25)

        entrar_iframe_detalhe_analise(driver, wait)

        xpaths_justificativa = [
            "//*[normalize-space(.)='Justificativa:' or normalize-space(.)='Justificativa']/following::textarea[1]",
            "//label[normalize-space(.)='Justificativa:' or normalize-space(.)='Justificativa']/following::textarea[1]",
            "//*[contains(normalize-space(.), 'Justificativa:')]/ancestor::tr[1]//textarea[1]",
            "//*[contains(normalize-space(.), 'Justificativa:')]/following::textarea[1]",
        ]

        campo = None

        for xpath in xpaths_justificativa:
            try:
                elementos = driver.find_elements(By.XPATH, xpath)
            except Exception:
                elementos = []

            for el in elementos:
                try:
                    if (
                        str(el.tag_name or "").lower() == "textarea"
                        and el.is_displayed()
                    ):
                        campo = el
                        break
                except Exception:
                    continue

            if campo is not None:
                break

        # Fallback controlado: na tela mostrada do Retorno Para Estudo,
        # a Justificativa atual é o primeiro textarea antes da seção
        # 'Acompanhar Processo'. Só aceitamos esse fallback quando conseguimos
        # confirmar a existência da seção de acompanhamento depois dele.
        if campo is None:
            try:
                candidatos = [
                    el
                    for el in driver.find_elements(
                        By.XPATH,
                        "//textarea[not(@disabled)]",
                    )
                    if el.is_displayed()
                ]

                marcador_acompanhar = driver.find_elements(
                    By.XPATH,
                    "//*[contains(normalize-space(), 'Acompanhar Processo') "
                    "or contains(normalize-space(), "
                    "'Desejo acompanhar este processo')]",
                )

                if candidatos and marcador_acompanhar:
                    campo = candidatos[0]
            except Exception:
                campo = None

        if campo is None:
            raise RuntimeError(
                "Textarea da Justificativa atual do OCD não foi localizado "
                "com segurança."
            )

        texto = str(
            driver.execute_script(
                "return arguments[0].value == null ? '' : String(arguments[0].value);",
                campo,
            )
            or ""
        ).strip()

        resultado["capturado"] = bool(texto)
        resultado["texto"] = texto
        resultado["id_campo"] = str(campo.get_attribute("id") or "")
        resultado["name_campo"] = str(campo.get_attribute("name") or "")

        if texto:
            resumo_terminal = " ".join(texto.split())[:500]
            print(
                "[SCH][RETORNO] Justificativa atual do OCD capturada: "
                f"{resumo_terminal}"
            )
        else:
            resultado["erro"] = "Justificativa atual do OCD está vazia."
            print(
                "[SCH][RETORNO][WARN] A Justificativa atual do OCD "
                "foi localizada, mas está vazia."
            )

        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        print(
            "[SCH][RETORNO][WARN] Falha ao capturar a Justificativa "
            f"atual do OCD: {e}"
        )

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        return resultado


def _mapa_tipos_re_informacoes_adicionais():
    return {
        "1": "Inclusão/exclusão de unidade(s) fabril(is), sem alteração do CH",
        "2": "Inclusão/exclusão de interfaces",
        "3": "Inclusão/exclusão de fontes",
        "4": "Inclusão da 2ª fase de bateria",
        "5": "Inclusão/exclusão de modelo de bateria",
        "6": "Manutenção tácita",
        "7": "Inclusão/exclusão de modelos",
        "8": "Inclusão/exclusão de nome comercial",
        "9": "Alteração de características técnicas",
        "10": "Alteração de dados de entidade com atualização do CH",
        "11": "Troca de OCD",
        "12": "Recertificação",
        "13": "Manutenção com alteração do CH",
        "14": "Troca de OCD - manutenção precária",
        "15": "Manutenção para assistência técnica/garantias",
        "16": "Declaração de conformidade com relatório de ensaio",
    }


def _analisar_numeros_tipo_re_informacoes_adicionais(texto_info):
    """
    Procura números de tipo de análise RE na aba Informações Adicionais.

    Regras atuais para aprovação automática:

    Aceitos individualmente:
    - 1
    - 5
    - 6
    - 10
    - 12

    Combinações aceitas:
    - 6 + 12
    - 6 + 11

    Observação:
    - 11 sozinho não é aceito.
    - 11 só é aceito quando aparecer junto com 6.
    """

    texto = str(texto_info or "")
    mapa = _mapa_tipos_re_informacoes_adicionais()

    aceitos_individuais = {"1", "5", "6", "10", "12"}

    texto_limpo = texto.replace("\u00a0", " ")
    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip()

    padrao = re.compile(
        r"(?<![\d/.-])"
        r"(16|15|14|13|12|11|10|9|8|7|6|5|4|3|2|1)"
        r"\s*[\.\-\)]\s*"
        r"(?=[A-Za-zÀ-ÿ])",
        flags=re.I,
    )

    numeros = []

    for m in padrao.finditer(texto_limpo):
        numero = str(m.group(1)).strip()

        if numero not in numeros:
            numeros.append(numero)

    conjunto = set(numeros)

    numeros_nao_permitidos = []

    for numero in numeros:
        if numero in aceitos_individuais:
            continue

        # Regra especial:
        # Tipo 11 só é permitido quando aparecer junto com o tipo 6.
        if numero == "11" and "6" in conjunto:
            continue

        numeros_nao_permitidos.append(numero)

    numeros_permitidos = [
        numero for numero in numeros
        if numero not in numeros_nao_permitidos
    ]

    def _tipo(numero):
        return {
            "numero": numero,
            "nome": mapa.get(numero, "Tipo de análise não mapeado"),
            "permitido": numero not in numeros_nao_permitidos,
        }

    combinacao_detectada = " + ".join(numeros) if numeros else ""

    combinacao_ok = False

    if not numeros:
        combinacao_ok = True
    elif conjunto.issubset(aceitos_individuais):
        combinacao_ok = True
    elif conjunto == {"6", "11"}:
        combinacao_ok = True
    elif conjunto == {"6", "12"}:
        combinacao_ok = True
    elif conjunto == {"6", "11", "12"}:
        combinacao_ok = True

    return {
        "numeros_detectados": numeros,
        "tipos_detectados": [_tipo(n) for n in numeros],
        "numeros_permitidos": numeros_permitidos,
        "tipos_permitidos": [_tipo(n) for n in numeros_permitidos],
        "numeros_nao_permitidos": numeros_nao_permitidos,
        "tipos_nao_permitidos": [_tipo(n) for n in numeros_nao_permitidos],
        "tem_numero_nao_permitido": bool(numeros_nao_permitidos),
        "combinacao_detectada": combinacao_detectada,
        "combinacao_ok": combinacao_ok,
        "permitidos_esperados": ["1", "5", "6", "10", "12", "6+12", "6+11"],
        "nomes_permitidos_esperados": [
            "1. Inclusão/exclusão de unidade(s) fabril(is), sem alteração do CH",
            "5. Inclusão/exclusão de modelo de bateria",
            "6. Manutenção tácita",
            "10. Alteração de dados de entidade com atualização do CH",
            "12. Recertificação",
            "6 + 12. Manutenção tácita + Recertificação",
            "6 + 11. Manutenção tácita + Troca de OCD",
        ],
    }



def _descricao_tipos_re_detectados(analise_numeros_info):
    """Monta o identificador e a descrição humana dos tipos RE detectados."""
    analise_numeros_info = analise_numeros_info or {}
    tipos = analise_numeros_info.get("tipos_detectados", []) or []

    numeros = []
    descricoes = []

    for item in tipos:
        if not isinstance(item, dict):
            continue

        numero = str(item.get("numero") or "").strip()
        nome = str(item.get("nome") or "").strip()

        if numero and numero not in numeros:
            numeros.append(numero)

        if numero and nome:
            descricoes.append(f"{numero}. {nome}")
        elif numero:
            descricoes.append(numero)

    if not numeros:
        return {
            "tipo_re": "6",
            "descricao_tipo_re": "6. Manutenção tácita",
            "origem": "padrao_sem_numero_explicito",
        }

    return {
        "tipo_re": "+".join(numeros),
        "descricao_tipo_re": " + ".join(descricoes),
        "origem": "informacoes_adicionais",
    }



def _regra_doc_retorno(chave, nome, aliases, obrigatorio=True, tipos=None):
    return {
        "chave": chave,
        "nome": nome,
        "aliases": aliases,
        "obrigatorio": obrigatorio,
        "tipos": tipos or [],
    }


def _regras_documentos_por_tipo_re_retorno():
    """
    Mapa resumido da planilha RE_DOCS para os tipos tratados neste fluxo.

    Importante:
    - A automação usa os obrigatórios principais para bloqueio.
    - Itens marcados como "se aplicável" ficam como condicionais/informativos.
    """
    base_cct = _regra_doc_retorno(
        "cct",
        "CCT",
        ["CCT", "Certificado de Conformidade Técnica", "Certificado de Conformidade Tecnica"],
    )
    base_ract = _regra_doc_retorno(
        "ract",
        "RACT",
        ["RACT", "Relatório de Avaliação da Conformidade", "Relatorio de Avaliacao da Conformidade"],
    )
    base_art = _regra_doc_retorno(
        "art",
        "ART",
        ["ART", "Anotação de Responsabilidade Técnica", "Anotacao de Responsabilidade Tecnica"],
    )

    manutencao_obrigatorios = [
        base_cct,
        base_ract,
        _regra_doc_retorno(
            "fotos_externas",
            "Fotos externas com selo Anatel atualizadas",
            [
                "Fotos externas",
                "Foto externa",
                "Fotos do produto",
                "Foto do produto",
                "FOTOS EXTERNAS",
                "selo anatel",
            ],
        ),
        _regra_doc_retorno(
            "fotos_internas",
            "Fotos internas atualizadas",
            ["Fotos internas", "Foto interna", "FOTOS INTERNAS", "internas"],
        ),
        _regra_doc_retorno(
            "declaracao_manutencao",
            "Declaração de manutenção",
            [
                "Declaração de manutenção",
                "Declaracao de manutencao",
                "Decl. de manutenção",
                "Decl de manutencao",
                "Declaração manutenção",
                "Declaracao manutencao",
                "DECL. DE ALTERAÇÃO",
                "DECL DE ALTERACAO",
                "Declaração de alteração",
                "Declaracao de alteracao",
                "manutenção",
                "manutencao",
                "Maintenance",
                "Maintenance Declaration",
                "Declaration of Maintenance",
                "Maintenance Statement",
            ],
        ),
        base_art,
    ]

    manutencao_condicionais = [
        _regra_doc_retorno(
            "iso_ou_auditoria_ocd",
            "Cópia da ISO ou relatório de auditoria do OCD",
            ["ISO", "auditoria", "relatório de auditoria", "relatorio de auditoria", "OCD"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "traducao_juramentada",
            "Tradução juramentada",
            ["Tradução juramentada", "Traducao juramentada", "tradução", "traducao"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "ensaios_seguranca_eletrica",
            "Relatórios de ensaios de segurança elétrica",
            ["segurança elétrica", "seguranca eletrica", "ensaio de segurança elétrica", "ensaio de seguranca eletrica"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "alteracao_laboratorio",
            "Alteração de laboratório",
            ["Alteração de laboratório", "Alteracao de laboratorio", "laboratório", "laboratorio"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "declaracao_rastreabilidade",
            "Declaração de rastreabilidade",
            ["Declaração de rastreabilidade", "Declaracao de rastreabilidade", "rastreabilidade", "controle de rast"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "outros",
            "Outros",
            ["Outros", "Outro", "Outros (OCD)"],
            obrigatorio=False,
        ),
    ]

    tipo_1_obrigatorios = [base_cct, base_ract, base_art]
    tipo_1_condicionais = [
        _regra_doc_retorno(
            "iso_ou_auditoria_ocd",
            "Cópia da ISO ou relatório de auditoria do OCD",
            ["ISO", "auditoria", "relatório de auditoria", "relatorio de auditoria", "OCD"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "traducao_juramentada",
            "Tradução juramentada",
            ["Tradução juramentada", "Traducao juramentada", "tradução", "traducao"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "outros",
            "Outros",
            ["Outros", "Outro", "Outros (OCD)"],
            obrigatorio=False,
        ),
    ]

    tipo_5_obrigatorios = [
        _regra_doc_retorno(
            "fotos_externas",
            "Fotos externas atualizadas",
            [
                "Fotos externas",
                "Foto externa",
                "Fotos do produto",
                "Foto do produto",
                "FOTOS EXTERNAS",
            ],
        ),
        base_cct,
        base_ract,
        base_art,
    ]

    tipo_5_condicionais = [
        _regra_doc_retorno(
            "iso_ou_auditoria_ocd",
            "Cópia da ISO ou relatório de auditoria do OCD, se aplicável",
            ["ISO", "auditoria", "relatório de auditoria", "relatorio de auditoria", "OCD"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "traducao_juramentada",
            "Tradução juramentada, se aplicável",
            ["Tradução juramentada", "Traducao juramentada", "tradução", "traducao"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "outros",
            "Outros",
            ["Outros", "Outro", "Outros (OCD)"],
            obrigatorio=False,
        ),
    ]

    tipo_10_obrigatorios = [base_cct, base_ract, base_art]
    tipo_10_condicionais = [
        _regra_doc_retorno(
            "fotos_externas",
            "Fotos externas atualizadas / fotos do selo, se aplicável",
            ["Fotos externas", "Foto externa", "Fotos do produto", "Foto do produto", "selo anatel"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "manual_especificacao_tecnica",
            "Manual/especificação técnica, se aplicável",
            ["Manual", "Manual do Produto", "Especificação Técnica", "Especificacao Tecnica", "ESPECIFICAÇÃO TÉCNICA"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "declaracao_alteracao_dados_fabricante",
            "Declaração de alteração dos dados do fabricante, se aplicável",
            ["Declaração de alteração", "Declaracao de alteracao", "DECL. DE ALTERAÇÃO", "alteração dos dados do fabricante"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "contrato_social_atualizado",
            "Contrato social atualizado, se aplicável",
            ["Contrato Social", "contrato social atualizado"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "carta_representacao_comercial",
            "Carta de representação comercial, se aplicável",
            ["Carta de Representação Comercial", "Carta de Representacao Comercial", "representação comercial"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "iso_ou_auditoria_ocd",
            "Cópia da ISO ou relatório de auditoria do OCD, se aplicável",
            ["ISO", "auditoria", "relatório de auditoria", "relatorio de auditoria", "OCD"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "traducao_juramentada",
            "Tradução juramentada, se aplicável",
            ["Tradução juramentada", "Traducao juramentada", "tradução", "traducao"],
            obrigatorio=False,
        ),
        _regra_doc_retorno(
            "outros",
            "Outros",
            ["Outros", "Outro", "Outros (OCD)"],
            obrigatorio=False,
        ),
    ]

    return {
        "1": {
            "numero": "1",
            "nome": "Inclusão/exclusão de unidade(s) fabril(is), sem alteração do CH",
            "obrigatorios": tipo_1_obrigatorios,
            "condicionais": tipo_1_condicionais,
        },
        "5": {
            "numero": "5",
            "nome": "Inclusão/exclusão de modelo de bateria no CCT do celular, sem alteração do CH",
            "obrigatorios": tipo_5_obrigatorios,
            "condicionais": tipo_5_condicionais,
        },
        "6": {
            "numero": "6",
            "nome": "Manutenção tácita",
            "obrigatorios": manutencao_obrigatorios,
            "condicionais": manutencao_condicionais,
        },
        "10": {
            "numero": "10",
            "nome": "Alteração de dados de entidade com atualização do CH",
            "obrigatorios": tipo_10_obrigatorios,
            "condicionais": tipo_10_condicionais,
        },
        "12": {
            "numero": "12",
            "nome": "Recertificação (documentos idem manutenção tácita)",
            "obrigatorios": manutencao_obrigatorios,
            "condicionais": manutencao_condicionais,
        },
    }


def _tipos_re_para_validacao_documentos(analise_numeros_info):
    analise_numeros_info = analise_numeros_info or {}
    permitidos = analise_numeros_info.get("numeros_permitidos", []) or []

    # Se não houver número explícito na justificativa, mantém o comportamento antigo:
    # tratar como manutenção tácita.
    if not permitidos:
        return ["6"]

    return [str(n) for n in permitidos if str(n) in {"1", "5", "6", "10", "12"}]


def _validar_documentos_obrigatorios_por_tipos_re(documentos_adicionados, tipos_re=None):
    documentos_adicionados = documentos_adicionados or []
    tipos_re = [str(t) for t in (tipos_re or ["6"])]

    mapa = _regras_documentos_por_tipo_re_retorno()

    regras_obrigatorias = []
    regras_condicionais = []
    tipos_usados = []

    def _add_regra(destino, regra, tipo_numero, tipo_nome):
        chave_base = regra.get("chave") or regra.get("nome") or "documento"
        chave = f"{tipo_numero}:{chave_base}"
        destino.append({
            **regra,
            "chave": chave,
            "chave_base": chave_base,
            "tipo_re_numero": tipo_numero,
            "tipo_re_nome": tipo_nome,
        })

    for tipo in tipos_re:
        regra_tipo = mapa.get(tipo)
        if not regra_tipo:
            continue

        tipos_usados.append({
            "numero": tipo,
            "nome": regra_tipo.get("nome", ""),
        })

        for regra in regra_tipo.get("obrigatorios", []) or []:
            _add_regra(regras_obrigatorias, regra, tipo, regra_tipo.get("nome", ""))

        for regra in regra_tipo.get("condicionais", []) or []:
            _add_regra(regras_condicionais, regra, tipo, regra_tipo.get("nome", ""))

    encontrados = []
    faltantes = []

    for regra in regras_obrigatorias:
        docs_match = [
            doc for doc in documentos_adicionados
            if _doc_match_retorno(doc, regra.get("aliases", []))
        ]

        item = {
            "chave": regra.get("chave"),
            "chave_base": regra.get("chave_base"),
            "nome": regra.get("nome"),
            "tipo_re_numero": regra.get("tipo_re_numero"),
            "tipo_re_nome": regra.get("tipo_re_nome"),
        }

        if docs_match:
            item["documentos"] = _lista_unica_retorno(docs_match)
            encontrados.append(item)
        else:
            faltantes.append(item)

    condicionais_encontrados = []

    for regra in regras_condicionais:
        docs_match = [
            doc for doc in documentos_adicionados
            if _doc_match_retorno(doc, regra.get("aliases", []))
        ]

        if docs_match:
            condicionais_encontrados.append({
                "chave": regra.get("chave"),
                "chave_base": regra.get("chave_base"),
                "nome": regra.get("nome"),
                "tipo_re_numero": regra.get("tipo_re_numero"),
                "tipo_re_nome": regra.get("tipo_re_nome"),
                "documentos": _lista_unica_retorno(docs_match),
            })

    return {
        "tipos_re_usados": tipos_usados,
        "obrigatorios_ok": not bool(faltantes),
        "obrigatorios_encontrados": encontrados,
        "obrigatorios_faltantes": faltantes,
        "condicionais_encontrados": condicionais_encontrados,
        "documentos_analisados": documentos_adicionados,
    }


def _validar_documentos_obrigatorios_manutencao_tacita(documentos_adicionados):
    """
    Compatibilidade com chamadas antigas.
    A validação padrão sem número informado continua usando o tipo 6.
    """
    return _validar_documentos_obrigatorios_por_tipos_re(
        documentos_adicionados=documentos_adicionados,
        tipos_re=["6"],
    )

def analisar_retorno_para_estudo(
    driver,
    wait,
    req=None,
    anexos_baixados=None,
    executar_envio=False,
):
    """
    Analisa Retorno Para Estudo tipo 6: manutenção tácita.

    Regra aplicada:

    - Se Produto NÃO mudou
      E Dados Técnicos do Produto NÃO mudaram
      E houve documento novo anexado
      E não houve documento removido
      E os documentos obrigatórios da manutenção tácita foram identificados
      => Pode enviar para aprovação.

    - Se Produto mudou
      => Não enviar para aprovação.

    - Se houve alteração real em Dados Técnicos do Produto
      => Não enviar para aprovação.

    - Se nenhum documento novo foi identificado
      => Não enviar para aprovação.

    - Se houve documento removido
      => Não enviar para aprovação.

    - Unidade Fabril é comparada e registrada em relatório. Nesta versão,
      alteração de Unidade Fabril gera alerta, mas não bloqueia automaticamente.

    Observação importante:
    Texto vermelho em Dados Técnicos do Produto NÃO é considerado alteração
    automaticamente. O vermelho pode ocorrer quando o OCD reescreve o mesmo
    conteúdo com formatação diferente. A decisão técnica é feita pela comparação
    normalizada do bloco.
    """

    req = req or {}
    anexos_baixados = anexos_baixados or []

    numero_req = req.get("requerimento", "") if isinstance(req, dict) else str(req or "")

    resultado = {
        "tipo_relatorio": "retorno_para_estudo",
        "tipo_re": "nao_identificado",
        "descricao_tipo_re": "Não identificado",
        "origem_tipo_re": "pendente",
        "requerimento": numero_req,

        "tipo_produto": req.get("tipo_produto", "") if isinstance(req, dict) else "",
        "tipo_produto_no_escopo": None,
        "filtro_tipo_produto_retorno": {},

        "itens_analisados_pela_automacao": [
            "Produto",
            "Dados Técnicos do Produto",
            "Outras Unidades Fabris",
            "Relação de Arquivos Anexos",
            "Documentos obrigatórios conforme tipo RE citado",
            "Informações Adicionais / justificativa do Retorno Para Estudo",
        ],

        "status_comparacao": "nao_executada",

        "produto_alterado": None,
        "alteracoes_produto": [],

        "dados_tecnicos_alterados": None,
        "alteracoes_dados_tecnicos": [],
        "alteracoes_especificacoes_complementares": [],

        "unidade_fabril_alterada": None,
        "alteracoes_unidade_fabril": [],

        "documentos_obrigatorios_ok": None,
        "documentos_obrigatorios_encontrados": [],
        "documentos_obrigatorios_faltantes": [],
        "documentos_condicionais_encontrados": [],
        "tipos_re_documentos_usados": [],

        "informacoes_adicionais_retorno": {},
        "analise_numeros_informacoes_adicionais": {},
        "numeros_tipo_re_detectados": [],
        "numeros_tipo_re_nao_permitidos": [],
        "info_adicionais_tem_numero_nao_permitido": False,

        "documentos_novos_detectados": None,
        "documentos_adicionados": [],
        "documentos_removidos": [],
        "documentos_removidos_inconclusivos": [],
        "documentos_removidos_detectados": False,
        "remocao_documental_inconclusiva": False,
        "diagnostico_documentos": {},
        "tempos_comparar_versoes": {},
        "marcacao_automacao_informacoes_adicionais": {},

        "pode_enviar_para_aprovacao": False,
        "deve_enviar_para_aprovacao": False,
        "acao_recomendada": "Não enviar para aprovação / Revisar manualmente",

        "resultado": "",
        "alertas": [],

        "envio_para_aprovacao": {
            "executado": False,
            "motivo": "execucao_desabilitada",
        },

        "captura": {},
        "erro": "",
    }

    info_abertura = {}

    # O filtro de tipos de produto explicitamente fora do escopo é aplicado
    # no fluxo antes de abrir o requerimento. Esta função recebe apenas os
    # requerimentos restantes e decide o escopo de análise pelo texto original
    # de Informações Adicionais e pela comparação das versões.
    resultado["tipo_produto_no_escopo"] = True
    resultado["filtro_tipo_produto_retorno"] = {
        "aplicado": True,
        "no_escopo": True,
        "motivo": "filtro_previo_de_tipos_explicitamente_nao_avaliados",
    }

    try:
        print("[SCH][RETORNO] Capturando Informações Adicionais do retorno para estudo...")

        info_adicionais_retorno = _extrair_texto_informacoes_adicionais_retorno(
            driver,
            wait,
        )

        resultado["informacoes_adicionais_retorno"] = info_adicionais_retorno

        if info_adicionais_retorno.get("capturado"):
            print("[SCH][RETORNO] Informações Adicionais capturadas.")
        else:
            print(
                "[SCH][RETORNO][WARN] Não foi possível capturar Informações Adicionais: "
                f"{info_adicionais_retorno.get('erro', '')}"
            )

        # A decisão de escopo do tipo RE é feita ANTES de qualquer alteração
        # em Informações Adicionais e antes de abrir Comparar Versões.
        analise_numeros_info = _analisar_numeros_tipo_re_informacoes_adicionais(
            info_adicionais_retorno.get("texto", "")
        )
        resultado["analise_numeros_informacoes_adicionais"] = analise_numeros_info
        resultado["numeros_tipo_re_detectados"] = (
            analise_numeros_info.get("numeros_detectados", []) or []
        )
        resultado["numeros_tipo_re_nao_permitidos"] = (
            analise_numeros_info.get("numeros_nao_permitidos", []) or []
        )
        resultado["info_adicionais_tem_numero_nao_permitido"] = bool(
            analise_numeros_info.get("tem_numero_nao_permitido")
        )

        descricao_tipos = _descricao_tipos_re_detectados(analise_numeros_info)
        resultado["tipo_re"] = descricao_tipos["tipo_re"]
        resultado["descricao_tipo_re"] = descricao_tipos["descricao_tipo_re"]
        resultado["origem_tipo_re"] = descricao_tipos["origem"]

        if not info_adicionais_retorno.get("capturado"):
            resultado["status_comparacao"] = "bloqueado_sem_informacoes_adicionais"
            resultado["resultado"] = (
                "O processo não foi analisado automaticamente porque não foi "
                "possível ler Informações Adicionais e confirmar o tipo de análise "
                "solicitado pelo OCD."
            )
            resultado["acao_recomendada"] = (
                "Não enviar para aprovação / Revisar Informações Adicionais"
            )
            resultado["alertas"].append(
                "A análise automática foi interrompida antes de Comparar Versões "
                "porque o tipo RE não pôde ser verificado em Informações Adicionais."
            )
            return resultado

        if (
            analise_numeros_info.get("tem_numero_nao_permitido")
            or not analise_numeros_info.get("combinacao_ok", True)
        ):
            numeros_txt = ", ".join(
                str(n)
                for n in analise_numeros_info.get("numeros_nao_permitidos", [])
            ) or "não especificado"
            resultado["status_comparacao"] = "fora_escopo_tipo_re"
            resultado["resultado"] = (
                "O processo não foi analisado automaticamente porque Informações "
                "Adicionais indicam tipo de análise RE fora do escopo automático."
            )
            resultado["acao_recomendada"] = (
                "Não enviar para aprovação / Revisar manualmente"
            )
            resultado["alertas"].append(
                "Tipo RE fora do escopo automático identificado antes de Comparar "
                f"Versões: {numeros_txt}."
            )
            return resultado

        print(
            "[SCH][RETORNO] Tipo RE validado antes da comparação: "
            f"{resultado.get('descricao_tipo_re', 'Não identificado')}"
        )

        print("[SCH][RETORNO] Retornando para Dados Gerais antes de abrir Comparar Versões...")

        try:
            clicar_aba_dados_gerais(driver, wait)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            esperar_tela_carregar(driver, 0.6)
            print("[SCH][RETORNO] Tela base pronta para abrir Comparar Versões.")
        except Exception as e:
            print(
                "[SCH][RETORNO][WARN] Não foi possível retornar para Dados Gerais "
                f"antes do Comparar Versões: {e}"
            )
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        inicio_abertura_comparacao = time.time()
        info_abertura = clicar_comparar_versoes(driver, wait)
        tempo_abertura_comparacao = round(
            time.time() - inicio_abertura_comparacao,
            2,
        )

        inicio_captura_comparacao = time.time()
        captura = _capturar_comparar_versoes(driver, wait, timeout=45)
        tempo_captura_comparacao = round(
            time.time() - inicio_captura_comparacao,
            2,
        )

        resultado["tempos_comparar_versoes"] = {
            "abertura_segundos": tempo_abertura_comparacao,
            "captura_segundos": tempo_captura_comparacao,
            "total_segundos": round(
                tempo_abertura_comparacao + tempo_captura_comparacao,
                2,
            ),
            "tentativas_captura": captura.get("_tentativas_captura", 0),
            "captura_completa": bool(captura.get("_captura_completa")),
        }

        resultado["captura"] = {
            "url": captura.get("url", ""),
            "title": captura.get("title", ""),
            "qtd_vermelhos_esquerda": len(captura.get("vermelhos_esquerda", []) or []),
            "qtd_vermelhos_direita": len(captura.get("vermelhos_direita", []) or []),
            "qtd_anexos_tabela_esquerda": len(captura.get("documentos_anexos_esquerda", []) or []),
            "qtd_anexos_tabela_direita": len(captura.get("documentos_anexos_direita", []) or []),
            "qtd_anexos_vermelhos_direita": len(captura.get("documentos_anexos_vermelhos_direita", []) or []),
            "qtd_anexos_vermelhos_esquerda": len(captura.get("documentos_anexos_vermelhos_esquerda", []) or []),
            "captura_completa": bool(captura.get("_captura_completa")),
            "tentativas_captura": captura.get("_tentativas_captura", 0),
            "tempo_captura_segundos": captura.get("_tempo_captura_segundos", 0),
        }

        texto_antigo = captura.get("texto_esquerda", "") or ""
        texto_novo = captura.get("texto_direita", "") or ""

        especificacoes_versao_nova = (
            _extrair_especificacoes_complementares_do_texto_direita(
                texto_novo
            )
        )

        resultado["especificacoes_complementares_versao_nova"] = (
            especificacoes_versao_nova
        )
        resultado["captura"][
            "especificacoes_complementares_versao_nova"
        ] = especificacoes_versao_nova

        print(
            "[SCH][RETORNO] Especificações Complementares da versão nova: "
            f"{'capturadas' if especificacoes_versao_nova else 'não capturadas'}"
        )

        if not texto_antigo and not texto_novo:
            texto_total = captura.get("texto_total", "") or ""
            texto_antigo = texto_total
            texto_novo = texto_total

            resultado["alertas"].append(
                "Não foi possível separar com segurança o lado antigo e o lado novo da comparação."
            )

        vermelhos_direita = _extrair_textos_vermelhos_por_lado_retorno(
            captura,
            lado="direita",
        )

        vermelhos_esquerda = _extrair_textos_vermelhos_por_lado_retorno(
            captura,
            lado="esquerda",
        )

        comparacao_tecnica = _comparar_blocos_dados_tecnicos_retorno(
            texto_antigo,
            texto_novo,
        )

        documentos = _comparar_documentos_anexos_retorno(
            texto_antigo=texto_antigo,
            texto_novo=texto_novo,
            vermelhos_direita=vermelhos_direita,
            vermelhos_esquerda=vermelhos_esquerda,
            docs_tabela_esquerda=captura.get("documentos_anexos_esquerda", []) or [],
            docs_tabela_direita=captura.get("documentos_anexos_direita", []) or [],
            docs_tabela_vermelhos_esquerda=captura.get("documentos_anexos_vermelhos_esquerda", []) or [],
            docs_tabela_vermelhos_direita=captura.get("documentos_anexos_vermelhos_direita", []) or [],
        )
        texto_produto_antigo = captura.get("produto_esquerda", "") or texto_antigo
        texto_produto_novo = captura.get("produto_direita", "") or texto_novo

        comparacao_produto = _comparar_bloco_produto_retorno(
            texto_produto_antigo,
            texto_produto_novo,
        )
        comparacao_unidade_fabril = _comparar_bloco_unidade_fabril_retorno(
            texto_antigo,
            texto_novo,
        )


        # Importante:
        # A partir daqui, NÃO usamos mais os textos vermelhos de Dados Técnicos
        # como prova automática de alteração técnica.
        #
        # O vermelho pode indicar apenas que o OCD reescreveu a mesma informação
        # com formatação diferente, como:
        # - Vca x VAC
        # - Vcc x VDC
        # - 0,9 A x 0,9A
        # - vírgula, ponto, ponto e vírgula etc.
        #
        # A alteração técnica real vem da comparação normalizada feita em:
        # _comparar_blocos_dados_tecnicos_retorno()

        alteracoes_tecnicas = list(comparacao_tecnica.get("alteracoes", []) or [])
        alteracoes_especificacoes = list(
            comparacao_tecnica.get("alteracoes_especificacoes_complementares", []) or []
        )

        resultado["alteracoes_dados_tecnicos"] = alteracoes_tecnicas
        resultado["alteracoes_especificacoes_complementares"] = alteracoes_especificacoes
        resultado["especificacoes_complementares_alteradas"] = bool(alteracoes_especificacoes)

        resultado["documentos_adicionados"] = documentos.get("documentos_adicionados", []) or []
        resultado["documentos_removidos"] = documentos.get("documentos_removidos", []) or []
        resultado["documentos_removidos_inconclusivos"] = (
            documentos.get("documentos_removidos_inconclusivos", []) or []
        )
        resultado["documentos_removidos_detectados"] = bool(
            documentos.get("remocao_confirmada")
        )
        resultado["remocao_documental_inconclusiva"] = bool(
            documentos.get("tem_remocao_inconclusiva")
        )
        resultado["diagnostico_documentos"] = documentos

        print(
            "[SCH][RETORNO] Relação de Arquivos Anexos capturada: "
            f"antigos={len(documentos.get('documentos_antigos', []) or [])} | "
            f"novos={len(documentos.get('documentos_novos', []) or [])} | "
            f"adicionados={len(resultado['documentos_adicionados'])} | "
            f"removidos={len(resultado['documentos_removidos'])} | "
            f"origem={documentos.get('origem_documentos', '')}"
        )

        # O tipo RE já foi identificado e validado antes de abrir Comparar Versões.
        analise_numeros_info = (
            resultado.get("analise_numeros_informacoes_adicionais") or {}
        )

        tipos_re_para_validacao = _tipos_re_para_validacao_documentos(
            analise_numeros_info
        )

        validacao_documentos = _validar_documentos_obrigatorios_por_tipos_re(
            documentos_adicionados=resultado["documentos_adicionados"],
            tipos_re=tipos_re_para_validacao,
        )

        resultado["produto_alterado"] = bool(comparacao_produto.get("alterado"))
        resultado["alteracoes_produto"] = comparacao_produto.get("alteracoes", [])

        resultado["unidade_fabril_alterada"] = bool(
            comparacao_unidade_fabril.get("alterada")
        )
        resultado["alteracoes_unidade_fabril"] = comparacao_unidade_fabril.get("alteracoes", [])

        resultado["documentos_obrigatorios_ok"] = bool(
            validacao_documentos.get("obrigatorios_ok")
        )
        resultado["documentos_obrigatorios_encontrados"] = (
            validacao_documentos.get("obrigatorios_encontrados", [])
        )
        resultado["documentos_obrigatorios_faltantes"] = (
            validacao_documentos.get("obrigatorios_faltantes", [])
        )
        resultado["documentos_condicionais_encontrados"] = (
            validacao_documentos.get("condicionais_encontrados", [])
        )
        resultado["tipos_re_documentos_usados"] = (
            validacao_documentos.get("tipos_re_usados", [])
        )



        tem_alteracao_tecnica = bool(resultado["alteracoes_dados_tecnicos"])
        tem_documento_adicionado = bool(resultado["documentos_adicionados"])
        tem_documento_removido = bool(resultado["documentos_removidos"])
        tem_remocao_inconclusiva = bool(
            resultado["documentos_removidos_inconclusivos"]
        )

        tem_alteracao_produto = bool(resultado["produto_alterado"])
        tem_alteracao_unidade_fabril = bool(resultado["unidade_fabril_alterada"])
        documentos_obrigatorios_ok = bool(resultado["documentos_obrigatorios_ok"])

        resultado["dados_tecnicos_alterados"] = tem_alteracao_tecnica
        resultado["documentos_novos_detectados"] = tem_documento_adicionado

        if tem_alteracao_produto:
            resultado["alertas"].append(
                "Houve alteração no bloco Produto. Manutenção tácita não deve alterar produto."
            )
        if tem_alteracao_unidade_fabril:
            resultado["alertas"].append(
                "Houve alteração em Outras Unidades Fabris. A alteração foi registrada para conferência."
            )
        if not documentos_obrigatorios_ok:
            faltantes_txt = ", ".join(
                item.get("nome", "")
                for item in resultado["documentos_obrigatorios_faltantes"]
                if item.get("nome")
            )

            resultado["alertas"].append(
                "Documentos obrigatórios conforme o(s) tipo(s) RE citado(s) não identificados: "
                f"{faltantes_txt or 'não especificado'}."
            )

        if resultado.get("info_adicionais_tem_numero_nao_permitido"):
            numeros_txt = ", ".join(
                str(n) for n in resultado.get("numeros_tipo_re_nao_permitidos", [])
            )
            permitidos_txt = ", ".join(
                resultado.get("analise_numeros_informacoes_adicionais", {}).get(
                    "permitidos_esperados",
                    ["1", "5", "6", "10", "12", "6+12", "6+11"],
                )
            )

            resultado["alertas"].append(
                "Informações Adicionais citam tipo(s) de análise RE fora do escopo esperado: "
                f"{numeros_txt or 'não especificado'}. "
                f"Tipos aceitos neste fluxo: {permitidos_txt}. Revisão manual recomendada."
            )

    

        if tem_alteracao_tecnica:
            resultado["alertas"].append(
                "Houve alteração real em Dados Técnicos do Produto. "
                "Manutenção tácita não deve alterar dados técnicos."
            )

        if not tem_documento_adicionado:
            resultado["alertas"].append(
                "Nenhum documento novo foi identificado na Relação de Arquivos Anexos."
            )

        if tem_documento_removido:
            resultado["alertas"].append(
                "Foi identificada remoção confirmada de documento no lado antigo "
                "da Relação de Arquivos Anexos."
            )

        if tem_remocao_inconclusiva:
            resultado["alertas"].append(
                "Há diferença documental sem confirmação visual de remoção. "
                "O caso foi classificado como inconclusivo e requer revisão manual."
            )

        if (
            not tem_alteracao_produto
            and not tem_alteracao_tecnica
            and tem_documento_adicionado
            and not tem_documento_removido
            and not tem_remocao_inconclusiva
            and documentos_obrigatorios_ok
            and not resultado.get("info_adicionais_tem_numero_nao_permitido")
        ):
            resultado["status_comparacao"] = "manutencao_tacita_apta"
            resultado["resultado"] = (
                "Análise de Retorno Para Estudo concluída: não houve alteração em Produto "
                "nem em Dados Técnicos do Produto, houve documento novo, não houve remoção confirmada "
                "nem diferença documental inconclusiva, "
                "os documentos obrigatórios do(s) tipo(s) RE citado(s) foram identificados e "
                "as Informações Adicionais não citaram número de análise fora do escopo permitido."
            )
            resultado["acao_recomendada"] = "Enviar para aprovação"
            resultado["pode_enviar_para_aprovacao"] = True
            resultado["deve_enviar_para_aprovacao"] = True

        else:
            resultado["status_comparacao"] = "manutencao_tacita_nao_apta"
            resultado["resultado"] = (
                "Análise de manutenção tácita concluída: o processo não deve ser "
                "enviado para aprovação automaticamente."
            )
            resultado["acao_recomendada"] = "Não enviar para aprovação / Revisar manualmente"
            resultado["pode_enviar_para_aprovacao"] = False
            resultado["deve_enviar_para_aprovacao"] = False

        resultado["envio_para_aprovacao"] = enviar_retorno_para_aprovacao_se_apto(
            driver=driver,
            wait=wait,
            resultado=resultado,
            info_abertura=info_abertura,
            executar_envio=executar_envio,
        )

        print(
            "[SCH][RETORNO] Resultado da comparação: "
            f"{resultado['status_comparacao']} | "
            f"ação={resultado['acao_recomendada']}"
        )

        print(
            "[SCH][RETORNO] Produto alterado: "
            f"{'SIM' if resultado.get('produto_alterado') else 'NÃO'}"
        )

        print(
            "[SCH][RETORNO] Dados Técnicos alterados: "
            f"{'SIM' if resultado.get('dados_tecnicos_alterados') else 'NÃO'}"
        )

        print(
            "[SCH][RETORNO] Unidade fabril alterada: "
            f"{'SIM' if resultado.get('unidade_fabril_alterada') else 'NÃO'}"
        )

        print(
            "[SCH][RETORNO] Documento novo identificado: "
            f"{'SIM' if resultado.get('documentos_novos_detectados') else 'NÃO'}"
        )

        print(
            "[SCH][RETORNO] Documentos obrigatórios OK: "
            f"{'SIM' if resultado.get('documentos_obrigatorios_ok') else 'NÃO'}"
        )

        numeros_detectados_txt = ", ".join(
            str(n) for n in resultado.get("numeros_tipo_re_detectados", [])
        ) or "nenhum"
        numeros_nao_permitidos_txt = ", ".join(
            str(n) for n in resultado.get("numeros_tipo_re_nao_permitidos", [])
        ) or "nenhum"

        print(
            "[SCH][RETORNO] Números RE nas Informações Adicionais: "
            f"{numeros_detectados_txt}"
        )
        print(
            "[SCH][RETORNO] Números RE fora do escopo: "
            f"{numeros_nao_permitidos_txt}"
        )

        print(
            "[SCH][RETORNO] Pode enviar para aprovação: "
            f"{'SIM' if resultado.get('deve_enviar_para_aprovacao') else 'NÃO'}"
        )

        return resultado

    except Exception as e:
        erro_texto = str(e)
        erro_norm = _normalizar_texto_comparacao(erro_texto)

        if (
            "proxy error" in erro_norm
            or "erro temporario do sch" in erro_norm
            or "error reading from remote server" in erro_norm
        ):
            resultado["status_comparacao"] = "erro_temporario_sch_proxy"
            resultado["resultado"] = (
                "Não foi possível concluir a análise porque o SCH retornou Proxy Error "
                "ao abrir Comparar Versões. Tente novamente mais tarde."
            )
        else:
            resultado["status_comparacao"] = "erro"
            resultado["resultado"] = (
                "Não foi possível concluir automaticamente a análise de manutenção tácita."
            )
        resultado["acao_recomendada"] = "Não enviar para aprovação / Revisar manualmente"
        resultado["pode_enviar_para_aprovacao"] = False
        resultado["deve_enviar_para_aprovacao"] = False
        resultado["erro"] = str(e)
        resultado["alertas"].append(
            "Erro durante a análise automática. Revisão manual obrigatória."
        )

        print(f"[SCH][RETORNO][WARN] Falha na análise de Retorno Para Estudo: {e}")

        return resultado

    finally:
        try:
            restauracao = restaurar_tela_requerimento_apos_comparacao(
                driver=driver,
                wait=wait,
                aba_original_sch=info_abertura.get("aba_origem")
                if isinstance(info_abertura, dict)
                else None,
                info_abertura=info_abertura,
            )
            resultado["restauracao_tela_requerimento"] = restauracao
        except Exception as e:
            resultado["restauracao_tela_requerimento"] = {
                "restaurado": False,
                "erro": str(e),
            }
            resultado.setdefault("alertas", []).append(
                "Não foi possível confirmar o retorno à tela do "
                "requerimento após Comparar Versões."
            )
            print(
                "[SCH][RETORNO][WARN] Falha ao restaurar a tela "
                f"do requerimento: {e}"
            )


def _confirmar_aprovacao_retorno_para_estudo(driver, wait, timeout=4):
    """
    Confirma alertas ou modais que possam aparecer depois de clicar em Aprovar.
    """

    # 1) Alert nativo do navegador
    try:
        alert = WebDriverWait(driver, timeout).until(EC.alert_is_present())
        texto_alerta = alert.text or ""
        alert.accept()
        esperar_tela_carregar(driver, 0.8)

        print(f"[SCH][RETORNO] Alert de aprovação confirmado: {texto_alerta}")

        return {
            "confirmado": True,
            "tipo": "alert",
            "mensagem": texto_alerta,
        }

    except Exception:
        pass

    # 2) Modal HTML / PrimeFaces
    xpaths_confirmar = [
        "//*[self::button or self::a][normalize-space()='Sim']",
        "//*[self::button or self::a][normalize-space()='SIM']",
        "//*[self::button or self::a][normalize-space()='Confirmar']",
        "//*[self::button or self::a][normalize-space()='OK']",
        "//span[normalize-space()='Sim']/ancestor::*[self::button or self::a][1]",
        "//span[normalize-space()='Confirmar']/ancestor::*[self::button or self::a][1]",
        "//span[normalize-space()='OK']/ancestor::*[self::button or self::a][1]",
    ]

    ultimo_erro = None

    for contexto in ["iframe", "default"]:
        try:
            if contexto == "iframe":
                entrar_iframe_detalhe_analise(driver, wait)
            else:
                driver.switch_to.default_content()

            for xpath in xpaths_confirmar:
                try:
                    botoes = driver.find_elements(By.XPATH, xpath)

                    for botao in botoes:
                        try:
                            if not botao.is_displayed() or not botao.is_enabled():
                                continue

                            texto_botao = " ".join(
                                [
                                    botao.text or "",
                                    botao.get_attribute("value") or "",
                                    botao.get_attribute("title") or "",
                                ]
                            ).strip()

                            driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});",
                                botao,
                            )

                            _clicar_com_fallback(driver, botao)
                            esperar_tela_carregar(driver, 1.0)

                            print(
                                "[SCH][RETORNO] Confirmação da aprovação clicada: "
                                f"{texto_botao or xpath}"
                            )

                            return {
                                "confirmado": True,
                                "tipo": "modal_html",
                                "botao": texto_botao or xpath,
                            }

                        except Exception as e:
                            ultimo_erro = e
                            continue

                except Exception as e:
                    ultimo_erro = e
                    continue

        except Exception as e:
            ultimo_erro = e
            continue

    return {
        "confirmado": False,
        "tipo": "sem_confirmacao_detectada",
        "erro": str(ultimo_erro or ""),
    }


def clicar_aprovar_retorno_para_estudo(driver, wait, timeout=20):
    """
    Localiza e clica exclusivamente no botão Aprovar do Retorno Para Estudo.

    Usa primeiro o ID exato confirmado no DevTools:
    formAnalise:botaoAprovar
    """

    print(
        "[SCH][RETORNO] Procurando o botão 'Aprovar' pelo ID exato "
        "'formAnalise:botaoAprovar'..."
    )

    inicio = time.time()
    ultimo_erro = None
    tentativa = 0

    while time.time() - inicio < timeout:
        tentativa += 1

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        # Documento principal + todos os iframes.
        contextos = [("default", None)]

        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")

            contextos.extend(
                (f"iframe_{indice}", indice)
                for indice in range(len(iframes))
            )
        except Exception:
            pass

        for nome_contexto, indice_iframe in contextos:
            try:
                driver.switch_to.default_content()

                if indice_iframe is not None:
                    # Rebusca os iframes em cada tentativa para evitar stale.
                    iframes_atuais = driver.find_elements(
                        By.TAG_NAME,
                        "iframe",
                    )

                    if indice_iframe >= len(iframes_atuais):
                        continue

                    iframe = iframes_atuais[indice_iframe]

                    nome_contexto = (
                        iframe.get_attribute("id")
                        or iframe.get_attribute("name")
                        or nome_contexto
                    )

                    driver.switch_to.frame(iframe)

                # ID exato confirmado no DevTools.
                candidatos = driver.find_elements(
                    By.ID,
                    "formAnalise:botaoAprovar",
                )

                # Fallback com o XPath exato.
                if not candidatos:
                    candidatos = driver.find_elements(
                        By.XPATH,
                        '//*[@id="formAnalise:botaoAprovar"]',
                    )

                botao = None

                for candidato in candidatos:
                    try:
                        if (
                            candidato.is_displayed()
                            and candidato.is_enabled()
                        ):
                            botao = candidato
                            break
                    except StaleElementReferenceException:
                        continue

                if botao is None:
                    continue

                driver.execute_script(
                    """
                    arguments[0].scrollIntoView({
                        block: 'center',
                        inline: 'center'
                    });
                    """,
                    botao,
                )

                id_botao = botao.get_attribute("id") or ""

                try:
                    botao.click()
                except Exception:
                    driver.execute_script(
                        "arguments[0].click();",
                        botao,
                    )

                print(
                    "[SCH][RETORNO] Botão 'Aprovar' clicado. "
                    f"contexto={nome_contexto} | id={id_botao}"
                )

                esperar_tela_carregar(driver, 0.8)

                confirmacao = _confirmar_aprovacao_retorno_para_estudo(
                    driver,
                    wait,
                    timeout=6,
                )

                return {
                    "executado": True,
                    "confirmado": bool(
                        confirmacao.get("confirmado")
                    ),
                    "botao": "Aprovar",
                    "id_botao": id_botao,
                    "contexto": nome_contexto,
                    "tentativa": tentativa,
                    "confirmacao": confirmacao,
                }

            except StaleElementReferenceException as e:
                ultimo_erro = e
                continue

            except Exception as e:
                ultimo_erro = e
                continue

        time.sleep(0.5)

    try:
        driver.switch_to.default_content()
        url_final = str(driver.current_url or "")
    except Exception:
        url_final = ""

    print(
        "[SCH][RETORNO][WARN] Botão 'Aprovar' não encontrado pelo ID "
        "'formAnalise:botaoAprovar'."
    )

    return {
        "executado": False,
        "confirmado": False,
        "motivo": "botao_aprovar_nao_encontrado",
        "erro": str(ultimo_erro or ""),
        "url_final": url_final,
        "xpath": '//*[@id="formAnalise:botaoAprovar"]',
    }

def enviar_retorno_para_aprovacao_se_apto(
    driver,
    wait,
    resultado,
    info_abertura=None,
    executar_envio=False,
):
    """
    Envia automaticamente apenas os requerimentos aprovados pela análise.

    Só clica em Aprovar quando:
    - executar_envio=True
    - resultado["deve_enviar_para_aprovacao"] == True
    """

    resultado = resultado or {}
    info_abertura = info_abertura or {}

    if not executar_envio:
        return {
            "executado": False,
            "motivo": "execucao_desabilitada_no_fluxo",
        }

    if not resultado.get("deve_enviar_para_aprovacao"):
        return {
            "executado": False,
            "motivo": "requerimento_nao_apto_para_aprovacao",
            "acao_recomendada": resultado.get("acao_recomendada", ""),
            "status_comparacao": resultado.get("status_comparacao", ""),
        }

    print(
        "[SCH][RETORNO] Requerimento julgado correto. "
        "Fechando comparação e retornando à tela do requerimento para clicar em Aprovar..."
    )

    try:
        _fechar_comparacao_se_abriu_nova_aba(driver, info_abertura)
        esperar_tela_carregar(driver, 1.0)
    except Exception as e:
        print(
            "[SCH][RETORNO][WARN] Não foi possível fechar a comparação antes de aprovar: "
            f"{e}"
        )

    return clicar_aprovar_retorno_para_estudo(driver, wait)


def voltar_para_fila(driver, wait, nome_fila=None):
    fila_destino = _resolver_nome_fila_sch(nome_fila or FILA_SCH_ATUAL or "Em Análise")
    print(f"[SCH] Voltando para a fila {fila_destino}...")

    if garantir_sessao_ativa_sch(
        driver,
        wait,
        contexto="ao tentar voltar para a fila",
        reabrir_fila=True,
        nome_fila=fila_destino,
    ):
        print(f"[SCH] Retorno para a fila {fila_destino} concluído após refazer login.")
        return

    candidatos = [
        "//a[contains(., 'Voltar')]",
        "//button[contains(., 'Voltar')]",
        "//input[@type='button' and contains(@value,'Voltar')]",
        "//img[contains(@src,'voltar')]/..",
    ]

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    for xpath in candidatos:
        try:
            botao = WebDriverWait(driver, 1.2, poll_frequency=0.08).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            _clicar_com_fallback(driver, botao)

            WebDriverWait(driver, 3, poll_frequency=0.08).until(
                EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
            )

            print(f"[SCH] Retorno para a fila {fila_destino} concluído por botão.")
            return
        except Exception:
            continue

    try:
        driver.switch_to.default_content()
        driver.back()

        WebDriverWait(driver, 3, poll_frequency=0.08).until(
            EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
        )
        print(f"[SCH] Retorno para a fila {fila_destino} concluído por back().")
        return
    except Exception:
        pass

    # Fallback: reabre a página principal e clica explicitamente na fila correta.
    try:
        abrir_sch(driver)
        esperar_tela_carregar(driver, 1.0)
        clicar_fila_sch(driver, wait, fila_destino)
        print(f"[SCH] Retorno para a fila {fila_destino} concluído por clique direto.")
        return

    except Exception as e:
        print(f"[SCH][WARN] Não foi possível voltar clicando na fila {fila_destino}: {e}")

    if garantir_sessao_ativa_sch(
        driver,
        wait,
        contexto="após falha ao voltar para a fila",
        reabrir_fila=True,
        nome_fila=fila_destino,
    ):
        print(f"[SCH] Retorno para a fila {fila_destino} concluído após refazer login.")
        return

    raise Exception(f"Não foi possível voltar para a fila {fila_destino}.")

