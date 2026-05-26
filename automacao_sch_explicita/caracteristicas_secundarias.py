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


def classificar_categoria_secundaria(dados_pdf):
    dados_pdf = dados_pdf or {}

    texto = dados_pdf.get("texto_completo") or _texto_total_dados_pdf(dados_pdf)
    texto_norm = _norm(texto)

    caracteristicas = _detectar_caracteristicas(texto)

    # Casos específicos primeiro.
    if caracteristicas["carregador_indutivo"]:
        return "carregador_indutivo"

    if caracteristicas["aplicacao_medica"]:
        return "aplicacao_medica"

    if caracteristicas["satelite"]:
        return "movel_satelite"

    if caracteristicas["ais"]:
        return "ais"

    if caracteristicas["uwb"]:
        return "uwb"

    if caracteristicas["rfid"]:
        return "rfid"

    if caracteristicas["estacao_terminal_acesso"]:
        return "estacao_terminal_acesso"

    if caracteristicas["dispositivo_operacao_periodica"]:
        return "dispositivo_operacao_periodica"

    if caracteristicas["transceptor_mpo"]:
        return "transceptor_mpo"

    # Depois os casos genéricos de radiação restrita.
    if (
        "transceptor de radiacao restrita" in texto_norm
        or "transceptor" in texto_norm
        or caracteristicas["bluetooth"]
        or caracteristicas["wifi"]
        or caracteristicas["ble"]
    ):
        return "transceptor_radiacao_restrita"

    if (
        "equipamento de radiocomunicacao de radiacao restrita" in texto_norm
        or "radiocomunicacao de radiacao restrita" in texto_norm
        or "radiacao restrita" in texto_norm
    ):
        return "equipamento_radiacao_restrita"

    return ""


def inferir_caracteristicas_secundarias(dados_pdf):
    dados_pdf = dados_pdf or {}

    texto = dados_pdf.get("texto_completo") or _texto_total_dados_pdf(dados_pdf)

    categoria = classificar_categoria_secundaria(dados_pdf)

    titulo = TITULOS_CARACTERISTICAS_SECUNDARIAS.get(
        categoria,
        ""
    )

    caracteristicas = _detectar_caracteristicas(texto)

    return {
        "categoria": categoria,
        "titulo": titulo,
        "caracteristicas": caracteristicas,
        "preencher_titulo": bool(titulo),
    }