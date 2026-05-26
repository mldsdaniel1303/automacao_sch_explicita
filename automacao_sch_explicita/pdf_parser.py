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



def _limpar_numero_certificado(valor):
    valor = str(valor or "").strip()
    valor = valor.replace("_", " ")
    valor = valor.replace("–", "-").replace("—", "-")
    valor = re.sub(r"\s+", " ", valor)
    valor = re.sub(r"\s*/\s*", "/", valor)
    valor = re.sub(r"\s*-\s*", "-", valor)
    valor = valor.strip(" :;,-")
    return valor.upper()


def _eh_cep(valor):
    texto = str(valor or "").strip()
    return bool(re.fullmatch(r"\d{2}\.?\d{3}-?\d{3}", texto))


def _candidato_certificado_valido(candidato):
    """
    Evita que dados de histórico/processo/descrição sejam confundidos com
    número de certificado. Ex.: DESCRIPTION 11847-26 não é certificado.
    """
    cand = _limpar_numero_certificado(candidato)
    cand_norm = _normalizar_texto(cand)

    if not cand or _eh_cep(cand):
        return False

    prefixos_ruins = {
        "description",
        "descricao",
        "descrição",
        "process",
        "processo",
        "history",
        "historico",
        "histórico",
        "revision",
        "revisao",
        "revisão",
        "date",
        "data",
    }

    primeiro_token = cand_norm.split(" ", 1)[0] if cand_norm else ""
    if primeiro_token in prefixos_ruins:
        return False

    # Códigos internos de processo, como 11847-26-01-IN-RO, não são certificado.
    if re.search(r"\b\d{4,6}-\d{2}-\d{2}-[A-Z]{2}-[A-Z]{2}\b", cand, flags=re.I):
        return False

    # Se tiver OCP, ICC ou NCC, é um candidato forte.
    if re.search(r"\b(OCP|ICC|NCC)\b", cand, flags=re.I):
        return True

    # Candidatos de formato tradicional ABCP-25-0154 etc.
    if re.search(r"\b[A-Z]{2,12}\s*[-/]?\s*\d{2,6}\s*[-/]\s*\d{2,8}\b", cand, flags=re.I):
        return True

    return False


def _extrair_candidatos_certificado(texto):
    texto = texto or ""

    padroes = [
        # Versys OCP 5200 / OCP 0186 / nomes de OCP seguidos de numeração
        r"\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9]{1,30}\s+OCP\s*\d{2,6}\b",
        r"\bOCP\s*\d{2,6}\b",

        # ICC 09.104/2025-I
        r"\b(?:ICC|NCC)\s*[-_]?\s*\d{1,5}(?:\.\d{1,5})?\s*/\s*\d{2,4}(?:\s*[-–—]\s*[A-Z0-9]+)?\b",

        # NCC 29900/26
        r"\b(?:ICC|NCC)\s*[-_]?\s*\d{1,6}\s*/\s*\d{2,4}(?:\s*[-–—]\s*[A-Z0-9]+)?\b",

        # ICC 09.104-2025-I
        r"\b(?:ICC|NCC)\s*[-_]?\s*\d{1,5}(?:\.\d{1,5})?\s*[-_]\s*\d{2,4}(?:\s*[-_]\s*[A-Z0-9]+)?\b",

        # ABCP-25-0154
        r"\b[A-Z]{2,12}\s*[-_]\s*\d{2,6}\s*[-_]\s*\d{2,8}\b",

        # ABCP-25/0154 ou similares
        r"\b[A-Z]{2,12}\s*[-_]\s*\d{2,6}\s*/\s*\d{2,8}\b",

        # ABCP25-0154 ou similares
        r"\b[A-Z]{2,12}\s*\d{2,6}\s*[-_]\s*\d{2,8}\b",
    ]

    candidatos = []

    for padrao in padroes:
        for m in re.finditer(padrao, texto, flags=re.I):
            candidato = _limpar_numero_certificado(m.group(0))

            if _candidato_certificado_valido(candidato):
                candidatos.append(candidato)

    return candidatos


def _limpar_valor_certificado_extraido(valor):
    valor = _limpar_texto(valor)

    # Remove campos seguintes quando a extração do PDF junta tudo na mesma linha.
    valor = re.split(
        r"\s+(?:Data\s+(?:Certifica(?:ç|c)[aã]o|Validade|Manuten(?:ç|c)[aã]o|Emiss(?:ã|a)o)|Certification\s+Date|Expiry\s+Date|Renewal\s+Date|Issue\s+Date)\b",
        valor,
        maxsplit=1,
        flags=re.I,
    )[0]

    valor = re.sub(r"^(?:n[uú]mero\s+do\s+certificado|certificate\s+number|certificate\s+no\.?|certificado)\s*[:#\-]?\s*", "", valor, flags=re.I)
    valor = re.sub(r"^\s*/\s*(?:certificate\s+number|certificate\s+no\.?)\s*[:#\-]?\s*", "", valor, flags=re.I)
    return _limpar_numero_certificado(valor)


def extrair_numero_certificado_cct(texto):
    texto = texto or ""

    # Primeiro tenta a linha rotulada. Isso evita pegar Histórico/Description/Process.
    for linha in texto.splitlines():
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        if not linha_norm:
            continue

        tem_rotulo_pt = "numero do certificado" in linha_norm or "n do certificado" in linha_norm or "no do certificado" in linha_norm
        tem_rotulo_en = "certificate number" in linha_norm or "certificate no" in linha_norm

        if tem_rotulo_pt or tem_rotulo_en:
            m = re.search(r"(?:number|no\.?|certificado)\s*[:#\-]?\s*(.+)$", linha_limpa, flags=re.I)
            if not m:
                m = re.search(r"[:#\-]\s*(.+)$", linha_limpa, flags=re.I)

            if m:
                valor = _limpar_valor_certificado_extraido(m.group(1))
                if _candidato_certificado_valido(valor):
                    return valor

            candidatos_linha = _extrair_candidatos_certificado(linha_limpa)
            if candidatos_linha:
                return candidatos_linha[0]

    padroes_rotulo = [
        r"n[uú]mero\s+do\s+certificado\s*/?\s*certificate\s*#?",
        r"n[º°o]\s*do\s*certificado\s*/?\s*certificate\s*no\.?",
        r"n[º°o]\s*do\s*certificado\s*/?\s*certificate\s*number",
        r"certificate\s+number",
        r"certificate\s*no\.?",
        r"certificado\s*#?",
    ]

    for rotulo in padroes_rotulo:
        m = re.search(rotulo, texto, flags=re.I)
        if not m:
            continue

        trecho = texto[m.start(): m.start() + 400]
        candidatos = _extrair_candidatos_certificado(trecho)

        if candidatos:
            return candidatos[0]

    # Último recurso: procura no texto todo, mas com blacklist.
    candidatos = _extrair_candidatos_certificado(texto)

    if candidatos:
        return candidatos[0]

    return ""


def _extrair_numero_certificado_do_nome(caminho_pdf):
    stem = Path(caminho_pdf).stem if caminho_pdf else ""
    stem = stem.replace("_", " ")
    candidatos = _extrair_candidatos_certificado(stem)

    if candidatos:
        return candidatos[0]

    return ""


def _extrair_data_por_rotulo(texto, rotulos):
    texto = texto or ""

    for rotulo in rotulos:
        padrao = rf"{rotulo}[^\d]{{0,50}}(\d{{2}}/\d{{2}}/\d{{4}})"
        m = re.search(padrao, texto, flags=re.I)
        if m:
            return m.group(1)

    return ""


def _limpar_valor_tabela_rotulada(valor):
    valor = _limpar_texto(valor)
    valor = re.sub(r"\s+", " ", valor)
    return valor.strip(" :-;")


def _label_contem(label_norm, termos):
    return any(termo in label_norm for termo in termos)


def _extrair_campos_cct_de_tabelas(tabelas_brutas):
    """
    Extrai campos principais do CCT a partir de tabelas do tipo:
    [Modelo / Model] [CCBQ730M]
    [Tipo de Produto / Type of Product] [Transceptor de Radiação Restrita]
    """
    campos = {
        "modelo": "",
        "nome_comercial": "",
        "tipo_produto": "",
        "servico_aplicacao": "",
        "solicitante": "",
        "fabricante": "",
        "regulamentos": "",
    }

    for tabela in tabelas_brutas or []:
        linhas = _limpar_tabela_bruta(tabela)

        for linha in linhas:
            if len(linha) < 2:
                continue

            label = _limpar_texto(linha[0])
            valor = _limpar_valor_tabela_rotulada(linha[1])

            if not label or not valor:
                continue

            label_norm = _normalizar_texto(label)

            if not campos["modelo"] and _label_contem(label_norm, ["modelo", "model"]):
                if "nome comercial" not in label_norm and "commercial name" not in label_norm:
                    campos["modelo"] = valor
                    continue

            if not campos["nome_comercial"] and _label_contem(label_norm, ["nome comercial", "commercial name"]):
                campos["nome_comercial"] = valor
                continue

            if not campos["tipo_produto"] and _label_contem(label_norm, ["tipo de produto", "tipo do produto", "type of product"]):
                campos["tipo_produto"] = valor
                continue

            if not campos["servico_aplicacao"] and _label_contem(label_norm, ["servico aplicacao", "serviço aplicação", "service application"]):
                campos["servico_aplicacao"] = valor
                continue

            if not campos["solicitante"] and _label_contem(label_norm, ["solicitante", "applicant"]):
                campos["solicitante"] = valor
                continue

            if not campos["fabricante"] and _label_contem(label_norm, ["fabricante", "manufacturer"]):
                campos["fabricante"] = valor
                continue

            if not campos["regulamentos"] and _label_contem(label_norm, ["regulamento", "regulation"]):
                campos["regulamentos"] = valor
                continue

    return campos


def _valor_parece_tipo_produto(valor):
    texto = _normalizar_texto(valor)

    if not texto:
        return False

    sinais_ruins = [
        "icc ",
        "ncc ",
        "certificado desde",
        "data de emissao",
        "valido ate",
        "válido até",
        "produto certificado desde",
        "certificate",
        "cnpj",
        "cep",
    ]

    if any(s in texto for s in sinais_ruins):
        return False

    sinais_tipo = [
        "transceptor",
        "radiacao restrita",
        "radiação restrita",
        "produto para telecomunicacao",
        "equipamento",
        "terminal",
        "modulo",
        "módulo",
    ]

    return any(s in texto for s in sinais_tipo)



def _limpar_ocd(valor):
    valor = _limpar_texto(valor)

    if not valor:
        return ""

    valor = re.sub(r"^(pela|pelo|da|do|de)\s+", "", valor, flags=re.I).strip()
    valor = re.split(r"\b(certifica|atesta|declara|informa)\b", valor, flags=re.I)[0].strip(" -:;,")

    valor_norm = _normalizar_texto(valor)

    ruins = {
        "pela",
        "pelo",
        "da",
        "do",
        "de",
        "certificado",
        "certificacao",
        "certificação",
        "organismo",
        "anatel",
    }

    if valor_norm in ruins:
        return ""

    # ANATEL é o órgão designador, não o OCD/OCP do certificado.
    if valor_norm == "anatel" or valor_norm.startswith("anatel "):
        return ""

    if "organismo de certificacao designado" in valor_norm:
        return ""

    if len(valor) < 3:
        return ""

    return valor


def _extrair_codigo_ocp(texto):
    texto = texto or ""

    # Código do OCP costuma aparecer como OCP 0186 no selo/credencial.
    # Não confundir com número de certificado, por exemplo "Versys OCP 5200".
    m = re.search(r"OCP\s*0\d{3}", texto, flags=re.I)
    if not m:
        return ""

    return re.sub(r"\s+", " ", m.group(0).upper()).strip()


def _extrair_ocd_do_texto(texto, linhas):
    """
    Prioriza o cabeçalho do CCT e impede o falso positivo 'ANATEL'.
    Para o modelo Versys, o nome aparece no topo como Associação Versys de Tecnologia.
    """
    linhas = linhas or []

    # 1) Cabeçalho do certificado.
    for linha in linhas[:30]:
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        if not linha_limpa:
            continue

        if "anatel" in linha_norm and "ocp" not in linha_norm:
            continue

        if "associacao" in linha_norm and "versys" in linha_norm:
            return linha_limpa

        if "versys certificacoes" in linha_norm:
            return "Versys Certificações"

    # 2) Padrões explícitos, desde que não capturem ANATEL.
    padroes = [
        r"\bOCD\b\s*[:\-]?\s*([^\n]{3,100})",
        r"Organismo\s+de\s+Certifica(?:ç|c)[aã]o\s*[:\-]?\s*([^\n]{3,100})",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto or "", flags=re.I)
        if not m:
            continue

        valor = _limpar_ocd(m.group(1))
        if valor:
            return valor

    # 3) Fallback específico para Versys.
    texto_norm = _normalizar_texto(texto)
    if "versys" in texto_norm:
        return "Versys Certificações"

    return ""


def _limpar_modelo(valor):
    valor = _limpar_texto(valor)
    if not valor:
        return ""

    valor = re.sub(r"^\s*(?:modelo\s*/\s*model|modelo|model)\s*[:\-]?\s*", "", valor, flags=re.I)
    valor = re.sub(r"^\s*/\s*model\s*[:\-]?\s*", "", valor, flags=re.I)
    valor = re.split(r"\s+(?:Solicitante|Applicant|Tipo\s+de\s+Produto|Product\s+Classification)\b", valor, maxsplit=1, flags=re.I)[0]
    return _limpar_texto(valor)


def _extrair_modelo_do_texto(linhas):
    for linha in linhas or []:
        linha_limpa = _limpar_texto(linha)
        if re.search(r"\bModelo\b\s*/\s*\bModel\b", linha_limpa, flags=re.I):
            m = re.search(r"\bModel\b\s*[:\-]?\s*([^\s].+)$", linha_limpa, flags=re.I)
            if m:
                return _limpar_modelo(m.group(1))

            m = re.search(r"\bModelo\b\s*[:\-]?\s*([^\s].+)$", linha_limpa, flags=re.I)
            if m:
                return _limpar_modelo(m.group(1))

    return ""


def _extrair_nome_empresa_apos_rotulo(linhas, rotulos):
    rotulos_norm = [_normalizar_texto(r) for r in rotulos]

    for idx, linha in enumerate(linhas or []):
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        if any(r in linha_norm for r in rotulos_norm):
            # Se houver valor na mesma linha após dois-pontos, usa esse valor.
            m = re.search(r"[:\-]\s*(.+)$", linha_limpa)
            if m:
                valor = _limpar_texto(m.group(1))
                valor_norm = _normalizar_texto(valor)
                if valor and not any(r == valor_norm or r in valor_norm for r in rotulos_norm):
                    return valor

            # Normalmente o CCT Versys traz o nome da empresa na linha seguinte.
            for prox in (linhas or [])[idx + 1: idx + 5]:
                prox_limpa = _limpar_texto(prox)
                prox_norm = _normalizar_texto(prox_limpa)

                if not prox_limpa:
                    continue

                if any(chave in prox_norm for chave in ["rua", "av ", "avenida", "cnpj", "cep", "phone", "fone"]):
                    continue

                return prox_limpa

    return ""


def _extrair_homologacoes_vinculadas(texto):
    texto = texto or ""
    vinculadas = []

    padrao_codigo = re.compile(
        r"(?:c[oó]digo\s+ANATEL|homologa(?:do|ção)\s+sob\s+c[oó]digo\s+ANATEL)\s*[:\-]?\s*"
        r"(\d{4,6}\s*-\s*\d{2}\s*-\s*\d{4,6})",
        flags=re.I,
    )

    for m in padrao_codigo.finditer(texto):
        codigo = re.sub(r"\s+", "", m.group(1))
        antes = texto[max(0, m.start() - 180): m.start()]
        modelos = re.findall(r"\bmodelo\s+([A-Z0-9._/-]{2,40})", antes, flags=re.I)
        modelo = _limpar_modelo(modelos[-1]) if modelos else ""
        trecho = _limpar_texto(texto[max(0, m.start() - 160): m.end() + 80])

        item = {
            "modelo": modelo,
            "codigo_anatel": codigo,
            "contexto": trecho,
        }

        if item not in vinculadas:
            vinculadas.append(item)

    return vinculadas


def _extrair_regulamentos_do_texto(texto):
    texto = texto or ""
    padroes = [
        r"Normas\s+aplic[aá]veis\s*/\s*Applicable\s+Standards\s*[:\-]?\s*([^\n]+)",
        r"Normas\s+aplic[aá]veis\s*[:\-]?\s*([^\n]+)",
        r"Applicable\s+Standards\s*[:\-]?\s*([^\n]+)",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.I)
        if m:
            return _limpar_texto(m.group(1))

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
        "sar",
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

            corpo = linhas[idx_cab + 1:]
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
    if valor_extraido and _valor_parece_tipo_produto(valor_extraido):
        return valor_extraido

    texto_norm = _normalizar_texto(texto)

    if "transceptor de radiacao restrita" in texto_norm:
        return "Transceptor de Radiação Restrita"

    if "radiocomunicacao de radiacao restrita" in texto_norm or "radiacao restrita" in texto_norm:
        return "Transceptor de Radiação Restrita"

    return ""


def parsear_certificado_pdf(caminho_pdf):
    resultado = {
        "numero_certificado": "",
        "homologacao": "",
        "modelo": "",
        "fabricante": "",
        "solicitante": "",
        "tipo_produto": "",
        "data_emissao": "",
        "data_validade": "",
        "ocd": "",
        "regulamentos": "",
        "texto_completo": "",
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
    resultado["texto_completo"] = texto

    campos_tabela = _extrair_campos_cct_de_tabelas(tabelas_brutas)

    resultado["numero_certificado"] = extrair_numero_certificado_cct(texto)

    if not resultado["numero_certificado"]:
        resultado["numero_certificado"] = _extrair_numero_certificado_do_nome(caminho_pdf)

    padroes_homologacao = [
        r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]?\s*([0-9./-]{4,})",
        r"N[ÚU]MERO\s+DE\s+HOMOLOGA[CÇ][AÃ]O\s*[:\-]?\s*([0-9./-]{4,})",
    ]

    resultado["homologacao"] = _extrair_primeiro(texto_limpo, padroes_homologacao)
    resultado["ocp_codigo"] = _extrair_codigo_ocp(texto)
    resultado["ocd"] = _extrair_ocd_do_texto(texto, linhas)
    resultado["homologacoes_vinculadas"] = _extrair_homologacoes_vinculadas(texto)

    resultado["modelo"] = _limpar_modelo(
        campos_tabela.get("modelo") or _extrair_modelo_do_texto(linhas) or _extrair_valor_por_rotulo(
            linhas,
            ["MODELO", "MODEL"],
        )
    )

    resultado["fabricante"] = campos_tabela.get("fabricante") or _extrair_nome_empresa_apos_rotulo(
        linhas,
        [
            "Fabricante",
            "Manufacturer",
            "Manufacturer Product Owner",
            "Detentor da Tecnologia",
        ],
    ) or _extrair_valor_por_rotulo(
        linhas,
        [
            "NOME E ENDEREÇO DO FABRICANTE",
            "NOME E ENDERECO DO FABRICANTE",
            "FABRICANTE",
            "MANUFACTURER",
        ],
    )

    resultado["solicitante"] = campos_tabela.get("solicitante") or _extrair_nome_empresa_apos_rotulo(
        linhas,
        [
            "Solicitante",
            "Solicitant",
            "Applicant",
        ],
    ) or _extrair_valor_por_rotulo(
        linhas,
        [
            "NOME E ENDEREÇO DO SOLICITANTE",
            "NOME E ENDERECO DO SOLICITANTE",
            "SOLICITANTE",
            "APPLICANT",
        ],
    )

    tipo_tabela = campos_tabela.get("tipo_produto", "")

    if tipo_tabela and _valor_parece_tipo_produto(tipo_tabela):
        resultado["tipo_produto"] = tipo_tabela
    else:
        resultado["tipo_produto"] = _extrair_valor_por_rotulo(
            linhas,
            [
                "TIPO DE PRODUTO",
                "TIPO DO PRODUTO",
                "TYPE OF PRODUCT",
                "DESCRIÇÃO DO PRODUTO",
                "DESCRICAO DO PRODUTO",
            ],
        )

    resultado["tipo_produto"] = _inferir_tipo_produto(
        texto,
        resultado["tipo_produto"],
    )

    resultado["regulamentos"] = campos_tabela.get("regulamentos", "") or _extrair_regulamentos_do_texto(texto)

    resultado["data_emissao"] = _extrair_data_por_rotulo(
        texto,
        [
            "data de emiss[aã]o",
            "emiss[aã]o",
            "issue date",
            "emission date",
            "emitido em",
        ],
    )

    resultado["data_validade"] = _extrair_data_por_rotulo(
        texto,
        [
            "data de validade",
            "validade",
            "expiry date",
            "expiration date",
            "v[aá]lido at[eé]",
            "valid until",
        ],
    )

    if not resultado["homologacao"]:
        for linha in linhas:
            m = re.search(r"HOMOLOGA[CÇ][AÃ]O(?:\s+ANATEL)?\s*[:\-]\s*([0-9./-]{4,})", linha, re.I)

            if m:
                resultado["homologacao"] = _limpar_texto(m.group(1))
                break

    if not resultado["ocd"]:
        resultado["ocd"] = _extrair_ocd_do_texto(texto, linhas)

    obs = _classificar_observacao_cct(texto)
    resultado["observacao_classificacao"] = obs["observacao_classificacao"]
    resultado["observacao_texto"] = obs["observacao_texto"]
    resultado["observacao_motivos"] = obs["observacao_motivos"]

    resultado["tabela_tecnica_cct"] = _extrair_tabela_tecnica_cct_de_tabelas(tabelas_brutas)

    print(f"[PDF] Dados extraídos de {caminho_pdf.name}: {resultado}")
    return resultado