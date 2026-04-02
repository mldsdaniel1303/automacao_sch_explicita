import re
import shutil
import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils import esperar_tela_carregar, nome_seguro

OBS_RADIACAO_RESTRITA = (
    "Na instalação do produto devem ser observadas as condições de uso "
    "conforme estabelecido no Regulamento sobre Equipamentos de "
    "Radiocomunicação de Radiação Restrita."
)

OBS_PRODUTO_NAO_ACABADO = (
    "Produto não acabado, de uso interno, cuja integração em outros "
    "equipamentos passíveis de homologação pode requerer nova avaliação."
)


def abrir_sch(driver):
    url = "https://sistemasnet.anatel.gov.br/mosaico/sch/worklist/visualizar"
    print(f"[SCH] Abrindo {url}")
    driver.get(url)
    esperar_tela_carregar(driver, 2)


def clicar_fila_em_analise(driver, wait):
    xpath_fila = "//a[normalize-space()='Em Análise' or contains(normalize-space(), 'Em Análise')]"

    print("[SCH] Clicando na fila Em Análise...")
    fila = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_fila)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", fila)
    driver.execute_script("arguments[0].click();", fila)

    esperar_tela_carregar(driver, 2)
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
                return colunas[posicao].text.strip() if len(colunas) > posicao else ""

            dados = {
                "row_index": idx,
                "requerimento": valor_coluna(idx_requerimento),
                "homologacao": valor_coluna(idx_homologacao),
                "certificado": valor_coluna(idx_certificado),
                "tipo_produto": valor_coluna(idx_tipo_produto),
                "modelo": valor_coluna(idx_modelo),
                "solicitante": valor_coluna(idx_solicitante),
                "fabricante": valor_coluna(idx_fabricante),
                "data_conclusao": valor_coluna(idx_data_conclusao),
            }

            requerimentos.append(dados)

        except Exception as e:
            print(f"[SCH][WARN] Falha ao ler linha {idx}: {e}")

    print(f"[SCH] {len(requerimentos)} requerimentos encontrados.")
    return requerimentos


def abrir_requerimento(driver, wait, req):
    numero = req.get("requerimento", "")
    linha_idx = req.get("row_index")

    xpath_tabela = "//table[.//th[contains(., 'Requerimento')] or .//td[contains(., 'Requerimento')]]"
    xpath_linha = f"(.//tbody/tr[td])[{linha_idx}]"
    xpath_botao_abrir = ".//img/.. | .//a[img] | .//button"

    print(f"[SCH] Abrindo requerimento {numero}...")
    tabela = wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
    linha = tabela.find_element(By.XPATH, xpath_linha)

    botoes = linha.find_elements(By.XPATH, xpath_botao_abrir)
    if not botoes:
        raise Exception(f"Nenhum botão encontrado para o requerimento {numero}.")

    alvo = botoes[1] if len(botoes) >= 2 else botoes[0]
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", alvo)

    try:
        alvo.click()
    except Exception:
        driver.execute_script("arguments[0].click();", alvo)

    esperar_tela_carregar(driver, 3)
    time.sleep(3)

    print("[SCH] Requerimento aberto. Aguardando tela de detalhes...")


def entrar_iframe_detalhe_analise(driver, wait):
    driver.switch_to.default_content()

    iframe = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//iframe[@id='__frameDetalhe' or @name='__frameDetalhe' or contains(@src,'/analise/requerimento')]",
            )
        )
    )
    driver.switch_to.frame(iframe)
    return iframe


def _clicar_aba_por_rotulo(driver, wait, rotulo_principal, rotulos_alternativos=None):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 1)

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

    for xpath in candidatos:
        try:
            aba = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", aba)
            time.sleep(0.3)

            try:
                aba.click()
            except Exception:
                driver.execute_script("arguments[0].click();", aba)

            esperar_tela_carregar(driver, 2)
            time.sleep(1)

            print(f"[SCH] Aba '{rotulo_principal}' aberta. XPath usado: {xpath}")
            return xpath
        except Exception as e:
            ultimo_erro = e

    raise Exception(f"Não foi possível abrir a aba '{rotulo_principal}'. Último erro: {ultimo_erro}")


def clicar_aba_anexos(driver, wait):
    print("[SCH] Tentando abrir aba Anexos...")

    entrar_iframe_detalhe_analise(driver, wait)

    xpath_botao_anexos = "//button[.//span[normalize-space()='Anexos']]"
    botao = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, xpath_botao_anexos))
    )

    botao_id = botao.get_attribute("id")
    classe_antes = botao.get_attribute("class") or ""

    print(f"[SCH] Botão Anexos encontrado. id={botao_id}")
    print(f"[SCH] Classe antes do clique: {classe_antes}")

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
    esperar_tela_carregar(driver, 1)

    clicou = False

    try:
        botao.click()
        clicou = True
        print("[SCH] Clique normal executado no botão Anexos.")
    except Exception as e:
        print(f"[SCH][WARN] Clique normal falhou: {e}")

    esperar_tela_carregar(driver, 2)

    try:
        botao_pos = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, botao_id))
        )
        classe_depois = botao_pos.get_attribute("class") or ""
        print(f"[SCH] Classe após clique normal: {classe_depois}")

        if "botao-ativo" in classe_depois:
            print("[SCH] Aba Anexos ativada com sucesso.")
            return
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível validar após clique normal: {e}")

    try:
        botao = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, botao_id))
        )
        driver.execute_script("arguments[0].click();", botao)
        clicou = True
        print("[SCH] Clique via JavaScript executado no botão Anexos.")
    except Exception as e:
        print(f"[SCH][WARN] Clique JS falhou: {e}")

    esperar_tela_carregar(driver, 2)

    try:
        botao_pos = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, botao_id))
        )
        classe_depois = botao_pos.get_attribute("class") or ""
        print(f"[SCH] Classe após clique JS: {classe_depois}")

        if "botao-ativo" in classe_depois:
            print("[SCH] Aba Anexos ativada com sucesso.")
            return
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível validar após clique JS: {e}")

    raise Exception(
        f"O botão Anexos foi encontrado, mas a aba não ficou ativa. "
        f"id={botao_id} | clicou={clicou}"
    )


def clicar_categoria_anexo(driver, wait, categoria):
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 1)

    categoria_txt = categoria.replace('"', "").strip()

    xpaths = [
        f'//button[.//span[normalize-space()="{categoria_txt}"]]',
        f'//span[normalize-space()="{categoria_txt}"]/ancestor::button[1]',
        f'//button[contains(normalize-space(), "{categoria_txt}")]',
    ]

    print(f"[SCH] Abrindo categoria de anexos: {categoria}")

    ultimo_erro = None

    for xpath in xpaths:
        try:
            botao = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
            time.sleep(0.5)

            try:
                botao.click()
            except Exception:
                driver.execute_script("arguments[0].click();", botao)

            esperar_tela_carregar(driver, 2)

            botao_pos = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            classe = botao_pos.get_attribute("class") or ""

            print(f"[SCH] Classe da categoria {categoria}: {classe}")

            if "botao-ativo" in classe or "ui-state-hover" in classe:
                print(f"[SCH] Categoria aberta com sucesso: {categoria}")
                return

        except Exception as e:
            ultimo_erro = e
            print(f"[SCH][WARN] Falha ao abrir categoria {categoria} com XPath {xpath}: {e}")

    raise Exception(f"Não foi possível abrir a categoria {categoria}. Último erro: {ultimo_erro}")


def localizar_tabela_anexos(driver, wait):
    xpaths_tabela = [
        "//table[.//th[normalize-space()='ID'] and .//th[contains(., 'Anexo')]]",
        "//table[.//th[contains(., 'Tipo de Documento')] and .//th[contains(., 'Anexo')]]",
        "//table[.//th[contains(., 'Análise da Anatel')]]",
        "//table[.//th[contains(., 'Tipo')] or .//td[contains(., 'Tipo')]]",
    ]

    for xpath in xpaths_tabela:
        try:
            tabela = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            print(f"[SCH] Tabela de anexos localizada com XPath: {xpath}")
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


def esperar_novo_arquivo_baixado(pasta_download, arquivos_antes, timeout=60):
    inicio = time.time()
    pasta = Path(pasta_download)

    while time.time() - inicio < timeout:
        temporarios = (
            list(pasta.glob("*.crdownload"))
            + list(pasta.glob("*.tmp"))
            + list(pasta.glob("*.part"))
        )

        atuais = listar_arquivos_estaveis(pasta_download)
        novos = [p for p in atuais if p not in arquivos_antes]

        if novos and not temporarios:
            novos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return novos[0]

        time.sleep(1)

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
    numero = req.get("requerimento", "sem_numero")
    pasta_req = Path(pasta_saida) / nome_seguro(numero) / nome_seguro(categoria)
    pasta_req.mkdir(parents=True, exist_ok=True)

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 1)

    tabela = localizar_tabela_anexos(driver, wait)
    linhas = tabela.find_elements(By.XPATH, ".//tr[td]")

    print(f"[SCH] {len(linhas)} linhas encontradas na categoria {categoria}.")

    anexos_categoria = []

    for i, linha in enumerate(linhas, start=1):
        try:
            tds = linha.find_elements(By.XPATH, "./td")

            id_linha = tds[0].text.strip() if len(tds) > 0 else str(i)
            tipo_documento = tds[1].text.strip() if len(tds) > 1 else ""
            detalhamento = tds[2].text.strip() if len(tds) > 2 else ""
            data_hora = tds[3].text.strip() if len(tds) > 3 else ""
            nome_anexo = tds[4].text.strip() if len(tds) > 4 else id_linha
            entidade = tds[5].text.strip() if len(tds) > 5 else ""
            contato = tds[6].text.strip() if len(tds) > 6 else ""

            xpaths_download = [
                ".//td[5]//a",
                ".//a[contains(@href,'download')]",
                ".//a",
                ".//img/ancestor::a[1]",
            ]

            link = None
            for xp in xpaths_download:
                try:
                    link = linha.find_element(By.XPATH, xp)
                    break
                except Exception:
                    pass

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

            if link is None:
                print(f"[SCH][WARN] Link não encontrado para o anexo {id_linha} da categoria {categoria}.")
                registro["status"] = "sem_link"
                anexos_categoria.append(registro)
                continue

            print(f"[SCH] Baixando anexo {i} da categoria {categoria}: {nome_anexo}")

            janela_principal = driver.current_window_handle
            handles_antes = set(driver.window_handles)
            arquivos_antes = listar_arquivos_estaveis(pasta_download)

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            time.sleep(0.5)

            try:
                link.click()
            except Exception:
                driver.execute_script("arguments[0].click();", link)

            time.sleep(2)

            handles_depois = set(driver.window_handles)
            novas_abas = [h for h in handles_depois if h not in handles_antes]

            if novas_abas:
                for nova_aba in novas_abas:
                    print(f"[SCH][WARN] O anexo abriu em nova aba. Fechando aba extra: {nome_anexo}")
                    driver.switch_to.window(nova_aba)
                    time.sleep(1)
                    driver.close()

                driver.switch_to.window(janela_principal)
                entrar_iframe_detalhe_analise(driver, wait)

            novo_arquivo = esperar_novo_arquivo_baixado(pasta_download, arquivos_antes, timeout=90)

            if novo_arquivo:
                nome_limpo = nome_seguro(nome_anexo) or f"anexo_{i}"
                nome_destino = f"{nome_limpo}{novo_arquivo.suffix.lower()}"
                arquivo_final = mover_arquivo_para_requerimento(novo_arquivo, pasta_req, nome_destino)

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

    pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0]


def clicar_aba_minuta(driver, wait):
    print("[SCH] Abrindo aba Minuta...")
    _clicar_aba_por_rotulo(driver, wait, "Minuta")


def _achar_campo_visivel(driver, wait, xpaths, descricao):
    entrar_iframe_detalhe_analise(driver, wait)

    for xpath in xpaths:
        try:
            elementos = WebDriverWait(driver, 6).until(
                EC.presence_of_all_elements_located((By.XPATH, xpath))
            )

            for el in elementos:
                try:
                    if el.is_displayed() and el.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        time.sleep(0.2)
                        return el
                except Exception:
                    continue
        except Exception:
            continue

    try:
        candidatos = driver.find_elements(
            By.XPATH,
            "//input[not(@type='hidden')] | //textarea | //select"
        )
        visiveis = []
        for el in candidatos:
            try:
                if el.is_displayed() and el.is_enabled():
                    visiveis.append(el)
            except Exception:
                continue

        if visiveis:
            print(
                f"[SCH][WARN] Campo específico não encontrado para '{descricao}'. "
                f"Usando fallback com {len(visiveis)} campo(s) visível(is)."
            )
            return visiveis[0]
    except Exception:
        pass

    raise Exception(f"Campo não encontrado/visível: {descricao}")


def _preencher_campo(driver, wait, xpaths, valor, descricao):
    valor = (valor or "").strip()
    if not valor:
        print(f"[SCH][WARN] Valor vazio para o campo {descricao}.")
        return

    print(f"[SCH] Preenchendo {descricao}: {valor}")

    campo = _achar_campo_visivel(driver, wait, xpaths, descricao)

    try:
        campo.click()
    except Exception:
        driver.execute_script("arguments[0].click();", campo)

    time.sleep(0.2)

    try:
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.DELETE)
        campo.send_keys(valor)
    except Exception:
        driver.execute_script(
            """
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
            """,
            campo,
            valor,
        )

    esperar_tela_carregar(driver, 1)


def preencher_campo_numero_certificado(driver, wait, valor):
    xpaths = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'CERTIFICADO')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//td[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'CERTIFICADO')]"
        "/following-sibling::td//*[self::input or self::textarea or self::select][1]",

        "//span[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'CERTIFICADO')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CERT')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CERT')]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CERT')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CERT')]",

        "(//input[not(@type='hidden') and not(@disabled)] | //textarea[not(@disabled)] | //select[not(@disabled)])[1]",
    ]
    _preencher_campo(driver, wait, xpaths, valor, "número do certificado")


def preencher_campo_homologacao(driver, wait, valor):
    xpaths = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'HOMOLOG')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//td[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'HOMOLOG')]"
        "/following-sibling::td//*[self::input or self::textarea or self::select][1]",

        "//span[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'HOMOLOG')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'HOMOLOG')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'HOMOLOG')]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'HOMOLOG')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'HOMOLOG')]",

        "(//input[not(@type='hidden') and not(@disabled)] | //textarea[not(@disabled)] | //select[not(@disabled)])[2]",
    ]
    _preencher_campo(driver, wait, xpaths, valor, "homologação")


def preencher_campo_modelo(driver, wait, valor):
    xpaths = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'MODELO')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//td[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'MODELO')]"
        "/following-sibling::td//*[self::input or self::textarea or self::select][1]",

        "//span[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'MODELO')]"
        "/following::*[self::input or self::textarea or self::select][1]",

        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'MODELO')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'MODELO')]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'MODELO')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'MODELO')]",

        "(//input[not(@type='hidden') and not(@disabled)] | //textarea[not(@disabled)] | //select[not(@disabled)])[3]",
    ]
    _preencher_campo(driver, wait, xpaths, valor, "modelo")


def preencher_minuta_com_dados(driver, wait, dados_pdf):
    clicar_aba_minuta(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 1)
    time.sleep(1)

    erros = []

    try:
        preencher_campo_numero_certificado(driver, wait, dados_pdf.get("numero_certificado", ""))
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher número do certificado: {e}")
        erros.append(f"numero_certificado: {e}")

    try:
        preencher_campo_homologacao(driver, wait, dados_pdf.get("homologacao", ""))
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher homologação: {e}")
        erros.append(f"homologacao: {e}")

    try:
        preencher_campo_modelo(driver, wait, dados_pdf.get("modelo", ""))
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher modelo: {e}")
        erros.append(f"modelo: {e}")

    if erros:
        print(f"[SCH][WARN] Minuta preenchida parcialmente. Problemas: {erros}")

def _normalizar_texto_rapido(texto):
    texto = (texto or "").lower()
    texto = texto.replace("não", "nao")
    texto = texto.replace("módulo", "modulo")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


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


def preencher_caracteristicas_tecnicas_com_analise(driver, wait, req, anexos_baixados, dados_pdf):
    analise = decidir_texto_observacao_por_cct(dados_pdf)

    print(
        f"[SCH] Observação definida pelo CCT: {analise['classificacao']} "
        f"| origem={analise.get('origem')} "
        f"| motivos={analise.get('motivos', [])}"
    )

    clicar_aba_caracteristicas_tecnicas(driver, wait)
    preencher_observacao_caracteristicas(driver, wait, analise["texto"])

    return analise

def clicar_aba_caracteristicas_tecnicas(driver, wait):
    print("[SCH] Abrindo aba Características Técnicas...")
    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Características Técnicas",
        rotulos_alternativos=["Caracteristicas Tecnicas", "Características", "Caracteristicas"],
    )


def _preencher_texto_em_area(driver, wait, texto, descricao, xpaths_input, xpaths_editor=None):
    if not texto:
        print(f"[SCH][WARN] Texto vazio para {descricao}.")
        return

    texto_plano = texto.replace("<br>", "\n").strip()

    entrar_iframe_detalhe_analise(driver, wait)
    esperar_tela_carregar(driver, 1)

    for xpath in xpaths_input:
        try:
            elementos = WebDriverWait(driver, 5).until(
                EC.presence_of_all_elements_located((By.XPATH, xpath))
            )
            for campo in elementos:
                try:
                    if campo.is_displayed() and campo.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo)
                        time.sleep(0.2)

                        try:
                            campo.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", campo)

                        try:
                            campo.send_keys(Keys.CONTROL, "a")
                            campo.send_keys(Keys.DELETE)
                            campo.send_keys(texto_plano)
                        except Exception:
                            driver.execute_script(
                                """
                                arguments[0].value = arguments[1];
                                arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                                arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                                arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                                """,
                                campo,
                                texto_plano,
                            )

                        esperar_tela_carregar(driver, 1)
                        return
                except Exception:
                    continue
        except Exception:
            pass

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
                    if editor.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)
                        driver.execute_script(
                            """
                            arguments[0].innerHTML = arguments[1];
                            arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                            arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                            """,
                            editor,
                            texto.replace("\n", "<br>"),
                        )
                        esperar_tela_carregar(driver, 1)
                        return
                except Exception:
                    continue
        except Exception:
            pass

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
    ]
    _preencher_texto_em_area(driver, wait, texto, "observação em Características Técnicas", xpaths_input)


def preencher_caracteristicas_tecnicas_com_analise(driver, wait, req, anexos_baixados, dados_pdf):
    analise = decidir_texto_observacao_por_cct(dados_pdf)

    print(
        f"[SCH] Análise rápida: {analise['classificacao']} "
        f"| motivos={analise.get('motivos', [])}"
    )

    clicar_aba_caracteristicas_tecnicas(driver, wait)
    preencher_observacao_caracteristicas(driver, wait, analise["texto"])

    return analise


def clicar_aba_informacoes_adicionais(driver, wait):
    print("[SCH] Abrindo aba Informações Adicionais...")
    _clicar_aba_por_rotulo(
        driver,
        wait,
        "Informações Adicionais",
        rotulos_alternativos=["Informacoes Adicionais", "Informações", "Informacoes"],
    )


def montar_texto_informacoes_adicionais(req, anexos_baixados, dados_pdf, analise_rapida):
    numero = req.get("requerimento", "sem_numero")
    qtd_docs = len([x for x in (anexos_baixados or []) if isinstance(x, dict) and x.get("status") == "baixado"])
    motivos = analise_rapida.get("motivos", []) if analise_rapida else []
    classificacao = analise_rapida.get("classificacao", "nao_classificado") if analise_rapida else "nao_classificado"

    linhas = [
        f"Análise preliminar automatizada do requerimento {numero}.",
        f"Classificação inicial: {classificacao}.",
        f"Documentos baixados: {qtd_docs}.",
    ]

    if dados_pdf.get("numero_certificado"):
        linhas.append(f"Número do certificado identificado: {dados_pdf.get('numero_certificado')}.")

    if dados_pdf.get("modelo"):
        linhas.append(f"Modelo identificado: {dados_pdf.get('modelo')}.")

    if motivos:
        linhas.append(f"Indícios encontrados: {', '.join(motivos)}.")
    else:
        linhas.append("Sem indícios preliminares adicionais na triagem rápida.")

    return " ".join(linhas)


def preencher_texto_informacoes_adicionais(driver, wait, texto):
    print(f"[SCH] Preenchendo Informações Adicionais: {texto}")

    xpaths_input = [
        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'INFORMA')]"
        "/following::*[self::textarea or self::input][1]",

        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'ADICION')]"
        "/following::*[self::textarea or self::input][1]",

        "//label[contains(translate(normalize-space(.), "
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ'), 'OBSERVA')]"
        "/following::*[self::textarea or self::input][1]",

        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'INFORMA')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'INFORMA')]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ADICION')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ADICION')]",
        "//textarea[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",
        "//textarea[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OBSERV')]",

        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'INFORMA')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'INFORMA')]",
        "//input[contains(translate(@name,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ADICION')]",
        "//input[contains(translate(@id,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ADICION')]",
    ]

    xpaths_editor = [
        "//*[@contenteditable='true']",
        "//div[contains(@class,'ql-editor')]",
        "//div[contains(@class,'ui-editor')]//*[@contenteditable='true']",
        "//div[contains(@class,'tox-edit-area')]//iframe",
        "//iframe[contains(@title,'Rich Text')]",
        "//iframe[contains(@class,'tox-edit-area__iframe')]",
    ]

    try:
        _preencher_texto_em_area(
            driver,
            wait,
            texto,
            "Informações Adicionais",
            xpaths_input,
            xpaths_editor=xpaths_editor,
        )
        return True
    except Exception as e:
        print(f"[SCH][WARN] Não foi possível preencher Informações Adicionais automaticamente: {e}")
        return False


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

    clicar_aba_informacoes_adicionais(driver, wait)
    preenchido = preencher_texto_informacoes_adicionais(driver, wait, texto)

    return {
        "texto": texto,
        "classificacao": (analise_rapida or {}).get("classificacao", ""),
        "motivos": (analise_rapida or {}).get("motivos", []),
        "preenchido_automaticamente": preenchido,
    }


def voltar_para_fila(driver, wait):
    candidatos = [
        "//a[contains(., 'Voltar')]",
        "//button[contains(., 'Voltar')]",
        "//img[contains(@src,'voltar')]/..",
    ]

    print("[SCH] Voltando para a fila...")
    for xpath in candidatos:
        try:
            driver.switch_to.default_content()
            botao = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
            driver.execute_script("arguments[0].click();", botao)
            esperar_tela_carregar(driver, 2)
            print("[SCH] Retorno para a fila concluído.")
            return
        except Exception:
            pass

    driver.switch_to.default_content()
    driver.back()
    esperar_tela_carregar(driver, 2)
    print("[SCH] Retorno para a fila via back().")