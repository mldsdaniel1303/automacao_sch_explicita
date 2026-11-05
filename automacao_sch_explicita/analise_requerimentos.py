import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from utils import carregar_regras

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
    "radiação restrita": [
        r"radia[cç][aã]o restrita",
        r"radia[cç][aã]o de radia[cç][aã]o restrita",
    ],
    "bateria_litio": [r"l[ií]tio", r"li-ion", r"li ion", r"li-poly", r"lithium"],
    "produto não acabado": [
        r"produto n[aã]o acabado",
        r"not finished product",
        r"end product",
    ],
}

NORMAS_RAD_RESTRITA_BASE = [
    "Ato nº 1120, de 19 de fevereiro de 2018",
    "Ato nº 14448, de 04 de dezembro de 2017",
    "Ato nº 17087, de 19 de dezembro de 2022",
    "Resolução nº 680, de 27 de junho de 2017",
]

NORMA_ATO_77 = "Ato nº 77, de 05 de janeiro de 2021"

NORMA_ATO_1630 = "Ato nº 1630"

TERMOS_ATO_77_FORTES = [
    r"\bwi[\-\s]?fi\b",
    r"\bwifi\b",
    r"\b802\.11\b",
    r"\bwlan\b",
    r"\bofdm\b",
    r"\bofdma\b",
    r"\bdsss\b",
]


def _normalizar_texto(texto):
    texto = texto or ""
    texto = texto.replace("\x00", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _remover_acentos(texto):
    texto = str(texto or "")
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(ch)
    )


def _normalizar_comparacao(texto):
    texto = _normalizar_texto(texto)
    texto = _remover_acentos(texto).lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto



def _texto_tem_ato_77_aplicavel(texto):
    texto = texto or ""

    for padrao in TERMOS_ATO_77_FORTES:
        if re.search(padrao, texto, flags=re.I):
            return True

    return False


def _texto_indica_sar_nao_aplicavel(texto):
    texto_norm = _normalizar_comparacao(texto)

    termos = [
        "ensaio de sar nao aplicavel",
        "sar nao aplicavel",
        "ensaio sar nao aplicavel",
        "nao se aplica sar",
        "sar nao se aplica",
    ]

    return any(termo in texto_norm for termo in termos)


def _texto_tem_dados_sar(texto):
    texto_norm = _normalizar_comparacao(texto)

    termos = [
        "sar cabeca",
        "sar corpo",
        "sar head",
        "sar body",
        "valor sar",
        "limite sar",
        "taxa de absorcao especifica",
        "w kg",
        "w/kg",
    ]

    return any(termo in texto_norm for termo in termos)


def _dados_pdf_tem_coluna_sar(dados_pdf):
    dados_pdf = dados_pdf or {}
    tabela = dados_pdf.get("tabela_tecnica_cct", {}) or {}
    cabecalho = tabela.get("cabecalho", []) or []

    texto_cabecalho = _normalizar_comparacao(
        " ".join(str(c or "") for c in cabecalho)
    )

    termos = [
        "sar",
        "sar cabeca",
        "sar corpo",
        "sar head",
        "sar body",
        "taxa de absorcao especifica",
    ]

    return any(termo in texto_cabecalho for termo in termos)


def _dados_pdf_tem_valor_sar(dados_pdf):
    dados_pdf = dados_pdf or {}
    tabela = dados_pdf.get("tabela_tecnica_cct", {}) or {}
    cabecalho = tabela.get("cabecalho", []) or []
    linhas = tabela.get("linhas", []) or []

    indices_sar = []

    for i, col in enumerate(cabecalho):
        col_norm = _normalizar_comparacao(col)
        if "sar" in col_norm or "taxa de absorcao especifica" in col_norm:
            indices_sar.append(i)

    if not indices_sar:
        return False

    for linha in linhas:
        for idx in indices_sar:
            if idx < len(linha):
                valor = str(linha[idx] or "").strip()
                valor_norm = _normalizar_comparacao(valor)

                if valor_norm in {"", "-", "n a", "n/a", "nao aplicavel", "nao se aplica"}:
                    continue

                if re.search(r"\d+[,.]?\d*", valor):
                    return True

    return False


def _tem_sar_no_cct(texto_cct, dados_pdf=None):
    if _dados_pdf_tem_valor_sar(dados_pdf):
        return True

    return _texto_tem_dados_sar(texto_cct)



def _texto_tem_norma(texto, numero):
    texto_norm = _normalizar_comparacao(texto)
    numero = str(numero or "").strip()

    if not texto_norm or not numero:
        return False

    padroes = [
        rf"\bato\s*(?:n|no|numero)?\s*{re.escape(numero)}\b",
        rf"\bresolucao\s*(?:n|no|numero)?\s*{re.escape(numero)}\b",
    ]

    for padrao in padroes:
        if re.search(padrao, texto_norm, flags=re.I):
            return True

    return False



def _valor_generico_ou_invalido(valor):
    texto = _normalizar_comparacao(valor)

    if not texto:
        return True

    genericos = {
        "nao identificado",
        "nao informado",
        "sem numero",
        "sem modelo",
        "modelo",
        "model",
        "produto",
        "product",
        "type of product",
        "-",
        "--",
        "---",
        "–",
        "—",
    }

    if texto in genericos:
        return True

    if len(texto) < 3:
        return True

    return False


def _valores_referencia(*valores):
    saida = []
    vistos = set()

    for valor in valores:
        if valor is None:
            continue

        valor = str(valor).strip()

        if _valor_generico_ou_invalido(valor):
            continue

        chave = _normalizar_comparacao(valor)

        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(valor)

    return saida


def _tokens_relevantes(valor):
    texto = _normalizar_comparacao(valor)

    ignorar = {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "a",
        "o",
        "as",
        "os",
        "ltda",
        "ltd",
        "sa",
        "s",
        "a",
        "inc",
        "co",
        "company",
        "tecnologia",
        "digital",
        "industria",
        "comercio",
        "comercial",
        "importacao",
        "exportacao",
        "detentor",
        "tecnologia",
    }

    tokens = [
        t for t in texto.split()
        if len(t) >= 3 and t not in ignorar
    ]

    return tokens


def _valor_aparece_no_texto(texto, valor, min_cobertura=0.75):
    texto_norm = _normalizar_comparacao(texto)
    valor_norm = _normalizar_comparacao(valor)

    if not texto_norm or not valor_norm:
        return False

    if valor_norm in texto_norm:
        return True

    tokens = _tokens_relevantes(valor)

    if not tokens:
        return False

    encontrados = sum(1 for token in tokens if token in texto_norm)
    cobertura = encontrados / max(len(tokens), 1)

    if cobertura >= min_cobertura:
        return True

    # Último recurso: similaridade de strings para nomes com pequenas variações.
    # Evita exigir igualdade exata entre "Polyvox Tecnologia Digital Ltda" e "Polyvox".
    for trecho in re.findall(r".{0,80}", texto_norm):
        if not trecho.strip():
            continue

        score = SequenceMatcher(None, valor_norm, trecho.strip()).ratio()
        if score >= 0.88:
            return True

    return False


def _avaliar_valor_esperado_no_texto(texto, valor, min_cobertura=0.75):
    """
    Retorna:
    - C quando o valor esperado aparece de forma clara no texto;
    - REVISAR quando há indício de similaridade, mas não igualdade segura;
    - NC quando não há evidência suficiente.
    """
    texto_norm = _normalizar_comparacao(texto)
    valor_norm = _normalizar_comparacao(valor)

    if not texto_norm or not valor_norm:
        return {
            "status": "NC",
            "evidencia": "",
            "motivo": "Texto ou valor esperado vazio.",
        }

    # Igualdade clara: aparece como substring normalizada.
    # Exemplo: "Polyvox Tecnologia Digital Ltda" no relatório.
    if valor_norm in texto_norm:
        return {
            "status": "C",
            "evidencia": _extrair_evidencia_por_valor(texto, valor),
            "motivo": "Valor esperado encontrado de forma clara no relatório.",
        }

    tokens = _tokens_relevantes(valor)

    if not tokens:
        return {
            "status": "NC",
            "evidencia": "",
            "motivo": "Valor esperado sem tokens relevantes para comparação.",
        }

    encontrados = sum(1 for token in tokens if token in texto_norm)
    cobertura = encontrados / max(len(tokens), 1)

    if cobertura >= min_cobertura:
        return {
            "status": "REVISAR",
            "evidencia": _extrair_evidencia_por_valor(texto, valor),
            "motivo": (
                "Foram encontrados termos parecidos com o valor esperado, "
                "mas não há igualdade segura. Revisar manualmente."
            ),
        }

    # Similaridade textual: também vai para REVISAR, não para C.
    for trecho in re.findall(r".{1,80}", texto_norm):
        trecho = trecho.strip()
        if not trecho:
            continue

        score = SequenceMatcher(None, valor_norm, trecho).ratio()

        if score >= 0.88:
            return {
                "status": "REVISAR",
                "evidencia": trecho,
                "motivo": (
                    "Há similaridade textual com o valor esperado, "
                    "mas a regra atual manda revisar pequenas diferenças manualmente."
                ),
            }

    return {
        "status": "NC",
        "evidencia": "",
        "motivo": "Valor esperado não localizado no relatório.",
    }



def _extrair_evidencia_por_padroes(texto, padroes, janela=120):
    texto = texto or ""

    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.I)
        if not m:
            continue

        ini = max(m.start() - janela, 0)
        fim = min(m.end() + janela, len(texto))
        return _normalizar_texto(texto[ini:fim])

    return ""


def _extrair_evidencia_por_valor(texto, valor, janela=120):
    texto = texto or ""
    valor = str(valor or "").strip()

    if not texto or not valor:
        return ""

    m = re.search(re.escape(valor), texto, flags=re.I)
    if m:
        ini = max(m.start() - janela, 0)
        fim = min(m.end() + janela, len(texto))
        return _normalizar_texto(texto[ini:fim])

    tokens = _tokens_relevantes(valor)

    for token in tokens:
        m = re.search(re.escape(token), texto, flags=re.I)
        if m:
            ini = max(m.start() - janela, 0)
            fim = min(m.end() + janela, len(texto))
            return _normalizar_texto(texto[ini:fim])

    return ""


def _resultado_conferencia(status, aplicavel, conforme, motivo, evidencia="", esperado=""):
    return {
        "status": status,
        "aplicavel": aplicavel,
        "conforme": conforme,
        "motivo": motivo,
        "evidencia": evidencia,
        "esperado": esperado,
    }


def _avaliar_lab_relatorio(texto):
    texto_norm = _normalizar_comparacao(texto)

    if not texto_norm:
        return _resultado_conferencia(
            status="N/A",
            aplicavel=None,
            conforme=None,
            motivo="Não foi possível extrair texto do relatório para avaliar o laboratório.",
        )

    padroes_lab = [
        r"\blaborat[oó]rio\b",
        r"\blab\b",
        r"\btest laboratory\b",
        r"\blaboratory\b",
        r"\bensaio realizado por\b",
    ]

    evidencia = _extrair_evidencia_por_padroes(texto, padroes_lab)

    if evidencia:
        return _resultado_conferencia(
            status="C",
            aplicavel=True,
            conforme=True,
            motivo="Identificação de laboratório encontrada no relatório.",
            evidencia=evidencia,
        )

    return _resultado_conferencia(
        status="NC",
        aplicavel=True,
        conforme=False,
        motivo="Relatório de ensaio sem identificação clara de laboratório.",
    )


def _avaliar_campo_relatorio(texto, nome_campo, valores_esperados, padroes_rotulo):
    texto_norm = _normalizar_comparacao(texto)

    if not texto_norm:
        return _resultado_conferencia(
            status="N/A",
            aplicavel=None,
            conforme=None,
            motivo=f"Não foi possível extrair texto do relatório para avaliar {nome_campo}.",
        )

    valores_esperados = _valores_referencia(*valores_esperados)

    if not valores_esperados:
        evidencia_rotulo = _extrair_evidencia_por_padroes(texto, padroes_rotulo)

        if evidencia_rotulo:
            return _resultado_conferencia(
                status="N/A",
                aplicavel=None,
                conforme=None,
                motivo=(
                    f"O campo {nome_campo} aparece no relatório, "
                    "mas não havia valor de referência confiável para comparar."
                ),
                evidencia=evidencia_rotulo,
            )

        return _resultado_conferencia(
            status="N/A",
            aplicavel=None,
            conforme=None,
            motivo=f"Sem valor de referência confiável para avaliar {nome_campo}.",
        )

    candidatos_revisar = []

    for esperado in valores_esperados:
        avaliacao = _avaliar_valor_esperado_no_texto(texto, esperado)

        if avaliacao["status"] == "C":
            return _resultado_conferencia(
                status="C",
                aplicavel=True,
                conforme=True,
                motivo=f"{nome_campo} compatível encontrado no relatório.",
                evidencia=avaliacao.get("evidencia", ""),
                esperado=esperado,
            )

        if avaliacao["status"] == "REVISAR":
            candidatos_revisar.append(
                {
                    "esperado": esperado,
                    "evidencia": avaliacao.get("evidencia", ""),
                    "motivo": avaliacao.get("motivo", ""),
                }
            )

    if candidatos_revisar:
        primeiro = candidatos_revisar[0]

        return _resultado_conferencia(
            status="REVISAR",
            aplicavel=True,
            conforme=None,
            motivo=(
                f"{nome_campo} possui possível correspondência no relatório, "
                "mas há diferença de escrita. Revisar manualmente."
            ),
            evidencia=primeiro.get("evidencia", ""),
            esperado=primeiro.get("esperado", ""),
        )

    evidencia_rotulo = _extrair_evidencia_por_padroes(texto, padroes_rotulo)

    # Regra específica confirmada: modelo divergente/ausente deve gerar alerta para revisão manual.
    if _normalizar_comparacao(nome_campo) == "modelo":
        return _resultado_conferencia(
            status="REVISAR",
            aplicavel=True,
            conforme=None,
            motivo="Modelo esperado não localizado de forma segura no relatório. Revisar manualmente.",
            evidencia=evidencia_rotulo,
            esperado=" | ".join(valores_esperados),
        )

    if evidencia_rotulo:
        motivo = (
            f"O relatório possui campo relacionado a {nome_campo}, "
            "mas o valor esperado não foi localizado."
        )
    else:
        motivo = f"{nome_campo} esperado não localizado no relatório."

    return _resultado_conferencia(
        status="NC",
        aplicavel=True,
        conforme=False,
        motivo=motivo,
        evidencia=evidencia_rotulo,
        esperado=" | ".join(valores_esperados),
    )


def _status_item_relatorio(item, campo):
    valor = item.get(campo)

    if isinstance(valor, dict):
        return valor.get("status", "N/A")

    if valor is True:
        return "C"

    if valor is False:
        return "NC"

    return "N/A"

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


def _categoria_do_arquivo(caminho_pdf, pasta_req):
    try:
        relativo = Path(caminho_pdf).relative_to(Path(pasta_req))
        if len(relativo.parts) >= 2:
            return relativo.parts[0]
    except Exception:
        pass
    return "Sem categoria"


def _analisar_relatorio_ensaio(caminho_pdf, texto, req=None, dados_pdf=None):
    req = req or {}
    dados_pdf = dados_pdf or {}

    solicitantes_esperados = _valores_referencia(
        req.get("solicitante", ""),
        dados_pdf.get("solicitante", ""),
        dados_pdf.get("applicant", ""),
    )

    fabricantes_esperados = _valores_referencia(
        dados_pdf.get("fabricante", ""),
        req.get("fabricante", ""),
        dados_pdf.get("detentor_tecnologia", ""),
        dados_pdf.get("detentor_da_tecnologia", ""),
    )

    modelos_esperados = _valores_referencia(
        dados_pdf.get("modelo", ""),
        req.get("modelo", ""),
    )

    return {
        "documento": caminho_pdf.stem,
        "lab": _avaliar_lab_relatorio(texto),
        "sol": _avaliar_campo_relatorio(
            texto=texto,
            nome_campo="solicitante",
            valores_esperados=solicitantes_esperados,
            padroes_rotulo=[
                r"\bsolicitante\b",
                r"\bapplicant\b",
                r"\bcliente\b",
                r"\bcustomer\b",
            ],
        ),
        "fab": _avaliar_campo_relatorio(
            texto=texto,
            nome_campo="fabricante",
            valores_esperados=fabricantes_esperados,
            padroes_rotulo=[
                r"\bfabricante\b",
                r"\bmanufacturer\b",
                r"\bdetentor da tecnologia\b",
                r"\bholder of technology\b",
            ],
        ),
        "mod": _avaliar_campo_relatorio(
            texto=texto,
            nome_campo="modelo",
            valores_esperados=modelos_esperados,
            padroes_rotulo=[
                r"\bmodelo\b",
                r"\bmodel\b",
                r"\bmodel name\b",
                r"\bmodel no\b",
            ],
        ),
    }


def _detectar_presenca(texto, padroes):
    for padrao in padroes:
        if re.search(padrao, texto, flags=re.I):
            return True
    return False


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


def _normas_aplicaveis(equipamentos, texto_cct="", dados_pdf=None):
    if not any("Radiação Restrita" in eq or "Radiacao Restrita" in eq for eq in equipamentos):
        return []

    motivadores = "; ".join(equipamentos) if equipamentos else "Equipamentos identificados no requerimento"

    normas = []

    regras_base = [
        {
            "norma": "Ato nº 1120, de 19 de fevereiro de 2018",
            "numero": "1120",
            "ausente": "REVISAR",
        },
        {
            "norma": "Ato nº 14448, de 04 de dezembro de 2017",
            "numero": "14448",
            "ausente": "NC",
        },
        {
            "norma": "Ato nº 17087, de 19 de dezembro de 2022",
            "numero": "17087",
            "ausente": "REVISAR",
        },
        {
            "norma": "Resolução nº 680, de 27 de junho de 2017",
            "numero": "680",
            "ausente": "NC",
        },
    ]

    for regra in regras_base:
        presente = _texto_tem_norma(texto_cct, regra["numero"])

        if presente:
            status = "C"
            motivo = "Norma encontrada no CCT."
        else:
            status = regra["ausente"]

            if status == "NC":
                motivo = "Norma obrigatória não encontrada no CCT."
            else:
                motivo = "Norma geralmente aplicável não encontrada no CCT. Revisar manualmente."

        normas.append(
            {
                "status": status,
                "norma": regra["norma"],
                "motivadores": f"{motivadores}. {motivo}",
            }
        )

    ato_77_aplicavel = _texto_tem_ato_77_aplicavel(texto_cct)
    ato_77_presente = _texto_tem_norma(texto_cct, "77")

    if ato_77_aplicavel and ato_77_presente:
        status_77 = "C"
        motivo_77 = (
            "Termos de Wi-Fi/OFDM/802.11/WLAN/OFDMA/DSSS encontrados no CCT "
            "e Ato nº 77 presente."
        )

    elif ato_77_aplicavel and not ato_77_presente:
        status_77 = "NC"
        motivo_77 = (
            "Termos de Wi-Fi/OFDM/802.11/WLAN/OFDMA/DSSS encontrados no CCT, "
            "mas Ato nº 77 não consta."
        )

    else:
        status_77 = "N/A"
        motivo_77 = (
            "Sem termos de Wi-Fi/OFDM/802.11/WLAN/OFDMA/DSSS no CCT. "
            "Bluetooth isolado não torna o Ato nº 77 aplicável."
        )

    normas.append(
        {
            "status": status_77,
            "norma": NORMA_ATO_77,
            "motivadores": f"{motivadores}. {motivo_77}",
        }
    )

    sar_nao_aplicavel = _texto_indica_sar_nao_aplicavel(texto_cct)
    sar_com_dados = _tem_sar_no_cct(texto_cct, dados_pdf=dados_pdf)
    ato_1630_presente = _texto_tem_norma(texto_cct, "1630")

    if sar_nao_aplicavel:
        status_1630 = "N/A"
        motivo_1630 = (
            "O CCT informa que o ensaio de SAR não é aplicável. "
            "Ato nº 1630 tratado como não aplicável."
        )

    elif sar_com_dados and ato_1630_presente:
        status_1630 = "C"
        motivo_1630 = (
            "Foram encontrados dados/coluna de SAR no CCT e o Ato nº 1630 está presente."
        )

    elif sar_com_dados and not ato_1630_presente:
        status_1630 = "NC"
        motivo_1630 = (
            "Foram encontrados dados/coluna de SAR no CCT, mas o Ato nº 1630 não consta. "
            "Conferir não conformidade."
        )

    else:
        status_1630 = "N/A"
        motivo_1630 = (
            "Não foram encontrados dados/coluna de SAR no CCT. "
            "Ato nº 1630 tratado como não aplicável."
        )

    normas.append(
        {
            "status": status_1630,
            "norma": NORMA_ATO_1630,
            "motivadores": f"{motivadores}. {motivo_1630}",
        }
    )

    return normas
   


def _selecionar_pdf_cct(pdfs, resumo=None):
    resumo = resumo or {}
    caminho_resumo = resumo.get("pdf_cct", "")

    if caminho_resumo:
        p = Path(caminho_resumo)
        if p.exists():
            return p

    palavras_cct = ["cct", "certificado", "conformidade", "tecnica", "técnica"]
    candidatos = [p for p in pdfs if any(k in p.name.lower() for k in palavras_cct)]

    if candidatos:
        candidatos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidatos[0]

    return None


def _contar_keywords_documentos(documentos):
    encontrados = {}
    detalhes = []

    for chave, padroes in KEYWORDS.items():
        total_geral = 0
        docs_encontrados = []

        for item in documentos:
            texto = item["texto"] or ""
            total_doc = 0

            for padrao in padroes:
                total_doc += len(re.findall(padrao, texto, flags=re.I))

            if total_doc > 0:
                total_geral += total_doc
                docs_encontrados.append(
                    {
                        "arquivo": item["arquivo"],
                        "categoria": item["categoria"],
                        "quantidade": total_doc,
                    }
                )

        if total_geral > 0:
            encontrados[chave] = total_geral
            detalhes.append(
                {
                    "palavra": chave,
                    "quantidade_total": total_geral,
                    "documentos": docs_encontrados,
                }
            )

    detalhes.sort(key=lambda x: (-x["quantidade_total"], x["palavra"]))
    return encontrados, detalhes


def _montar_resultado_palavras_chave(pasta_req, pdfs, textos_por_pdf, resumo, regras):
    cfg = (regras or {}).get("analise_palavras_chave", {}) or {}
    modo_busca = cfg.get("modo_busca", "somente_cct")

    documentos_analisados = []
    erro = None

    if modo_busca == "somente_cct":
        pdf_cct = _selecionar_pdf_cct(pdfs, resumo=resumo)
        if pdf_cct and pdf_cct in textos_por_pdf:
            documentos_analisados = [
                {
                    "arquivo": str(pdf_cct),
                    "categoria": _categoria_do_arquivo(pdf_cct, pasta_req),
                    "texto": textos_por_pdf[pdf_cct],
                }
            ]
        else:
            erro = "CCT não encontrado para análise de palavras-chave."
    else:
        documentos_analisados = [
            {
                "arquivo": str(pdf),
                "categoria": _categoria_do_arquivo(pdf, pasta_req),
                "texto": textos_por_pdf.get(pdf, ""),
            }
            for pdf in pdfs
        ]

    encontrados, detalhes = _contar_keywords_documentos(documentos_analisados) if documentos_analisados else ({}, [])

    resultado = {
        "modo_busca": modo_busca,
        "documentos_analisados": [
            {
                "arquivo": item["arquivo"],
                "categoria": item["categoria"],
            }
            for item in documentos_analisados
        ],
        "encontradas": encontrados,
        "ausentes": [k for k in KEYWORDS.keys() if k not in encontrados],
        "detalhes": detalhes,
    }

    if erro:
        resultado["erro"] = erro

    if modo_busca == "somente_cct" and documentos_analisados:
        resultado["documento_base"] = documentos_analisados[0]["arquivo"]

    return resultado


def _montar_alertas(req, dados_pdf, qtd_pdfs, relatorios_ensaio, palavras_encontradas):
    alertas = []

    if qtd_pdfs == 0:
        alertas.append("Nenhum PDF encontrado para análise.")

    if not dados_pdf.get("numero_certificado"):
        alertas.append("Número do certificado não identificado no CCT.")

    if not relatorios_ensaio:
        alertas.append("Nenhum Relatório de Ensaio encontrado.")

    if (
        palavras_encontradas.get("produto não acabado")
        or palavras_encontradas.get("modulo")
        or palavras_encontradas.get("uso interno")
    ):
        alertas.append("Há indícios de produto não acabado / módulo / uso interno.")

    if palavras_encontradas.get("bluetooth", 0) == 0 and "Radiação Restrita" in (req.get("tipo_produto") or ""):
        alertas.append("Nenhuma ocorrência de 'bluetooth' encontrada no escopo analisado.")

    if relatorios_ensaio:
        status_lab = [_status_item_relatorio(r, "lab") for r in relatorios_ensaio]
        status_sol = [_status_item_relatorio(r, "sol") for r in relatorios_ensaio]
        status_fab = [_status_item_relatorio(r, "fab") for r in relatorios_ensaio]
        status_mod = [_status_item_relatorio(r, "mod") for r in relatorios_ensaio]

        if all(status != "C" for status in status_lab):
            alertas.append("Laboratório não confirmado em nenhum relatório de ensaio.")

        if all(status != "C" for status in status_sol):
            alertas.append("Solicitante não confirmado em nenhum relatório de ensaio.")

        if all(status != "C" for status in status_fab):
            alertas.append("Fabricante não confirmado em nenhum relatório de ensaio.")

        if all(status != "C" for status in status_mod):
            alertas.append("Modelo não confirmado em nenhum relatório de ensaio.")

        if any(status == "NC" for status in status_sol):
            alertas.append("Há relatório de ensaio com solicitante não conforme ou não localizado.")

        if any(status == "NC" for status in status_fab):
            alertas.append("Há relatório de ensaio com fabricante não conforme ou não localizado.")

        if any(status == "REVISAR" for status in status_sol):
            alertas.append("Há relatório de ensaio com solicitante semelhante, mas pendente de revisão manual.")

        if any(status == "REVISAR" for status in status_fab):
            alertas.append("Há relatório de ensaio com fabricante semelhante, mas pendente de revisão manual.")

        if any(status == "REVISAR" for status in status_mod):
            alertas.append("Há relatório de ensaio com modelo não confirmado de forma segura. Revisar manualmente.")

    return alertas


def _alertas_normas_aplicaveis(normas):
    alertas = []

    for item in normas or []:
        status = item.get("status", "")
        norma = item.get("norma", "")
        motivo = item.get("motivadores", "")

        if status == "NC":
            alertas.append(f"{norma}: Não conforme. {motivo}")

        elif status == "REVISAR":
            alertas.append(f"{norma}: Revisar manualmente. {motivo}")

    return alertas


def analisar_requerimento(pasta_req, req, resumo=None):
    inicio = time.perf_counter()
    pasta_req = Path(pasta_req)
    resumo = resumo or {}
    regras = carregar_regras()

    dados_pdf = resumo.get("dados_pdf", {}) if resumo else {}

    pdfs = sorted(pasta_req.rglob("*.pdf"))
    textos_por_pdf = {}
    texto_total_partes = []

    for pdf in pdfs:
        cct_anterior = resumo.get('pdf_cct')
        if cct_anterior and Path(cct_anterior).resolve() == pdf.resolve() and dados_pdf.get('texto_completo'):
            texto = dados_pdf['texto_completo']
        else:
            texto = _extrair_texto_pdf(pdf)
        textos_por_pdf[pdf] = texto
        texto_total_partes.append(texto)

    texto_total = "\n".join(texto_total_partes)
    equipamentos = _inferir_equipamentos(req, texto_total)

    pdf_cct_base = _selecionar_pdf_cct(pdfs, resumo=resumo)
    texto_cct_base = textos_por_pdf.get(pdf_cct_base, "") if pdf_cct_base else ""

    normas = _normas_aplicaveis(
        equipamentos,
        texto_cct=texto_cct_base,
        dados_pdf=dados_pdf,
    )

    relatorios_ensaio = []
    outros_documentos = []

    for pdf in pdfs:
        texto = textos_por_pdf.get(pdf, "")
        categoria = _categoria_do_arquivo(pdf, pasta_req)
        nome = pdf.stem

        if "ensaio" in nome.lower() or "ensaio" in categoria.lower():
            relatorios_ensaio.append(
                _analisar_relatorio_ensaio(
                    caminho_pdf=pdf,
                    texto=texto,
                    req=req,
                    dados_pdf=dados_pdf,
                )
            )
        else:
            outros_documentos.append(
                {
                    "documento": nome,
                    "categoria": categoria,
                }
            )

    ocd = _extrair_ocd(req, list(textos_por_pdf.values()))

    resultado_palavras = _montar_resultado_palavras_chave(
        pasta_req=pasta_req,
        pdfs=pdfs,
        textos_por_pdf=textos_por_pdf,
        resumo=resumo,
        regras=regras,
    )

    alertas = _montar_alertas(
        req=req,
        dados_pdf=dados_pdf,
        qtd_pdfs=len(pdfs),
        relatorios_ensaio=relatorios_ensaio,
        palavras_encontradas=resultado_palavras.get("encontradas", {}),
    )
    
    alertas.extend(_alertas_normas_aplicaveis(normas))

    fim = time.perf_counter()

    return {
        "requerimento": req.get("requerimento", ""),
        "tempo_analise_segundos": round(fim - inicio, 6),
        "qtd_pdfs": len(pdfs),
        "ocd": ocd,
        "equipamentos": equipamentos,
        "palavras_chave": resultado_palavras,
        "normas_aplicaveis": normas,
        "documentos_processados": {
            "relatorios_ensaio": relatorios_ensaio,
            "outros_documentos": outros_documentos,
        },
        "alertas": alertas,
    }
