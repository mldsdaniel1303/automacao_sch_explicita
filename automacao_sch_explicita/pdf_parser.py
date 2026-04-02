from pathlib import Path
import re

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


OBS_RADIACAO_RESTRITA = (
    "Na instalação do produto devem ser observadas as condições de uso "
    "conforme estabelecido no Regulamento sobre Equipamentos de "
    "Radiocomunicação de Radiação Restrita."
)

OBS_PRODUTO_NAO_ACABADO = (
    "Produto não acabado, de uso interno, cuja integração em outros "
    "equipamentos passíveis de homologação pode requerer nova avaliação."
)


def _limpar_texto(valor):
    return re.sub(r"\s+", " ", (valor or "")).strip(" \t\r\n:-")


def _extrair_primeiro(texto, padroes):
    for padrao in padroes:
        m = re.search(padrao, texto, re.I)
        if m:
            valor = _limpar_texto(m.group(1))
            if valor:
                return valor
    return ""


def _classificar_observacao_cct(texto):
    texto_norm = (texto or "").lower()
    texto_norm = texto_norm.replace("não", "nao")
    texto_norm = texto_norm.replace("módulo", "modulo")
    texto_norm = re.sub(r"\s+", " ", texto_norm)

    sinais_produto_nao_acabado = [
        "produto nao acabado",
        "uso interno",
        "integração em outros equipamentos",
        "integracao em outros equipamentos",
        "pode requerer nova avaliação",
        "pode requerer nova avaliacao",
        "nova avaliação",
        "nova avaliacao",
    ]

    sinais_radiacao_restrita = [
        "na instalação do produto devem ser observadas as condições de uso",
        "na instalacao do produto devem ser observadas as condicoes de uso",
        "radiocomunicação de radiação restrita",
        "radiocomunicacao de radiacao restrita",
        "regulamento sobre equipamentos de radiocomunicação de radiação restrita",
        "regulamento sobre equipamentos de radiocomunicacao de radiacao restrita",
    ]

    achados_produto_nao_acabado = [s for s in sinais_produto_nao_acabado if s in texto_norm]
    achados_radiacao_restrita = [s for s in sinais_radiacao_restrita if s in texto_norm]

    if achados_produto_nao_acabado:
        return {
            "observacao_classificacao": "produto_nao_acabado",
            "observacao_texto": OBS_PRODUTO_NAO_ACABADO,
            "observacao_motivos": achados_produto_nao_acabado,
        }

    if achados_radiacao_restrita:
        return {
            "observacao_classificacao": "radiacao_restrita_padrao",
            "observacao_texto": OBS_RADIACAO_RESTRITA,
            "observacao_motivos": achados_radiacao_restrita,
        }

    return {
        "observacao_classificacao": "",
        "observacao_texto": "",
        "observacao_motivos": [],
    }


def parsear_certificado_pdf(caminho_pdf):
    resultado = {
        "numero_certificado": "",
        "homologacao": "",
        "modelo": "",
        "fabricante": "",
        "observacao_classificacao": "",
        "observacao_texto": "",
        "observacao_motivos": [],
    }

    if pdfplumber is None:
        print("[PDF][WARN] pdfplumber não instalado.")
        return resultado

    if not caminho_pdf:
        return resultado

    caminho_pdf = Path(caminho_pdf)
    if not caminho_pdf.exists():
        print(f"[PDF][WARN] Arquivo não encontrado: {caminho_pdf}")
        return resultado

    texto_total = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            texto_total.append(page.extract_text() or "")

    texto = "\n".join(texto_total)
    texto_limpo = _limpar_texto(texto)
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]

    padroes_certificado = [
        r"N[ÚU]MERO\s+DO\s+CERTIFICADO\s*[:\-]?\s*((?=[A-Z0-9./-]*\d)[A-Z0-9./-]{4,})",
        r"N[ÚU]MERO\s+DE\s+CERTIFICADO\s*[:\-]?\s*((?=[A-Z0-9./-]*\d)[A-Z0-9./-]{4,})",
        r"CERTIFICADO(?:\s+DE\s+CONFORMIDADE\s+T[ÉE]CNICA)?\s*(?:N[ºO°.]?|N[ÚU]MERO)?\s*[:\-]?\s*((?=[A-Z0-9./-]*\d)[A-Z0-9./-]{4,})",
        r"\b((?=\d)[A-Z0-9]{3,6}-\d{2}-\d{3,10})\b",
    ]

    padroes_homologacao = [
        r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]?\s*([0-9./-]{4,})",
        r"N[ÚU]MERO\s+DE\s+HOMOLOGA[CÇ][AÃ]O\s*[:\-]?\s*([0-9./-]{4,})",
    ]

    resultado["numero_certificado"] = _extrair_primeiro(texto_limpo, padroes_certificado)
    resultado["homologacao"] = _extrair_primeiro(texto_limpo, padroes_homologacao)

    for linha in linhas:
        if not resultado["modelo"]:
            m = re.search(r"MODELO\s*[:\-]\s*(.+)$", linha, re.I)
            if m:
                resultado["modelo"] = _limpar_texto(m.group(1))

        if not resultado["fabricante"]:
            m = re.search(r"FABRICANTE\s*[:\-]\s*(.+)$", linha, re.I)
            if m:
                resultado["fabricante"] = _limpar_texto(m.group(1))

        if not resultado["homologacao"]:
            m = re.search(r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]\s*([0-9./-]{4,})", linha, re.I)
            if m:
                resultado["homologacao"] = _limpar_texto(m.group(1))

        if not resultado["numero_certificado"]:
            m = re.search(r"\b((?=\d)[A-Z0-9]{3,6}-\d{2}-\d{3,10})\b", linha.upper(), re.I)
            if m:
                resultado["numero_certificado"] = _limpar_texto(m.group(1))

    if not resultado["numero_certificado"]:
        m = re.search(r"\b\d{3,6}-\d{2}(?:-\d{2,10})?\b", caminho_pdf.stem.upper())
        if m:
            resultado["numero_certificado"] = m.group(0)

    obs = _classificar_observacao_cct(texto)
    resultado["observacao_classificacao"] = obs["observacao_classificacao"]
    resultado["observacao_texto"] = obs["observacao_texto"]
    resultado["observacao_motivos"] = obs["observacao_motivos"]

    print(f"[PDF] Dados extraídos de {caminho_pdf.name}: {resultado}")
    return resultado