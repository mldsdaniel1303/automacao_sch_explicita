import re
import shutil
import time
import unicodedata

from pathlib import Path
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

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


def _parece_requerimento(valor):
    texto = str(valor or "").strip()
    return bool(re.search(r"\b\d{4,6}\s*/\s*\d{2,4}\b", texto))


def _parece_homologacao_anatel(valor):
    texto = str(valor or "").strip()

    # Exemplo: 03645-26-12388 / 14956-22-10459
    if re.search(r"\b\d{4,6}\s*[-–—]\s*\d{2}\s*[-–—]\s*\d{4,6}\b", texto):
        return True

    # Exemplo: 036452612388, quando vem sem hífen
    digitos = _somente_digitos(texto)
    if len(digitos) == 12:
        return True

    return False


def _parece_certificado(valor):
    texto = str(valor or "").strip()
    texto_norm = _normalizar_texto_comparacao(texto)

    if not texto_norm:
        return False

    # Evita classificar homologação ou requerimento como certificado
    if _parece_homologacao_anatel(texto) or _parece_requerimento(texto):
        return False

    sinais_certificado = [
        "ocp",
        "icc",
        "ncc",
        "abcp",
        "certificate",
        "certificado",
        "versys",
        "cpqd",
        "dekra",
        "tuv",
        "ul",
    ]

    return any(sinal in texto_norm for sinal in sinais_certificado)


def _formatar_requerimento(valor):
    texto = str(valor or "").strip()
    m = re.search(r"\b(\d{4,6})\s*/\s*(\d{2,4})\b", texto)

    if not m:
        return texto

    numero = _somente_digitos(m.group(1))
    ano = _somente_digitos(m.group(2))

    if len(numero) < 5:
        numero = numero.zfill(5)

    if len(ano) == 4:
        ano = ano[-2:]

    return f"{numero}/{ano}"


def _formatar_homologacao_anatel(valor):
    texto = str(valor or "").strip()
    texto = texto.replace("–", "-").replace("—", "-")

    m = re.search(r"\b(\d{4,6})\s*-\s*(\d{2})\s*-\s*(\d{4,6})\b", texto)
    if m:
        p1 = _somente_digitos(m.group(1)).zfill(5)
        p2 = _somente_digitos(m.group(2))
        p3 = _somente_digitos(m.group(3)).zfill(5)
        return f"{p1}-{p2}-{p3}"

    digitos = _somente_digitos(texto)
    if len(digitos) == 12:
        return f"{digitos[:5]}-{digitos[5:7]}-{digitos[7:]}"

    return texto


def _corrigir_campos_fila_por_padrao(dados):
    """
    Corrige inversões comuns entre requerimento, homologação e certificado
    usando o formato do valor, não apenas a posição da coluna.
    """
    dados = dados or {}

    valores = []

    for chave in [
        "requerimento",
        "homologacao",
        "certificado",
        "tipo_produto",
        "modelo",
        "texto_linha",
    ]:
        valor = str(dados.get(chave, "") or "").strip()
        if valor:
            valores.append(valor)

    texto_linha = str(dados.get("texto_linha", "") or "")
    partes_linha = [p.strip() for p in re.split(r"\s*\|\s*", texto_linha) if p.strip()]
    valores.extend(partes_linha)

    # Requerimento
    for valor in valores:
        if _parece_requerimento(valor):
            dados["requerimento"] = _formatar_requerimento(valor)
            break

    # Homologação
    for valor in valores:
        if _parece_homologacao_anatel(valor):
            dados["homologacao"] = _formatar_homologacao_anatel(valor)
            break

    # Certificado
    for valor in valores:
        if _parece_certificado(valor):
            dados["certificado"] = _texto_limpo(valor)
            break

    # Evita certificado receber homologação ANATEL
    if _parece_homologacao_anatel(dados.get("certificado", "")):
        dados["certificado"] = ""

    # Evita homologação receber número de requerimento
    if _parece_requerimento(dados.get("homologacao", "")):
        dados["homologacao"] = ""

    return dados



def _extrair_numero_requerimento_de_linha(texto_linha, celulas=None):
    """
    Extrai o número do requerimento preservando o ano quando vier no formato 04334/26.

    Exemplos:
    - 04334/26  -> 04334/26
    - 4334/26   -> 04334/26
    - 04334     -> 04334
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

    # 1. Prioridade: formato com ano, exemplo 04334/26
    padroes_com_ano = [
        r"\b(\d{4,6})\s*/\s*(\d{2,4})\b",
        r"requerimento\s*[:#\-]?\s*(\d{4,6})\s*/\s*(\d{2,4})\b",
    ]

    for texto in candidatos:
        for padrao in padroes_com_ano:
            m = re.search(padrao, texto, re.I)
            if m:
                numero = _somente_digitos(m.group(1))
                ano = _somente_digitos(m.group(2))

                if not numero or not ano:
                    continue

                # Garante 5 dígitos no número principal: 4334 -> 04334
                if len(numero) < 5:
                    numero = numero.zfill(5)

                # Ano com 4 dígitos vira 2 dígitos: 2026 -> 26
                if len(ano) == 4:
                    ano = ano[-2:]

                return f"{numero}/{ano}"

    # 2. Fallback: formato antigo, somente número
    padroes_sem_ano = [
        r"requerimento\s*[:#\-]?\s*(\d{4,6})",
        r"^\s*(\d{4,6})\s*$",
        r"\b(\d{5,6})\b",
    ]

    for texto in candidatos:
        for padrao in padroes_sem_ano:
            m = re.search(padrao, texto, re.I)
            if m:
                numero = _somente_digitos(m.group(1))

                if len(numero) >= 4:
                    if len(numero) < 5:
                        numero = numero.zfill(5)

                    return numero

    return ""

def _clicar_com_fallback(driver, elemento):
    try:
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elemento)


def _aguardar_iframe_detalhe(driver, timeout=8):
    return WebDriverWait(driver, timeout, poll_frequency=0.05).until(
        EC.presence_of_element_located((By.XPATH, XPATH_IFRAME_DETALHE))
    )


def _aguardar_tabela_fila(driver, timeout=6):
    return WebDriverWait(driver, timeout, poll_frequency=0.05).until(
        EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
    )


def _tabela_fila_pronta(driver):
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    try:
        tabelas = driver.find_elements(By.XPATH, XPATH_TABELA_FILA)

        for tabela in tabelas:
            try:
                if not tabela.is_displayed():
                    continue

                linhas = tabela.find_elements(By.XPATH, ".//tbody/tr[td]")
                if linhas:
                    return True

                # Mesmo sem linha, se a tabela está visível, já considera carregada.
                return True

            except Exception:
                continue

    except Exception:
        pass

    return False



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

    try:
        WebDriverWait(driver, 8, poll_frequency=0.08).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
    except Exception:
        pass

    esperar_tela_carregar(driver, 0.05)


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


def garantir_sessao_ativa_sch(driver, wait, contexto="", reabrir_fila=True):
    """
    Verifica se o SCH caiu na tela de login.
    Se caiu, pausa para o usuário logar novamente e reabre a fila Em Análise.
    Retorna True quando precisou refazer login.
    Retorna False quando a sessão já estava ativa.
    """
    if not _esta_na_tela_login_sch(driver):
        return False

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
                    clicar_fila_em_analise(driver, wait)
                except Exception as e:
                    print(f"[SCH][WARN] Login refeito, mas não foi possível clicar na fila Em Análise automaticamente: {e}")

            print("[SCH][LOGIN] Sessão restaurada. Continuando fluxo.")
            return True

        print("[SCH][WARN] A tela ainda parece estar no login.")

    raise Exception("Sessão SCH expirada. Não foi possível restaurar o login após 3 tentativas.")


def clicar_fila_em_analise(driver, wait):
    xpath_fila = "//a[normalize-space()='Em Análise' or contains(normalize-space(), 'Em Análise')]"

    print("[SCH] Clicando na fila Em Análise...")

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    fila = WebDriverWait(driver, 4, poll_frequency=0.05).until(
        EC.element_to_be_clickable((By.XPATH, xpath_fila))
    )

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", fila)
    driver.execute_script("arguments[0].click();", fila)

    WebDriverWait(driver, 5, poll_frequency=0.05).until(
        lambda d: _tabela_fila_pronta(d)
    )

    esperar_tela_carregar(driver, 0.03)

    print("[SCH] Fila aberta.")


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
            }

            dados = _corrigir_campos_fila_por_padrao(dados)

            requerimentos.append(dados)

        except Exception as e:
            print(f"[SCH][WARN] Falha ao ler linha {idx}: {e}")

    print(f"[SCH] {len(requerimentos)} requerimentos encontrados.")
    for item in requerimentos:
       print(
        f"[SCH] Linha {item['row_index']}: "
        f"requerimento={item.get('requerimento', '')} | "
        f"homologacao={item.get('homologacao', '')} | "
        f"certificado={item.get('certificado', '')} | "
        f"tipo_produto={item.get('tipo_produto', '')} | "
        f"modelo={item.get('modelo', '')}"
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

    print(
        "[SCH] Dados do certificado no SCH: "
        f"certificado={dados.get('numero_certificado', '')} | "
        f"emissão={dados.get('data_certificado', '')} | "
        f"validade={dados.get('data_validade', '')}"
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
            "faixa de frequencias",
            "faixa de frequencia",
            "faixa de frequencia mhz",
            "faixa de frequencias mhz",
            "frequency range mhz",
            "frequency range",
        ],
        "potencia_max_saida": [
            "potencia maxima de saida w",
            "potencia maxima saida w",
            "potencia maxima de saida",
            "potencia maxima saida",
            "saida maximum power w",
            "maximum power w",
            "maximum power",
            "output power w",
            "output power",
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
    texto = _normalizar_texto_tabela(valor)

    if not texto:
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
            return f"{inicio}-{fim}"

    if len(numeros) == 1:
        return _normalizar_decimal_tabela(numeros[0])

    return texto.replace(" ", "")


def _normalizar_potencia_tabela(valor):
    texto = _normalizar_texto_tabela(valor)
    texto = texto.replace("w", "").strip()

    numeros = re.findall(r"\d[\d.,]*", texto)

    if numeros:
        return _normalizar_decimal_tabela(numeros[0])

    return texto



def _normalizar_valor_tabela_por_campo(campo, valor):
    texto = _normalizar_texto_tabela(valor)

    if not texto:
        return ""

    if campo == "faixa_freq_tx":
        return _normalizar_faixa_frequencia_tabela(valor)

    if campo == "potencia_max_saida":
        return _normalizar_potencia_tabela(valor)

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

def _mapear_colunas_relevantes(cabecalho):
    mapeamento = {}

    for idx, col in enumerate(cabecalho or []):
        canonico = _cabecalho_canonico(col)
        if canonico and canonico not in mapeamento:
            mapeamento[canonico] = idx

    return mapeamento


def _extrair_linhas_comparaveis(tabela):
    tabela = tabela or {}
    cabecalho = list(tabela.get("cabecalho", []) or [])
    linhas = [list(l) for l in (tabela.get("linhas", []) or [])]

    mapa_colunas = _mapear_colunas_relevantes(cabecalho)

    campos_alvo = [
        "faixa_freq_tx",
        "potencia_max_saida",
        "designacao_emissoes",
        "tecnologias",
        "tipo_modulacao",
    ]

    linhas_saida = []
    for linha in linhas:
        registro = {}
        for campo in campos_alvo:
            idx = mapa_colunas.get(campo)
            valor = linha[idx] if idx is not None and idx < len(linha) else ""
            registro[campo] = _normalizar_valor_tabela_por_campo(campo, valor)

        if any(registro.values()):
            linhas_saida.append(registro)

    return linhas_saida


def _assinatura_linha_tabela(registro):
    return (
        registro.get("faixa_freq_tx", ""),
        registro.get("potencia_max_saida", ""),
        registro.get("designacao_emissoes", ""),
        registro.get("tecnologias", ""),
        registro.get("tipo_modulacao", ""),
    )


def comparar_tabelas_tecnicas_sch_cct(tabela_sch, tabela_cct):
    linhas_sch = _extrair_linhas_comparaveis(tabela_sch)
    linhas_cct = _extrair_linhas_comparaveis(tabela_cct)

    if not linhas_sch and not linhas_cct:
        return {
            "status": "sem_tabela",
            "motivo": "nenhuma_tabela_disponivel",
            "divergencias": [],
        }

    linhas_sch_ord = sorted(linhas_sch, key=_assinatura_linha_tabela)
    linhas_cct_ord = sorted(linhas_cct, key=_assinatura_linha_tabela)

    divergencias = []

    if len(linhas_sch_ord) != len(linhas_cct_ord):
        divergencias.append(
            {
                "tipo": "quantidade_linhas_diferente",
                "linhas_sch": len(linhas_sch_ord),
                "linhas_cct": len(linhas_cct_ord),
            }
        )

    total = min(len(linhas_sch_ord), len(linhas_cct_ord))
    campos = [
        ("faixa_freq_tx", "Faixa de Frequências Tx (MHz)"),
        ("potencia_max_saida", "Potência Máxima de Saída (W)"),
        ("designacao_emissoes", "Designação de Emissões"),
        ("tecnologias", "Tecnologias"),
        ("tipo_modulacao", "Tipo de Modulação"),
    ]

    for i in range(total):
        sch = linhas_sch_ord[i]
        cct = linhas_cct_ord[i]

        for chave, nome_coluna in campos:
            valor_sch = sch.get(chave, "")
            valor_cct = cct.get(chave, "")

            if valor_sch != valor_cct:
                divergencias.append(
                    {
                        "tipo": "valor_diferente",
                        "linha": i + 1,
                        "coluna": nome_coluna,
                        "nome_coluna": nome_coluna,
                        "valor_sch": valor_sch,
                        "valor_cct": valor_cct,
                    }
                )

    return {
        "status": "ok" if not divergencias else "divergente",
        "linhas_sch": len(linhas_sch_ord),
        "linhas_cct": len(linhas_cct_ord),
        "campos_comparados": [
            "Faixa de Frequências Tx (MHz)",
            "Potência Máxima de Saída (W)",
            "Designação de Emissões",
            "Tecnologias",
            "Tipo de Modulação",
        ],
        "colunas_ignoradas_do_cct": [
            "SAR Cabeça / SAR head",
            "SAR Corpo / SAR body",
            "Padrão / Standard",
            "Taxa de transmissão / Transmission rate",
        ],
        "divergencias": divergencias,
    }


def extrair_tabela_tecnica_sch(driver, wait):
    clicar_aba_caracteristicas_tecnicas(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    xpaths_tabela = [
        "//table[.//th[contains(., 'Faixa')] and .//th[contains(., 'Pot')]]",
        "//table[.//th[contains(., 'Frequ')] and .//th[contains(., 'Emiss')]]",
        "//table[.//td[contains(., 'Faixa')] and .//td[contains(., 'Pot')]]",
        "//table[.//td[contains(., 'Frequ')] and .//td[contains(., 'Emiss')]]",
    ]

    tabela = None
    for xp in xpaths_tabela:
        try:
            tabela = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            break
        except Exception:
            continue

    if tabela is None:
        return {"cabecalho": [], "linhas": []}

    trs = tabela.find_elements(By.XPATH, ".//tr")
    if not trs:
        return {"cabecalho": [], "linhas": []}

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


def _normalizar_cabecalho_tabela_sch(texto):
    texto = _texto_limpo(texto)
    texto = _remover_acentos(texto).lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _eh_linha_cabecalho_tabela_sch(celulas):
    if not celulas:
        return False

    texto = " | ".join(_normalizar_cabecalho_tabela_sch(c) for c in celulas if c)
    sinais = [
        "faixa",
        "frequencia",
        "potencia",
        "emissao",
        "tecnologia",
        "modulacao",
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

    # No SCH queremos só as 5 colunas comparáveis
    max_colunas_comparaveis = 5
    cabecalho = cabecalho[:max_colunas_comparaveis]
    linhas = [linha[:max_colunas_comparaveis] for linha in linhas]

    return {
        "cabecalho": cabecalho,
        "linhas": [linha for linha in linhas if any(_texto_limpo(c) for c in linha)],
    }


def comparar_dados_sch_x_cct(req, dados_pdf):
    req = req or {}
    dados_pdf = dados_pdf or {}

    homologacao_sch = req.get("homologacao", "")
    homologacao_cct = dados_pdf.get("homologacao", "")

    homologacoes_vinculadas = dados_pdf.get("homologacoes_vinculadas", []) or []

    codigos_vinculados = {
        item.get("codigo_anatel")
        for item in homologacoes_vinculadas
        if isinstance(item, dict) and item.get("codigo_anatel")
    }

    homologacao_sch_norm = _normalizar_numero_comparacao(homologacao_sch)

    homologacao_sch_esta_em_vinculadas = any(
        homologacao_sch_norm == _normalizar_numero_comparacao(codigo)
        for codigo in codigos_vinculados
    )

    if homologacao_sch_esta_em_vinculadas and not homologacao_cct:
        comparacao_homologacao = {
            "campo": "homologacao",
            "status": "homologacao_vinculada_no_cct",
            "valor_sch": homologacao_sch,
            "valor_cct": "",
            "valor_sch_normalizado": homologacao_sch_norm,
            "valor_cct_normalizado": "",
            "diverge": False,
            "observacao": (
                "A homologação informada no SCH foi encontrada no CCT apenas como "
                "homologação vinculada/informativa, não como homologação principal."
            ),
            "homologacoes_vinculadas": homologacoes_vinculadas,
        }
    else:
        comparacao_homologacao = _comparar_valores(
            homologacao_sch,
            homologacao_cct,
            "homologacao",
            modo="numero",
        )

    comparacoes = [
        _comparar_valores(
            req.get("certificado", ""),
            dados_pdf.get("numero_certificado", ""),
            "certificado",
            modo="texto_flex",
        ),
        comparacao_homologacao,
        _comparar_valores(
            req.get("modelo", ""),
            dados_pdf.get("modelo", ""),
            "modelo",
            modo="texto",
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
        "homologacoes_vinculadas_cct": homologacoes_vinculadas,
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



def escolher_titulo_caracteristicas_secundarias(req=None, dados_pdf=None):
    """
    Decide qual frase preencher no campo:
    'Título/Descrição para Características Técnicas Secundárias'.

    Retorna "" quando não houver segurança para preencher.
    """
    req = req or {}
    dados_pdf = dados_pdf or {}
    texto_completo = str(
        dados_pdf.get("texto_caracteristicas_secundarias") or ""
    ).strip()

    if texto_completo:
        return texto_completo 
    
    
    caracteristicas_sec = dados_pdf.get("caracteristicas_secundarias") or {}
    titulo_detectado = str(caracteristicas_sec.get("titulo") or "").strip()

    if titulo_detectado:
        return titulo_detectado

    titulo_direto = str(dados_pdf.get("titulo_caracteristicas_secundarias") or "").strip()

    if titulo_direto:
        return titulo_direto

    texto_base = " ".join(
        [
            _texto_total_dados_pdf(req),
            _texto_total_dados_pdf(dados_pdf),
        ]
    )

    texto = _normalizar_texto_comparacao(texto_base)

    regras = [
        (
            ["carregador indutivo", "wireless charger"],
            "O produto incorpora um módulo “Carregador Indutivo para Telefone Celular” com as seguintes características técnicas:",
        ),
        (
            ["dispositivo de operacao periodica", "periodic operation device"],
            "O produto incorpora um módulo “Dispositivo de Operação Periódica” com as seguintes características técnicas:",
        ),
        (
            ["estacao terminal de acesso", "terminal de acesso", "access terminal"],
            'O produto incorpora um módulo "Estação Terminal de Acesso" com as seguintes características:',
        ),
        (
            ["sistema de identificacao por radiofrequencias", "identificacao por radiofrequencias", "rfid"],
            "O produto incorpora Sistema de Identificação por Radiofrequências com as seguintes características:",
        ),
        (
            ["ultra larga", "uwb", "ultra wideband"],
            "O produto incorpora Sistemas Operando nas Faixas de RF Ultra Larga com as seguintes características:",
        ),
        (
            ["transceptor mpo", "mpo"],
            "O produto incorpora Transceptor Mpo com as seguintes características:",
        ),
        (
            ["sistema automatico de identificacao de navios", "ais", "navios"],
            "O produto incorpora Transceptor para Sistema Automático de Identificação de Navios com as seguintes características:",
        ),
        (
            ["transceptor movel por satelite", "movel por satelite", "satellite"],
            "O produto incorpora Transceptor Móvel por Satélite com as seguintes características:",
        ),
        (
            ["aplicacoes medicas", "aplicacao medica", "medical"],
            "O produto incorpora Sistema de Aplicações Médicas com as seguintes características:",
        ),
        (
            ["transceptor de radiacao restrita", "transceptor"],
            "O produto incorpora Transceptor de Radiação Restrita com as seguintes características:",
        ),
        (
            [
                "equipamento de radiocomunicacao de radiacao restrita",
                "radiocomunicacao de radiacao restrita",
                "radiacao restrita",
            ],
            "O produto incorpora Equipamento de Radiocomunicação de Radiação Restrita com as seguintes características:",
        ),
    ]

    for termos, frase in regras:
        if any(termo in texto for termo in termos):
            return frase

    return ""


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
    Preenche o campo de Características Técnicas Secundárias sempre substituindo
    qualquer texto existente pelo texto gerado pela automação.

    Mantém o mesmo nome da função para não precisar alterar quem chama.
    """
    texto = str(texto or "").strip()

    if not texto:
        return {
            "preenchido": False,
            "motivo": "texto_vazio",
        }

    try:
        valor_atual = driver.execute_script(
            """
            return (
                arguments[0].value ||
                arguments[0].innerText ||
                arguments[0].textContent ||
                ''
            ).trim();
            """,
            campo,
        ) or ""
    except Exception:
        valor_atual = ""

    tag = (campo.tag_name or "").lower()

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        campo,
    )

    try:
        _clicar_com_fallback(driver, campo)
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
                const el = arguments[0];
                const valor = arguments[1];

                el.focus();

                const proto = Object.getPrototypeOf(el);
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');

                if (desc && desc.set) {
                    desc.set.call(el, valor);
                } else {
                    el.value = valor;
                }

                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                el.dispatchEvent(new Event('blur', {bubbles:true}));
                """,
                campo,
                texto,
            )

    else:
        html = texto.replace("\n", "<br>")

        driver.execute_script(
            """
            const el = arguments[0];
            const html = arguments[1];

            el.focus();
            el.innerHTML = html;

            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new Event('blur', {bubbles:true}));
            """,
            campo,
            html,
        )

    try:
        campo.send_keys(Keys.TAB)
    except Exception:
        pass

    try:
        valor_final = driver.execute_script(
            """
            return (
                arguments[0].value ||
                arguments[0].innerText ||
                arguments[0].textContent ||
                ''
            ).trim();
            """,
            campo,
        ) or ""
    except Exception:
        valor_final = ""

    return {
        "preenchido": True,
        "motivo": "substituido",
        "texto": texto,
        "valor_anterior": valor_atual,
        "valor_final": valor_final,
        "substituiu_texto_existente": bool(str(valor_atual or "").strip()),
    }


def preencher_titulo_caracteristicas_secundarias_se_existir(driver, wait, req=None, dados_pdf=None):
    """
    Preenche o campo opcional:
    'Título/Descrição para Características Técnicas Secundárias'.

    Se o campo já tiver texto, a automação substitui pelo texto gerado.
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
            "motivo": "Campo de características técnicas secundárias não encontrado na tela.",
        }

    texto_caracteristicas = escolher_titulo_caracteristicas_secundarias(
        req=req,
        dados_pdf=dados_pdf,
    )

    if not texto_caracteristicas:
        print(
            "[SCH][WARN] Campo de características secundárias encontrado, "
            "mas sem texto seguro para preencher."
        )

        return {
            "campo_encontrado": True,
            "preenchido": False,
            "status": "revisar",
            "motivo": (
                "Campo encontrado, mas a automação não identificou texto seguro "
                "para preenchimento."
            ),
        }

    resultado = _preencher_campo_sem_apagar_se_ja_tem_valor(
        driver,
        campo,
        texto_caracteristicas,
    )

    if resultado.get("preenchido"):
        if resultado.get("substituiu_texto_existente"):
            print(
                "[SCH] Características Técnicas Secundárias substituídas "
                "pelo texto da automação."
            )
        else:
            print(
                "[SCH] Características Técnicas Secundárias preenchidas "
                "pela automação."
            )

        print(
            "[SCH] Texto aplicado em Características Técnicas Secundárias:",
            texto_caracteristicas[:500],
        )

    else:
        print(
            "[SCH] Características Técnicas Secundárias não preenchidas: "
            f"{resultado.get('motivo')}"
        )

    resultado.update(
        {
            "campo_encontrado": True,
            "status": "preenchido" if resultado.get("preenchido") else "nao_alterado",
            "texto_gerado": texto_caracteristicas,
        }
    )

    return resultado




def salvar_caracteristicas_tecnicas(driver, wait, texto_esperado=""):
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

    if confirmado:
        print("[SCH] Características Técnicas salvas e conferidas com sucesso.")
    else:
        print("[SCH][WARN] Características Técnicas salvas, mas não foi possível confirmar o texto após salvar.")

    return {
        "salvo": True,
        "confirmado_apos_salvar": confirmado,
    }


FRASE_SAR_NAO_APLICAVEL = (
    "Ensaio de SAR não aplicável"
)

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


def analisar_sar_cct(dados_pdf):
    dados_pdf = dados_pdf or {}

    tem_frase_nao_aplicavel = _dados_pdf_tem_frase_sar_nao_aplicavel(dados_pdf)
    tem_coluna_sar = _dados_pdf_tem_coluna_sar(dados_pdf)
    tem_valor_sar = _dados_pdf_tem_valor_sar(dados_pdf)
    tem_ato_1630 = _dados_pdf_tem_ato_1630(dados_pdf)
    produto_nao_acabado = _dados_pdf_indica_produto_nao_acabado(dados_pdf)

    frase_sar = _extrair_frase_sar_nao_aplicavel(dados_pdf)

    if tem_coluna_sar and not tem_valor_sar:
        return {
            "status": "sar_nao_aplicavel_coluna_sem_valor",
            "sar_aplicavel": False,
            "ato_1630_presente": tem_ato_1630,
            "preencher_frase": True,
            "frase": frase_sar or FRASE_SAR_NAO_APLICAVEL,
            "mensagem": (
                "A tabela possui coluna SAR, mas os campos de SAR não possuem valor real "
                "ou estão preenchidos com '-'. SAR tratado como não aplicável."
        ),
    }

    if tem_frase_nao_aplicavel:
        return {
            "status": "sar_nao_aplicavel",
            "sar_aplicavel": False,
            "ato_1630_presente": tem_ato_1630,
            "preencher_frase": True,
            "frase": frase_sar,
            "mensagem": "Foi identificado no CCT que o ensaio de SAR não é aplicável.",
        }

    if produto_nao_acabado:
        return {
            "status": "sar_nao_aplicavel_produto_nao_acabado",
            "sar_aplicavel": False,
            "ato_1630_presente": tem_ato_1630,
            "preencher_frase": True,
            "frase": FRASE_SAR_NAO_APLICAVEL,
            "mensagem": "Produto não acabado/uso interno identificado. SAR tratado como não aplicável.",
        }

    if not tem_coluna_sar:
        return {
            "status": "sar_nao_aplicavel_sem_coluna",
            "sar_aplicavel": False,
            "ato_1630_presente": tem_ato_1630,
            "preencher_frase": True,
            "frase": FRASE_SAR_NAO_APLICAVEL,
            "mensagem": "Não foi identificada coluna SAR na tabela técnica do CCT. SAR tratado como não aplicável.",
        }

    if tem_coluna_sar and not tem_valor_sar:
        return {
            "status": "sar_coluna_sem_valor_revisar",
            "sar_aplicavel": None,
            "ato_1630_presente": tem_ato_1630,
            "preencher_frase": False,
            "frase": "",
            "mensagem": (
                "A tabela possui coluna SAR, mas não há valor preenchido. "
                "Como o CCT não trouxe frase de SAR não aplicável, revisar manualmente."
            ),
        }

    if tem_valor_sar and tem_ato_1630:
        return {
            "status": "sar_aplicavel_com_ato_1630",
            "sar_aplicavel": True,
            "ato_1630_presente": True,
            "preencher_frase": False,
            "frase": "",
            "mensagem": (
                "Foram encontrados valores de SAR no CCT e o Ato nº 1630 está presente. "
                "A frase de SAR não aplicável não será inserida."
            ),
        }

    if tem_valor_sar and not tem_ato_1630:
        return {
            "status": "sar_aplicavel_sem_ato_1630",
            "sar_aplicavel": True,
            "ato_1630_presente": False,
            "preencher_frase": False,
            "frase": "",
            "mensagem": (
                "Foram encontrados valores de SAR no CCT, mas o Ato nº 1630 não consta. "
                "Não preencher 'SAR não aplicável'; gerar alerta para revisão/NC."
            ),
        }

    return {
        "status": "nao_identificado",
        "sar_aplicavel": None,
        "ato_1630_presente": tem_ato_1630,
        "preencher_frase": False,
        "frase": "",
        "mensagem": "Não foi possível determinar automaticamente a aplicabilidade de SAR.",
    }


def _ha_campo_corrigir_minuta(driver):
    xpaths = [
        "//textarea[not(@disabled)]",
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//iframe",
        "//*[contains(normalize-space(), 'Minuta')]",
        "//*[contains(normalize-space(), 'Corrigir Minuta')]",
    ]

    for xp in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xp)
            if any(el.is_displayed() for el in elementos):
                return True
        except Exception:
            continue

    return False


def clicar_corrigir_minuta(driver, wait):
    print("[SCH] Abrindo Corrigir Minuta...")

    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Corrigir Minuta",
        rotulos_alternativos=[
            "Minuta",
            "Corrigir minuta",
            "Correção da Minuta",
            "Correcao da Minuta",
        ],
        condicao_pronta=_ha_campo_corrigir_minuta,
        timeout_click=2.0,
        timeout_pronta=2.0,
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



def _capturar_alerta_se_existir(driver, timeout=1.5):
    try:
        alert = WebDriverWait(driver, timeout).until(EC.alert_is_present())
        texto = alert.text or ""
        print(f"[SCH] Alerta após salvar: {texto}")
        alert.accept()
        esperar_tela_carregar(driver, 0.2)
        return texto
    except Exception:
        return ""


def _texto_visivel_pagina_e_iframe(driver):
    textos = []

    try:
        driver.switch_to.default_content()
        body = driver.find_element(By.TAG_NAME, "body")
        textos.append(body.text or "")
    except Exception:
        pass

    try:
        driver.switch_to.default_content()
        iframe = driver.find_element(By.XPATH, XPATH_IFRAME_DETALHE)
        driver.switch_to.frame(iframe)

        body = driver.find_element(By.TAG_NAME, "body")
        textos.append(body.text or "")
    except Exception:
        pass

    return "\n".join(textos)


def _detectar_resultado_salvamento_minuta(driver, alerta_texto=""):
    texto_total = "\n".join(
        [
            str(alerta_texto or ""),
            _texto_visivel_pagina_e_iframe(driver),
        ]
    )

    texto_norm = _normalizar_texto_comparacao(texto_total)

    termos_sucesso = [
        "salvo com sucesso",
        "salva com sucesso",
        "gravado com sucesso",
        "alterado com sucesso",
        "alteracao realizada com sucesso",
        "alterações realizadas com sucesso",
        "alteracoes realizadas com sucesso",
        "operacao realizada com sucesso",
        "operação realizada com sucesso",
        "registro salvo com sucesso",
        "registro alterado com sucesso",
        "dados salvos com sucesso",
    ]

    termos_bloqueio = [
        "erro ao salvar",
        "falha ao salvar",
        "nao foi possivel salvar",
        "não foi possível salvar",
        "operacao nao realizada",
        "operação não realizada",
        "nao permitido",
        "não permitido",
        "nao permite",
        "não permite",
        "campo obrigatorio",
        "campo obrigatório",
        "preenchimento obrigatorio",
        "preenchimento obrigatório",
        "corrija",
        "inconsistencia",
        "inconsistência",
        "inconsistente",
        "data invalida",
        "data inválida",
        "periodo invalido",
        "período inválido",
        "validade invalida",
        "validade inválida",
        "data de validade invalida",
        "data de validade inválida",
        "data do certificado invalida",
        "data do certificado inválida",
        "data de emissao invalida",
        "data de emissão inválida",
        "certificado vencido",
        "a data",
        "as datas",
    ]

    sucesso = any(_normalizar_texto_comparacao(t) in texto_norm for t in termos_sucesso)
    bloqueio = any(_normalizar_texto_comparacao(t) in texto_norm for t in termos_bloqueio)

    return {
        "sucesso": sucesso,
        "bloqueio": bloqueio,
        "texto_detectado": texto_total[:2000],
    }


def _confirmar_texto_minuta_no_campo(driver, wait, texto_esperado):
    if not texto_esperado:
        return False

    texto_esperado_norm = _normalizar_texto_comparacao(texto_esperado)

    try:
        entrar_iframe_detalhe_analise(driver, wait)
    except Exception:
        pass

    xpaths_validacao = [
        "//textarea[not(@disabled)]",
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//input[not(@disabled)]",
    ]

    for xpath in xpaths_validacao:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for el in elementos:
                try:
                    if not el.is_displayed():
                        continue

                    valor = driver.execute_script(
                        """
                        return (
                            arguments[0].value ||
                            arguments[0].innerText ||
                            arguments[0].textContent ||
                            ''
                        ).trim();
                        """,
                        el,
                    ) or ""

                    if texto_esperado_norm in _normalizar_texto_comparacao(valor):
                        return True

                except Exception:
                    continue

        except Exception:
            continue

    return False



def salvar_minuta_corrigida(driver, wait, texto_esperado=""):
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
        print("[SCH][WARN] Botão Salvar não encontrado em Corrigir Minuta.")
        return {
            "salvo": False,
            "confirmado_apos_salvar": False,
            "status": "botao_salvar_nao_encontrado",
            "motivo": "Botão Salvar não encontrado em Corrigir Minuta.",
        }

    print("[SCH] Salvando Corrigir Minuta...")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        botao_salvar,
    )

    _clicar_com_fallback(driver, botao_salvar)

    esperar_tela_carregar(driver, 0.4)

    alerta_texto = _capturar_alerta_se_existir(driver, timeout=1.5)

    esperar_tela_carregar(driver, 0.4)

    resultado_sistema = _detectar_resultado_salvamento_minuta(
        driver,
        alerta_texto=alerta_texto,
    )

    confirmado = _confirmar_texto_minuta_no_campo(
        driver,
        wait,
        texto_esperado,
    )

    if resultado_sistema.get("bloqueio"):
        print(
            "[SCH][WARN] Corrigir Minuta NÃO foi considerada salva, "
            "pois o sistema indicou bloqueio/erro no salvamento."
        )

        return {
            "salvo": False,
            "confirmado_apos_salvar": confirmado,
            "status": "bloqueado_pelo_sistema",
            "motivo": "O SCH indicou erro/bloqueio ao tentar salvar a Corrigir Minuta.",
            "alerta": alerta_texto,
            "mensagem_sistema": resultado_sistema.get("texto_detectado", ""),
        }

    if resultado_sistema.get("sucesso") and confirmado:
        print("[SCH] Corrigir Minuta salva e confirmada com sucesso.")

        return {
            "salvo": True,
            "confirmado_apos_salvar": True,
            "status": "salvo_confirmado",
            "motivo": "O SCH retornou mensagem de sucesso e o texto foi confirmado no campo.",
            "alerta": alerta_texto,
            "mensagem_sistema": resultado_sistema.get("texto_detectado", ""),
        }

    if confirmado and not resultado_sistema.get("sucesso"):
        print(
            "[SCH][WARN] Texto encontrado no campo, mas o SCH não confirmou "
            "o salvamento. Não será marcado como salvo."
        )

        return {
            "salvo": False,
            "confirmado_apos_salvar": True,
            "status": "texto_na_tela_sem_confirmacao_de_salvamento",
            "motivo": (
                "O texto ficou visível no campo, mas o sistema não retornou "
                "mensagem confiável de sucesso."
            ),
            "alerta": alerta_texto,
            "mensagem_sistema": resultado_sistema.get("texto_detectado", ""),
        }

    print(
        "[SCH][WARN] Corrigir Minuta não foi confirmada após salvar. "
        "Não será marcada como salva."
    )

    return {
        "salvo": False,
        "confirmado_apos_salvar": False,
        "status": "nao_confirmado",
        "motivo": "Não houve confirmação confiável de salvamento.",
        "alerta": alerta_texto,
        "mensagem_sistema": resultado_sistema.get("texto_detectado", ""),
    }


def voltar_da_tela_corrigir_minuta(driver, wait):
    """
    Sai da tela Corrigir Minuta e volta para a tela principal do requerimento.
    """
    print("[SCH] Voltando da tela Corrigir Minuta...")

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.15)

    xpaths_voltar = [
        "//button[normalize-space()='Voltar']",
        "//a[normalize-space()='Voltar']",
        "//span[normalize-space()='Voltar']/ancestor::button[1]",
        "//span[normalize-space()='Voltar']/ancestor::a[1]",
        "//*[@title='Voltar']",
        "//*[self::a or self::button][contains(normalize-space(), 'Voltar')]",
        "//input[@type='button' and contains(@value,'Voltar')]",
    ]

    ultimo_erro = None

    for xpath in xpaths_voltar:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)

            for botao in elementos:
                try:
                    if not botao.is_displayed() or not botao.is_enabled():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        botao,
                    )

                    _clicar_com_fallback(driver, botao)
                    esperar_tela_carregar(driver, 0.8)

                    print("[SCH] Retorno da tela Corrigir Minuta concluído.")
                    return True

                except Exception as e:
                    ultimo_erro = e
                    continue

        except Exception as e:
            ultimo_erro = e
            continue

    print(f"[SCH][WARN] Não foi possível clicar em Voltar na Corrigir Minuta. Último erro: {ultimo_erro}")
    return False



def _localizar_campo_especificacoes_complementares_minuta(driver):
    """
    Localiza o campo 'Especificações Complementares' dentro da seção 'Especificação'
    da aba Corrigir Minuta.
    """
    xpaths = [
        "//*[contains(normalize-space(), 'Especificações Complementares')]/following::textarea[1]",
        "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::textarea[1]",

        "//*[contains(normalize-space(), 'Especificações Complementares')]/following::*[@contenteditable='true'][1]",
        "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::*[@contenteditable='true'][1]",

        "//*[contains(normalize-space(), 'Especificações Complementares')]/following::div[contains(@class,'ql-editor')][1]",
        "//*[contains(normalize-space(), 'Especificacoes Complementares')]/following::div[contains(@class,'ql-editor')][1]",
    ]

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


def abrir_secao_especificacao_minuta(driver, wait):
    """
    Na aba Corrigir Minuta, abre a seção 'Especificação'
    para acessar 'Especificações Complementares'.
    """
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.08)

    campo = _localizar_campo_especificacoes_complementares_minuta(driver)
    if campo:
        return True

    xpaths_rotulo = [
        "//*[normalize-space()='Especificação']",
        "//*[normalize-space()='Especificacao']",
        "//*[contains(normalize-space(), 'Especificação')]",
        "//*[contains(normalize-space(), 'Especificacao')]",
    ]

    ultimo_erro = None

    for xpath in xpaths_rotulo:
        try:
            rotulos = driver.find_elements(By.XPATH, xpath)

            for rotulo in rotulos:
                try:
                    if not rotulo.is_displayed():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        rotulo,
                    )

                    esperar_tela_carregar(driver, 0.05)

                    try:
                        _clicar_com_fallback(driver, rotulo)
                    except Exception:
                        driver.execute_script("arguments[0].click();", rotulo)

                    esperar_tela_carregar(driver, 0.25)

                    campo = _localizar_campo_especificacoes_complementares_minuta(driver)
                    if campo:
                        print("[SCH] Seção 'Especificação' da minuta aberta.")
                        return True

                    try:
                        linha = rotulo.find_element(
                            By.XPATH,
                            "./ancestor::*[self::tr or self::div or self::li][1]"
                        )
                    except Exception:
                        linha = rotulo

                    candidatos = linha.find_elements(
                        By.XPATH,
                        ".//*[self::a or self::button or self::span or self::input][not(@disabled)]"
                    )

                    for candidato in candidatos:
                        try:
                            if not candidato.is_displayed():
                                continue

                            texto_candidato = " ".join(
                                [
                                    candidato.text or "",
                                    candidato.get_attribute("title") or "",
                                    candidato.get_attribute("class") or "",
                                    candidato.get_attribute("value") or "",
                                ]
                            ).lower()

                            if (
                                "+"
                                in texto_candidato
                                or "plus" in texto_candidato
                                or "expand" in texto_candidato
                                or "ui-icon" in texto_candidato
                            ):
                                _clicar_com_fallback(driver, candidato)
                                esperar_tela_carregar(driver, 0.25)

                                campo = _localizar_campo_especificacoes_complementares_minuta(driver)
                                if campo:
                                    print("[SCH] Seção 'Especificação' da minuta aberta pelo botão '+'.")
                                    return True

                        except Exception as e:
                            ultimo_erro = e
                            continue

                except Exception as e:
                    ultimo_erro = e
                    continue

        except Exception as e:
            ultimo_erro = e
            continue

    print(
        "[SCH][WARN] Não foi possível abrir a seção 'Especificação' da minuta. "
        f"Último erro: {ultimo_erro}"
    )

    return False



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
        analise["resultado_salvamento"] = {
            "salvo": False,
            "confirmado_apos_salvar": False,
            "status": "sem_frase_para_preencher",
            "motivo": "A análise SAR não indicou necessidade de preencher frase na minuta.",
        }
        return analise

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
        ) or {}

        retornou_minuta = voltar_da_tela_corrigir_minuta(driver, wait)

        salvo_ok = bool(resultado_salvar.get("salvo"))
        confirmado_ok = bool(resultado_salvar.get("confirmado_apos_salvar"))

        if salvo_ok and confirmado_ok:
            status_final = "preenchido"

            mensagem_final = (
                "A frase de SAR foi preenchida, salva e confirmada na Corrigir Minuta."
            )

        elif preenchido and not salvo_ok:
            status_final = "preenchido_na_tela_mas_nao_salvo"

            mensagem_final = (
                "A frase de SAR foi inserida na tela da Corrigir Minuta, "
                "mas o SCH não confirmou o salvamento. Verificar manualmente, "
                "principalmente possíveis bloqueios relacionados a datas do certificado/validade."
            )

        else:
            status_final = "nao_salvo"

            mensagem_final = (
                "A frase de SAR não foi salva na Corrigir Minuta. "
                "Verificar manualmente."
            )

        analise["status"] = status_final
        analise["preenchido_automaticamente"] = bool(preenchido)
        analise["salvo"] = salvo_ok
        analise["confirmado_apos_salvar"] = confirmado_ok
        analise["retornou_para_requerimento"] = bool(retornou_minuta)
        analise["resultado_salvamento"] = resultado_salvar
        analise["mensagem"] = mensagem_final

        if not salvo_ok:
            analise["erro_salvamento"] = {
                "status": resultado_salvar.get("status", ""),
                "motivo": resultado_salvar.get("motivo", ""),
                "alerta": resultado_salvar.get("alerta", ""),
                "mensagem_sistema": resultado_salvar.get("mensagem_sistema", ""),
            }

            print(
                "[SCH][WARN] Corrigir Minuta não foi marcada como salva. "
                f"Status do salvamento: {resultado_salvar.get('status', 'não informado')}"
            )

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
        analise["resultado_salvamento"] = {
            "salvo": False,
            "confirmado_apos_salvar": False,
            "status": "erro_ao_preencher_minuta",
            "motivo": str(e),
        }
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
    print("[SCH] Abrindo aba Informações Adicionais...")
    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Informações Adicionais",
        rotulos_alternativos=["Informacoes Adicionais", "Informações", "Informacoes"],
        condicao_pronta=_ha_campo_informacoes_adicionais,
        timeout_click=1.2,
        timeout_pronta=1.2,
    )


TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES = (
    "Este processo foi analisado conforme Portaria n° 2257, "
    "de 03 de março de 2022 (Análise Simplificada)."
)


def _achar_primeiro_elemento_visivel(driver, xpaths, descricao, timeout=2):
    for xpath in xpaths:
        try:
            elementos = WebDriverWait(driver, timeout, poll_frequency=0.05).until(
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


def marcar_acompanhar_processo(driver, wait):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    checkbox_xpaths = [
        "//label[contains(normalize-space(), 'Desejo acompanhar este processo')]/preceding::input[@type='checkbox'][1]",
        "//label[contains(normalize-space(), 'Desejo acompanhar este processo')]/ancestor::*[1]//input[@type='checkbox'][1]",
        "//input[@type='checkbox'][contains(@name,'acompanh')]",
        "//input[@type='checkbox'][contains(@id,'acompanh')]",
        "(//input[@type='checkbox'])[1]",
    ]

    label_xpaths = [
        "//label[contains(normalize-space(), 'Desejo acompanhar este processo')]",
        "//*[contains(normalize-space(), 'Desejo acompanhar este processo')]",
    ]

    checkbox = None

    for xpath in checkbox_xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
            for el in elementos:
                try:
                    if el.is_displayed():
                        checkbox = el
                        break
                except Exception:
                    continue
            if checkbox:
                break
        except Exception:
            continue

    if checkbox and _checkbox_esta_marcado(checkbox):
        print("[SCH] Opção 'Desejo acompanhar este processo' já está marcada.")
        return True

    alvo_clique = checkbox or _achar_primeiro_elemento_visivel(
        driver,
        label_xpaths,
        "checkbox/label de acompanhar processo",
        timeout=3,
    )

    _clicar_com_fallback(driver, alvo_clique)
    esperar_tela_carregar(driver, 0.04)

    entrar_iframe_detalhe_analise(driver, wait)

    for xpath in checkbox_xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
            for el in elementos:
                try:
                    if el.is_displayed() and _checkbox_esta_marcado(el):
                        print("[SCH] Opção 'Desejo acompanhar este processo' marcada com sucesso.")
                        return True
                except Exception:
                    continue
        except Exception:
            continue

    print("[SCH][WARN] Não foi possível validar visualmente a marcação do acompanhamento.")
    return False



def _localizar_campo_acompanhar_processo(driver, timeout=4):
    """
    Localiza o campo de texto do bloco 'Acompanhar Processo',
    evitando confundir com o campo '*Descrição' de Informações Adicionais.
    """

    def _buscar_por_js(d):
        script = """
        function visivel(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (!st) return false;
            if (st.display === 'none') return false;
            if (st.visibility === 'hidden') return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }

        const todos = Array.from(document.querySelectorAll('body *'));

        const blocoAcompanhar = todos.find(el => {
            const txt = (el.innerText || el.textContent || '').trim();
            return visivel(el) && txt.includes('Acompanhar Processo');
        });

        const blocoInfo = todos.find(el => {
            const txt = (el.innerText || el.textContent || '').trim();
            return visivel(el) && txt.includes('Informações Adicionais');
        });

        const textareas = Array.from(document.querySelectorAll('textarea'))
            .filter(el => visivel(el) && !el.disabled && !el.readOnly);

        if (!textareas.length) return null;

        if (blocoAcompanhar) {
            const rAcomp = blocoAcompanhar.getBoundingClientRect();
            const rInfo = blocoInfo ? blocoInfo.getBoundingClientRect() : null;

            const candidatos = textareas.filter(t => {
                const r = t.getBoundingClientRect();
                const abaixoAcompanhar = r.top >= rAcomp.bottom - 5;
                const acimaInfo = !rInfo || r.top < rInfo.top;
                return abaixoAcompanhar && acimaInfo;
            });

            if (candidatos.length) {
                candidatos.sort((a, b) => {
                    return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
                });
                return candidatos[0];
            }
        }

        return textareas[0];
        """

        try:
            return d.execute_script(script)
        except Exception:
            return None

    try:
        entrar_iframe_detalhe_analise(driver, None)
    except Exception:
        pass

    try:
        campo = WebDriverWait(driver, timeout, poll_frequency=0.05).until(
            lambda d: _buscar_por_js(d)
        )
        if campo:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                campo,
            )
            return campo
    except Exception:
        pass

    xpaths = [
        "//*[contains(normalize-space(), 'Desejo acompanhar este processo')]/following::textarea[1]",
        "//*[contains(normalize-space(), 'Acompanhar Processo')]/following::textarea[1]",
        "//textarea[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
        "//textarea[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'acompanh')]",
    ]

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



def _preencher_campo_textarea_js(driver, campo, texto):
    texto = str(texto or "").strip()

    if not texto:
        return False

    driver.execute_script(
        """
        const el = arguments[0];
        const valor = arguments[1];

        el.focus();

        if ('value' in el) {
            const proto = Object.getPrototypeOf(el);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');

            if (desc && desc.set) {
                desc.set.call(el, valor);
            } else {
                el.value = valor;
            }
        } else {
            el.textContent = valor;
            el.innerText = valor;
        }

        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
        """,
        campo,
        texto,
    )

    try:
        campo.send_keys(Keys.TAB)
    except Exception:
        pass

    valor = driver.execute_script(
        "return (arguments[0].value || arguments[0].innerText || arguments[0].textContent || '').trim();",
        campo,
    ) or ""

    return texto in valor




def preencher_acompanhar_processo(driver, wait, texto):
    if not texto:
        print("[SCH][WARN] Texto vazio para Acompanhar Processo.")
        return False

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    marcado = marcar_acompanhar_processo(driver, wait)

    if not marcado:
        print("[SCH][WARN] Não foi possível marcar 'Desejo acompanhar este processo'.")
        return False

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.08)

    campo = _localizar_campo_acompanhar_processo(driver, timeout=4)

    if not campo:
        print("[SCH][WARN] Campo de texto do Acompanhar Processo não encontrado.")
        return False

    print("[SCH] Preenchendo campo 'Acompanhar Processo'...")

    # Primeiro tenta por JS, que é mais confiável nesse tipo de tela.
    preenchido = _preencher_campo_textarea_js(driver, campo, texto)

    if preenchido:
        print("[SCH] Campo 'Acompanhar Processo' preenchido com sucesso.")
        return True

    # Fallback com teclado.
    try:
        _clicar_com_fallback(driver, campo)
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.DELETE)
        campo.send_keys(texto)

        esperar_tela_carregar(driver, 0.05)

        valor = driver.execute_script(
            "return (arguments[0].value || arguments[0].innerText || arguments[0].textContent || '').trim();",
            campo,
        ) or ""

        if texto.strip() in valor:
            print("[SCH] Campo 'Acompanhar Processo' preenchido com sucesso via teclado.")
            return True

    except Exception as e:
        print(f"[SCH][WARN] Falha no fallback por teclado do Acompanhar Processo: {e}")

    print("[SCH][WARN] O campo de acompanhamento não confirmou o texto após preenchimento.")
    return False

def salvar_informacoes_adicionais(driver, wait):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 0.04)

    xpaths_salvar = [
        "//button[normalize-space()='Salvar']",
        "//a[normalize-space()='Salvar']",
        "//span[normalize-space()='Salvar']/ancestor::button[1]",
        "//span[normalize-space()='Salvar']/ancestor::a[1]",
        "//*[@title='Salvar']",
        "//*[self::a or self::button][contains(normalize-space(), 'Salvar')]",
    ]

    botao = _achar_primeiro_elemento_visivel(
        driver,
        xpaths_salvar,
        "botão Salvar em Informações Adicionais",
        timeout=4,
    )

    _clicar_com_fallback(driver, botao)
    esperar_tela_carregar(driver, 0.10)

    print("[SCH] Informações Adicionais salvas.")
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

        preenchido = preencher_texto_informacoes_adicionais(
            driver,
            wait,
            texto,
        )

        if not preenchido:
            print(
                "[SCH][WARN] Informações Adicionais não serão salvas, "
                "pois o texto não foi confirmado no campo."
            )

            return {
                "texto": texto,
                "classificacao": "analise_simplificada_portaria_2257",
                "motivos": [],
                "preenchido_automaticamente": False,
                "acompanhar_processo_marcado": acompanhar_marcado,
                "salvo": False,
                "modo_preenchimento": "acompanhar_processo",
                "erro": "texto_nao_confirmado_no_campo",
            }

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

def voltar_para_fila(driver, wait):
    print("[SCH] Voltando para a fila...")

    if garantir_sessao_ativa_sch(
        driver,
        wait,
        contexto="ao tentar voltar para a fila",
        reabrir_fila=True,
    ):
        print("[SCH] Retorno para a fila concluído após refazer login.")
        return

    candidatos = [
        "//a[contains(., 'Voltar')]",
        "//button[contains(., 'Voltar')]",
        "//img[contains(@src,'voltar')]/..",
    ]

    driver.switch_to.default_content()

    for xpath in candidatos:
        try:
            botao = WebDriverWait(driver, 1.2, poll_frequency=0.08).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            _clicar_com_fallback(driver, botao)

            WebDriverWait(driver, 3, poll_frequency=0.08).until(
                EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
            )
            print("[SCH] Retorno para a fila concluído por botão.")
            return
        except Exception:
            continue

    try:
        driver.switch_to.default_content()
        driver.back()

        WebDriverWait(driver, 3, poll_frequency=0.08).until(
            EC.presence_of_element_located((By.XPATH, XPATH_TABELA_FILA))
        )
        print("[SCH] Retorno para a fila concluído por back().")
        return
    except Exception:
        pass

    if garantir_sessao_ativa_sch(
        driver,
        wait,
        contexto="após falha ao voltar para a fila",
        reabrir_fila=True,
    ):
        print("[SCH] Retorno para a fila concluído após refazer login.")
        return

    raise Exception("Não foi possível voltar para a fila.")



