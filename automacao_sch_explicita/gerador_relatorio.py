import json
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


def _html_requerimento(resultado):
    req_numero = _fmt_req(resultado)
    analise = _fmt_analise(resultado)
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

        <h2>Dados do SCH</h2>
        <ul>
            <li><b>Observação em Características Técnicas:</b> {escape(str(resultado.get("observacao_caracteristicas", "")))}</li>
            <li><b>Informações Adicionais:</b> {escape(str((resultado.get("informacoes_adicionais") or {}).get("texto", "")))}</li>
            <li><b>CCT localizado:</b> {escape(str(resultado.get("pdf_cct", "")))}</li>
            <li><b>Downloads realizados:</b> {escape(str(resultado.get("downloads_realizados", 0)))}</li>
        </ul>
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