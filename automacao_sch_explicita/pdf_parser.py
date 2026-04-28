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


def _normalizar_texto(valor):
    texto = _limpar_texto(valor).lower()
    texto = texto.replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
    texto = texto.replace("é", "e").replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    texto = texto.replace("ú", "u")
    texto = texto.replace("ç", "c")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _extrair_primeiro(texto, padroes):
    for padrao in padroes:
        m = re.search(padrao, texto, re.I | re.S)
        if m:
            valor = _limpar_texto(m.group(1))
            if valor:
                return valor
    return ""


def _extrair_valor_por_rotulo(linhas, rotulos):
    rotulos_norm = [_normalizar_texto(r) for r in rotulos]

    for idx, linha in enumerate(linhas):
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        for rotulo, rotulo_norm in zip(rotulos, rotulos_norm):
            m = re.search(
                rf"^\s*{re.escape(rotulo)}\s*[:\-]?\s*(.+?)\s*$",
                linha_limpa,
                re.I,
            )
            if m:
                valor = _limpar_texto(m.group(1))
                if valor:
                    return valor

            if linha_norm == rotulo_norm:
                if idx + 1 < len(linhas):
                    prox = _limpar_texto(linhas[idx + 1])
                    if prox:
                        return prox

            m2 = re.search(
                rf"{re.escape(rotulo)}\s*[:\-]?\s*(.+?)\s*$",
                linha_limpa,
                re.I,
            )
            if m2:
                valor = _limpar_texto(m2.group(1))
                if valor and _normalizar_texto(valor) != rotulo_norm:
                    return valor

    return ""


def _limpar_ocd(valor):
    valor = _limpar_texto(valor)

    if not valor:
        return ""

    # remove prefixos ruins que às vezes entram na captura
    valor = re.sub(r"^(pela|pelo|da|do|de)\s+", "", valor, flags=re.I).strip()

    ruins = {
        "pela",
        "pelo",
        "da",
        "do",
        "de",
        "certificado",
        "certificacao",
        "organismo",
    }

    if _normalizar_texto(valor) in ruins:
        return ""

    # corta quando vier algo claramente explicativo demais
    valor = re.split(r"\b(certifica|certifica|atesta|declara|informa)\b", valor, flags=re.I)[0].strip(" -:;,")

    if len(valor) < 3:
        return ""

    return valor


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


def _limpar_celula_tabela(valor):
    return _limpar_texto(str(valor or "").replace("\n", " "))


def _limpar_tabela_bruta(tabela):
    linhas = []
    for linha in tabela or []:
        limpa = [_limpar_celula_tabela(cel) for cel in (linha or [])]
        if any(c for c in limpa):
            linhas.append(limpa)
    return linhas


def _pontuacao_cabecalho_tabela(cabecalho):
    texto = " | ".join(_normalizar_texto(c) for c in (cabecalho or []))
    score = 0

    sinais = [
        "faixa",
        "frequencia",
        "potencia",
        "emissao",
        "tecnologia",
        "modulacao",
        "taxa maxima de transmissao",
    ]

    for s in sinais:
        if s in texto:
            score += 1

    return score


def _ajustar_tabela_extraida(cabecalho, linhas):
    cabecalho = [c for c in cabecalho or []]
    linhas = [list(l) for l in (linhas or [])]

    total_colunas = max(
        [len(cabecalho)] + [len(l) for l in linhas] + [0]
    )
    if total_colunas == 0:
        return {"cabecalho": [], "linhas": []}

    cabecalho = cabecalho + [""] * (total_colunas - len(cabecalho))
    linhas = [l + [""] * (total_colunas - len(l)) for l in linhas]

    # remove colunas totalmente vazias
    manter = []
    for idx in range(total_colunas):
        valores = [cabecalho[idx]] + [linha[idx] for linha in linhas]
        if any(_limpar_texto(v) for v in valores):
            manter.append(idx)

    cabecalho_final = [cabecalho[idx] for idx in manter]
    linhas_finais = [[linha[idx] for idx in manter] for linha in linhas]

    return {
        "cabecalho": cabecalho_final,
        "linhas": linhas_finais,
    }


def _extrair_tabela_tecnica_cct_de_tabelas(tabelas_brutas):
    melhor = None
    melhor_score = -1
    melhor_qtd_linhas = -1

    for tabela in tabelas_brutas:
        linhas = _limpar_tabela_bruta(tabela)
        if len(linhas) < 2:
            continue

        for idx_cab in range(min(3, len(linhas))):
            cabecalho = linhas[idx_cab]
            score = _pontuacao_cabecalho_tabela(cabecalho)

            if score < 2:
                continue

            corpo = linhas[idx_cab + 1 :]
            corpo = [l for l in corpo if any(_limpar_texto(c) for c in l)]

            if not corpo:
                continue

            tabela_ajustada = _ajustar_tabela_extraida(cabecalho, corpo)

            if (
                score > melhor_score
                or (score == melhor_score and len(tabela_ajustada["linhas"]) > melhor_qtd_linhas)
            ):
                melhor = tabela_ajustada
                melhor_score = score
                melhor_qtd_linhas = len(tabela_ajustada["linhas"])

    if melhor is None:
        return {"cabecalho": [], "linhas": []}

    return melhor


def _inferir_tipo_produto(texto, valor_extraido=""):
    if valor_extraido:
        return valor_extraido

    texto_norm = _normalizar_texto(texto)

    if "radiacao restrita" in texto_norm:
        return "Transceptor de Radiação Restrita"

    return ""


def parsear_certificado_pdf(caminho_pdf):
    resultado = {
        "numero_certificado": "",
        "homologacao": "",
        "modelo": "",
        "fabricante": "",
        "tipo_produto": "",
        "ocd": "",
        "tabela_tecnica_cct": {
            "cabecalho": [],
            "linhas": [],
        },
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
    tabelas_brutas = []

    with pdfplumber.open(caminho_pdf) as pdf:
        for page in pdf.pages:
            texto_total.append(page.extract_text() or "")
            try:
                tabelas_brutas.extend(page.extract_tables() or [])
            except Exception:
                pass

    texto = "\n".join(texto_total)
    texto_limpo = _limpar_texto(texto)
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]

    padroes_certificado_contextuais = [
        r"(?:n[º°o]\s*|n[úu]mero\s+)(?:do|de)\s+certificado(?:\s*/\s*certificate\s*no\.?)?\s*[:\-]?\s*([A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4})",
        r"(?:certificate\s*no\.?)\s*[:\-]?\s*([A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4})",
        r"(?:certificado\s+de\s+conformidade\s+t[ée]cnica).*?(?:n[º°o]\s*|n[úu]mero\s+)?(?:do|de)?\s*certificado(?:\s*/\s*certificate\s*no\.?)?\s*[:\-]?\s*([A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4})",
        r"(?:certificado).*?(?:no\.?|n[º°o]|n[úu]mero)?\s*[:\-]?\s*([A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4})",
    ]

    padroes_certificado_genericos = [
        r"\b([A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4})\b",
    ]

    padroes_homologacao = [
        r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]?\s*([0-9./-]{4,})",
        r"N[ÚU]MERO\s+DE\s+HOMOLOGA[CÇ][AÃ]O\s*[:\-]?\s*([0-9./-]{4,})",
    ]

    padroes_ocd = [
        r"\bOCD\b\s*[:\-]?\s*([^\n]{3,80})",
        r"Organismo\s+de\s+Certifica(?:ç|c)[aã]o(?:\s+Designado)?\s*[:\-]?\s*([^\n]{3,80})",
    ]

    resultado["numero_certificado"] = _extrair_primeiro(texto_limpo, padroes_certificado_contextuais)

    if not resultado["numero_certificado"]:
        for linha in linhas:
            valor = _extrair_primeiro(linha, padroes_certificado_contextuais)
            if valor:
                resultado["numero_certificado"] = valor
                break

    if not resultado["numero_certificado"]:
        resultado["numero_certificado"] = _extrair_primeiro(texto_limpo, padroes_certificado_genericos)

    resultado["homologacao"] = _extrair_primeiro(texto_limpo, padroes_homologacao)

    ocd_bruto = _extrair_primeiro(texto_limpo, padroes_ocd)
    resultado["ocd"] = _limpar_ocd(ocd_bruto)

    resultado["modelo"] = _extrair_valor_por_rotulo(
        linhas,
        ["MODELO", "MODEL"],
    )

    resultado["fabricante"] = _extrair_valor_por_rotulo(
        linhas,
        ["FABRICANTE", "MANUFACTURER"],
    )

    resultado["tipo_produto"] = _extrair_valor_por_rotulo(
        linhas,
        [
            "TIPO DE PRODUTO",
            "TIPO DO PRODUTO",
            "DESCRIÇÃO DO PRODUTO",
            "DESCRICAO DO PRODUTO",
            "PRODUTO",
        ],
    )

    if not resultado["homologacao"]:
        for linha in linhas:
            m = re.search(r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]\s*([0-9./-]{4,})", linha, re.I)
            if m:
                resultado["homologacao"] = _limpar_texto(m.group(1))
                break

    if not resultado["ocd"]:
        for linha in linhas:
            m = re.search(r"\bOCD\b\s*[:\-]?\s*([^\n]{3,80})", linha, re.I)
            if m:
                valor = _limpar_ocd(m.group(1))
                if valor:
                    resultado["ocd"] = valor
                    break

    if not resultado["numero_certificado"]:
        m = re.search(r"\b[A-Z0-9./]{2,20}(?:-[A-Z0-9./]{1,20}){1,4}\b", caminho_pdf.stem.upper())
        if m:
            resultado["numero_certificado"] = m.group(0)

    obs = _classificar_observacao_cct(texto)
    resultado["observacao_classificacao"] = obs["observacao_classificacao"]
    resultado["observacao_texto"] = obs["observacao_texto"]
    resultado["observacao_motivos"] = obs["observacao_motivos"]

    resultado["tipo_produto"] = _inferir_tipo_produto(
        texto,
        resultado["tipo_produto"],
    )

    resultado["tabela_tecnica_cct"] = _extrair_tabela_tecnica_cct_de_tabelas(tabelas_brutas)

    print(f"[PDF] Dados extraídos de {caminho_pdf.name}: {resultado}")
    return resultado