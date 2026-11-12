"""Orquestração de leitura da opção 4, com capacidade de escrita removida."""
from pathlib import Path
import inspect
import ast
import json
import re
import textwrap

SCRIPT_INSPECAO_NAV = """return {botoes:Array.from(document.querySelectorAll('button,a')).filter(e=>e.getClientRects().length && /Dados Gerais/.test(e.innerText)).map(e=>({id:e.id,texto:e.innerText,onclick:e.getAttribute('onclick'),disabled:e.disabled})),mensagens:Array.from(document.querySelectorAll('.ui-messages-error,.ui-growl-message,.ui-dialog-content')).filter(e=>e.getClientRects().length).map(e=>(e.innerText||'').slice(0,400)),ajax:window.jQuery?.active,recursos:performance.getEntriesByType('resource').filter(e=>e.initiatorType==='xmlhttprequest').slice(-3).map(e=>({caminho:new URL(e.name).pathname,status:e.responseStatus}))};"""


SCRIPT_LINHAS_ANEXOS = """return Array.from(arguments[0].querySelectorAll('tr')).map(r=>Array.from(r.children).filter(c=>c.tagName==='TD').map(c=>c.innerText)).filter(r=>r.length);"""
SCRIPT_VINCULO_DOWNLOAD = """const e=arguments[0], td=e.closest('td'), tr=e.closest('tr'); return {celula:td?.cellIndex,tag:e.tagName,texto:e.innerText,linha:tr?Array.from(tr.children).map(c=>c.innerText):[]};"""


def ler_linhas_anexos(guard, wait):
    """Lê cada tabela em uma chamada; refaz a localização após atualização AJAX."""
    import funcoes_sch as s
    return s.ler_linhas_anexos_re(guard,wait)


class AcaoBloqueada(RuntimeError):
    pass


class ElementoLeitura:
    __slots__ = ('_elemento','_guard')

    def __init__(self, elemento, guard):
        self._elemento,self._guard = elemento,guard

    def __getattr__(self, nome):
        if nome in {'text','tag_name','id','rect'}:
            return getattr(self._elemento,nome)
        if nome in {'get_attribute','get_dom_attribute','get_property','is_displayed','is_enabled','is_selected'}:
            return getattr(self._elemento,nome)
        if nome in {'find_element','find_elements'}:
            return lambda *a,**kw:self._guard.envolver(getattr(self._elemento,nome)(*a,**kw))
        self._guard.bloquear('elemento.'+nome)

    def click(self):
        from mvp_simplificada_re import normalizar
        if self._elemento.id in self._guard._downloads:
            return self._guard.clicar_download_cct(self)
        texto=normalizar(self._elemento.text)
        if self._elemento.tag_name.lower() not in {'a','button'} or texto not in self._guard.navegacoes:
            self._guard.bloquear('click: '+texto)
        self._guard.verificar_contexto()
        self._guard.eventos.append({'acao':'navegacao_leitura','controle':texto})
        try:
            # O SCH usa handlers PrimeFaces que nem sempre reagem ao clique
            # nativo ao reconectar. Só este caminho, após validar legenda e
            # contexto, pode disparar o clique JS de navegação conhecido.
            self._guard._driver.execute_script('arguments[0].click();',self._elemento)
        except Exception as exc:
            self._guard.eventos.append({'erro_navegacao':type(exc).__name__+': '+str(exc)[:300]})
            raise


class TrocaLeitura:
    def __init__(self, guard):
        self.guard=guard

    def default_content(self):
        self.guard._driver.switch_to.default_content()

    def frame(self, frame):
        self.guard._driver.switch_to.frame(self.guard.desembrulhar(frame))

    def window(self, handle):
        self.guard._driver.switch_to.window(handle)

    def __getattr__(self, nome):
        self.guard.bloquear('switch_to.'+nome)


class DriverSomenteLeitura:
    """Barreira por allowlist: scripts desconhecidos, escrita e ações W3C falham fechadas.

    Protege contra caminhos indiretos das rotinas existentes, não contra código
    Python hostil que deliberadamente acesse os atributos privados desta classe.
    """
    somente_leitura=True
    navegacoes={'dados gerais','caracteristicas tecnicas','informacoes adicionais','anexos',
                'certificado de conformidade tecnica - cct'}

    def __init__(self, driver, contexto_esperado):
        self._driver=driver
        self.contexto_esperado=contexto_esperado
        self.eventos=[]
        self.scripts=set()
        self._selado=False
        self._downloads={}
        self._alvo_download=None
        self.switch_to=TrocaLeitura(self)

    def bloquear(self, acao):
        self.eventos.append({'acao':acao,'status':'bloqueada_simulacao'})
        raise AcaoBloqueada('Simulação: ação bloqueada: '+acao)

    def definir_alvo_download_cct(self, alvo):
        self.verificar_contexto()
        self._alvo_download={k:str(alvo.get(k,'')) for k in ('id','data_hora','nome_anexo')}

    def autorizar_download_cct(self, elemento, registro):
        self.verificar_contexto()
        if not self._alvo_download or any(str(registro.get(k,''))!=v for k,v in self._alvo_download.items()):
            self.bloquear('download_fora_do_anexo_selecionado')
        url=self._validar_link_get_cct(elemento)
        vinculo=self.execute_script(SCRIPT_VINCULO_DOWNLOAD,elemento)
        esperado=[registro['id'],registro['tipo_documento'],registro.get('detalhamento',''),registro['data_hora'],registro['nome_anexo']]
        linha=vinculo.get('linha',[])
        if vinculo.get('tag')!='A' or vinculo.get('celula')!=4 or len(linha)<5 or any(linha[i].strip()!=esperado[i].strip() for i in (0,1,3,4)):
            self.bloquear('link_download_sem_identidade_confirmada')
        self._downloads[elemento.id]={'vinculo':vinculo,'url':url}

    def _validar_link_get_cct(self, elemento):
        from urllib.parse import urlsplit,parse_qs
        href=elemento.get_attribute('href')
        if not isinstance(href,str) or elemento.get_attribute('onclick') not in (None,''):
            self.bloquear('download_com_handler_ou_url_nao_confirmada')
        u=urlsplit(href);q=parse_qs(u.query)
        if (u.scheme!='https' or u.netloc!='sistemasnet.anatel.gov.br'
                or u.path!='/mosaico/sch/download' or len(q.get('id',[]))!=1
                or not q['id'][0].isdigit()):
            self.bloquear('link_nao_e_get_de_download_cct')
        return href

    def clicar_download_cct(self, elemento):
        self.verificar_contexto()
        anterior=self._downloads.pop(elemento.id)
        if (self._validar_link_get_cct(elemento)!=anterior['url']
                or self.execute_script(SCRIPT_VINCULO_DOWNLOAD,elemento)!=anterior['vinculo']):
            self.bloquear('link_download_alterado')
        self.eventos.append({'acao':'download_cct_somente_leitura','anexo':self._alvo_download})
        self._driver.execute_script('arguments[0].click();',self.desembrulhar(elemento))

    def registrar(self, script):
        if self._selado:
            self.bloquear('allowlist_selada')
        if re.search(r'dispatchEvent|\.click\(|\.submit\(|setAttribute|fetch\(|XMLHttpRequest|\.(?:value|innerHTML|textContent)\s*=',script):
            self.bloquear('registro_de_script_de_escrita')
        self.scripts.add(script.strip())

    def registrar_leituras(self, funcoes):
        for funcao in funcoes:
            tree=ast.parse(textwrap.dedent(inspect.getsource(funcao)))
            for node in ast.walk(tree):
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='script' for t in node.targets) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                    self.registrar(node.value.value)
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='execute_script' and node.args:
                    if isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                        script=node.args[0].value
                        if re.search(r'dispatchEvent|\.click\(|\.submit\(|setAttribute|fetch\(|XMLHttpRequest|\.(?:value|innerHTML|textContent)\s*=',script):
                            raise ValueError('Script de escrita não pode ser registrado como leitura.')
                        self.registrar(script)

    def envolver(self, valor):
        from selenium.webdriver.remote.webelement import WebElement
        if isinstance(valor,WebElement):
            return ElementoLeitura(valor,self)
        if isinstance(valor,list):
            return [self.envolver(v) for v in valor]
        if isinstance(valor,dict):
            return {k:self.envolver(v) for k,v in valor.items()}
        return valor

    def desembrulhar(self, valor):
        if isinstance(valor,ElementoLeitura):
            return valor._elemento
        if isinstance(valor,(list,tuple)):
            return [self.desembrulhar(v) for v in valor]
        return valor

    def verificar_contexto(self):
        from diagnostico_estrutura_sch import contexto_iframe
        from urllib.parse import urlparse,parse_qs
        script="return {url:location.href, principal:window===window.top,ultimo_status:performance.getEntriesByType('resource').filter(e=>e.initiatorType==='xmlhttprequest').slice(-1).map(e=>e.responseStatus)[0]};"
        atual=self._driver.execute_script(script)
        if atual['principal']:
            contexto=contexto_iframe(self._driver)
            atual=self._driver.execute_script(script)
        else:
            url=urlparse(atual['url']);q=parse_qs(url.query)
            if url.hostname!='sistemasnet.anatel.gov.br':
                self.bloquear('dominio_do_iframe_divergente')
            contexto={'caminho':url.path,'idRequerimento':(q.get('idRequerimento') or [None])[0],
                      'codCct':q.get('codCct'),'codInstancia':q.get('codInstancia')}
        if contexto!=self.contexto_esperado:
            self.bloquear('contexto_do_requerimento_divergente')
        if atual.get('ultimo_status') in {401,403}:
            self.bloquear('sessao_nao_autorizada_http_'+str(atual['ultimo_status']))

    def execute_script(self, script, *args):
        # O helper de categorias existente usa JS click. Converte para o clique
        # nativo sob a mesma allowlist, sem executar JavaScript arbitrário.
        if script.strip()=='arguments[0].click();' and len(args)==1 and isinstance(args[0],ElementoLeitura):
            return args[0].click()
        if script.strip() not in self.scripts:
            self.eventos.append({'script_nao_autorizado':script[:250]})
            self.bloquear('execute_script_nao_autorizado')
        return self.envolver(self._driver.execute_script(script,*[self.desembrulhar(a) for a in args]))

    def find_elements(self,*args):
        return self.envolver(self._driver.find_elements(*args))

    def find_element(self,*args):
        return self.envolver(self._driver.find_element(*args))

    def __getattr__(self,nome):
        if nome=='get_log':
            return lambda tipo:self._driver.get_log(tipo) if tipo=='browser' else self.bloquear('log_nao_permitido')
        if nome in {'current_url','current_window_handle','window_handles','title'}:
            return getattr(self._driver,nome)
        self.bloquear('driver.'+nome)


def preparar_guard(driver, contexto, leituras_adicionais=()):
    import funcoes_sch as s
    import utils
    from diagnostico_estrutura_sch import _SCRIPT_TABELAS_COMPLETAS
    guard=DriverSomenteLeitura(driver,contexto)
    guard.registrar(_SCRIPT_TABELAS_COMPLETAS)
    guard.registrar(SCRIPT_INSPECAO_NAV)
    guard.registrar(SCRIPT_LINHAS_ANEXOS)
    guard.registrar(s.SCRIPT_LINHAS_ANEXOS_RE)
    guard.registrar(s.SCRIPT_DIAGNOSTICO_CTS)
    guard.registrar(SCRIPT_VINCULO_DOWNLOAD)
    guard.registrar_leituras([s.baixar_anexos_da_categoria_atual])
    guard.registrar_leituras([s._texto_visivel_sch,s._clicar_aba_por_rotulo,
        s._localizar_campo_titulo_caracteristicas_secundarias,utils.esperar_tela_carregar,
        s._localizar_textarea_acompanhar_processo,s._contexto_tabela_secundaria_sch,
        utils._documento_pronto,utils._ajax_primefaces_pronto])
    guard.registrar_leituras([s._localizar_checkbox_acompanhar_processo,s._checkbox_esta_marcado])
    guard.registrar_leituras(leituras_adicionais)
    guard._selado=True
    return guard


def coletar_estado_simulacao(guard, pasta, requerimento=None):
    """Somente leitura; não chama processamento de filas ou rotinas de download."""
    import funcoes_sch as s
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from diagnostico_estrutura_sch import _SCRIPT_TABELAS_COMPLETAS
    wait=WebDriverWait(guard,12)
    guard.verificar_contexto()
    dados=s.extrair_dados_certificado_sch(guard,wait)
    texto=s._texto_visivel_sch(guard)
    tipo=s._extrair_valor_sch_por_rotulo(texto,[r'Tipo\s+do\s+Produto',r'Tipo\s+de\s+Produto'])
    estado={'dados_certificado_sch':{k:dados.get(k) for k in ('numero_certificado','modelo_sch_dados_gerais','data_certificado','data_validade')},'tipo_produto':tipo}
    def salvar():
        Path(pasta).mkdir(parents=True,exist_ok=True)
        (Path(pasta)/'estado_leitura.json').write_text(json.dumps(estado,ensure_ascii=False,indent=2),encoding='utf-8')
    salvar()
    s.clicar_aba_caracteristicas_tecnicas(guard,wait)
    s.entrar_iframe_detalhe_analise(guard,wait)
    estado['observacao']=__import__('mvp_simplificada_re').ler_observacao_atual_re(guard,wait)
    estado['cts']=s.diagnosticar_campo_cts_re(guard)
    campo=s._localizar_campo_titulo_caracteristicas_secundarias(guard,timeout=1.5) if estado['cts']['localizado'] else None
    if campo:
        estado['cts']['contexto']=s._contexto_tabela_secundaria_sch(guard,campo)
    estado['tabelas_dom']=guard.execute_script(_SCRIPT_TABELAS_COMPLETAS)
    salvar()
    s.clicar_aba_informacoes_adicionais(guard,wait)
    s.entrar_iframe_detalhe_analise(guard,wait)
    campo=s._localizar_textarea_acompanhar_processo(guard,wait,timeout=2)
    estado['acompanhar']={'localizado':bool(campo),'valor':campo.get_attribute('value') if campo else None}
    caixa=s._localizar_checkbox_acompanhar_processo(guard,wait,timeout=1)
    estado['acompanhar']['checkbox_encontrado']=bool(caixa)
    estado['acompanhar']['marcado']=s._checkbox_esta_marcado(caixa) if caixa else None
    salvar()
    s.clicar_aba_anexos(guard,wait)
    try:
        s.clicar_categoria_anexo(guard,wait,'Certificado de Conformidade Técnica - CCT')
    except Exception as exc:
        estado['aviso_categoria_cct']=str(exc)
        # Nenhum campo é alterado: ainda podemos inspecionar a tabela já exibida.
    anexos=[]
    for valores in ler_linhas_anexos(guard,wait):
        if len(valores)>=5:
            tipo_normal=__import__('mvp_simplificada_re').normalizar(valores[1])
            categoria='CCT' if 'cct' in tipo_normal or 'certificado de conformidade tecnica' in tipo_normal else valores[1]
            anexos.append({'categoria':categoria,'id':valores[0].strip(),'tipo_documento':valores[1],
                           'detalhamento':valores[2],'data_hora':valores[3].strip(),'nome_anexo':valores[4].strip(),'arquivo':''})
    estado['anexos_cct']=anexos
    estado['exigir_download_real']=True
    selecao,baixados=s.baixar_cct_mais_recente_confirmado_re(guard,wait,{'requerimento':requerimento},pasta,Path(pasta)/'browser_downloads')
    estado['selecao_download']=selecao
    estado['anexos_cct']=baixados
    guard.verificar_contexto()
    estado['auditoria']=guard.eventos
    Path(pasta).mkdir(parents=True,exist_ok=True)
    (Path(pasta)/'estado_leitura.json').write_text(json.dumps(estado,ensure_ascii=False,indent=2),encoding='utf-8')
    return estado


def analisar_estado_integrado(guard, estado, requerimento, pasta, diretorio_ccts):
    """Entra no gate real da opção 4 em modo simulado; não valida campos ausentes."""
    import fluxo_sch as f
    import funcoes_sch as s
    from pdf_parser import parsear_certificado_pdf
    from caracteristicas_secundarias import inferir_caracteristicas_secundarias
    from mvp_simplificada_re import avaliar_cobertura_mvp
    from diagnostico_estrutura_sch import classificar_tabela_tecnica
    from selenium.webdriver.support.ui import WebDriverWait
    dados_sch=estado.get('dados_certificado_sch') or {}
    req={'requerimento':requerimento,'tipo_produto':estado.get('tipo_produto'),
         'certificado':dados_sch.get('numero_certificado'),
         'modelo':dados_sch.get('modelo_sch_dados_gerais'),
         'modelo_sch_dados_gerais':dados_sch.get('modelo_sch_dados_gerais')}
    rel={'modo':'simulacao','requerimento':req,'gravacoes_executadas':0,'navegador_encerrado':False,
         'estado_leitura':estado,'tipo_permitido':f._tipo_produto_permitido_simplificada(req),
         'riscos':[],'operacoes_reais':'Leitura de abas/DOM; nenhuma gravação ou aprovação.'}
    anexos=__import__('copy').deepcopy(estado.get('anexos_cct') or [])
    def chave(nome):
        nome=nome[:-4] if nome.lower().endswith('.pdf') else nome
        return re.sub(r'[^a-z0-9]','',__import__('mvp_simplificada_re').normalizar(nome))
    arquivos=[] if estado.get('exigir_download_real') else list(Path(diretorio_ccts).glob('*.pdf'))
    for anexo in anexos:
        iguais=[p for p in arquivos if chave(p.name)==chave(anexo['nome_anexo'])]
        if len(iguais)==1:
            anexo['arquivo']=str(iguais[0].resolve())
            anexo['origem_arquivo']='Reutilização local por nome exato normalizado, conforme metadados; não é novo download.'
    selecao=(estado.get('selecao_download') or {'status':'sem_download_confirmado','arquivo':''}) if estado.get('exigir_download_real') else f._selecionar_cct_mais_recente_re(anexos,pasta)
    rel['selecao_cct']=selecao
    if estado.get('exigir_download_real'):
        prova=f.confirmar_identidade_cct_baixado_re(selecao,anexos,dados_sch,req)
        rel['confirmacao_cct_re']=prova
        if prova['status']!='confirmado':
            rel.update(status='bloqueado_identidade_download',riscos=prova['motivos'])
            return rel
        estado['identidade_cct_confirmada']=True
        if (prova.get('datas') or {}).get('status_geral')=='divergente':
            rel['riscos'].append('Data de emissão do CCT mais recente difere de Dados Gerais; registrar para revisão, sem alterar datas nem declarar conformidade cadastral integral.')
    if not rel['tipo_permitido'] or not selecao.get('arquivo'):
        rel['status']='bloqueado_pre_condicoes'
        rel['riscos'].append('Tipo não permitido ou CCT mais recente não disponível com vínculo seguro; não usar certificado anterior.')
        return rel
    dados=(rel.get('confirmacao_cct_re') or {}).get('dados_pdf') or parsear_certificado_pdf(selecao['arquivo'])
    dados['caracteristicas_secundarias']=inferir_caracteristicas_secundarias(dados)
    rel['diagnostico_extracao']=dados.get('diagnostico_extracao')
    rel['certificado_cct']=dados.get('numero_certificado')
    tabelas=(estado.get('tabelas_dom') or {}).get('tabelas') or []
    if len(tabelas)!=1:
        rel.update(status='bloqueado_tabela_ambigua');rel['riscos'].append('Tabela técnica não é única.')
        return rel
    tabela=tabelas[0]
    req['tabela_tecnica_sch']={'cabecalho':tabela['cabecalho_visivel'],'linhas':tabela['linhas_visiveis'],
                             'origem':'Leitura Selenium protegida durante simulação','captura_selenium':True}
    conferencia=s.comparar_dados_sch_x_cct(req,dados)
    resumo={'pdf_cct':selecao['arquivo'],'dados_pdf':dados,'dados_certificado_sch':dados_sch,
            'conferencia_sch_cct':conferencia,'anexos_baixados':anexos}
    resumo['confirmacao_cct_re']=rel.get('confirmacao_cct_re')
    diagnostico={'status':'coletado','tabelas':[{'familia':classificar_tabela_tecnica(tabela['cabecalho_visivel'])}]}
    rel['cobertura']=avaliar_cobertura_mvp(diagnostico,conferencia,dados)
    rel['comparacao_cct_sch']=conferencia
    rel['plano']=f._preencher_abas_com_regras_em_analise_no_re(guard,WebDriverWait(guard,12),req,resumo,
                                                        simulacao=True,estado_simulacao=estado)
    if rel['plano'].get('pronto_para_escrita_controlada'):
        rel['escopo_teste_controlado']={'requerimento':requerimento,
            'acoes':rel['plano']['acoes_independentes_prontas'],
            'limite':'Somente ações independentes listadas; EIRP e dados cadastrais não são declarados conformes. Nenhuma escrita autorizada ou executada nesta simulação.'}
    if not s.analisar_sar_cct(dados).get('preencher_frase'):
        rel['verificacao_rotina_sar_real']=s.preencher_minuta_sar_se_necessario(guard,WebDriverWait(guard,12),dados,preservar_existente=True)
    rel['status']='simulado' if rel['plano'].get('status')=='simulado' else 'bloqueado_gate_real'
    rel['auditoria']=guard.eventos
    rel['riscos'].append('Salvar e confirmação pós-salvamento não foram executados nesta etapa.')
    if conferencia.get('campos_ausentes'):
        rel['riscos'].append('Há campos cadastrais não coletados; não declarar conformidade cadastral integral.')
    return rel


def salvar_relatorios(relatorio,pasta):
    from html import escape
    from gerador_relatorio import _css,_html_comparacao_tabela_tecnica
    pasta=Path(pasta);pasta.mkdir(parents=True,exist_ok=True)
    (pasta/'simulacao_opcao4.json').write_text(json.dumps(relatorio,ensure_ascii=False,indent=2),encoding='utf-8')
    comp=(relatorio.get('comparacao_cct_sch') or {}).get('comparacao_tabela_tecnica')
    corpo='<h1>Opção 4 — simulação protegida: 01553/25</h1><p>Leituras reais no SCH e plano simulado. Nenhum campo foi gravado. Aprovação automática não executada.</p>'
    corpo+='<pre>'+escape(json.dumps({k:v for k,v in relatorio.items() if k not in ('estado_leitura','comparacao_cct_sch','auditoria')},ensure_ascii=False,indent=2))+'</pre>'
    if relatorio.get('estado_leitura'):
        campos={k:v for k,v in relatorio['estado_leitura'].items() if k not in ('tabelas_dom','auditoria')}
        corpo+='<details><summary>Valores lidos nesta execução, sem edição</summary><pre>'+escape(json.dumps(campos,ensure_ascii=False,indent=2))+'</pre></details>'
    if comp:
        corpo+=_html_comparacao_tabela_tecnica({'conferencia_sch_cct':{'comparacao_tabela_tecnica':comp}})
    corpo+='<details><summary>Auditoria de leitura e ações bloqueadas</summary><pre>'+escape(json.dumps(relatorio.get('auditoria',[]),ensure_ascii=False,indent=2))+'</pre></details>'
    (pasta/'simulacao_opcao4.html').write_text('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Simulação opção 4</title>'+_css()+'</head><body>'+corpo+'</body></html>',encoding='utf-8')


def main():
    import argparse
    import traceback
    from navegador import criar_driver
    import funcoes_sch as s
    parser=argparse.ArgumentParser(description='Simulação protegida da opção 4; somente leitura.')
    parser.add_argument('--debugger-address',required=True)
    parser.add_argument('--captura-identidade',required=True)
    parser.add_argument('--requerimento',required=True)
    parser.add_argument('--saida',required=True)
    parser.add_argument('--caminho-driver',required=True)
    parser.add_argument('--inspecionar',action='store_true')
    parser.add_argument('--diretorio-ccts',default='tests/fixtures/ccts')
    args=parser.parse_args()
    if not re.fullmatch(r'(?:localhost|127\.0\.0\.1):\d{1,5}',args.debugger_address):
        raise ValueError('Conexão restrita à própria janela local.')
    origem=json.loads(Path(args.captura_identidade).read_text(encoding='utf-8'))
    from diagnostico_estrutura_sch import normalizar_requerimento
    if not origem.get('captura_autenticada_real') or normalizar_requerimento(origem['requerimento_esperado'])!=normalizar_requerimento(args.requerimento):
        raise ValueError('Fonte de identidade autenticada não corresponde ao requerimento solicitado.')
    pasta=Path(args.saida);pasta.mkdir(parents=True,exist_ok=True)
    driver,wait,_,_=criar_driver(navegador='chrome',pasta_base=pasta,caminho_driver=args.caminho_driver,debugger_address=args.debugger_address)
    # Configuração local de destino de downloads; não altera dados do SCH.
    driver.execute_cdp_cmd('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str((pasta/'browser_downloads').resolve())})
    guard=preparar_guard(driver,origem['identidade_antes']['vinculo_iframe'])
    try:
        guard.verificar_contexto()
        if args.inspecionar:
            texto=s._texto_visivel_sch(guard)
            r={'texto_com_caracteres':len(texto),'ha_bloco':s._ha_bloco_dados_certificado(guard),
               'linhas':[l for l in texto.splitlines() if any(p in l.lower() for p in ('dados','certificado','cpqd','sm-x520'))][:20],
               'auditoria':guard.eventos}
            r['navegacao']=guard.execute_script(SCRIPT_INSPECAO_NAV)
            r['erros_console']=[e['message'][:600] for e in guard.get_log('browser') if e.get('level')=='SEVERE'][-8:]
            (pasta/'inspecao_guard.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            estado=coletar_estado_simulacao(guard,pasta,args.requerimento)
            r=analisar_estado_integrado(guard,estado,args.requerimento,pasta,args.diretorio_ccts)
            salvar_relatorios(r,pasta)
        print(json.dumps({'status':r.get('status'),'modo':r.get('modo'),
              'gravacoes_executadas':r.get('gravacoes_executadas',0),'saida':str(pasta)},ensure_ascii=True),flush=True)
    except Exception as exc:
        r={'erro':type(exc).__name__+': '+str(exc),'auditoria':guard.eventos}
        (pasta/'falha_leitura.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        rel={'modo':'simulacao','status':'bloqueado_leitura','requerimento':args.requerimento,
             'gravacoes_executadas':0,'navegador_encerrado':False,'falhas':[r['erro']],
             'acoes_bloqueadas':['Todos os preenchimentos: leitura atual não concluída.','Salvar/Aprovar/Recusar: indisponíveis na barreira de simulação.'],
             'campos_nao_avaliados':['Observação atual','CTS atual','Acompanhar Processo atual','Seleção do CCT mais recente'],
             'pronto_para_escrita_controlada':False,'auditoria':guard.eventos,
             'limite':'Não confundir esta interrupção com os resultados da captura autenticada anterior.'}
        if any('401' in ev.get('acao','') for ev in guard.eventos):
            rel['status']='bloqueado_sessao_expirada_http401'
        salvar_relatorios(rel,pasta)
        traceback.print_exc()
        print(json.dumps(r,ensure_ascii=True)[-3000:],flush=True)


if __name__=='__main__':
    # O gate importa a classe pelo nome do módulo. Usar a mesma instância
    # também no CLI evita duas classes distintas (__main__ e módulo).
    import simulacao_simplificada_re
    simulacao_simplificada_re.main()
