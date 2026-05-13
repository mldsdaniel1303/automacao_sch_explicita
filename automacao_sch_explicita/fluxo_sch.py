from pathlib import Path
from datetime import datetime
import re
import unicodedata

from navegador import criar_driver
from utils import aguardar_enter, carregar_regras, salvar_json, nome_seguro
from pdf_parser import parsear_certificado_pdf
from funcoes_sch import (
    abrir_sch,
    clicar_fila_em_analise,
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
    preencher_minuta_sar_se_necessario,
    garantir_sessao_ativa_sch,
    voltar_para_fila,
)
from analise_requerimentos import analisar_requerimento
from gerador_relatorio import gerar_req_report

VERSAO_SCRIPT = "0.6.8"


def _normalizar_texto(valor):
    if valor is None:
        return ""

    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


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


def _criar_driver_com_pasta(pasta_base):
    pasta_base = Path(pasta_base).resolve()
    pasta_base.mkdir(parents=True, exist_ok=True)

    pasta_download = pasta_base / "browser_downloads"
    pasta_download.mkdir(parents=True, exist_ok=True)

    tentativas = [
        {"pasta_base": str(pasta_base), "pasta_download": str(pasta_download)},
        {"pasta_saida_base": str(pasta_base), "pasta_download": str(pasta_download)},
        {"pasta_saida": str(pasta_base), "pasta_download": str(pasta_download)},
    ]

    for kwargs in tentativas:
        try:
            return criar_driver(**kwargs)
        except TypeError:
            continue

    print("[WARN] criar_driver() não aceitou pasta personalizada. Usando comportamento atual do navegador.")
    return criar_driver()


def perguntar_se_fecha_navegador():
    while True:
        resposta = input("[SCH] Deseja fechar o navegador ao final do fluxo? (s/n): ").strip().lower()

        if resposta in {"s", "sim"}:
            return True

        if resposta in {"n", "nao", "não"}:
            return False

        print("[SCH][WARN] Resposta inválida. Digite 's' para sim ou 'n' para não.")


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


def executar_fluxo_sch(
    pasta_base,
    limite_requerimentos=None,
    processar_somente_pendentes=False,
    processar_apenas_radiacao_restrita=True,
    preencher_caracteristicas=True,
    preencher_minuta=True,
    preencher_informacoes_adicionais=False,
    pausar_antes_anexos=False,
    categorias_anexos=None,
    fechar_navegador_ao_final=None,
):
    pasta_base = Path(pasta_base).resolve()
    pasta_base.mkdir(parents=True, exist_ok=True)

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

    driver, wait, pasta_saida_driver, pasta_download = _criar_driver_com_pasta(pasta_base)

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

        clicar_fila_em_analise(driver, wait)
        requerimentos = coletar_requerimentos(driver, wait, regras)

        requerimentos = list(reversed(requerimentos))

        if limite_requerimentos:
            requerimentos = requerimentos[: int(limite_requerimentos)]

        requerimentos_processaveis, requerimentos_ignorados = separar_requerimentos_por_escopo(
            requerimentos,
            processar_apenas_rr=processar_apenas_radiacao_restrita,
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
        print(f"[SCH] Categorias de anexos configuradas: {', '.join(categorias_anexos_ativas) if categorias_anexos_ativas else 'padrão do sistema'}")

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

            print("=" * 90)
            print(f"[SCH] Iniciando processamento do requerimento {numero}")
            print(f"[SCH] Pasta do requerimento: {pasta_req}")
            print("=" * 90)

            resumo = {
                "requerimento": req,
                "pasta_requerimento": str(pasta_req),
                "anexos_baixados": [],
                "dados_pdf": {},
                "pdf_cct": "",
                "validade_cct": {},
                "sar_minuta": {},
                "tabela_tecnica_sch": {},
                "conferencia_sch_cct": {},
                "downloads_realizados": 0,
                "status": "iniciado",
                "inicio": datetime.now().isoformat(),
                "fim": None,
                "versao_script": VERSAO_SCRIPT,
                "escopo_processamento": "radiacao_restrita" if processar_apenas_radiacao_restrita else "todos",
                "escopo_normativo": _dados_normativos_radiacao_restrita(),
                "categorias_anexos_configuradas": categorias_anexos_ativas,
                "preenchimento_sch": {
                    "minuta": False,
                    "minuta_habilitada": preencher_minuta,
                    "caracteristicas": preencher_caracteristicas,
                    "informacoes_adicionais": preencher_informacoes_adicionais,
                },
                "minuta": {
                    "preenchida": False,
                    "salvo": False,
                    "confirmado_apos_salvar": False,
                    "status": "pendente" if preencher_minuta else "desabilitado_pelo_usuario",
                    "mensagem": (
                        "Preenchimento de Corrigir Minuta habilitado."
                        if preencher_minuta
                        else "Preenchimento de Corrigir Minuta desabilitado pelo usuário."
                    ),
                    "frase": "",
                },
            }

            try:
                garantir_sessao_ativa_sch(
                    driver,
                    wait,
                    contexto=f"antes de iniciar o requerimento {numero}",
                    reabrir_fila=True,
                )

                abrir_requerimento(driver, wait, req)

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

                if pdf_cct:
                    print(f"[SCH] PDF CCT localizado: {pdf_cct}")
                    dados_pdf = parsear_certificado_pdf(pdf_cct)
                else:
                    print("[SCH][WARN] Nenhum PDF CCT localizado na pasta do requerimento.")
                    dados_pdf = {}

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

                if preencher_minuta:
                    sar_minuta = preencher_minuta_sar_se_necessario(
                        driver=driver,
                        wait=wait,
                        dados_pdf=dados_pdf,
                    )
                else:
                    sar_minuta = {
                        "status": "desabilitado_pelo_usuario",
                        "mensagem": "Preenchimento de Corrigir Minuta desabilitado pelo usuário.",
                        "frase": "",
                        "preencher_frase": False,
                        "preenchido_automaticamente": False,
                        "salvo": False,
                        "confirmado_apos_salvar": False,
                    }

                resumo["sar_minuta"] = sar_minuta
                resumo["minuta"] = {
                    "preenchida": bool(sar_minuta.get("preenchido_automaticamente")),
                    "salvo": bool(sar_minuta.get("salvo")),
                    "confirmado_apos_salvar": bool(sar_minuta.get("confirmado_apos_salvar")),
                    "status": sar_minuta.get("status", ""),
                    "mensagem": sar_minuta.get("mensagem", ""),
                    "frase": sar_minuta.get("frase", ""),
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

                controle = {
                    "requerimento": numero,
                    "downloads_realizados": qtd_downloads,
                    "categorias_configuradas": categorias_anexos_ativas,
                    "categorias_processadas": sorted(
                        list(
                            {
                                item.get("categoria", "")
                                for item in resumo["anexos_baixados"]
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
                    ),
                    "escopo_processamento": resumo["escopo_processamento"],
                    "atualizado_em": datetime.now().isoformat(),
                }
                salvar_json(pasta_req / "controle_downloads.json", controle)

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

                try:
                    voltar_para_fila(driver, wait)
                except Exception as e:
                    print(f"[SCH][WARN] Não foi possível voltar normalmente: {e}")

        fim_execucao = datetime.now()

        caminho_relatorio = pasta_base / "relatorio_execucao.json"
        salvar_json(
            caminho_relatorio,
            {
                "inicio_execucao": inicio_execucao.isoformat(),
                "fim_execucao": fim_execucao.isoformat(),
                "tempo_total_segundos": round((fim_execucao - inicio_execucao).total_seconds(), 2),
                "total_coletados_na_fila": len(requerimentos),
                "total_processaveis": len(requerimentos_processaveis),
                "total_ignorados_fora_escopo": len(requerimentos_ignorados),
                "sucessos": sum(1 for x in relatorio_execucao if x.get("status") == "sucesso"),
                "erros": sum(1 for x in relatorio_execucao if x.get("status") == "erro"),
                "documentos_processados": sum(x.get("downloads_realizados", 0) for x in relatorio_execucao),
                "itens": relatorio_execucao,
                "ignorados_fora_escopo": ignorados_resumidos,
                "versao_script": VERSAO_SCRIPT,
                "pasta_base": str(pasta_base),
                "categorias_anexos_configuradas": categorias_anexos_ativas,
            },
        )
        print(f"[SCH] Relatório consolidado salvo em: {caminho_relatorio}")

        caminho_req_report = gerar_req_report(
            pasta_saida=pasta_base,
            resultados=relatorio_execucao,
            versao_script=VERSAO_SCRIPT,
            inicio_execucao=inicio_execucao,
            fim_execucao=fim_execucao,
        )
        print(f"[SCH] Pasta req_report gerada em: {caminho_req_report}")

    finally:
        if fechar_navegador_ao_final:
            print("[SCH] Encerrando navegador.")
            driver.quit()
        else:
            print("[SCH] Navegador mantido aberto ao final do fluxo.")