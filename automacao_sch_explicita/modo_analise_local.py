from pathlib import Path
from datetime import datetime
import json
import re
import unicodedata

from utils import salvar_json
from pdf_parser import parsear_certificado_pdf
from analise_requerimentos import analisar_requerimento
from gerador_relatorio import gerar_req_report
from funcoes_sch import (
    localizar_pdf_cct_do_requerimento,
    avaliar_validade_cct,
)

try:
    from funcoes_sch import comparar_dados_sch_x_cct
except ImportError:
    comparar_dados_sch_x_cct = None

try:
    from funcoes_sch import comparar_datas_certificado_sch_x_cct
except ImportError:
    comparar_datas_certificado_sch_x_cct = None

try:
    from funcoes_sch import analisar_sar_cct
except ImportError:
    analisar_sar_cct = None

try:
    from caracteristicas_secundarias import (
        inferir_caracteristicas_secundarias,
        gerar_texto_caracteristicas_secundarias,
    )
except ImportError:
    inferir_caracteristicas_secundarias = None
    gerar_texto_caracteristicas_secundarias = None


VERSAO_SCRIPT = "0.7.0-local"


def contar_arquivos_requerimento(pasta_req):
    pasta_req = Path(pasta_req)
    ignorar = {
        "resumo.json",
        "controle_downloads.json",
        "analise_requerimento.json",
    }

    return len(
        [
            p for p in pasta_req.rglob("*")
            if p.is_file() and p.name not in ignorar
        ]
    )


def _carregar_json_se_existir(caminho):
    caminho = Path(caminho)

    if not caminho.exists():
        return {}

    try:
        with caminho.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _normalizar_texto_local(valor):
    texto = str(valor or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _texto_util(valor):
    return str(valor or "").strip()


def _valor_vazio_ou_invalido(valor):
    texto = _texto_util(valor)
    norm = _normalizar_texto_local(texto)

    if not norm:
        return True

    if norm in {
        "-",
        "--",
        "n/a",
        "na",
        "n a",
        "nao aplicavel",
        "nao identificado",
        "não identificado",
        "não aplicável",
        "none",
        "null",
    }:
        return True

    cabecalhos = [
        "modelo",
        "model",
        "modelos",
        "models",
        "nome comercial",
        "trade name",
        "modelo model",
        "nome comercial trade name",
        "modelo nome comercial",
        "model trade name",
    ]

    return norm in cabecalhos


def _extrair_numero_do_nome_pasta(nome_pasta):
    nome = str(nome_pasta or "").strip()

    if not nome:
        return ""

    m = re.search(r"\b(\d{4,6})\s*[_\-/ ]\s*(\d{2})\b", nome)

    if m:
        return f"{m.group(1)}/{m.group(2)}"

    if re.fullmatch(r"\d{3,}", nome):
        return nome

    m = re.search(r"\b(\d{3,})\b", nome)

    if m:
        return m.group(1)

    return ""


def _numero_req_para_nome_seguro(numero):
    numero = str(numero or "").strip()

    if not numero:
        return ""

    m = re.search(r"\b(\d{4,6})\s*[/_\- ]\s*(\d{2})\b", numero)

    if m:
        return f"{m.group(1)}_{m.group(2)}"

    return re.sub(r"[^\w.-]+", "_", numero)


def _normalizar_req_local(pasta_req, resumo_existente):
    numero_pasta = (
        _extrair_numero_do_nome_pasta(Path(pasta_req).name)
        or Path(pasta_req).name
    )

    req_existente = {}

    if isinstance(resumo_existente, dict):
        req_existente = resumo_existente.get("requerimento") or {}

    if not isinstance(req_existente, dict):
        req_existente = {}

    req = dict(req_existente)
    numero_existente = _texto_util(req.get("requerimento", ""))

    if not numero_existente or numero_existente.lower().startswith("sem_numero"):
        req["requerimento"] = numero_pasta

    return req


def _obter_dados_certificado_sch_salvos(resumo):
    resumo = resumo or {}
    dados = resumo.get("dados_certificado_sch") or {}

    if not isinstance(dados, dict):
        dados = {}

    req = resumo.get("requerimento") or {}

    if isinstance(req, dict):
        dados_req = req.get("dados_certificado_sch") or {}

        if isinstance(dados_req, dict):
            dados = {**dados_req, **dados}

    return dados


def _obter_tabela_sch_salva(resumo, req):
    resumo = resumo or {}
    req = req or {}
    tabela = resumo.get("tabela_tecnica_sch") or req.get("tabela_tecnica_sch") or {}

    if not isinstance(tabela, dict):
        return {"cabecalho": [], "linhas": []}

    return tabela


def _tabela_tem_linhas(tabela):
    if not isinstance(tabela, dict):
        return False

    return bool(tabela.get("linhas") or [])


def _aplicar_dados_sch_salvos_no_req(req, resumo):
    req = dict(req or {})
    resumo = resumo or {}
    dados_certificado_sch = _obter_dados_certificado_sch_salvos(resumo)

    nome_comercial = _texto_util(dados_certificado_sch.get("nome_comercial", ""))
    modelo_dados_gerais = _texto_util(
        dados_certificado_sch.get("modelo_sch_dados_gerais", "")
    )

    if nome_comercial and not _valor_vazio_ou_invalido(nome_comercial):
        req["nome_comercial"] = nome_comercial

    if modelo_dados_gerais and not _valor_vazio_ou_invalido(modelo_dados_gerais):
        req["modelo_sch_dados_gerais"] = modelo_dados_gerais

        if _valor_vazio_ou_invalido(req.get("modelo", "")):
            req["modelo"] = modelo_dados_gerais

    tabela_sch = _obter_tabela_sch_salva(resumo, req)

    if _tabela_tem_linhas(tabela_sch):
        req["tabela_tecnica_sch"] = tabela_sch

    if _valor_vazio_ou_invalido(req.get("nome_comercial", "")):
        req["nome_comercial"] = (
            req.get("modelo_sch_dados_gerais")
            or req.get("modelo")
            or ""
        )

    return req


def _completar_req_com_dados_pdf_para_relatorio(req, dados_pdf):
    """
    Completa campos vazios para deixar o relatório local legível.

    A conferência SCH x CCT deve ser calculada antes deste preenchimento
    quando não houver dados reais do SCH, para evitar falso positivo.
    """
    req = dict(req or {})
    dados_pdf = dados_pdf or {}

    preenchimentos = {
        "modelo": dados_pdf.get("modelo", ""),
        "nome_comercial": dados_pdf.get("nome_comercial", "") or dados_pdf.get("modelo", ""),
        "fabricante": dados_pdf.get("fabricante", ""),
        "solicitante": dados_pdf.get("solicitante", ""),
        "tipo_produto": dados_pdf.get("tipo_produto", ""),
        "certificado": dados_pdf.get("numero_certificado", ""),
        "homologacao": dados_pdf.get("homologacao", ""),
    }

    campos_preenchidos_por_cct = []

    for campo, valor in preenchimentos.items():
        valor_atual = _texto_util(req.get(campo, ""))
        valor_novo = _texto_util(valor)

        if _valor_vazio_ou_invalido(valor_atual) and not _valor_vazio_ou_invalido(valor_novo):
            req[campo] = valor_novo
            campos_preenchidos_por_cct.append(campo)

    if _valor_vazio_ou_invalido(req.get("nome_comercial", "")):
        req["nome_comercial"] = req.get("modelo", "")

    if campos_preenchidos_por_cct:
        req["_campos_preenchidos_por_cct_na_analise_local"] = campos_preenchidos_por_cct

    return req


def _tem_dados_sch_para_comparacao(req, resumo):
    req = req or {}
    resumo = resumo or {}
    campos_sch = ["certificado", "homologacao", "modelo", "fabricante", "tipo_produto"]

    if any(not _valor_vazio_ou_invalido(req.get(campo, "")) for campo in campos_sch):
        return True

    dados_certificado_sch = _obter_dados_certificado_sch_salvos(resumo)

    if any(
        not _valor_vazio_ou_invalido(dados_certificado_sch.get(campo, ""))
        for campo in ["numero_certificado", "data_certificado", "data_validade"]
    ):
        return True

    tabela_sch = _obter_tabela_sch_salva(resumo, req)

    if _tabela_tem_linhas(tabela_sch):
        return True

    return False


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
        raise NotADirectoryError(
            f"O caminho selecionado não é uma pasta: {pasta_escolhida}"
        )

    pasta_requerimentos = pasta_escolhida / "requerimentos"

    if pasta_requerimentos.exists() and pasta_requerimentos.is_dir():
        return {
            "pasta_base": pasta_escolhida,
            "pasta_requerimentos": pasta_requerimentos,
            "pasta_requerimento_unico": None,
            "modo": "pasta_base",
        }

    subpastas = [p for p in pasta_escolhida.iterdir() if p.is_dir()]

    if subpastas and any(_parece_pasta_de_requerimento(p) for p in subpastas):
        return {
            "pasta_base": pasta_escolhida.parent,
            "pasta_requerimentos": pasta_escolhida,
            "pasta_requerimento_unico": None,
            "modo": "pasta_requerimentos",
        }

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


def _filtrar_por_numero_requerimento(pastas_req, numero_requerimento):
    if not numero_requerimento:
        return pastas_req

    numero_busca = _normalizar_texto_local(numero_requerimento)
    numero_busca_seguro = _normalizar_texto_local(
        _numero_req_para_nome_seguro(numero_requerimento)
    )
    filtrados = []

    for pasta_req in pastas_req:
        nome_norm = _normalizar_texto_local(pasta_req.name)
        numero_pasta = _normalizar_texto_local(_extrair_numero_do_nome_pasta(pasta_req.name))

        if (
            numero_busca in nome_norm
            or numero_busca_seguro in nome_norm
            or numero_busca == numero_pasta
            or numero_busca_seguro == numero_pasta.replace("/", "_")
        ):
            filtrados.append(pasta_req)

    return filtrados


def _aplicar_datas_sch_no_dados_pdf(dados_pdf, dados_certificado_sch):
    dados_pdf = dict(dados_pdf or {})
    dados_certificado_sch = dados_certificado_sch or {}

    if not dados_certificado_sch:
        return dados_pdf

    dados_pdf["data_emissao_cct"] = dados_pdf.get("data_emissao", "")
    dados_pdf["data_validade_cct"] = dados_pdf.get("data_validade", "")
    dados_pdf["data_emissao_sch"] = dados_certificado_sch.get("data_certificado", "")
    dados_pdf["data_validade_sch"] = dados_certificado_sch.get("data_validade", "")
    dados_pdf["numero_certificado_sch_dados_gerais"] = dados_certificado_sch.get(
        "numero_certificado",
        "",
    )

    if dados_certificado_sch.get("data_certificado"):
        dados_pdf["data_emissao"] = dados_certificado_sch.get("data_certificado")

    if dados_certificado_sch.get("data_validade"):
        dados_pdf["data_validade"] = dados_certificado_sch.get("data_validade")

    if dados_certificado_sch.get("data_certificado") or dados_certificado_sch.get("data_validade"):
        dados_pdf["datas_origem"] = "SCH salvo no resumo.json - Dados Gerais - Dados do Certificado"

    return dados_pdf


def _comparar_datas_local(dados_certificado_sch, dados_pdf):
    if comparar_datas_certificado_sch_x_cct is None:
        return {
            "status_geral": "nao_executado",
            "mensagem": "Função comparar_datas_certificado_sch_x_cct não disponível.",
            "comparacoes": [],
            "divergencias": [],
        }

    if not dados_certificado_sch:
        return {
            "status_geral": "sem_dados_sch",
            "mensagem": "Não há dados de certificado do SCH salvos para comparar datas.",
            "comparacoes": [],
            "divergencias": [],
        }

    try:
        return comparar_datas_certificado_sch_x_cct(
            dados_certificado_sch=dados_certificado_sch,
            dados_pdf=dados_pdf,
        )
    except Exception as e:
        return {
            "status_geral": "erro",
            "mensagem": str(e),
            "comparacoes": [],
            "divergencias": [],
        }


def _analisar_sar_local(dados_pdf):
    if analisar_sar_cct is None:
        return {
            "status": "nao_executado",
            "mensagem": "Função analisar_sar_cct não disponível.",
            "frase": "",
            "preencher_frase": False,
            "preenchido_automaticamente": False,
            "salvo": False,
            "confirmado_apos_salvar": False,
            "modo_execucao": "analise_local",
        }

    try:
        sar = analisar_sar_cct(dados_pdf)
        sar = dict(sar or {})
    except Exception as e:
        sar = {
            "status": "erro",
            "mensagem": str(e),
            "frase": "",
            "preencher_frase": False,
        }

    sar["preenchido_automaticamente"] = False
    sar["salvo"] = False
    sar["confirmado_apos_salvar"] = False
    sar["retornou_para_requerimento"] = False
    sar["modo_execucao"] = "analise_local_sem_preenchimento"
    sar["observacao_local"] = (
        "A análise local apenas indica se a frase seria necessária; "
        "ela não abre o SCH e não preenche Corrigir Minuta."
    )

    return sar


def _inferir_caracteristicas_secundarias_local(dados_pdf):
    if inferir_caracteristicas_secundarias is None:
        return {
            "caracteristicas_secundarias": {
                "categoria": "",
                "titulo": "",
                "caracteristicas": {},
                "preencher_titulo": False,
                "status": "nao_executado",
            },
            "texto_caracteristicas_secundarias": "",
        }

    try:
        caracteristicas_sec = inferir_caracteristicas_secundarias(dados_pdf)

        if gerar_texto_caracteristicas_secundarias is not None:
            texto = gerar_texto_caracteristicas_secundarias(dados_pdf)
        else:
            texto = ""

        return {
            "caracteristicas_secundarias": caracteristicas_sec or {},
            "texto_caracteristicas_secundarias": texto or "",
        }
    except Exception as e:
        return {
            "caracteristicas_secundarias": {
                "categoria": "",
                "titulo": "",
                "caracteristicas": {},
                "preencher_titulo": False,
                "status": "erro",
                "erro": str(e),
            },
            "texto_caracteristicas_secundarias": "",
        }


def _montar_conferencia_sem_cct(numero):
    return {
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


def _montar_conferencia_sem_dados_sch(numero):
    return {
        "status_geral": "sem_dados_sch",
        "comparacoes": [],
        "divergencias": [],
        "campos_ausentes": [],
        "comparacao_tabela_tecnica": {
            "status": "sem_tabela",
            "motivo": "sem_dados_sch_salvos_para_comparacao",
            "divergencias": [],
        },
        "requerimento": numero,
        "motivo": "A análise local encontrou CCT, mas não encontrou dados do SCH salvos no resumo.json.",
    }


def _comparar_sch_x_cct_local(req, resumo, dados_pdf):
    numero = (req or {}).get("requerimento", "")

    if not dados_pdf:
        return _montar_conferencia_sem_cct(numero)

    if not _tem_dados_sch_para_comparacao(req, resumo):
        return _montar_conferencia_sem_dados_sch(numero)

    if comparar_dados_sch_x_cct is None:
        return {
            "status_geral": "nao_executado",
            "comparacoes": [],
            "divergencias": [],
            "campos_ausentes": [],
            "comparacao_tabela_tecnica": {
                "status": "nao_executado",
                "motivo": "função comparar_dados_sch_x_cct não disponível",
                "divergencias": [],
            },
            "requerimento": numero,
            "motivo": "Função comparar_dados_sch_x_cct não disponível.",
        }

    try:
        return comparar_dados_sch_x_cct(req, dados_pdf)
    except Exception as e:
        return {
            "status_geral": "erro",
            "comparacoes": [],
            "divergencias": [],
            "campos_ausentes": [],
            "comparacao_tabela_tecnica": {
                "status": "erro",
                "motivo": str(e),
                "divergencias": [],
            },
            "requerimento": numero,
            "motivo": str(e),
        }


def _resumo_tabela_tecnica(conferencia):
    tabela = (conferencia or {}).get("comparacao_tabela_tecnica") or {}

    return {
        "status": tabela.get("status", ""),
        "motivo": tabela.get("motivo", ""),
        "linhas_sch": tabela.get("linhas_sch", 0),
        "linhas_cct": tabela.get("linhas_cct", 0),
        "linhas_extraidas_sch": tabela.get("linhas_extraidas_sch", 0),
        "linhas_extraidas_cct": tabela.get("linhas_extraidas_cct", 0),
        "campos_comparados": tabela.get("campos_comparados", []),
        "origem_tabela_cct": tabela.get("origem_tabela_cct", ""),
        "qtd_divergencias": len(tabela.get("divergencias", []) or []),
    }


def _imprimir_resumo_requerimento_local(resumo):
    req = resumo.get("requerimento") or {}
    dados_pdf = resumo.get("dados_pdf") or {}
    conferencia = resumo.get("conferencia_sch_cct") or {}
    comparacao_tabela = (conferencia.get("comparacao_tabela_tecnica") or {})
    sar = resumo.get("sar_minuta") or {}
    tabela_cct = dados_pdf.get("tabela_tecnica_cct") or {}
    tabela_sch = resumo.get("tabela_tecnica_sch") or req.get("tabela_tecnica_sch") or {}

    print("[LOCAL] Resumo:")
    print(f"[LOCAL] - Modelo SCH: {req.get('modelo', '') or 'não identificado'}")
    print(f"[LOCAL] - Modelo CCT: {dados_pdf.get('modelo', '') or 'não identificado'}")
    print(f"[LOCAL] - Nome Comercial: {req.get('nome_comercial', '') or dados_pdf.get('nome_comercial', '') or 'não identificado'}")
    print(
        "[LOCAL] - Tabela SCH/CCT: "
        f"{len(tabela_sch.get('linhas', []) or [])} linha(s) bruta(s) SCH | "
        f"{len(tabela_cct.get('linhas', []) or [])} linha(s) bruta(s) CCT | "
        f"origem CCT={tabela_cct.get('origem_extracao', '') or 'não informada'}"
    )
    print(
        "[LOCAL] - Comparação técnica: "
        f"status={comparacao_tabela.get('status', '') or 'não executada'} | "
        f"SCH={comparacao_tabela.get('linhas_sch', 0)} | "
        f"CCT={comparacao_tabela.get('linhas_cct', 0)} | "
        f"motivo={comparacao_tabela.get('motivo', '')}"
    )
    print(
        "[LOCAL] - SAR: "
        f"status={sar.get('status', '') or 'não executado'} | "
        f"frase_necessaria={sar.get('preencher_frase', False)}"
    )


def _contar_statuses(resultados):
    total = len(resultados)
    sucessos = sum(1 for x in resultados if x.get("status") == "analise_local_sucesso")
    erros = sum(1 for x in resultados if x.get("status") == "analise_local_erro")
    sem_cct = sum(1 for x in resultados if not x.get("pdf_cct"))
    divergentes = sum(
        1 for x in resultados
        if (x.get("conferencia_sch_cct") or {}).get("status_geral") == "divergente"
    )
    sem_dados_sch = sum(
        1 for x in resultados
        if (x.get("conferencia_sch_cct") or {}).get("status_geral") == "sem_dados_sch"
    )
    tabela_divergente = sum(
        1 for x in resultados
        if ((x.get("conferencia_sch_cct") or {}).get("comparacao_tabela_tecnica") or {}).get("status") == "divergente"
    )
    sar_aplicavel = sum(
        1 for x in resultados
        if (x.get("sar_minuta") or {}).get("status") == "sar_aplicavel"
    )
    sar_nao_aplicavel = sum(
        1 for x in resultados
        if (x.get("sar_minuta") or {}).get("status") == "sar_nao_aplicavel"
    )

    return {
        "total_processados": total,
        "sucessos": sucessos,
        "erros": erros,
        "sem_cct": sem_cct,
        "sem_dados_sch": sem_dados_sch,
        "conferencia_divergente": divergentes,
        "tabela_tecnica_divergente": tabela_divergente,
        "sar_aplicavel": sar_aplicavel,
        "sar_nao_aplicavel": sar_nao_aplicavel,
    }


def debug_pdf_local(caminho_pdf):
    """
    Testa rapidamente a extração de um CCT sem rodar todo o lote.

    Uso opcional pelo terminal Python:
        from modo_analise_local import debug_pdf_local
        debug_pdf_local(r"C:\\caminho\\arquivo.pdf")
    """
    caminho_pdf = Path(caminho_pdf).resolve()

    if not caminho_pdf.exists():
        raise FileNotFoundError(f"PDF não encontrado: {caminho_pdf}")

    dados_pdf = parsear_certificado_pdf(caminho_pdf)
    tabela = dados_pdf.get("tabela_tecnica_cct") or {}

    print("=" * 80)
    print("[LOCAL][DEBUG PDF]")
    print("=" * 80)
    print(f"Arquivo: {caminho_pdf}")
    print(f"Certificado: {dados_pdf.get('numero_certificado', '')}")
    print(f"Homologação: {dados_pdf.get('homologacao', '')}")
    print(f"Modelo: {dados_pdf.get('modelo', '')}")
    print(f"Nome Comercial: {dados_pdf.get('nome_comercial', '')}")
    print(f"Fabricante: {dados_pdf.get('fabricante', '')}")
    print(f"Solicitante: {dados_pdf.get('solicitante', '')}")
    print(f"Tipo do produto: {dados_pdf.get('tipo_produto', '')}")
    print(f"Data emissão: {dados_pdf.get('data_emissao', '')}")
    print(f"Data validade: {dados_pdf.get('data_validade', '')}")
    print(f"Tabela CCT: {len(tabela.get('linhas', []) or [])} linha(s)")
    print(f"Origem tabela CCT: {tabela.get('origem_extracao', '')}")

    for idx, linha in enumerate(tabela.get("linhas", []) or [], start=1):
        print(f"  {idx:02d}. {linha}")

    if analisar_sar_cct is not None:
        sar = analisar_sar_cct(dados_pdf)
        print(f"SAR: {sar.get('status')} | frase necessária={sar.get('preencher_frase')}")

    return dados_pdf


def executar_modo_analise_local(
    pasta_base,
    limite_requerimentos=None,
    processar_somente_pendentes=False,
    numero_requerimento=None,
):
    pasta_escolhida = Path(pasta_base).resolve()
    info_pastas = _resolver_pasta_requerimentos(pasta_escolhida)

    pasta_base_real = info_pastas["pasta_base"]
    requerimentos_dirs = _listar_requerimentos(info_pastas)

    if numero_requerimento:
        requerimentos_dirs = _filtrar_por_numero_requerimento(
            requerimentos_dirs,
            numero_requerimento,
        )

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

    if numero_requerimento:
        print(f"[LOCAL] Filtro de requerimento: {numero_requerimento}")

    if not requerimentos_dirs:
        print("[LOCAL][WARN] Nenhum requerimento encontrado para análise.")
        return

    resultados = []
    inicio_execucao = datetime.now()

    for pasta_req in requerimentos_dirs:
        numero_extraido = _extrair_numero_do_nome_pasta(pasta_req.name) or pasta_req.name

        print("-" * 80)
        print(f"[LOCAL] Analisando requerimento: {numero_extraido}")
        print(f"[LOCAL] Pasta: {pasta_req}")

        resumo_existente = _carregar_json_se_existir(pasta_req / "resumo.json")
        req = _normalizar_req_local(pasta_req, resumo_existente)
        req = _aplicar_dados_sch_salvos_no_req(req, resumo_existente)

        resumo = dict(resumo_existente) if isinstance(resumo_existente, dict) else {}
        resumo["requerimento"] = req
        resumo["pasta_requerimento"] = str(pasta_req)
        resumo["inicio"] = datetime.now().isoformat()
        resumo["versao_script"] = VERSAO_SCRIPT
        resumo["modo_execucao"] = "analise_local"

        dados_certificado_sch = _obter_dados_certificado_sch_salvos(resumo_existente)
        tabela_sch = _obter_tabela_sch_salva(resumo_existente, req)

        if _tabela_tem_linhas(tabela_sch):
            req["tabela_tecnica_sch"] = tabela_sch
            resumo["tabela_tecnica_sch"] = tabela_sch

        resumo["dados_certificado_sch"] = dados_certificado_sch
        resumo["preenchimento_sch"] = resumo.get("preenchimento_sch") or {
            "minuta": False,
            "minuta_habilitada": False,
            "caracteristicas": False,
            "informacoes_adicionais": False,
        }

        try:
            pdf_cct = localizar_pdf_cct_do_requerimento(pasta_req, regras=None)
            resumo["pdf_cct"] = str(pdf_cct) if pdf_cct else ""

            if pdf_cct:
                print(f"[LOCAL] CCT localizado: {pdf_cct.name}")
                dados_pdf = parsear_certificado_pdf(pdf_cct) or {}
            else:
                print("[LOCAL][WARN] Nenhum CCT localizado para este requerimento.")
                dados_pdf = {}

            dados_pdf = _aplicar_datas_sch_no_dados_pdf(
                dados_pdf,
                dados_certificado_sch,
            )

            dados_pdf["nome_comercial_sch"] = req.get("nome_comercial", "")
            dados_pdf["modelo_sch_dados_gerais"] = req.get(
                "modelo_sch_dados_gerais",
                "",
            )

            resumo["dados_pdf"] = dados_pdf

            comparacao_datas = _comparar_datas_local(
                dados_certificado_sch=dados_certificado_sch,
                dados_pdf=dados_pdf,
            )
            resumo["comparacao_datas_sch_cct"] = comparacao_datas
            dados_pdf["comparacao_datas_sch_cct"] = comparacao_datas

            if comparacao_datas.get("status_geral") == "divergente":
                print("[LOCAL][WARN] Divergência nas datas entre SCH salvo e CCT.")
            elif comparacao_datas.get("status_geral") == "sem_dados_sch":
                print("[LOCAL][WARN] Sem dados SCH salvos para comparar datas.")
            else:
                print(f"[LOCAL] Datas: {comparacao_datas.get('status_geral')}")

            validade_cct = avaliar_validade_cct(dados_pdf)
            resumo["validade_cct"] = validade_cct

            if validade_cct.get("status") == "alerta":
                print(f"[LOCAL][WARN] CCT: {validade_cct.get('mensagem')}")
            else:
                print(f"[LOCAL] CCT: {validade_cct.get('mensagem')}")

            caracteristicas_local = _inferir_caracteristicas_secundarias_local(dados_pdf)
            resumo["caracteristicas_secundarias"] = caracteristicas_local[
                "caracteristicas_secundarias"
            ]
            resumo["texto_caracteristicas_secundarias"] = caracteristicas_local[
                "texto_caracteristicas_secundarias"
            ]
            dados_pdf["caracteristicas_secundarias"] = resumo["caracteristicas_secundarias"]
            dados_pdf["titulo_caracteristicas_secundarias"] = (
                resumo["caracteristicas_secundarias"].get("titulo", "")
                if isinstance(resumo["caracteristicas_secundarias"], dict)
                else ""
            )
            dados_pdf["texto_caracteristicas_secundarias"] = resumo[
                "texto_caracteristicas_secundarias"
            ]

            conferencia = _comparar_sch_x_cct_local(req, resumo, dados_pdf)
            resumo["conferencia_sch_cct"] = conferencia
            resumo["resumo_tabela_tecnica"] = _resumo_tabela_tecnica(conferencia)

            sar_minuta = _analisar_sar_local(dados_pdf)
            resumo["sar_minuta"] = sar_minuta
            resumo["minuta"] = {
                "preenchida": False,
                "salvo": False,
                "confirmado_apos_salvar": False,
                "status": sar_minuta.get("status", ""),
                "mensagem": sar_minuta.get("mensagem", ""),
                "frase": sar_minuta.get("frase", ""),
                "modo_execucao": "analise_local_sem_preenchimento",
            }

            req_relatorio = _completar_req_com_dados_pdf_para_relatorio(req, dados_pdf)
            resumo["requerimento"] = req_relatorio

            resumo["downloads_realizados"] = contar_arquivos_requerimento(pasta_req)

            analise_documental = analisar_requerimento(
                pasta_req=pasta_req,
                req=req_relatorio,
                resumo=resumo,
            )
            resumo["analise_documental"] = analise_documental

            salvar_json(pasta_req / "analise_requerimento.json", analise_documental)

            resumo["status"] = "analise_local_sucesso"
            resumo["fim"] = datetime.now().isoformat()

            _imprimir_resumo_requerimento_local(resumo)
            print(f"[LOCAL] Análise concluída com sucesso: {numero_extraido}")

        except Exception as e:
            resumo["status"] = "analise_local_erro"
            resumo["fim"] = datetime.now().isoformat()
            resumo["erro"] = {
                "tipo": type(e).__name__,
                "mensagem": str(e),
                "repr": repr(e),
            }

            print(
                f"[LOCAL][ERRO] Falha no requerimento {numero_extraido}: "
                f"{type(e).__name__}: {e}"
            )

        salvar_json(pasta_req / "resumo.json", resumo)
        resultados.append(resumo)

    fim_execucao = datetime.now()
    caminho_relatorio = pasta_base_real / "relatorio_execucao_local.json"
    resumo_final = _contar_statuses(resultados)

    salvar_json(
        caminho_relatorio,
        {
            "modo_execucao": "analise_local",
            "inicio_execucao": inicio_execucao.isoformat(),
            "fim_execucao": fim_execucao.isoformat(),
            "tempo_total_segundos": round(
                (fim_execucao - inicio_execucao).total_seconds(),
                2,
            ),
            **resumo_final,
            "itens": resultados,
            "versao_script": VERSAO_SCRIPT,
            "pasta_base": str(pasta_base_real),
            "pasta_escolhida": str(pasta_escolhida),
            "modo_detectado": info_pastas["modo"],
            "filtro_requerimento": numero_requerimento or "",
        },
    )

    print("=" * 80)
    print("[LOCAL] RESUMO DA ANÁLISE LOCAL")
    print("=" * 80)
    print(f"[LOCAL] Requerimentos processados: {resumo_final['total_processados']}")
    print(f"[LOCAL] Sucessos: {resumo_final['sucessos']}")
    print(f"[LOCAL] Erros: {resumo_final['erros']}")
    print(f"[LOCAL] Sem CCT: {resumo_final['sem_cct']}")
    print(f"[LOCAL] Sem dados SCH salvos: {resumo_final['sem_dados_sch']}")
    print(f"[LOCAL] Conferências divergentes: {resumo_final['conferencia_divergente']}")
    print(f"[LOCAL] Tabelas técnicas divergentes: {resumo_final['tabela_tecnica_divergente']}")
    print(f"[LOCAL] SAR aplicável: {resumo_final['sar_aplicavel']}")
    print(f"[LOCAL] SAR não aplicável: {resumo_final['sar_nao_aplicavel']}")
    print(f"[LOCAL] Relatório local salvo em: {caminho_relatorio}")

    caminho_req_report = gerar_req_report(
        pasta_saida=pasta_base_real,
        resultados=resultados,
        versao_script=VERSAO_SCRIPT,
        inicio_execucao=inicio_execucao,
        fim_execucao=fim_execucao,
    )

    print(f"[LOCAL] Pasta req_report gerada em: {caminho_req_report}")

    try:
        arquivos_req_report = sorted(
            p.name for p in Path(caminho_req_report).iterdir()
            if p.is_file()
        )

        print("[LOCAL] Arquivos gerados no req_report:")

        for arquivo in arquivos_req_report:
            print(f"[LOCAL] - {arquivo}")

    except Exception as e:
        print(f"[LOCAL][WARN] Não foi possível listar os arquivos do req_report: {e}")
