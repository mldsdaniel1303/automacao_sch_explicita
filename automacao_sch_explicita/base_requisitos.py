from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def normalizar_texto(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_lista(valores: List[str]) -> List[str]:
    return [normalizar_texto(v) for v in (valores or []) if str(v).strip()]


def extrair_atos_do_texto(texto: str) -> List[str]:
    """
    Extrai referências do tipo:
    - Ato nº 14448, de 04 de dezembro de 2017
    - Resolução nº 680, de 27 de junho de 2017
    """
    texto = texto or ""
    padrao = re.compile(
        r"\b(Ato|Resolucao|Resolução)\s*n[ºo°]?\s*(\d{1,6})\b",
        flags=re.I,
    )
    encontrados = []
    for tipo, numero in padrao.findall(texto):
        tipo = "Resolução" if normalizar_texto(tipo) == "resolucao" else "Ato"
        ref = f"{tipo} nº {numero}"
        if ref not in encontrados:
            encontrados.append(ref)
    return encontrados


@dataclass
class RegraProduto:
    produto: str
    categoria: str
    atos_principais: List[str] = field(default_factory=list)
    palavras_chave: List[str] = field(default_factory=list)
    secoes_relevantes: List[str] = field(default_factory=list)
    observacao_padrao: str = ""
    observacao_produto_nao_acabado: str = ""
    notas: List[str] = field(default_factory=list)
    interfaces_relevantes: List[str] = field(default_factory=list)

    def tokens_busca(self) -> List[str]:
        return list(
            {
                normalizar_texto(self.produto),
                *normalizar_lista(self.palavras_chave),
            }
        )


OBS_RADIACAO_RESTRITA = (
    "Na instalação do produto devem ser observadas as condições de uso conforme "
    "estabelecido no Regulamento sobre Equipamentos de Radiocomunicação de Radiação Restrita."
)

OBS_PRODUTO_NAO_ACABADO = (
    "Produto não acabado, de uso interno, cuja integração em outros equipamentos "
    "passíveis de homologação pode requerer nova avaliação."
)


BASE_REGRAS: List[RegraProduto] = [
    RegraProduto(
        produto="Equipamento de Radiação Restrita",
        categoria="II",
        atos_principais=["Resolução nº 680", "Ato nº 14448", "Ato nº 237"],
        palavras_chave=[
            "equipamento de radiacao restrita",
            "radiacao restrita",
            "bluetooth",
            "wifi",
            "wi-fi",
            "nfc",
            "rfid",
            "telemedicao",
            "microfone sem fio",
        ],
        secoes_relevantes=[
            "Anexo I ao Ato 14448/2017: itens 4, 5, 6, 7, 8, 9, 11, 12, 13, 15, 16, 17, 18, 19, 20 e 21",
            "Anexo I ao Ato 237/2022",
        ],
        observacao_padrao=OBS_RADIACAO_RESTRITA,
        observacao_produto_nao_acabado=OBS_PRODUTO_NAO_ACABADO,
        notas=[
            "Verificar PADFF e Regulamento sobre Canalização e Condições de Uso quando aplicável.",
        ],
    ),
    RegraProduto(
        produto="Transceptor de Radiação Restrita",
        categoria="II",
        atos_principais=["Resolução nº 680", "Ato nº 14448", "Ato nº 237"],
        palavras_chave=[
            "transceptor de radiacao restrita",
            "transceptor",
            "bluetooth",
            "ble",
            "espalhamento espectral",
            "modulacao digital",
        ],
        secoes_relevantes=[
            "Anexo I ao Ato 14448/2017: itens 4, 5, 10 e 21",
            "Anexo I ao Ato 237/2022",
        ],
        observacao_padrao=OBS_RADIACAO_RESTRITA,
        observacao_produto_nao_acabado=OBS_PRODUTO_NAO_ACABADO,
        notas=[
            "Ensaios de Bluetooth EDR devem considerar modulação mais simples e mais complexa.",
            "Verificar PADFF e Regulamento sobre Canalização e Condições de Uso quando aplicável.",
        ],
    ),
    RegraProduto(
        produto="Telefone móvel celular",
        categoria="I",
        atos_principais=["Ato nº 3152"],
        palavras_chave=[
            "telefone movel celular",
            "smartphone",
            "celular",
            "telefone celular",
            "handset",
        ],
        notas=[
            "Aplicar os requisitos do Ato 3152 na íntegra, no que for aplicável.",
        ],
    ),
    RegraProduto(
        produto="Carregador para Telefone Celular / Carregador Indutivo para Telefone Celular",
        categoria="I",
        atos_principais=["Ato nº 5155"],
        palavras_chave=[
            "carregador telefone celular",
            "carregador indutivo",
            "charger",
            "wireless charger",
        ],
        notas=[
            "Aplicar Anexo ao Ato 5155.",
        ],
    ),
    RegraProduto(
        produto="Acessório para Telefone Móvel Celular do tipo Bateria Auxiliar",
        categoria="I",
        atos_principais=["Ato nº 1120", "Ato nº 17087", "Ato nº 3484"],
        palavras_chave=[
            "bateria auxiliar",
            "power bank",
            "bateria movel celular",
        ],
        notas=[
            "Exige EMC, segurança elétrica e ensaios de segurança do Ato 3484.",
        ],
    ),
    RegraProduto(
        produto="Telefone IP / Telefone Ethernet (com fio e sem fio)",
        categoria="I",
        atos_principais=["Ato nº 17087"],
        palavras_chave=[
            "telefone ip",
            "telefone ethernet",
            "sip",
            "h323",
            "voip",
            "ata",
        ],
        notas=[
            "Para enquadramento como Telefone IP/Ethernet sem fio, deve implementar pelo menos SIP ou H.323 e atender aos testes do protocolo implementado.",
        ],
    ),
    RegraProduto(
        produto="OLT – Terminação de Linha Óptica / ONU – Unidade de Rede Óptica",
        categoria="III",
        atos_principais=["Ato nº 7869"],
        palavras_chave=[
            "olt",
            "ont",
            "onu",
            "gpon",
            "xgpon",
            "xgspon",
            "rede optica passiva",
        ],
        notas=[
            "Aplicar Ato 7869 na íntegra, no que for aplicável.",
        ],
        interfaces_relevantes=["GPON", "XGPON", "XGSPON"],
    ),
    RegraProduto(
        produto="Categoria III - produtos dependentes de interface",
        categoria="III",
        atos_principais=[],
        palavras_chave=[
            "dslam",
            "sdh",
            "e1",
            "e3",
            "stm1",
            "stm4",
            "stm16",
            "stm64",
            "multiplex",
            "rede de dados",
            "interconexao de redes",
        ],
        notas=[
            "Para Categoria III, observar requisitos específicos do produto e também as interfaces passíveis de homologação (E1, E3, STM-N) quando existirem.",
        ],
        interfaces_relevantes=["E1", "E3", "STM-1", "STM-4", "STM-16", "STM-64"],
    ),
]


def encontrar_regra_produto(produto: str) -> Optional[RegraProduto]:
    alvo = normalizar_texto(produto)
    if not alvo:
        return None

    melhor: Optional[RegraProduto] = None
    melhor_score = 0

    for regra in BASE_REGRAS:
        score = 0
        nome_regra = normalizar_texto(regra.produto)
        if nome_regra and nome_regra in alvo:
            score += 100

        for token in regra.tokens_busca():
            if token and token in alvo:
                score += max(10, len(token.split()))

        if score > melhor_score:
            melhor_score = score
            melhor = regra

    return melhor


def inferir_regra_por_contexto(
    produto_sch: str = "",
    produto_cct: str = "",
    texto_cct: str = "",
) -> Optional[RegraProduto]:
    candidatos = [
        produto_cct,
        produto_sch,
        texto_cct,
    ]
    melhor: Optional[RegraProduto] = None
    melhor_score = 0

    for texto in candidatos:
        alvo = normalizar_texto(texto)
        if not alvo:
            continue
        for regra in BASE_REGRAS:
            score = 0
            nome_regra = normalizar_texto(regra.produto)
            if nome_regra and nome_regra in alvo:
                score += 100
            for token in regra.tokens_busca():
                if token and token in alvo:
                    score += max(10, len(token.split()))
            if score > melhor_score:
                melhor_score = score
                melhor = regra

    return melhor


def comparar_campos_cct_sch(
    req_sch: Dict[str, Any],
    dados_cct: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    comparacao = {}

    pares = {
        "certificado": (
            req_sch.get("certificado", ""),
            dados_cct.get("numero_certificado", ""),
        ),
        "homologacao": (
            req_sch.get("homologacao", ""),
            dados_cct.get("homologacao", ""),
        ),
        "modelo": (
            req_sch.get("modelo", ""),
            dados_cct.get("modelo", ""),
        ),
        "fabricante": (
            req_sch.get("fabricante", ""),
            dados_cct.get("fabricante", ""),
        ),
        "tipo_produto": (
            req_sch.get("tipo_produto", ""),
            dados_cct.get("tipo_produto", "") or dados_cct.get("produto_principal", ""),
        ),
    }

    for campo, (valor_sch, valor_cct) in pares.items():
        ns = normalizar_texto(str(valor_sch))
        nc = normalizar_texto(str(valor_cct))
        if not valor_sch and not valor_cct:
            status = "vazio"
        elif valor_sch and valor_cct and ns == nc:
            status = "ok"
        elif valor_sch and valor_cct and (ns in nc or nc in ns):
            status = "compatível"
        elif valor_sch and valor_cct:
            status = "divergente"
        elif valor_sch and not valor_cct:
            status = "somente_sch"
        else:
            status = "somente_cct"

        comparacao[campo] = {
            "sch": valor_sch,
            "cct": valor_cct,
            "status": status,
            "fonte_principal": "CCT",
        }

    return comparacao


def validar_atos_esperados(regra: Optional[RegraProduto], texto_cct: str) -> Dict[str, Any]:
    atos_encontrados = extrair_atos_do_texto(texto_cct)
    if not regra:
        return {
            "atos_esperados": [],
            "atos_encontrados": atos_encontrados,
            "faltantes": [],
            "status": "sem_regra",
        }

    esperados = regra.atos_principais
    norm_encontrados = normalizar_lista(atos_encontrados)
    faltantes = []
    for ato in esperados:
        if normalizar_texto(ato) not in norm_encontrados:
            faltantes.append(ato)

    status = "ok" if not faltantes else "pendencia_ato"
    return {
        "atos_esperados": esperados,
        "atos_encontrados": atos_encontrados,
        "faltantes": faltantes,
        "status": status,
    }


def decidir_observacao_caracteristicas(
    dados_cct: Dict[str, Any],
    regra: Optional[RegraProduto],
    texto_cct: str = "",
) -> Dict[str, Any]:
    texto_cct = texto_cct or ""
    classificacao_pdf = (dados_cct or {}).get("observacao_classificacao", "")
    texto_pdf = (dados_cct or {}).get("observacao_texto", "")
    motivos_pdf = (dados_cct or {}).get("observacao_motivos", []) or []

    if texto_pdf:
        return {
            "origem": "cct",
            "classificacao": classificacao_pdf or "extraido_do_cct",
            "texto": texto_pdf,
            "motivos": motivos_pdf,
        }

    universo = normalizar_texto(texto_cct)
    sinais_nao_acabado = [
        "produto nao acabado",
        "uso interno",
        "integracao em outros equipamentos",
        "pode requerer nova avaliacao",
        "rf module",
        "module",
        "modulo",
        "oem",
    ]

    if any(s in universo for s in sinais_nao_acabado):
        return {
            "origem": "heuristica_cct",
            "classificacao": "produto_nao_acabado",
            "texto": OBS_PRODUTO_NAO_ACABADO,
            "motivos": [s for s in sinais_nao_acabado if s in universo],
        }

    if regra and regra.observacao_padrao:
        return {
            "origem": "regra_produto",
            "classificacao": "observacao_padrao_categoria",
            "texto": regra.observacao_padrao,
            "motivos": [],
        }

    return {
        "origem": "fallback",
        "classificacao": "sem_observacao",
        "texto": "",
        "motivos": [],
    }


def montar_informacoes_adicionais(
    req_sch: Dict[str, Any],
    dados_cct: Dict[str, Any],
    regra: Optional[RegraProduto],
    comparacao: Dict[str, Dict[str, Any]],
    validacao_atos: Dict[str, Any],
) -> str:
    numero = req_sch.get("requerimento", "sem_numero")
    linhas = [f"Análise preliminar automatizada do requerimento {numero}."]

    if regra:
        linhas.append(
            f"Produto enquadrado pela regra técnica como categoria {regra.categoria}: {regra.produto}."
        )

    divergentes = [k for k, v in comparacao.items() if v.get("status") == "divergente"]
    if divergentes:
        linhas.append(
            "Foram identificadas divergências entre SCH e CCT nos campos: "
            + ", ".join(divergentes)
            + "."
        )
        linhas.append("Para fins de análise, o CCT foi considerado a fonte principal.")
    else:
        linhas.append("Não foram identificadas divergências relevantes entre SCH e CCT nos campos principais comparados.")

    faltantes = validacao_atos.get("faltantes", [])
    if faltantes:
        linhas.append(
            "Atos principais esperados pela regra do produto não localizados no texto do CCT: "
            + ", ".join(faltantes)
            + "."
        )

    return " ".join(linhas)


def analisar_requerimento_por_regras(
    req_sch: Dict[str, Any],
    dados_cct: Dict[str, Any],
    texto_cct: str = "",
) -> Dict[str, Any]:
    regra = inferir_regra_por_contexto(
        produto_sch=req_sch.get("tipo_produto", ""),
        produto_cct=dados_cct.get("tipo_produto", "") or dados_cct.get("produto_principal", ""),
        texto_cct=texto_cct,
    )

    comparacao = comparar_campos_cct_sch(req_sch, dados_cct)
    validacao_atos = validar_atos_esperados(regra, texto_cct)
    observacao = decidir_observacao_caracteristicas(dados_cct, regra, texto_cct)
    informacoes_adicionais = montar_informacoes_adicionais(
        req_sch=req_sch,
        dados_cct=dados_cct,
        regra=regra,
        comparacao=comparacao,
        validacao_atos=validacao_atos,
    )

    alertas = []
    for campo, detalhe in comparacao.items():
        if detalhe["status"] == "divergente":
            alertas.append(
                f"Divergência em {campo}: SCH='{detalhe['sch']}' x CCT='{detalhe['cct']}'."
            )
    for ato in validacao_atos.get("faltantes", []):
        alertas.append(f"Ato esperado não localizado no CCT: {ato}.")
    if observacao.get("classificacao") == "produto_nao_acabado":
        alertas.append("Indício de produto não acabado / uso interno detectado a partir do CCT.")

    return {
        "fonte_principal": "CCT",
        "regra_produto": {
            "produto": regra.produto if regra else "",
            "categoria": regra.categoria if regra else "",
            "atos_principais": regra.atos_principais if regra else [],
            "secoes_relevantes": regra.secoes_relevantes if regra else [],
            "notas": regra.notas if regra else [],
            "interfaces_relevantes": regra.interfaces_relevantes if regra else [],
        },
        "comparacao_cct_x_sch": comparacao,
        "validacao_atos": validacao_atos,
        "observacao_caracteristicas": observacao,
        "informacoes_adicionais": informacoes_adicionais,
        "alertas": alertas,
    }
