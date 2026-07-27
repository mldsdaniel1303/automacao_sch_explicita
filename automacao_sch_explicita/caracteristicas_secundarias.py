import re
import unicodedata


TITULOS_CARACTERISTICAS_SECUNDARIAS = {
    "transceptor_radiacao_restrita":
        "O produto incorpora Transceptor de Radiação Restrita com as seguintes características:",

    "rfid":
        "O produto incorpora Sistema de Identificação por Radiofrequências com as seguintes características:",

    "equipamento_radiacao_restrita":
        "O produto incorpora Equipamento de Radiocomunicação de Radiação Restrita com as seguintes características:",

    "carregador_indutivo":
        "O produto incorpora um módulo “Carregador Indutivo para Telefone Celular” com as seguintes características técnicas:",

    "dispositivo_operacao_periodica":
        "O produto incorpora um módulo “Dispositivo de Operação Periódica” com as seguintes características técnicas:",

    "estacao_terminal_acesso":
        "O produto incorpora um módulo \"Estação Terminal de Acesso\" com as seguintes características:",

    "uwb":
        "O produto incorpora Sistemas Operando nas Faixas de RF Ultra Larga com as seguintes características:",

    "transceptor_mpo":
        "O produto incorpora Transceptor Mpo com as seguintes características:",

    "ais":
        "O produto incorpora Transceptor para Sistema Automático de Identificação de Navios com as seguintes características:",

    "movel_satelite":
        "O produto incorpora Transceptor Móvel por Satélite com as seguintes características:",

    "aplicacao_medica":
        "O produto incorpora Sistema de Aplicações Médicas com as seguintes características:",
}


CATEGORIAS_CARACTERISTICAS_SECUNDARIAS = {
    "carregador_indutivo": {
        "nome": "Carregador Indutivo para Telefone Celular",
        "aliases": [
            "carregador indutivo para telefone celular",
            "carregador indutivo",
            "wireless charger",
            "inductive charger",
            "qi charging",
        ],
    },
    "dispositivo_operacao_periodica": {
        "nome": "Dispositivo de Operação Periódica",
        "aliases": [
            "dispositivo de operacao periodica",
            "periodic operation device",
        ],
    },
    "estacao_terminal_acesso": {
        "nome": "Estação Terminal de Acesso",
        "aliases": [
            "estacao terminal de acesso",
            "terminal de acesso",
            "access terminal",
        ],
    },
    "rfid": {
        "nome": "Sistema de Identificação por Radiofrequências",
        "aliases": [
            "sistema de identificacao por radiofrequencias",
            "sistemas de identificacao por radiofrequencias",
            "identificacao por radiofrequencias",
            "radio frequency identification",
            "rfid",
        ],
    },
    "uwb": {
        "nome": "Sistemas Operando nas Faixas de RF Ultra Larga",
        "aliases": [
            "sistemas operando nas faixas de rf ultra larga",
            "faixas de rf ultra larga",
            "ultra wideband",
            "ultra larga",
            "uwb",
        ],
    },
    "transceptor_mpo": {
        "nome": "Transceptor Mpo",
        "aliases": ["transceptor mpo"],
    },
    "ais": {
        "nome": "Transceptor para Sistema Automático de Identificação de Navios",
        "aliases": [
            "transceptor para sistema automatico de identificacao de navios",
            "sistema automatico de identificacao de navios",
            "automatic identification system",
        ],
    },
    "movel_satelite": {
        "nome": "Transceptor Móvel por Satélite",
        "aliases": [
            "transceptor movel por satelite",
            "movel por satelite",
            "mobile satellite transceiver",
            "mobile satellite",
        ],
    },
    "aplicacao_medica": {
        "nome": "Sistema de Aplicações Médicas",
        "aliases": [
            "sistema de aplicacoes medicas",
            "aplicacoes medicas",
            "aplicacao medica",
            "medical application system",
            "medical application",
        ],
    },
    # Categorias genéricas ficam por último; a correspondência mais longa vence.
    "equipamento_radiacao_restrita": {
        "nome": "Equipamento de Radiocomunicação de Radiação Restrita",
        "aliases": [
            "equipamento de radiocomunicacao de radiacao restrita",
            "radiocomunicacao de radiacao restrita",
        ],
    },
    "transceptor_radiacao_restrita": {
        "nome": "Transceptor de Radiação Restrita",
        "aliases": ["transceptor de radiacao restrita"],
    },
}


def _norm(texto):
    texto = str(texto or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _texto_total_dados_pdf(dados_pdf):
    partes = []

    def percorrer(valor):
        if valor is None:
            return

        if isinstance(valor, dict):
            for v in valor.values():
                percorrer(v)
            return

        if isinstance(valor, list):
            for v in valor:
                percorrer(v)
            return

        partes.append(str(valor))

    percorrer(dados_pdf or {})
    return " ".join(partes)


def _tem(texto, termos):
    texto_norm = _norm(texto)

    for termo in termos:
        termo_norm = _norm(termo)

        if not termo_norm:
            continue

        # Para siglas curtas, usa palavra inteira.
        # Evita AIS dentro de "mais" e BLE dentro de "rechargeable".
        if len(termo_norm) <= 3:
            if re.search(rf"(^|\s){re.escape(termo_norm)}(\s|$)", texto_norm):
                return True
        else:
            if termo_norm in texto_norm:
                return True

    return False


def _detectar_caracteristicas(texto):
    return {
        "bluetooth": _tem(texto, [
            "bluetooth",
            "bluetooth low energy",
            "bluetooth le",
        ]),

        "ble": _tem(texto, [
            "ble",
            "bluetooth low energy",
            "bluetooth le",
        ]),

        "wifi": _tem(texto, [
            "wifi",
            "wi-fi",
            "802.11",
            "802 11",
            "wlan",
        ]),

        "rfid": _tem(texto, [
            "rfid",
            "radio frequency identification",
            "identificacao por radiofrequencias",
            "identificação por radiofrequências",
        ]),

        "uwb": _tem(texto, [
            "uwb",
            "ultra wideband",
            "ultra larga",
        ]),

        "satelite": _tem(texto, [
            "satellite",
            "satelite",
            "satélite",
            "mobile satellite",
            "movel por satelite",
            "móvel por satélite",
            "mss",
        ]),

        "ais": _tem(texto, [
            "ais",
            "automatic identification system",
            "sistema automatico de identificacao de navios",
            "sistema automático de identificação de navios",
        ]),

        "carregador_indutivo": _tem(texto, [
            "carregador indutivo",
            "wireless charger",
            "inductive charger",
            "qi charging",
        ]),

        "dispositivo_operacao_periodica": _tem(texto, [
            "dispositivo de operacao periodica",
            "dispositivo de operação periódica",
            "periodic operation device",
        ]),

        "estacao_terminal_acesso": _tem(texto, [
            "estacao terminal de acesso",
            "estação terminal de acesso",
            "access terminal",
            "terminal de acesso",
        ]),

        "transceptor_mpo": _tem(texto, [
            "transceptor mpo",
            "mpo",
        ]),

        "aplicacao_medica": _tem(texto, [
            "aplicacao medica",
            "aplicação médica",
            "aplicacoes medicas",
            "aplicações médicas",
            "medical application",
            "medical",
        ]),

        "dsss": _tem(texto, [
            "dsss",
            "sequencia direta",
            "sequência direta",
        ]),

        "ofdm": _tem(texto, [
            "ofdm",
        ]),

        "ofdma": _tem(texto, [
            "ofdma",
        ]),
    }



def _categoria_por_texto(texto):
    """
    Converte um título ou trecho em uma categoria canônica.

    A correspondência mais longa vence. Assim, o nome completo
    "Equipamento de Radiocomunicação de Radiação Restrita" não perde para
    uma ocorrência genérica de "Transceptor" ou "Radiação Restrita".
    """
    texto_norm = _norm(texto)

    if not texto_norm:
        return ""

    melhor_categoria = ""
    melhor_tamanho = -1

    for categoria, dados in CATEGORIAS_CARACTERISTICAS_SECUNDARIAS.items():
        termos = [dados.get("nome", ""), *(dados.get("aliases") or [])]

        for termo in termos:
            termo_norm = _norm(termo)

            if not termo_norm or termo_norm not in texto_norm:
                continue

            if len(termo_norm) > melhor_tamanho:
                melhor_categoria = categoria
                melhor_tamanho = len(termo_norm)

    return melhor_categoria


def _categoria_principal(dados_pdf):
    """Identifica a categoria principal quando o parser a disponibiliza."""
    candidatos = [
        dados_pdf.get("tipo_produto"),
        dados_pdf.get("tipo_produto_cct"),
        dados_pdf.get("categoria_produto"),
        dados_pdf.get("especificacao_principal"),
        dados_pdf.get("titulo_especificacao_principal"),
    ]

    for candidato in candidatos:
        categoria = _categoria_por_texto(candidato)
        if categoria:
            return categoria

    return ""


def _extrair_categorias_titulos_explicitos(texto):
    """
    Extrai títulos como:
    "Características como Equipamento de Radiocomunicação de Radiação Restrita:".
    """
    texto = str(texto or "")
    categorias = []
    evidencias = []

    linhas = [
        re.sub(r"\\s+", " ", linha).strip()
        for linha in texto.splitlines()
        if str(linha or "").strip()
    ]

    janelas = list(linhas)
    for indice in range(len(linhas)):
        janelas.append(" ".join(linhas[indice:indice + 3]))

    texto_continuo = re.sub(r"\\s+", " ", texto).strip()
    if texto_continuo:
        janelas.append(texto_continuo)

    marcadores = [
        "caracteristicas como",
        "caracteristicas tecnicas como",
        "caracteristicas de",
        "caracteristicas tecnicas de",
    ]

    for janela in janelas:
        janela_norm = _norm(janela)

        if not any(marcador in janela_norm for marcador in marcadores):
            continue

        categoria = _categoria_por_texto(janela)
        if not categoria or categoria in categorias:
            continue

        categorias.append(categoria)
        evidencias.append({"categoria": categoria, "texto": janela[:500]})

    return categorias, evidencias


def diagnosticar_categoria_secundaria(dados_pdf):
    """
    Decide a categoria secundária sem confundir o produto principal.

    Prioridade:
    1. Títulos explícitos "Características como ..." do CCT;
    2. Campos estruturados do parser;
    3. Um único nome completo e específico diferente do produto principal.

    Bluetooth, Wi-Fi, BLE e a palavra isolada "transceptor" nunca definem
    sozinhos o título secundário.
    """
    dados_pdf = dados_pdf or {}
    texto = (
        dados_pdf.get("texto_completo")
        or dados_pdf.get("texto")
        or _texto_total_dados_pdf(dados_pdf)
    )

    principal = _categoria_principal(dados_pdf)
    explicitas, evidencias = _extrair_categorias_titulos_explicitos(texto)
    explicitas = list(dict.fromkeys(explicitas))

    if principal:
        candidatas = [categoria for categoria in explicitas if categoria != principal]

        if len(candidatas) == 1:
            return {
                "categoria": candidatas[0],
                "status": "identificado",
                "origem": "titulo_explicito_cct_diferente_do_principal",
                "confianca": "alta",
                "categoria_principal": principal,
                "categorias_explicitas": explicitas,
                "evidencias": evidencias,
            }

        if len(candidatas) > 1:
            return {
                "categoria": "",
                "status": "revisar",
                "origem": "multiplas_categorias_secundarias_explicitas",
                "confianca": "baixa",
                "categoria_principal": principal,
                "categorias_explicitas": explicitas,
                "evidencias": evidencias,
            }

    # No padrão do CCT, o primeiro título é principal e o segundo é secundário.
    if len(explicitas) == 2:
        return {
            "categoria": explicitas[1],
            "status": "identificado",
            "origem": "segundo_titulo_explicito_cct",
            "confianca": "alta",
            "categoria_principal": explicitas[0],
            "categorias_explicitas": explicitas,
            "evidencias": evidencias,
        }

    if len(explicitas) > 2:
        return {
            "categoria": "",
            "status": "revisar",
            "origem": "mais_de_duas_categorias_explicitas",
            "confianca": "baixa",
            "categoria_principal": principal,
            "categorias_explicitas": explicitas,
            "evidencias": evidencias,
        }

    fontes_estruturadas = [
        dados_pdf.get("categoria_caracteristicas_secundarias"),
        dados_pdf.get("tipo_caracteristicas_secundarias"),
        dados_pdf.get("titulo_caracteristicas_secundarias"),
    ]

    for valor in fontes_estruturadas:
        categoria = _categoria_por_texto(valor)
        if categoria and categoria != principal:
            return {
                "categoria": categoria,
                "status": "identificado",
                "origem": "campo_estruturado_parser",
                "confianca": "alta",
                "categoria_principal": principal,
                "categorias_explicitas": explicitas,
                "evidencias": evidencias,
            }

    texto_norm = _norm(texto)
    candidatas = []

    for categoria, dados in CATEGORIAS_CARACTERISTICAS_SECUNDARIAS.items():
        if categoria == principal:
            continue

        termos = [dados.get("nome", ""), *(dados.get("aliases") or [])]
        tem_termo_especifico = any(
            len(_norm(termo)) >= 10 and _norm(termo) in texto_norm
            for termo in termos
            if _norm(termo)
        )

        if tem_termo_especifico:
            candidatas.append(categoria)

    candidatas = list(dict.fromkeys(candidatas))

    if len(candidatas) == 1:
        return {
            "categoria": candidatas[0],
            "status": "identificado",
            "origem": "termo_especifico_no_texto_cct",
            "confianca": "media",
            "categoria_principal": principal,
            "categorias_explicitas": explicitas,
            "evidencias": evidencias,
        }

    return {
        "categoria": "",
        "status": "nao_identificado" if not candidatas else "revisar",
        "origem": (
            "nenhuma_categoria_secundaria_segura"
            if not candidatas
            else "multiplas_categorias_especificas_no_texto"
        ),
        "confianca": "baixa",
        "categoria_principal": principal,
        "categorias_explicitas": explicitas,
        "candidatas_texto": candidatas,
        "evidencias": evidencias,
    }


def classificar_categoria_secundaria(dados_pdf):
    diagnostico = diagnosticar_categoria_secundaria(dados_pdf)
    return str(diagnostico.get("categoria") or "")

def inferir_caracteristicas_secundarias(dados_pdf):
    dados_pdf = dados_pdf or {}

    texto = (
        dados_pdf.get("texto_completo")
        or dados_pdf.get("texto")
        or _texto_total_dados_pdf(dados_pdf)
    )

    diagnostico = diagnosticar_categoria_secundaria(dados_pdf)
    categoria = str(diagnostico.get("categoria") or "")
    titulo = TITULOS_CARACTERISTICAS_SECUNDARIAS.get(categoria, "")
    caracteristicas = _detectar_caracteristicas(texto)

    return {
        "categoria": categoria,
        "titulo": titulo,
        "caracteristicas": caracteristicas,
        "preencher_titulo": bool(titulo),
        "status": diagnostico.get("status", ""),
        "origem": diagnostico.get("origem", ""),
        "confianca": diagnostico.get("confianca", ""),
        "categoria_principal": diagnostico.get("categoria_principal", ""),
        "categorias_explicitas": diagnostico.get("categorias_explicitas", []),
        "evidencias": diagnostico.get("evidencias", []),
        "diagnostico": diagnostico,
    }

def _achar_valor_linha_por_coluna(cabecalho, linha, termos):
    """
    Busca valor em uma linha da tabela técnica usando termos do cabeçalho.
    """
    cabecalho = cabecalho or []
    linha = linha or []

    termos_norm = [_norm(t) for t in termos]

    for idx, col in enumerate(cabecalho):
        col_norm = _norm(col)

        if any(t in col_norm for t in termos_norm):
            if idx < len(linha):
                valor = str(linha[idx] or "").strip()
                if valor:
                    return valor

    return ""


def gerar_texto_caracteristicas_secundarias(dados_pdf):
    """
    Gera o texto completo para preencher em:
    'Título/Descrição para Características Técnicas Secundárias'.

    Usa:
    - título detectado pela categoria;
    - tabela técnica do CCT.
    """
    dados_pdf = dados_pdf or {}

    info = inferir_caracteristicas_secundarias(dados_pdf)
    titulo = info.get("titulo", "").strip()

    if not titulo:
        return ""

    # Não reutiliza a tabela principal do CCT como se fosse secundária.
    tabela = (
        dados_pdf.get("tabela_tecnica_secundaria_cct")
        or dados_pdf.get("tabela_caracteristicas_secundarias")
        or {}
    )
    cabecalho = tabela.get("cabecalho") or []
    linhas = tabela.get("linhas") or []

    if not cabecalho or not linhas:
        return titulo

    blocos = [titulo, ""]

    for linha in linhas:
        faixa = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "faixa de frequencia",
                "faixa de frequências",
                "frequency range",
                "range mhz",
            ],
        )

        potencia = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "potencia maxima",
                "potência máxima",
                "maximum output power",
                "power w",
            ],
        )

        intensidade = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "intensidade de campo",
                "field strength",
            ],
        )

        distancia = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "distancia da medida",
                "measurement distance",
            ],
        )

        emissao = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "designacao de emissoes",
                "designação de emissões",
                "designation of emissions",
                "emissions",
            ],
        )

        tecnologia = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "tecnologia",
                "technology",
            ],
        )

        modulacao = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "tipo de modulacao",
                "tipo de modulação",
                "modulation",
            ],
        )

        taxa = _achar_valor_linha_por_coluna(
            cabecalho,
            linha,
            [
                "taxa de transmissao",
                "taxa de transmissão",
                "transmission rate",
                "mbit",
            ],
        )

        partes = []

        if faixa:
            partes.append(f"Faixa de Frequências Tx: {faixa} MHz")

        if potencia:
            partes.append(f"Potência Máxima de Saída: {potencia} W")

        if intensidade:
            partes.append(f"Intensidade de Campo: {intensidade} µV/m")

        if distancia:
            partes.append(f"Distância da Medida: {distancia} m")

        if emissao:
            partes.append(f"Designação de Emissões: {emissao}")

        if tecnologia:
            partes.append(f"Tecnologia: {tecnologia}")

        if modulacao:
            partes.append(f"Tipo de Modulação: {modulacao}")

        if taxa:
            partes.append(f"Taxa de Transmissão: {taxa}")

        if partes:
            blocos.append("\n".join(partes))
            blocos.append("")

    texto_final = "\n".join(blocos).strip()

    return texto_final