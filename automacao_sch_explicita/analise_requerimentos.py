import re
import time
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


KEYWORDS = {
    "bluetooth": [r"\bbluetooth\b"],
    "bateria": [r"\bbateria\b", r"\bbattery\b"],
    "wifi": [r"\bwi[\-\s]?fi\b", r"\bwifi\b", r"\b802\.11\b"],
    "nfc": [r"\bnfc\b"],
    "lte": [r"\blte\b", r"\b4g\b"],
    "5g": [r"\b5g\b", r"\bnr\b"],
    "gsm": [r"\bgsm\b"],
    "antena": [r"\bantena\b", r"\bantenna\b"],
    "modulo": [r"\bm[oó]dulo\b", r"\bmodule\b", r"\brf module\b"],
    "uso interno": [r"\buso interno\b", r"\binternal use\b"],
    "oem": [r"\boem\b"],
    "transceptor": [r"\btransceptor\b", r"\btransceiver\b"],
    "radiação restrita": [r"radia[cç][aã]o restrita", r"radia[cç][aã]o de radia[cç][aã]o restrita"],
    "bateria_litio": [r"l[ií]tio", r"li-ion", r"li ion", r"li-poly", r"lithium"],
    "produto não acabado": [r"produto n[aã]o acabado", r"not finished product", r"end product"],
}

NORMAS_RAD_RESTRITA = [
    "Ato nº 1120, de 19 de fevereiro de 2018",
    "Ato nº 14448, de 04 de dezembro de 2017",
    "Ato nº 17087, de 19 de dezembro de 2022",
    "Ato nº 77, de 05 de janeiro de 2021",
    "Resolução nº 680, de 27 de junho de 2017",
]


def _normalizar_texto(texto):
    texto = texto or ""
    texto = texto.replace("\x00", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _extrair_texto_pdf(caminho_pdf):
    if pdfplumber is None:
        return ""

    partes = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for page in pdf.pages:
                partes.append(page.extract_text() or "")
    except Exception:
        return ""

    return "\n".join(partes)


def _contar_keywords(texto_total):
    contagens = {}
    texto = texto_total or ""
    for chave, padroes in KEYWORDS.items():
        total = 0
        for padrao in padroes:
            total += len(re.findall(padrao, texto, flags=re.I))
        if total > 0:
            contagens[chave] = total
    return dict(sorted(contagens.items(), key=lambda kv: (-kv[1], kv[0])))


def _inferir_equipamentos(req, texto_total):
    universo = f"{req.get('tipo_produto', '')} {texto_total}".lower()
    equipamentos = []

    if (
        "radiação restrita" in universo
        or "radiacao restrita" in universo
        or "bluetooth" in universo
        or "wi-fi" in universo
        or "wifi" in universo
        or "nfc" in universo
    ):
        equipamentos.append("Equipamentos de Radiocomunicação de Radiação Restrita")

    if "transceptor" in universo or "transceiver" in universo:
        equipamentos.append("Transceptor de Radiação Restrita")

    if not equipamentos and req.get("tipo_produto"):
        equipamentos.append(req.get("tipo_produto"))

    return equipamentos


def _normas_aplicaveis(equipamentos):
    if any("Radiação Restrita" in eq or "Radiacao Restrita" in eq for eq in equipamentos):
        motivadores = "; ".join(equipamentos) if equipamentos else "Equipamentos identificados no requerimento"
        return [
            {"status": "ok", "norma": norma, "motivadores": motivadores}
            for norma in NORMAS_RAD_RESTRITA
        ]
    return []


def _detectar_presenca(texto, padroes):
    for padrao in padroes:
        if re.search(padrao, texto, flags=re.I):
            return True
    return False


def _categoria_do_arquivo(caminho_pdf, pasta_req):
    try:
        relativo = Path(caminho_pdf).relative_to(Path(pasta_req))
        if len(relativo.parts) >= 2:
            return relativo.parts[0]
    except Exception:
        pass
    return "Sem categoria"


def _analisar_relatorio_ensaio(caminho_pdf, texto):
    return {
        "documento": caminho_pdf.stem,
        "lab": _detectar_presenca(texto, [r"\blaborat[oó]rio\b", r"\blab\b"]),
        "sol": _detectar_presenca(texto, [r"\bsolicitante\b", r"\bapplicant\b"]),
        "fab": _detectar_presenca(texto, [r"\bfabricante\b", r"\bmanufacturer\b"]),
        "mod": _detectar_presenca(texto, [r"\bmodelo\b", r"\bmodel\b"]),
    }


def _extrair_ocd(req, textos):
    universo = "\n".join(textos)
    m = re.search(
        r"(?:OCD|Organismo de Certifica[cç][aã]o Designado)\s*[:\-]?\s*(.+)",
        universo,
        flags=re.I,
    )
    if m:
        return _normalizar_texto(m.group(1)).split("\n")[0][:200]

    return req.get("solicitante", "") or ""


def _montar_alertas(req, dados_pdf, qtd_pdfs, relatorios_ensaio, palavras):
    alertas = []

    if qtd_pdfs == 0:
        alertas.append("Nenhum PDF encontrado para análise.")
    if not dados_pdf.get("numero_certificado"):
        alertas.append("Número do certificado não identificado no CCT.")
    if not relatorios_ensaio:
        alertas.append("Nenhum Relatório de Ensaio encontrado.")
    if palavras.get("produto não acabado") or palavras.get("modulo") or palavras.get("uso interno"):
        alertas.append("Há indícios de produto não acabado / módulo / uso interno.")
    if palavras.get("bluetooth", 0) == 0 and "Radiação Restrita" in (req.get("tipo_produto") or ""):
        alertas.append("Nenhuma ocorrência de 'bluetooth' encontrada no conjunto analisado.")
    if relatorios_ensaio and all(not r["fab"] for r in relatorios_ensaio):
        alertas.append("Fabricante ausente em todos os relatórios de ensaio.")
    if relatorios_ensaio and all(not r["mod"] for r in relatorios_ensaio):
        alertas.append("Modelo ausente em todos os relatórios de ensaio.")

    return alertas


def analisar_requerimento(pasta_req, req, resumo=None):
    inicio = time.perf_counter()
    pasta_req = Path(pasta_req)

    pdfs = sorted(pasta_req.rglob("*.pdf"))
    textos_por_pdf = {}
    texto_total_partes = []

    for pdf in pdfs:
        texto = _extrair_texto_pdf(pdf)
        textos_por_pdf[pdf] = texto
        texto_total_partes.append(texto)

    texto_total = "\n".join(texto_total_partes)
    palavras = _contar_keywords(texto_total)
    equipamentos = _inferir_equipamentos(req, texto_total)
    normas = _normas_aplicaveis(equipamentos)

    relatorios_ensaio = []
    outros_documentos = []

    for pdf in pdfs:
        texto = textos_por_pdf.get(pdf, "")
        categoria = _categoria_do_arquivo(pdf, pasta_req)
        nome = pdf.stem

        if "ensaio" in nome.lower() or "ensaio" in categoria.lower():
            relatorios_ensaio.append(_analisar_relatorio_ensaio(pdf, texto))
        else:
            outros_documentos.append(
                {
                    "documento": nome,
                    "categoria": categoria,
                }
            )

    ocd = _extrair_ocd(req, list(textos_por_pdf.values()))
    dados_pdf = (resumo or {}).get("dados_pdf", {}) if resumo else {}

    alertas = _montar_alertas(
        req=req,
        dados_pdf=dados_pdf,
        qtd_pdfs=len(pdfs),
        relatorios_ensaio=relatorios_ensaio,
        palavras=palavras,
    )

    fim = time.perf_counter()

    return {
        "requerimento": req.get("requerimento", ""),
        "tempo_analise_segundos": round(fim - inicio, 6),
        "qtd_pdfs": len(pdfs),
        "ocd": ocd,
        "equipamentos": equipamentos,
        "palavras_chave": {
            "encontradas": palavras,
            "ausentes": [k for k in KEYWORDS.keys() if k not in palavras],
        },
        "normas_aplicaveis": normas,
        "documentos_processados": {
            "relatorios_ensaio": relatorios_ensaio,
            "outros_documentos": outros_documentos,
        },
        "alertas": alertas,
    }