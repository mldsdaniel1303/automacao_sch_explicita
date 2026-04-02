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
    preencher_caracteristicas_tecnicas_com_analise,
    preencher_informacoes_adicionais_com_analise,
    preencher_minuta_com_dados,
    voltar_para_fila,
)
from analise_requerimentos import analisar_requerimento
from gerador_relatorio import gerar_req_report

VERSAO_SCRIPT = "0.5.1"


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


def separar_requerimentos_por_escopo(requerimentos, regras):
    processar_apenas_rr = regras.get("processar_apenas_radiacao_restrita", True)

    if not processar_apenas_rr:
        return requerimentos, []

    selecionados = []
    ignorados = []

    for req in requerimentos:
        if _eh_radiacao_restrita(req):
            selecionados.append(req)
        else:
            ignorados.append(req)

    return selecionados, ignorados


def preparar_pastas_requerimentos(pasta_saida, requerimentos):
    pasta_requerimentos = Path(pasta_saida) / "requerimentos"
    pasta_requerimentos.mkdir(parents=True, exist_ok=True)

    mapeados = []
    for req in requerimentos:
        numero = req.get("requerimento", "sem_numero")
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


def salvar_manifesto_requerimentos(pasta_saida, mapeados, ignorados=None):
    caminho = Path(pasta_saida) / "manifest_requerimentos.json"
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
    ignorar = {"resumo.json", "controle_downloads.json", "analise_requerimento.json"}
    return len([p for p in pasta_req.rglob("*") if p.is_file() and p.name not in ignorar])


def executar_fluxo_sch():
    regras = carregar_regras()
    driver, wait, pasta_saida, pasta_download = criar_driver()

    relatorio_execucao = []
    inicio_execucao = datetime.now()

    try:
        abrir_sch(driver)
        aguardar_enter("[SCH] Faça o login manualmente no sistema.")

        clicar_fila_em_analise(driver, wait)
        requerimentos = coletar_requerimentos(driver, wait, regras)

        if regras.get("limite_requerimentos"):
            requerimentos = requerimentos[: regras["limite_requerimentos"]]

        requerimentos_processaveis, requerimentos_ignorados = separar_requerimentos_por_escopo(
            requerimentos,
            regras,
        )

        pasta_requerimentos, mapeados = preparar_pastas_requerimentos(
            pasta_saida,
            requerimentos_processaveis,
        )

        ignorados_resumidos = [
            {
                "requerimento": req.get("requerimento", "sem_numero"),
                "tipo_produto": req.get("tipo_produto", ""),
                "motivo": "fora_escopo_radiacao_restrita",
            }
            for req in requerimentos_ignorados
        ]

        print("[SCH] Mapeando requerimentos...")
        print(f"[SCH] Total coletado na fila: {len(requerimentos)}")
        print(f"[SCH] Dentro do escopo (radiação restrita): {len(requerimentos_processaveis)}")
        print(f"[SCH] Fora do escopo: {len(requerimentos_ignorados)}")
        print(f"[SCH] {sum(1 for x in mapeados if x['status'] == 'pendente')} requerimento(s) pendente(s)")
        print(f"[SCH] {sum(1 for x in mapeados if x['status'] == 'processado')} requerimento(s) já processado(s)")

        caminho_manifesto = salvar_manifesto_requerimentos(
            pasta_saida,
            mapeados,
            ignorados=ignorados_resumidos,
        )
        print(f"[SCH] Manifesto salvo em: {caminho_manifesto}")

        if not requerimentos_processaveis:
            print("[SCH][WARN] Nenhum requerimento de radiação restrita encontrado para processamento.")
            return

        for req in requerimentos_processaveis:
            numero = req.get("requerimento", "sem_numero")
            pasta_req = pasta_requerimentos / nome_seguro(numero)

            print("=" * 90)
            print(f"[SCH] Iniciando processamento do requerimento {numero}")
            print("=" * 90)

            resumo = {
                "requerimento": req,
                "pasta_requerimento": str(pasta_req),
                "anexos_baixados": [],
                "dados_pdf": {},
                "pdf_cct": "",
                "downloads_realizados": 0,
                "status": "iniciado",
                "inicio": datetime.now().isoformat(),
                "versao_script": VERSAO_SCRIPT,
                "escopo_processamento": "radiacao_restrita",
                "escopo_normativo": _dados_normativos_radiacao_restrita(),
            }

            try:
                abrir_requerimento(driver, wait, req)

                if regras.get("pausar_antes_anexos", True):
                    aguardar_enter("[SCH] Se a tela estiver pronta, prossiga para a aba Anexos.")

                clicar_aba_anexos(driver, wait)

                anexos_baixados = baixar_todos_os_anexos_de_todas_as_categorias(
                    driver=driver,
                    wait=wait,
                    req=req,
                    pasta_saida=pasta_requerimentos,
                    pasta_download=pasta_download,
                    regras=regras,
                )

                resumo["anexos_baixados"] = anexos_baixados or []

                pdf_cct = localizar_pdf_cct_do_requerimento(pasta_req, regras)
                resumo["pdf_cct"] = str(pdf_cct) if pdf_cct else ""

                if pdf_cct:
                    print(f"[SCH] PDF CCT localizado no requerimento: {pdf_cct}")
                    dados_pdf = parsear_certificado_pdf(pdf_cct)
                else:
                    print("[SCH][WARN] Nenhum PDF CCT localizado na pasta do requerimento.")
                    dados_pdf = {}

                resumo["dados_pdf"] = dados_pdf

                analise_rapida = preencher_caracteristicas_tecnicas_com_analise(
                    driver=driver,
                    wait=wait,
                    req=req,
                    anexos_baixados=resumo["anexos_baixados"],
                    dados_pdf=dados_pdf,
                )
                resumo["analise_rapida"] = analise_rapida
                resumo["observacao_caracteristicas"] = analise_rapida.get("texto", "")

                info_adicionais = preencher_informacoes_adicionais_com_analise(
                    driver=driver,
                    wait=wait,
                    req=req,
                    anexos_baixados=resumo["anexos_baixados"],
                    dados_pdf=dados_pdf,
                    analise_rapida=analise_rapida,
                )
                resumo["informacoes_adicionais"] = info_adicionais

                if regras.get("preencher_minuta", True) and dados_pdf:
                    preencher_minuta_com_dados(driver, wait, dados_pdf)
                else:
                    print("[SCH][WARN] Sem dados de CCT para preencher a minuta.")

                qtd_downloads = contar_arquivos_requerimento(pasta_req)
                resumo["downloads_realizados"] = qtd_downloads

                controle = {
                    "requerimento": numero,
                    "downloads_realizados": qtd_downloads,
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
                                }
                            }
                        )
                    ),
                    "escopo_processamento": "radiacao_restrita",
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

        caminho_relatorio = Path(pasta_saida) / "relatorio_execucao.json"
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
            },
        )
        print(f"[SCH] Relatório consolidado salvo em: {caminho_relatorio}")

        caminho_req_report = gerar_req_report(
            pasta_saida=Path(pasta_saida),
            resultados=relatorio_execucao,
            versao_script=VERSAO_SCRIPT,
            inicio_execucao=inicio_execucao,
            fim_execucao=fim_execucao,
        )
        print(f"[SCH] Pasta req_report gerada em: {caminho_req_report}")

    finally:
        print("[SCH] Encerrando navegador.")
        driver.quit()