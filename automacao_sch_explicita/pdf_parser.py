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



def _somente_digitos(valor):
    return re.sub(r"\D+", "", str(valor or ""))


def _parece_homologacao_anatel(valor):
    """
    Reconhece homologação ANATEL no padrão 03645-26-12388
    ou no padrão numérico equivalente com 12 dígitos.
    """
    texto = str(valor or "").strip()

    if re.search(r"\b\d{4,6}\s*[-–—]\s*\d{2}\s*[-–—]\s*\d{4,6}\b", texto):
        return True

    digitos = _somente_digitos(texto)
    return len(digitos) == 12


def _formatar_homologacao_anatel(valor):
    """
    Normaliza homologação ANATEL para 00000-00-00000.
    """
    texto = str(valor or "").strip()
    texto = texto.replace("–", "-").replace("—", "-").replace("−", "-")

    m = re.search(r"\b(\d{4,6})\s*-\s*(\d{2})\s*-\s*(\d{4,6})\b", texto)
    if m:
        parte1 = _somente_digitos(m.group(1)).zfill(5)
        parte2 = _somente_digitos(m.group(2))
        parte3 = _somente_digitos(m.group(3)).zfill(5)
        return f"{parte1}-{parte2}-{parte3}"

    digitos = _somente_digitos(texto)
    if len(digitos) == 12:
        return f"{digitos[:5]}-{digitos[5:7]}-{digitos[7:]}"

    return texto

def _candidato_certificado_valido(candidato):
    """
    Evita que dados de histórico/processo/descrição sejam confundidos com
    número de certificado. Ex.: DESCRIPTION 11847-26 não é certificado.
    """
    cand = _limpar_numero_certificado(candidato)
    cand_norm = _normalizar_texto(cand)

    if not cand or _eh_cep(cand):
        return False

    # Homologação ANATEL não é número de certificado.
    if _parece_homologacao_anatel(cand):
        return False

    # Código do OCP no selo, por exemplo OCP 0186, não é certificado.
    # Número de certificado como "Versys OCP 5200" continua válido.
    if re.fullmatch(r"OCP\s*0\d{3}", cand, flags=re.I):
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



def _linhas_relevantes_por_palavras(texto, palavras, janela=2):
    """
    Procura linhas que contenham palavras-chave e retorna a linha encontrada
    mais algumas linhas seguintes. Útil quando o rótulo fica em uma linha
    e o valor na próxima.
    """
    linhas = [linha.strip() for linha in (texto or "").splitlines() if linha.strip()]
    resultado = []
    palavras_norm = [_normalizar_texto(p) for p in (palavras or [])]

    for idx, linha in enumerate(linhas):
        linha_norm = _normalizar_texto(linha)

        if any(p and p in linha_norm for p in palavras_norm):
            bloco_linhas = linhas[idx: idx + janela + 1]
            resultado.append(
                {
                    "indice": idx,
                    "linha": linha,
                    "linhas": bloco_linhas,
                    "bloco": " ".join(bloco_linhas),
                }
            )

    return resultado


def _contexto_indica_homologacao_vinculada(texto):
    """
    Retorna True quando o código ANATEL parece pertencer a acessório/dongle/módulo
    mencionado no CCT, não à homologação principal do produto.
    """
    texto_norm = _normalizar_texto(texto)

    sinais_vinculado = [
        "dongle",
        "acessorio",
        "acessório",
        "modulo",
        "módulo",
        "module",
        "comercializado com",
        "sera comercializado com",
        "será comercializado com",
        "integrado",
        "incorporado",
        "homologado sob codigo anatel",
        "homologado sob código anatel",
    ]

    return any(s in texto_norm for s in sinais_vinculado)


def extrair_numero_certificado_por_contexto(texto):
    """
    Extrai número do certificado somente perto de rótulos fortes:
    Número do Certificado / Certificate Number / Certificate No.
    Evita pegar Description, Processo, Histórico etc.
    """
    palavras = [
        "Número do Certificado",
        "Numero do Certificado",
        "Nº do Certificado",
        "No do Certificado",
        "Certificate Number",
        "Certificate No",
    ]

    blocos = _linhas_relevantes_por_palavras(texto, palavras, janela=2)

    for item in blocos:
        bloco = item["bloco"]

        m = re.search(
            r"(?:n[uú]mero\s+do\s+certificado|numero\s+do\s+certificado|n[ºo]\s+do\s+certificado|certificate\s+number|certificate\s+no\.?)"
            r".{0,120}?"
            r"((?:[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9]{1,30}\s+)?OCP\s*\d{2,8}|ICC\s*[-_]?\s*[\w./-]+|NCC\s*[-_]?\s*[\w./-]+|[A-Z]{2,12}\s*[-_]\s*\d{2,6}\s*[-_/]\s*\d{2,8})",
            bloco,
            flags=re.I,
        )

        if m:
            valor = _limpar_valor_certificado_extraido(m.group(1))
            if _candidato_certificado_valido(valor):
                return valor

        candidatos = _extrair_candidatos_certificado(bloco)
        for candidato in candidatos:
            if _candidato_certificado_valido(candidato):
                return candidato

    return ""


def extrair_homologacao_por_contexto(texto):
    """
    Extrai homologação ANATEL principal usando contexto e formato.
    Não retorna códigos vinculados a dongle/acessório/módulo.
    """
    palavras = [
        "Número de Homologação",
        "Numero de Homologacao",
        "Homologação",
        "Homologacao",
        "Código ANATEL",
        "Codigo ANATEL",
        "ANATEL code",
    ]

    blocos = _linhas_relevantes_por_palavras(texto, palavras, janela=2)

    for item in blocos:
        bloco = item["bloco"]

        # Se o contexto indica acessório/dongle, não tratar como homologação principal.
        if _contexto_indica_homologacao_vinculada(bloco):
            continue

        m = re.search(
            r"\b\d{4,6}\s*[-–—]\s*\d{2}\s*[-–—]\s*\d{4,6}\b",
            bloco,
            flags=re.I,
        )

        if m:
            return _formatar_homologacao_anatel(m.group(0))

        for digitos in re.findall(r"\b\d{12}\b", bloco):
            if _parece_homologacao_anatel(digitos):
                return _formatar_homologacao_anatel(digitos)

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
    m = re.search(r"\bOCP\s*0\d{3}\b", texto, flags=re.I)
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
    """
    Extrai homologações informativas/vinculadas, como dongle, acessório ou módulo
    comercializado junto com o produto.
    """
    texto = texto or ""
    vinculadas = []
    vistos = set()

    def _adicionar_vinculada(modelo, codigo, contexto):
        chave = (str(modelo or "").strip().upper(), str(codigo or "").strip())
        if chave in vistos:
            return
        vistos.add(chave)
        vinculadas.append(
            {
                "modelo": modelo or "",
                "codigo_anatel": codigo,
                "contexto": contexto,
            }
        )

    padrao = re.compile(
        r"(?P<contexto>.{0,220}?"
        r"(?:dongle|m[oó]dulo|module|acess[oó]rio|comercializado|homologado)"
        r".{0,220}?"
        r"(?P<codigo>\d{4,6}\s*[-–—]\s*\d{2}\s*[-–—]\s*\d{4,6})"
        r".{0,120})",
        flags=re.I | re.S,
    )

    for m in padrao.finditer(texto):
        contexto = _limpar_texto(m.group("contexto"))
        codigo = _formatar_homologacao_anatel(m.group("codigo"))

        modelo = ""
        modelos = re.findall(r"\bmodelo\s+([A-Z0-9._/-]{2,40})", contexto, flags=re.I)
        if modelos:
            modelo = _limpar_modelo(modelos[-1])

        _adicionar_vinculada(modelo, codigo, contexto)

    # Fallback para frase direta "Código ANATEL: 00000-00-00000" em contexto vinculado.
    padrao_codigo = re.compile(
        r"(?:c[oó]digo\s+ANATEL|homologa(?:do|ção)\s+sob\s+c[oó]digo\s+ANATEL)\s*[:\-]?\s*"
        r"(\d{4,6}\s*[-–—]\s*\d{2}\s*[-–—]\s*\d{4,6})",
        flags=re.I,
    )

    for m in padrao_codigo.finditer(texto):
        contexto = _limpar_texto(texto[max(0, m.start() - 180): m.end() + 120])

        if not _contexto_indica_homologacao_vinculada(contexto):
            continue

        codigo = _formatar_homologacao_anatel(m.group(1))
        modelos = re.findall(r"\bmodelo\s+([A-Z0-9._/-]{2,40})", contexto, flags=re.I)
        modelo = _limpar_modelo(modelos[-1]) if modelos else ""

        _adicionar_vinculada(modelo, codigo, contexto)

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
    texto = _normalizar_texto(
        " ".join(str(c or "") for c in (cabecalho or []))
    )

    score = 0

    tem_faixa = any(
        termo in texto
        for termo in [
            "faixa de frequencia",
            "faixa de frequencias",
            "faixa de frequencia tx",
            "faixa de frequencias tx",
            "frequency range",
            "range mhz",
        ]
    )

    tem_potencia = any(
        termo in texto
        for termo in [
            "potencia maxima de saida",
            "potencia de saida",
            "potencia saida",
            "maximum output power",
            "output power",
            "tx power",
            "power w",
        ]
    )

    tem_intensidade = any(
        termo in texto
        for termo in [
            "intensidade de campo",
            "intensidade campo",
            "field strength",
            "electric field strength",
            "uv m",
        ]
    )

    tem_emissao = any(
        termo in texto
        for termo in [
            "designacao de emissoes",
            "designacao de emissao",
            "designation of emission",
            "designation of emissions",
        ]
    )

    tem_tecnologia = any(
        termo in texto
        for termo in [
            "tecnologia",
            "technology",
            "espalhamento",
            "spread spectrum",
        ]
    )

    tem_modulacao = any(
        termo in texto
        for termo in [
            "modulacao",
            "modulation",
            "tipo de modulacao",
            "type of modulation",
        ]
    )

    if tem_faixa:
        score += 4

    if tem_potencia:
        score += 4

    if tem_intensidade:
        score += 4

    if tem_emissao:
        score += 2

    if tem_tecnologia:
        score += 2

    if tem_modulacao:
        score += 2

    # Cabeçalho técnico forte: faixa + potência ou faixa + intensidade.
    if tem_faixa and (tem_potencia or tem_intensidade):
        score += 10

    return score


def _linha_parece_cabecalho_tecnico_cct(linha):
    texto = _normalizar_texto(
        " ".join(str(c or "") for c in (linha or []))
    )

    tem_faixa = (
        "faixa de frequencia" in texto
        or "faixa de frequencias" in texto
        or "frequency range" in texto
        or "range mhz" in texto
    )

    tem_potencia = (
        "potencia maxima de saida" in texto
        or "potencia maxima saida" in texto
        or "potencia de saida" in texto
        or "potencia saida" in texto
        or "maximum output power" in texto
        or "output power" in texto
        or "tx power" in texto
        or "power w" in texto
    )

    tem_intensidade = (
        "intensidade de campo" in texto
        or "intensidade campo" in texto
        or "field strength" in texto
        or "electric field strength" in texto
        or "uv m" in texto
    )

    return tem_faixa and (tem_potencia or tem_intensidade)


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

    for tabela in tabelas_brutas or []:
        linhas = _limpar_tabela_bruta(tabela)

        if len(linhas) < 2:
            continue

        # Antes a automação costumava procurar só nas primeiras linhas.
        # Agora varremos a tabela inteira, porque alguns CCTs trazem título/texto
        # antes do cabeçalho técnico real.
        for idx_cab in range(len(linhas)):
            cabecalho = linhas[idx_cab]

            if not _linha_parece_cabecalho_tecnico_cct(cabecalho):
                continue

            score = _pontuacao_cabecalho_tabela(cabecalho)

            if score < 6:
                continue

            corpo = linhas[idx_cab + 1:]
            corpo = [
                l for l in corpo
                if any(_limpar_texto(c) for c in l)
            ]

            if not corpo:
                continue

            tabela_ajustada = _ajustar_tabela_extraida(cabecalho, corpo)

            qtd_linhas = len(tabela_ajustada.get("linhas", []) or [])

            if (
                score > melhor_score
                or (
                    score == melhor_score
                    and qtd_linhas > melhor_qtd_linhas
                )
            ):
                melhor = tabela_ajustada
                melhor_score = score
                melhor_qtd_linhas = qtd_linhas

    if melhor is None:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    return melhor



def _extrair_tabela_tecnica_cct_do_texto(texto):
    """
    Fallback para CCTs em que o pdfplumber não extrai a tabela corretamente.

    Procura no texto linhas contendo:
    - Faixa de frequência
    - Potência de saída

    E monta uma tabela simples com:
    - Faixa de frequência (MHz)
    - Potência de saída (W)

    Também trata caso de célula mesclada:
    a faixa aparece uma vez e as potências aparecem nas linhas seguintes.
    """
    texto = texto or ""

    linhas = [
        _limpar_texto(l)
        for l in texto.splitlines()
        if _limpar_texto(l)
    ]

    if not linhas:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    idx_inicio = None

    for i, linha in enumerate(linhas):
        norm = _normalizar_texto(linha)

        tem_faixa = (
            "faixa de frequencia" in norm
            or "faixa de frequencias" in norm
            or "frequency range" in norm
        )

        tem_potencia = (
            "potencia maxima de saida" in norm
            or "potencia de saida" in norm
            or "potencia saida" in norm
            or "maximum output power" in norm
            or "output power" in norm
            or "power w" in norm
        )

        # Cabeçalho pode estar dividido em linhas próximas.
        janela = " ".join(linhas[i:i + 4])
        janela_norm = _normalizar_texto(janela)

        tem_faixa_janela = (
            "faixa de frequencia" in janela_norm
            or "faixa de frequencias" in janela_norm
            or "frequency range" in janela_norm
        )

        tem_potencia_janela = (
            "potencia maxima de saida" in janela_norm
            or "potencia de saida" in janela_norm
            or "potencia saida" in janela_norm
            or "maximum output power" in janela_norm
            or "output power" in janela_norm
            or "power w" in janela_norm
        )

        if (tem_faixa and tem_potencia) or (tem_faixa_janela and tem_potencia_janela):
            idx_inicio = i
            break

    if idx_inicio is None:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    linhas_saida = []
    ultima_faixa = ""

    # Captura a partir do cabeçalho técnico.
    # Limita a janela para não pegar observações/normas do restante do CCT.
    trecho = linhas[idx_inicio: idx_inicio + 80]

    padrao_faixa = re.compile(
        r"(\d[\d.,]*\s*(?:a|até|ate|-|–|—)\s*\d[\d.,]*)",
        flags=re.I,
    )

    padrao_potencia = re.compile(
        r"(?<![A-Z0-9])(\d+[,.]\d+)(?![A-Z0-9])",
        flags=re.I,
    )

    for linha in trecho:
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        # Para parar antes de pegar rodapé/observações/normas.
        if linhas_saida and any(
            marcador in linha_norm
            for marcador in [
                "normas aplicaveis",
                "applicable standards",
                "observacoes",
                "observations",
                "historico",
                "history",
                "informacoes adicionais",
                "additional information",
            ]
        ):
            break

        m_faixa = padrao_faixa.search(linha_limpa)

        if m_faixa:
            ultima_faixa = _limpar_texto(m_faixa.group(1))

        # A potência pode estar na mesma linha da faixa ou em linhas seguintes.
        numeros_decimais = padrao_potencia.findall(linha_limpa)

        if not numeros_decimais:
            continue

        # Evita tratar a própria faixa como potência.
        # Ex.: "2400 a 2483,5" contém "2483,5", mas não é potência.
        potencias = []

        for numero in numeros_decimais:
            if m_faixa and numero in m_faixa.group(1):
                continue

            potencias.append(numero)

        if not potencias:
            continue

        if not ultima_faixa:
            continue

        # Normalmente a primeira potência da linha é a coluna Potência de saída.
        potencia = potencias[0]

        linhas_saida.append(
            [
                ultima_faixa,
                potencia,
            ]
        )

    # Remove duplicatas preservando ordem.
    linhas_unicas = []
    vistos = set()

    for linha in linhas_saida:
        chave = tuple(linha)

        if chave in vistos:
            continue

        vistos.add(chave)
        linhas_unicas.append(linha)

    if not linhas_unicas:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    return {
        "cabecalho": [
            "Faixa de frequência (MHz)",
            "Potência de saída (W)",
        ],
        "linhas": linhas_unicas,
    }


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
        "ocp_codigo": "",
        "regulamentos": "",
        "texto_completo": "",
        "homologacoes_vinculadas": [],
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

    resultado["numero_certificado"] = extrair_numero_certificado_por_contexto(texto)

    if not resultado["numero_certificado"]:
        resultado["numero_certificado"] = extrair_numero_certificado_cct(texto)

    if not resultado["numero_certificado"]:
        resultado["numero_certificado"] = _extrair_numero_certificado_do_nome(caminho_pdf)

    resultado["homologacoes_vinculadas"] = _extrair_homologacoes_vinculadas(texto)
    resultado["homologacao"] = extrair_homologacao_por_contexto(texto)

    codigos_vinculados = {
        item.get("codigo_anatel")
        for item in resultado["homologacoes_vinculadas"]
        if item.get("codigo_anatel")
    }

    if resultado["homologacao"] in codigos_vinculados:
        resultado["homologacao"] = ""

    resultado["ocp_codigo"] = _extrair_codigo_ocp(texto)
    resultado["ocd"] = _extrair_ocd_do_texto(texto, linhas)

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
            "data emiss[aã]o",
            "issue date",
            "emission date",
            "emitido em",
        ],
    )

    resultado["data_validade"] = _extrair_data_por_rotulo(
        texto,
        [
            "v[aá]lido at[eé]",
            "valid until",
            "expiry date",
            "validade",
            "data de validade",
            "data validade",
        ],
    )

    if resultado["homologacao"] in {
        item.get("codigo_anatel")
        for item in resultado.get("homologacoes_vinculadas", [])
        if item.get("codigo_anatel")
    }:
        resultado["homologacao"] = ""

    if not resultado["ocd"]:
        resultado["ocd"] = _extrair_ocd_do_texto(texto, linhas)

    obs = _classificar_observacao_cct(texto)
    resultado["observacao_classificacao"] = obs["observacao_classificacao"]
    resultado["observacao_texto"] = obs["observacao_texto"]
    resultado["observacao_motivos"] = obs["observacao_motivos"]

    tabela_cct = _extrair_tabela_tecnica_cct_de_tabelas(tabelas_brutas)

    if not tabela_cct.get("linhas"):
     tabela_cct = _extrair_tabela_tecnica_cct_do_texto(texto)

    resultado["tabela_tecnica_cct"] = tabela_cct

    print(f"[PDF] Dados extraídos de {caminho_pdf.name}: {resultado}")
    return resultado