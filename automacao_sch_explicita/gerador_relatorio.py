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
    return (
        (resultado.get("requerimento") or {}).get("requerimento")
        or resultado.get("requerimento_numero")
        or "sem_numero"
    )


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
    return ", ".join(analise.get("equipamentos", [])) or (req.get("tipo_produto") or "Não identificado")


def _fmt_numero_certificado(resultado):
    return (_fmt_dados_pdf(resultado).get("numero_certificado") or "").strip() or "Não identificado"


def _fmt_homologacao(resultado):
    return (_fmt_dados_pdf(resultado).get("homologacao") or "").strip() or "Não identificado"


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


def _criar_tabela_normas(normas):
    if not normas:
        return "<p>Nenhuma norma aplicável identificada.</p>"

    linhas = [
        "<table><thead><tr><th>Status</th><th>Norma</th><th>Motivador(es)</th></tr></thead><tbody>"
    ]
    for item in normas:
        linhas.append(
            "<tr>"
            f"<td>{'✓' if item.get('status') == 'ok' else escape(str(item.get('status', '')))}</td>"
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
        "<table><thead><tr><th>Documento</th><th>Lab</th><th>Sol</th><th>Fab</th><th>Mod</th></tr></thead><tbody>"
    ]
    for item in relatorios:
        linhas.append(
            "<tr>"
            f"<td>{escape(str(item.get('documento', '')))}</td>"
            f"<td>{'✓' if item.get('lab') else '✗'}</td>"
            f"<td>{'✓' if item.get('sol') else '✗'}</td>"
            f"<td>{'✓' if item.get('fab') else '✗'}</td>"
            f"<td>{'✓' if item.get('mod') else '✗'}</td>"
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
        ("Homologação", dados_pdf.get("homologacao", "")),
        ("Tipo do produto", dados_pdf.get("tipo_produto", "")),
        ("Modelo", dados_pdf.get("modelo", "")),
        ("Fabricante", dados_pdf.get("fabricante", "")),
        ("OCD", dados_pdf.get("ocd", "")),
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
        "<table><thead><tr><th>Campo</th><th>SCH</th><th>CCT</th><th>Status</th></tr></thead><tbody>",
    ]

    for item in itens:
        campo = _nome_humano_campo(item.get("campo", ""))
        valor_sch = (item.get("valor_sch") or "").strip() or "Não identificado"
        valor_cct = (item.get("valor_cct") or "").strip() or "Não identificado"
        status = item.get("status", "")

        if status == "ok":
            status_txt = "OK"
        elif status == "divergente":
            status_txt = "Divergente"
        elif status == "ausente_em_um_dos_lados":
            status_txt = "Ausente em um dos lados"
        elif status == "ausente_nos_dois":
            status_txt = "Ausente nos dois"
        elif status == "não_comparado":
            status_txt = "Não comparado"
        else:
            status_txt = status or "Não identificado"

        linhas.append(
            "<tr>"
            f"<td>{escape(campo)}</td>"
            f"<td>{escape(valor_sch)}</td>"
            f"<td>{escape(valor_cct)}</td>"
            f"<td>{escape(status_txt)}</td>"
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