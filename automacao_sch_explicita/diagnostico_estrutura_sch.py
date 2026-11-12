"""Diagnóstico SOMENTE LEITURA da aba Características Técnicas no SCH.

Não modifica o DOM, não envia formulários nem salva alterações. Requer que o
Selenium esteja autenticado e posicionado em um requerimento.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def classificar_tabela_tecnica(cabecalho):
    """Classifica pelos CABEÇALHOS reais, jamais pelo tipo de produto."""
    campos = " | ".join(_normalizar(c) for c in (cabecalho or []))
    if not campos.strip(" |"):
        return "indefinida"
    frequencia = "frequenc" in campos or "frequency" in campos
    potencia = "potencia" in campos or "power" in campos
    intensidade = "intensidade de campo" in campos or "field strength" in campos
    distancia = "distancia" in campos or "distance" in campos
    fisicos = any(p in campos for p in (
        "tipo de cabo", "blindagem", "bitola", "condutor", "quantidade de pares",
        "material da capa", "comportamento frente", "categoria", "tipo de fibra",
    ))
    if frequencia and intensidade:
        return "rf_intensidade_distancia" if distancia else "rf_intensidade_sem_distancia"
    if frequencia and potencia:
        return "rf_frequencia_potencia"
    if fisicos:
        return "caracteristicas_fisicas"
    if frequencia:
        return "rf_outros_campos"
    return "outra_tabela"


# Coleta compacta e determinística, executada uma só vez dentro do iframe ativo.
# Nunca usa atribuições ou dispatchEvent; somente consulta o DOM.
_SCRIPT_LER_ESTRUTURAS = r"""
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none');
const txt = e => String(e?.innerText || e?.textContent || '').replace(/\s+/g, ' ').trim();
const bases = ['frequenc', 'potencia', 'intensidade', 'distancia', 'modulac', 'designacao', 'emiss', 'tecnolog', 'sar', 'categoria', 'tipo de cabo', 'blindagem', 'condutor', 'bitola', 'pares', 'material da capa', 'chama', 'antena acoplada', 'tipo de fibra'];
const matchesHeader = vals => vals.filter(v => bases.some(k => norm(v).includes(k))).length;
const saida = {tabelas: [], campos_textuais: [], advertencias: []};
// .rows do HTMLTableElement evita a maior parte dos <tr> das tabelas aninhadas.
for (const tabela of document.querySelectorAll('table')) {
  if (!visible(tabela)) continue;
  const linhas = Array.from(tabela.rows || []);
  if (!linhas.length) continue;
  let idx = -1, cab = [], marcador = 0;
  for (let i = 0; i < Math.min(linhas.length, 5); i++) {
    const celulas = Array.from(linhas[i].cells || []);
    if (celulas.length < 2) continue;
    if (celulas.some(c => c.querySelector('table,textarea,input,select,button'))) continue;
    const valores = celulas.map(txt);
    const score = matchesHeader(valores);
    if (score > marcador) { idx = i; cab = valores; marcador = score; }
  }
  if (idx < 0 || marcador === 0) continue; // ignora menus e tabelas do layout
  const corpo = linhas.slice(idx + 1).filter(l => l.cells && l.cells.length >= 2);
  const amostra = corpo.slice(0, 8).map(l => Array.from(l.cells).map(c => txt(c).slice(0, 180)));
  saida.tabelas.push({
    indice: saida.tabelas.length + 1, cabecalho: cab.map(c => c.slice(0, 180)),
    total_linhas: corpo.length, linhas_exemplo: amostra,
    identificador_html: String(tabela.id || '').slice(0, 100),
    colunas: cab.length
  });
}
// Busca textos nomeados (independente da tag/ordem do layout).
const elementos = Array.from(document.querySelectorAll('label, span, div, td, th, strong, b'))
 .filter(e => visible(e) && !e.querySelector('label, span, div, td, th, strong, b'));
for (const [nome, padrao] of [
 ['observacao', /^observacao\s*:?$/],
 ['titulo_caracteristicas_secundarias', /titulo\s*\/\s*descricao.*caracteristicas tecnicas secundarias/],
 ['especificacoes_complementares', /^especificacoes complementares\s*:?$/]
]) {
  let encontrados = 0;
  for (const rotulo of elementos) {
    if (!padrao.test(norm(txt(rotulo)))) continue;
    // Prioriza campo no mesmo contêiner; não inclui textos de outras abas.
    let area = rotulo.parentElement;
    let editor = null;
    for (let k=0; k<4 && area && !editor; k++, area=area.parentElement) {
      const possiveis = Array.from(area.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]'));
      editor = possiveis.find(visible) || null;
    }
    let valor = editor ? (editor.value ?? editor.innerText ?? '') : '';
    if (nome === 'especificacoes_complementares' && !editor) {
      const seguinte = rotulo.nextElementSibling || rotulo.parentElement?.nextElementSibling;
      valor = seguinte ? txt(seguinte) : '';
    }
    // Não salvar conteúdo longo nem justificar conclusão apenas por texto recortado.
    saida.campos_textuais.push({nome, ordem: ++encontrados,
      campo_editavel_detectado: !!editor,
      preenchido: !!String(valor).trim(),
      caracteres: String(valor).length,
      amostra: String(valor).replace(/\s+/g,' ').slice(0, 160)});
    if (encontrados >= 12) break;
  }
}
return saida;
"""


def diagnosticar_estrutura_atual(driver, wait, req):
    """Abre aba técnica e devolve catálogo sem clique em Salvar ou anexos."""
    # Importação tardia: não obriga Selenium durante os testes de classificação.
    from funcoes_sch import (
        clicar_aba_caracteristicas_tecnicas,
        entrar_iframe_detalhe_analise,
    )

    resultado = {
        "status": "erro",
        "requerimento": str((req or {}).get("requerimento") or ""),
        "tipo_produto": str((req or {}).get("tipo_produto") or ""),
        "somente_leitura": True,
        "data_inspecao": datetime.now().isoformat(),
        "tabelas": [], "campos_textuais": [], "familias": [],
        "total_tabelas": 0,
        "motivo": "",
    }
    try:
        clicar_aba_caracteristicas_tecnicas(driver, wait)
        entrar_iframe_detalhe_analise(driver, wait)
        bruto = driver.execute_script(_SCRIPT_LER_ESTRUTURAS) or {}
        tabelas, descartadas = separar_tabelas_comparaveis(bruto.get("tabelas") or [])
        resultado["tabelas_descartadas"] = descartadas
        for tab in tabelas:
            tab["familia"] = classificar_tabela_tecnica(tab.get("cabecalho"))
        resultado["tabelas"] = tabelas
        resultado["campos_textuais"] = bruto.get("campos_textuais") or []
        resultado["total_tabelas"] = len(tabelas)
        resultado["familias"] = sorted({t["familia"] for t in tabelas}) or ["somente_texto_ou_sem_tabela"]
        resultado["status"] = "coletado"
        if not tabelas:
            resultado["motivo"] = "Nenhuma tabela técnica reconhecida pelos cabeçalhos; verificar os campos textuais."
    except Exception as exc:
        resultado["motivo"] = f"Falha na inspeção: {type(exc).__name__}: {exc}"
    return resultado


def separar_tabelas_comparaveis(tabelas):
    """Mantém evidência das tabelas vazias/de apresentação fora do catálogo técnico."""
    aceitas, descartadas = [], []
    for original in tabelas:
        tab = dict(original)
        familia = classificar_tabela_tecnica(tab.get('cabecalho'))
        if not tab.get('total_linhas') or familia in {'outra_tabela', 'indefinida'}:
            tab['motivo_descarte'] = ('sem_linhas_de_dados' if not tab.get('total_linhas')
                                      else 'cabecalho_sem_grandezas_tecnicas')
            descartadas.append(tab)
        else:
            aceitas.append(tab)
    return aceitas, descartadas


def exibir_resumo_diagnostico(resultado):
    numero = resultado.get("requerimento", "")
    print(f"[SCH][RE][DIAGNOSTICO] {numero} | Status: {resultado.get('status')}")
    print(f"[SCH][RE][DIAGNOSTICO] Tabelas: {resultado.get('total_tabelas', 0)} | Famílias: {', '.join(resultado.get('familias') or [])}")
    for tab in resultado.get("tabelas") or []:
        print(f"  Tabela {tab.get('indice')}: {tab.get('familia')} | linhas={tab.get('total_linhas')} | colunas={tab.get('colunas')}")
        print(f"    Cabeçalhos: {' | '.join(tab.get('cabecalho') or [])[:350]}")
    for campo in resultado.get("campos_textuais") or []:
        print(f"  Campo {campo['nome']} #{campo['ordem']}: {'preenchido' if campo['preenchido'] else 'vazio'}")
    if resultado.get("motivo"):
        print(f"[SCH][RE][DIAGNOSTICO] {resultado['motivo']}")


# A coleta completa é separada do catálogo de amostras usado pelos fluxos online.
# Nenhum script abaixo atribui propriedades DOM ou dispara eventos.
_SCRIPT_IDENTIDADE = r"""
const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const evidencias = [];
for (const el of document.querySelectorAll('label,td,th,span,strong,b,h1,h2,h3,legend,input')) {
  if (!visible(el)) continue;
  const texto = String(el.innerText || el.textContent || '').trim();
  const identificador = String(el.id || '').split(':').pop() + ' ' + String(el.name || '').split(':').pop();
  if ((texto.length <= 140 && /^(?:(?:numero|n[º°o]\.?)\s+(?:do\s+)?)?requerimento\b/.test(norm(texto))) || /(?:^|\s)(?:numeroRequerimento|numRequerimento|nrRequerimento)(?:$|\s)/i.test(identificador)) {
    const valores = [texto];
    if (el.tagName === 'INPUT' && !['password','hidden'].includes(el.type)) valores.push(el.value);
    for (const vizinho of [el.nextElementSibling, el.parentElement?.nextElementSibling]) {
      if (vizinho && visible(vizinho)) {
        const t = String(vizinho.innerText || vizinho.textContent || '').trim();
        if (t.length <= 140) valores.push(t);
      }
    }
    evidencias.push({rotulo: texto.slice(0,140), valores: valores.filter(v => v && v.length <= 140)});
  }
}
return {evidencias, frame: window === window.top ? 'principal' : 'iframe', url: location.pathname};
"""

_SCRIPT_TABELAS_COMPLETAS = r"""
const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const bases = ['frequenc','potencia','intensidade','distancia','modulac','emiss','tecnolog','sar','categoria','tipo de cabo','blindagem','bitola','fibra'];
const saida = [];
for (const tabela of document.querySelectorAll('table')) {
  if (!visible(tabela)) continue;
  const rows = Array.from(tabela.rows).filter(r => r.closest('table') === tabela);
  let cab = -1;
  for (let i=0;i<Math.min(rows.length,8);i++) {
    const cs = Array.from(rows[i].cells);
    if (cs.length < 2 || cs.some(c => c.querySelector('table'))) continue;
    const score = cs.filter(c => visible(c) && String(c.innerText || c.textContent).length <= 200 && bases.some(b => norm(c.innerText || c.textContent).includes(b))).length;
    if (score >= 2) { cab = i; break; }
  }
  if (cab < 0) continue;
  const ler = r => Array.from(r.cells).map(c => ({
    texto_original: c.textContent ?? '', texto_visivel: c.innerText ?? c.textContent ?? '',
    tag: c.tagName, rowspan: c.rowSpan, colspan: c.colSpan, visivel:visible(c)
  }));
  const cabecalho = ler(rows[cab]);
  const linhas = rows.slice(cab+1).map((r,i) => ({indice_dom: cab+i+1, visivel:visible(r), celulas: ler(r)}));
  const paginacao = Array.from(tabela.parentElement.querySelectorAll('a,button,select'))
    .filter(e => visible(e) && /pagin|proxim|next|seguinte/i.test(String(e.id)+' '+String(e.className)+' '+String(e.title)+' '+String(e.innerText)))
    .map(e => ({tag:e.tagName, texto:e.innerText || '', id:e.id || ''}));
  const marcadores = Array.from(document.querySelectorAll('legend,h1,h2,h3,h4,label,strong,b,span'))
    .filter(e => visible(e) && String(e.textContent||'').length < 120 &&
      /caracteristicas.*(?:basicas|secundarias)|funcionalidade adicional/.test(norm(e.textContent)) &&
      !!(e.compareDocumentPosition(tabela) & Node.DOCUMENT_POSITION_FOLLOWING));
  const contexto = marcadores.length ? marcadores[marcadores.length-1].textContent : '';
  const secao = /secundarias|funcionalidade adicional/.test(norm(contexto)) ? 'secundarias' : /basicas/.test(norm(contexto)) ? 'basicas' : null;
  saida.push({identificador_html:tabela.id || '', secao, contexto_secao:contexto, cabecalho: cabecalho.map(c => c.texto_original),
    cabecalho_visivel:cabecalho.map(c => c.texto_visivel), celulas_cabecalho:cabecalho,
    linhas:linhas.map(r => r.celulas.map(c => c.texto_original)),
    linhas_visiveis:linhas.map(r => r.celulas.map(c => c.texto_visivel)), linhas_dom:linhas,
    total_linhas:linhas.length, total_colunas:cabecalho.length,
    colunas_por_linha:linhas.map(r => r.celulas.length), paginacao_detectada:paginacao,
    total_linhas_aria:tabela.getAttribute('aria-rowcount'),
    virtualizacao_detectada:!!(tabela.querySelector('[class*="virtual"], [class*="Virtual"]') || tabela.closest('[class*="virtual"], [class*="Virtual"]'))});
}
return {tabelas:saida, pronto:document.readyState === 'complete' && !(window.jQuery && window.jQuery.active)};
"""


def normalizar_requerimento(numero):
    m = re.fullmatch(r'\s*(\d{1,6})/(\d{2}|\d{4})\s*', str(numero or ''))
    if not m:
        raise ValueError('Informe o requerimento completo no formato número/ano.')
    return f'{int(m.group(1)):05d}/{m.group(2)[-2:]}'


def extrair_tabela_dom_para_comparacao(driver, wait):
    """Reutiliza a captura completa, rejeitando layout, paginação e ambiguidades."""
    from funcoes_sch import clicar_aba_caracteristicas_tecnicas, entrar_iframe_detalhe_analise
    from controles_acompanhar import aguardar_ajax
    clicar_aba_caracteristicas_tecnicas(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    aguardar_ajax(driver, wait)
    bruto = driver.execute_script(_SCRIPT_TABELAS_COMPLETAS) or {}
    if not bruto.get('pronto'):
        raise RuntimeError('Tabela SCH ainda não carregada.')
    candidatas = [t for t in bruto.get('tabelas', []) if t.get('total_linhas') and
                  classificar_tabela_tecnica(t.get('cabecalho')) in {
                      'rf_frequencia_potencia', 'rf_intensidade_distancia',
                      'rf_intensidade_sem_distancia', 'rf_outros_campos'}]
    if not candidatas:
        raise RuntimeError('Nenhuma tabela RF comparável encontrada.')
    for ordem, tabela in enumerate(candidatas, 1):
        _validar_tabela_dom_completa(tabela)
        tabela['familia'] = classificar_tabela_tecnica(tabela.get('cabecalho'))
        tabela['ordem_dom'] = ordem
        tabela['origem'] = 'SCH_DOM'
    # Compatibilidade da tabela única; a coleção nunca concatena cabeçalhos distintos.
    resultado = dict(candidatas[0]) if len(candidatas) == 1 else {'cabecalho': [], 'linhas': []}
    resultado['tabelas'] = candidatas
    resultado['total_tabelas'] = len(candidatas)
    resultado['total_linhas'] = sum(t['total_linhas'] for t in candidatas)
    return resultado


def _validar_tabela_dom_completa(tabela):
    if any(not c.get('visivel', True) for c in tabela.get('celulas_cabecalho') or []):
        raise RuntimeError('Cabeçalhos ocultos: captura completa não confirmada.')
    if any(not r.get('visivel', True) for r in tabela.get('linhas_dom') or []):
        raise RuntimeError('Linhas ocultas: captura completa não confirmada.')
    if tabela.get('paginacao_detectada') or tabela.get('virtualizacao_detectada'):
        raise RuntimeError('Tabela paginada/virtualizada: completude não confirmada.')
    colunas = len(tabela['cabecalho'])
    linhas = tabela.get('linhas') or []
    aria = tabela.get('total_linhas_aria')
    if len(linhas) != tabela['total_linhas'] or any(len(l) != colunas for l in linhas):
        raise RuntimeError('Quantidade de células/linhas inconsistente.')
    if aria and str(aria) not in {str(len(linhas)), str(len(linhas)+1)}:
        raise RuntimeError('aria-rowcount indica captura incompleta.')
    if any(c.get('rowspan',1) != 1 or c.get('colspan',1) != 1
           for row in tabela.get('linhas_dom',[]) for c in row.get('celulas',[])):
        raise RuntimeError('Células mescladas exigem revisão; não inferir correspondência.')
    print(f'[SCH][OPCAO4] Captura DOM: {len(linhas)} linhas, {colunas} colunas; valores originais preservados.')


def confirmar_identidade(bruto, esperado):
    """Só aceita evidências rotuladas no iframe; nunca usa a fila ao fundo."""
    if bruto.get('frame') != 'iframe':
        raise RuntimeError('Identidade não confirmada dentro do iframe do requerimento.')
    numeros = {normalizar_requerimento(n) for e in bruto.get('evidencias') or []
               for v in e.get('valores') or []
               for n in re.findall(r'(?<![\d./-])\d{1,6}/(?:\d{4}|\d{2})(?![\d/-])', v)}
    if numeros != {normalizar_requerimento(esperado)}:
        raise RuntimeError(f'Identidade ausente, divergente ou ambígua no iframe: {sorted(numeros)}.')
    return {'requerimento':normalizar_requerimento(esperado), 'evidencias':bruto['evidencias']}


def contexto_iframe(driver):
    from urllib.parse import urlparse, parse_qs
    from funcoes_sch import _aguardar_iframe_detalhe
    driver.switch_to.default_content()
    iframe = _aguardar_iframe_detalhe(driver,timeout=8)
    url = urlparse(iframe.get_attribute('src'))
    campos = parse_qs(url.query)
    ids = campos.get('idRequerimento') or []
    if url.hostname != 'sistemasnet.anatel.gov.br' or len(ids)!=1 or not ids[0].isdigit():
        raise RuntimeError('Iframe sem vínculo inequívoco a um ID interno de requerimento SCH.')
    driver.switch_to.frame(iframe)
    return {'caminho':url.path,'idRequerimento':ids[0],
            'codCct':campos.get('codCct'), 'codInstancia':campos.get('codInstancia')}


def identidade_pdf(texto, esperado):
    numeros = {normalizar_requerimento(n) for n in re.findall(
        r'requerimento\s*(?:n[º°o]\s*[:.]?\s*)?:?\s*(\d{1,6}/(?:\d{4}|\d{2}))(?!\d)', _normalizar(texto))}
    if numeros != {normalizar_requerimento(esperado)}:
        raise RuntimeError('PDF de visualização não identifica inequivocamente o requerimento esperado.')
    return normalizar_requerimento(esperado)


def _baixar_visualizacao_pdf_aba(driver, url, pasta):
    """GET de leitura da aba recém-aberta pelo SCH; nunca segue redirects."""
    from urllib.parse import urlsplit
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from uuid import uuid4
    from pathlib import Path
    alvo=urlsplit(url)
    if alvo.scheme!='https' or alvo.netloc!='sistemasnet.anatel.gov.br' or alvo.path!='/mosaico/sch/rest/visualizarPdf/requerimento':
        raise RuntimeError('Aba de visualização fora da origem e rota exatas do SCH.')
    class SemRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            raise RuntimeError('PDF redirecionou: sessão/identidade não confirmada. Nenhum cookie foi encaminhado a outro destino.')
    # Cookies permanecem apenas em memória; não entram nos logs ou relatórios.
    cookies='; '.join(c['name']+'='+c['value'] for c in driver.get_cookies())
    request=Request(url,headers={'Cookie':cookies,'User-Agent':driver.execute_script('return navigator.userAgent;'),
                                'Cache-Control':'no-cache','Accept':'application/pdf'})
    with build_opener(SemRedirect()).open(request,timeout=10) as resposta:
        if resposta.status!=200:
            raise RuntimeError(f'Visualização PDF respondeu HTTP {resposta.status}; identidade não confirmada.')
        conteudo=resposta.read(50*1024*1024+1)
        if len(conteudo)>50*1024*1024 or not conteudo.startswith(b'%PDF-'):
            raise RuntimeError('Resposta da aba não é um PDF válido ou excede 50 MiB; não aceitar página de login/erro.')
    arquivo=Path(pasta)/('visualizar_requerimento_'+uuid4().hex+'.pdf')
    with arquivo.open('xb') as destino:
        destino.write(conteudo)
    return arquivo


def confirmar_por_visualizacao(driver, esperado, pasta_download, etapa=None):
    """Gera só a visualização PDF do próprio requerimento e vincula ao iframe."""
    import hashlib
    from pathlib import Path
    import pymupdf
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException
    from contextlib import nullcontext
    from urllib.parse import urlsplit
    etapa=etapa or (lambda nome: nullcontext())
    pasta = Path(pasta_download)
    pasta.mkdir(parents=True,exist_ok=True)
    anteriores = set(pasta.iterdir())
    janela = driver.current_window_handle
    abas_antes=set(driver.window_handles)
    with etapa('pdf.contexto_iframe_antes'):
        contexto = contexto_iframe(driver)
    with etapa('pdf.localizar_visualizar_requerimento'):
        botoes = driver.find_elements(By.XPATH,"//button[@title='Visualizar Requerimento']")
        if len(botoes)!=1 or not botoes[0].is_displayed():
            raise RuntimeError('Controle de visualização de leitura não é único ou visível.')
    with etapa('pdf.clicar_visualizar_requerimento_leitura'):
        botoes[0].click()
    ultimo = None
    origem_pdf='download_chrome'
    aba_pdf_lida=False
    def download_estavel(_):
        nonlocal ultimo,origem_pdf,aba_pdf_lida
        novos = [p for p in pasta.iterdir() if p.is_file() and p.suffix.lower()=='.pdf' and p not in anteriores]
        temporarios=[p for p in pasta.iterdir() if p.suffix.lower() in {'.crdownload','.tmp','.part'}]
        if not novos and not temporarios and not aba_pdf_lida:
            abas=[]
            try:
                for handle in set(driver.window_handles)-abas_antes:
                    driver.switch_to.window(handle)
                    url=driver.current_url
                    partes=urlsplit(url)
                    if partes.scheme=='https' and partes.netloc=='sistemasnet.anatel.gov.br' and partes.path=='/mosaico/sch/rest/visualizarPdf/requerimento':
                        abas.append((handle,url))
                if len(abas)>1:
                    raise RuntimeError('Mais de uma aba PDF nova: origem ambígua; identidade não presumida.')
                if abas:
                    driver.switch_to.window(abas[0][0])
                    with etapa('pdf.ler_resposta_da_nova_aba_sch'):
                        _baixar_visualizacao_pdf_aba(driver,abas[0][1],pasta)
                    aba_pdf_lida=True
                    origem_pdf='aba_pdf_sch_get_autenticado'
            finally:
                driver.switch_to.window(janela)
            return False
        if len(novos)!=1 or temporarios:
            return False
        estado = (novos[0],novos[0].stat().st_size)
        pronto = estado == ultimo and estado[1]>0
        ultimo = estado
        return novos[0] if pronto else False
    with etapa('pdf.esperar_download_estavel_45s'):
        try:
            arquivo = WebDriverWait(driver,45,poll_frequency=.5).until(download_estavel)
        except TimeoutException as exc:
            arquivos=[{'nome':p.name,'bytes':p.stat().st_size} for p in pasta.iterdir() if p.is_file()]
            abas=[]
            try:
                for handle in set(driver.window_handles)-abas_antes:
                    driver.switch_to.window(handle)
                    url=urlsplit(driver.current_url)
                    abas.append({'titulo':driver.title,'origem':url.scheme+'://'+url.netloc,'caminho':url.path})
            finally:
                driver.switch_to.window(janela)
            raise TimeoutException(f'Visualizar Requerimento: nenhum PDF novo, único e estável em 45s. Pasta={pasta.resolve()}; arquivos={arquivos}; novas_abas={abas}. Verificar visualizador PDF, bloqueio de pop-up, resposta do SCH e destino do download. Nenhuma identidade foi presumida.') from exc
    with etapa('pdf.contexto_iframe_depois'):
        driver.switch_to.window(janela)
        depois = contexto_iframe(driver)
        if contexto != depois:
            raise RuntimeError('Requerimento mudou durante a visualização PDF; coleta interrompida.')
    with etapa('pdf.ler_numero_e_confirmar_identidade'):
        with pymupdf.open(arquivo) as pdf:
            numero = identidade_pdf(pdf[0].get_text(),esperado)
    return {'requerimento':numero,'metodo':'Visualizar Requerimento: PDF recém-gerado pelo SCH e vinculado ao iframe antes/depois.',
            'vinculo_iframe':contexto,'arquivo_pdf':str(arquivo.resolve()),
            'sha256':hashlib.sha256(arquivo.read_bytes()).hexdigest(), 'origem_pdf':origem_pdf}


def comparar_captura_visual(tabela, fixture):
    """Compara todas as colunas e preserva multiplicidade, sem depender da ordem."""
    from collections import Counter
    from extracao_cct import intervalos, escalar, numero
    chave = lambda t: re.sub(r'[^a-z0-9]', '', _normalizar(t))
    cab = tabela.get('cabecalho_visivel', tabela.get('cabecalho') or [])
    ref = fixture.get('cabecalho') or []
    chaves = [chave(c) for c in cab]
    if len(set(chaves)) != len(chaves) or set(chaves) != {chave(c) for c in ref}:
        return {'status':'inconclusiva', 'motivo':'Cabeçalhos ausentes, extras ou ambíguos.', 'cabecalho_capturado':cab,'cabecalho_visual':ref}
    indices = [chaves.index(chave(c)) for c in ref]
    def valor(c, v):
        t = _normalizar(c)
        if not str(v).strip():
            return ('ausente','vazio')
        if str(v).strip() in {'-','–','—'}:
            return ('ausente','traco')
        if 'frequenc' in t:
            faixas = intervalos(v,c)
            return ('frequencia',tuple(faixas)) if faixas else ('original',chave(v))
        if 'potencia' in t:
            n = escalar(v,c,'potencia_saida')
            if n is not None:
                return ('numero',round(n,10))
        if 'sar' in t and re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*', str(v)):
            return ('numero',numero(v))
        return ('original',chave(v))
    capturadas = tabela.get('linhas_visiveis', tabela.get('linhas') or [])
    if any(len(l)!=len(cab) for l in capturadas):
        return {'status':'inconclusiva','motivo':'Linhas com larguras diferentes; verificar células mescladas.'}
    real = Counter(tuple(valor(c,l[i]) for c,i in zip(ref,indices)) for l in capturadas)
    visual = Counter(tuple(valor(c,v) for c,v in zip(ref,l)) for l in fixture.get('linhas') or [])
    return {'status':'ok' if real == visual else 'divergente', 'linhas_capturadas':len(capturadas),
            'linhas_visuais':len(fixture.get('linhas') or []), 'colunas_conferidas':ref,
            'registros_extras_captura':sum((real-visual).values()),
            'registros_ausentes_captura':sum((visual-real).values()),
            'criterio':'Multiconjunto de todas as colunas; números normalizados e formatação textual desconsiderada. Originais preservados.'}


def capturar_requerimento_somente_leitura(driver, wait, requerimento, pasta_saida,
                                         fixture=None, cct=None, tabela_id=None, pasta_download=None,
                                         identidade_por_visualizacao=False):
    from pathlib import Path
    from urllib.parse import urlparse
    import json
    from funcoes_sch import entrar_iframe_detalhe_analise, clicar_aba_caracteristicas_tecnicas
    from selenium.webdriver.support.ui import WebDriverWait
    esperado = normalizar_requerimento(requerimento)
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True,exist_ok=True)
    resultado = {'status':'erro','somente_leitura':True,'requerimento_esperado':esperado,
                 'captura_autenticada_real':False,'navegador_encerrado':False,
                 'origem':'Selenium DOM','data_utc':datetime.now(timezone.utc).isoformat()}
    try:
        url = urlparse(driver.current_url)
        if url.hostname != 'sistemasnet.anatel.gov.br' or not url.path.startswith('/mosaico/sch/'):
            raise RuntimeError('Navegador fora do domínio/caminho SCH esperado.')
        entrar_iframe_detalhe_analise(driver,wait)
        evidencia = driver.execute_script(_SCRIPT_IDENTIDADE) or {}
        resultado['evidencias_identidade_antes'] = evidencia
        if identidade_por_visualizacao and not evidencia.get('evidencias'):
            if not pasta_download:
                raise RuntimeError('Informe a pasta de downloads para a identidade por visualização.')
            resultado['identidade_antes'] = confirmar_por_visualizacao(driver,esperado,pasta_download)
        else:
            resultado['identidade_antes'] = confirmar_identidade(evidencia,esperado)
        clicar_aba_caracteristicas_tecnicas(driver,wait)
        entrar_iframe_detalhe_analise(driver,wait)
        anterior = None
        def estavel(d):
            nonlocal anterior
            bruto = d.execute_script(_SCRIPT_TABELAS_COMPLETAS) or {}
            pronto = bruto.get('pronto') and bruto.get('tabelas')
            igual = pronto and anterior == bruto
            anterior = bruto
            return bruto if igual else False
        snapshot = WebDriverWait(driver,20,poll_frequency=.5).until(estavel)
        resultado['captura_dom'] = snapshot
        if resultado['identidade_antes'].get('vinculo_iframe'):
            vinculo = contexto_iframe(driver)
            if vinculo != resultado['identidade_antes']['vinculo_iframe']:
                raise RuntimeError('O vínculo de identidade do iframe mudou após a captura.')
            resultado['identidade_depois'] = {'requerimento':esperado,'vinculo_iframe':vinculo}
        else:
            evidencia = driver.execute_script(_SCRIPT_IDENTIDADE) or {}
            resultado['evidencias_identidade_depois'] = evidencia
            resultado['identidade_depois'] = confirmar_identidade(evidencia,esperado)
        tabelas = snapshot['tabelas']
        if tabela_id:
            tabelas = [t for t in tabelas if t['identificador_html']==tabela_id]
        if len(tabelas)!=1:
            raise RuntimeError('Tabela técnica não é única; informe --tabela-id após inspecionar o JSON.')
        tabela = tabelas[0]
        resultado['tabela_capturada'] = tabela
        if not tabela['total_linhas'] or not tabela['total_colunas']:
            raise RuntimeError('Tabela sem linhas ou cabeçalhos; captura não validada.')
        if any(n != tabela['total_colunas'] for n in tabela['colunas_por_linha']):
            raise RuntimeError('Larguras de linhas inconsistentes; analisar células mescladas antes da comparação.')
        if any(not r.get('visivel',True) for r in tabela.get('linhas_dom') or []):
            raise RuntimeError('Linhas ocultas no DOM; correspondência com a tabela visual exige revisão.')
        if tabela.get('paginacao_detectada') or tabela.get('virtualizacao_detectada'):
            raise RuntimeError('Paginação/virtualização detectada; completude não confirmada nesta captura.')
        if tabela.get('total_linhas_aria') and int(tabela['total_linhas_aria']) > tabela['total_linhas']+1:
            raise RuntimeError('Quantidade de linhas declarada excede as linhas presentes no DOM.')
        resultado.update(status='capturado',captura_autenticada_real=True)
        if fixture:
            referencia = json.loads(Path(fixture).read_text(encoding='utf-8'))
            resultado['comparacao_fixture_visual'] = comparar_captura_visual(tabela,referencia)
        if cct:
            from pdf_parser import parsear_certificado_pdf
            from funcoes_sch import comparar_tabelas_tecnicas_sch_cct, analisar_sar_cct
            dados = parsear_certificado_pdf(cct)
            entrada = {'cabecalho':tabela['cabecalho_visivel'],'linhas':tabela['linhas_visiveis'],
                       'origem':'Captura Selenium DOM autenticada; identidade confirmada antes/depois.',
                       'captura_selenium':True,'conferencia_visual_sch':False}
            resultado['comparacao_cct_sch'] = comparar_tabelas_tecnicas_sch_cct(entrada,dados['tabela_tecnica_cct'])
            resultado['sar_cct'] = analisar_sar_cct(dados)
            resultado['certificado_cct'] = dados['numero_certificado']
    except Exception as exc:
        resultado.update(status='erro',motivo=f'{type(exc).__name__}: {exc}')
    finally:
        destino = pasta/'captura_sch.json'
        destino.write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
    return resultado


def salvar_relatorio_diagnostico(resultado, destino):
    """Relatório derivado do JSON capturado; não acessa o navegador."""
    import json
    from html import escape
    from pathlib import Path
    from gerador_relatorio import _css, _html_comparacao_tabela_tecnica
    tabela = resultado.get('tabela_capturada') or {}
    corpo = ['<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Diagnóstico Selenium SCH</title>',
             _css(),'</head><body><h1>Diagnóstico de leitura do requerimento ',
             escape(str(resultado.get('requerimento_esperado') or '')),'</h1>',
             '<p>Captura DOM via Selenium. Login e abertura manuais; sem edição ou comandos de gravação. Navegador mantido aberto.</p>']
    resumo = {k:resultado.get(k) for k in ('status','captura_autenticada_real','data_utc',
               'identidade_antes','identidade_depois','comparacao_fixture_visual','motivo') if k in resultado}
    corpo.extend(['<h2>Identidade e validação da captura</h2><pre>',escape(json.dumps(resumo,ensure_ascii=False,indent=2)),'</pre>'])
    if tabela:
        corpo.append('<h2>Valores originais do DOM</h2><table><thead><tr>'+''.join('<th>'+escape(c)+'</th>' for c in tabela['cabecalho'])+'</tr></thead><tbody>')
        for linha in tabela['linhas']:
            corpo.append('<tr>'+''.join('<td style="white-space:pre-wrap">'+escape(v)+'</td>' for v in linha)+'</tr>')
        corpo.append('</tbody></table>')
    comp = resultado.get('comparacao_cct_sch')
    if comp:
        corpo.extend(['<h2>Resultado CCT × SCH</h2><pre>',
                      escape(json.dumps(comp.get('resumo_correspondencias'),ensure_ascii=False,indent=2)),'</pre>',
                      _html_comparacao_tabela_tecnica({'conferencia_sch_cct':{'comparacao_tabela_tecnica':comp}})])
    corpo.append('</body></html>')
    Path(destino).write_text(''.join(corpo),encoding='utf-8')


def main():
    """Entrada independente: login e abertura manuais; coleta automática só de leitura."""
    import argparse
    from pathlib import Path
    from navegador import criar_driver
    from funcoes_sch import abrir_sch
    parser = argparse.ArgumentParser(description='Diagnóstico SCH somente leitura; não executa as opções 3/4.')
    parser.add_argument('--requerimento', required=True)
    parser.add_argument('--navegador', choices=['edge','chrome'],default='edge')
    parser.add_argument('--saida',default='diagnostico_sch')
    parser.add_argument('--fixture')
    parser.add_argument('--cct')
    parser.add_argument('--tabela-id')
    parser.add_argument('--caminho-driver')
    parser.add_argument('--caminho-navegador')
    parser.add_argument('--sinal-pronto', help='Arquivo local novo contendo o número do requerimento após login/abertura manuais.')
    parser.add_argument('--debugger-address', help='Reconectar à janela de diagnóstico já aberta, em localhost:porta.')
    parser.add_argument('--capturar-agora', action='store_true', help='Somente com --debugger-address, após login e abertura manuais já concluídos.')
    parser.add_argument('--pasta-download', help='Pasta de downloads efetiva da janela reconectada.')
    parser.add_argument('--identidade-por-visualizacao',action='store_true')
    args = parser.parse_args()
    req = normalizar_requerimento(args.requerimento)
    if args.debugger_address and not re.fullmatch(r'(?:127\.0\.0\.1|localhost):\d{1,5}',args.debugger_address):
        raise ValueError('Reconexão permitida somente a um navegador local.')
    if args.capturar_agora and not args.debugger_address:
        raise ValueError('--capturar-agora exige reconexão a uma janela já aberta.')
    pasta = Path(args.saida).resolve()/req.replace('/','_')/datetime.now().strftime('%Y%m%d_%H%M%S')
    pasta.mkdir(parents=True,exist_ok=True)
    import json
    def estado(status, motivo='', captura=False):
        (pasta/'estado_execucao.json').write_text(json.dumps({'status':status,'motivo':motivo,
            'requerimento':req,'captura_autenticada_real':captura,'somente_leitura':True},ensure_ascii=False,indent=2),encoding='utf-8')
    sinal = Path(args.sinal_pronto).resolve() if args.sinal_pronto else None
    if sinal and sinal.exists():
        raise ValueError('O arquivo de sinal já existe; use um caminho novo para esta sessão.')
    estado('iniciando_navegador')
    try:
        driver,wait,_,downloads = criar_driver(navegador=args.navegador,pasta_base=pasta,
                                      caminho_driver=args.caminho_driver,caminho_navegador=args.caminho_navegador,
                                      debugger_address=args.debugger_address)
        if not args.debugger_address:
            abrir_sch(driver)
    except Exception as exc:
        estado('erro_inicializacao',f'{type(exc).__name__}: {exc}')
        raise
    print(f'DIAGNÓSTICO: {req}. Faça login e abra MANUALMENTE somente esse requerimento em Dados Gerais.',flush=True)
    estado('aguardando_login_e_abertura_manual')
    if args.capturar_agora:
        pass
    elif sinal:
        import time
        print(f'Aguardando sinal manual em {sinal}. Navegador permanece aberto.',flush=True)
        while not sinal.exists():
            time.sleep(.5)
        if normalizar_requerimento(sinal.read_text(encoding='utf-8').strip()) != req:
            estado('erro_sinal','Sinal não corresponde ao requerimento esperado.')
            raise ValueError('Sinal não corresponde ao requerimento esperado.')
    else:
        input('Quando o requerimento estiver aberto, pressione Enter para confirmar identidade e coletar. Não clique em Salvar/Aprovar/Recusar.\n')
    resultado = capturar_requerimento_somente_leitura(driver,wait,req,pasta,args.fixture,args.cct,args.tabela_id,
                  pasta_download=args.pasta_download or downloads,identidade_por_visualizacao=args.identidade_por_visualizacao)
    salvar_relatorio_diagnostico(resultado,pasta/'relatorio_diagnostico.html')
    print(f"Status: {resultado['status']} | JSON: {pasta/'captura_sch.json'}",flush=True)
    if resultado.get('motivo'):
        print(resultado['motivo'],flush=True)
    estado(resultado['status'],resultado.get('motivo',''),resultado['captura_autenticada_real'])
    print('Navegador mantido aberto. Nenhuma rotina de escrita foi executada.',flush=True)


if __name__ == '__main__':
    main()
