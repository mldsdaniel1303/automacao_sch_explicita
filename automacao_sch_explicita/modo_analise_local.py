from pathlib import Path
from datetime import datetime
import json

from utils import salvar_json
from pdf_parser import parsear_certificado_pdf
from analise_requerimentos import analisar_requerimento
from gerador_relatorio import gerar_req_report
from funcoes_sch import localizar_pdf_cct_do_requerimento

VERSAO_SCRIPT = "0.6.1"


def contar_arquivos_requerimento(pasta_req):
    pasta_req = Path(pasta_req)
    ignorar = {"resumo.json", "controle_downloads.json", "analise_requerimento.json"}
    return len([p for p in pasta_req.rglob("*") if p.is_file() and p.name not in ignorar])


def _carregar_json_se_existir(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return {}

    try:
        with caminho.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _parece_pasta_de_requerimento(pasta):
    pasta = Path(pasta)

    if not pasta.exists() or not pasta.is_dir():
        return False

    if (pasta / "resumo.json").exists():
        return True

    if (pasta / "controle_downloads.json").exists():
        return True

    if (pasta / "analise_requerimento.json").exists():
        return True

    if any(pasta.rglob("*.pdf")):
        return True

    subdirs = [p.name.lower() for p in pasta.iterdir() if p.is_dir()]
    pistas = [
        "certificado",
        "cct",
        "manual",
        "outros",
        "fotos",
        "ract",
        "ensaio",
        "selo",
        "contrato",
        "art",
    ]
    if any(any(pista in nome for pista in pistas) for nome in subdirs):
        return True

    return False


def _resolver_pasta_requerimentos(pasta_escolhida):
    pasta_escolhida = Path(pasta_escolhida).resolve()

    if not pasta_escolhida.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {pasta_escolhida}")

    if not pasta_escolhida.is_dir():
        raise NotADirectoryError(f"O caminho selecionado não é uma pasta: {pasta_escolhida}")

    # Caso 1: usuário escolheu a pasta base da execução
    pasta_requerimentos = pasta_escolhida / "requerimentos"
    if pasta_requerimentos.exists() and pasta_requerimentos.is_dir():
        return {
            "pasta_base": pasta_escolhida,
            "pasta_requerimentos": pasta_requerimentos,
            "pasta_requerimento_unico": None,
            "modo": "pasta_base",
        }

    # Caso 2: usuário escolheu diretamente a pasta "requerimentos"
    subpastas = [p for p in pasta_escolhida.iterdir() if p.is_dir()]
    if subpastas and any(_parece_pasta_de_requerimento(p) for p in subpastas):
        return {
            "pasta_base": pasta_escolhida.parent,
            "pasta_requerimentos": pasta_escolhida,
            "pasta_requerimento_unico": None,
            "modo": "pasta_requerimentos",
        }

    # Caso 3: usuário escolheu a pasta de um único requerimento
    if _parece_pasta_de_requerimento(pasta_escolhida):
        return {
            "pasta_base": pasta_escolhida.parent,
            "pasta_requerimentos": None,
            "pasta_requerimento_unico": pasta_escolhida,
            "modo": "requerimento_unico",
        }

    raise FileNotFoundError(
        "A pasta selecionada não parece ser uma pasta base, nem a pasta "
        f"'requerimentos', nem uma pasta de requerimento único: {pasta_escolhida}"
    )


def _listar_requerimentos(info_pastas):
    modo = info_pastas["modo"]

    if modo == "requerimento_unico":
        return [info_pastas["pasta_requerimento_unico"]]

    pasta_requerimentos = info_pastas["pasta_requerimentos"]

    return sorted(
        [p for p in Path(pasta_requerimentos).iterdir() if p.is_dir()],
        key=lambda p: p.name.lower(),
    )


def _filtrar_pendentes(pastas_req):
    filtrados = []

    for pasta_req in pastas_req:
        resumo = _carregar_json_se_existir(pasta_req / "resumo.json")
        analise = pasta_req / "analise_requerimento.json"

        status = resumo.get("status")
        if not analise.exists() or status not in {"sucesso", "analise_local_sucesso"}:
            filtrados.append(pasta_req)

    return filtrados


def executar_modo_analise_local(
    pasta_base,
    limite_requerimentos=None,
    processar_somente_pendentes=False,
):
    pasta_escolhida = Path(pasta_base).resolve()
    info_pastas = _resolver_pasta_requerimentos(pasta_escolhida)

    pasta_base_real = info_pastas["pasta_base"]
    relatorios_dir = pasta_base_real / "relatorios"
    relatorios_dir.mkdir(parents=True, exist_ok=True)

    requerimentos_dirs = _listar_requerimentos(info_pastas)

    if processar_somente_pendentes:
        requerimentos_dirs = _filtrar_pendentes(requerimentos_dirs)

    if limite_requerimentos:
        requerimentos_dirs = requerimentos_dirs[: int(limite_requerimentos)]

    print("=" * 80)
    print("[LOCAL] MODO SOMENTE ANÁLISE LOCAL")
    print("=" * 80)
    print(f"[LOCAL] Pasta escolhida: {pasta_escolhida}")
    print(f"[LOCAL] Pasta base considerada: {pasta_base_real}")
    print(f"[LOCAL] Modo detectado: {info_pastas['modo']}")
    print(f"[LOCAL] Total selecionado: {len(requerimentos_dirs)}")

    if not requerimentos_dirs:
        print("[LOCAL][WARN] Nenhum requerimento encontrado para análise.")
        return

    resultados = []
    inicio_execucao = datetime.now()

    for pasta_req in requerimentos_dirs:
        numero = pasta_req.name
        print("-" * 80)
        print(f"[LOCAL] Analisando requerimento: {numero}")
        print(f"[LOCAL] Pasta: {pasta_req}")

        resumo_existente = _carregar_json_se_existir(pasta_req / "resumo.json")
        req = resumo_existente.get("requerimento")

        if not isinstance(req, dict):
            req = {"requerimento": numero}

        resumo = dict(resumo_existente) if isinstance(resumo_existente, dict) else {}
        resumo.setdefault("requerimento", req)
        resumo["pasta_requerimento"] = str(pasta_req)
        resumo["inicio"] = datetime.now().isoformat()
        resumo["versao_script"] = VERSAO_SCRIPT
        resumo["modo_execucao"] = "analise_local"

        try:
            pdf_cct = localizar_pdf_cct_do_requerimento(pasta_req, regras=None)
            resumo["pdf_cct"] = str(pdf_cct) if pdf_cct else ""

            if pdf_cct:
                print(f"[LOCAL] CCT localizado: {pdf_cct.name}")
                dados_pdf = parsear_certificado_pdf(pdf_cct)
            else:
                print("[LOCAL][WARN] Nenhum CCT localizado para este requerimento.")
                dados_pdf = {}

            resumo["dados_pdf"] = dados_pdf
            resumo["downloads_realizados"] = contar_arquivos_requerimento(pasta_req)

            analise_documental = analisar_requerimento(
                pasta_req=pasta_req,
                req=req,
                resumo=resumo,
            )
            resumo["analise_documental"] = analise_documental

            salvar_json(pasta_req / "analise_requerimento.json", analise_documental)

            resumo["status"] = "analise_local_sucesso"
            resumo["fim"] = datetime.now().isoformat()

            print(f"[LOCAL] Análise concluída com sucesso: {numero}")

        except Exception as e:
            resumo["status"] = "analise_local_erro"
            resumo["fim"] = datetime.now().isoformat()
            resumo["erro"] = {
                "tipo": type(e).__name__,
                "mensagem": str(e),
                "repr": repr(e),
            }
            print(f"[LOCAL][ERRO] Falha no requerimento {numero}: {type(e).__name__}: {e}")

        salvar_json(pasta_req / "resumo.json", resumo)
        resultados.append(resumo)

    fim_execucao = datetime.now()

    caminho_relatorio = relatorios_dir / "relatorio_execucao_local.json"
    salvar_json(
        caminho_relatorio,
        {
            "modo_execucao": "analise_local",
            "inicio_execucao": inicio_execucao.isoformat(),
            "fim_execucao": fim_execucao.isoformat(),
            "tempo_total_segundos": round((fim_execucao - inicio_execucao).total_seconds(), 2),
            "total_processados": len(resultados),
            "sucessos": sum(1 for x in resultados if x.get("status") == "analise_local_sucesso"),
            "erros": sum(1 for x in resultados if x.get("status") == "analise_local_erro"),
            "itens": resultados,
            "versao_script": VERSAO_SCRIPT,
            "pasta_base": str(pasta_base_real),
            "pasta_escolhida": str(pasta_escolhida),
            "modo_detectado": info_pastas["modo"],
        },
    )
    print(f"[LOCAL] Relatório local salvo em: {caminho_relatorio}")

    caminho_req_report = gerar_req_report(
        pasta_saida=relatorios_dir,
        resultados=resultados,
        versao_script=VERSAO_SCRIPT,
        inicio_execucao=inicio_execucao,
        fim_execucao=fim_execucao,
    )
    print(f"[LOCAL] Pasta req_report gerada em: {caminho_req_report}")