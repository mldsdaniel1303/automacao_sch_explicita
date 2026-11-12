from pathlib import Path
from datetime import datetime
import builtins
import re
import unicodedata

from selenium.webdriver.common.by import By

from navegador import criar_driver
from utils import aguardar_enter, carregar_regras, salvar_json, nome_seguro
from pdf_parser import parsear_certificado_pdf
from funcoes_sch import (
    abrir_sch,
    clicar_fila_sch,
    selecionar_quantidade_registros_fila,
    coletar_requerimentos,
    abrir_requerimento,
    clicar_aba_anexos,
    baixar_todos_os_anexos_de_todas_as_categorias,
    localizar_pdf_cct_do_requerimento,
    extrair_tabela_tecnica_sch,
    comparar_dados_sch_x_cct,
    avisar_resultado_conferencia_sch_cct,
    preencher_caracteristicas_tecnicas_com_analise,
    preencher_caracteristicas_secundarias_retorno,
    preencher_informacoes_adicionais_com_analise,
    registrar_avaliacao_automacao_informacoes_adicionais_retorno,
    avaliar_validade_cct,
    comparar_datas_certificado_sch_x_cct,
    preencher_minuta_sar_se_necessario,
    limpar_especificacoes_complementares_minuta_se_necessario,
    tipo_produto_deve_limpar_especificacoes_complementares,
    enviar_retorno_para_aprovacao_se_apto,
    garantir_sessao_ativa_sch,
    voltar_para_fila,
    extrair_dados_certificado_sch,
    analisar_retorno_para_estudo,
    restaurar_tela_requerimento_apos_comparacao,
)
from analise_requerimentos import analisar_requerimento
from gerador_relatorio import gerar_req_report
from diagnostico_estrutura_sch import diagnosticar_estrutura_atual, exibir_resumo_diagnostico
from mvp_simplificada_re import (
    avaliar_cobertura_mvp,
    expandir_faixas_explicitas_re,
    preencher_caracteristicas_conservadoras_re,
    preencher_acompanhamento_seguro_re,
)
from caracteristicas_secundarias import (
    inferir_caracteristicas_secundarias,
    gerar_texto_caracteristicas_secundarias,
)

VERSAO_SCRIPT = "0.8.9.6-re-simplificada"


def _normalizar_texto(valor):
    if valor is None:
        return ""

    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _eh_fila_retorno_para_estudo(fila_sch):
    return _normalizar_texto(fila_sch) in {
        "retorno para estudo",
        "retorno pra estudo",
        "retorno estudo",
    }


def _texto_requerimento(req):
    if not isinstance(req, dict):
        return ""

    partes = []
    for _, valor in req.items():
        if valor is None:
            continue
        partes.append(str(valor))

    return _normalizar_texto(" | ".join(partes))


def _eh_radiacao_restrita(req):
    if not isinstance(req, dict):
        return False

    tipo_produto = _normalizar_texto(req.get("tipo_produto", ""))
    texto_total = _texto_requerimento(req)

    alvos = [
        "transceptor de radiacao restrita",
        "equipamento de radiacao restrita",
        "produto de radiacao restrita",
        "radiacao restrita",
    ]

    if any(alvo in tipo_produto for alvo in alvos):
        return True

    if any(alvo in texto_total for alvo in alvos):
        return True

    return False


def _numero_requerimento(req):
    if isinstance(req, dict):
        numero = req.get("requerimento", "sem_numero")

        if not numero or str(numero).strip().lower().startswith("sem_numero"):
            numero = f"req_linha_{req.get('row_index', 'sem_indice')}"

        return str(numero)

    if req is None:
        return "sem_numero"

    texto = str(req).strip()
    return texto or "sem_numero"


def _dados_normativos_radiacao_restrita():
    return {
        "tipo_produto_alvo": "Transceptor de Radiação Restrita",
        "familia_produto_alvo": "Equipamentos de RF (exceto radiodifusão)",
        "categoria_requisitos": "Categoria II",
        "modalidade_avaliacao": "Certificação",
        "modelo_avaliacao": (
            "Certificação baseada em Ensaio de Tipo com Avaliação Periódica "
            "do Produto e do Sistema de Gestão Fabril a cada 2 anos"
        ),
        "observacoes": [
            "Compatibilidade eletromagnética obrigatória",
            "Segurança elétrica obrigatória quando aplicável",
            "IPv6 não obrigatório como regra geral para radiação restrita",
            "SAR obrigatório quando aplicável",
            "Segurança cibernética apenas para tipos específicos",
        ],
    }


def _dados_normativos_retorno_para_estudo():
    return {
        "tipo_fluxo": "Retorno Para Estudo",
        "objetivo": (
            "Comparar a versão anterior e a nova versão do requerimento uma única vez "
            "e avaliar separadamente cada tipo RE identificado na Justificativa do OCD."
        ),
        "regra_decisao": [
            "Os RE 1, 5, 6, 10, 11 e 12 possuem analisadores individuais.",
            "Quando houver múltiplos RE, cada número é julgado por sua própria regra; não existem combos fixos.",
            "A validação documental considera somente documentos incluídos e as exigências próprias de cada RE.",
            "O requerimento só pode seguir automaticamente quando todas as análises individuais estiverem aptas.",
        ],
    }



def _extrair_ano_homologacao(req):
    """
    Extrai o ano central do código de homologação XXXXX-AA-XXXXX.

    Prioriza ``req['homologacao']``. Como proteção para versões da fila cujo
    mapeamento de colunas veio incorreto, também examina ``certificado`` e o
    texto integral da linha. O primeiro código compatível é usado.
    """
    if not isinstance(req, dict):
        return None

    candidatos = [
        ("homologacao", req.get("homologacao")),
        ("certificado_fallback", req.get("certificado")),
        ("texto_linha_fallback", req.get("texto_linha")),
    ]

    padrao = re.compile(
        r"\b\d{4,6}\s*[-–—]\s*(\d{2,4})\s*[-–—]\s*\d{4,6}\b"
    )

    for origem, valor in candidatos:
        texto = str(valor or "").strip()
        if not texto:
            continue
        m = padrao.search(texto)
        if not m:
            continue
        ano_txt = m.group(1)
        try:
            ano = int(ano_txt)
        except (TypeError, ValueError):
            continue
        if len(ano_txt) == 2:
            ano += 2000
        req.setdefault("origem_ano_homologacao", origem)
        return ano

    return None



def _homologacao_ano_2026_ou_superior(req):
    """Bloqueia homologações cujo ano central seja 2026 ou posterior."""
    ano = _extrair_ano_homologacao(req)
    return bool(ano is not None and ano >= 2026)


# Compatibilidade com eventuais testes/chamadas antigas.
def _homologacao_tem_ano_26(req):
    return _homologacao_ano_2026_ou_superior(req)


def _separar_homologacoes_2026_ou_superior(requerimentos):
    processaveis = []
    ignorados = []

    for req in requerimentos or []:
        if _homologacao_ano_2026_ou_superior(req):
            item = dict(req)
            ano = _extrair_ano_homologacao(req)
            item["motivo"] = "homologacao_2026_ou_superior"
            item["ano_homologacao"] = ano
            item["mensagem"] = (
                "Requerimento ignorado porque a homologação possui "
                f"ano {ano} no bloco central (2026 ou posterior)."
            )
            ignorados.append(item)
        else:
            processaveis.append(req)

    return processaveis, ignorados


# Compatibilidade com nome antigo; a regra agora é 2026 ou posterior.
def _separar_homologacoes_ano_26(requerimentos):
    return _separar_homologacoes_2026_ou_superior(requerimentos)


def _tipo_produto_no_escopo_automatico_retorno(tipo_produto):
    """
    Em Retorno Para Estudo existe uma única lista positiva de tipos aceitos.

    A lista oficial é a mesma usada para o tratamento automático da minuta.
    Qualquer tipo fora dela é ignorado ainda na fila, antes de abrir o
    requerimento, ler Informações Adicionais, Comparar Versões ou Corrigir Minuta.
    """
    return bool(
        tipo_produto_deve_limpar_especificacoes_complementares(tipo_produto)
    )


# A conferência CCT x SCH tem escopo próprio e NÃO compartilha a lista
# positiva de produtos utilizada por Comparar Versões/Corrigir Minuta.
CATEGORIA_CCT = "Certificado de Conformidade Técnica - CCT"


def _tipo_produto_permitido_simplificada(req):
    """Lista exclusiva da opção 4; usa apenas a coluna real da fila."""
    return _normalizar_texto((req or {}).get("tipo_produto", "")) in {
        "estacao terminal de acesso", "estacao terminal de acesso (eta)",
        "transceptor de radiacao restrita",
    }


def _escopo_conferencia_cct_re(req, dados_sch=None):
    """Exclui os quatro tipos do art. 3 e a modalidade Declaração de Conformidade.

    A modalidade só é excluída quando identificada explicitamente; na ausência
    dessa informação, não inventamos que o produto foi declarado. A decisão
    permanece registrada para auditoria e possível revisão da fonte no SCH.
    """
    req = req or {}
    dados_sch = dados_sch or {}
    tipo = _normalizar_texto(req.get("tipo_produto", ""))

    proibidos = (
        "carregador para telefone celular",
        "carregador indutivo para telefone celular",
        "bateria de litio utilizada em telefone celular",
        "acessorio para telefone movel celular do tipo bateria auxiliar",
    )
    # A comparação é por expressão completa, não por palavras soltas:
    # evita excluir todos os acessórios ou todos os aparelhos celulares.
    tipo_limpo = re.sub(r"[^a-z0-9]+", " ", tipo).strip()
    for excluido in proibidos:
        if tipo_limpo == excluido or tipo_limpo.startswith(excluido + " "):
            return {
                "executar": False,
                "motivo": "tipo_produto_excluido_portaria_art_3",
                "descricao": f"Tipo de produto excluído da análise simplificada: {req.get('tipo_produto', '')}",
                "modalidade_confirmada": False,
            }

    # A modalidade não é sinônimo de tipo de produto: verificar campos explícitos.
    campos_modalidade = (
        "modalidade_avaliacao", "modalidade_de_avaliacao",
        "modalidade", "modalidade_certificacao", "tipo_avaliacao",
    )
    valores = [
        str(fonte.get(campo) or "")
        for fonte in (req, dados_sch)
        for campo in campos_modalidade
        if fonte.get(campo)
    ]
    # Suporte a uma linha de fila que informe EXPRESSAMENTE a modalidade.
    texto_linha = _normalizar_texto(req.get("texto_linha", ""))
    trecho = re.search(
        r"modalidade(?:\s+de\s+avaliacao)?\s*[:=\-]\s*([^|;\n]+)",
        texto_linha,
    )
    if trecho:
        valores.append(trecho.group(1))

    declaracao = any(
        "declaracao de conformidade" in _normalizar_texto(valor)
        for valor in valores
    )
    if declaracao:
        return {
            "executar": False,
            "motivo": "modalidade_declaracao_conformidade",
            "descricao": "Modalidade de avaliação: Declaração de Conformidade.",
            "modalidade_confirmada": True,
        }

    return {
        "executar": True,
        "motivo": "produto_elegivel_para_conferencia_cct",
        "descricao": "Comparação CCT x SCH habilitada independentemente do tipo RE.",
        "modalidade_confirmada": bool(valores),
    }


def _extrair_modalidade_avaliacao_visivel_sch(driver):
    """Lê a modalidade APENAS se estiver rotulada na tela atual de Dados Gerais.

    Não busca a palavra 'declaração' livremente na página: isso poderia
    confundir anexos, referências legais ou outras informações com a
    modalidade efetiva de avaliação do requerimento.
    """
    try:
        texto = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""

    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    for i, linha in enumerate(linhas):
        if not re.fullmatch(r"modalidade(?:\s+de\s+avaliacao)?", _normalizar_texto(linha.rstrip(":"))):
            # Captura também campo rotulado e valor juntos na mesma linha.
            m = re.match(
                r"^modalidade(?:\s+de\s+avalia[çc][ãa]o)?\s*[:\-]\s*(.+)$",
                linha,
                flags=re.I,
            )
            if m:
                return m.group(1).strip()
            continue
        if i + 1 < len(linhas):
            return linhas[i + 1]
    return ""


def _definir_escopos_re(req, modo=None):
    """Cada opção consulta seu próprio filtro antes de abrir o requerimento."""
    if modo == "analise_simplificada":
        permitido = _tipo_produto_permitido_simplificada(req)
        conferencia = _escopo_conferencia_cct_re(req)
        return {
            "analise_tradicional_re": False,
            "comparacao_cct_sch": bool(permitido and conferencia["executar"]),
            "motivo_comparacao_cct": (conferencia["motivo"] if permitido else
                                      "tipo_produto_fora_escopo_analise_simplificada"),
            "descricao_comparacao_cct": conferencia["descricao"],
            "modalidade_confirmada": conferencia["modalidade_confirmada"],
            "filtro_produtos": "analise_simplificada_eta_transceptor_rr",
        }
    pode_tradicional = _tipo_produto_no_escopo_automatico_retorno(
        req.get("tipo_produto", "")
    ) and not _homologacao_ano_2026_ou_superior(req)
    conferencia = _escopo_conferencia_cct_re(req)
    return {
        "analise_tradicional_re": bool(pode_tradicional),
        "comparacao_cct_sch": bool(conferencia["executar"]),
        "motivo_comparacao_cct": conferencia["motivo"],
        "descricao_comparacao_cct": conferencia["descricao"],
        "modalidade_confirmada": conferencia["modalidade_confirmada"],
        "ano_homologacao_2026_mais": _homologacao_ano_2026_ou_superior(req),
    }


MODOS_ANALISE_RE = {"comparar_versoes", "analise_simplificada", "ambos"}
CATEGORIA_RACT = "Relatório de Avaliação da Conformidade - RACT"


def _escopos_para_modo_re(escopos, modo):
    """Aplica a escolha do usuário aos escopos técnicos independentes."""
    if modo not in MODOS_ANALISE_RE:
        raise ValueError(f"Modo de análise RE desconhecido: {modo}")
    escopos = dict(escopos or {})
    escopos["modo_analise_re"] = modo
    if modo == "comparar_versoes":
        escopos["comparacao_cct_sch"] = False
        escopos["motivo_comparacao_cct"] = "nao_executada_opcao_usuario"
        escopos["descricao_comparacao_cct"] = "Conferência não selecionada: modo Comparar Versões."
    if modo == "analise_simplificada":
        escopos["analise_tradicional_re"] = False
        escopos["motivo_analise_tradicional"] = "nao_executada_opcao_usuario"
    return escopos


def separar_requerimentos_por_escopo(requerimentos, processar_apenas_rr=True):
    if not processar_apenas_rr:
        return requerimentos, []

    selecionados = []
    ignorados = []

    for req in requerimentos:
        if not isinstance(req, dict):
            ignorados.append(
                {
                    "requerimento": str(req),
                    "tipo_produto": "",
                    "motivo": "item_invalido_na_fila",
                }
            )
            continue

        if _eh_radiacao_restrita(req):
            selecionados.append(req)
        else:
            ignorados.append(req)

    return selecionados, ignorados


def preparar_pastas_requerimentos(pasta_base, requerimentos):
    pasta_base = Path(pasta_base)
    pasta_requerimentos = pasta_base / "requerimentos"
    pasta_requerimentos.mkdir(parents=True, exist_ok=True)

    mapeados = []

    for req in requerimentos:
        numero = _numero_requerimento(req)
        pasta_req = pasta_requerimentos / nome_seguro(numero)
        pasta_req.mkdir(parents=True, exist_ok=True)

        resumo_json = pasta_req / "resumo.json"
        status = "processado" if resumo_json.exists() else "pendente"

        mapeados.append(
            {
                "requerimento": numero,
                "pasta": str(pasta_req),
                "status": status,
            }
        )

    return pasta_requerimentos, mapeados


def salvar_manifesto_requerimentos(pasta_base, mapeados, ignorados=None):
    caminho = Path(pasta_base) / "manifest_requerimentos.json"
    ignorados = ignorados or []

    salvar_json(
        caminho,
        {
            "gerado_em": datetime.now().isoformat(),
            "total_processaveis": len(mapeados),
            "processados": sum(1 for x in mapeados if x["status"] == "processado"),
            "pendentes": sum(1 for x in mapeados if x["status"] == "pendente"),
            "ignorados_fora_escopo": len(ignorados),
            "itens": mapeados,
            "ignorados": ignorados,
        },
    )

    return caminho


def contar_arquivos_requerimento(pasta_req):
    pasta_req = Path(pasta_req)

    ignorar = {
        "resumo.json",
        "controle_downloads.json",
        "analise_requerimento.json",
    }

    return len(
        [
            p
            for p in pasta_req.rglob("*")
            if p.is_file() and p.name not in ignorar
        ]
    )


def _normalizar_navegador_preferido(valor):
    texto = _normalizar_texto(valor)

    if texto in {"1", "chrome", "google chrome"}:
        return "chrome"

    if texto in {"2", "edge", "microsoft edge"}:
        return "edge"

    return ""


def _invocar_criar_driver(
    kwargs_base,
    navegador=None,
):
    """
    Tenta informar o navegador diretamente ao navegador.py.

    Como versões anteriores do projeto usam assinaturas diferentes, a função
    testa nomes de parâmetro comuns. Quando criar_driver ainda pergunta pelo
    terminal, intercepta somente a pergunta de Chrome/Edge e responde com a
    escolha feita no novo menu.
    """
    kwargs_base = dict(kwargs_base or {})
    navegador_norm = _normalizar_navegador_preferido(navegador)

    if not navegador_norm:
        return criar_driver(**kwargs_base)

    nomes_parametro = [
        "navegador",
        "browser",
        "tipo_navegador",
        "navegador_escolhido",
        "browser_name",
    ]

    for nome_parametro in nomes_parametro:
        try:
            kwargs = dict(kwargs_base)
            kwargs[nome_parametro] = navegador_norm
            return criar_driver(**kwargs)
        except TypeError:
            continue

    escolha_terminal = "1" if navegador_norm == "chrome" else "2"
    input_original = builtins.input

    def input_com_navegador(prompt=""):
        prompt_norm = _normalizar_texto(prompt)

        eh_pergunta_navegador = (
            "navegador" in prompt_norm
            or (
                "chrome" in prompt_norm
                and "edge" in prompt_norm
            )
            or (
                "opcao" in prompt_norm
                and "1/2" in prompt_norm
            )
        )

        if eh_pergunta_navegador:
            print(f"{prompt}{escolha_terminal}")
            return escolha_terminal

        return input_original(prompt)

    builtins.input = input_com_navegador

    try:
        return criar_driver(**kwargs_base)
    finally:
        builtins.input = input_original


def _criar_driver_com_pasta(pasta_base, navegador=None):
    pasta_base = Path(pasta_base).resolve()
    pasta_base.mkdir(parents=True, exist_ok=True)

    pasta_download = pasta_base / "browser_downloads"
    pasta_download.mkdir(parents=True, exist_ok=True)

    tentativas = [
        {
            "pasta_base": str(pasta_base),
            "pasta_download": str(pasta_download),
        },
        {
            "pasta_saida_base": str(pasta_base),
            "pasta_download": str(pasta_download),
        },
        {
            "pasta_saida": str(pasta_base),
            "pasta_download": str(pasta_download),
        },
    ]

    ultimo_erro = None

    for kwargs in tentativas:
        try:
            return _invocar_criar_driver(
                kwargs,
                navegador=navegador,
            )
        except TypeError as e:
            ultimo_erro = e
            continue

    print(
        "[WARN] criar_driver() não aceitou pasta personalizada. "
        "Usando o comportamento padrão do navegador.py."
    )

    try:
        return _invocar_criar_driver(
            {},
            navegador=navegador,
        )
    except Exception:
        if ultimo_erro:
            raise ultimo_erro
        raise

def perguntar_se_fecha_navegador():
    while True:
        resposta = input("[SCH] Deseja fechar o navegador ao final do fluxo? (s/n): ").strip().lower()

        if resposta in {"s", "sim"}:
            return True

        if resposta in {"n", "nao", "não"}:
            return False

        print("[SCH][WARN] Resposta inválida. Digite 's' para sim ou 'n' para não.")


def perguntar_fila_sch():
    """
    Define qual fila do SCH será processada.
    O restante do fluxo usa a fila escolhida, sem cair automaticamente em Em Análise.
    """
    while True:
        print("\n[SCH] Qual fila deseja processar?")
        print("1. Em Análise")
        print("2. Retorno Para Estudo")

        resposta = input("Opção [1/2]: ").strip().lower()

        if resposta in {"", "1", "em analise", "em análise"}:
            return "Em Análise"

        if resposta in {"2", "retorno para estudo", "retorno pra estudo"}:
            return "Retorno Para Estudo"

        print("[SCH][WARN] Opção inválida. Digite 1 ou 2.")


def _montar_ignorados_resumidos(requerimentos_ignorados):
    ignorados_resumidos = []

    for req in requerimentos_ignorados:
        if isinstance(req, dict):
            ignorados_resumidos.append(
                {
                    "requerimento": _numero_requerimento(req),
                    "tipo_produto": req.get("tipo_produto", ""),
                    "homologacao": req.get("homologacao", ""),
                    "ano_homologacao": req.get("ano_homologacao", ""),
                    "fila_sch": req.get("fila_sch", ""),
                    "motivo": req.get("motivo", "fora_escopo_radiacao_restrita"),
                    "mensagem": req.get("mensagem", ""),
                }
            )
        else:
            ignorados_resumidos.append(
                {
                    "requerimento": str(req),
                    "tipo_produto": "",
                    "motivo": "item_invalido_na_fila",
                }
            )

    return ignorados_resumidos


def _categorias_processadas(anexos_baixados):
    return sorted(
        list(
            {
                item.get("categoria", "")
                for item in (anexos_baixados or [])
                if isinstance(item, dict)
                and item.get("status") in {
                    "baixado",
                    "sem_link",
                    "erro",
                    "erro_categoria",
                    "nao_identificado",
                    "duplicado_ignorado",
                    "ja_existente",
                }
            }
        )
    )


def _selecionar_cct_mais_recente_re(anexos_baixados, pasta_req, exigir_arquivo=True):
    """Seleciona o CCT pela data/hora real da tabela Anexos do SCH.

    O instante do download (mtime do arquivo) NUNCA determina qual CCT e o
    mais recente. Uma falha no download do CCT mais novo nao autoriza usar
    um certificado anterior como se fosse o atual.
    """
    pasta_req = Path(pasta_req)
    registros = []
    for item in anexos_baixados or []:
        if not isinstance(item, dict):
            continue
        categoria = _normalizar_texto(item.get("categoria"))
        if "cct" not in categoria and "certificado de conformidade tecnica" not in categoria:
            continue

        data_texto = str(item.get("data_hora") or "").strip()
        data = None
        for formato in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                data = datetime.strptime(data_texto, formato)
                break
            except ValueError:
                pass

        try:
            identificador = int(str(item.get("id") or "0").strip())
        except (ValueError, TypeError):
            identificador = 0

        registros.append((data, identificador, item))

    if registros:
        # Sem data em um anexo, nao ha certeza de que ele nao e o mais novo.
        if any(data is None for data, _, _ in registros):
            return {
                "status": "data_anexo_indisponivel",
                "motivo": "Ha CCT sem Data-Hora confiavel na tabela de Anexos; selecao automatica suspensa.",
                "arquivo": "",
                "total_ccts": len(registros),
            }

        registros.sort(key=lambda reg: (reg[0], reg[1]), reverse=True)
        _, _, ultimo = registros[0]
        caminho = Path(str(ultimo.get("arquivo") or "")) if ultimo.get("arquivo") else None
        if exigir_arquivo and (not caminho or not caminho.is_file() or caminho.suffix.lower() != ".pdf"):
            return {
                "status": "cct_mais_recente_indisponivel",
                "motivo": "O CCT mais recente foi identificado, mas seu PDF nao foi baixado/localizado. Nao usar um CCT anterior.",
                "arquivo": "",
                "id": ultimo.get("id", ""),
                "data_hora": ultimo.get("data_hora", ""),
                "nome_anexo": ultimo.get("nome_anexo", ""),
                "total_ccts": len(registros),
            }
        return {
            "status": "selecionado",
            "motivo": "CCT escolhido pela Data-Hora da tabela de Anexos do SCH (ID como desempate).",
            "arquivo": str(caminho) if caminho else "",
            "id": ultimo.get("id", ""),
            "data_hora": ultimo.get("data_hora", ""),
            "nome_anexo": ultimo.get("nome_anexo", ""),
            "total_ccts": len(registros),
        }

    # Sem metadados da tabela do SCH nao e possivel garantir que o CCT
    # presente na pasta seja o atual (pode ser de execucao antiga).
    return {
        "status": "sem_selecao_segura",
        "motivo": (
            "Nao ha metadados de CCT da tabela Anexos para determinar a versao mais recente. "
            "Nao usar data de download nem PDF de execucao anterior por suposicao."
        ),
        "arquivo": "",
        "total_ccts": 0,
    }


def confirmar_identidade_cct_baixado_re(selecao, anexos, dados_sch, req):
    """Valida bytes novos e identidade antes de autorizar dependências do CCT."""
    import hashlib
    import pdfplumber
    resultado={'status':'bloqueado','selecao':selecao,'motivos':[]}
    try:
        if selecao.get('status')!='selecionado':
            raise ValueError('CCT mais recente não disponível.')
        registros=[a for a in anexos if all(a.get(k)==selecao.get(k) for k in ('id','data_hora','nome_anexo','arquivo'))]
        if len(registros)!=1 or registros[0].get('origem')!='download_sch_nesta_execucao' or registros[0].get('download_confirmado') is not True:
            raise ValueError('Sem evidência de novo download do anexo selecionado; nome local não confirma origem.')
        arquivo=Path(selecao['arquivo']).resolve()
        hash_atual=hashlib.sha256(arquivo.read_bytes()).hexdigest()
        resultado.update(arquivo=str(arquivo),sha256=hash_atual,origem=registros[0]['origem'])
        if hash_atual!=registros[0].get('sha256'):
            raise ValueError('Hash do arquivo mudou após o download.')
        with pdfplumber.open(arquivo) as pdf:
            if not pdf.pages:
                raise ValueError('PDF sem páginas.')
            resultado['paginas']=len(pdf.pages)
            for pagina in pdf.pages:
                pagina.extract_text()
        dados=parsear_certificado_pdf(arquivo)
        from funcoes_sch import _comparar_modelos_sch_x_cct
        certificado_sch=dados_sch.get('numero_certificado') or req.get('certificado')
        modelo_sch=dados_sch.get('modelo_sch_dados_gerais') or req.get('modelo_sch_dados_gerais')
        norm=lambda v: re.sub(r'[^a-z0-9]','',_normalizar_texto(v))
        modelo=_comparar_modelos_sch_x_cct(modelo_sch,dados.get('modelo'))
        resultado.update(arquivo=str(arquivo),sha256=hash_atual,origem=registros[0]['origem'],
                         certificado_sch=certificado_sch,certificado_pdf=dados.get('numero_certificado'),
                         modelo=modelo,leitura_pdf='ok',dados_pdf=dados,
                         datas=comparar_datas_certificado_sch_x_cct(dados_sch,dados))
        if not norm(certificado_sch) or norm(certificado_sch)!=norm(dados.get('numero_certificado')):
            raise ValueError('Número do certificado não corresponde ao SCH.')
        if modelo.get('status')!='ok':
            raise ValueError('Modelo não confirmado integralmente com o SCH.')
        if hashlib.sha256(arquivo.read_bytes()).hexdigest()!=hash_atual:
            raise ValueError('Arquivo mudou durante a leitura.')
        resultado['status']='confirmado'
    except Exception as exc:
        resultado['motivos'].append(f'{type(exc).__name__}: {exc}')
    return resultado


def _salvar_controle_downloads(
    pasta_req,
    numero,
    qtd_downloads,
    categorias_anexos_ativas,
    anexos_baixados,
    escopo_processamento,
    fila_sch,
    retorno_para_estudo=None,
):
    controle = {
        "requerimento": numero,
        "downloads_realizados": qtd_downloads,
        "categorias_configuradas": categorias_anexos_ativas,
        "categorias_processadas": _categorias_processadas(anexos_baixados),
        "escopo_processamento": escopo_processamento,
        "fila_sch": fila_sch,
        "atualizado_em": datetime.now().isoformat(),
    }

    if retorno_para_estudo is not None:
        controle["retorno_para_estudo"] = retorno_para_estudo

    salvar_json(Path(pasta_req) / "controle_downloads.json", controle)
    return controle


def _gerar_relatorios_parciais_execucao(
    pasta_base,
    relatorio_execucao,
    inicio_execucao,
    fila_sch,
    requerimentos,
    requerimentos_processaveis,
    requerimentos_ignorados,
    ignorados_resumidos,
    versao_script,
    categorias_anexos_ativas,
    processar_apenas_rr_efetivo,
    status_execucao="em_andamento",
    imprimir=False,
):
    """
    Salva o relatório consolidado JSON e atualiza a pasta req_report.

    Esta função pode ser chamada:
    - ao final de cada requerimento;
    - no final normal da execução;
    - quando o usuário interromper com Ctrl+C.

    Assim, os requerimentos já analisados não ficam sem relatório.
    """

    pasta_base = Path(pasta_base)
    pasta_base.mkdir(parents=True, exist_ok=True)

    relatorio_execucao = relatorio_execucao or []
    requerimentos = requerimentos or []
    requerimentos_processaveis = requerimentos_processaveis or []
    requerimentos_ignorados = requerimentos_ignorados or []
    ignorados_resumidos = ignorados_resumidos or []
    categorias_anexos_ativas = categorias_anexos_ativas or []

    fim_execucao = datetime.now()
    caminho_relatorio = pasta_base / "relatorio_execucao.json"

    dados_relatorio = {
        "status_execucao": status_execucao,
        "relatorio_parcial": status_execucao not in {"finalizado", "concluido", "concluído"},
        "atualizado_em": fim_execucao.isoformat(),
        "inicio_execucao": inicio_execucao.isoformat() if inicio_execucao else "",
        "fim_execucao": fim_execucao.isoformat(),
        "fila_sch": fila_sch,
        "tempo_total_segundos": (
            round((fim_execucao - inicio_execucao).total_seconds(), 2)
            if inicio_execucao
            else 0
        ),
        "total_coletados_na_fila": len(requerimentos),
        "total_processaveis": len(requerimentos_processaveis),
        "total_ignorados_fora_escopo": len(requerimentos_ignorados),
        "total_ja_processados_nesta_execucao": len(relatorio_execucao),
        "sucessos": sum(1 for x in relatorio_execucao if x.get("status") == "sucesso"),
        "erros": sum(1 for x in relatorio_execucao if x.get("status") == "erro"),
        "interrompidos": sum(1 for x in relatorio_execucao if x.get("status") == "interrompido"),
        "documentos_processados": sum(x.get("downloads_realizados", 0) for x in relatorio_execucao),
        "itens": relatorio_execucao,
        "ignorados_fora_escopo": ignorados_resumidos,
        "versao_script": versao_script,
        "pasta_base": str(pasta_base),
        "categorias_anexos_configuradas": categorias_anexos_ativas,
        "filtro_radiacao_restrita_efetivo": processar_apenas_rr_efetivo,
    }

    salvar_json(caminho_relatorio, dados_relatorio)

    caminho_req_report = ""

    if relatorio_execucao or ignorados_resumidos:
        try:
            caminho_req_report = gerar_req_report(
                pasta_saida=pasta_base,
                resultados=relatorio_execucao,
                versao_script=versao_script,
                inicio_execucao=inicio_execucao,
                fim_execucao=fim_execucao,
                ignorados_fora_escopo=ignorados_resumidos,
            )
        except Exception as e:
            print(
                "[SCH][WARN] Não foi possível atualizar o req_report parcial agora: "
                f"{type(e).__name__}: {e}"
            )
    else:
        print(
            "[SCH][WARN] Nenhum requerimento processado nem ignorado foi "
            "registrado; relatório HTML parcial não foi gerado."
        )

    if imprimir:
        print(f"[SCH] Relatório consolidado salvo em: {caminho_relatorio}")

        if caminho_req_report:
            print(f"[SCH] Pasta req_report gerada/atualizada em: {caminho_req_report}")

    return {
        "json": str(caminho_relatorio),
        "req_report": str(caminho_req_report or ""),
        "fim_execucao": fim_execucao.isoformat(),
        "status_execucao": status_execucao,
    }


def _requerimento_corresponde_ao_alvo(req, alvo):
    """
    Compara requerimentos preservando o ano quando ele foi informado.

    Exemplos aceitos:
    - 04334/26
    - 04334
    """
    alvo = str(alvo or "").strip()

    if not alvo:
        return False

    numero_req = _numero_requerimento(req)
    digitos_req = re.sub(r"\D+", "", numero_req)
    digitos_alvo = re.sub(r"\D+", "", alvo)

    if not digitos_req or not digitos_alvo:
        return False

    if "/" in alvo:
        return digitos_req == digitos_alvo

    numero_req_sem_ano = str(numero_req).split("/", 1)[0]
    digitos_req_sem_ano = re.sub(r"\D+", "", numero_req_sem_ano)

    return (
        digitos_req_sem_ano.lstrip("0")
        == digitos_alvo.lstrip("0")
    )


def _conferir_cct_sch_independente_re(
    driver,
    wait,
    req,
    pdf_cct,
    dados_certificado_sch,
    resumo,
    tela_requerimento_restaurada=True,
):
    """Reutiliza em RE a MESMA comparação da fila Em Análise, sem aprovar nem editar.

    A conferência é independente de Comparar Versões e dos analisadores dos RE.
    Quando não houver CCT ou a tela não estiver acessível, registra o motivo
    explícito em vez de afirmar conformidade.
    """
    numero = _numero_requerimento(req)
    dados_certificado_sch = dados_certificado_sch or {}

    def nao_executada(status, motivo):
        resumo["conferencia_sch_cct"] = {
            "status_geral": status,
            "comparacoes": [],
            "divergencias": [],
            "campos_ausentes": [],
            "comparacao_tabela_tecnica": {
                "status": "sem_tabela",
                "motivo": motivo,
                "divergencias": [],
            },
            "requerimento": numero,
            "motivo": motivo,
        }
        print(f"[SCH][RETORNO][CCT x SCH][WARN] {numero}: {motivo}")
        return resumo["conferencia_sch_cct"]

    if not pdf_cct:
        return nao_executada(
            "sem_cct", "CCT não localizado. Verifique a seleção de downloads ou a pasta do requerimento."
        )

    try:
        dados_pdf = parsear_certificado_pdf(pdf_cct) or {}
    except Exception as exc:
        return nao_executada("erro", f"Falha ao interpretar PDF do CCT: {type(exc).__name__}: {exc}")

    if not dados_pdf:
        return nao_executada("sem_cct", "O PDF do CCT não forneceu dados válidos.")

    # Guardar dados brutos do CCT ANTES de aplicar as datas do SCH para
    # avaliação da validade. Sem isso, emissão ausente no parser pode acabar
    # comparada com a própria emissão do SCH, produzindo falso status 'ok'.
    dados_cct_datas_brutos = {
        "data_emissao": dados_pdf.get("data_emissao", ""),
        "data_validade": dados_pdf.get("data_validade", ""),
        "data_emissao_cct": dados_pdf.get("data_emissao", ""),
        "data_validade_cct": dados_pdf.get("data_validade", ""),
    }

    # Mesmo preparo de dados utilizado na fila Em Análise.
    dados_pdf["nome_comercial_sch"] = req.get("nome_comercial", "")
    dados_pdf["modelo_sch_dados_gerais"] = req.get("modelo_sch_dados_gerais", "")

    if dados_certificado_sch:
        dados_pdf["data_emissao_cct"] = dados_pdf.get("data_emissao", "")
        dados_pdf["data_validade_cct"] = dados_pdf.get("data_validade", "")
        dados_pdf["data_emissao_sch"] = dados_certificado_sch.get("data_certificado", "")
        dados_pdf["data_validade_sch"] = dados_certificado_sch.get("data_validade", "")
        dados_pdf["numero_certificado_sch_dados_gerais"] = dados_certificado_sch.get("numero_certificado", "")
        if dados_certificado_sch.get("data_certificado"):
            dados_pdf["data_emissao"] = dados_certificado_sch["data_certificado"]
        if dados_certificado_sch.get("data_validade"):
            dados_pdf["data_validade"] = dados_certificado_sch["data_validade"]
        dados_pdf["datas_origem"] = "SCH - Dados Gerais - Dados do Certificado"

    resumo["dados_pdf"] = dados_pdf
    resumo["validade_cct"] = avaliar_validade_cct(dados_pdf)

    try:
        datas = comparar_datas_certificado_sch_x_cct(
            dados_certificado_sch=dados_certificado_sch,
            dados_pdf=dados_cct_datas_brutos,
            distinguir_eventos=resumo.get("modo_analise_re") == "analise_simplificada",
        )
    except Exception as exc:
        datas = {
            "status_geral": "erro", "mensagem": str(exc),
            "comparacoes": [], "divergencias": [],
        }
    resumo["comparacao_datas_sch_cct"] = datas
    dados_pdf["comparacao_datas_sch_cct"] = datas

    if not tela_requerimento_restaurada:
        return nao_executada(
            "nao_executada_tela", "Não foi possível restaurar o requerimento para ler a tabela técnica do SCH."
        )

    try:
        if resumo.get("modo_analise_re") == "analise_simplificada":
            from diagnostico_estrutura_sch import extrair_tabela_dom_para_comparacao
            req["tabela_tecnica_sch"] = extrair_tabela_dom_para_comparacao(driver, wait)
        else:
            req["tabela_tecnica_sch"] = extrair_tabela_tecnica_sch(driver, wait)
    except Exception as exc:
        print(f"[SCH][RETORNO][CCT x SCH][WARN] Tabela técnica indisponível: {exc}")
        req["tabela_tecnica_sch"] = {"cabecalho": [], "linhas": []}

    resumo["tabela_tecnica_sch"] = req["tabela_tecnica_sch"]

    # Estas DUAS funções são exatamente as já utilizadas em Em Análise.
    req_comparacao, pdf_comparacao = req, dados_pdf
    if resumo.get("modo_analise_re") == "analise_simplificada":
        req_comparacao = dict(req, tabela_tecnica_sch=expandir_faixas_explicitas_re(req.get("tabela_tecnica_sch")))
        pdf_comparacao = dict(dados_pdf, tabela_tecnica_cct=expandir_faixas_explicitas_re(dados_pdf.get("tabela_tecnica_cct")))
    if resumo.get("modo_analise_re") == "analise_simplificada":
        resultado = comparar_dados_sch_x_cct(req_comparacao, pdf_comparacao, modo_simplificado=True)
    else:
        resultado = comparar_dados_sch_x_cct(req_comparacao, pdf_comparacao)
    resumo["conferencia_sch_cct"] = resultado
    # Inspeção somente leitura integrada à opção 4. Não cria opção no menu
    # e não altera a decisão do RE tradicional nem a fila Em Análise.
    if resumo.get("modo_analise_re") == "analise_simplificada":
        for item in resultado.get("campos_ausentes", []):
            item.update(diverge=False, status="inconclusivo", motivo="Campo ausente; revisão manual.")
        resultado["divergencias"] = [i for i in resultado.get("divergencias", []) if i.get("diverge")]
        if not resultado["divergencias"] and resultado.get("campos_ausentes"):
            resultado["status_geral"] = "parcial"
        try:
            diagnostico = diagnosticar_estrutura_atual(driver, wait, req)
            resumo["diagnostico_estrutura_re"] = diagnostico
            exibir_resumo_diagnostico(diagnostico)
        except Exception as exc:
            resumo["diagnostico_estrutura_re"] = {
                "status": "erro", "tabelas": [], "familias": [],
                "motivo": f"{type(exc).__name__}: {exc}",
            }
        cobertura = avaliar_cobertura_mvp(
            resumo["diagnostico_estrutura_re"], resultado, dados_pdf
        )
        resumo["cobertura_simplificada_re"] = cobertura
        # Não anunciar conformidade técnica completa em estruturas que o
        # comparador atual ainda não cobre (físicas, texto, intensidade,
        # múltiplas tabelas e secundárias).
        if not cobertura.get("comparacao_tecnica_integral"):
            tabela = resultado.get("comparacao_tabela_tecnica") or {}
            if tabela.get("status") in {"ok", "sem_tabela"}:
                tabela["status_original_comparador"] = tabela["status"]
                tabela["status"] = "comparacao_parcial"
                tabela["motivo"] = (
                    "Cobertura técnica limitada nesta versão; "
                    + cobertura.get("motivo", "Revisão manual.")
                )
            if resultado.get("status_geral") == "ok":
                resultado["status_geral"] = "parcial"
            resultado["motivo"] = cobertura.get("motivo", "Cobertura técnica parcial.")
        print(f"[SCH][RETORNO][MVP] {numero}: "
              f"{cobertura['status']} | {cobertura['motivo']}")
    if resultado.get("divergencias"):
        avisar_resultado_conferencia_sch_cct(resultado)
    else:
        resultado["mensagens_humanas"] = []
        print(f"[SCH][RETORNO][CCT x SCH] Dados gerais sem divergências detectadas; "
              f"cobertura da conferência: {resultado.get('status_geral')}.")
    print(
        f"[SCH][RETORNO][CCT x SCH] {numero}: "
        f"{resultado.get('status_geral', 'indefinido')} | "
        f"Datas: {datas.get('status_geral', 'indefinido')}"
    )
    return resultado



def _preencher_abas_com_regras_em_analise_no_re(driver, wait, req, resumo,
                                             simulacao=False, estado_simulacao=None):
    """Executa no módulo simplificado RE as MESMAS rotinas da fila Em Análise.

    Somente a opção 4 chama esta função. Nunca acessa Comparar Versões,
    aprova o requerimento ou aplica a limpeza de minuta do RE tradicional.
    Informação do OCD/Justificativa não deve ser alterada: a rotina de
    Informações Adicionais existente escreve em Acompanhar Processo.
    """
    if simulacao:
        from simulacao_simplificada_re import DriverSomenteLeitura
        if not isinstance(driver,DriverSomenteLeitura):
            raise RuntimeError('Simulação exige a barreira de somente leitura; driver sem proteção recusado.')
    numero = _numero_requerimento(req)
    resumo.setdefault("preenchimento_sch", {})
    dados_pdf = resumo.get("dados_pdf") or {}
    conferencia = resumo.get("conferencia_sch_cct") or {}
    resultado = {
        "status": "nao_executado",
        "motivo": "",
        "executado": False,
        "caracteristicas_tecnicas": {"status": "nao_executado"},
        "sar_minuta": {"status": "nao_executado"},
        "informacoes_adicionais": {"status": "nao_executado"},
    }
    resumo["preenchimento_analise_simplificada_re"] = resultado

    # A execução normal da opção 4 exige prova de download e identidade.
    # Simulações antigas/offline continuam testáveis, sem autorização de escrita.
    if not simulacao or (estado_simulacao or {}).get('exigir_download_real'):
        prova=resumo.get('confirmacao_cct_re') or {}
        import hashlib
        try:
            valido=(prova.get('status')=='confirmado'
                    and Path(prova['arquivo']).resolve()==Path(resumo['pdf_cct']).resolve()
                    and hashlib.sha256(Path(prova['arquivo']).read_bytes()).hexdigest()==prova['sha256'])
        except (KeyError,OSError,TypeError):
            valido=False
        if not valido:
            resultado.update(status='bloqueado_identidade_download',motivo='Novo download e identidade do CCT não confirmados; nenhuma escrita autorizada.')
            return resultado

    # Falha fechada: nenhum campo editado sem CCT selecionado, parseado e
    # uma conferência efetivamente concluída.
    if (
        not resumo.get("pdf_cct")
        or not dados_pdf
        or conferencia.get("status_geral") not in {"ok", "conforme", "divergente", "parcial"}
    ):
        resultado.update({
            "status": "nao_executado_sem_conferencia_valida",
            "motivo": "CCT ou conferência SCH x CCT indisponível; nenhuma aba foi modificada.",
        })
        print(f"[SCH][RETORNO][PREENCHIMENTO] {numero}: {resultado['motivo']}")
        return resultado

    # Não preencher a partir de certificado diferente do vigente no SCH,
    # mesmo que seja o anexo mais recente. Manter divergência no relatório.
    certificado_sch = str(
        (resumo.get("dados_certificado_sch") or {}).get("numero_certificado")
        or req.get("certificado") or ""
    ).strip()
    certificado_cct = str(dados_pdf.get("numero_certificado") or "").strip()
    norm_cert = lambda x: re.sub(r"[^a-z0-9]+", "", _normalizar_texto(x))
    if not norm_cert(certificado_sch) or not norm_cert(certificado_cct) or norm_cert(certificado_sch) != norm_cert(certificado_cct):
        resultado.update({
            "status": "bloqueado_certificado_nao_correspondente",
            "motivo": "Não foi confirmada a correspondência entre o certificado do SCH e o CCT mais recente; revisão manual necessária.",
            "certificado_sch": certificado_sch,
            "certificado_cct": certificado_cct,
        })
        print(f"[SCH][RETORNO][PREENCHIMENTO][WARN] {numero}: {resultado['motivo']}")
        return resultado

    def interromper(etapa, exc):
        resultado[etapa] = {"status": "erro", "erro": f"{type(exc).__name__}: {exc}"}
        resultado["status"] = "erro_parcial"
        resultado["motivo"] = f"Falha na etapa {etapa}; etapas seguintes não executadas."
        print(f"[SCH][RETORNO][PREENCHIMENTO][WARN] {numero}: {resultado['motivo']} {exc}")
        return resultado

    def confirmar_contexto():
        # O número do requerimento não é exibido no body de todas as abas.
        # Relê a seção estruturada Dados Gerais com a rotina já utilizada
        # na abertura: a identidade precisa continuar sendo a do CCT analisado.
        atuais = extrair_dados_certificado_sch(driver, wait) or {}
        certificado_atual = str(atuais.get("numero_certificado") or "").strip()
        if not certificado_atual or norm_cert(certificado_atual) != norm_cert(certificado_sch):
            raise RuntimeError("Certificado da tela atual não corresponde ao requerimento analisado; edição bloqueada.")
        modelo_inicial = _normalizar_texto(req.get("modelo_sch_dados_gerais"))
        modelo_atual = _normalizar_texto(atuais.get("modelo_sch_dados_gerais"))
        if not modelo_inicial or not modelo_atual or modelo_atual != modelo_inicial:
            raise RuntimeError("Modelos de Dados Gerais não confirmam o contexto original; edição bloqueada.")
        resultado["contexto_confirmado"] = {
            "requerimento": numero, "certificado": certificado_atual,
            "modelo": atuais["modelo_sch_dados_gerais"],
            "origem": "releitura_dados_gerais",
        }

    if simulacao:
        try:
            confirmar_contexto()
            from mvp_simplificada_re import planejar_acoes_simplificadas
            plano = planejar_acoes_simplificadas(req,resumo,estado_simulacao or {})
            resultado.update(plano)
            resultado.update(simulacao=True,executado=False,gravacoes_executadas=0,
                             contexto_confirmado=resultado.get('contexto_confirmado'))
            return resultado
        except Exception as exc:
            return interromper('contexto_simulacao',exc)

    resultado["executado"] = True
    print(f"[SCH][RETORNO][PREENCHIMENTO] {numero}: aplicando regras de Em Análise ao CCT mais recente.")

    # 1) Características Técnicas: Observação + Título das Secundárias.
    try:
        confirmar_contexto()
        caracteristicas = preencher_caracteristicas_conservadoras_re(
            driver=driver, wait=wait, req=req,
            anexos_baixados=resumo.get("anexos_baixados") or [],
            dados_pdf=dados_pdf,
        ) or {}
        resultado["caracteristicas_tecnicas"] = caracteristicas
        resumo["analise_rapida"] = caracteristicas
        resumo["observacao_caracteristicas"] = caracteristicas.get("texto", "")
        resumo["preenchimento_sch"]["caracteristicas"] = bool(
            caracteristicas.get("preenchido_automaticamente") and caracteristicas.get("salvo")
        )
        resumo["caracteristicas_secundarias"] = caracteristicas.get(
            "titulo_caracteristicas_secundarias", {}
        )
        if not caracteristicas.get("sem_alteracao") and (not caracteristicas.get("salvo") or not caracteristicas.get("confirmado_apos_salvar")):
            resultado["status"] = "erro_parcial"
            resultado["motivo"] = "Características Técnicas não tiveram salvamento e conferência confirmados; demais abas não foram alteradas."
            return resultado
    except Exception as exc:
        return interromper("caracteristicas_tecnicas", exc)

    # 2) Corrigir Minuta: somente SAR, conforme análise do CCT em Em Análise.
    # A limpeza de Especificações Complementares do RE tradicional NÃO participa.
    try:
        confirmar_contexto()
        sar = preencher_minuta_sar_se_necessario(
            driver=driver, wait=wait, dados_pdf=dados_pdf, preservar_existente=True
        ) or {}
        sar["modo"] = "analise_sar_cct_em_analise_re_simplificada"
        resultado["sar_minuta"] = sar
        resumo["sar_minuta"] = sar
        resumo["resultado_minuta"] = sar
        resumo["minuta"] = {
            "preenchida": bool(sar.get("preenchido_automaticamente")),
            "campo_limpo": False,
            "alterada": bool(sar.get("preenchido_automaticamente")),
            "salvo": bool(sar.get("salvo")),
            "confirmado_apos_salvar": bool(sar.get("confirmado_apos_salvar")),
            "status": sar.get("status", ""),
            "mensagem": sar.get("mensagem", ""),
            "frase": sar.get("frase", ""),
            "modo": sar["modo"],
        }
        resumo["preenchimento_sch"]["minuta"] = bool(
            sar.get("preenchido_automaticamente") and sar.get("salvo")
        )
        if sar.get("status") not in {"sar_aplicavel", "sar_nao_aplicavel", "revisar", "preenchido", "preservado"} or (sar.get("preencher_frase") and (
            not sar.get("salvo")
            or not sar.get("confirmado_apos_salvar")
            or not sar.get("retornou_para_requerimento")
        )):
            resultado["status"] = "erro_parcial"
            resultado["motivo"] = "SAR exigiu minuta, mas salvamento/retorno não foi confirmado; Acompanhar Processo não foi alterado."
            return resultado
    except Exception as exc:
        return interromper("sar_minuta", exc)

    # 3) Informações Adicionais: texto de Análise Simplificada em Acompanhar
    # Processo, não na Justificativa do OCD nem na Descrição de RE.
    try:
        confirmar_contexto()
        from funcoes_sch import TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES
        informacoes = preencher_acompanhamento_seguro_re(
            driver=driver, wait=wait,
            frase=TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES,
        ) or {}
        resultado["informacoes_adicionais"] = informacoes
        resumo["informacoes_adicionais"] = informacoes
        resumo["preenchimento_sch"]["informacoes_adicionais"] = bool(
            informacoes.get("preenchido_automaticamente") and informacoes.get("salvo")
        )
        if not informacoes.get("salvo") or not informacoes.get("confirmado_apos_salvar"):
            resultado["status"] = "erro_parcial"
            resultado["motivo"] = "Não foi possível confirmar o preenchimento de Acompanhar Processo."
            return resultado
    except Exception as exc:
        return interromper("informacoes_adicionais", exc)

    resultado["status"] = "concluido"
    resultado["motivo"] = "Rotinas de Em Análise executadas na opção 4 de RE."
    print(f"[SCH][RETORNO][PREENCHIMENTO] {numero}: preenchimento concluído.")
    return resultado

def executar_fluxo_sch(
    pasta_base,
    limite_requerimentos=None,
    requerimento_especifico=None,
    navegador=None,
    quantidade_exibida_sch=100,
    processar_somente_pendentes=False,
    processar_apenas_radiacao_restrita=True,
    preencher_caracteristicas=True,
    preencher_minuta=True,
    preencher_informacoes_adicionais=False,
    pausar_antes_anexos=False,
    categorias_anexos=None,
    fechar_navegador_ao_final=None,
    fila_sch=None,
    executar_envio_retorno_para_estudo=False,
    modo_analise_re="ambos",
):
    pasta_base = Path(pasta_base).resolve()
    pasta_base.mkdir(parents=True, exist_ok=True)

    if not fila_sch:
        fila_sch = perguntar_fila_sch()

    fila_retorno = _eh_fila_retorno_para_estudo(fila_sch)
    if fila_retorno and modo_analise_re not in MODOS_ANALISE_RE:
        raise ValueError(f"Modo RE inválido: {modo_analise_re!r}")
    if fila_retorno:
        if modo_analise_re == "analise_simplificada":
            executar_envio_retorno_para_estudo = False
        # Em RE, os documentos são definidos pelo modo, não pelo seletor global.
        categorias_anexos = (
            [] if modo_analise_re == "comparar_versoes"
            else [CATEGORIA_CCT, CATEGORIA_RACT]
        )
        print(f"[SCH][RETORNO] Modo: {modo_analise_re}")
        print("[SCH][RETORNO] Documentos do modo: " +
              (", ".join(categorias_anexos) if categorias_anexos else "Nenhum"))
    print(f"[SCH] Fila selecionada para processamento: {fila_sch}")

    regras = carregar_regras()
    regras["pausar_antes_anexos"] = pausar_antes_anexos

    # categorias_anexos=None  -> usa a configuração padrão do sistema.
    # categorias_anexos=[]    -> opção explícita "Nenhuma": não abre Anexos
    #                            e não realiza downloads.
    # categorias_anexos=[...] -> baixa somente as categorias escolhidas.
    categorias_anexos_informadas = categorias_anexos is not None

    if categorias_anexos_informadas:
        categorias_anexos_ativas = list(categorias_anexos or [])
        baixar_anexos_habilitado = bool(categorias_anexos_ativas)
        modo_download_anexos = (
            "categorias_selecionadas"
            if baixar_anexos_habilitado
            else "nenhuma"
        )
    else:
        categorias_anexos_ativas = list(
            regras.get("categorias_anexos", []) or []
        )
        baixar_anexos_habilitado = True
        modo_download_anexos = "padrao_sistema"

    if categorias_anexos_ativas:
        regras["categorias_anexos"] = categorias_anexos_ativas

    if limite_requerimentos:
        regras["limite_requerimentos"] = int(limite_requerimentos)

    # O filtro genérico de radiação restrita é usado somente em Em Análise.
    # Em Retorno Para Estudo existe um filtro próprio e positivo por tipo de
    # produto, aplicado ainda na fila antes de abrir qualquer requerimento.
    processar_apenas_rr_efetivo = (
        bool(processar_apenas_radiacao_restrita)
        and not fila_retorno
    )

    print(
        "[SCH] Navegador selecionado no menu: "
        f"{(_normalizar_navegador_preferido(navegador) or 'padrão').title()}"
    )

    driver, wait, pasta_saida_driver, pasta_download = (
        _criar_driver_com_pasta(
            pasta_base,
            navegador=navegador,
        )
    )

    if Path(pasta_saida_driver).resolve() != pasta_base:
        print(f"[WARN] O navegador retornou pasta de saída diferente da escolhida: {pasta_saida_driver}")
        print(f"[INFO] Os relatórios e requerimentos continuarão sendo organizados em: {pasta_base}")

    relatorio_execucao = []

    if fechar_navegador_ao_final is None:
        fechar_navegador_ao_final = perguntar_se_fecha_navegador()

    inicio_execucao = datetime.now()
    requerimentos = []
    requerimentos_processaveis = []
    requerimentos_ignorados = []
    ignorados_resumidos = []

    try:
        abrir_sch(driver)
        aguardar_enter("[SCH] Faça o login manualmente no sistema e pressione Enter para continuar.")

        inicio_execucao = datetime.now()

        clicar_fila_sch(driver, wait, fila_sch)

        resultado_paginacao = selecionar_quantidade_registros_fila(
            driver=driver,
            wait=wait,
            quantidade=quantidade_exibida_sch,
        )

        print(
            "[SCH] Registros configurados por página: "
            f"{resultado_paginacao.get('valor_final', quantidade_exibida_sch)}"
        )

        requerimentos = coletar_requerimentos(driver, wait, regras)

        for req in requerimentos:
            if isinstance(req, dict):
                req["fila_sch"] = fila_sch

        requerimentos = list(reversed(requerimentos))

        # No RE, homologações 2026+ deixam de ser removidas da lista.
        # O bloqueio continua pertencendo APENAS à análise tradicional de RE;
        # o módulo independente CCT x SCH ainda pode analisar esses processos.
        ignorados_homologacao_2026_mais = []
        if fila_retorno:
            print("[SCH][RETORNO] Homologação 2026+ restringe apenas o módulo tradicional RE.")

        if requerimento_especifico:
            requerimentos_encontrados = [
                req
                for req in requerimentos
                if _requerimento_corresponde_ao_alvo(
                    req,
                    requerimento_especifico,
                )
            ]

            if not requerimentos_encontrados:
                ignorado_2026 = next(
                    (
                        item for item in ignorados_homologacao_2026_mais
                        if _requerimento_corresponde_ao_alvo(
                            item, requerimento_especifico
                        )
                    ),
                    None,
                )

                if ignorado_2026:
                    print(
                        "[SCH][IGNORADO] O requerimento específico foi "
                        "encontrado na fila, mas foi ignorado pela regra de "
                        "homologação 2026 ou posterior: "
                        f"{requerimento_especifico}."
                    )
                else:
                    print(
                        "[SCH][WARN] O requerimento específico não foi "
                        f"encontrado na fila: {requerimento_especifico}"
                    )

            requerimentos = requerimentos_encontrados

        elif limite_requerimentos:
            requerimentos = requerimentos[
                : int(limite_requerimentos)
            ]

        requerimentos_processaveis, requerimentos_ignorados_escopo = separar_requerimentos_por_escopo(
            requerimentos,
            processar_apenas_rr=processar_apenas_rr_efetivo,
        )

        ignorados_tipo_produto_retorno = []

        if fila_retorno:
            selecionados = []
            for req in requerimentos_processaveis:
                if not isinstance(req, dict):
                    continue
                if modo_analise_re == "analise_simplificada" and not _tipo_produto_permitido_simplificada(req):
                    item = dict(req)
                    item.update(motivo="tipo_produto_fora_escopo_analise_simplificada",
                                mensagem="Opção 4 aceita somente ETA e Transceptor de Radiação Restrita; ignorado antes de abrir e baixar documentos.")
                    ignorados_tipo_produto_retorno.append(item)
                    continue
                escopos = _escopos_para_modo_re(
                    _definir_escopos_re(req, modo=modo_analise_re), modo_analise_re
                )
                req["escopo_modulos_re"] = escopos
                if escopos["analise_tradicional_re"] or escopos["comparacao_cct_sch"]:
                    selecionados.append(req)
                    print(
                        f"[SCH][RETORNO][ESCOPO] {_numero_requerimento(req)} | "
                        f"RE tradicional={escopos['analise_tradicional_re']} | "
                        f"CCT x SCH={escopos['comparacao_cct_sch']}"
                    )
                else:
                    item = dict(req)
                    item["motivo"] = "fora_escopo_ambos_modulos_re"
                    item["mensagem"] = (
                        "Fora do escopo dos dois módulos: análise tradicional RE "
                        "e comparação CCT x SCH. Nenhuma etapa interna executada."
                    )
                    ignorados_tipo_produto_retorno.append(item)
            requerimentos_processaveis = selecionados

        requerimentos_ignorados = (
            list(ignorados_homologacao_2026_mais)
            + list(requerimentos_ignorados_escopo)
            + list(ignorados_tipo_produto_retorno)
        )

        pasta_requerimentos, mapeados = preparar_pastas_requerimentos(
            pasta_base,
            requerimentos_processaveis,
        )

        if processar_somente_pendentes:
            pendentes = {
                item["requerimento"]
                for item in mapeados
                if item["status"] == "pendente"
            }

            requerimentos_processaveis = [
                req
                for req in requerimentos_processaveis
                if _numero_requerimento(req) in pendentes
            ]

        ignorados_resumidos = _montar_ignorados_resumidos(requerimentos_ignorados)

        print("[SCH] Mapeando requerimentos...")
        print(f"[SCH] Total coletado na fila: {len(requerimentos)}")
        print(f"[SCH] Dentro do escopo: {len(requerimentos_processaveis)}")
        print(f"[SCH] Fora do escopo: {len(requerimentos_ignorados)}")
        print(f"[SCH] Pasta base da execução: {pasta_base}")
        print(
            "[SCH] Registros exibidos por página no SCH: "
            f"{quantidade_exibida_sch}"
        )
        print(f"[SCH] Filtro radiação restrita efetivo: {'sim' if processar_apenas_rr_efetivo else 'não'}")
        print(
            "[SCH] Categorias de anexos configuradas: "
            + (
                ", ".join(categorias_anexos_ativas)
                if categorias_anexos_ativas
                else "nenhuma"
                if modo_download_anexos == "nenhuma"
                else "padrão do sistema"
            )
        )
        print(
            "[SCH] Download de anexos: "
            f"{'habilitado' if baixar_anexos_habilitado else 'desabilitado (Nenhuma)'}"
        )

        caminho_manifesto = salvar_manifesto_requerimentos(
            pasta_base,
            mapeados,
            ignorados=ignorados_resumidos,
        )
        print(f"[SCH] Manifesto salvo em: {caminho_manifesto}")

        if not requerimentos_processaveis:
            print("[SCH][WARN] Nenhum requerimento selecionado para processamento.")
            _gerar_relatorios_parciais_execucao(
                pasta_base=pasta_base,
                relatorio_execucao=relatorio_execucao,
                inicio_execucao=inicio_execucao,
                fila_sch=fila_sch,
                requerimentos=requerimentos,
                requerimentos_processaveis=requerimentos_processaveis,
                requerimentos_ignorados=requerimentos_ignorados,
                ignorados_resumidos=ignorados_resumidos,
                versao_script=VERSAO_SCRIPT,
                categorias_anexos_ativas=categorias_anexos_ativas,
                processar_apenas_rr_efetivo=processar_apenas_rr_efetivo,
                status_execucao="finalizado",
                imprimir=True,
            )
            return

        for req in requerimentos_processaveis:
            if not isinstance(req, dict):
                print(
                    f"[SCH][WARN] Item inválido em requerimentos_processaveis: "
                    f"{type(req).__name__} -> {req}"
                )
                continue

            numero = _numero_requerimento(req)
            pasta_req = pasta_requerimentos / nome_seguro(numero)

            if not req.get("nome_comercial"):
                req["nome_comercial"] = req.get("modelo", "")

            if not req.get("modelo_sch_dados_gerais"):
                req["modelo_sch_dados_gerais"] = req.get("modelo", "")

            print("=" * 90)
            print(f"[SCH] Iniciando processamento do requerimento {numero}")
            print(f"[SCH] Pasta do requerimento: {pasta_req}")
            print("=" * 90)

            resumo = {
                "requerimento": req,
                "pasta_requerimento": str(pasta_req),
                "fila_sch": fila_sch,
                "modo_analise_re": modo_analise_re if fila_retorno else None,
                "navegador": (
                    _normalizar_navegador_preferido(navegador)
                    or "padrao"
                ),
                "requerimento_especifico_configurado": (
                    requerimento_especifico or ""
                ),
                "quantidade_exibida_sch": quantidade_exibida_sch,
                "anexos_baixados": [],
                "dados_pdf": {},
                "pdf_cct": "",
                "validade_cct": {},
                "dados_certificado_sch": {},
                "comparacao_datas_sch_cct": {},
                "sar_minuta": {},
                "caracteristicas_secundarias": {},
                "texto_caracteristicas_secundarias": "",
                "tabela_tecnica_sch": {},
                "conferencia_sch_cct": {},
                "preenchimento_analise_simplificada_re": {},
                "retorno_para_estudo": {},
                "escopo_modulos_re": dict(req.get("escopo_modulos_re") or {}) if fila_retorno else {},
                "downloads_realizados": 0,
                "status": "iniciado",
                "inicio": datetime.now().isoformat(),
                "fim": None,
                "versao_script": VERSAO_SCRIPT,
                "escopo_processamento": "retorno_para_estudo" if fila_retorno else (
                    "radiacao_restrita" if processar_apenas_rr_efetivo else "todos"
                ),
                "escopo_normativo": _dados_normativos_retorno_para_estudo() if fila_retorno else _dados_normativos_radiacao_restrita(),
                "categorias_anexos_configuradas": categorias_anexos_ativas,
                "modo_download_anexos": modo_download_anexos,
                "download_anexos_habilitado": bool(baixar_anexos_habilitado),
                "preenchimento_sch": {
                    "minuta": False,
                    "minuta_habilitada": (
                        modo_analise_re in {"comparar_versoes", "analise_simplificada", "ambos"}
                        if fila_retorno else bool(preencher_minuta)
                    ),
                    "modo_minuta": (
                        ("analise_sar_cct" if modo_analise_re == "analise_simplificada" else "limpeza_especificacoes_complementares")
                        if fila_retorno
                        else "analise_sar_cct"
                    ),
                    "caracteristicas": False if fila_retorno else bool(preencher_caracteristicas),
                    "caracteristicas_secundarias_retorno": bool(
                        fila_retorno
                    ),
                    "informacoes_adicionais": False if fila_retorno else bool(preencher_informacoes_adicionais),
                },
                "minuta": {
                    "preenchida": False,
                    "campo_limpo": False,
                    "alterada": False,
                    "salvo": False,
                    "confirmado_apos_salvar": False,
                    "status": (
                        "pendente_limpeza_especificacoes_complementares"
                        if fila_retorno
                        else "pendente_analise_sar_cct"
                        if preencher_minuta
                        else "desabilitado_pelo_usuario"
                    ),
                    "mensagem": (
                        "Na fila Retorno Para Estudo, Corrigir Minuta será usado somente para apagar "
                        "Especificações Complementares dos tipos de produto configurados."
                        if fila_retorno
                        else "Na fila Em Análise, Corrigir Minuta será tratado somente pela análise de SAR do CCT."
                        if preencher_minuta
                        else "Tratamento de Corrigir Minuta desabilitado pelo usuário."
                    ),
                    "frase": "",
                    "modo": (
                        "limpeza_especificacoes_complementares"
                        if fila_retorno
                        else "analise_sar_cct"
                    ),
                },
            }

            dados_certificado_sch = {}
            interrompido_pelo_usuario = False

            try:
                garantir_sessao_ativa_sch(
                    driver,
                    wait,
                    contexto=f"antes de iniciar o requerimento {numero}",
                    reabrir_fila=True,
                    nome_fila=fila_sch,
                )

                abrir_requerimento(driver, wait, req)

                try:
                    dados_certificado_sch = extrair_dados_certificado_sch(driver, wait)
                    dados_certificado_sch = dados_certificado_sch or {}

                    if fila_retorno:
                        modalidade_visivel = _extrair_modalidade_avaliacao_visivel_sch(driver)
                        if modalidade_visivel:
                            dados_certificado_sch["modalidade_avaliacao"] = modalidade_visivel
                            resumo["modalidade_avaliacao_sch"] = modalidade_visivel

                    nome_comercial_sch = str(
                        dados_certificado_sch.get("nome_comercial") or ""
                    ).strip()

                    modelo_sch_dados_gerais = str(
                        dados_certificado_sch.get("modelo_sch_dados_gerais") or ""
                    ).strip()

                    if nome_comercial_sch:
                        req["nome_comercial"] = nome_comercial_sch

                    if modelo_sch_dados_gerais:
                        req["modelo_sch_dados_gerais"] = modelo_sch_dados_gerais

                    if not str(req.get("nome_comercial") or "").strip():
                        req["nome_comercial"] = req.get("modelo_sch_dados_gerais") or req.get("modelo", "")

                    resumo["dados_certificado_sch"] = dados_certificado_sch
                    resumo["nome_comercial_sch"] = req.get("nome_comercial", "")
                    resumo["modelo_sch_dados_gerais"] = req.get("modelo_sch_dados_gerais", "")
                    req["dados_certificado_sch"] = dados_certificado_sch

                    print(
                        "[SCH] Produto no SCH: "
                        f"modelo_dados_gerais={req.get('modelo_sch_dados_gerais', '')} | "
                        f"nome_comercial={req.get('nome_comercial', '')}"
                    )

                except Exception as e:
                    print(f"[SCH][WARN] Não foi possível extrair dados do certificado/produto no SCH: {e}")
                    dados_certificado_sch = {}
                    resumo["dados_certificado_sch"] = {}

                    if not str(req.get("nome_comercial") or "").strip():
                        req["nome_comercial"] = req.get("modelo", "")

                    if not str(req.get("modelo_sch_dados_gerais") or "").strip():
                        req["modelo_sch_dados_gerais"] = req.get("modelo", "")

                    resumo["nome_comercial_sch"] = req.get("nome_comercial", "")
                    resumo["modelo_sch_dados_gerais"] = req.get("modelo_sch_dados_gerais", "")

                # A opção geral "Nenhuma" não desliga o CCT obrigatório do
                # módulo independente de RE. Não força download de outros anexos.
                escopos_re = req.get("escopo_modulos_re") or {}
                executar_re_tradicional = bool(fila_retorno and escopos_re.get("analise_tradicional_re"))
                executar_cct_re = bool(fila_retorno and escopos_re.get("comparacao_cct_sch"))

                # Após entrar nos Dados Gerais, é possível haver mais metadados;
                # impedir comparação se a modalidade explícita for Declaração.
                if executar_cct_re:
                    elegibilidade_final = _escopo_conferencia_cct_re(req, dados_certificado_sch)
                    if not elegibilidade_final["executar"]:
                        executar_cct_re = False
                        escopos_re["comparacao_cct_sch"] = False
                        escopos_re["motivo_comparacao_cct"] = elegibilidade_final["motivo"]
                        escopos_re["descricao_comparacao_cct"] = elegibilidade_final["descricao"]
                        resumo["escopo_modulos_re"] = dict(escopos_re)

                if fila_retorno:
                    # No modo Comparar Versões, nem CCT nem RACT devem ser
                    # baixados. Em Simplificada/Ambos, baixar só CCT e RACT
                    # dos requerimentos elegíveis à conferência.
                    categorias_para_requerimento = (
                        [CATEGORIA_CCT, CATEGORIA_RACT] if executar_cct_re else []
                    )
                    download_requerimento_habilitado = bool(categorias_para_requerimento)
                else:
                    categorias_para_requerimento = list(categorias_anexos_ativas)
                    download_requerimento_habilitado = baixar_anexos_habilitado
                regras_anexos_requerimento = dict(regras)
                download_confirmado_opcao4 = bool(fila_retorno and executar_cct_re and modo_analise_re == 'analise_simplificada')
                if download_confirmado_opcao4:
                    # CCT é baixado separadamente, sem reutilização por nome.
                    categorias_para_requerimento = [c for c in categorias_para_requerimento if c != CATEGORIA_CCT]
                if fila_retorno or categorias_anexos_informadas:
                    regras_anexos_requerimento["categorias_anexos"] = categorias_para_requerimento

                if download_requerimento_habilitado:
                    clicar_aba_anexos(driver, wait)
                    anexos_baixados = baixar_todos_os_anexos_de_todas_as_categorias(
                        driver=driver,
                        wait=wait,
                        req=req,
                        pasta_saida=pasta_req,
                        pasta_download=pasta_download,
                        regras=regras_anexos_requerimento,
                    )
                    resumo["anexos_baixados"] = anexos_baixados or []
                else:
                    anexos_baixados = []
                    resumo["anexos_baixados"] = []
                    print("[SCH] Download de anexos não executado: módulo sem documentos ou produto não elegível.")

                resumo["categorias_anexos_efetivas"] = categorias_para_requerimento
                resumo["download_cct_obrigatorio_re"] = executar_cct_re

                # Comparar Versões não precisa localizar/analisar CCT, mesmo
                # quando houver PDF antigo na pasta de outra execução.
                deve_buscar_cct = (executar_cct_re if fila_retorno else True)
                if fila_retorno and executar_cct_re:
                    # RE simplificada: data/hora do ANEXO no SCH, nunca o
                    # instante em que o Python fez o download dos PDFs.
                    if download_confirmado_opcao4:
                        from funcoes_sch import baixar_cct_mais_recente_confirmado_re
                        selecao_cct, registros_cct = baixar_cct_mais_recente_confirmado_re(
                            driver,wait,req,pasta_req,pasta_download)
                        anexos_baixados.extend(registros_cct)
                        resumo['anexos_baixados']=anexos_baixados
                        prova=confirmar_identidade_cct_baixado_re(selecao_cct,registros_cct,dados_certificado_sch or {},req)
                        resumo['confirmacao_cct_re']=prova
                        if prova.get('status')!='confirmado':
                            selecao_cct=dict(selecao_cct,arquivo='',status='identidade_cct_nao_confirmada',motivo='; '.join(prova['motivos']))
                    else:
                        selecao_cct = _selecionar_cct_mais_recente_re(anexos_baixados, pasta_req)
                    resumo["selecao_cct_re"] = selecao_cct
                    pdf_cct = (
                        Path(selecao_cct["arquivo"])
                        if selecao_cct.get("arquivo") else None
                    )
                    print(
                        f"[SCH][RETORNO][CCT] {numero}: "
                        f"{selecao_cct['status']} | ID={selecao_cct.get('id', '')} | "
                        f"Data-Hora={selecao_cct.get('data_hora', '')} | "
                        f"Arquivo={selecao_cct.get('nome_anexo', '')}"
                    )
                    if not pdf_cct:
                        print(f"[SCH][RETORNO][CCT][WARN] {selecao_cct['motivo']}")
                else:
                    pdf_cct = (
                        localizar_pdf_cct_do_requerimento(pasta_req, regras)
                        if deve_buscar_cct else None
                    )
                resumo["pdf_cct"] = str(pdf_cct) if pdf_cct else ""

                # ==========================================================
                # FLUXO ESPECIAL: Retorno Para Estudo
                # Baixa anexos, abre Comparar Versões, compara versão antiga x nova
                # e gera relatório próprio de retorno. Não executa a análise completa
                # SCH x CCT da fila Em Análise.
                # ==========================================================
                if fila_retorno:
                    # RE traditional só ocorre nos tipos/anos já permitidos.
                    # O CCT x SCH segue fluxo próprio, mesmo quando o RE
                    # tradicional não está habilitado para este requerimento.
                    if not executar_cct_re:
                        motivo_cct = escopos_re.get("motivo_comparacao_cct", "")
                        resumo["conferencia_sch_cct"] = {
                            "status_geral": (
                                "nao_executada_opcao_usuario" if motivo_cct == "nao_executada_opcao_usuario"
                                else "fora_escopo_cct"
                            ),
                            "motivo": escopos_re.get("descricao_comparacao_cct", "Excluído da comparação CCT x SCH."),
                            "comparacoes": [], "divergencias": [],
                        }
                    if not executar_re_tradicional:
                        resumo["retorno_para_estudo"] = {
                            "status_comparacao": "nao_executada_fora_escopo_tradicional",
                            "comparacao_executada": False,
                            "pode_enviar_para_aprovacao": False,
                            "deve_enviar_para_aprovacao": False,
                            "envio_para_aprovacao": {"executado": False, "motivo": "modulo_tradicional_fora_escopo"},
                            "motivo": (
                                "Análise tradicional RE não selecionada pelo usuário."
                                if modo_analise_re == "analise_simplificada"
                                else "Análise tradicional RE fora do escopo; somente CCT x SCH habilitado."
                            ),
                        }
                        if executar_cct_re:
                            _conferir_cct_sch_independente_re(
                                driver=driver, wait=wait, req=req,
                                pdf_cct=pdf_cct,
                                dados_certificado_sch=dados_certificado_sch,
                                resumo=resumo, tela_requerimento_restaurada=True,
                            )
                            if modo_analise_re == "analise_simplificada":
                                _preencher_abas_com_regras_em_analise_no_re(
                                    driver=driver, wait=wait, req=req, resumo=resumo,
                                )
                            else:
                                resumo["preenchimento_analise_simplificada_re"] = {
                                    "status": "nao_executado_modo_combinado",
                                    "executado": False,
                                    "motivo": "Modo combinado preserva as ações exclusivas do RE tradicional; preenchimentos de Em Análise não foram acionados.",
                                }
                        preenchimento_re = resumo.get("preenchimento_analise_simplificada_re") or {}
                        resumo["status"] = (
                            "erro" if modo_analise_re == "analise_simplificada"
                            and preenchimento_re.get("status") == "erro_parcial" else "sucesso"
                        )
                        resumo["fim"] = datetime.now().isoformat()
                        resumo["downloads_realizados"] = contar_arquivos_requerimento(pasta_req)
                        _salvar_controle_downloads(
                            pasta_req=pasta_req, numero=numero,
                            qtd_downloads=resumo["downloads_realizados"],
                            categorias_anexos_ativas=categorias_para_requerimento,
                            anexos_baixados=resumo["anexos_baixados"],
                            escopo_processamento=resumo["escopo_processamento"],
                            fila_sch=fila_sch,
                            retorno_para_estudo=resumo["retorno_para_estudo"],
                        )
                        print(f"[SCH][RETORNO][CCT x SCH] {numero}: conferência exclusiva finalizada; nenhuma ação tradicional RE.")
                        continue

                    qtd_downloads = contar_arquivos_requerimento(pasta_req)
                    resumo["downloads_realizados"] = qtd_downloads

                    # Guarda explicitamente a aba original do requerimento.
                    # Comparar Versões pode abrir uma aba nova ou about:blank.
                    aba_original_sch = driver.current_window_handle

                    # Primeiro compara as versões, mas NÃO aprova ainda.
                    retorno_estudo = analisar_retorno_para_estudo(
                        driver=driver,
                        wait=wait,
                        req=req,
                        anexos_baixados=resumo["anexos_baixados"],
                        executar_envio=False,
                    )

                    # Conferência independente CCT x SCH para RE.
                    # Não muda a decisão dos analisadores dos Tipos RE e
                    # não escreve em nenhuma aba do requerimento.
                    # A comparação de RE pode ter aberto outra janela; somente
                    # extraímos a tabela após retornar ao requerimento original.
                    if executar_cct_re and pdf_cct:
                        try:
                            restauracao_para_cct_re = (
                                restaurar_tela_requerimento_apos_comparacao(
                                    driver=driver,
                                    wait=wait,
                                    aba_original_sch=aba_original_sch,
                                    info_abertura={},
                                )
                            )
                            tela_para_cct_re = bool(
                                restauracao_para_cct_re.get("restaurado")
                            )
                        except Exception as e:
                            tela_para_cct_re = False
                            print(
                                "[SCH][RETORNO][CCT x SCH][WARN] "
                                f"Falha na restauração: {e}"
                            )
                    else:
                        tela_para_cct_re = False

                    if executar_cct_re:
                        try:
                            _conferir_cct_sch_independente_re(
                                driver=driver,
                                wait=wait,
                                req=req,
                                pdf_cct=pdf_cct,
                                dados_certificado_sch=dados_certificado_sch,
                                resumo=resumo,
                                tela_requerimento_restaurada=tela_para_cct_re,
                            )
                        except Exception as e:
                            print(
                                "[SCH][RETORNO][CCT x SCH][WARN] Falha na "
                                f"conferência independente: {type(e).__name__}: {e}"
                            )
                            resumo["conferencia_sch_cct"] = {
                                "status_geral": "erro",
                                "motivo": f"{type(e).__name__}: {e}",
                                "comparacoes": [],
                                "divergencias": [],
                                "campos_ausentes": [],
                            }

                    if executar_cct_re and modo_analise_re == "ambos":
                        resumo["preenchimento_analise_simplificada_re"] = {
                            "status": "nao_executado_modo_combinado",
                            "executado": False,
                            "motivo": "No modo combinado, ações de escrita permanecem sob as regras tradicionais de RE para evitar conflito com a minuta e Acompanhar Processo.",
                        }

                    # IMPORTANTE:
                    # analisar_retorno_para_estudo pode encerrar cedo quando
                    # Informações Adicionais indicam tipo RE fora do escopo,
                    # quando não foi possível ler o campo ou quando Comparar
                    # Versões falhou. Nesses casos NÃO podemos abrir Corrigir
                    # Minuta, substituir Informações Adicionais nem aprovar.
                    status_retorno_inicial = str(
                        retorno_estudo.get("status_comparacao") or ""
                    ).strip()

                    comparacao_concluida = status_retorno_inicial in {
                        "analises_re_individuais_aptas",
                        "analises_re_individuais_nao_aptas",
                        # Compatibilidade com resultados antigos.
                        "manutencao_tacita_apta",
                        "manutencao_tacita_nao_apta",
                    }
                    retorno_estudo["comparacao_executada"] = bool(
                        comparacao_concluida
                    )

                    if not comparacao_concluida:
                        tipo_produto = req.get("tipo_produto", "")

                        resultado_minuta = {
                            "aplicavel": False,
                            "tratado": False,
                            "limpo": False,
                            "substituido": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                            "status": "nao_executada_analise_interrompida",
                            "mensagem": (
                                "Corrigir Minuta não foi executado porque a "
                                "análise do Retorno Para Estudo foi encerrada "
                                "antes de uma comparação válida."
                            ),
                            "modo": (
                                "tratamento_especificacoes_complementares_"
                                "retorno_para_estudo"
                            ),
                            "tipo_produto": tipo_produto,
                        }

                        retorno_estudo["corrigir_minuta"] = resultado_minuta
                        retorno_estudo["tratamento_minuta_exigido"] = False
                        retorno_estudo["tratamento_minuta_confirmado"] = False
                        retorno_estudo["limpeza_minuta_exigida"] = False
                        retorno_estudo["limpeza_minuta_confirmada"] = False

                        retorno_estudo[
                            "marcacao_automacao_informacoes_adicionais"
                        ] = {
                            "exigida": False,
                            "preenchida": False,
                            "salva": False,
                            "confirmada_apos_salvar": False,
                            "status": (
                                "nao_executada_analise_interrompida_antes_da_aprovacao"
                            ),
                        }

                        retorno_estudo["envio_para_aprovacao"] = {
                            "executado": False,
                            "motivo": (
                                "analise_retorno_interrompida_antes_da_etapa_de_aprovacao"
                            ),
                        }
                        retorno_estudo["caracteristicas_secundarias"] = {
                            "executado": False,
                            "status": (
                                "nao_executada_analise_interrompida"
                            ),
                            "motivo": (
                                "Características Secundárias não foram "
                                "alteradas porque a análise do Retorno não "
                                "chegou a uma comparação válida."
                            ),
                            "fila": "Retorno Para Estudo",
                        }
                        resumo["caracteristicas_secundarias_retorno"] = (
                            retorno_estudo["caracteristicas_secundarias"]
                        )
                        retorno_estudo["pode_enviar_para_aprovacao"] = False
                        retorno_estudo["deve_enviar_para_aprovacao"] = False
                        retorno_estudo["resultado_execucao_analise"] = (
                            "nao_analisado_comparar_versoes"
                        )

                        # Não transformar ausência de comparação em False.
                        # O relatório deve conseguir distinguir:
                        # True=alterado, False=conferido/sem alteração,
                        # None=não analisado.
                        for campo_nao_analisado in (
                            "produto_alterado",
                            "dados_tecnicos_alterados",
                            "unidade_fabril_alterada",
                            "documentos_novos_detectados",
                            "documentos_obrigatorios_ok",
                        ):
                            retorno_estudo[campo_nao_analisado] = None

                        resumo["retorno_para_estudo"] = retorno_estudo
                        resumo["resultado_minuta"] = resultado_minuta
                        resumo[
                            "marcacao_automacao_informacoes_adicionais"
                        ] = retorno_estudo.get(
                            "marcacao_automacao_informacoes_adicionais",
                            {},
                        )
                        resumo["sar_minuta"] = {
                            "status": "nao_aplicavel_fila_retorno_para_estudo",
                            "mensagem": (
                                "A fila Retorno Para Estudo não executa "
                                "julgamento de SAR."
                            ),
                            "preencher_frase": False,
                            "preenchido_automaticamente": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                        }
                        resumo["minuta"] = {
                            "preenchida": False,
                            "campo_limpo": False,
                            "campo_substituido": False,
                            "tratado": False,
                            "alterada": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                            "status": resultado_minuta["status"],
                            "mensagem": resultado_minuta["mensagem"],
                            "frase": "",
                            "modo": resultado_minuta["modo"],
                            "tipo_produto": tipo_produto,
                        }
                        resumo["preenchimento_sch"]["minuta"] = False
                        resumo["status"] = "sucesso"
                        resumo["fim"] = datetime.now().isoformat()

                        _salvar_controle_downloads(
                            pasta_req=pasta_req,
                            numero=numero,
                            qtd_downloads=qtd_downloads,
                            categorias_anexos_ativas=categorias_anexos_ativas,
                            anexos_baixados=resumo["anexos_baixados"],
                            escopo_processamento=resumo["escopo_processamento"],
                            fila_sch=fila_sch,
                            retorno_para_estudo=retorno_estudo,
                        )

                        print(
                            "[SCH][RETORNO] Pós-processamento não executado. "
                            f"Status={status_retorno_inicial or 'não informado'} | "
                            "Corrigir Minuta=NÃO | "
                            "Registro em Informações Adicionais=NÃO | "
                            "Aprovação=NÃO"
                        )

                        continue

                    # A análise também tenta restaurar a tela em seu finally,
                    # mas repetimos a confirmação de forma idempotente antes
                    # de qualquer clique em Corrigir Minuta.
                    try:
                        restauracao_requerimento = (
                            restaurar_tela_requerimento_apos_comparacao(
                                driver=driver,
                                wait=wait,
                                aba_original_sch=aba_original_sch,
                                info_abertura={},
                            )
                        )
                    except Exception as e:
                        restauracao_requerimento = {
                            "restaurado": False,
                            "erro": str(e),
                        }

                    retorno_estudo["restauracao_tela_requerimento"] = (
                        restauracao_requerimento
                    )

                    # ======================================================
                    # CARACTERÍSTICAS TÉCNICAS SECUNDÁRIAS — RETORNO
                    #
                    # A Justificativa/Tipos RE já foram lidos e o Comparar
                    # Versões já foi concluído antes desta alteração.
                    #
                    # Reutiliza a mesma lógica segura da fila Em Análise, mas
                    # altera SOMENTE o campo:
                    # "Título/Descrição para Características Técnicas
                    # Secundárias".
                    # ======================================================
                    dados_pdf_secundarias_retorno = {}

                    if restauracao_requerimento.get("restaurado") and pdf_cct:
                        try:
                            dados_pdf_secundarias_retorno = (
                                parsear_certificado_pdf(pdf_cct) or {}
                            )

                            caracteristicas_sec_retorno = (
                                inferir_caracteristicas_secundarias(
                                    dados_pdf_secundarias_retorno
                                )
                            )

                            texto_sec_retorno = (
                                gerar_texto_caracteristicas_secundarias(
                                    dados_pdf_secundarias_retorno
                                )
                            )

                            dados_pdf_secundarias_retorno[
                                "caracteristicas_secundarias"
                            ] = caracteristicas_sec_retorno
                            dados_pdf_secundarias_retorno[
                                "titulo_caracteristicas_secundarias"
                            ] = caracteristicas_sec_retorno.get(
                                "titulo",
                                "",
                            )
                            dados_pdf_secundarias_retorno[
                                "texto_caracteristicas_secundarias"
                            ] = texto_sec_retorno
                            dados_pdf_secundarias_retorno[
                                "tipo_produto"
                            ] = req.get("tipo_produto", "")

                        except Exception as e:
                            print(
                                "[SCH][RETORNO][WARN] Não foi possível "
                                "preparar o CCT para Características "
                                f"Secundárias: {e}"
                            )
                            dados_pdf_secundarias_retorno = {}

                    if restauracao_requerimento.get("restaurado"):
                        resultado_secundarias_retorno = (
                            preencher_caracteristicas_secundarias_retorno(
                                driver=driver,
                                wait=wait,
                                req=req,
                                dados_pdf=dados_pdf_secundarias_retorno,
                            )
                        )
                    else:
                        resultado_secundarias_retorno = {
                            "executado": False,
                            "campo_encontrado": False,
                            "preenchido": False,
                            "corrigido": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                            "status": "nao_executada_tela_nao_restaurada",
                            "motivo": (
                                "Tela original do requerimento não foi "
                                "restaurada após Comparar Versões."
                            ),
                            "fila": "Retorno Para Estudo",
                        }

                    retorno_estudo[
                        "caracteristicas_secundarias"
                    ] = resultado_secundarias_retorno

                    resumo[
                        "caracteristicas_secundarias_retorno"
                    ] = resultado_secundarias_retorno

                    if resultado_secundarias_retorno.get("status") in {
                        "erro",
                        "erro_confirmacao",
                        "revisar_sem_titulo_seguro",
                    }:
                        retorno_estudo.setdefault("alertas", []).append(
                            "Características Secundárias: "
                            + str(
                                resultado_secundarias_retorno.get(
                                    "motivo",
                                    resultado_secundarias_retorno.get(
                                        "status",
                                        "",
                                    ),
                                )
                            )
                        )

                    tipo_produto = req.get("tipo_produto", "")
                    limpeza_exigida = (
                        tipo_produto_deve_limpar_especificacoes_complementares(
                            tipo_produto
                        )
                    )

                    # O tratamento em Corrigir Minuta é uma etapa técnica
                    # independente da decisão final de aprovação.
                    #
                    # Se o tipo de produto está na lista configurada, o
                    # tratamento deve ser executado após uma comparação válida
                    # e após restaurar a tela do requerimento, mesmo que o
                    # resultado do Comparar Versões seja "revisão manual".
                    #
                    # IMPORTANTE: isso NÃO torna o requerimento apto. A decisão
                    # de aprovação continua obedecendo ao resultado original da
                    # comparação e aos demais bloqueios.
                    apto_antes_pos_processamento = bool(
                        retorno_estudo.get("deve_enviar_para_aprovacao")
                    )

                    minuta_deve_executar = bool(
                        comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                        and limpeza_exigida
                    )

                    print(
                        "[SCH][RETORNO][MINUTA] "
                        f"Tipo produto='{tipo_produto}' | "
                        f"tratamento configurado={'SIM' if limpeza_exigida else 'NÃO'} | "
                        f"comparação apta={'SIM' if apto_antes_pos_processamento else 'NÃO'} | "
                        f"executar Corrigir Minuta={'SIM' if minuta_deve_executar else 'NÃO'}"
                    )

                    if minuta_deve_executar:
                        resultado_minuta = (
                            limpar_especificacoes_complementares_minuta_se_necessario(
                                driver=driver,
                                wait=wait,
                                req=req,
                                aba_original_sch=aba_original_sch,
                                texto_especificacoes_versao_nova=(
                                    retorno_estudo.get(
                                        "especificacoes_complementares_versao_nova",
                                        "",
                                    )
                                    or retorno_estudo.get("captura", {}).get(
                                        "especificacoes_complementares_versao_nova",
                                        "",
                                    )
                                ),
                            )
                        )

                    elif not limpeza_exigida:
                        resultado_minuta = {
                            "aplicavel": False,
                            "tratado": False,
                            "limpo": False,
                            "substituido": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                            "retornou_para_requerimento": bool(
                                restauracao_requerimento.get("restaurado")
                            ),
                            "status": "nao_aplicavel_tipo_produto",
                            "mensagem": (
                                "Corrigir Minuta não foi executado porque o "
                                "tipo de produto não está na lista de tratamento "
                                "automático de Especificações Complementares."
                            ),
                        }

                    else:
                        resultado_minuta = {
                            "aplicavel": bool(limpeza_exigida),
                            "tratado": False,
                            "limpo": False,
                            "substituido": False,
                            "salvo": False,
                            "confirmado_apos_salvar": False,
                            "retornou_para_requerimento": False,
                            "status": "erro_restauracao_apos_comparacao",
                            "mensagem": (
                                "Corrigir Minuta não foi executado porque "
                                "não foi possível restaurar a tela original "
                                "do requerimento após Comparar Versões."
                            ),
                            "erro": restauracao_requerimento.get("erro", ""),
                        }

                    tratamento_aplicavel = bool(
                        resultado_minuta.get("aplicavel", limpeza_exigida)
                    )
                    tratamento_confirmado = bool(
                        resultado_minuta.get("tratado")
                        and resultado_minuta.get("salvo")
                        and resultado_minuta.get(
                            "confirmado_apos_salvar"
                        )
                    )

                    resultado_minuta["modo"] = (
                        "tratamento_especificacoes_complementares_"
                        "retorno_para_estudo"
                    )
                    resultado_minuta["tratamento_exigido"] = bool(
                        limpeza_exigida
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                    )
                    resultado_minuta["tratamento_confirmado"] = bool(
                        tratamento_confirmado
                    )

                    resultado_minuta["limpeza_exigida"] = bool(
                        limpeza_exigida
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                    )
                    resultado_minuta["limpeza_confirmada"] = bool(
                        tratamento_confirmado
                    )

                    retorno_estudo["corrigir_minuta"] = resultado_minuta
                    retorno_estudo["tratamento_minuta_exigido"] = bool(
                        limpeza_exigida
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                    )
                    retorno_estudo["tratamento_minuta_confirmado"] = bool(
                        tratamento_confirmado
                    )
                    retorno_estudo["limpeza_minuta_exigida"] = bool(
                        limpeza_exigida
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                    )
                    retorno_estudo["limpeza_minuta_confirmada"] = bool(
                        tratamento_confirmado
                    )

                    # Sem retorno confirmado à tela original, nenhum clique
                    # posterior (minuta ou aprovação) é seguro.
                    if not restauracao_requerimento.get("restaurado"):
                        retorno_estudo["pode_enviar_para_aprovacao"] = False
                        retorno_estudo["deve_enviar_para_aprovacao"] = False
                        retorno_estudo["acao_recomendada"] = (
                            "Não enviar para aprovação / Restaurar tela do requerimento"
                        )
                        retorno_estudo["status_comparacao"] = (
                            "bloqueado_por_falha_ao_restaurar_requerimento"
                        )
                        retorno_estudo.setdefault("alertas", []).append(
                            "A aprovação automática foi bloqueada porque "
                            "a tela original do requerimento não foi confirmada "
                            "após Comparar Versões."
                        )

                    # Se o tipo exige limpeza, a aprovação automática fica
                    # bloqueada até que apagar + salvar + confirmar tenha sucesso.
                    if (
                        limpeza_exigida
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                        and not tratamento_confirmado
                    ):
                        retorno_estudo.setdefault("alertas", []).append(
                            "Não foi possível confirmar o tratamento de "
                            "Especificações Complementares e o salvamento "
                            "em Corrigir Minuta."
                        )

                        if apto_antes_pos_processamento:
                            retorno_estudo["pode_enviar_para_aprovacao"] = False
                            retorno_estudo["deve_enviar_para_aprovacao"] = False
                            retorno_estudo["acao_recomendada"] = (
                                "Não enviar para aprovação / Revisar tratamento da minuta"
                            )
                            retorno_estudo["status_comparacao"] = (
                                "bloqueado_por_falha_no_tratamento_da_minuta"
                            )

                    # ======================================================
                    # REGISTRO DA ANÁLISE EM ACOMPANHAR PROCESSO
                    #
                    # A frase deve ser registrada em TODO requerimento de
                    # Retorno Para Estudo efetivamente analisado pela automação,
                    # independentemente de:
                    # - estar APTO ou NÃO APTO;
                    # - seguir para revisão manual;
                    # - a aprovação automática estar habilitada ou desabilitada.
                    #
                    # Não recebe marcação:
                    # - requerimento ignorado antes da análise;
                    # - fora do escopo;
                    # - análise sem conclusão segura do Comparar Versões;
                    # - tela original não restaurada.
                    #
                    # A falha na marcação só bloqueia o envio quando o
                    # requerimento estiver, de fato, no caminho de aprovação
                    # automática.
                    # ======================================================
                    marcacao_deve_registrar = bool(
                        comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                    )

                    marcacao_obrigatoria_para_envio = bool(
                        executar_envio_retorno_para_estudo
                        and comparacao_concluida
                        and restauracao_requerimento.get("restaurado")
                        and retorno_estudo.get("deve_enviar_para_aprovacao")
                    )

                    if marcacao_deve_registrar:
                        print(
                            "[SCH][RETORNO] Registrando avaliação da automação "
                            "em Acompanhar Processo para requerimento analisado..."
                        )

                        marcacao_automacao = (
                            registrar_avaliacao_automacao_informacoes_adicionais_retorno(
                                driver=driver,
                                wait=wait,
                                texto_original_analisado=(
                                    retorno_estudo.get(
                                        "informacoes_adicionais_retorno",
                                        {},
                                    ).get("texto", "")
                                ),
                                analise_tipos_re=retorno_estudo.get(
                                    "analise_numeros_informacoes_adicionais",
                                    {},
                                ),
                            )
                        )
                    else:
                        if not comparacao_concluida:
                            motivo_marcacao = (
                                "análise não concluída com segurança no Comparar Versões"
                            )
                            status_marcacao = "nao_executada_analise_incompleta"
                        elif not restauracao_requerimento.get("restaurado"):
                            motivo_marcacao = (
                                "tela original do requerimento não restaurada"
                            )
                            status_marcacao = "nao_executada_tela_nao_restaurada"
                        else:
                            motivo_marcacao = (
                                "requerimento não chegou a uma análise concluída segura"
                            )
                            status_marcacao = "nao_executada_sem_analise_concluida"

                        marcacao_automacao = {
                            "exigida": False,
                            "preenchida": False,
                            "salva": False,
                            "confirmada_apos_salvar": False,
                            "status": status_marcacao,
                            "motivo": motivo_marcacao,
                        }

                        print(
                            "[SCH][RETORNO] Acompanhar Processo: "
                            f"marcação NÃO EXECUTADA — {motivo_marcacao}."
                        )

                    retorno_estudo[
                        "marcacao_automacao_informacoes_adicionais"
                    ] = marcacao_automacao

                    marcacao_confirmada = bool(
                        marcacao_deve_registrar
                        and marcacao_automacao.get(
                            "acompanhar_processo_marcado"
                        )
                        and marcacao_automacao.get("preenchida")
                        and marcacao_automacao.get("salva")
                        and marcacao_automacao.get(
                            "confirmada_apos_salvar"
                        )
                    )

                    # Novas chaves com o nome correto do campo.
                    retorno_estudo[
                        "registro_automacao_informacoes_adicionais_executado"
                    ] = bool(marcacao_deve_registrar)

                    retorno_estudo[
                        "registro_automacao_informacoes_adicionais_confirmado"
                    ] = bool(marcacao_confirmada)

                    # Mantém aliases antigos para não quebrar relatórios que ainda
                    # leem as chaves históricas de Acompanhar Processo.
                    retorno_estudo[
                        "registro_automacao_acompanhar_processo_executado"
                    ] = bool(marcacao_deve_registrar)

                    retorno_estudo[
                        "registro_automacao_acompanhar_processo_confirmado"
                    ] = bool(marcacao_confirmada)

                    if (
                        marcacao_deve_registrar
                        and not marcacao_confirmada
                    ):
                        retorno_estudo.setdefault("alertas", []).append(
                            "O requerimento foi analisado pela automação, mas não "
                            "foi possível salvar e confirmar a frase de registro "
                            "em Acompanhar Processo."
                        )

                    if (
                        marcacao_obrigatoria_para_envio
                        and not marcacao_confirmada
                    ):
                        retorno_estudo["pode_enviar_para_aprovacao"] = False
                        retorno_estudo["deve_enviar_para_aprovacao"] = False
                        retorno_estudo["acao_recomendada"] = (
                            "Não enviar para aprovação / Revisar registro em "
                            "Acompanhar Processo"
                        )
                        retorno_estudo["status_comparacao"] = (
                            "bloqueado_por_falha_na_marcacao_da_automacao"
                        )
                        retorno_estudo.setdefault("alertas", []).append(
                            "A aprovação automática foi bloqueada porque a frase "
                            "de registro da análise por automação não foi salva e "
                            "confirmada em Acompanhar Processo."
                        )

                    # A análise já encerrou a tela Comparar Versões. Agora o envio
                    # pode ocorrer somente se a comparação estiver apta, o tratamento
                    # da minuta estiver confirmado quando exigido e a marcação da
                    # automação tiver sido registrada antes da aprovação.
                    retorno_estudo["envio_para_aprovacao"] = (
                        enviar_retorno_para_aprovacao_se_apto(
                            driver=driver,
                            wait=wait,
                            resultado=retorno_estudo,
                            info_abertura={},
                            executar_envio=executar_envio_retorno_para_estudo,
                        )
                    )

                    resumo["retorno_para_estudo"] = retorno_estudo
                    resumo["restauracao_apos_comparacao"] = (
                        restauracao_requerimento
                    )
                    resumo["resultado_minuta"] = resultado_minuta
                    resumo["marcacao_automacao_informacoes_adicionais"] = (
                        retorno_estudo.get(
                            "marcacao_automacao_informacoes_adicionais",
                            {},
                        )
                    )
                    resumo["sar_minuta"] = {
                        "status": "nao_aplicavel_fila_retorno_para_estudo",
                        "mensagem": (
                            "A fila Retorno Para Estudo não executa julgamento de SAR. "
                            "O tratamento da minuta nesta fila pode limpar ou substituir "
                            "Especificações Complementares, conforme IPv6/E.I.R.P. e o "
                            "tipo de produto configurado."
                        ),
                        "preencher_frase": False,
                        "preenchido_automaticamente": False,
                        "salvo": False,
                        "confirmado_apos_salvar": False,
                    }
                    resumo["minuta"] = {
                        "preenchida": bool(
                            resultado_minuta.get("substituido")
                        ),
                        "campo_limpo": bool(
                            resultado_minuta.get("limpo")
                        ),
                        "campo_substituido": bool(
                            resultado_minuta.get("substituido")
                        ),
                        "tratado": bool(
                            resultado_minuta.get("tratado")
                        ),
                        "alterada": bool(
                            resultado_minuta.get("tratado")
                        ),
                        "salvo": bool(resultado_minuta.get("salvo")),
                        "confirmado_apos_salvar": bool(
                            resultado_minuta.get(
                                "confirmado_apos_salvar"
                            )
                        ),
                        "status": resultado_minuta.get("status", ""),
                        "mensagem": resultado_minuta.get(
                            "mensagem",
                            resultado_minuta.get("motivo", ""),
                        ),
                        "frase": resultado_minuta.get(
                            "conteudo_final_esperado",
                            "",
                        ),
                        "acao_minuta": resultado_minuta.get(
                            "acao_minuta",
                            "",
                        ),
                        "palavras_identificadas": resultado_minuta.get(
                            "palavras_identificadas",
                            [],
                        ),
                        "conteudo_anterior": resultado_minuta.get(
                            "conteudo_anterior",
                            "",
                        ),
                        "texto_especificacoes_versao_nova": resultado_minuta.get(
                            "texto_especificacoes_versao_nova",
                            "",
                        ),
                        "fontes_analisadas": resultado_minuta.get(
                            "fontes_analisadas",
                            [],
                        ),
                        "texto_analisado_palavras_chave": resultado_minuta.get(
                            "texto_analisado_palavras_chave",
                            "",
                        ),
                        "conteudo_final_confirmado": resultado_minuta.get(
                            "conteudo_final_confirmado",
                            "",
                        ),
                        "modo": (
                            "tratamento_especificacoes_complementares_"
                            "retorno_para_estudo"
                        ),
                        "tipo_produto": tipo_produto,
                    }
                    resumo["preenchimento_sch"]["minuta"] = bool(
                        tratamento_confirmado
                    )
                    resumo["status"] = "sucesso"
                    resumo["fim"] = datetime.now().isoformat()

                    _salvar_controle_downloads(
                        pasta_req=pasta_req,
                        numero=numero,
                        qtd_downloads=qtd_downloads,
                        categorias_anexos_ativas=categorias_anexos_ativas,
                        anexos_baixados=resumo["anexos_baixados"],
                        escopo_processamento=resumo["escopo_processamento"],
                        fila_sch=fila_sch,
                        retorno_para_estudo=retorno_estudo,
                    )

                    print(
                        "[SCH][RETORNO] Requerimento finalizado. "
                        f"Resultado={retorno_estudo.get('status_comparacao')} | "
                        f"Comparar Versões={'SIM' if retorno_estudo.get('comparacao_executada') else 'NÃO'} | "
                        f"Características Secundárias="
                        f"{resultado_secundarias_retorno.get('status', 'não executada')} | "
                        f"Tratamento da minuta={'SIM' if tratamento_confirmado else 'NÃO'} | "
                        f"Registro em Informações Adicionais="
                        f"{'SIM' if marcacao_automacao.get('confirmada_apos_salvar') else 'NÃO'} | "
                        f"Ação={retorno_estudo.get('acao_recomendada')}"
                    )

                    continue

                if pdf_cct:
                    print(f"[SCH] PDF CCT localizado: {pdf_cct}")
                    dados_pdf = parsear_certificado_pdf(pdf_cct)
                    dados_pdf = dados_pdf or {}
                else:
                    print("[SCH][WARN] Nenhum PDF CCT localizado na pasta do requerimento.")
                    dados_pdf = {}

                dados_pdf["nome_comercial_sch"] = req.get("nome_comercial", "")
                dados_pdf["modelo_sch_dados_gerais"] = req.get("modelo_sch_dados_gerais", "")

                if dados_certificado_sch:
                    dados_pdf["data_emissao_cct"] = dados_pdf.get("data_emissao", "")
                    dados_pdf["data_validade_cct"] = dados_pdf.get("data_validade", "")

                    dados_pdf["data_emissao_sch"] = dados_certificado_sch.get("data_certificado", "")
                    dados_pdf["data_validade_sch"] = dados_certificado_sch.get("data_validade", "")
                    dados_pdf["numero_certificado_sch_dados_gerais"] = dados_certificado_sch.get("numero_certificado", "")

                    if dados_certificado_sch.get("data_certificado"):
                        dados_pdf["data_emissao"] = dados_certificado_sch.get("data_certificado")

                    if dados_certificado_sch.get("data_validade"):
                        dados_pdf["data_validade"] = dados_certificado_sch.get("data_validade")

                    dados_pdf["datas_origem"] = "SCH - Dados Gerais - Dados do Certificado"

                    print(
                        "[SCH] Datas para validação serão usadas do SCH: "
                        f"emissão={dados_pdf.get('data_emissao', '')} | "
                        f"validade={dados_pdf.get('data_validade', '')}"
                    )

                try:
                    comparacao_datas = comparar_datas_certificado_sch_x_cct(
                        dados_certificado_sch=dados_certificado_sch,
                        dados_pdf=dados_pdf,
                    )
                    resumo["comparacao_datas_sch_cct"] = comparacao_datas
                    dados_pdf["comparacao_datas_sch_cct"] = comparacao_datas

                    if comparacao_datas.get("status_geral") == "divergente":
                        print(
                            "[SCH][WARN] Divergência nas datas entre SCH e CCT: "
                            "Revisão manual recomendada."
                        )
                    elif comparacao_datas.get("status_geral") == "parcial":
                        print(
                            "[SCH][WARN] Comparação de datas SCH x CCT parcial: "
                            f"{comparacao_datas.get('mensagem')}"
                        )
                    else:
                        print("[SCH] Datas SCH x CCT conferidas com sucesso.")
                except Exception as e:
                    print(f"[SCH][WARN] Falha ao comparar datas SCH x CCT: {e}")
                    resumo["comparacao_datas_sch_cct"] = {
                        "status_geral": "erro",
                        "mensagem": str(e),
                        "comparacoes": [],
                        "divergencias": [],
                    }

                try:
                    caracteristicas_sec = inferir_caracteristicas_secundarias(dados_pdf)

                    texto_caracteristicas_secundarias = gerar_texto_caracteristicas_secundarias(
                        dados_pdf
                    )

                    dados_pdf["caracteristicas_secundarias"] = caracteristicas_sec
                    dados_pdf["titulo_caracteristicas_secundarias"] = (
                        caracteristicas_sec.get("titulo", "")
                    )
                    dados_pdf["texto_caracteristicas_secundarias"] = (
                        texto_caracteristicas_secundarias
                    )

                    resumo["caracteristicas_secundarias"] = caracteristicas_sec
                    resumo["texto_caracteristicas_secundarias"] = (
                        texto_caracteristicas_secundarias
                    )

                    print(
                        "[SCH] Categoria secundária detectada:",
                        caracteristicas_sec.get("categoria") or "não identificada",
                    )
                    print(
                        "[SCH] Título de características secundárias:",
                        caracteristicas_sec.get("titulo") or "não aplicável",
                    )
                    print(
                        "[SCH] Características secundárias detectadas:",
                        caracteristicas_sec.get("caracteristicas", {}),
                    )
                    print(
                        "[SCH] Texto de características secundárias:",
                        (texto_caracteristicas_secundarias or "")[:500],
                    )

                except Exception as e:
                    print(f"[SCH][WARN] Falha ao inferir características secundárias: {e}")

                    resumo["caracteristicas_secundarias"] = {
                        "categoria": "",
                        "titulo": "",
                        "caracteristicas": {},
                        "preencher_titulo": False,
                        "erro": str(e),
                    }
                    resumo["texto_caracteristicas_secundarias"] = ""

                    dados_pdf["caracteristicas_secundarias"] = resumo["caracteristicas_secundarias"]
                    dados_pdf["titulo_caracteristicas_secundarias"] = ""
                    dados_pdf["texto_caracteristicas_secundarias"] = ""

                resumo["dados_pdf"] = dados_pdf

                validade_cct = avaliar_validade_cct(dados_pdf)
                resumo["validade_cct"] = validade_cct

                if validade_cct.get("status") == "alerta":
                    print(f"[SCH][WARN] CCT: {validade_cct.get('mensagem')}")
                else:
                    print(f"[SCH] CCT: {validade_cct.get('mensagem')}")

                try:
                    req["tabela_tecnica_sch"] = extrair_tabela_tecnica_sch(driver, wait)
                    resumo["tabela_tecnica_sch"] = req.get("tabela_tecnica_sch", {})
                except Exception as e:
                    print(f"[SCH][WARN] Não foi possível extrair a tabela técnica do SCH: {e}")
                    req["tabela_tecnica_sch"] = {"cabecalho": [], "linhas": []}
                    resumo["tabela_tecnica_sch"] = req["tabela_tecnica_sch"]

                if dados_pdf:
                    conferencia = comparar_dados_sch_x_cct(req, dados_pdf)
                    avisar_resultado_conferencia_sch_cct(conferencia)
                    resumo["conferencia_sch_cct"] = conferencia

                    if conferencia.get("status_geral") == "divergente":
                        print(
                            f"[SCH][WARN] O requerimento {numero} possui divergências entre SCH e CCT. "
                            "Revisão manual recomendada."
                        )
                else:
                    resumo["conferencia_sch_cct"] = {
                        "status_geral": "sem_cct",
                        "comparacoes": [],
                        "divergencias": [],
                        "campos_ausentes": [],
                        "comparacao_tabela_tecnica": {
                            "status": "sem_tabela",
                            "motivo": "cct_nao_localizado_ou_nao_parseado",
                            "divergencias": [],
                        },
                        "requerimento": numero,
                        "motivo": "cct_nao_localizado_ou_nao_parseado",
                    }
                    print(
                        f"[SCH][WARN] Conferência SCH x CCT não executada no requerimento {numero} "
                        "porque não houve dados válidos do CCT."
                    )

                if preencher_caracteristicas:
                    analise_rapida = preencher_caracteristicas_tecnicas_com_analise(
                        driver=driver,
                        wait=wait,
                        req=req,
                        anexos_baixados=resumo["anexos_baixados"],
                        dados_pdf=dados_pdf,
                    )
                else:
                    analise_rapida = {
                        "classificacao": "",
                        "texto": "",
                        "motivos": [],
                        "origem": "desabilitado_pelo_usuario",
                    }

                resumo["analise_rapida"] = analise_rapida
                resumo["observacao_caracteristicas"] = analise_rapida.get("texto", "")

                # FILA EM ANÁLISE:
                # Corrigir Minuta é tratado exclusivamente pela análise de SAR
                # extraída do CCT. A lista de limpeza por tipo de produto NÃO é
                # consultada nesta fila.
                if preencher_minuta:
                    sar_minuta = preencher_minuta_sar_se_necessario(
                        driver=driver,
                        wait=wait,
                        dados_pdf=dados_pdf,
                    )
                else:
                    sar_minuta = {
                        "status": "desabilitado_pelo_usuario",
                        "mensagem": (
                            "Análise/preenchimento de SAR em Corrigir Minuta "
                            "desabilitado pelo usuário."
                        ),
                        "frase": "",
                        "preencher_frase": False,
                        "preenchido_automaticamente": False,
                        "salvo": False,
                        "confirmado_apos_salvar": False,
                    }

                sar_minuta["modo"] = "analise_sar_cct_em_analise"
                resumo["sar_minuta"] = sar_minuta
                resumo["resultado_minuta"] = sar_minuta
                resumo["minuta"] = {
                    "preenchida": bool(
                        sar_minuta.get("preenchido_automaticamente")
                    ),
                    "campo_limpo": False,
                    "alterada": bool(
                        sar_minuta.get("preenchido_automaticamente")
                    ),
                    "salvo": bool(sar_minuta.get("salvo")),
                    "confirmado_apos_salvar": bool(
                        sar_minuta.get("confirmado_apos_salvar")
                    ),
                    "status": sar_minuta.get("status", ""),
                    "mensagem": sar_minuta.get("mensagem", ""),
                    "frase": sar_minuta.get("frase", ""),
                    "modo": "analise_sar_cct_em_analise",
                }

                resumo["preenchimento_sch"]["minuta"] = bool(
                    sar_minuta.get("preenchido_automaticamente")
                )

                if preencher_informacoes_adicionais:
                    info_adicionais = preencher_informacoes_adicionais_com_analise(
                        driver=driver,
                        wait=wait,
                        req=req,
                        anexos_baixados=resumo["anexos_baixados"],
                        dados_pdf=dados_pdf,
                        analise_rapida=analise_rapida,
                    )
                else:
                    info_adicionais = {
                        "texto": "",
                        "classificacao": analise_rapida.get("classificacao", ""),
                        "motivos": analise_rapida.get("motivos", []),
                        "preenchido_automaticamente": False,
                        "origem": "desabilitado_pelo_usuario",
                    }

                resumo["informacoes_adicionais"] = info_adicionais

                qtd_downloads = contar_arquivos_requerimento(pasta_req)
                resumo["downloads_realizados"] = qtd_downloads

                _salvar_controle_downloads(
                    pasta_req=pasta_req,
                    numero=numero,
                    qtd_downloads=qtd_downloads,
                    categorias_anexos_ativas=categorias_anexos_ativas,
                    anexos_baixados=resumo["anexos_baixados"],
                    escopo_processamento=resumo["escopo_processamento"],
                    fila_sch=fila_sch,
                )

                analise_documental = analisar_requerimento(
                    pasta_req=pasta_req,
                    req=req,
                    resumo=resumo,
                )
                resumo["analise_documental"] = analise_documental
                salvar_json(pasta_req / "analise_requerimento.json", analise_documental)

                print(f"[SCH] {qtd_downloads} arquivo(s) salvos para o requerimento {numero}")

                resumo["status"] = "sucesso"
                resumo["fim"] = datetime.now().isoformat()
                print(f"[SCH] Requerimento {numero} finalizado com sucesso.")

            except KeyboardInterrupt:
                interrompido_pelo_usuario = True
                resumo["status"] = "interrompido"
                resumo["fim"] = datetime.now().isoformat()
                resumo["erro"] = {
                    "tipo": "KeyboardInterrupt",
                    "mensagem": "Execução interrompida pelo usuário.",
                    "repr": "KeyboardInterrupt()",
                }

                print(
                    f"[SCH][INTERRUPCAO] Execução interrompida durante o requerimento {numero}. "
                    "Salvando relatório parcial antes de encerrar..."
                )

                raise

            except Exception as e:
                resumo["status"] = "erro"
                resumo["fim"] = datetime.now().isoformat()
                resumo["erro"] = {
                    "tipo": type(e).__name__,
                    "mensagem": str(e),
                    "repr": repr(e),
                }

                print(f"[SCH][ERRO] Falha no requerimento {numero}: {type(e).__name__}: {repr(e)}")

            finally:
                caminho_json = pasta_req / "resumo.json"
                salvar_json(caminho_json, resumo)
                relatorio_execucao.append(resumo)

                _gerar_relatorios_parciais_execucao(
                    pasta_base=pasta_base,
                    relatorio_execucao=relatorio_execucao,
                    inicio_execucao=inicio_execucao,
                    fila_sch=fila_sch,
                    requerimentos=requerimentos,
                    requerimentos_processaveis=requerimentos_processaveis,
                    requerimentos_ignorados=requerimentos_ignorados,
                    ignorados_resumidos=ignorados_resumidos,
                    versao_script=VERSAO_SCRIPT,
                    categorias_anexos_ativas=categorias_anexos_ativas,
                    processar_apenas_rr_efetivo=processar_apenas_rr_efetivo,
                    status_execucao=(
                        "interrompida_pelo_usuario"
                        if interrompido_pelo_usuario
                        else "parcial_em_andamento"
                    ),
                    imprimir=True,
                )

                if not interrompido_pelo_usuario:
                    try:
                        voltar_para_fila(driver, wait, nome_fila=fila_sch)
                    except Exception as e:
                        print(f"[SCH][WARN] Não foi possível voltar normalmente: {e}")

        _gerar_relatorios_parciais_execucao(
            pasta_base=pasta_base,
            relatorio_execucao=relatorio_execucao,
            inicio_execucao=inicio_execucao,
            fila_sch=fila_sch,
            requerimentos=requerimentos,
            requerimentos_processaveis=requerimentos_processaveis,
            requerimentos_ignorados=requerimentos_ignorados,
            ignorados_resumidos=ignorados_resumidos,
            versao_script=VERSAO_SCRIPT,
            categorias_anexos_ativas=categorias_anexos_ativas,
            processar_apenas_rr_efetivo=processar_apenas_rr_efetivo,
            status_execucao="finalizado",
            imprimir=True,
        )

    except KeyboardInterrupt:
        print(
            "\n[SCH][INTERRUPCAO] Execução interrompida pelo usuário. "
            "Gerando relatório parcial dos requerimentos já analisados..."
        )

        _gerar_relatorios_parciais_execucao(
            pasta_base=pasta_base,
            relatorio_execucao=relatorio_execucao,
            inicio_execucao=inicio_execucao,
            fila_sch=fila_sch,
            requerimentos=requerimentos,
            requerimentos_processaveis=requerimentos_processaveis,
            requerimentos_ignorados=requerimentos_ignorados,
            ignorados_resumidos=ignorados_resumidos,
            versao_script=VERSAO_SCRIPT,
            categorias_anexos_ativas=categorias_anexos_ativas,
            processar_apenas_rr_efetivo=processar_apenas_rr_efetivo,
            status_execucao="interrompida_pelo_usuario",
            imprimir=True,
        )

        raise

    finally:
        if fechar_navegador_ao_final:
            print("[SCH] Encerrando navegador.")
            driver.quit()
        else:
            print("[SCH] Navegador mantido aberto ao final do fluxo.")
