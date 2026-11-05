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
    Evita que dados de histórico/processo/endereço/descrição sejam confundidos
    com número de certificado.

    Exemplos que NÃO devem ser aceitos:
    - DESCRIPTION 11847-26
    - ROOM 2403-2404
    - BLOCK B
    - SALA 01
    - 04073/26
    - 04073-26
    - 04225-26-01654

    Exemplos que devem ser aceitos:
    - ICC 11.182/2025-I
    - NCC 29900/26
    - ABCP-25-0154
    - BRC-25.5598.02
    - OCP-I 93425
    """
    cand = _limpar_numero_certificado(candidato)
    cand_norm = _normalizar_texto(cand)

    if not cand or _eh_cep(cand):
        return False

    # Evita falso positivo vindo de endereço/localização.
    # Ex.: ROOM 2403-2404, BLOCK B, SALA 01, FLOOR 2.
    termos_endereco_ou_local = [
        "room",
        "sala",
        "bloco",
        "block",
        "andar",
        "floor",
        "building",
        "predio",
        "prédio",
        "edificio",
        "edifício",
        "avenida",
        "av ",
        "rua",
        "street",
        "road",
        "rd",
        "cep",
        "zip",
        "district",
        "bairro",
        "cidade",
        "city",
        "province",
        "provincia",
        "address",
        "endereco",
        "endereço",
    ]

    if any(t in cand_norm for t in termos_endereco_ou_local):
        return False

    # Homologação ANATEL não é número de certificado.
    # Ex.: 04225-26-01654.
    if _parece_homologacao_anatel(cand):
        return False

    # Requerimento/processo simples não é certificado.
    # Ex.: 04073/26, 04073-26, 10268/26.
    if re.fullmatch(r"\d{4,6}\s*[-/]\s*\d{2,4}", cand, flags=re.I):
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
        "emission",
        "emissao",
        "emissão",
        "validade",
        "valid",
        "expiry",
        "expiration",
        "traceability",
        "rastreabilidade",
        "service",
        "servico",
        "serviço",
        "order",
        "os",
        "page",
        "pagina",
        "página",
    }

    primeiro_token = cand_norm.split(" ", 1)[0] if cand_norm else ""

    if primeiro_token in prefixos_ruins:
        return False

    # Códigos internos de processo, como 11847-26-01-IN-RO, não são certificado.
    if re.search(r"\b\d{4,6}-\d{2}-\d{2}-[A-Z]{2}-[A-Z]{2}\b", cand, flags=re.I):
        return False

    # BRC-25.5598.02 / ABC-25.1234.01 / CERT-25.12345.1
    if re.search(
        r"\b[A-Z]{2,12}\s*[-_]\s*\d{2}\s*[.]\s*\d{3,8}(?:\s*[.]\s*\d{1,4})?\b",
        cand,
        flags=re.I,
    ):
        return True

    # OCP-I 93425 / OCP-TELI 93425 / OCP ABC 93425.
    if re.search(r"\bOCP\s*[-_]?\s*[A-Z]{1,10}\s*\d{3,8}\b", cand, flags=re.I):
        return True

    # ICC 11.182/2025-I, NCC 29900/26, OCP-I 93425 etc.
    if re.search(r"\b(ICC|NCC|OCP)\b", cand, flags=re.I):
        # Mas não aceitar OCP sozinho sem estrutura de certificado.
        if re.fullmatch(r"OCP\s*\d{2,6}", cand, flags=re.I):
            return False

        return True

    # Candidatos de formato tradicional ABCP-25-0154 etc.
    if re.search(
        r"\b[A-Z]{2,12}\s*[-/]?\s*\d{2,6}\s*[-/]\s*\d{2,8}\b",
        cand,
        flags=re.I,
    ):
        return True

    return False


def _extrair_candidatos_certificado(texto):
    texto = texto or ""

    padroes = [
        # Versys OCP 5200 / OCP 0186 / nomes de OCP seguidos de numeração
        r"\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9]{1,30}\s+OCP\s*\d{2,6}\b",
        r"\bOCP\s*\d{2,6}\b",

        # OCP-I 93425 / OCP-TELI 93425 / OCP ABC 93425
        r"\bOCP\s*[-_]?\s*[A-Z]{1,10}\s*\d{3,8}\b",

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

        # BRC-25.5598.02 / ABC-25.1234.01
        r"\b[A-Z]{2,12}\s*[-_]\s*\d{2}\s*[.]\s*\d{3,8}(?:\s*[.]\s*\d{1,4})?\b",
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



def _extrair_datas_cabecalho(texto):
    """Lê datas rotuladas da capa, sem usar datas de linhas do histórico."""
    meses = {m:i for i,m in enumerate(('janeiro','fevereiro','marco','abril','maio','junho',
                                      'julho','agosto','setembro','outubro','novembro','dezembro'), 1)}
    data = r'(\d{1,2}/\d{2}/\d{4}|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})'
    def formatar(valor):
        if '/' in valor:
            d,m,a = valor.split('/')
        else:
            d,m,a = re.split(r'\s+de\s+', _normalizar_texto(valor))
            m = meses.get(m)
            if m is None:
                return ''
        from datetime import date
        try:
            return date(int(a), int(m), int(d)).strftime('%d/%m/%Y')
        except ValueError:
            return ''
    resultado = {}
    for campo, rotulo in [('data_certificacao', r'(?:data (?:da|de) certifica[çc][aã]o|produto certificado desde)'),
                           ('data_alteracao', r'data (?:da|de) altera[çc][aã]o'),
                           ('data_emissao', r'(?:data (?:da|de) emiss[aã]o|emiss[aã]o)'),
                           ('data_validade', r'(?:data (?:da|de) validade|v[aá]lido at[eé])')]:
        m = re.search(rotulo + r'[^\d\n]{0,65}' + data, texto, re.I)
        if m:
            valor = formatar(m.group(1))
            if valor:
                resultado[campo] = valor
    dupla = re.search(r'certifica[çc][aã]o inicial\s+v[aá]lido at[eé](.{0,200})', texto, re.I | re.S)
    if dupla:
        datas = re.findall(data, dupla.group(1), re.I)
        if len(datas) == 2:
            for campo, valor in zip(('data_certificacao', 'data_validade'), datas):
                if formatar(valor):
                    resultado[campo] = formatar(valor)
    return resultado


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
    # Identificador repetido no cabeçalho; não aceitar o primeiro RE do corpo.
    cab_cpqd = re.search(r'^\s*(CPQD\s*[-–]?\s*[A-Z]\s*[- ]?\s*\d{3,8})\s*$', texto or '', re.I | re.M)
    if cab_cpqd:
        return _limpar_numero_certificado(cab_cpqd.group(1))
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
    # Rótulo completo vem antes de "Modelo de avaliação da conformidade".
    for idx, linha in enumerate(linhas or []):
        m = re.fullmatch(r'\s*Modelo(?:\(s\))?\s*(?:/\s*Model)?\s*:\s*(.*)', linha, re.I)
        if m:
            if m.group(1).strip():
                return _limpar_modelo(m.group(1))
            for seguinte in linhas[idx+1:idx+4]:
                if _normalizar_texto(seguinte) not in {'model', 'models'}:
                    return _limpar_modelo(seguinte)
    for idx, linha in enumerate(linhas or []):
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        if not linha_limpa:
            continue

        # Caso: "Modelo(s): W AI 3, W AI 4"
        m = re.search(
            r"\bModelo(?:\(s\))?\s*[:\-]?\s*(.+)$",
            linha_limpa,
            flags=re.I,
        )

        if m:
            valor = _limpar_modelo(m.group(1))

            if valor and not _normalizar_texto(valor) in {
                "model",
                "models",
                "modelo",
                "modelos",
                "nome comercial",
                "trade name",
            }:
                return valor

        # Caso: rótulo numa linha e valor na próxima.
        if linha_norm in {"modelo", "model", "modelos", "models", "modelo / model"}:
            for prox in (linhas or [])[idx + 1: idx + 4]:
                prox_limpa = _limpar_modelo(prox)

                if prox_limpa and not _normalizar_texto(prox_limpa) in {
                    "model",
                    "models",
                    "modelo",
                    "modelos",
                    "nome comercial",
                    "trade name",
                }:
                    return prox_limpa

    return ""


def _extrair_empresas_por_geometria(page):
    """Lê nomes sob rótulos isolados sem cruzar duas colunas ou a marca d'água."""
    palavras = page.extract_words()
    rotulos = []
    for palavra in palavras:
        nome = _normalizar_texto(palavra['text']).strip(':')
        if nome not in {'fabricante', 'solicitante', 'requerente'}:
            continue
        anteriores = [p for p in palavras if abs(p['top']-palavra['top']) < 3 and p['x0'] < palavra['x0']]
        if any(_normalizar_texto(p['text']) in {'nome', 'endereco', 'do'} for p in anteriores):
            continue
        rotulos.append((palavra, 'fabricante' if nome=='fabricante' else 'solicitante'))
    resultado = {}
    for palavra, campo in rotulos:
        direita = min([p['x0']-3 for p,_ in rotulos if abs(p['top']-palavra['top']) < 3 and p['x0'] > palavra['x0']] + [page.width-30])
        fundo = min([p['top']-3 for p,_ in rotulos if p['top'] > palavra['bottom']] + [palavra['bottom']+60])
        if direita <= palavra['x0'] or fundo <= palavra['bottom']:
            continue
        texto = page.crop((palavra['x0'], palavra['bottom']+1, direita, fundo)).extract_text() or ''
        for linha in texto.splitlines():
            if _normalizar_texto(linha).strip(' /:') in {'applicant','manufacturer','requerente','solicitante','fabricante'}:
                continue
            if len(re.findall(r'[A-Za-z]', linha)) >= 5:
                resultado[campo] = _limpar_texto(linha)
                break
    return resultado


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

    def _normalizar_norma_numero(numero):
        return re.sub(r"\D+", "", str(numero or ""))

    def _adicionar_norma(saida, tipo, numero):
        numero_norm = _normalizar_norma_numero(numero)

        if not numero_norm:
            return

        if tipo == "ato":
            item = f"Ato nº {numero_norm}"
        elif tipo == "resolucao":
            item = f"Resolução nº {numero_norm}"
        else:
            return

        chave = _normalizar_texto(item)

        if chave not in { _normalizar_texto(x) for x in saida }:
            saida.append(item)

    # Recorte preferencial do bloco "Normas Aplicáveis"
    bloco = texto

    m = re.search(
        r"Normas\s+Aplic[aá]veis\s*/?\s*Applicable\s+Standards\s*:?(?P<bloco>.*?)(?:Laborat[oó]rio|Laboratories|Relat[oó]rio|Reports|Informa[cç][oõ]es\s+Adicionais|Additional\s+Information|$)",
        texto,
        flags=re.I | re.S,
    )

    if m:
        bloco = m.group("bloco")

    normas = []

    for m_ato in re.finditer(
        r"\bAto(?:\s+ANATEL)?\s*n?[º°o]?\s*\.?\s*([\d.\s]+)",
        bloco,
        flags=re.I,
    ):
        _adicionar_norma(normas, "ato", m_ato.group(1))

    for m_res in re.finditer(
        r"\bResolu[cç][aã]o\s*n?[º°o]?\s*\.?\s*([\d.\s]+)",
        bloco,
        flags=re.I,
    ):
        _adicionar_norma(normas, "resolucao", m_res.group(1))

    # Fallback no texto completo, caso o recorte do bloco falhe.
    if not normas:
        for m_ato in re.finditer(
            r"\bAto(?:\s+ANATEL)?\s*n?[º°o]?\s*\.?\s*([\d.\s]+)",
            texto,
            flags=re.I,
        ):
            _adicionar_norma(normas, "ato", m_ato.group(1))

        for m_res in re.finditer(
            r"\bResolu[cç][aã]o\s*n?[º°o]?\s*\.?\s*([\d.\s]+)",
            texto,
            flags=re.I,
        ):
            _adicionar_norma(normas, "resolucao", m_res.group(1))

    return "; ".join(normas)


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

    # Remove espaços também para capturar cabeçalhos que o PDF junta.
    # Ex.: "FaixadeFrequência(MHz)".
    texto_sem_espaco = re.sub(r"\s+", "", texto)

    tem_faixa = (
        "faixa de frequencia" in texto
        or "faixa de frequencias" in texto
        or "faixa frequencia" in texto
        or "faixa frequencias" in texto
        or "faixa de frequencia tx" in texto
        or "faixa de frequencias tx" in texto
        or "frequency range" in texto
        or "range mhz" in texto
        or "faixadefrequencia" in texto_sem_espaco
        or "faixadefrequencias" in texto_sem_espaco
        or "frequencyrange" in texto_sem_espaco
    )

    tem_potencia = (
        "potencia maxima de saida" in texto
        or "potencia maxima saida" in texto
        or "potencia maxima" in texto
        or "potencia de saida" in texto
        or "potencia saida" in texto
        or "maximum output power" in texto
        or "output power" in texto
        or "tx power" in texto
        or "power w" in texto
        or "potenciamaximadesaida" in texto_sem_espaco
        or "potenciadesaida" in texto_sem_espaco
        or "maximumoutputpower" in texto_sem_espaco
        or "outputpower" in texto_sem_espaco
    )

    tem_intensidade = (
        "intensidade de campo" in texto
        or "intensidade campo" in texto
        or "field strength" in texto
        or "electric field strength" in texto
        or "uv m" in texto
        or "uv/m" in texto
        or "intensidadedecampo" in texto_sem_espaco
        or "fieldstrength" in texto_sem_espaco
        or "electricfieldstrength" in texto_sem_espaco
    )

    tem_designacao = (
        "designacao de emissoes" in texto
        or "designacao das emissoes" in texto
        or "designacao emissoes" in texto
        or "designation of emission" in texto
        or "designation of emissions" in texto
        or "emission designation" in texto
        or "designacaodeemissoes" in texto_sem_espaco
        or "designacaodasemissoes" in texto_sem_espaco
        or "designationofemission" in texto_sem_espaco
        or "designationofemissions" in texto_sem_espaco
        or "emissiondesignation" in texto_sem_espaco
    )

    tem_tecnologia = (
        "tecnologia" in texto
        or "technology" in texto
        or "spread spectrum" in texto
        or "espalhamento" in texto
        or "tecnologiaespalhamento" in texto_sem_espaco
        or "technologyspread" in texto_sem_espaco
    )

    tem_modulacao = (
        "modulacao" in texto
        or "modulation" in texto
        or "tipo de modulacao" in texto
        or "type of modulation" in texto
        or "tipodemodulacao" in texto_sem_espaco
        or "typeofmodulation" in texto_sem_espaco
    )

    tem_sar = (
        "sar cabeca" in texto
        or "sar cabeça" in texto
        or "sar head" in texto
        or "sar corpo" in texto
        or "sar body" in texto
        or "sarcabeca" in texto_sem_espaco
        or "sarhead" in texto_sem_espaco
        or "sarcorpo" in texto_sem_espaco
        or "sarbody" in texto_sem_espaco
    )

    tem_taxa = (
        "taxa de transmissao" in texto
        or "taxa transmissao" in texto
        or "transmission rate" in texto
        or "taxadetransmissao" in texto_sem_espaco
        or "transmissionrate" in texto_sem_espaco
    )

    tem_padrao = (
        "padrao" in texto
        or "standard" in texto
    )

    # Regra:
    # precisa ter faixa e pelo menos uma coluna técnica forte.
    # Normalmente potência aparece sempre, mas alguns CCTs podem ter intensidade.
    tem_coluna_principal = tem_potencia or tem_intensidade

    tem_coluna_tecnica_auxiliar = (
        tem_designacao
        or tem_tecnologia
        or tem_modulacao
        or tem_sar
        or tem_taxa
        or tem_padrao
    )

    return tem_faixa and (tem_coluna_principal or tem_coluna_tecnica_auxiliar)


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


def _extrair_tabela_tecnica_cct_do_texto(texto):
    """
    Fallback por texto completo para CCTs cuja tabela técnica é quebrada
    entre páginas.

    Extrai:
    - Faixa de Frequência/Frequências (MHz)
    - Potência Máxima de Saída (W)
    - Designação de Emissões

    Especialmente útil para CCTs da Moderna, em que o pdfplumber pode
    extrair só a primeira página da tabela e ignorar a continuação.
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

    for i in range(len(linhas)):
        janela = " ".join(linhas[i:i + 25])
        janela_norm = _normalizar_texto(janela)

        tem_faixa = (
            "faixa de frequencia" in janela_norm
            or "faixa de frequencias" in janela_norm
            or "frequency range" in janela_norm
        )

        tem_potencia = (
            "potencia maxima de saida" in janela_norm
            or "potencia maxima" in janela_norm
            or "potencia de saida" in janela_norm
            or "output power" in janela_norm
            or "maximum output power" in janela_norm
        )

        tem_designacao = (
            "designacao de emissoes" in janela_norm
            or "designation of emission" in janela_norm
            or "emission designation" in janela_norm
        )

        if tem_faixa and tem_potencia and tem_designacao:
            idx_inicio = i
            break

    if idx_inicio is None:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    trecho = linhas[idx_inicio: idx_inicio + 260]

    padrao_faixa = re.compile(
        r"(\d[\d.,]*\s*(?:a|ate|até|-|–|—)\s*\d[\d.,]*)",
        flags=re.I,
    )

    padrao_potencia = re.compile(
        r"(?<![A-Z0-9])(\d+[,.]\d+)(?![A-Z0-9])",
        flags=re.I,
    )

    padrao_designacao = re.compile(
        r"\b(?:[0-9]+[A-Z][0-9A-Z]*[A-Z]|[0-9]+[A-Z]{1,3}[0-9A-Z]*)\b",
        flags=re.I,
    )

    linhas_saida = []
    ultima_faixa = ""

    for linha in trecho:
        linha_limpa = _limpar_texto(linha)
        linha_norm = _normalizar_texto(linha_limpa)

        if not linha_limpa:
            continue

        # Para ao sair da tabela técnica.
        if linhas_saida and any(
            marcador in linha_norm
            for marcador in [
                "observacoes",
                "observacao",
                "comments",
                "informacoes adicionais",
                "comentarios adicionais",
                "relatorio",
                "relatorios",
                "laboratorio",
                "laboratorios",
                "unidade fabril",
                "historico",
                "certification history",
                "test report",
                "dados do laboratorio",
                "factory unit",
            ]
        ):
            break

        # Ignora cabeçalho repetido.
        if (
            "faixa de frequencia" in linha_norm
            and (
                "potencia" in linha_norm
                or "output power" in linha_norm
            )
        ):
            continue

        m_faixa = padrao_faixa.search(linha_limpa)

        if m_faixa:
            ultima_faixa = _limpar_texto(m_faixa.group(1))

            # Se a linha contém apenas a faixa, segue para a próxima.
            texto_sem_faixa = linha_limpa.replace(m_faixa.group(1), " ")
        else:
            texto_sem_faixa = linha_limpa

        numeros = padrao_potencia.findall(texto_sem_faixa)

        if not numeros:
            continue

        potencia = ""

        for numero in numeros:
            try:
                valor_num = float(numero.replace(".", "").replace(",", "."))
            except Exception:
                continue

            # Potência em W, normalmente valor pequeno.
            # Evita pegar frequência, taxa de transmissão, página etc.
            if 0 < valor_num <= 100:
                potencia = numero
                break

        if not potencia:
            continue

        if not ultima_faixa:
            continue

        designacao = ""

        candidatos_designacao = padrao_designacao.findall(texto_sem_faixa)

        for cand in candidatos_designacao:
            cand_limpo = str(cand or "").strip().upper()

            # Evita pegar coisas que são padrão/tecnologia.
            if cand_limpo in {
                "OFDM",
                "DSSS",
                "FHSS",
                "GFSK",
                "BPSK",
                "QPSK",
                "QAM",
                "HT20",
                "HT40",
                "VHT20",
                "VHT40",
                "VHT80",
            }:
                continue

            # Designações típicas: 1M10F7D, 16M4X9D, 36M0X9D etc.
            if re.search(r"\d", cand_limpo) and re.search(r"[A-Z]", cand_limpo):
                designacao = cand_limpo
                break

        linhas_saida.append(
            [
                ultima_faixa,
                potencia,
                designacao,
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
            "Faixa de Frequência (MHz)",
            "Potência Máxima de Saída (W)",
            "Designação de Emissões",
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



def _linha_tecnica_cct_util(linha):
    texto = _normalizar_texto(
        " ".join(str(c or "") for c in (linha or []))
    )

    if not texto:
        return False

    marcadores_fim = [
        "observacoes",
        "observacao",
        "informacoes adicionais",
        "comentarios adicionais",
        "relatorio",
        "relatorios",
        "laboratorio",
        "laboratorios",
        "unidade fabril",
        "historico",
        "certification history",
        "test report",
    ]

    if any(m in texto for m in marcadores_fim):
        return False

    return any(_limpar_texto(c) for c in linha or [])


def _linha_tecnica_cct_util(linha):
    texto = _normalizar_texto(
        " ".join(str(c or "") for c in (linha or []))
    )

    if not texto:
        return False

    # Ignora cabeçalho repetido dentro da tabela.
    if (
        "faixa de frequencia" in texto
        and (
            "potencia" in texto
            or "output power" in texto
        )
    ):
        return False

    marcadores_fim = [
        "observacoes",
        "observacao",
        "informacoes adicionais",
        "comentarios adicionais",
        "relatorio",
        "relatorios",
        "laboratorio",
        "laboratorios",
        "unidade fabril",
        "historico",
        "certification history",
        "test report",
        "relatorio de ensaio",
        "dados do laboratorio",
    ]

    if any(m in texto for m in marcadores_fim):
        return False

    return any(_limpar_texto(c) for c in linha or [])



def _extrair_tabela_tecnica_por_geometria(tabela):
    """Reconstrói cabeçalhos em várias linhas sem deslocar células mescladas."""
    bruto = tabela.extract() or []
    if not bruto:
        return None
    cab_teste = [' '.join(str(l[i] or '') for l in bruto[:3] if i < len(l))
                 for i in range(len(bruto[0]))]
    if not _linha_parece_cabecalho_tecnico_cct(cab_teste):
        return None
    primeira = tabela.rows[0].cells
    ancoras = [(i, (cel[0] + cel[2]) / 2) for i, cel in enumerate(primeira)
               if cel and str(bruto[0][i] or '').strip()]
    if len(ancoras) < 2:
        return None
    fim_cab = max(primeira[i][3] for i, _ in ancoras)
    cabecalho = [''] * len(ancoras)
    linhas = []
    ultima_faixa = ''
    for row, valores in zip(tabela.rows, bruto):
        celulas = [''] * len(ancoras)
        for cell, valor in zip(row.cells, valores):
            if not cell or not str(valor or '').strip():
                continue
            centro = (cell[0] + cell[2]) / 2
            coluna = min(range(len(ancoras)), key=lambda j: abs(ancoras[j][1] - centro))
            celulas[coluna] = ' '.join(filter(None, (celulas[coluna],
                                      re.sub(r'\s+', ' ', str(valor)).strip())))
        topo = min((c[1] for c in row.cells if c), default=fim_cab)
        if topo < fim_cab - 0.5:
            cabecalho = [' '.join(filter(None, (a, b))) for a, b in zip(cabecalho, celulas)]
            continue
        # Ruído lateral ou rodapé não deve criar uma linha nem herdar faixa.
        if not any(re.fullmatch(r'[0-9]+(?:[.,][0-9]+)?', c) for c in celulas[1:]):
            continue
        if re.search(r'[0-9]+(?:[.,][0-9]+)?\s*(?:a|[-–—])\s*[0-9]', celulas[0]):
            ultima_faixa = celulas[0]
        elif not celulas[0] and ultima_faixa:
            celulas[0] = ultima_faixa
        else:
            continue
        linhas.append(celulas)
    return [cabecalho] + linhas if linhas else None


def _chave_coluna_tecnica_cct(valor):
    texto = _normalizar_texto(valor)
    from extracao_cct import coluna, unidade
    semantica = coluna(valor)
    if semantica != 'nao_interpretado':
        return semantica + '_' + (unidade(valor) or 'unidade_ausente')
    if 'eirp' in texto:
        return 'potencia_eirp_' + ('mw' if '(mw)' in texto.replace(' ', '') else 'w')
    if 'frequenc' in texto or 'frequency' in texto:
        return 'frequencia_' + ('ghz' if 'ghz' in texto else 'mhz')
    if 'potencia' in texto or 'output power' in texto:
        return 'potencia_saida_' + ('mw' if '(mw)' in texto.replace(' ', '') else 'w')
    if 'sar' in texto:
        return 'sar_cabeca' if any(k in texto for k in ('cabeca', 'head')) else 'sar_corpo'
    for chave, termos in [('emissao', ('emiss',)), ('modulacao', ('modula',)),
                         ('tecnologia', ('tecnologia', 'technology')),
                         ('taxa', ('taxa', 'transmission rate')), ('padrao', ('padrao', 'standard'))]:
        if any(t in texto for t in termos):
            return chave
    return texto


def _extrair_tabela_tecnica_cct_de_tabelas(tabelas_brutas):
    """
    Extrai e une todas as partes da tabela técnica do CCT.

    Necessário porque alguns CCTs, como os da Moderna, quebram a tabela
    em mais de uma página. A versão antiga podia escolher apenas uma parte
    da tabela, causando CCT com 19 linhas quando havia 25.
    """
    tabelas_tecnicas = []

    for tabela in tabelas_brutas or []:
        linhas = _limpar_tabela_bruta(tabela)

        if len(linhas) < 2:
            continue

        for idx_cab in range(len(linhas)):
            cabecalho = linhas[idx_cab]

            if not _linha_parece_cabecalho_tecnico_cct(cabecalho):
                continue

            score = _pontuacao_cabecalho_tabela(cabecalho)

            if score < 6:
                continue

            corpo = linhas[idx_cab + 1:]

            corpo = [
                linha for linha in corpo
                if _linha_tecnica_cct_util(linha)
            ]

            if not corpo:
                continue

            tabela_ajustada = _ajustar_tabela_extraida(cabecalho, corpo)

            if tabela_ajustada.get("cabecalho") and tabela_ajustada.get("linhas"):
                tabelas_tecnicas.append(tabela_ajustada)

            # Já achou o cabeçalho técnico dessa tabela.
            # Pode ir para a próxima tabela bruta.
            break

    if not tabelas_tecnicas:
        return {
            "cabecalho": [],
            "linhas": [],
        }

    # Cada parte pode ter colunas distintas. Nunca alinhar pela posição.
    chaves, cabecalho_final, linhas_final, origens = [], [], [], []
    for parte in tabelas_tecnicas:
        for cab in parte['cabecalho']:
            chave = _chave_coluna_tecnica_cct(cab)
            if chave not in chaves:
                chaves.append(chave)
                cabecalho_final.append(cab)
    for indice, parte in enumerate(tabelas_tecnicas, 1):
        mapa = [chaves.index(_chave_coluna_tecnica_cct(c)) for c in parte['cabecalho']]
        for numero, linha in enumerate(parte['linhas'], 1):
            nova = [''] * len(chaves)
            for coluna, valor in zip(mapa, linha):
                nova[coluna] = valor
            linhas_final.append(nova)
            origens.append({'parte': indice, 'linha': numero})
    return {'cabecalho': cabecalho_final, 'linhas': linhas_final,
            'partes_extraidas': len(tabelas_tecnicas), 'origens_linhas': origens,
            'alinhamento_colunas': 'significado_do_cabecalho'}



def parsear_certificado_pdf(caminho_pdf):
    resultado = {
        "diagnostico_extracao": {"status": "falha_extracao", "alertas": [],
                                 "paginas_examinadas": 0},
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
        resultado['diagnostico_extracao']['alertas'].append('pdfplumber não instalado.')
        print("[PDF][WARN] pdfplumber não instalado.")
        return resultado

    if not caminho_pdf:
        resultado['diagnostico_extracao']['alertas'].append('Caminho do PDF ausente.')
        return resultado

    caminho_pdf = Path(caminho_pdf)

    if not caminho_pdf.exists():
        resultado['diagnostico_extracao']['alertas'].append('Arquivo não encontrado.')
        print(f"[PDF][WARN] Arquivo não encontrado: {caminho_pdf}")
        return resultado

    texto_total = []
    tabelas_brutas = []
    tabelas_geometricas = []
    paginas_tecnicas = []
    empresas_geometria = {}
    from extracao_cct import (montar_tabelas, extrair_complementar, qualidade, registros, reconstruir,
                              unidade, coluna, extrair_estruturas, extrair_secoes,
                              extrair_caracteristicas_eletricas, extrair_modelos_part_numbers)
    candidatos = []
    alertas_extracao = []

    try:
        documento = pdfplumber.open(caminho_pdf)
    except Exception as exc:
        resultado['diagnostico_extracao']['alertas'].append(f'PDF não pôde ser aberto: {type(exc).__name__}.')
        return resultado
    with documento as pdf:
        for numero_pagina, page in enumerate(pdf.pages, 1):
            try:
                texto_total.append(page.extract_text() or "")
            except Exception as exc:
                texto_total.append('')
                alertas_extracao.append(f'Página {numero_pagina}: falha de leitura textual ({type(exc).__name__}).')
            if numero_pagina == 1 and hasattr(page, 'extract_words'):
                try:
                    empresas_geometria = _extrair_empresas_por_geometria(page)
                except Exception as exc:
                    alertas_extracao.append(f'Nomes empresariais sem recuperação geométrica: {type(exc).__name__}.')

            try:
                for tabela in page.find_tables():
                    bruto = tabela.extract() or []
                    tabelas_brutas.append(bruto)
                    geometrica = _extrair_tabela_tecnica_por_geometria(tabela)
                    x0, topo, x1, _ = tabela.bbox
                    contexto = page.crop((x0, max(page.bbox[1], topo - 60), x1, topo)).extract_text() if topo > page.bbox[1] else ''
                    candidatos.append({'pagina': numero_pagina, 'bruto': geometrica or bruto,
                                       'bruto_original': bruto,
                                       'estrategia': 'pdfplumber_linhas',
                                       'continuacao_explicita': bool(re.search(r'\bcontinua(?:ção|cao|tion)\b', contexto or '', re.I))})
                    if geometrica:
                        tabelas_geometricas.append(geometrica)
                        paginas_tecnicas.append(numero_pagina)
            except Exception as exc:
                alertas_extracao.append(f'Página {numero_pagina}: {type(exc).__name__} na extração por linhas.')
            # Alinhamento textual é complementar à geometria, na mesma página.
            if not any(c['pagina'] == numero_pagina and montar_tabelas([c]) for c in candidatos):
                try:
                    for bruto in page.extract_tables({'vertical_strategy': 'text', 'horizontal_strategy': 'text'}):
                        candidatos.append({'pagina': numero_pagina, 'bruto': bruto,
                                           'estrategia': 'pdfplumber_texto',
                                           'continuacao_explicita': False})
                except Exception as exc:
                    alertas_extracao.append(f'Página {numero_pagina}: {type(exc).__name__} no alinhamento textual.')

    texto = "\n".join(texto_total)
    texto_limpo = _limpar_texto(texto)
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    resultado["texto_completo"] = texto
    estruturas = extrair_estruturas(candidatos)
    secoes = extrair_secoes(texto_total)
    resultado['estruturas_documento'] = estruturas
    resultado['secoes_documento'] = secoes
    resultado['caracteristicas_eletricas'] = extrair_caracteristicas_eletricas(secoes)
    resultado['modelos_part_numbers'] = extrair_modelos_part_numbers(estruturas)

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
    if any(rotulo in _normalizar_texto(resultado['modelo']) for rotulo in ('nome comercial', 'trade name')):
        resultado['modelo'] = _extrair_modelo_do_texto(linhas)

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
    resultado.update(empresas_geometria)

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
    if not resultado['tipo_produto']:
        for i, linha in enumerate(linhas):
            if re.match(r'(?i)^tipo de produto\s*:', linha):
                resultado['tipo_produto'] = linha.split(':', 1)[1].strip()
                if not resultado['tipo_produto']:
                    for seguinte in linhas[i+1:i+4]:
                        if _normalizar_texto(seguinte) not in {'type of product', 'tipo de produto'}:
                            resultado['tipo_produto'] = seguinte
                            break
                break

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

    # Layout Moderna: cabeçalho "Emissão 07/09/2026", sem "Data de".
    # Captura direta para não associar o rótulo a datas de outras seções.
    if not resultado["data_emissao"]:
        emissao_direta = re.search(
            r"\bemiss[aã]o\s*:?\s*(\d{2}/\d{2}/\d{4})", texto, flags=re.I
        )
        if emissao_direta:
            resultado["data_emissao"] = emissao_direta.group(1)
    resultado["data_manutencao"] = _extrair_data_por_rotulo(
        texto, [r"data de manuten[cç][aã]o"]
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
    resultado.update(_extrair_datas_cabecalho(texto_total[0] if texto_total else ''))

    if resultado["homologacao"] in {
        item.get("codigo_anatel")
        for item in resultado.get("homologacoes_vinculadas", [])
        if item.get("codigo_anatel")
    }:
        resultado["homologacao"] = ""

    if not resultado["ocd"]:
        resultado["ocd"] = _extrair_ocd_do_texto(texto, linhas)
    # Nomes impressos completos têm prioridade sobre referências a termos de OCD.
    for nome in ('Moderna Tecnologia LTDA', 'NCC Certificações do Brasil Ltda', 'FUNDAÇÃO CPQD'):
        if _normalizar_texto(nome) in _normalizar_texto(texto):
            resultado['ocd'] = nome
            break

    obs = _classificar_observacao_cct(texto)
    resultado["observacao_classificacao"] = obs["observacao_classificacao"]
    resultado["observacao_texto"] = obs["observacao_texto"]
    resultado["observacao_motivos"] = obs["observacao_motivos"]

    tabela_cct_tabelas = _extrair_tabela_tecnica_cct_de_tabelas(tabelas_geometricas or tabelas_brutas)
    if tabelas_geometricas:
        tabela_cct_tabelas['paginas_origem'] = paginas_tecnicas
        for origem in tabela_cct_tabelas.get('origens_linhas') or []:
            origem['pagina'] = paginas_tecnicas[origem['parte'] - 1]
    tabela_cct_texto = _extrair_tabela_tecnica_cct_do_texto(texto)

    linhas_tabelas = len(tabela_cct_tabelas.get("linhas", []) or [])
    linhas_texto = len(tabela_cct_texto.get("linhas", []) or [])

    if linhas_texto > linhas_tabelas and not tabelas_geometricas:
        tabela_cct = tabela_cct_texto
        tabela_cct["origem_extracao"] = "texto_completo"
    else:
        tabela_cct = tabela_cct_tabelas
        tabela_cct["origem_extracao"] = "pdfplumber_extract_tables"

    # Cada tabela mantém seu contexto. A visão legada reúne colunas por significado,
    # sem declarar que duas tabelas distintas sejam continuações uma da outra.
    tabelas = montar_tabelas(candidatos)
    paginas_cobertas = {p for t in tabelas for p in t['paginas_origem']}
    paginas_suspeitas = {i for i, t in enumerate(texto_total, 1)
                         if re.search(r'frequenc|frequency', _normalizar_texto(t))
                         and re.search(r'potencia maxima de saida|potencia de saida|output power|intensidade de campo|potencia eirp', _normalizar_texto(t))}
    outro_contexto_tecnico = bool(resultado['caracteristicas_eletricas'] or resultado['modelos_part_numbers'])
    if (not tabelas and texto.strip() and not outro_contexto_tecnico) or paginas_suspeitas - paginas_cobertas or any(qualidade(t)[2] < 0 or qualidade(t)[0] < qualidade(t)[1] for t in tabelas):
        try:
            alternativas = montar_tabelas(extrair_complementar(caminho_pdf))
            for alternativa in alternativas:
                mesma = [t for t in tabelas if t['paginas_origem'] == alternativa['paginas_origem']
                         and [_chave_coluna_tecnica_cct(c) for c in t['cabecalho']] ==
                             [_chave_coluna_tecnica_cct(c) for c in alternativa['cabecalho']]]
                if mesma:
                    anterior = max(mesma, key=qualidade)
                    if qualidade(alternativa) > qualidade(anterior):
                        tabelas[tabelas.index(anterior)] = alternativa
                elif not any(t['paginas_origem'] == alternativa['paginas_origem'] for t in tabelas):
                    tabelas.append(alternativa)
                else:
                    alertas_extracao.append('Extratores discordam da estrutura na mesma página; revisar manualmente.')
        except (ImportError, AttributeError, RuntimeError, ValueError) as exc:
            alertas_extracao.append(f'Complemento PyMuPDF indisponível: {type(exc).__name__}.')
    tabelas, avisos_continuidade, reconstruidas = reconstruir(tabelas)
    alertas_extracao.extend(avisos_continuidade)
    if tabelas:
        chaves, cabecalho, corpo, origens = [], [], [], []
        for tab in tabelas:
            for c in tab['cabecalho']:
                chave = _chave_coluna_tecnica_cct(c)
                if chave not in chaves:
                    chaves.append(chave)
                    cabecalho.append(c)
        for tab in tabelas:
            for l, origem in zip(tab['linhas'], tab['origens_linhas']):
                nova = [''] * len(chaves)
                for c, v in zip(tab['cabecalho'], l):
                    nova[chaves.index(_chave_coluna_tecnica_cct(c))] = v
                corpo.append(nova)
                origens.append(origem)
        tabela_cct = {'cabecalho': cabecalho, 'linhas': corpo, 'origens_linhas': origens,
                      'paginas_origem': sorted({p for t in tabelas for p in t['paginas_origem']}),
                      'origem_extracao': ', '.join(dict.fromkeys(t['origem_extracao'] for t in tabelas)),
                      'tabelas_identificadas': tabelas}
    regs, descartadas = registros(tabela_cct)
    if qualidade(tabela_cct)[1] < len(regs):
        alertas_extracao.append('Registros técnicos duplicados: associação exige revisão manual.')
    if not tabelas and tabela_cct.get('linhas'):
        alertas_extracao.append('Extração legada sem proveniência completa; revisar associações de frequência e potência.')
    campos = [_chave_coluna_tecnica_cct(c) for c in tabela_cct.get('cabecalho') or []]
    sem_rf = not regs and not paginas_suspeitas and bool(resultado['caracteristicas_eletricas'] or resultado['modelos_part_numbers'])
    resultado['diagnostico_extracao'] = {
        'status': ('sem_texto_interpretavel' if not texto.strip() else 'sem_tabela_rf' if sem_rf else 'falha_extracao' if not regs else
                   'ambigua' if alertas_extracao else 'parcial' if descartadas or qualidade(tabela_cct)[0] < len(regs) or paginas_suspeitas - {p for t in tabelas for p in t['paginas_origem']} else 'valida'),
        'paginas_examinadas': len(texto_total), 'tabelas_encontradas': len(estruturas),
        'candidatos_extracao': len(candidatos),
        'tabelas_tecnicas': len(tabelas), 'paginas_utilizadas': tabela_cct.get('paginas_origem', []),
        'linhas_recuperadas': len(tabela_cct.get('linhas') or []),
        'linhas_aproveitaveis': len({r['linha_origem'] for r in regs if any(r[k] is not None for k in ('potencia_saida_w', 'potencia_eirp_w', 'intensidade_campo_uv_m'))}),
        'intervalos_normalizados': len(regs), 'linhas_descartadas': descartadas,
        'cabecalhos': tabela_cct.get('cabecalho', []), 'campos_identificados': campos,
        'estrategia': tabela_cct.get('origem_extracao'), 'alertas': alertas_extracao,
        'unidades_reconhecidas': sorted({unidade(c) for c in tabela_cct.get('cabecalho') or [] if unidade(c)}),
        'campos_nao_interpretados': [c for c in tabela_cct.get('cabecalho') or [] if coluna(c) == 'nao_interpretado'],
        'indicios_layout': [nome for nome in ('cpqd', 'ncc', 'moderna') if re.search(r'\b' + nome + r'\b', texto, re.I)],
        'tabelas_reconstruidas': reconstruidas,
        'comparabilidade_rf': 'nao_aplicavel' if sem_rf else 'disponivel' if regs else 'inconclusiva',
        'tipos_tabelas': {tipo:sum(t['tipo'] == tipo for t in estruturas) for tipo in sorted({t['tipo'] for t in estruturas})},
        'tipos_secoes': {tipo:sum(t['tipo'] == tipo for t in secoes) for tipo in sorted({t['tipo'] for t in secoes})},
        'registros_eletricos': len(resultado['caracteristicas_eletricas']),
        'registros_modelos_part_numbers': len(resultado['modelos_part_numbers']),
        'limitacoes': ['Modulação, tecnologia, emissão, taxa e SAR linha a linha não são validados pela extração.'],
    }
    tabela_cct['registros_normalizados'] = regs
    tabela_cct['status_extracao'] = resultado['diagnostico_extracao']['status']
    resultado["tabela_tecnica_cct"] = tabela_cct

    print(
        "[PDF] Tabela técnica CCT: "
        f"pdfplumber={linhas_tabelas} linha(s) | "
        f"texto={linhas_texto} linha(s) | "
        f"usada={len(tabela_cct.get('linhas', []) or [])} linha(s) | "
        f"origem={tabela_cct.get('origem_extracao')}"
    )

    print(f"[PDF] {caminho_pdf.name}: {resultado['diagnostico_extracao']['status']}")
    return resultado
