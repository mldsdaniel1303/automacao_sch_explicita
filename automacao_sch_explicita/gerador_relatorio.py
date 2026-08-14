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
        "tabela_tecnica": "Tabela técnica",
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

    dados_certificado_sch = resultado.get("dados_certificado_sch") or {}
    dados_produto_sch = resultado.get("dados_produto_sch") or {}

    nome_comercial = (
        req.get("nome_comercial")
        or dados_produto_sch.get("nome_comercial")
        or dados_certificado_sch.get("nome_comercial")
        or ""
    )

    return [
        ("Requerimento", req.get("requerimento", "")),
        ("Homologação", req.get("homologacao", "")),
        ("Certificado", req.get("certificado", "")),
        ("Tipo do produto", req.get("tipo_produto", "")),
        ("Modelo", req.get("modelo", "")),
        ("Nome Comercial", nome_comercial),
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

    # Antes estava: itens = comparacoes or divergencias
    # Isso escondia divergências extras, como tabela_tecnica,
    # quando a lista comparacoes já existia.
    itens = list(comparacoes or [])

    campos_ja_incluidos = {
        item.get("campo")
        for item in itens
        if isinstance(item, dict)
    }

    for div in divergencias:
        if not isinstance(div, dict):
            continue

        campo = div.get("campo")

        if campo and campo not in campos_ja_incluidos:
            itens.append(div)
            campos_ja_incluidos.add(campo)

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
        campo_chave = item.get("campo", "")
        campo = _nome_humano_campo(campo_chave)

        valor_sch = str(item.get("valor_sch") or "").strip() or "Não identificado"
        valor_cct = str(item.get("valor_cct") or "").strip() or "Não identificado"
        status = item.get("status", "")

        observacao = (
            item.get("observacao")
            or item.get("motivo")
            or item.get("mensagem")
            or ""
        )
        if item.get("campo") == "modelo":
            modelos_sch_unicos = item.get("modelos_sch_unicos") or []
            modelos_cct_unicos = item.get("modelos_cct_unicos") or []

            if modelos_sch_unicos:
                valor_sch = ", ".join(modelos_sch_unicos)

            if modelos_cct_unicos:
                valor_cct = ", ".join(modelos_cct_unicos)

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

        elif campo_chave == "tabela_tecnica":
            status_para_celula = "NC"

            if valor_sch == "Não identificado":
                valor_sch = "Tabela técnica do SCH"

            if valor_cct == "Não identificado":
                valor_cct = "Tabela técnica do CCT"

            if not observacao:
                detalhes = item.get("detalhes_tabela") or {}
                status_tabela = detalhes.get("status", "")

                if status_tabela == "divergente":
                    observacao = (
                        "Foram encontradas divergências na tabela técnica. "
                        "Veja a seção 'Conferência da tabela técnica SCH x CCT' abaixo."
                    )
                elif status_tabela == "sem_tabela":
                    observacao = (
                        "Não foi possível comparar a tabela técnica porque uma ou ambas "
                        "as tabelas não foram identificadas."
                    )
                else:
                    observacao = "Divergência de tabela técnica identificada."

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


def _html_comparacao_tabela_tecnica(resultado):
    conferencia = _fmt_conferencia(resultado)
    comparacao = conferencia.get("comparacao_tabela_tecnica") or {}

    if not comparacao:
        for div in conferencia.get("divergencias", []) or []:
            if isinstance(div, dict) and div.get("campo") == "tabela_tecnica":
                comparacao = div.get("detalhes_tabela") or {}
                break

    if not comparacao:
        return (
            "<h3>Conferência da tabela técnica SCH x CCT</h3>"
            "<div class='alerta'>Comparação da tabela técnica não encontrada no resultado.</div>"
        )

    status = comparacao.get("status") or "nao_verificado"
    motivo = comparacao.get("motivo") or ""
    divergencias = comparacao.get("divergencias", []) or []

    linhas_sch = comparacao.get("linhas_sch", "")
    linhas_cct = comparacao.get("linhas_cct", "")

    campos_comparados = comparacao.get("campos_comparados", []) or []
    colunas_ignoradas = comparacao.get("colunas_ignoradas_do_cct", []) or []

    classe = "ok" if status == "ok" else "alerta"

    if status == "ok":
        mensagem = (
            "Tabela técnica SCH x CCT conferida sem divergências nos campos comparados."
        )
    elif status == "sem_tabela":
        mensagem = (
            "Não foi possível comparar a tabela técnica porque uma ou ambas as tabelas "
            "não foram identificadas."
        )
    elif status == "divergente":
        mensagem = "Foram encontradas divergências na tabela técnica SCH x CCT."
    else:
        mensagem = f"Status da comparação da tabela técnica: {status}"

    if motivo:
        mensagem += f" Motivo: {motivo}"

    linhas = [
        "<h3>Conferência da tabela técnica SCH x CCT</h3>",
        f"<div class='{classe}'>{escape(str(mensagem))}</div>",
        "<table><thead><tr><th>Item</th><th>Valor</th></tr></thead><tbody>",
        f"<tr><td>Status</td><td>{escape(str(status))}</td></tr>",
        f"<tr><td>Combinações técnicas comparadas no SCH</td><td>{escape(str(linhas_sch))}</td></tr>",
        f"<tr><td>Combinações técnicas comparadas no CCT</td><td>{escape(str(linhas_cct))}</td></tr>",
        f"<tr><td>Campos comparados</td><td>{escape(', '.join(str(c) for c in campos_comparados) or 'Não informado')}</td></tr>",
        f"<tr><td>Colunas ignoradas do CCT</td><td>{escape(', '.join(str(c) for c in colunas_ignoradas) or 'Não informado')}</td></tr>",
    ]

    linhas_extraidas_sch = comparacao.get("linhas_extraidas_sch", "")
    linhas_extraidas_cct = comparacao.get("linhas_extraidas_cct", "")

    if linhas_extraidas_sch != "":
        linhas.append(
            f"<tr><td>Linhas extraídas do SCH antes de remover repetidas</td><td>{escape(str(linhas_extraidas_sch))}</td></tr>"
        )

    if linhas_extraidas_cct != "":
        linhas.append(
            f"<tr><td>Linhas extraídas do CCT antes de remover repetidas</td><td>{escape(str(linhas_extraidas_cct))}</td></tr>"
        )

    linhas.append("</tbody></table>")

    if not divergencias:
        linhas.append(
            "<div class='ok'>Nenhuma divergência específica de tabela técnica foi registrada.</div>"
        )
        return "".join(linhas)

    linhas.extend(
        [
            "<h4>Divergências da tabela técnica</h4>",
            (
                "<table>"
                "<thead>"
                "<tr>"
                "<th>Tipo</th>"
                "<th>Linha</th>"
                "<th>Coluna</th>"
                "<th>Valor SCH</th>"
                "<th>Valor CCT</th>"
                "</tr>"
                "</thead>"
                "<tbody>"
            ),
        ]
    )

    for div in divergencias:
        tipo = div.get("tipo", "")
        linha = div.get("linha", "")

        coluna = (
            div.get("nome_coluna")
            or div.get("coluna")
            or ""
        )

        valor_sch = div.get("valor_sch", "")
        valor_cct = div.get("valor_cct", "")

        if tipo == "quantidade_linhas_diferente":
            coluna = "Quantidade de linhas"
            valor_sch = div.get("linhas_sch", "")
            valor_cct = div.get("linhas_cct", "")

        elif tipo == "tabela_cct_sem_linhas_comparaveis":
            coluna = "Tabela CCT"
            valor_sch = div.get("linhas_sch", "")
            valor_cct = "Sem linhas comparáveis"

        elif tipo == "tabela_sch_sem_linhas_comparaveis":
            coluna = "Tabela SCH"
            valor_sch = "Sem linhas comparáveis"
            valor_cct = div.get("linhas_cct", "")

        linhas.append(
            "<tr>"
            f"<td>{escape(str(tipo))}</td>"
            f"<td>{escape(str(linha))}</td>"
            f"<td>{escape(str(coluna))}</td>"
            f"<td>{escape(str(valor_sch))}</td>"
            f"<td>{escape(str(valor_cct))}</td>"
            "</tr>"
        )

    linhas.append("</tbody></table>")

    return "".join(linhas)


def _html_conferencia_bloco(resultado):
    conferencia = _fmt_conferencia(resultado)
    status_geral = (conferencia.get("status_geral") or "").strip().lower()

    blocos = ["<h2>Conferência SCH x CCT</h2>"]

    if status_geral == "ok":
        blocos.append(
            "<div class='ok'>Sem incongruências entre os dados do SCH e do CCT.</div>"
        )

    elif status_geral == "sem_cct":
        blocos.append(
            "<div class='alerta'>"
            "Não foi possível realizar a conferência SCH x CCT porque não houve "
            "dados válidos do CCT."
            "</div>"
        )

    elif status_geral == "parcial":
        blocos.append(
            "<div class='alerta'>"
            "A conferência SCH x CCT foi realizada parcialmente. "
            "Alguns campos não foram identificados em um dos lados."
            "</div>"
        )

    else:
        blocos.append(
            "<div class='alerta'>"
            "Foram encontradas incongruências entre os dados do SCH e do CCT."
            "</div>"
        )

    blocos.append(_criar_tabela_comparacao(resultado))

    # Nova seção detalhada da comparação da tabela técnica.
    # Mostra se a tabela SCH x CCT foi OK, divergente ou não encontrada.
    blocos.append(_html_comparacao_tabela_tecnica(resultado))

    blocos.append(
        _criar_tabela_campos(
            "Tabela do SCH",
            _linhas_tabela_sch(resultado),
        )
    )

    blocos.append(
        _criar_tabela_campos(
            "Tabela do CCT",
            _linhas_tabela_cct(resultado),
        )
    )

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
    dados_certificado_sch = resultado.get("dados_certificado_sch") or {}

    comparacao_datas = (
        resultado.get("comparacao_datas_sch_cct")
        or dados_pdf.get("comparacao_datas_sch_cct")
        or {}
    )

    data_emissao = (
        validade.get("data_emissao_bruta")
        or dados_pdf.get("data_emissao")
        or dados_pdf.get("data_emissao_sch")
        or dados_certificado_sch.get("data_certificado")
        or "Não identificada"
    )

    data_validade = (
        validade.get("data_validade_bruta")
        or dados_pdf.get("data_validade")
        or dados_pdf.get("data_validade_sch")
        or dados_certificado_sch.get("data_validade")
        or "Não identificada"
    )

    origem = (
        dados_pdf.get("datas_origem")
        or dados_certificado_sch.get("origem")
        or "Não informada"
    )

    data_emissao_cct = dados_pdf.get("data_emissao_cct") or ""
    data_validade_cct = dados_pdf.get("data_validade_cct") or ""

    numero_certificado_sch = (
        dados_certificado_sch.get("numero_certificado")
        or dados_pdf.get("numero_certificado_sch_dados_gerais")
        or ""
    )

    status = validade.get("status") or "nao_verificado"
    mensagem = validade.get("mensagem") or "Validade do certificado não verificada."

    dias = validade.get("dias_entre_emissao_validade", "")
    limite_2_anos = validade.get("limite_2_anos", "")

    classe = "ok" if status == "ok" else "alerta"

    linhas = [
        "<h2>Validade do Certificado</h2>",
        f"<div class='{classe}'>{escape(str(mensagem))}</div>",
        "<table><thead><tr><th>Item</th><th>Valor</th></tr></thead><tbody>",
        f"<tr><td>Data de emissão usada na análise</td><td>{escape(str(data_emissao))}</td></tr>",
        f"<tr><td>Data de validade usada na análise</td><td>{escape(str(data_validade))}</td></tr>",
        f"<tr><td>Origem das datas usadas na análise</td><td>{escape(str(origem))}</td></tr>",
    ]

    if numero_certificado_sch:
        linhas.append(
            f"<tr><td>Nº do certificado no SCH</td><td>{escape(str(numero_certificado_sch))}</td></tr>"
        )

    if data_emissao_cct:
        linhas.append(
            f"<tr><td>Data de emissão extraída do CCT</td><td>{escape(str(data_emissao_cct))}</td></tr>"
        )

    if data_validade_cct:
        linhas.append(
            f"<tr><td>Data de validade extraída do CCT</td><td>{escape(str(data_validade_cct))}</td></tr>"
        )

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
            f"<tr><td>Status da validade</td><td>{escape(str(status))}</td></tr>",
            "</tbody></table>",
        ]
    )

    status_comp = comparacao_datas.get("status_geral") or "nao_verificado"
    mensagem_comp = comparacao_datas.get("mensagem") or "Comparação de datas SCH x CCT não executada."

    classe_comp = "ok" if status_comp == "ok" else "alerta"

    linhas.extend(
        [
            "<h3>Comparação de datas SCH x CCT</h3>",
            f"<div class='{classe_comp}'>{escape(str(mensagem_comp))}</div>",
            (
                "<table>"
                "<thead>"
                "<tr>"
                "<th>Campo</th>"
                "<th>Data no SCH</th>"
                "<th>Data no CCT</th>"
                "<th>Status</th>"
                "<th>Observação</th>"
                "</tr>"
                "</thead>"
                "<tbody>"
            ),
        ]
    )

    comparacoes = comparacao_datas.get("comparacoes", []) or []

    if not comparacoes:
        linhas.append(
            "<tr>"
            "<td colspan='5'>Comparação de datas não disponível.</td>"
            "</tr>"
        )
    else:
        nomes = {
            "data_emissao": "Data de emissão",
            "data_validade": "Data de validade",
        }

        for item in comparacoes:
            campo = nomes.get(item.get("campo", ""), item.get("campo", ""))
            valor_sch = item.get("valor_sch", "") or "Não identificada"
            valor_cct = item.get("valor_cct", "") or "Não identificada"
            status_item = item.get("status", "")
            msg_item = item.get("mensagem", "")

            linhas.append(
                "<tr>"
                f"<td>{escape(str(campo))}</td>"
                f"<td>{escape(str(valor_sch))}</td>"
                f"<td>{escape(str(valor_cct))}</td>"
                f"<td>{escape(str(status_item))}</td>"
                f"<td>{escape(str(msg_item))}</td>"
                "</tr>"
            )

    linhas.append("</tbody></table>")

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





# =============================================================================
# RELATÓRIO - RETORNO PARA ESTUDO
# =============================================================================

def _fmt_fila_sch(resultado):
    req = resultado.get("requerimento") or {}
    if isinstance(req, dict):
        return req.get("fila_sch", "") or resultado.get("fila_sch", "")
    return resultado.get("fila_sch", "")


def _fmt_retorno_para_estudo(resultado):
    return resultado.get("retorno_para_estudo") or {}


def _resultado_eh_retorno_para_estudo(resultado):
    retorno = _fmt_retorno_para_estudo(resultado)
    fila = str(_fmt_fila_sch(resultado) or "").lower()
    fila = fila.replace("á", "a").replace("ã", "a").replace("ç", "c")

    return bool(retorno) or "retorno para estudo" in fila or "retorno pra estudo" in fila


def _html_lista_retorno(valores, vazio="Nenhum."):
    if not valores:
        return f"<p>{escape(vazio)}</p>"

    linhas = ["<ul>"]

    for item in valores:
        if isinstance(item, dict):
            campo = item.get("campo") or ""
            anterior = item.get("anterior") or ""
            novo = item.get("novo") or ""

            linhas.append("<li>")

            if campo:
                linhas.append(f"<b>{escape(str(campo))}</b>")

            if anterior or novo:
                linhas.append(
                    "<table>"
                    "<thead><tr><th>Anterior</th><th>Novo</th></tr></thead>"
                    "<tbody><tr>"
                    f"<td>{escape(str(anterior or 'Não identificado'))}</td>"
                    f"<td>{escape(str(novo or 'Não identificado'))}</td>"
                    "</tr></tbody></table>"
                )
            else:
                linhas.append(escape(str(item)))

            linhas.append("</li>")

        else:
            linhas.append(f"<li>{escape(str(item))}</li>")

    linhas.append("</ul>")
    return "".join(linhas)



def _bool_retorno(valor):
    if isinstance(valor, bool):
        return valor

    texto = str(valor or "").strip().lower()
    texto = texto.replace("ã", "a").replace("á", "a").replace("ç", "c")

    return texto in {"true", "1", "sim", "s", "yes", "enviar", "apto"}


def _sim_nao_retorno(valor):
    return "SIM" if _bool_retorno(valor) else "NÃO"


def _classe_retorno_aprovacao(valor):
    return "ok" if _bool_retorno(valor) else "alerta"


def _html_alertas_retorno(alertas):
    if not alertas:
        return "<div class='ok'>Nenhum alerta identificado.</div>"

    return "".join(
        f"<div class='alerta'>{escape(str(alerta))}</div>"
        for alerta in alertas
    )





def _html_resumo_dados_tecnicos_retorno(comparacao_executada, dados_tecnicos_alterados):
    """
    Exibe somente o resultado da comparação de Dados Técnicos no relatório.
    Os dados brutos permanecem no resultado/JSON para diagnóstico, mas não são
    despejados no HTML como um bloco de texto corrido.
    """
    if not comparacao_executada:
        return (
            "<div class='alerta'>"
            "<b>NÃO ANALISADO.</b> O Comparar Versões não foi executado com sucesso "
            "para este item."
            "</div>"
        )

    if _bool_retorno(dados_tecnicos_alterados):
        return (
            "<div class='alerta'>"
            "<b>Houve alteração em Dados Técnicos do Produto.</b>"
            "</div>"
        )

    return (
        "<div class='ok'>"
        "Nenhuma alteração em Dados Técnicos do Produto identificada."
        "</div>"
    )


def _html_documentos_validacao_retorno(itens, vazio="Nenhum."):
    """
    Monta lista/tabela simples para documentos obrigatórios/condicionais
    da manutenção tácita.
    """
    if not itens:
        return f"<div class='ok'>{escape(vazio)}</div>"

    linhas = ["<ul>"]

    for item in itens:
        if isinstance(item, dict):
            nome = item.get("nome") or item.get("chave") or "Documento"
            documentos = item.get("documentos") or []
            tipo_numero = item.get("tipo_re_numero") or ""
            tipo_nome = item.get("tipo_re_nome") or ""

            prefixo_tipo = ""
            if tipo_numero:
                prefixo_tipo = f"Tipo {tipo_numero}"
                if tipo_nome:
                    prefixo_tipo += f" - {tipo_nome}"
                prefixo_tipo = f"<span class='muted'>[{escape(str(prefixo_tipo))}]</span> "

            linhas.append(f"<li>{prefixo_tipo}<b>{escape(str(nome))}</b>")

            if documentos:
                linhas.append("<ul>")
                for doc in documentos:
                    linhas.append(f"<li>{escape(str(doc))}</li>")
                linhas.append("</ul>")

            linhas.append("</li>")
        else:
            linhas.append(f"<li>{escape(str(item))}</li>")

    linhas.append("</ul>")
    return "".join(linhas)



def _rotulo_marcacao_campo_retorno(marcacao, chave):
    """Mostra N/A quando a etapa de marcação não chegou a ser executada."""
    marcacao = marcacao or {}
    status = str(marcacao.get("status") or "").strip().lower()

    executada = bool(
        marcacao.get("exigida")
        or marcacao.get("preenchida")
        or marcacao.get("salva")
        or marcacao.get("confirmada_apos_salvar")
        or (
            status
            and not status.startswith("nao_executada")
            and not status.startswith("não_executada")
        )
    )

    if not executada:
        return "NÃO APLICÁVEL / NÃO EXECUTADO"

    return _sim_nao_retorno(marcacao.get(chave))


def _html_tipos_re_informacoes_adicionais_retorno(analise):
    analise = analise or {}

    numeros_detectados = analise.get("numeros_detectados", []) or []
    tipos_detectados = analise.get("tipos_detectados", []) or []
    tipos_nao_permitidos = analise.get("tipos_nao_permitidos", []) or []
    nomes_permitidos = analise.get("nomes_permitidos_esperados", []) or []
    permitidos_codigos = analise.get("permitidos_esperados", []) or []

    numeros_txt = (
        ", ".join(str(n) for n in numeros_detectados)
        or "Nenhum número identificado"
    )
    permitidos_txt = (
        "; ".join(str(n) for n in nomes_permitidos)
        or ", ".join(str(n) for n in permitidos_codigos)
        or "Não informado pela análise"
    )

    todos_com_analisador = bool(
        numeros_detectados
        and not tipos_nao_permitidos
        and all(
            item.get(
                "possui_analisador_individual",
                item.get("permitido", False),
            )
            for item in tipos_detectados
            if isinstance(item, dict)
        )
    )

    classe = "ok" if todos_com_analisador else "alerta"

    linhas = [
        "<h3>Cruzamento com Informações Adicionais</h3>",
        f"<div class='{classe}'>",
        "<p><b>Números de tipo RE detectados:</b> "
        + escape(numeros_txt)
        + "</p>",
        "<p><b>Modo de análise:</b> cada número RE é avaliado separadamente.</p>",
        "<p><b>Tipos com analisador individual:</b> "
        + escape(permitidos_txt)
        + "</p>",
        "<p><b>Existe número sem analisador automático?</b> "
        + _sim_nao_retorno(bool(tipos_nao_permitidos))
        + "</p>",
        "</div>",
    ]

    if tipos_detectados:
        linhas.append(
            "<table><thead><tr>"
            "<th>Número</th><th>Tipo identificado</th>"
            "<th>Possui analisador individual?</th>"
            "</tr></thead><tbody>"
        )

        for item in tipos_detectados:
            if not isinstance(item, dict):
                continue

            possui = item.get(
                "possui_analisador_individual",
                item.get("permitido", False),
            )

            linhas.append(
                "<tr>"
                f"<td>{escape(str(item.get('numero','')))}</td>"
                f"<td>{escape(str(item.get('nome','')))}</td>"
                f"<td>{_sim_nao_retorno(possui)}</td>"
                "</tr>"
            )

        linhas.append("</tbody></table>")
    else:
        linhas.append(
            "<p class='muted'>Nenhum número de tipo RE foi identificado com "
            "segurança na Justificativa do OCD em Informações Adicionais. "
            "O relatório não presume automaticamente o tipo 6.</p>"
        )

    return "".join(linhas)

def _html_analises_individuais_retorno(retorno):
    """
    Mostra o julgamento de cada RE sem misturar critérios entre números.
    """
    retorno = retorno or {}
    analises = retorno.get("analises_por_tipo_re") or {}

    if not analises:
        if _comparacao_retorno_executada(retorno):
            return (
                "<div class='alerta'>A comparação foi executada, mas não há "
                "resultados individuais por tipo RE neste registro.</div>"
            )
        return (
            "<div class='muted'>As análises individuais não foram executadas "
            "porque o Comparar Versões não foi concluído.</div>"
        )

    linhas = [
        "<table>",
        "<thead><tr>"
        "<th>RE</th><th>Tipo</th><th>Resultado individual</th>"
        "<th>Documentos obrigatórios</th><th>Motivo</th>"
        "</tr></thead><tbody>",
    ]

    def ordem(item):
        try:
            return int(str(item[0]))
        except Exception:
            return 999

    for numero, analise in sorted(analises.items(), key=ordem):
        analise = analise or {}
        status = str(analise.get("status") or "REVISAR")
        documentos = analise.get("documentos") or {}
        docs_ok = analise.get("documentos_ok")

        if docs_ok is None:
            docs_ok = documentos.get("obrigatorios_ok")

        motivos = analise.get("motivos") or []
        motivo_txt = " ".join(
            str(item).strip()
            for item in motivos
            if str(item).strip()
        ) or "Critérios individuais atendidos."

        faltantes = documentos.get("obrigatorios_faltantes") or []
        nomes_faltantes = [
            str(item.get("nome") or "").strip()
            for item in faltantes
            if isinstance(item, dict) and str(item.get("nome") or "").strip()
        ]

        if nomes_faltantes:
            motivo_txt += (
                " Documentos faltantes: "
                + ", ".join(nomes_faltantes)
                + "."
            )

        linhas.append(
            "<tr>"
            f"<td><b>{escape(str(numero))}</b></td>"
            f"<td>{escape(str(analise.get('nome') or 'Não informado'))}</td>"
            f"<td><b>{escape(status)}</b></td>"
            f"<td>{_rotulo_documentos_ok_retorno(docs_ok)}</td>"
            f"<td>{escape(motivo_txt)}</td>"
            "</tr>"
        )

    linhas.append("</tbody></table>")

    consolidacao = retorno.get("consolidacao_analises_re") or {}
    if consolidacao:
        status_final = str(consolidacao.get("status") or "REVISAR")
        classe = "ok" if status_final == "APTO" else "alerta"
        linhas.append(
            f"<div class='{classe}'>"
            "<b>Resultado consolidado dos RE:</b> "
            f"{escape(status_final)}. "
            f"{escape(str(consolidacao.get('motivo') or ''))}"
            "</div>"
        )

    return "".join(linhas)





def _tipos_aceitos_retorno_txt(retorno):
    retorno = retorno or {}
    analise = retorno.get("analise_numeros_informacoes_adicionais") or {}

    nomes = analise.get("nomes_permitidos_esperados", []) or []
    codigos = analise.get("permitidos_esperados", []) or []

    if nomes:
        return "; ".join(str(item) for item in nomes)

    if codigos:
        return ", ".join(str(item) for item in codigos)

    return "Não informado pela análise"


def _descricao_tipos_re_retorno(retorno):
    retorno = retorno or {}
    analise = retorno.get("analise_numeros_informacoes_adicionais") or {}
    tipos = analise.get("tipos_detectados", []) or []

    descricoes = []
    for item in tipos:
        if not isinstance(item, dict):
            continue

        numero = str(item.get("numero") or "").strip()
        nome = str(item.get("nome") or "").strip()

        if numero and nome:
            descricoes.append(f"{numero}. {nome}")
        elif numero:
            descricoes.append(numero)

    if descricoes:
        return " + ".join(descricoes)

    numeros = retorno.get("numeros_tipo_re_detectados", []) or []
    if numeros:
        return " + ".join(str(numero) for numero in numeros)

    return (
        retorno.get("descricao_tipo_re")
        or retorno.get("tipo_re")
        or "Não identificado"
    )


def _html_retorno_para_estudo_bloco(resultado):
    retorno = _fmt_retorno_para_estudo(resultado)
    req_numero = _fmt_req(resultado)

    status = retorno.get("status_comparacao") or "Não executada"

    tipo_re = _descricao_tipos_re_retorno(retorno)

    itens_analisados = retorno.get("itens_analisados_pela_automacao") or [
        "Produto",
        "Dados Técnicos do Produto",
        "Outras Unidades Fabris",
        "Relação de Arquivos Anexos",
        "Documentos obrigatórios conforme cada tipo RE",
        "Análise individual por número RE",
        "Informações Adicionais / justificativa do Retorno Para Estudo",
    ]

    comparacao_executada = _comparacao_retorno_executada(retorno)

    produto_alterado = retorno.get("produto_alterado") if comparacao_executada else None
    dados_tecnicos_alterados = retorno.get("dados_tecnicos_alterados") if comparacao_executada else None
    unidade_fabril_alterada = retorno.get("unidade_fabril_alterada") if comparacao_executada else None
    documentos_novos_detectados = retorno.get("documentos_novos_detectados") if comparacao_executada else None

    docs_adicionados = retorno.get("documentos_adicionados") or []
    marcacao_automacao = (
        retorno.get("marcacao_automacao_informacoes_adicionais") or {}
    )
    tempos_comparar = retorno.get("tempos_comparar_versoes") or {}

    documentos_obrigatorios_encontrados = (
        retorno.get("documentos_obrigatorios_encontrados") or []
    )
    documentos_obrigatorios_faltantes = (
        retorno.get("documentos_obrigatorios_faltantes") or []
    )
    documentos_condicionais_encontrados = (
        retorno.get("documentos_condicionais_encontrados") or []
    )
    tipos_re_documentos_usados = retorno.get("tipos_re_documentos_usados") or []
    analise_numeros_info = retorno.get("analise_numeros_informacoes_adicionais") or {}
    numeros_tipo_re_detectados = retorno.get("numeros_tipo_re_detectados") or []
    numeros_tipo_re_nao_permitidos = retorno.get("numeros_tipo_re_nao_permitidos") or []
    info_adicionais_tem_numero_nao_permitido = retorno.get(
        "info_adicionais_tem_numero_nao_permitido",
        False,
    )

    documentos_obrigatorios_ok = (
        retorno.get("documentos_obrigatorios_ok")
        if comparacao_executada
        else None
    )

    if comparacao_executada and documentos_obrigatorios_ok is None:
        if documentos_obrigatorios_encontrados or documentos_obrigatorios_faltantes:
            documentos_obrigatorios_ok = not bool(
                documentos_obrigatorios_faltantes
            )

    pode_enviar = (
        retorno.get("pode_enviar_para_aprovacao")
        if "pode_enviar_para_aprovacao" in retorno
        else retorno.get("deve_enviar_para_aprovacao")
    )

    alteracoes_produto = retorno.get("alteracoes_produto") or []
    alteracoes_especificacoes = retorno.get("alteracoes_especificacoes_complementares") or []
    alteracoes_unidade_fabril = retorno.get("alteracoes_unidade_fabril") or []

    alertas = retorno.get("alertas") or []

    resultado_txt = retorno.get("resultado") or "Não informado."
    acao = retorno.get("acao_recomendada") or "Não enviar para aprovação / Revisar manualmente"

    envio = retorno.get("envio_para_aprovacao") or {}
    envio_executado = envio.get("executado")
    envio_motivo = envio.get("motivo") or envio.get("erro") or ""

    classe_aprovacao = _classe_retorno_aprovacao(pode_enviar)

    itens_html = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in itens_analisados
    )

    envio_linhas = ""
    if envio:
        envio_linhas = (
            f"<tr><td>Envio automático executado?</td><td>{_sim_nao_retorno(envio_executado)}</td></tr>"
            f"<tr><td>Detalhe do envio automático</td><td>{escape(str(envio_motivo or 'Não informado'))}</td></tr>"
        )

    return f"""
        <h2>Relatório - Retorno Para Estudo — Requerimento {escape(str(req_numero))}</h2>

        <div class="{classe_aprovacao}">
            <h3>Conclusão da automação</h3>
            <p>
                <b>Pode enviar para aprovação?</b>
                {_sim_nao_retorno(pode_enviar)}
            </p>
            <p>
                <b>Ação recomendada:</b>
                {escape(str(acao))}
            </p>
        </div>

        <h3>Resumo da análise</h3>
        <table>
            <thead>
                <tr><th>Item</th><th>Valor</th></tr>
            </thead>
            <tbody>
                <tr><td>Requerimento</td><td>{escape(str(req_numero))}</td></tr>
                <tr><td>Tipo de RE analisado</td><td>{escape(str(tipo_re))}</td></tr>
                <tr><td>Comparar Versões executado?</td><td>{'SIM' if comparacao_executada else 'NÃO'}</td></tr>
                <tr><td>Status da comparação</td><td>{escape(str(status))}</td></tr>
                <tr><td>Produto alterado?</td><td>{_rotulo_tri_retorno(produto_alterado)}</td></tr>
                <tr><td>Dados Técnicos do Produto alterados?</td><td>{_rotulo_tri_retorno(dados_tecnicos_alterados)}</td></tr>
                <tr><td>Unidade fabril alterada?</td><td>{_rotulo_tri_retorno(unidade_fabril_alterada)}</td></tr>
                <tr><td>Documento novo identificado?</td><td>{_rotulo_tri_retorno(documentos_novos_detectados)}</td></tr>
                <tr><td>Tabelas dos dois lados localizadas?</td><td>{_sim_nao_retorno(tempos_comparar.get('captura_completa'))}</td></tr>
                <tr><td>Captura documental segura para decisão automática?</td><td>{_sim_nao_retorno(retorno.get('captura_documental_segura'))}</td></tr>
                <tr><td>Tempo do Comparar Versões</td><td>{escape(str(tempos_comparar.get('total_segundos', 'Não informado')))} segundo(s)</td></tr>
                <tr><td>Marcação da automação exigida?</td><td>{_sim_nao_retorno(marcacao_automacao.get('exigida'))}</td></tr>
                <tr><td>Registro em Acompanhar Processo salvo e confirmado?</td><td>{_sim_nao_retorno(marcacao_automacao.get('acompanhar_processo_marcado') and marcacao_automacao.get('preenchida') and marcacao_automacao.get('salva') and marcacao_automacao.get('confirmada_apos_salvar'))}</td></tr>
                <tr><td>Documentos obrigatórios OK?</td><td>{_rotulo_documentos_ok_retorno(documentos_obrigatorios_ok)}</td></tr>
                <tr><td>Números RE detectados nas Informações Adicionais</td><td>{escape(', '.join(str(n) for n in numeros_tipo_re_detectados) or 'Nenhum')}</td></tr>
                <tr><td>Números RE fora do escopo?</td><td>{_sim_nao_retorno(info_adicionais_tem_numero_nao_permitido)}</td></tr>
                <tr><td>Números RE fora do escopo identificados</td><td>{escape(', '.join(str(n) for n in numeros_tipo_re_nao_permitidos) or 'Nenhum')}</td></tr>
                <tr><td>Pode enviar para aprovação?</td><td><b>{_sim_nao_retorno(pode_enviar)}</b></td></tr>
                {envio_linhas}
            </tbody>
        </table>

        <h3>Itens analisados pela automação</h3>
        <ul>
            {itens_html}
        </ul>

        <h3>Regra aplicada</h3>
        <p>
            Cada número RE identificado é <b>avaliado separadamente</b>, com seus
            próprios critérios técnicos e documentais. O Comparar Versões é capturado
            uma única vez, mas os RE <b>1, 5, 6, 10, 11 e 12</b> recebem julgamentos
            independentes. A validação documental considera somente
            <b>documentos incluídos</b>; exclusão de anexos não participa da decisão.
            O requerimento só pode seguir para aprovação quando
            <b>todos os RE identificados estiverem APTO individualmente</b>.
        </p>

        {_html_tipos_re_informacoes_adicionais_retorno(analise_numeros_info)}

        <h3>Análise individual por tipo RE</h3>
        {_html_analises_individuais_retorno(retorno)}

        <h3>Tipos RE usados para validação documental</h3>
        {_html_documentos_validacao_retorno(tipos_re_documentos_usados, "Nenhum tipo RE usado na validação documental.")}

        <h3>Alertas</h3>
        {_html_alertas_retorno(alertas)}

        <h3>Alterações no Produto</h3>
        {_html_lista_retorno(alteracoes_produto, "Nenhuma alteração em Produto identificada.")}

        <h3>Alterações em Dados Técnicos do Produto</h3>
        {_html_resumo_dados_tecnicos_retorno(comparacao_executada, dados_tecnicos_alterados)}

        <h3>Alterações em Especificações Complementares</h3>
        {_html_lista_retorno(alteracoes_especificacoes, "Nenhuma alteração identificada.")}

        <h3>Alterações em Unidade Fabril</h3>
        {_html_lista_retorno(alteracoes_unidade_fabril, "Nenhuma alteração em Unidade Fabril identificada.")}

        <h3>Documentos obrigatórios encontrados</h3>
        {_html_documentos_validacao_retorno(documentos_obrigatorios_encontrados, "Nenhum documento obrigatório encontrado.")}

        <h3>Documentos obrigatórios faltantes</h3>
        {_html_documentos_validacao_retorno(documentos_obrigatorios_faltantes, "Nenhum documento obrigatório faltante.")}

        <h3>Documentos condicionais/informativos encontrados</h3>
        {_html_documentos_validacao_retorno(documentos_condicionais_encontrados, "Nenhum documento condicional identificado.")}

        <h3>Documentos adicionados</h3>
        {_html_lista_retorno(docs_adicionados, "Nenhum documento adicionado identificado.")}

        <h3>Registro da análise por automação - Acompanhar Processo</h3>
        <table>
            <thead><tr><th>Item</th><th>Valor</th></tr></thead>
            <tbody>
                <tr><td>Status</td><td>{escape(str(marcacao_automacao.get('status') or 'Não exigida/não executada'))}</td></tr>
                <tr><td>Campo de destino</td><td>{escape(str(marcacao_automacao.get('campo_destino') or 'Acompanhar Processo'))}</td></tr>
                <tr><td>Justificativa do OCD preservada?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'justificativa_preservada')}</td></tr>
                <tr><td>Informações Adicionais &gt; Descrição preservada?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'descricao_informacoes_adicionais_preservada')}</td></tr>
                <tr><td>Destinatários alterados?</td><td>{'SIM' if marcacao_automacao.get('destinatarios_alterados') else 'NÃO'}</td></tr>
                <tr><td>Justificativa capturada antes do registro?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'texto_original_capturado_antes_do_registro')}</td></tr>
                <tr><td>Tipo RE analisado antes do registro?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'tipo_re_analisado_antes_do_registro')}</td></tr>
                <tr><td>Desejo acompanhar este processo marcado?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'acompanhar_processo_marcado')}</td></tr>
                <tr><td>Conteúdo anterior de Acompanhar Processo</td><td>{escape(str(marcacao_automacao.get('conteudo_anterior') or 'Vazio/não informado'))}</td></tr>
                <tr><td>Frase registrada</td><td>{escape(str(marcacao_automacao.get('frase') or 'Não informada'))}</td></tr>
                <tr><td>Salva?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'salva')}</td></tr>
                <tr><td>Confirmada após salvar e reabrir a aba?</td><td>{_rotulo_marcacao_campo_retorno(marcacao_automacao, 'confirmada_apos_salvar')}</td></tr>
            </tbody>
        </table>

        <h3>Resultado detalhado</h3>
        <div class="{classe_aprovacao}">
            {escape(str(resultado_txt))}
        </div>
    """

def _html_requerimento_retorno_para_estudo(resultado):
    req_numero = _fmt_req(resultado)
    tempo_ativo = _tempo_ativo_resultado_segundos(resultado)
    retorno = _fmt_retorno_para_estudo(resultado)
    erro = retorno.get("erro") or ""

    erro_html = (
        f"<div class='alerta'><b>Erro na comparação:</b> {escape(str(erro))}</div>"
        if erro
        else ""
    )

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Retorno Para Estudo - Requerimento {escape(req_numero)}</title>
        {_css()}
    </head>
    <body>
        <h1>Requerimento {escape(req_numero)}</h1>
        <p class="muted">Fila: Retorno Para Estudo</p>
        <p class="muted">Tempo de análise: {escape(str(tempo_ativo))} segundo(s)</p>

        {erro_html}

        {_html_retorno_para_estudo_bloco(resultado)}

        <h2>Dados operacionais</h2>
        <ul>
            <li><b>Downloads realizados:</b> {escape(str(resultado.get('downloads_realizados', 0)))}</li>
            <li><b>CCT localizado:</b> {escape(str(resultado.get('pdf_cct', '')))}</li>
            <li><b>Status do processamento:</b> {escape(str(resultado.get('status', '')))}</li>
        </ul>
    </body>
    </html>
    """


def _retorno_resultado_resumo(resultado):
    """
    Pega o bloco de resultado do Retorno Para Estudo, mesmo que ele venha
    em estruturas diferentes.
    """
    if not isinstance(resultado, dict):
        return {}

    for chave in [
        "retorno_para_estudo",
        "resultado_retorno_para_estudo",
        "resultado_retorno",
        "analise_retorno_para_estudo",
    ]:
        valor = resultado.get(chave)
        if isinstance(valor, dict):
            return valor

    # Em alguns fluxos, o próprio resultado já é o bloco de Retorno Para Estudo.
    if (
        resultado.get("tipo_relatorio") == "retorno_para_estudo"
        or resultado.get("tipo_re")
        or "pode_enviar_para_aprovacao" in resultado
        or "deve_enviar_para_aprovacao" in resultado
    ):
        return resultado

    return resultado


def _bool_resumo_retorno(valor):
    if isinstance(valor, bool):
        return valor

    texto = str(valor or "").strip().lower()

    return texto in {
        "true",
        "1",
        "sim",
        "s",
        "yes",
        "y",
        "ok",
        "apto",
        "aprovado",
    }


def _sim_nao_resumo_retorno(valor):
    return "SIM" if _bool_resumo_retorno(valor) else "NÃO"


def _comparacao_retorno_executada(retorno):
    """
    True somente quando Comparar Versões realmente produziu uma comparação.
    """
    retorno = retorno or {}

    if "comparacao_executada" in retorno:
        return retorno.get("comparacao_executada") is True

    status = str(
        retorno.get("status_comparacao") or ""
    ).strip().lower()

    if status in {
        "analises_re_individuais_aptas",
        "analises_re_individuais_nao_aptas",
        # Compatibilidade com resultados antigos.
        "manutencao_tacita_apta",
        "manutencao_tacita_nao_apta",
        "bloqueado_por_falha_no_tratamento_da_minuta",
        "bloqueado_por_falha_na_marcacao_da_automacao",
        "bloqueado_por_falha_ao_restaurar_requerimento",
    }:
        return True

    campos = (
        "produto_alterado",
        "dados_tecnicos_alterados",
        "unidade_fabril_alterada",
        "documentos_novos_detectados",
        "documentos_obrigatorios_ok",
    )

    return any(
        campo in retorno and retorno.get(campo) is not None
        for campo in campos
    )


def _rotulo_tri_retorno(
    valor,
    *,
    verdadeiro="SIM",
    falso="NÃO",
    nao_analisado="NÃO ANALISADO",
):
    if valor is None:
        return nao_analisado

    return verdadeiro if _bool_resumo_retorno(valor) else falso


def _rotulo_alteracao_retorno(valor, feminino=False):
    if valor is None:
        return "NÃO ANALISADO"

    if _bool_resumo_retorno(valor):
        return "Alterada" if feminino else "Alterado"

    return "OK"


def _rotulo_documentos_ok_retorno(valor):
    if valor is None:
        return "NÃO ANALISADO"

    return "OK" if _bool_resumo_retorno(valor) else "NÃO OK"


def _lista_resumo_retorno(valor):
    if not valor:
        return []

    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]

    if isinstance(valor, tuple):
        return [str(v).strip() for v in valor if str(v).strip()]

    return [str(valor).strip()] if str(valor).strip() else []


def _texto_curto_resumo_retorno(valor, limite=120):
    texto = " ".join(str(valor or "").split())

    if not texto:
        return "-"

    if len(texto) <= limite:
        return texto

    return texto[: limite - 3] + "..."


def _resultado_executivo_retorno(resultado):
    retorno = _retorno_resultado_resumo(resultado)

    envio = (
        retorno.get("envio_para_aprovacao")
        or resultado.get("envio_para_aprovacao")
        or {}
    )
    erro = retorno.get("erro") or resultado.get("erro") or ""

    status_comparacao = str(
        retorno.get("status_comparacao") or ""
    ).strip().lower()
    status_processamento = str(
        resultado.get("status") or retorno.get("status") or ""
    ).strip().lower()

    enviado = _bool_resumo_retorno(envio.get("executado"))

    pode_enviar = _bool_resumo_retorno(
        retorno.get("pode_enviar_para_aprovacao")
        if "pode_enviar_para_aprovacao" in retorno
        else retorno.get("deve_enviar_para_aprovacao")
    )

    if erro or status_comparacao == "erro" or status_processamento == "erro":
        return "Erro na análise"

    if enviado:
        return "Aprovado automaticamente"

    if pode_enviar:
        return "Apto para aprovação"

    if not _comparacao_retorno_executada(retorno):
        return "Não analisado / Fora do escopo"

    return "Revisão manual"


def _classe_resultado_executivo_retorno(resultado_exec):
    texto = str(resultado_exec or "").lower()

    if "aprovado automaticamente" in texto:
        return "status-c"

    if "apto" in texto:
        return "status-revisar"

    if "erro" in texto:
        return "status-nc"

    if "nao analisado" in texto or "não analisado" in texto:
        return "status-na"

    return "status-revisar"


def _motivo_principal_retorno(resultado):
    retorno = _retorno_resultado_resumo(resultado)

    erro = retorno.get("erro") or resultado.get("erro") or ""
    if erro:
        return f"Erro: {_texto_curto_resumo_retorno(erro, 160)}"

    if not _comparacao_retorno_executada(retorno):
        analise_re = (
            retorno.get("analise_numeros_informacoes_adicionais") or {}
        )

        numeros_fora = _lista_resumo_retorno(
            retorno.get("numeros_tipo_re_nao_permitidos")
            or analise_re.get("numeros_nao_permitidos")
        )
        if numeros_fora:
            return (
                "Tipo RE sem analisador automático: "
                + ", ".join(str(n) for n in numeros_fora)
            )

        if not _lista_resumo_retorno(
            retorno.get("numeros_tipo_re_detectados")
            or analise_re.get("numeros_detectados")
        ):
            return "Tipo RE não identificado com segurança"

        status = str(
            retorno.get("status_comparacao") or ""
        ).strip()
        if status:
            return "Comparar Versões não executado: " + status

        return "Comparar Versões não executado"

    analises = retorno.get("analises_por_tipo_re") or {}
    consolidacao = retorno.get("consolidacao_analises_re") or {}

    if analises:
        for numero, analise in analises.items():
            analise = analise or {}
            if analise.get("status") == "APTO":
                continue

            motivos = analise.get("motivos") or []
            motivo = (
                str(motivos[0]).strip()
                if motivos
                else f"Resultado individual: {analise.get('status', 'REVISAR')}"
            )
            return _texto_curto_resumo_retorno(
                f"RE {numero}: {motivo}",
                160,
            )

    marcacao = (
        retorno.get(
            "marcacao_automacao_informacoes_adicionais"
        )
        or {}
    )
    if marcacao.get("exigida") and not (
        marcacao.get("acompanhar_processo_marcado")
        and marcacao.get("preenchida")
        and marcacao.get("salva")
        and marcacao.get("confirmada_apos_salvar")
    ):
        return (
            "Registro da análise automática não confirmado em "
            "Acompanhar Processo"
        )

    if analises and consolidacao.get("todos_aptos") is True:
        return "Todos os RE aptos individualmente"

    # Compatibilidade com resultados antigos, anteriores à análise individual.
    if retorno.get("captura_documental_segura") is False:
        return (
            "Captura documental incompleta; "
            "aprovação automática bloqueada"
        )

    faltantes = _lista_resumo_retorno(
        retorno.get("documentos_obrigatorios_faltantes")
    )
    if faltantes:
        nomes = []
        for item in faltantes[:3]:
            if isinstance(item, dict):
                nomes.append(
                    str(
                        item.get("nome")
                        or item.get("documento")
                        or item
                    )
                )
            else:
                nomes.append(str(item))

        extra = (
            ""
            if len(faltantes) <= 3
            else f" +{len(faltantes) - 3}"
        )
        return (
            "Documento obrigatório faltante: "
            + ", ".join(nomes)
            + extra
        )

    if _bool_resumo_retorno(
        retorno.get("pode_enviar_para_aprovacao")
    ):
        return "Critérios atendidos"

    alertas = _lista_resumo_retorno(
        retorno.get("alertas")
    )
    if alertas:
        return _texto_curto_resumo_retorno(
            alertas[0],
            160,
        )

    return "-"


def _numeros_re_resumo(resultado):
    retorno = _retorno_resultado_resumo(resultado)

    numeros = _lista_resumo_retorno(retorno.get("numeros_tipo_re_detectados"))

    if not numeros:
        analise = retorno.get("analise_numeros_informacoes_adicionais") or {}
        numeros = _lista_resumo_retorno(analise.get("numeros_detectados"))

    return ", ".join(numeros) if numeros else "Nenhum"


def _acao_recomendada_resumo(resultado):
    retorno = _retorno_resultado_resumo(resultado)

    acao = (
        retorno.get("acao_recomendada")
        or resultado.get("acao_recomendada")
        or ""
    )

    if acao:
        return str(acao)

    resultado_exec = _resultado_executivo_retorno(resultado)

    if resultado_exec == "Aprovado automaticamente":
        return "Enviado para aprovação"

    if resultado_exec == "Apto para aprovação":
        return "Enviar para aprovação"

    if resultado_exec == "Erro na análise":
        return "Revisar manualmente"

    if resultado_exec == "Não analisado / Fora do escopo":
        return "Não analisado automaticamente / Fora do escopo"

    return "Não enviar para aprovação / Revisar manualmente"


def _html_resumo_executivo_retorno_para_estudo(resultados):
    resultados = resultados or []

    total = len(resultados)

    qtd_aprovado = 0
    qtd_apto = 0
    qtd_revisar = 0
    qtd_nao_analisado = 0
    qtd_erro = 0

    linhas = []

    for idx, resultado in enumerate(resultados, start=1):
        retorno = _retorno_resultado_resumo(resultado)
        req_numero = _fmt_req(resultado)

        resultado_exec = _resultado_executivo_retorno(resultado)

        if resultado_exec == "Aprovado automaticamente":
            qtd_aprovado += 1
        elif resultado_exec == "Apto para aprovação":
            qtd_apto += 1
        elif resultado_exec == "Erro na análise":
            qtd_erro += 1
        elif resultado_exec == "Não analisado / Fora do escopo":
            qtd_nao_analisado += 1
        else:
            qtd_revisar += 1

        classe_resultado = _classe_resultado_executivo_retorno(resultado_exec)

        comparacao_executada = _comparacao_retorno_executada(retorno)

        produto_valor = retorno.get("produto_alterado") if comparacao_executada else None
        dados_valor = retorno.get("dados_tecnicos_alterados") if comparacao_executada else None
        unidade_valor = retorno.get("unidade_fabril_alterada") if comparacao_executada else None
        docs_novos_valor = retorno.get("documentos_novos_detectados") if comparacao_executada else None
        docs_ok_valor = retorno.get("documentos_obrigatorios_ok") if comparacao_executada else None
        envio = retorno.get("envio_para_aprovacao") or {}
        envio_txt = "SIM" if _bool_resumo_retorno(envio.get("executado")) else "NÃO"

        motivo = _motivo_principal_retorno(resultado)

        linhas.append(
            "<tr>"
            f"<td>{escape(str(idx))}</td>"
            f"<td><b>{escape(str(req_numero))}</b></td>"
            f"<td class='status-cell {classe_resultado}'>{escape(resultado_exec)}</td>"
            f"<td>{escape(_acao_recomendada_resumo(resultado))}</td>"
            f"<td>{_rotulo_alteracao_retorno(produto_valor)}</td>"
            f"<td>{_rotulo_alteracao_retorno(dados_valor)}</td>"
            f"<td>{_rotulo_alteracao_retorno(unidade_valor, feminino=True)}</td>"
            f"<td>{_rotulo_tri_retorno(docs_novos_valor)}</td>"
            f"<td>{_rotulo_documentos_ok_retorno(docs_ok_valor)}</td>"
            f"<td>{escape(_numeros_re_resumo(resultado))}</td>"
            f"<td>{escape(envio_txt)}</td>"
            f"<td>{escape(motivo)}</td>"
            "</tr>"
        )

    return f"""
    <div class="sumario">
        <h2>Resumo da análise dos requerimentos</h2>

        <table>
            <thead>
                <tr>
                    <th>Total analisado</th>
                    <th>Aprovados automaticamente</th>
                    <th>Aptos, mas não enviados</th>
                    <th>Revisão manual</th>
                    <th>Não analisados</th>
                    <th>Erros</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><b>{escape(str(total))}</b></td>
                    <td class="status-cell status-c">{escape(str(qtd_aprovado))}</td>
                    <td class="status-cell status-revisar">{escape(str(qtd_apto))}</td>
                    <td class="status-cell status-revisar">{escape(str(qtd_revisar))}</td>
                    <td class="status-cell status-na">{escape(str(qtd_nao_analisado))}</td>
                    <td class="status-cell status-nc">{escape(str(qtd_erro))}</td>
                </tr>
            </tbody>
        </table>

        <h3>Resultado por requerimento</h3>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Requerimento</th>
                    <th>Resultado</th>
                    <th>Ação recomendada</th>
                    <th>Produto</th>
                    <th>Dados técnicos</th>
                    <th>Unidade fabril</th>
                    <th>Docs novos</th>
                    <th>Docs obrigatórios</th>
                    <th>Números RE</th>
                    <th>Enviado?</th>
                    <th>Motivo principal</th>
                </tr>
            </thead>
            <tbody>
                {''.join(linhas)}
            </tbody>
        </table>
    </div>
    """




def _html_consolidado_retorno_para_estudo(
    resultados,
    versao_script,
    inicio_execucao,
    fim_execucao,
    ignorados_fora_escopo=None,
):
    """
    Gera o relatório consolidado da fila Retorno Para Estudo.

    Inclui:
    - Resumo executivo da análise dos requerimentos;
    - Quantitativos gerais;
    - Tabela com resultado por requerimento;
    - Detalhamento individual de cada requerimento.
    """

    from html import escape

    resultados = resultados or []
    ignorados_fora_escopo = ignorados_fora_escopo or []

    def _safe_txt(valor):
        return escape(str(valor or ""))

    def _safe_data(valor):
        if not valor:
            return ""

        try:
            return valor.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return str(valor)

    def _pegar_retorno(resultado):
        if not isinstance(resultado, dict):
            return {}

        for chave in [
            "retorno_para_estudo",
            "resultado_retorno_para_estudo",
            "resultado_retorno",
            "analise_retorno_para_estudo",
        ]:
            valor = resultado.get(chave)
            if isinstance(valor, dict):
                return valor

        if (
            resultado.get("tipo_relatorio") == "retorno_para_estudo"
            or resultado.get("tipo_re")
            or "pode_enviar_para_aprovacao" in resultado
            or "deve_enviar_para_aprovacao" in resultado
        ):
            return resultado

        return resultado

    def _bool(valor):
        if isinstance(valor, bool):
            return valor

        texto = str(valor or "").strip().lower()

        return texto in {
            "true",
            "1",
            "sim",
            "s",
            "yes",
            "y",
            "ok",
            "apto",
            "aprovado",
        }

    def _lista(valor):
        if not valor:
            return []

        if isinstance(valor, list):
            return [v for v in valor if str(v).strip()]

        if isinstance(valor, tuple):
            return [v for v in valor if str(v).strip()]

        return [valor] if str(valor).strip() else []

    def _req_numero(resultado):
        if not isinstance(resultado, dict):
            return ""

        req = resultado.get("req") or resultado.get("requerimento") or {}

        if isinstance(req, dict):
            return (
                req.get("requerimento")
                or req.get("numero")
                or resultado.get("requerimento")
                or ""
            )

        return resultado.get("requerimento") or str(req or "")

    def _resultado_executivo(resultado):
        retorno = _pegar_retorno(resultado)
        envio = retorno.get("envio_para_aprovacao") or resultado.get("envio_para_aprovacao") or {}

        erro = retorno.get("erro") or resultado.get("erro") or ""
        status_comparacao = str(retorno.get("status_comparacao") or "").strip().lower()
        status_processamento = str(resultado.get("status") or retorno.get("status") or "").strip().lower()

        enviado = _bool(envio.get("executado"))

        pode_enviar = _bool(
            retorno.get("pode_enviar_para_aprovacao")
            if "pode_enviar_para_aprovacao" in retorno
            else retorno.get("deve_enviar_para_aprovacao")
        )

        if erro or status_comparacao == "erro" or status_processamento == "erro":
            return "Erro na análise"

        if enviado:
            return "Aprovado automaticamente"

        if pode_enviar:
            return "Apto para aprovação"

        if not _comparacao_retorno_executada(retorno):
            return "Não analisado / Fora do escopo"

        return "Revisão manual"

    def _classe_resultado(resultado_exec):
        texto = str(resultado_exec or "").lower()

        if "aprovado automaticamente" in texto:
            return "ok"

        if "apto" in texto:
            return "apto"

        if "erro" in texto:
            return "erro"

        if "nao analisado" in texto or "não analisado" in texto:
            return "revisar"

        return "revisar"

    def _acao_recomendada(resultado):
        retorno = _pegar_retorno(resultado)

        acao = (
            retorno.get("acao_recomendada")
            or resultado.get("acao_recomendada")
            or ""
        )

        if acao:
            return str(acao)

        resultado_exec = _resultado_executivo(resultado)

        if resultado_exec == "Aprovado automaticamente":
            return "Enviado para aprovação"

        if resultado_exec == "Apto para aprovação":
            return "Enviar para aprovação"

        if resultado_exec == "Erro na análise":
            return "Revisar manualmente"

        if resultado_exec == "Não analisado / Fora do escopo":
            return "Não analisado automaticamente / Fora do escopo"

        return "Não enviar para aprovação / Revisar manualmente"

    def _numeros_re(resultado):
        retorno = _pegar_retorno(resultado)

        numeros = _lista(retorno.get("numeros_tipo_re_detectados"))

        if not numeros:
            analise = retorno.get("analise_numeros_informacoes_adicionais") or {}
            numeros = _lista(analise.get("numeros_detectados"))

        return ", ".join(str(n) for n in numeros) if numeros else "Nenhum"

    def _motivo_principal(resultado):
        retorno = _pegar_retorno(resultado)

        erro = retorno.get("erro") or resultado.get("erro") or ""
        if erro:
            return f"Erro: {str(erro)[:180]}"

        if not _comparacao_retorno_executada(retorno):
            analise_re = (
                retorno.get("analise_numeros_informacoes_adicionais")
                or {}
            )
            numeros_fora = _lista(
                retorno.get("numeros_tipo_re_nao_permitidos")
                or analise_re.get("numeros_nao_permitidos")
            )
            if numeros_fora:
                return (
                    "Tipo RE sem analisador automático: "
                    + ", ".join(str(n) for n in numeros_fora)
                )

            numeros_detectados = _lista(
                retorno.get("numeros_tipo_re_detectados")
                or analise_re.get("numeros_detectados")
            )
            if not numeros_detectados:
                return "Tipo RE não identificado com segurança"

            status = str(
                retorno.get("status_comparacao") or ""
            ).strip()
            if status:
                return "Comparar Versões não executado: " + status

            return "Comparar Versões não executado"

        analises = retorno.get("analises_por_tipo_re") or {}
        consolidacao = retorno.get("consolidacao_analises_re") or {}

        if analises:
            for numero, analise in analises.items():
                analise = analise or {}
                if analise.get("status") == "APTO":
                    continue

                motivos = analise.get("motivos") or []
                motivo = (
                    str(motivos[0]).strip()
                    if motivos
                    else "Resultado individual: "
                    + str(analise.get("status") or "REVISAR")
                )
                return f"RE {numero}: {motivo}"[:180]

        marcacao = (
            retorno.get(
                "marcacao_automacao_informacoes_adicionais"
            )
            or {}
        )
        if marcacao.get("exigida") and not (
            marcacao.get("acompanhar_processo_marcado")
            and marcacao.get("preenchida")
            and marcacao.get("salva")
            and marcacao.get("confirmada_apos_salvar")
        ):
            return (
                "Registro da análise automática não confirmado em "
                "Acompanhar Processo"
            )

        if analises and consolidacao.get("todos_aptos") is True:
            return "Todos os RE aptos individualmente"

        # Compatibilidade com resultados antigos.
        if retorno.get("captura_documental_segura") is False:
            return (
                "Captura documental incompleta; "
                "aprovação automática bloqueada"
            )

        faltantes = _lista(
            retorno.get("documentos_obrigatorios_faltantes")
        )
        if faltantes:
            nomes = []
            for item in faltantes[:3]:
                if isinstance(item, dict):
                    nomes.append(
                        str(
                            item.get("nome")
                            or item.get("documento")
                            or item.get("tipo")
                            or item
                        )
                    )
                else:
                    nomes.append(str(item))

            extra = (
                ""
                if len(faltantes) <= 3
                else f" +{len(faltantes) - 3}"
            )
            return (
                "Documento obrigatório faltante: "
                + ", ".join(nomes)
                + extra
            )

        if _bool(retorno.get("pode_enviar_para_aprovacao")):
            return "Critérios atendidos"

        alertas = _lista(retorno.get("alertas"))
        if alertas:
            return str(alertas[0])[:180]

        return "-"

    total = len(resultados)
    qtd_ignorados_fora_escopo = len(ignorados_fora_escopo)
    qtd_aprovado = 0
    qtd_apto = 0
    qtd_revisar = 0
    qtd_nao_analisado = 0
    qtd_erro = 0

    linhas_resumo = []

    for idx, resultado in enumerate(resultados, start=1):
        retorno = _pegar_retorno(resultado)
        req_numero = _req_numero(resultado)

        resultado_exec = _resultado_executivo(resultado)
        classe = _classe_resultado(resultado_exec)

        if resultado_exec == "Aprovado automaticamente":
            qtd_aprovado += 1
        elif resultado_exec == "Apto para aprovação":
            qtd_apto += 1
        elif resultado_exec == "Erro na análise":
            qtd_erro += 1
        elif resultado_exec == "Não analisado / Fora do escopo":
            qtd_nao_analisado += 1
        else:
            qtd_revisar += 1

        comparacao_executada = _comparacao_retorno_executada(retorno)

        produto_valor = retorno.get("produto_alterado") if comparacao_executada else None
        dados_valor = retorno.get("dados_tecnicos_alterados") if comparacao_executada else None
        unidade_valor = retorno.get("unidade_fabril_alterada") if comparacao_executada else None
        docs_novos_valor = retorno.get("documentos_novos_detectados") if comparacao_executada else None
        docs_ok_valor = retorno.get("documentos_obrigatorios_ok") if comparacao_executada else None

        envio = retorno.get("envio_para_aprovacao") or {}
        envio_txt = "SIM" if _bool(envio.get("executado")) else "NÃO"

        linhas_resumo.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td><b>{_safe_txt(req_numero)}</b></td>"
            f"<td><span class='badge {classe}'>{_safe_txt(resultado_exec)}</span></td>"
            f"<td>{_safe_txt(_acao_recomendada(resultado))}</td>"
            f"<td>{_rotulo_alteracao_retorno(produto_valor)}</td>"
            f"<td>{_rotulo_alteracao_retorno(dados_valor)}</td>"
            f"<td>{_rotulo_alteracao_retorno(unidade_valor, feminino=True)}</td>"
            f"<td>{_rotulo_tri_retorno(docs_novos_valor)}</td>"
            f"<td>{_rotulo_documentos_ok_retorno(docs_ok_valor)}</td>"
            f"<td>{_safe_txt(_numeros_re(resultado))}</td>"
            f"<td>{_safe_txt(envio_txt)}</td>"
            f"<td>{_safe_txt(_motivo_principal(resultado))}</td>"
            "</tr>"
        )

    linhas_ignorados = []

    for idx, item in enumerate(ignorados_fora_escopo, start=1):
        item = item if isinstance(item, dict) else {"requerimento": str(item)}

        requerimento = item.get("requerimento", "") or "Não identificado"
        tipo_produto = item.get("tipo_produto", "") or "Não identificado"
        homologacao = item.get("homologacao", "") or "Não informada"
        motivo = item.get("motivo", "") or "fora_do_escopo"
        mensagem = item.get("mensagem", "") or ""

        motivo_humano = {
            "tipo_produto_fora_escopo_automatico_retorno": (
                "Tipo de produto fora da lista de avaliação automática do Retorno Para Estudo"
            ),
            "homologacao_2026_ou_superior": "Homologação de 2026 ou posterior",
            "fora_escopo_radiacao_restrita": "Fora do escopo configurado para esta execução",
        }.get(motivo, motivo)

        linhas_ignorados.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td><b>{_safe_txt(requerimento)}</b></td>"
            f"<td>{_safe_txt(tipo_produto)}</td>"
            f"<td>{_safe_txt(homologacao)}</td>"
            f"<td>{_safe_txt(motivo_humano)}</td>"
            f"<td>{_safe_txt(mensagem)}</td>"
            "</tr>"
        )

    blocos_detalhes = []

    for idx, resultado in enumerate(resultados, start=1):
        req_numero = _req_numero(resultado)

        try:
            bloco = _html_retorno_para_estudo_bloco(resultado)
        except Exception as e:
            bloco = (
                "<div class='card erro-card'>"
                f"<h2>Requerimento {_safe_txt(req_numero or idx)}</h2>"
                "<p>Não foi possível gerar o bloco detalhado deste requerimento.</p>"
                f"<p><b>Erro:</b> {_safe_txt(e)}</p>"
                "</div>"
            )

        blocos_detalhes.append(bloco)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <title>Relatório Consolidado - Retorno Para Estudo</title>

    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            margin: 24px;
            color: #222;
            background: #fff;
        }}

        h1 {{
            margin-bottom: 4px;
        }}

        h2 {{
            margin-top: 28px;
            border-bottom: 2px solid #ddd;
            padding-bottom: 6px;
        }}

        h3 {{
            margin-top: 22px;
        }}

        .meta {{
            color: #555;
            margin-bottom: 20px;
            font-size: 14px;
        }}

        .card {{
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 16px;
            margin: 18px 0;
            background: #fff;
        }}

        .resumo-executivo {{
            background: #f8fafc;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            padding: 16px;
            margin: 20px 0 28px 0;
        }}

        .kpis {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin: 16px 0 22px 0;
        }}

        .kpi {{
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 12px;
            background: white;
        }}

        .kpi .numero {{
            font-size: 26px;
            font-weight: bold;
            margin-bottom: 4px;
        }}

        .kpi .rotulo {{
            font-size: 13px;
            color: #555;
        }}

        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 12px 0 22px 0;
            font-size: 14px;
        }}

        th, td {{
            border: 1px solid #d6dbe1;
            padding: 8px;
            vertical-align: top;
        }}

        th {{
            background: #f0f2f5;
            text-align: left;
        }}

        tr:nth-child(even) td {{
            background: #fafafa;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: bold;
            white-space: nowrap;
        }}

        .badge.ok {{
            background: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }}

        .badge.apto {{
            background: #fef9c3;
            color: #854d0e;
            border: 1px solid #fde047;
        }}

        .badge.revisar {{
            background: #ffedd5;
            color: #9a3412;
            border: 1px solid #fdba74;
        }}

        .badge.erro {{
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }}

        .erro-card {{
            border-left: 5px solid #dc2626;
            background: #fff7f7;
        }}

        .separador {{
            margin: 36px 0;
            border: 0;
            border-top: 2px solid #e5e7eb;
        }}

        .observacao {{
            color: #555;
            font-size: 13px;
            margin-top: 6px;
        }}
    </style>
</head>

<body>
    <h1>Relatório Consolidado - Retorno Para Estudo</h1>

    <div class="meta">
        <div><b>Versão do script:</b> {_safe_txt(versao_script)}</div>
        <div><b>Início da execução:</b> {_safe_txt(_safe_data(inicio_execucao))}</div>
        <div><b>Fim da execução:</b> {_safe_txt(_safe_data(fim_execucao))}</div>
    </div>

    <section class="resumo-executivo">
        <h2>Resumo da análise dos requerimentos</h2>

        <div class="kpis">
            <div class="kpi">
                <div class="numero">{total}</div>
                <div class="rotulo">Total analisado</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_aprovado}</div>
                <div class="rotulo">Aprovados automaticamente</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_apto}</div>
                <div class="rotulo">Aptos, mas não enviados</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_revisar}</div>
                <div class="rotulo">Revisão manual</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_nao_analisado}</div>
                <div class="rotulo">Não analisados</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_erro}</div>
                <div class="rotulo">Erros de análise</div>
            </div>

            <div class="kpi">
                <div class="numero">{qtd_ignorados_fora_escopo}</div>
                <div class="rotulo">Ignorados antes da análise</div>
            </div>
        </div>

        <h3>Resultado por requerimento analisado</h3>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Requerimento</th>
                    <th>Resultado</th>
                    <th>Ação recomendada</th>
                    <th>Produto</th>
                    <th>Dados técnicos</th>
                    <th>Unidade fabril</th>
                    <th>Docs novos</th>
                    <th>Docs obrigatórios</th>
                    <th>Números RE</th>
                    <th>Enviado?</th>
                    <th>Motivo principal</th>
                </tr>
            </thead>
            <tbody>
                {''.join(linhas_resumo)}
            </tbody>
        </table>

        <h3>Requerimentos ignorados antes da análise automática</h3>

        {
            (
                "<table>"
                "<thead><tr>"
                "<th>#</th><th>Requerimento</th><th>Tipo do produto</th>"
                "<th>Homologação</th><th>Motivo</th><th>Detalhe</th>"
                "</tr></thead><tbody>"
                + "".join(linhas_ignorados)
                + "</tbody></table>"
            )
            if linhas_ignorados
            else "<div class='ok'>Nenhum requerimento foi ignorado antes da análise automática.</div>"
        }

        <div class="observacao">
            A aprovação automática depende dos critérios configurados para Retorno Para Estudo:
            produto e dados técnicos conforme as regras do tipo RE, documentos incluídos quando
            exigidos, documentos obrigatórios atendidos e justificativa dentro dos tipos RE aceitos.
        </div>
    </section>

    <hr class="separador">

    <h2>Detalhamento por requerimento</h2>

    {''.join(blocos_detalhes)}

</body>
</html>
"""

    return html

def _html_requerimento(resultado):
    if _resultado_eh_retorno_para_estudo(resultado):
        return _html_requerimento_retorno_para_estudo(resultado)

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

def _html_consolidado(
    resultados,
    versao_script,
    inicio_execucao,
    fim_execucao,
    ignorados_fora_escopo=None,
):
    ignorados_fora_escopo = ignorados_fora_escopo or []

    retorno_pelos_resultados = bool(
        resultados
        and all(_resultado_eh_retorno_para_estudo(r) for r in resultados)
    )
    retorno_pelos_ignorados = bool(
        ignorados_fora_escopo
        and all(
            "retorno" in str(
                (item or {}).get("fila_sch", "")
                if isinstance(item, dict)
                else ""
            ).lower()
            for item in ignorados_fora_escopo
        )
    )

    if retorno_pelos_resultados or (not resultados and retorno_pelos_ignorados):
        return _html_consolidado_retorno_para_estudo(
            resultados=resultados,
            versao_script=versao_script,
            inicio_execucao=inicio_execucao,
            fim_execucao=fim_execucao,
            ignorados_fora_escopo=ignorados_fora_escopo,
        )

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


def gerar_req_report(
    pasta_saida,
    resultados,
    versao_script,
    inicio_execucao,
    fim_execucao,
    ignorados_fora_escopo=None,
):
    pasta_saida = Path(pasta_saida)
    pasta_req_report = pasta_saida / "req_report"
    pasta_req_report.mkdir(parents=True, exist_ok=True)

    html_consolidado = _html_consolidado(
        resultados=resultados,
        versao_script=versao_script,
        inicio_execucao=inicio_execucao,
        fim_execucao=fim_execucao,
        ignorados_fora_escopo=ignorados_fora_escopo,
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