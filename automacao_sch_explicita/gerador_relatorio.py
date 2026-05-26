import json
import re
from datetime import datetime
from html import escape
from pathlib import Path


def _seguro(texto):
    texto = (texto or "").strip()
    proibidos = '<>:"/\\|?*'
    for ch in proibidos:
        texto = texto.replace(ch, "_")
    return texto or "sem_nome"


def _fmt_req(resultado):
    req = resultado.get("requerimento")

    if isinstance(req, dict):
        return (
            req.get("requerimento")
            or resultado.get("requerimento_numero")
            or "sem_numero"
        )

    if req:
        return str(req)

    return resultado.get("requerimento_numero") or "sem_numero"


def _fmt_analise(resultado):
    return resultado.get("analise_documental") or {}


def _fmt_dados_pdf(resultado):
    return resultado.get("dados_pdf") or {}


def _fmt_conferencia(resultado):
    return resultado.get("conferencia_sch_cct") or {}


def _fmt_alertas(resultado):
    return _fmt_analise(resultado).get("alertas", [])


def _fmt_palavras(resultado):
    return _fmt_analise(resultado).get("palavras_chave", {}).get("encontradas", {})


def _fmt_docs(resultado):
    return _fmt_analise(resultado).get("documentos_processados", {})


def _fmt_normas(resultado):
    return _fmt_analise(resultado).get("normas_aplicaveis", [])


def _fmt_ocd(resultado):
    dados_pdf = _fmt_dados_pdf(resultado)
    ocd_cct = (dados_pdf.get("ocd") or "").strip()
    return ocd_cct or "Não identificado"


def _fmt_equipamentos(resultado):
    analise = _fmt_analise(resultado)
    req = resultado.get("requerimento") or {}

    tipo_produto = ""
    if isinstance(req, dict):
        tipo_produto = req.get("tipo_produto") or ""

    return ", ".join(analise.get("equipamentos", [])) or tipo_produto or "Não identificado"

def _fmt_numero_certificado(resultado):
    return (_fmt_dados_pdf(resultado).get("numero_certificado") or "").strip() or "Não identificado"


def _fmt_homologacao(resultado):
    return (_fmt_dados_pdf(resultado).get("homologacao") or "").strip() or "Não identificado"


def _fmt_homologacoes_vinculadas(resultado):
    dados_pdf = _fmt_dados_pdf(resultado)
    vinculadas = dados_pdf.get("homologacoes_vinculadas", []) or []

    if not isinstance(vinculadas, list):
        return []

    return [
        item for item in vinculadas
        if isinstance(item, dict)
    ]


def _fmt_modelo(resultado):
    return (_fmt_dados_pdf(resultado).get("modelo") or "").strip() or "Não identificado"


def _fmt_minuta(resultado):
    return resultado.get("minuta") or {}


def _parse_iso_dt(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except Exception:
        return None


def _tempo_ativo_resultado_segundos(resultado):
    inicio = _parse_iso_dt(resultado.get("inicio"))
    fim = _parse_iso_dt(resultado.get("fim"))

    if inicio and fim and fim >= inicio:
        return round((fim - inicio).total_seconds(), 2)

    analise = _fmt_analise(resultado)
    tempo_analise = analise.get("tempo_analise_segundos")
    if isinstance(tempo_analise, (int, float)):
        return round(float(tempo_analise), 2)

    try:
        return round(float(tempo_analise or 0), 2)
    except Exception:
        return 0.0


def _tempo_ativo_total_segundos(resultados):
    return round(sum(_tempo_ativo_resultado_segundos(r) for r in resultados), 2)


def _fmt_duracao(segundos):
    try:
        segundos = float(segundos or 0)
    except Exception:
        segundos = 0.0

    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    secs = round(segundos % 60, 2)

    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{secs:05.2f}"
    return f"{minutos:02d}:{secs:05.2f}"


def _normalizar_status_conferencia(valor):
    """
    Converte valores variados em:
    C        = Conforme
    NC       = Não Conforme
    N/A      = Não Aplicável
    REVISAR  = Revisar manualmente

    Aceita booleanos, textos, dicionários e valores vazios.
    """
    if isinstance(valor, dict):
        valor = (
            valor.get("status")
            or valor.get("resultado")
            or valor.get("valor")
            or valor.get("conforme")
            or valor.get("aplicavel")
        )

    if valor is True:
        return "C"

    if valor is False:
        return "NC"

    texto_original = str(valor if valor is not None else "").strip()

    if not texto_original:
        return "N/A"

    texto = texto_original.lower()
    texto = texto.replace("não", "nao")
    texto = texto.replace("ã", "a")
    texto = texto.replace("á", "a")
    texto = texto.replace("à", "a")
    texto = texto.replace("â", "a")
    texto = texto.replace("é", "e")
    texto = texto.replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o")
    texto = texto.replace("ô", "o")
    texto = texto.replace("õ", "o")
    texto = texto.replace("ú", "u")
    texto = texto.replace("ç", "c")
    texto = re.sub(r"\s+", " ", texto).strip()

    conformes = {
        "c",
        "conforme",
        "ok",
        "sim",
        "true",
        "check",
        "checado",
        "aprovado",
        "✓",
        "✔",
    }

    nao_conformes = {
        "nc",
        "nao conforme",
        "x",
        "erro",
        "false",
        "falso",
        "divergente",
        "ausente em um dos lados",
        "ausente_em_um_dos_lados",
        "✗",
        "✕",
        "❌",
    }

    nao_aplicaveis = {
        "n/a",
        "na",
        "n.a",
        "nao aplicavel",
        "nao se aplica",
        "nao aplicavel ao caso",
        "nao_comparado",
        "nao comparado",
        "ausente nos dois",
        "ausente_nos_dois",
        "sem_tabela",
        "sem tabela",
        "nao identificado",
        "nao verificado",
    }

    revisar = {
        "revisar",
        "revisar manualmente",
        "revisao",
        "revisar_manual",
        "revisar_manualmente",
        "inconclusivo",
        "inconclusiva",
        "alerta",
        "manual",
        "pendente de revisao",
        "revisao manual",
    }

    if texto in conformes:
        return "C"

    if texto in nao_conformes:
        return "NC"

    if texto in nao_aplicaveis:
        return "N/A"

    if texto in revisar:
        return "REVISAR"

    # Fallback: textos conhecidos parcialmente
    if "diverg" in texto or "nao conforme" in texto:
        return "NC"

    if "nao aplic" in texto or "nao se aplica" in texto:
        return "N/A"

    if "revis" in texto or "inconclus" in texto or "alerta" in texto:
        return "REVISAR"

    if texto == "ok" or "conforme" in texto:
        return "C"

    return "N/A"


def _classe_status_conferencia(status):
    status = _normalizar_status_conferencia(status)

    if status == "C":
        return "status-c"

    if status == "NC":
        return "status-nc"

    if status == "REVISAR":
        return "status-revisar"

    return "status-na"

def _td_status_conferencia(valor):
    status = _normalizar_status_conferencia(valor)
    classe = _classe_status_conferencia(status)

    titulos = {
        "C": "Conforme",
        "NC": "Não Conforme",
        "N/A": "Não Aplicável",
        "REVISAR": "Revisar manualmente",
    }

    detalhe = ""

    if isinstance(valor, dict):
        motivo = valor.get("motivo", "")
        evidencia = valor.get("evidencia", "")
        esperado = valor.get("esperado", "")

        partes = []
        if motivo:
            partes.append(f"Motivo: {motivo}")
        if esperado:
            partes.append(f"Esperado: {esperado}")
        if evidencia:
            partes.append(f"Evidência: {evidencia}")

        detalhe = " | ".join(partes)

    titulo = detalhe or titulos.get(status, status)

    return (
        f'<td class="status-cell {classe}" title="{escape(titulo)}">'
        f"{escape(status)}"
        "</td>"
    )

def _legenda_status_conferencia():
    return (
        '<div class="legenda-status">'
        '<span class="status-cell status-c">C</span> Conforme '
        '<span class="status-cell status-nc">NC</span> Não Conforme '
        '<span class="status-cell status-na">N/A</span> Não Aplicável '
        '<span class="status-cell status-revisar">REVISAR</span> Revisar manualmente'
        '</div>'
    )



def _criar_tabela_normas(normas):
    if not normas:
        return "<p>Nenhuma norma aplicável identificada.</p>"

    linhas = [
        _legenda_status_conferencia(),
        "<table><thead><tr><th>Status</th><th>Norma</th><th>Motivador(es)</th></tr></thead><tbody>",
    ]

    for item in normas:
        status = item.get("status", "")

        linhas.append(
            "<tr>"
            f"{_td_status_conferencia(status)}"
            f"<td>{escape(str(item.get('norma', '')))}</td>"
            f"<td>{escape(str(item.get('motivadores', '')))}</td>"
            "</tr>"
        )

    linhas.append("</tbody></table>")
    return "".join(linhas)


def _criar_tabela_relatorios(relatorios):
    if not relatorios:
        return "<p>Nenhum relatório de ensaio processado.</p>"

    linhas = [
        _legenda_status_conferencia(),
        "<table><thead><tr><th>Documento</th><th>Lab</th><th>Sol</th><th>Fab</th><th>Mod</th></tr></thead><tbody>",
    ]

    for item in relatorios:
        linhas.append(
            "<tr>"
            f"<td>{escape(str(item.get('documento', '')))}</td>"
            f"{_td_status_conferencia(item.get('lab'))}"
            f"{_td_status_conferencia(item.get('sol'))}"
            f"{_td_status_conferencia(item.get('fab'))}"
            f"{_td_status_conferencia(item.get('mod'))}"
            "</tr>"
        )

    linhas.append("</tbody></table>")
    return "".join(linhas)


def _criar_tabela_outros(outros):
    if not outros:
        return "<p>Nenhum outro documento processado.</p>"

    linhas = ["<table><thead><tr><th>Documento</th><th>Categoria</th></tr></thead><tbody>"]
    for item in outros:
        linhas.append(
            "<tr>"
            f"<td>{escape(str(item.get('documento', '')))}</td>"
            f"<td>{escape(str(item.get('categoria', '')))}</td>"
            "</tr>"
        )
    linhas.append("</tbody></table>")
    return "".join(linhas)


def _css():
    return """
    <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #111; line-height: 1.45; }
    h1, h2, h3, h4 { color: #111; }
    .sumario { background: #f6f7fb; padding: 16px; border-radius: 10px; }
    .alerta { background: #fff4e5; border-left: 5px solid #f59e0b; padding: 10px 12px; margin: 8px 0; }
    .ok { background: #ecfdf5; border-left: 5px solid #10b981; padding: 10px 12px; margin: 8px 0; }

    table { border-collapse: collapse; width: 100%; margin: 12px 0 24px 0; }
    th, td { border: 1px solid #d1d5db; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; }

    .status-cell {
        text-align: center;
        font-weight: bold;
        min-width: 44px;
        white-space: nowrap;
    }

    .status-c {
        background: #d4edda;
        color: #155724;
    }

    .status-nc {
        background: #f8d7da;
        color: #721c24;
    }

    .status-na {
        background: #e2e3e5;
        color: #383d41;
    }

    .status-revisar {
        background: #fef3c7;
        color: #92400e;
    }

    .legenda-status {
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
        margin: 8px 0 10px 0;
        font-size: 13px;
        color: #374151;
    }

    .legenda-status .status-cell {
        display: inline-block;
        border: 1px solid #d1d5db;
        padding: 3px 8px;
        min-width: 36px;
        border-radius: 4px;
        margin-left: 8px;
    }

    .muted { color: #666; }
    .small { font-size: 12px; }
    .break { page-break-before: always; margin-top: 48px; }
    ul { margin-top: 6px; }
    code { background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }
    </style>
    """


def _nome_humano_campo(campo):
    nomes = {
        "certificado": "Certificado",
        "homologacao": "Homologação",
        "modelo": "Modelo",
        "fabricante": "Fabricante",
        "tipo_produto": "Tipo do produto",
    }
    return nomes.get(campo, str(campo or "").replace("_", " ").title())


def _construir_mensagens_conferencia(conferencia):
    conferencia = conferencia or {}
    mensagens = conferencia.get("mensagens_humanas") or []
    if mensagens:
        return mensagens

    divergencias = conferencia.get("divergencias", []) or []
    mensagens = []

    for item in divergencias:
        nome_campo = _nome_humano_campo(item.get("campo", ""))

        valor_sch = (item.get("valor_sch") or "").strip() or "não foi identificado"
        valor_cct = (item.get("valor_cct") or "").strip() or "não foi identificado"

        mensagens.append(
            f'{nome_campo}: no SCH está "{valor_sch}", mas no CCT está "{valor_cct}".'
        )

    return mensagens


def _extrair_itens_de_mensagens(mensagens):
    itens = []

    padrao = re.compile(
        r'^(?P<campo>.+?): no SCH está "(?P<sch>.*?)", mas no CCT está "(?P<cct>.*?)"\.$',
        re.IGNORECASE,
    )

    mapa_campos = {
        "certificado": "certificado",
        "homologação": "homologacao",
        "homologacao": "homologacao",
        "modelo": "modelo",
        "fabricante": "fabricante",
        "tipo do produto": "tipo_produto",
    }

    for msg in mensagens or []:
        texto = str(msg or "").strip()
        m = padrao.match(texto)
        if not m:
            continue

        campo_txt = m.group("campo").strip().lower()
        campo = mapa_campos.get(campo_txt, campo_txt.replace(" ", "_"))

        itens.append(
            {
                "campo": campo,
                "valor_sch": m.group("sch").strip(),
                "valor_cct": m.group("cct").strip(),
                "status": "divergente",
            }
        )

    return itens


def _valor_html(valor):
    return escape(str(valor or "Não identificado"))


def _criar_tabela_campos(titulo, linhas):
    corpo = [
        f"<h3>{escape(titulo)}</h3>",
        "<table><thead><tr><th>Campo</th><th>Valor</th></tr></thead><tbody>",
    ]

    for campo, valor in linhas:
        corpo.append(
            "<tr>"
            f"<td>{escape(str(campo))}</td>"
            f"<td>{_valor_html(valor)}</td>"
            "</tr>"
        )

    corpo.append("</tbody></table>")
    return "".join(corpo)


def _linhas_tabela_sch(resultado):
    req = resultado.get("requerimento") or {}
    return [
        ("Requerimento", req.get("requerimento", "")),
        ("Homologação", req.get("homologacao", "")),
        ("Certificado", req.get("certificado", "")),
        ("Tipo do produto", req.get("tipo_produto", "")),
        ("Modelo", req.get("modelo", "")),
        ("Solicitante", req.get("solicitante", "")),
        ("Fabricante", req.get("fabricante", "")),
        ("Data de conclusão", req.get("data_conclusao", "")),
    ]


def _linhas_tabela_cct(resultado):
    dados_pdf = _fmt_dados_pdf(resultado)

    return [
        ("Número do certificado", dados_pdf.get("numero_certificado", "")),
        ("Homologação principal", dados_pdf.get("homologacao", "")),
        ("Data de emissão", dados_pdf.get("data_emissao", "")),
        ("Data de validade", dados_pdf.get("data_validade", "")),
        ("Tipo do produto", dados_pdf.get("tipo_produto", "")),
        ("Modelo", dados_pdf.get("modelo", "")),
        ("Fabricante", dados_pdf.get("fabricante", "")),
        ("Solicitante", dados_pdf.get("solicitante", "")),
        ("OCD/OCP", dados_pdf.get("ocd", "")),
        ("Código OCP", dados_pdf.get("ocp_codigo", "")),
        ("Regulamentos/Normas", dados_pdf.get("regulamentos", "")),
        ("Classificação da observação", dados_pdf.get("observacao_classificacao", "")),
    ]

def _criar_tabela_comparacao(resultado):
    conferencia = _fmt_conferencia(resultado)
    comparacoes = conferencia.get("comparacoes", []) or []
    divergencias = conferencia.get("divergencias", []) or []
    mensagens = conferencia.get("mensagens_humanas", []) or []

    itens = comparacoes or divergencias

    if not itens:
        itens = _extrair_itens_de_mensagens(mensagens)

    if not itens:
        req = resultado.get("requerimento") or {}
        dados_pdf = _fmt_dados_pdf(resultado)

        itens = [
            {
                "campo": "certificado",
                "valor_sch": req.get("certificado", ""),
                "valor_cct": dados_pdf.get("numero_certificado", ""),
                "status": "não_comparado",
            },
            {
                "campo": "homologacao",
                "valor_sch": req.get("homologacao", ""),
                "valor_cct": dados_pdf.get("homologacao", ""),
                "status": "não_comparado",
            },
            {
                "campo": "modelo",
                "valor_sch": req.get("modelo", ""),
                "valor_cct": dados_pdf.get("modelo", ""),
                "status": "não_comparado",
            },
            {
                "campo": "fabricante",
                "valor_sch": req.get("fabricante", ""),
                "valor_cct": dados_pdf.get("fabricante", ""),
                "status": "não_comparado",
            },
            {
                "campo": "tipo_produto",
                "valor_sch": req.get("tipo_produto", ""),
                "valor_cct": dados_pdf.get("tipo_produto", ""),
                "status": "não_comparado",
            },
        ]

    linhas = [
        "<h3>Tabela comparativa SCH x CCT</h3>",
        _legenda_status_conferencia(),
        (
            "<table>"
            "<thead>"
            "<tr>"
            "<th>Campo</th>"
            "<th>SCH</th>"
            "<th>CCT</th>"
            "<th>Status</th>"
            "<th>Observação</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
        ),
    ]

    for item in itens:
        campo = _nome_humano_campo(item.get("campo", ""))
        valor_sch = str(item.get("valor_sch") or "").strip() or "Não identificado"
        valor_cct = str(item.get("valor_cct") or "").strip() or "Não identificado"
        status = item.get("status", "")

        observacao = (
            item.get("observacao")
            or item.get("motivo")
            or item.get("mensagem")
            or ""
        )

        status_para_celula = status

        if status == "ok":
            status_para_celula = "C"

        elif status in {"divergente", "ausente_em_um_dos_lados"}:
            status_para_celula = "NC"

        elif status in {
            "ausente_nos_dois",
            "não_comparado",
            "nao_comparado",
            "não comparado",
            "nao comparado",
        }:
            status_para_celula = "N/A"

        elif status == "homologacao_vinculada_no_cct":
            status_para_celula = "REVISAR"

            if not observacao:
                observacao = (
                    "A homologação do SCH foi encontrada no CCT apenas como "
                    "homologação vinculada/informativa. Conferir manualmente se "
                    "ela pertence ao produto principal ou a acessório/dongle/módulo."
                )

            if valor_cct == "Não identificado":
                valor_cct = "Encontrada como homologação vinculada/informativa"

        linhas.append(
            "<tr>"
            f"<td>{escape(campo)}</td>"
            f"<td>{escape(valor_sch)}</td>"
            f"<td>{escape(valor_cct)}</td>"
            f"{_td_status_conferencia(status_para_celula)}"
            f"<td>{escape(str(observacao or ''))}</td>"
            "</tr>"
        )

    linhas.append("</tbody></table>")
    return "".join(linhas)

def _html_conferencia_bloco(resultado):
    conferencia = _fmt_conferencia(resultado)
    status_geral = (conferencia.get("status_geral") or "").strip().lower()

    blocos = ["<h2>Conferência SCH x CCT</h2>"]

    if status_geral == "ok":
        blocos.append("<div class='ok'>Sem incongruências entre os dados do SCH e do CCT.</div>")
    elif status_geral == "sem_cct":
        blocos.append("<div class='alerta'>Não foi possível realizar a conferência SCH x CCT porque não houve dados válidos do CCT.</div>")
    else:
        blocos.append("<div class='alerta'>Foram encontradas incongruências entre os dados do SCH e do CCT.</div>")

    blocos.append(_criar_tabela_comparacao(resultado))
    blocos.append(_criar_tabela_campos("Tabela do SCH", _linhas_tabela_sch(resultado)))
    blocos.append(_criar_tabela_campos("Tabela do CCT", _linhas_tabela_cct(resultado)))

    return "".join(blocos)



def _html_situacao_sar(resultado):
    minuta = resultado.get("minuta") or {}
    sar_minuta = resultado.get("sar_minuta") or {}

    status = (
        sar_minuta.get("status")
        or minuta.get("status")
        or "Não identificado"
    )

    mensagem = (
        sar_minuta.get("mensagem")
        or minuta.get("mensagem")
        or ""
    )

    frase = (
        sar_minuta.get("frase")
        or minuta.get("frase")
        or ""
    )

    preencher_frase = sar_minuta.get("preencher_frase", False)
    preenchida = minuta.get("preenchida", False)
    salvo = minuta.get("salvo", False)
    confirmado = minuta.get("confirmado_apos_salvar", False)

    linhas = [
        "<h2>Situação SAR / Corrigir Minuta</h2>",
        "<table><thead><tr><th>Item</th><th>Valor</th></tr></thead><tbody>",
        f"<tr><td>Status</td><td>{escape(str(status))}</td></tr>",
        f"<tr><td>Mensagem</td><td>{escape(str(mensagem or 'Não informado'))}</td></tr>",
        f"<tr><td>Frase necessária</td><td>{'Sim' if preencher_frase else 'Não'}</td></tr>",
        f"<tr><td>Frase aplicada</td><td>{escape(str(frase or 'Nenhuma'))}</td></tr>",
        f"<tr><td>Preenchida automaticamente</td><td>{'Sim' if preenchida else 'Não'}</td></tr>",
        f"<tr><td>Salva</td><td>{'Sim' if salvo else 'Não'}</td></tr>",
        f"<tr><td>Confirmada após salvar</td><td>{'Sim' if confirmado else 'Não'}</td></tr>",
        "</tbody></table>",
    ]

    return "".join(linhas)



def _html_dados_sch(resultado):
    info_adicionais = resultado.get("informacoes_adicionais") or {}
    minuta = _fmt_minuta(resultado)

    minuta_preenchida = minuta.get("preenchida", False)
    minuta_motivo = minuta.get("motivo", "")

    linhas = [
        "<h2>Dados do SCH</h2>",
        "<ul>",
        f"<li><b>Observação em Características Técnicas:</b> {escape(str(resultado.get('observacao_caracteristicas', '')))}</li>",
        f"<li><b>Informações Adicionais:</b> {escape(str(info_adicionais.get('texto', '')))}</li>",
        f"<li><b>Minuta preenchida:</b> {'Sim' if minuta_preenchida else 'Não'}</li>",
    ]

    if minuta_motivo:
        linhas.append(f"<li><b>Status da minuta:</b> {escape(str(minuta_motivo))}</li>")

    linhas.extend(
        [
            f"<li><b>CCT localizado:</b> {escape(str(resultado.get('pdf_cct', '')))}</li>",
            f"<li><b>Downloads realizados:</b> {escape(str(resultado.get('downloads_realizados', 0)))}</li>",
            "</ul>",
        ]
    )

    return "".join(linhas)



def _html_validade_cct(resultado):
    validade = resultado.get("validade_cct") or {}
    dados_pdf = _fmt_dados_pdf(resultado)

    data_emissao = (
        validade.get("data_emissao_bruta")
        or dados_pdf.get("data_emissao")
        or "Não identificada"
    )

    data_validade = (
        validade.get("data_validade_bruta")
        or dados_pdf.get("data_validade")
        or "Não identificada"
    )

    status = validade.get("status") or "nao_verificado"
    mensagem = validade.get("mensagem") or "Validade do CCT não verificada."

    dias = validade.get("dias_entre_emissao_validade", "")
    limite_2_anos = validade.get("limite_2_anos", "")

    classe = "ok" if status == "ok" else "alerta"

    linhas = [
        "<h2>Validade do CCT</h2>",
        f"<div class='{classe}'>{escape(str(mensagem))}</div>",
        "<table><thead><tr><th>Item</th><th>Valor</th></tr></thead><tbody>",
        f"<tr><td>Data de emissão</td><td>{escape(str(data_emissao))}</td></tr>",
        f"<tr><td>Data de validade</td><td>{escape(str(data_validade))}</td></tr>",
    ]

    if dias != "":
        linhas.append(
            f"<tr><td>Dias entre emissão e validade</td><td>{escape(str(dias))}</td></tr>"
        )

    if limite_2_anos:
        linhas.append(
            f"<tr><td>Limite de 2 anos após emissão</td><td>{escape(str(limite_2_anos))}</td></tr>"
        )

    linhas.extend(
        [
            f"<tr><td>Status</td><td>{escape(str(status))}</td></tr>",
            "</tbody></table>",
        ]
    )

    return "".join(linhas)


def _html_homologacoes_vinculadas(resultado):
    vinculadas = _fmt_homologacoes_vinculadas(resultado)

    if not vinculadas:
        return (
            "<h2>Homologações vinculadas/informativas no CCT</h2>"
            "<div class='ok'>Nenhuma homologação vinculada/informativa identificada no CCT.</div>"
        )

    linhas = [
        "<h2>Homologações vinculadas/informativas no CCT</h2>",
        (
            "<div class='alerta'>"
            "Foram identificadas homologações no CCT que parecem estar vinculadas "
            "a acessório, dongle, módulo ou item informativo. Conferir se não se trata "
            "da homologação principal do produto."
            "</div>"
        ),
        (
            "<table>"
            "<thead>"
            "<tr>"
            "<th>Modelo vinculado</th>"
            "<th>Código ANATEL</th>"
            "<th>Contexto extraído do CCT</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
        ),
    ]

    for item in vinculadas:
        modelo = item.get("modelo", "") or "Não identificado"
        codigo = item.get("codigo_anatel", "") or "Não identificado"
        contexto = item.get("contexto", "") or "Não informado"

        linhas.append(
            "<tr>"
            f"<td>{escape(str(modelo))}</td>"
            f"<td>{escape(str(codigo))}</td>"
            f"<td>{escape(str(contexto))}</td>"
            "</tr>"
        )

    linhas.append("</tbody></table>")

    return "".join(linhas)



def _html_requerimento(resultado):
    req_numero = _fmt_req(resultado)
    palavras = _fmt_palavras(resultado)
    normas = _fmt_normas(resultado)
    docs = _fmt_docs(resultado)
    alertas = _fmt_alertas(resultado)

    palavras_txt = " ".join([f"{escape(k)} (x{v})" for k, v in palavras.items()]) or "Nenhuma"

    alertas_html = "".join(
        [f"<div class='alerta'>{escape(a)}</div>" for a in alertas]
    ) or "<div class='ok'>Nenhum alerta identificado.</div>"

    tempo_ativo = _tempo_ativo_resultado_segundos(resultado)

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Requerimento {escape(req_numero)}</title>
        {_css()}
    </head>
    <body>
        <h1>Requerimento {escape(req_numero)}</h1>
        <p class="muted">Tempo de análise: {escape(str(tempo_ativo))} segundo(s)</p>

        <p><b>OCD:</b> {escape(_fmt_ocd(resultado))}</p>
        <p><b>Número do certificado:</b> {escape(_fmt_numero_certificado(resultado))}</p>
        <p><b>Homologação:</b> {escape(_fmt_homologacao(resultado))}</p>
        <p><b>Modelo:</b> {escape(_fmt_modelo(resultado))}</p>
        <p><b>Equipamento(s):</b> {escape(_fmt_equipamentos(resultado))}</p>

        <h2>Palavras-chave encontradas</h2>
        <p>{palavras_txt}</p>

        <h2>Alertas</h2>
        {alertas_html}

        {_html_validade_cct(resultado)}

        {_html_homologacoes_vinculadas(resultado)}

        {_html_situacao_sar(resultado)}

        <h2>Dispositivos Normativos</h2>
        <p>Abaixo estão listadas as normas aplicáveis identificadas neste requerimento.</p>

        <h3>Normas aplicáveis</h3>
        {_criar_tabela_normas(normas)}

        <h2>Documentos Processados</h2>

        <h3>Relatórios de Ensaio</h3>
        {_criar_tabela_relatorios(docs.get("relatorios_ensaio", []))}

        <h3>Outros Documentos Processados</h3>
        {_criar_tabela_outros(docs.get("outros_documentos", []))}

        {_html_conferencia_bloco(resultado)}

        {_html_dados_sch(resultado)}
    </body>
    </html>
    """

def _html_consolidado(resultados, versao_script, inicio_execucao, fim_execucao):
    total = len(resultados)
    sucessos = sum(1 for x in resultados if x.get("status") == "sucesso")
    erros = sum(1 for x in resultados if x.get("status") == "erro")
    docs = sum(int(x.get("downloads_realizados", 0) or 0) for x in resultados)

    tempo_total_decorrido_segundos = round((fim_execucao - inicio_execucao).total_seconds(), 2)
    tempo_ativo_automacao_segundos = _tempo_ativo_total_segundos(resultados)

    itens_html = []
    for idx, resultado in enumerate(resultados, start=1):
        req_numero = _fmt_req(resultado)
        palavras = _fmt_palavras(resultado)
        palavras_txt = " ".join([f"{escape(k)} (x{v})" for k, v in palavras.items()]) or "Nenhuma"

        itens_html.append(
            f"""
            <div class="break"></div>
            <h1>{idx} Requerimento {escape(req_numero)}</h1>
            <p>
                A seguir, os detalhes da análise dos documentos associados a este requerimento.
                Tempo de análise: {escape(str(_tempo_ativo_resultado_segundos(resultado)))} segundo(s).
            </p>
            <ul>
                <li><b>OCD:</b> {escape(_fmt_ocd(resultado))}</li>
                <li><b>Número do certificado:</b> {escape(_fmt_numero_certificado(resultado))}</li>
                <li><b>Homologação:</b> {escape(_fmt_homologacao(resultado))}</li>
                <li><b>Modelo:</b> {escape(_fmt_modelo(resultado))}</li>
                <li><b>Equipamento(s):</b> {escape(_fmt_equipamentos(resultado))}</li>
            </ul>

            <p><b>Lista das palavras-chave encontradas:</b> {palavras_txt}</p>

            <h2>Dispositivos Normativos</h2>
            <h3>Normas aplicáveis</h3>
            {_criar_tabela_normas(_fmt_normas(resultado))}

            <h2>Documentos Processados</h2>
            <h3>Relatórios de Ensaio</h3>
            {_criar_tabela_relatorios(_fmt_docs(resultado).get("relatorios_ensaio", []))}
            <h3>Outros Documentos Processados</h3>
            {_criar_tabela_outros(_fmt_docs(resultado).get("outros_documentos", []))}

            <h2>Alertas</h2>
            {"".join([f"<div class='alerta'>{escape(a)}</div>" for a in _fmt_alertas(resultado)]) or "<div class='ok'>Nenhum alerta identificado.</div>"}

            {_html_validade_cct(resultado)}

            {_html_homologacoes_vinculadas(resultado)}

            {_html_conferencia_bloco(resultado)}
            

            {_html_dados_sch(resultado)}
            """
        )

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Relatório Simplificado Automatizado</title>
        {_css()}
    </head>
    <body>
        <h1>Relatório Simplificado Automatizado</h1>

        <div class="sumario">
            <h2>Sumário</h2>
            <p>Este relatório apresenta os resultados da análise automatizada de requerimentos do sistema SCH.</p>

            <h2>Estatísticas Gerais</h2>
            <ul>
                <li>Requerimentos analisados: {total}</li>
                <li>Documentos processados: {docs}</li>
                <li>Tempo ativo da automação: {_fmt_duracao(tempo_ativo_automacao_segundos)}</li>
                <li>Tempo total decorrido: {_fmt_duracao(tempo_total_decorrido_segundos)}</li>
                <li>Data do processamento: {fim_execucao.strftime("%H:%M:%S %d/%m/%Y")}</li>
                <li>Versão do script: {escape(str(versao_script))}</li>
                <li>Sucessos: {sucessos}</li>
                <li>Erros: {erros}</li>
            </ul>
        </div>

        {''.join(itens_html)}
    </body>
    </html>
    """


def _salvar_texto(caminho, conteudo):
    caminho.write_text(conteudo, encoding="utf-8")


def gerar_req_report(pasta_saida, resultados, versao_script, inicio_execucao, fim_execucao):
    pasta_saida = Path(pasta_saida)
    pasta_req_report = pasta_saida / "req_report"
    pasta_req_report.mkdir(parents=True, exist_ok=True)

    html_consolidado = _html_consolidado(
        resultados=resultados,
        versao_script=versao_script,
        inicio_execucao=inicio_execucao,
        fim_execucao=fim_execucao,
    )
    _salvar_texto(pasta_req_report / "relatorio_execucao.html", html_consolidado)

    for resultado in resultados:
        req_numero = _fmt_req(resultado)
        nome_base = _seguro(req_numero)

        html_req = _html_requerimento(resultado)
        _salvar_texto(pasta_req_report / f"{nome_base}.html", html_req)

    indice = {
        "gerado_em": datetime.now().isoformat(),
        "req_report": str(pasta_req_report),
        "arquivos": sorted([p.name for p in pasta_req_report.iterdir() if p.is_file()]),
    }
    _salvar_texto(
        pasta_req_report / "index.json",
        json.dumps(indice, ensure_ascii=False, indent=2),
    )

    return pasta_req_report