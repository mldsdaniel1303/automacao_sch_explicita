from pathlib import Path
from datetime import datetime
import builtins
import re
import unicodedata

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
    preencher_informacoes_adicionais_com_analise,
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
from caracteristicas_secundarias import (
    inferir_caracteristicas_secundarias,
    gerar_texto_caracteristicas_secundarias,
)

VERSAO_SCRIPT = "0.7.9"


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
            "Comparar a versão anterior e a nova versão do requerimento, "
            "identificando alterações em Dados Técnicos, Especificações Complementares "
            "e na relação de documentos anexados."
        ),
        "regra_decisao": [
            "Sem alteração técnica relevante e somente documentos adicionados: Enviar para aprovação.",
            "Alteração em Dados Técnicos, Especificações Complementares, documentos removidos ou caso inconclusivo: Revisar manualmente.",
        ],
    }


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
                    "motivo": req.get("motivo", "fora_escopo_radiacao_restrita"),
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

    if relatorio_execucao:
        try:
            caminho_req_report = gerar_req_report(
                pasta_saida=pasta_base,
                resultados=relatorio_execucao,
                versao_script=versao_script,
                inicio_execucao=inicio_execucao,
                fim_execucao=fim_execucao,
            )
        except Exception as e:
            print(
                "[SCH][WARN] Não foi possível atualizar o req_report parcial agora: "
                f"{type(e).__name__}: {e}"
            )
    else:
        print(
            "[SCH][WARN] Nenhum requerimento processado ainda; "
            "relatório HTML parcial não foi gerado."
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
):
    pasta_base = Path(pasta_base).resolve()
    pasta_base.mkdir(parents=True, exist_ok=True)

    if not fila_sch:
        fila_sch = perguntar_fila_sch()

    fila_retorno = _eh_fila_retorno_para_estudo(fila_sch)
    print(f"[SCH] Fila selecionada para processamento: {fila_sch}")

    regras = carregar_regras()
    regras["pausar_antes_anexos"] = pausar_antes_anexos

    categorias_anexos_ativas = list(
        categorias_anexos
        or regras.get("categorias_anexos", [])
        or []
    )

    if categorias_anexos_ativas:
        regras["categorias_anexos"] = categorias_anexos_ativas

    if limite_requerimentos:
        regras["limite_requerimentos"] = int(limite_requerimentos)

    # Em Retorno Para Estudo a análise deve comparar versões do requerimento,
    # então não faz sentido bloquear o processamento por tipo de produto.
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
                print(
                    "[SCH][WARN] O requerimento específico não foi "
                    f"encontrado na fila: {requerimento_especifico}"
                )

            requerimentos = requerimentos_encontrados

        elif limite_requerimentos:
            requerimentos = requerimentos[
                : int(limite_requerimentos)
            ]

        requerimentos_processaveis, requerimentos_ignorados = separar_requerimentos_por_escopo(
            requerimentos,
            processar_apenas_rr=processar_apenas_rr_efetivo,
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
            f"{', '.join(categorias_anexos_ativas) if categorias_anexos_ativas else 'padrão do sistema'}"
        )

        caminho_manifesto = salvar_manifesto_requerimentos(
            pasta_base,
            mapeados,
            ignorados=ignorados_resumidos,
        )
        print(f"[SCH] Manifesto salvo em: {caminho_manifesto}")

        if not requerimentos_processaveis:
            print("[SCH][WARN] Nenhum requerimento selecionado para processamento.")
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
                "retorno_para_estudo": {},
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
                "preenchimento_sch": {
                    "minuta": False,
                    "minuta_habilitada": True if fila_retorno else bool(preencher_minuta),
                    "modo_minuta": (
                        "limpeza_especificacoes_complementares"
                        if fila_retorno
                        else "analise_sar_cct"
                    ),
                    "caracteristicas": preencher_caracteristicas and not fila_retorno,
                    "informacoes_adicionais": preencher_informacoes_adicionais and not fila_retorno,
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

                clicar_aba_anexos(driver, wait)

                anexos_baixados = baixar_todos_os_anexos_de_todas_as_categorias(
                    driver=driver,
                    wait=wait,
                    req=req,
                    pasta_saida=pasta_req,
                    pasta_download=pasta_download,
                    regras=regras,
                )
                resumo["anexos_baixados"] = anexos_baixados or []

                pdf_cct = localizar_pdf_cct_do_requerimento(pasta_req, regras)
                resumo["pdf_cct"] = str(pdf_cct) if pdf_cct else ""

                # ==========================================================
                # FLUXO ESPECIAL: Retorno Para Estudo
                # Baixa anexos, abre Comparar Versões, compara versão antiga x nova
                # e gera relatório próprio de retorno. Não executa a análise completa
                # SCH x CCT da fila Em Análise.
                # ==========================================================
                if fila_retorno:
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

                    tipo_produto = req.get("tipo_produto", "")
                    limpeza_exigida = (
                        tipo_produto_deve_limpar_especificacoes_complementares(
                            tipo_produto
                        )
                    )

                    # O tipo do produto NÃO filtra a análise. Ele serve apenas
                    # para decidir se este caminho deve ser executado.
                    if restauracao_requerimento.get("restaurado"):
                        resultado_minuta = (
                            limpar_especificacoes_complementares_minuta_se_necessario(
                                driver=driver,
                                wait=wait,
                                req=req,
                                aba_original_sch=aba_original_sch,
                            )
                        )
                    else:
                        resultado_minuta = {
                            "aplicavel": bool(limpeza_exigida),
                            "limpo": False,
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

                    limpeza_aplicavel = bool(
                        resultado_minuta.get("aplicavel", limpeza_exigida)
                    )
                    limpeza_confirmada = bool(
                        resultado_minuta.get("limpo")
                        and resultado_minuta.get("salvo")
                        and resultado_minuta.get("confirmado_apos_salvar")
                    )

                    resultado_minuta["modo"] = (
                        "limpeza_especificacoes_complementares_retorno_para_estudo"
                    )
                    resultado_minuta["limpeza_exigida"] = bool(limpeza_exigida)
                    resultado_minuta["limpeza_confirmada"] = bool(
                        limpeza_confirmada
                    )

                    retorno_estudo["corrigir_minuta"] = resultado_minuta
                    retorno_estudo["limpeza_minuta_exigida"] = bool(
                        limpeza_exigida
                    )
                    retorno_estudo["limpeza_minuta_confirmada"] = bool(
                        limpeza_confirmada
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
                    if limpeza_exigida and not limpeza_confirmada:
                        retorno_estudo["pode_enviar_para_aprovacao"] = False
                        retorno_estudo["deve_enviar_para_aprovacao"] = False
                        retorno_estudo["acao_recomendada"] = (
                            "Não enviar para aprovação / Revisar Corrigir Minuta"
                        )
                        retorno_estudo["status_comparacao"] = (
                            "bloqueado_por_falha_na_limpeza_da_minuta"
                        )
                        retorno_estudo.setdefault("alertas", []).append(
                            "A aprovação automática foi bloqueada porque não foi "
                            "possível confirmar que Especificações Complementares "
                            "foram apagadas e salvas."
                        )

                    # A análise já encerrou a tela Comparar Versões. Agora o envio
                    # pode ocorrer somente se a comparação estiver apta e, quando
                    # exigida, a limpeza da minuta estiver confirmada.
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
                    resumo["sar_minuta"] = {
                        "status": "nao_aplicavel_fila_retorno_para_estudo",
                        "mensagem": (
                            "A fila Retorno Para Estudo não executa julgamento de SAR. "
                            "O tratamento da minuta nesta fila é somente a limpeza "
                            "de Especificações Complementares por tipo de produto."
                        ),
                        "preencher_frase": False,
                        "preenchido_automaticamente": False,
                        "salvo": False,
                        "confirmado_apos_salvar": False,
                    }
                    resumo["minuta"] = {
                        "preenchida": False,
                        "campo_limpo": bool(resultado_minuta.get("limpo")),
                        "alterada": bool(resultado_minuta.get("limpo")),
                        "salvo": bool(resultado_minuta.get("salvo")),
                        "confirmado_apos_salvar": bool(
                            resultado_minuta.get("confirmado_apos_salvar")
                        ),
                        "status": resultado_minuta.get("status", ""),
                        "mensagem": resultado_minuta.get(
                            "mensagem",
                            resultado_minuta.get("motivo", ""),
                        ),
                        "frase": "",
                        "modo": (
                            "limpeza_especificacoes_complementares_retorno_para_estudo"
                        ),
                        "tipo_produto": tipo_produto,
                    }
                    resumo["preenchimento_sch"]["minuta"] = bool(
                        limpeza_confirmada
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
                        f"Limpeza da minuta={'SIM' if limpeza_confirmada else 'NÃO'} | "
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
