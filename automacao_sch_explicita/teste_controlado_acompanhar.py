"""Preparação por padrão. Escrita isolada exige autorização externa e confirmação TTY.

Não integra menus/filas. Nunca chama os preenchimentos gerais da opção 4.
"""
from datetime import datetime, timezone
from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback

import funcoes_sch as s
from diagnostico_estrutura_sch import normalizar_requerimento

from controles_acompanhar import SCRIPT_VINCULO, SCRIPT_PAINEL_SUPERIOR, SCRIPT_CAIXA_NORMAL

REQUERIMENTO = '01553/25'
TIPO = 'Transceptor de Radiação Restrita'
MODELO = 'SM-X520'
CERTIFICADO = 'CPQD-i 12407'
CONTEXTO = {'caminho':'/mosaico/sch/worklist/analise/requerimento',
            'idRequerimento':'81916','codCct':['88178'],'codInstancia':['411471']}
FRASE = s.TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES
ACOES = ['texto_superior_acompanhar_processo', 'marcar_acompanhar_processo', 'salvar_informacoes_adicionais_uma_vez']
CONFIRMACAO = 'CONFIRMO GRAVAR 01553/25'
CONFIRMACAO_CONDICIONAL = 'CONFIRMO RENDERIZAR E GRAVAR 01553/25'
RAIZ = Path(__file__).resolve().parents[1]
TRAVA_REAL = RAIZ/'diagnostico_sch/teste_controlado_acompanhar_01553_25/tentativa_real.json'


class Cancelado(RuntimeError):
    pass


def exigir(condicao, motivo):
    if not condicao:
        raise Cancelado(motivo)


def norm(v):
    return re.sub(r'[^a-z0-9]', '', s._normalizar_texto_comparacao(v or ''))


def ler_json(caminho):
    return json.loads(Path(caminho).read_text(encoding='utf-8'))


def validar_simulacao(r, numero):
    exigir(normalizar_requerimento(numero)==REQUERIMENTO, 'Somente 01553/25 é permitido.')
    req=r.get('requerimento') or {}
    exigir(isinstance(req,dict) and req.get('requerimento')==REQUERIMENTO,'Simulação de outro requerimento.')
    exigir(r.get('captura_autenticada_real') is True and r.get('status')=='simulado','Exige simulação autenticada concluída.')
    exigir(r.get('identidade_iframe')==CONTEXTO,'Vínculo da simulação não corresponde à identidade fixada.')
    exigir(norm(req.get('tipo_produto'))==norm(TIPO) and norm(req.get('modelo'))==norm(MODELO)
           and norm(req.get('certificado'))==norm(CERTIFICADO),'Identidade da simulação divergente.')
    prova=r.get('confirmacao_cct_re') or {}
    exigir(prova.get('status')=='confirmado' and norm(prova.get('certificado_pdf'))==norm(CERTIFICADO),'CCT da simulação não confirmado.')
    exigir(sha256(Path(prova['arquivo']).read_bytes()).hexdigest()==prova.get('sha256'),'PDF da simulação ausente ou alterado.')
    anterior=(r.get('estado_leitura') or {}).get('acompanhar') or {}
    exigir(anterior.get('localizado') is True and anterior.get('checkbox_encontrado') is True
           and anterior.get('valor')=='' and anterior.get('marcado') is False,'Baseline deve conter texto vazio e caixa desmarcada.')
    plano=r.get('plano') or {}
    exigir((plano.get('acompanhar_processo') or {}).get('sugerido')==FRASE,'Texto proposto difere da simulação.')
    return {'numero':REQUERIMENTO,'texto':'','marcado':False,
            'datas_para_revisao':prova.get('datas'),'simulacao':req,
            'datas_sch':{k:(r.get('estado_leitura') or {}).get('dados_certificado_sch',{}).get(k)
                         for k in ('data_certificado','data_validade')}}


def validar_autorizacao(a, agora=None):
    agora=agora or datetime.now(timezone.utc)
    exigir(a.get('autorizado') is True,'Falta autorização institucional registrada.')
    exigir(a.get('requerimento')==REQUERIMENTO and a.get('acoes')==ACOES and a.get('texto')==FRASE,'Autorização fora do escopo exato.')
    for campo in ('referencia_institucional','responsavel_autorizacao','operador'):
        exigir(isinstance(a.get(campo),str) and bool(a[campo].strip()),f'Autorização sem {campo}.')
    try:
        validade=datetime.fromisoformat(a['valida_ate'].replace('Z','+00:00'))
        exigir(validade.tzinfo is not None and validade>agora,'Autorização vencida ou sem fuso horário.')
    except (KeyError,TypeError,ValueError) as exc:
        raise Cancelado('Validade da autorização inválida.') from exc
    return a


def validar_identidade_estado(estado, baseline):
    i=estado.get('identidade') or {}
    exigir(i.get('requerimento')==REQUERIMENTO and i.get('contexto')==CONTEXTO,'Número ou identidade da tela divergente.')
    exigir(norm(i.get('tipo_produto'))==norm(TIPO) and norm(i.get('certificado'))==norm(CERTIFICADO)
           and norm(i.get('modelo'))==norm(MODELO),'Produto, certificado ou modelo divergente.')
    for chave,valor in (baseline.get('datas_sch') or {}).items():
        exigir(valor is not None and i.get(chave)==valor,'Data do SCH mudou em relação ao snapshot; preservar e revisar, sem confundir com data do CCT.')


def vinculo_ajax_confirmado(callback):
    """Reconhece apenas os quatro literais observados; nunca avalia JavaScript."""
    pares=re.findall(r"\b(source|event|process|update)\s*:\s*(['\"])(.*?)\2",callback or '')
    esperado="function(event){PrimeFaces.ab({source:'formAnalise:checkBoxAcompanharProcesso',event:'change',process:'formAnalise:checkBoxAcompanharProcesso',update:'formAnalise:textAreaPanel'},arguments[1]);}"
    return (re.sub(r'\s+','',callback or '').replace('"',"'")==esperado
        and len(pares)==4 and {k:v for k,_,v in pares}=={
        'source':'formAnalise:checkBoxAcompanharProcesso','event':'change',
        'process':'formAnalise:checkBoxAcompanharProcesso','update':'formAnalise:textAreaPanel'}
        and (callback or '').count('PrimeFaces.ab(')==1)


def estado_condicional(estado):
    return (estado.get('renderizacao_condicional') is True and estado.get('texto') is None
            and estado.get('marcado') is False
            and (estado.get('vinculo') or {}).get('status')=='campo_superior_nao_renderizado'
            and vinculo_ajax_confirmado((estado.get('evidencia_ajax') or {}).get('callback_change')))


def validar_estado(estado, baseline):
    validar_identidade_estado(estado,baseline)
    if estado_condicional(estado):
        exigir(baseline['marcado'] is False,'Baseline incompatível com estado condicional.')
        return  # Valor inicial desconhecido; só poderá ser validado após renderização autorizada.
    exigir(estado.get('vinculo_confirmado') is True,estado.get('motivo_preparacao_bloqueada') or 'Identidade dos campos superiores não confirmada.')
    exigir(estado.get('texto')==baseline['texto'],'Campo superior contém texto inesperado; cancelar sem sobrescrever.')
    exigir(estado.get('marcado') is baseline['marcado'],'Checkbox difere da simulação; cancelar sem alterar.')


def persistir(r, pasta):
    pasta=Path(pasta);pasta.mkdir(parents=True,exist_ok=True)
    texto=json.dumps(r,ensure_ascii=False,indent=2)
    temporario=pasta/'resultado.tmp'
    temporario.write_text(texto,encoding='utf-8')
    os.replace(temporario,pasta/'resultado.json')
    html='<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Teste restrito 01553/25</title><body>'
    html+='<h1>Teste restrito de Acompanhar Processo — 01553/25</h1><pre>'+escape(texto)+'</pre></body></html>'
    (pasta/'resultado.html').write_text(html,encoding='utf-8')


def executar(adapter, baseline, pasta, executar_real=False, obter_autorizacao=None,
             confirmar=None, trava=None, ambiente='simulacao'):
    """Orquestração sem retry. Cada passo é registrado antes de sua tentativa."""
    exigir(ambiente in {'simulacao','gravacao_real','testes_automatizados'},'Ambiente inválido.')
    exigir(not executar_real or ambiente in {'gravacao_real','testes_automatizados'},'Modo de escrita inconsistente.')
    exigir(ambiente!='gravacao_real' or not (Path(pasta)/'resultado.json').exists(),'Relatório real já existe; não sobrescrever auditoria anterior.')
    r={'ambiente':ambiente,'requerimento':REQUERIMENTO,'status':'iniciado','antes':None,'depois':None,
       'fonte_simulacao':baseline.get('fonte_simulacao'),
       'proposto':{'texto':FRASE,'marcado':True},'autorizacao':None,'confirmacao_operador':None,
       'salvamento':{'tentativa_iniciada':False,'confirmado_pelo_sistema':False},
       'eventos':[],'falhas':[],'datas_para_revisao_humana':baseline.get('datas_para_revisao'),
       'limites':['Não altera datas, Observação, CTS, minuta, tabelas ou anexos.',
                  'Não aprova, recusa, envia exigência nem percorre fila.',
                  '18 correspondências EIRP continuam inconclusivas. Sem conformidade integral.']}
    def registrar(etapa):
        r['eventos'].append({'etapa':etapa,'utc':datetime.now(timezone.utc).isoformat()})
        persistir(r,pasta)
    try:
        registrar('inicio_sem_escrita')
        if executar_real:
            exigir(obter_autorizacao is not None,'Falta autorização institucional.')
            r['autorizacao']=deepcopy(validar_autorizacao(obter_autorizacao()))
        antes=adapter.coletar()
        r['antes']=antes
        if getattr(adapter,'diagnostico_coleta',None):
            r['diagnostico_coleta']=adapter.diagnostico_coleta
        validar_estado(antes,baseline)
        condicional=estado_condicional(antes)
        r['renderizacao_condicional']=condicional
        if condicional:
            r['proposto']['sequencia']='Marcar uma vez, aguardar AJAX, ler valor real; somente se vazio preencher e salvar uma vez.'
            r['limites'].append('A resposta AJAX real ainda deve comprovar a presença do textarea; ausência ou conteúdo não vazio cancelam sem Salvar.')
        registrar('estado_anterior_confirmado')
        if not executar_real:
            r['status']='preparado_condicional_sem_gravacao' if condicional else 'preparado_sem_gravacao'
            registrar('somente_preparacao')
            return r
        exigir(confirmar is not None,'Falta confirmação explícita do operador.')
        if condicional:
            exigir(r['autorizacao'].get('permitir_renderizacao_condicional') is True,'Autorização não contempla marcação antes de conhecer o valor do campo.')
        frase_confirmacao=CONFIRMACAO_CONDICIONAL if condicional else CONFIRMACAO
        resposta=confirmar({'requerimento':REQUERIMENTO,'antes':antes,'proposto':r['proposto'],
                           'confirmacao_exigida':frase_confirmacao})
        exigir(resposta==frase_confirmacao,'Operador não confirmou a frase exata; nenhuma escrita habilitada.')
        r['confirmacao_operador']={'frase':resposta,'utc':datetime.now(timezone.utc).isoformat(),
                                   'operador':r['autorizacao']['operador'],'renderizacao_condicional':condicional}
        # Revalidar autorização e estado depois da espera pelo operador.
        atual=validar_autorizacao(obter_autorizacao())
        exigir(atual==r['autorizacao'],'Autorização mudou durante a confirmação.')
        novo=adapter.coletar()
        validar_estado(novo,baseline)
        exigir(novo==antes,'Tela ou outro campo mudou enquanto o operador confirmava.')
        exigir(trava is not None,'Trava persistente de execução única não configurada.')
        Path(trava).parent.mkdir(parents=True,exist_ok=True)
        with Path(trava).open('x',encoding='utf-8') as arquivo:
            json.dump({'requerimento':REQUERIMENTO,'autorizacao':r['autorizacao'],
                       'confirmacao':r['confirmacao_operador'],'relatorio':str(Path(pasta).resolve())},arquivo,ensure_ascii=False,indent=2)
        registrar('tentativa_unica_reservada_nao_repetir')
        adapter.habilitar(r['autorizacao'],r['confirmacao_operador'])
        # Nenhuma rotina geral de escrita é chamada a partir daqui.
        alvo=antes
        if condicional:
            r['ajax_checkbox_iniciado']=True
            registrar('marcacao_unica_para_renderizacao_autorizada')
            alvo=adapter.marcar_e_aguardar_superior(antes)
            r['apos_renderizacao']=alvo
            exigir(alvo.get('texto')=='','Conteúdo real do campo renderizado não está vazio; cancelar sem Salvar.')
            registrar('valor_real_vazio_confirmado_apos_ajax')
        registrar('preenchimento_superior_iniciado')
        adapter.preencher_superior(alvo,FRASE)
        if not condicional:
            registrar('marcacao_unica_iniciada')
            adapter.marcar_checkbox(antes)
        adapter.conferir_pendente(alvo,FRASE)
        r['salvamento']['tentativa_iniciada']=True
        registrar('salvar_uma_vez_sem_fallback')
        r['salvamento']['resposta_sistema']=adapter.salvar_uma_vez()
        exigir(bool(r['salvamento']['resposta_sistema']),'Sem confirmação positiva do sistema.')
        r['salvamento']['confirmado_pelo_sistema']=True
        registrar('releitura_servidor_sem_reenvio_de_formulario')
        adapter.recarregar_do_servidor()
        depois=adapter.coletar()
        r['depois']=depois
        if condicional:
            validar_identidade_estado(depois,baseline)
            exigir(depois.get('vinculo_confirmado') is True,'Campo superior não confirmado após recarga.')
        else:
            validar_estado(dict(depois,texto='',marcado=False),baseline)
        exigir(depois['texto']==FRASE and depois['marcado'] is True,'Valores não persistiram após recarga.')
        exigir(depois['campos_preservados']==antes['campos_preservados'],'Outro campo mudou; interromper sem nova gravação.')
        exigir(depois['vinculo']==alvo['vinculo'],'Identidade dos controles mudou após salvar.')
        r['campos_preservados']=depois['campos_preservados']
        r['status']='confirmado_apos_releitura_servidor'
        registrar('concluido_sem_repeticoes')
    except (Exception, KeyboardInterrupt) as exc:
        r['status']='interrompido_sem_retry'
        r['falhas'].append(f'{type(exc).__name__}: {exc}')
        if getattr(adapter,'diagnostico_coleta',None):
            r['diagnostico_coleta']=adapter.diagnostico_coleta
        if isinstance(getattr(adapter,'diagnostico_renderizacao',None),dict):
            r['apos_renderizacao']=adapter.diagnostico_renderizacao
        r['estado_servidor_indeterminado']=bool((r['salvamento']['tentativa_iniciada'] or r.get('ajax_checkbox_iniciado')) and not r.get('depois'))
        registrar('interrompido_nao_reexecutar_automaticamente')
    return r


SCRIPT_INVENTARIO = r"""const visivel=e=>e.checkVisibility?e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}):!!e.getClientRects().length;
const condicional=arguments[0]===true,area=document.getElementById('formAnalise:textAreaPanel'),naArea=e=>condicional&&area?.contains(e);
return {
 campos:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!naArea(e)&&visivel(e) && ! /^(javax|jakarta)\.faces\.(ViewState|ClientWindow)$/.test(e.name||'')).map(e=>({id:e.id,nome:e.name,tipo:e.type,tag:e.tagName,valor:e.value,marcado:e.type==='checkbox'||e.type==='radio'?e.checked:null,desabilitado:e.disabled})),
 tabelas:Array.from(document.querySelectorAll('table')).filter(e=>!naArea(e)&&visivel(e)).map(t=>Array.from(t.rows).filter(visivel).map(r=>Array.from(r.cells).map(c=>{const copia=c.cloneNode(true);copia.querySelectorAll('input,textarea,select').forEach(e=>e.remove());if(condicional)copia.querySelectorAll('[id="formAnalise:textAreaPanel"]').forEach(e=>e.remove());return copia.textContent.replace(/\s+/g,' ').trim();}))),
 complementares:(document.body.innerText.split('Especificações Complementares')[1]||'').split('Salvar')[0]
};"""



SCRIPT_MENSAGENS = """return Array.from(document.querySelectorAll('[role=alert],.ui-messages-info,.ui-messages-error,.ui-messages-fatal,.ui-growl-message')).filter(e=>e.getClientRects().length).map(e=>e.innerText);"""
SCRIPT_CARGA = """return {documento:document.readyState,jquery_ativo:window.jQuery?.active??null,fila_ajax_vazia:window.PrimeFaces?.ajax?.Queue?.isEmpty?.()??null,ultimo_http:performance.getEntriesByType('resource').filter(e=>e.initiatorType==='xmlhttprequest').slice(-1).map(e=>({caminho:new URL(e.name).pathname,status:e.responseStatus})),iframes:Array.from(document.querySelectorAll('iframe')).map(e=>({id:e.id,caminho:(()=>{try{return new URL(e.src,location.href).pathname}catch(_){return ''}})()}))};"""



SCRIPT_EVENTOS_ACOMPANHAR = r"""const input=document.getElementById('formAnalise:checkBoxAcompanharProcesso_input');
const widgetId='formAnalise:checkBoxAcompanharProcesso',painel=document.getElementById('formAnalise:acompanharProcessoPanel'),area=document.getElementById('formAnalise:textAreaPanel');
const fun=f=>typeof f==='function'?f.toString():String(f??'');
const eventos=e=>{const ev=window.jQuery?jQuery._data?.(e,'events'):null;return Object.entries(ev||{}).flatMap(([tipo,hs])=>Array.from(hs).map(h=>({tipo,selector:h.selector||null,namespace:h.namespace||'',codigo:fun(h.handler)})))};
const nodes=[input,document.getElementById(widgetId),document.getElementById(widgetId)?.querySelector('.ui-chkbox-box'),painel?.querySelector('label[for="formAnalise:checkBoxAcompanharProcesso"]'),painel,area].filter(Boolean);
return {checkbox:input?{id:input.id,marcado:input.checked,disabled:input.disabled,inline:Object.fromEntries(['onclick','onchange','oninput'].map(k=>[k,input.getAttribute(k)]))}:null,
 painel:painel?{id:painel.id,html:painel.outerHTML}:null,
 textAreaPanel:area?{id:area.id,html:area.outerHTML,textareas:Array.from(area.querySelectorAll('textarea')).map(e=>({id:e.id,valor:e.value,visivel:e.checkVisibility?.()??!!e.getClientRects().length}))}:null,
 inferior:document.getElementById('formAnalise:descricao')?{id:'formAnalise:descricao',dentro_superior:!!painel?.contains(document.getElementById('formAnalise:descricao')),valor:document.getElementById('formAnalise:descricao').value}:null,
 eventos:nodes.map(e=>({id:e.id,eventos:eventos(e)})),
 widgets:Object.entries(window.PrimeFaces?.widgets||{}).filter(([k,v])=>v.cfg?.id===widgetId||v.id===widgetId||k.includes('checkBoxAcompanharProcesso')).map(([nome,v])=>({nome,id:v.id||v.cfg?.id,cfg_chaves:Object.keys(v.cfg||{}),behaviors:Object.fromEntries(Object.entries(v.cfg?.behaviors||{}).map(([k,f])=>[k,fun(f)])),metodos:Object.fromEntries(['bindEvents','check','uncheck','toggle'].filter(k=>typeof v[k]==='function').map(k=>[k,fun(v[k])]))})),
 scripts:Array.from(document.scripts).map(e=>e.textContent).filter(t=>t.includes(widgetId)||t.includes('formAnalise:textAreaPanel')).map(t=>t.slice(0,18000)),
 ajax_pendente:window.jQuery?.active??null};"""


class SeleniumRestrito:
    """Expõe somente três mutações fixas, nunca escrita genérica ou fallback."""
    def __init__(self, driver, wait, pasta):
        from simulacao_simplificada_re import preparar_guard
        self.__driver=driver
        self.wait=wait
        self.pasta=Path(pasta)
        self.guard=preparar_guard(driver,CONTEXTO)
        self.guard.navegacoes={'dados gerais','caracteristicas tecnicas','anexos','informacoes adicionais'}
        self.guard._selado=False
        for script in (SCRIPT_INVENTARIO,SCRIPT_VINCULO,SCRIPT_MENSAGENS,SCRIPT_CARGA,SCRIPT_PAINEL_SUPERIOR,SCRIPT_EVENTOS_ACOMPANHAR,SCRIPT_CAIXA_NORMAL):
            self.guard.registrar(script)
        self.guard._selado=True
        self.__identidade_pdf=None
        self.__consumidos=set()
        self.__alvos=None
        self.__habilitado=False
        self.diagnostico_coleta=[]
        self.__condicional=False

    def _ler_callback_change(self):
        """Inspeção CDP restrita a metadados de uma função; não a executa."""
        from uuid import uuid4
        grupo='sch_evento_leitura_'+uuid4().hex
        expressao="""(()=>{const id='formAnalise:checkBoxAcompanharProcesso_input';let doc=document;
        const correto=url=>{try{const u=new URL(url);return u.origin==='https://sistemasnet.anatel.gov.br'&&u.pathname==='/mosaico/sch/worklist/analise/requerimento'&&u.searchParams.get('idRequerimento')==='81916'&&u.searchParams.get('codCct')==='88178'&&u.searchParams.get('codInstancia')==='411471'}catch(_){return false}};
        const f=Array.from(document.querySelectorAll('iframe')).find(f=>correto(f.src));
        if(f){doc=f.contentDocument}else if(!correto(location.href)&&location.protocol!=='file:'){throw Error('Contexto da função não confirmado')}
        const ev=doc?.defaultView.jQuery._data(doc.getElementById(id),'events');
        if(ev?.change?.length!==1)throw Error('Handler change ausente ou ambíguo');return ev.change[0].handler;})()"""
        def props(obj):
            return self.__driver.execute_cdp_cmd('Runtime.getProperties',{'objectId':obj,'ownProperties':True})
        self._contexto()
        try:
            fn=self.__driver.execute_cdp_cmd('Runtime.evaluate',{'expression':expressao,'objectGroup':grupo,'returnByValue':False,'silent':True})
            exigir(not fn.get('exceptionDetails') and fn.get('result',{}).get('objectId'),'Handler change não confirmado.')
            internos=props(fn['result']['objectId']).get('internalProperties',[])
            scopes=next(p['value']['objectId'] for p in internos if p['name']=='[[Scopes]]')
            callbacks=[]
            for p in props(scopes).get('result',[]):
                v=p.get('value') or {}
                if v.get('description')!='Closure':continue
                for campo in props(v['objectId']).get('result',[]):
                    valor=campo.get('value') or {}
                    if campo['name']=='c' and valor.get('type')=='function':callbacks.append(valor.get('description'))
            exigir(len(callbacks)==1,'Callback change não é único ou acessível; manter bloqueio.')
            return {'callback_change':callbacks[0],'sha256_callback':sha256(callbacks[0].encode('utf-8')).hexdigest(),
                    'vinculo_ajax_confirmado':vinculo_ajax_confirmado(callbacks[0]),'handler_executado':False}
        finally:
            self.__driver.execute_cdp_cmd('Runtime.releaseObjectGroup',{'objectGroup':grupo})

    def investigar_renderizacao(self):
        """Lê funções como texto; não chama handlers, check/uncheck ou AJAX."""
        with self._etapa('renderizacao.confirmar_contexto'):
            self._contexto()
            self._aguardar_ajax()
        with self._etapa('renderizacao.ler_dom_eventos_configuracao_sem_disparar'):
            antes=self.guard.execute_script(SCRIPT_EVENTOS_ACOMPANHAR)
            exigir(antes.get('checkbox') and antes['checkbox']['marcado'] is False,'Inspeção requer checkbox desmarcado; não será alterado.')
            exigir(antes.get('painel') and antes.get('textAreaPanel'),'Painéis superiores não localizados.')
        with self._etapa('renderizacao.ler_callback_change_sem_executar'):
            antes['evidencia_ajax']=self._ler_callback_change()
        with self._etapa('renderizacao.confirmar_estado_preservado'):
            self._contexto()
            depois=self.guard.execute_script(SCRIPT_EVENTOS_ACOMPANHAR)
            for k in ('checkbox','painel','textAreaPanel','inferior'):
                exigir(antes.get(k)==depois.get(k),'Estado do formulário mudou durante inspeção; evidência descartada.')
        if antes.get('inferior'):
            valor=antes['inferior'].pop('valor','')
            antes['inferior']['sha256_valor_preservado']=sha256(valor.encode('utf-8')).hexdigest()
        antes.update(requerimento=REQUERIMENTO,contexto=CONTEXTO,
                     checkbox_marcado_pela_automacao=False,handlers_executados=False,
                     estado_preservado=True,origem='Inspeção de DOM/eventos; não é resposta AJAX pós-marcação.')
        return antes

    @contextmanager
    def _etapa(self, nome):
        inicio=time.perf_counter()
        evento={'etapa':nome,'status':'iniciada','inicio_utc':datetime.now(timezone.utc).isoformat()}
        self.diagnostico_coleta.append(evento)
        def gravar():
            self.pasta.mkdir(parents=True,exist_ok=True)
            (self.pasta/'coleta_diagnostico.json').write_text(json.dumps(self.diagnostico_coleta,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'[COLETA][INICIO] {nome}',flush=True)
        gravar()
        try:
            yield
        except (Exception,KeyboardInterrupt) as exc:
            evento.update(status='falha',duracao_s=round(time.perf_counter()-inicio,3),
                          erro=f'{type(exc).__name__}: {str(exc).strip() or "Espera encerrada sem mensagem do Selenium."}',
                          traceback=traceback.format_exc())
            try:
                evento['estado_carregamento']=self.guard.execute_script(SCRIPT_CARGA)
            except Exception as diagnostico_exc:
                evento['falha_diagnostico']=type(diagnostico_exc).__name__
            gravar()
            print(f'[COLETA][FALHA] {nome} | {evento["duracao_s"]:.3f}s | {evento["erro"]}',flush=True)
            if isinstance(exc,KeyboardInterrupt):raise
            raise Cancelado(f'Etapa {nome}: {evento["erro"]}') from exc
        else:
            evento.update(status='concluida',duracao_s=round(time.perf_counter()-inicio,3))
            gravar()
            print(f'[COLETA][OK] {nome} | {evento["duracao_s"]:.3f}s',flush=True)

    def _aguardar_ajax(self):
        from utils import _documento_pronto, _ajax_primefaces_pronto
        self.wait.until(lambda _: _documento_pronto(self.guard) and _ajax_primefaces_pronto(self.guard),
                        message='Documento ou fila AJAX do SCH não ficaram prontos no limite já configurado.')

    def habilitar(self, autorizacao, confirmacao):
        exigir(not self.__habilitado,'Escrita já habilitada nesta instância.')
        validar_autorizacao(autorizacao)
        condicional=confirmacao.get('renderizacao_condicional') is True
        exigir(confirmacao.get('frase')==(CONFIRMACAO_CONDICIONAL if condicional else CONFIRMACAO),'Confirmação exata ausente.')
        if condicional:exigir(autorizacao.get('permitir_renderizacao_condicional') is True,'Autorização não contempla estado condicional.')
        reserva=ler_json(TRAVA_REAL)
        exigir(reserva.get('autorizacao')==autorizacao and reserva.get('confirmacao')==confirmacao,'Reserva persistente não corresponde à autorização e confirmação.')
        self._contexto()
        self.__habilitado=True

    def _contexto(self):
        self.guard.verificar_contexto()

    def _inventario(self, ignorar=()):
        r=self.guard.execute_script(SCRIPT_INVENTARIO,getattr(self,'_SeleniumRestrito__condicional',False))
        r['campos']=[c for c in r['campos'] if c['id'] not in ignorar]
        return r

    def _controles(self, permitir_painel_sem_textarea=False):
        from selenium.webdriver.common.by import By
        with self._etapa('acompanhar.localizar_checkbox_superior'):
            cb=s._localizar_checkbox_acompanhar_processo(self.guard,self.wait,timeout=2)
            exigir(cb is not None,'Checkbox superior não encontrado.')
        with self._etapa('acompanhar.inspecionar_painel_superior_confirmado'):
            painel=self.guard.execute_script(SCRIPT_PAINEL_SUPERIOR,cb)
            exigir(painel['painel']=='formAnalise:acompanharProcessoPanel' and painel['checkbox_no_painel'],
                   f'Checkbox não pertence ao painel superior observado no SCH: {painel}.')
            exigir(not painel.get('outros_controles'),'Painel superior contém controles adicionais; manter bloqueio.')
        if not painel['textareas']:
            motivo='Campo superior não renderizado no painel Acompanhar Processo. Não usar Descrição inferior, presumir texto vazio ou marcar checkbox para inspecionar em leitura.'
            if not permitir_painel_sem_textarea:raise Cancelado(motivo)
            print('[COLETA][OBSERVACAO] '+motivo,flush=True)
            return None,cb,None,{'valido':False,'textoId':None,'checkboxId':painel['checkboxId'],
                                 'salvarId':None,'status':'campo_superior_nao_renderizado','diagnostico':painel}
        with self._etapa('acompanhar.localizar_textarea_superior'):
            exigir(len(painel['textareas'])==1,'Mais de um textarea no painel superior; identidade ambígua.')
            ta=s._localizar_textarea_acompanhar_processo(self.guard,self.wait,timeout=2)
            exigir(ta.get_attribute('id')==painel['textareas'][0], 'Localizador retornou campo de outra seção; não usar Descrição inferior.')
        candidatos={}
        with self._etapa('acompanhar.identificar_salvar_sem_clicar'):
            for xp in s.XPATHS_SALVAR_INFORMACOES_ADICIONAIS:
                for e in self.guard.find_elements(By.XPATH,xp):
                    if e.is_displayed() and e.is_enabled():candidatos[e.id]=e
            exigir(len(candidatos)==1,'Salvar não é único e visível na seção atual.')
        b=next(iter(candidatos.values()))
        with self._etapa('acompanhar.confirmar_vinculo_dos_controles'):
            vinculo=self.guard.execute_script(SCRIPT_VINCULO,ta,cb,b)
            exigir(vinculo['valido'] is True,f'Textarea, checkbox e Salvar não confirmam a seção superior: {vinculo.get("diagnostico")}.')
        return ta,cb,b,vinculo

    def coletar(self):
        from diagnostico_estrutura_sch import confirmar_por_visualizacao
        with self._etapa('contexto.confirmar_iframe_requerimento'):
            self._contexto()
        if self.__identidade_pdf is None:
            # Leitura do número em PDF recém-gerado, nunca número da fila ao fundo.
            self.__identidade_pdf=confirmar_por_visualizacao(self.__driver,REQUERIMENTO,self.pasta/'browser_downloads',etapa=self._etapa)
            with self._etapa('pdf.validar_vinculo_com_01553_25'):
                exigir(self.__identidade_pdf['vinculo_iframe']==CONTEXTO,'Número do PDF não vinculado à tela esperada.')
        with self._etapa('dados_gerais.navegar_e_ler_certificado'):
            dados=s.extrair_dados_certificado_sch(self.guard,self.wait)
        with self._etapa('dados_gerais.aguardar_documento_ajax'):
            self._aguardar_ajax()
        with self._etapa('dados_gerais.ler_tipo_produto'):
            texto=s._texto_visivel_sch(self.guard)
            tipo=s._extrair_valor_sch_por_rotulo(texto,[r'Tipo\s+do\s+Produto',r'Tipo\s+de\s+Produto'])
        identidade={'requerimento':self.__identidade_pdf['requerimento'],'contexto':CONTEXTO,
                    'tipo_produto':tipo,'certificado':dados.get('numero_certificado'),
                    'modelo':dados.get('modelo_sch_dados_gerais'),
                    'data_certificado':dados.get('data_certificado'),'data_validade':dados.get('data_validade')}
        with self._etapa('dados_gerais.inventario_preservacao'):
            preservados={'dados_gerais':self._inventario()}
        for nome,abrir in (('caracteristicas_tecnicas',s.clicar_aba_caracteristicas_tecnicas),
                           ('anexos',s.clicar_aba_anexos),('informacoes_adicionais',s.clicar_aba_informacoes_adicionais)):
            with self._etapa(nome+'.navegar'):
                abrir(self.guard,self.wait)
            with self._etapa(nome+'.aguardar_documento_ajax'):
                self._aguardar_ajax()
            if nome!='informacoes_adicionais':
                with self._etapa(nome+'.inventario_preservacao'):
                    preservados[nome]=self._inventario()
        ta,cb,b,vinculo=self._controles(permitir_painel_sem_textarea=True)
        evidencia_ajax=None
        if ta is None and not cb.is_selected():
            with self._etapa('acompanhar.confirmar_relacao_ajax_sem_disparar'):
                evidencia_ajax=self._ler_callback_change()
                self.__condicional=evidencia_ajax['vinculo_ajax_confirmado'] is True
        ids=tuple(i for i in (vinculo['textoId'],vinculo['checkboxId']) if i)
        with self._etapa('informacoes_adicionais.inventario_preservacao'):
            preservados['informacoes_adicionais']=self._inventario(ids)
        with self._etapa('acompanhar.ler_valores_atuais_sem_alterar'):
            texto_atual=ta.get_attribute('value') if ta is not None else None
            marcado_atual=bool(cb.is_selected())
        self.__alvos=(ta,cb,b,vinculo) if ta is not None else None
        return {'identidade':identidade,'evidencia_numero':self.__identidade_pdf,
                'coleta_leitura_concluida':True,
                'renderizacao_condicional':bool(ta is None and getattr(self,'_SeleniumRestrito__condicional',False)),
                'evidencia_ajax':evidencia_ajax,
                'vinculo_confirmado':vinculo['valido'],'vinculo':vinculo,
                'motivo_preparacao_bloqueada':None if ta is not None else 'Campo superior não renderizado: valor desconhecido. É proibido assumir vazio ou usar a Descrição inferior.',
                'texto':texto_atual,'marcado':marcado_atual,
                'campos_preservados':preservados}

    def _alvos(self, antes):
        self._contexto()
        ta,cb,b,vinculo=self._controles()
        exigir(vinculo==antes['vinculo'],'Controles mudaram de identidade.')
        return [self.guard.desembrulhar(e) for e in (ta,cb,b)]

    def _consumir(self, etapa):
        exigir(self.__habilitado,'Escrita não habilitada por autorização e confirmação.')
        exigir(etapa not in self.__consumidos,'Operação já tentada; repetição proibida.')
        self.__consumidos.add(etapa)

    def preencher_superior(self, antes, texto):
        exigir(texto==FRASE,'Somente a frase fixada pode ser escrita.')
        ta,cb,_=self._alvos(antes)
        condicional=antes.get('renderizado_apos_marcacao') is True
        if condicional:
            exigir('checkbox' in self.__consumidos and getattr(self,'_SeleniumRestrito__alvo_condicional',None)==antes,'Campo não foi validado após marcação autorizada.')
        exigir(ta.get_attribute('value')=='' and cb.is_selected() is condicional,'Estado mudou antes do preenchimento superior.')
        exigir(self._inventario((antes['vinculo']['textoId'],antes['vinculo']['checkboxId']))==antes['campos_preservados']['informacoes_adicionais'],'Outro campo mudou antes da escrita.')
        self._consumir('texto')
        ta.send_keys(FRASE)

    def marcar_e_aguardar_superior(self, antes, exigir_vazio=True):
        """Somente após autorização: clique normal único e comprovação da resposta."""
        from utils import _documento_pronto, _ajax_primefaces_pronto
        exigir(estado_condicional(antes),'Estado condicional não confirmado por evidência AJAX.')
        self._contexto()
        _,cb,_,vinculo=self._controles(permitir_painel_sem_textarea=True)
        exigir(vinculo==antes['vinculo'] and not cb.is_selected(),'Painel/checkbox mudou antes da marcação.')
        exigir(self._ler_callback_change()==antes['evidencia_ajax'],'Callback AJAX mudou; cancelar sem marcar.')
        exigir(self._inventario((vinculo['checkboxId'],))==antes['campos_preservados']['informacoes_adicionais'],'Outro campo mudou antes da marcação.')
        normal=self.guard.execute_script(SCRIPT_CAIXA_NORMAL,cb)
        exigir(normal['valido'] and normal['caixa'].is_displayed(),'Controle visual normal do checkbox não confirmado.')
        self._consumir('checkbox')
        self.guard.desembrulhar(normal['caixa']).click()  # Exatamente um clique normal PrimeFaces, sem fallback.
        with self._etapa('renderizacao.aguardar_ajax_e_unico_textarea_superior'):
            def renderizou(_):
                self._contexto()
                if not (_documento_pronto(self.guard) and _ajax_primefaces_pronto(self.guard)):return False
                p=self.guard.execute_script(SCRIPT_PAINEL_SUPERIOR,cb)
                exigir(not p.get('outros_controles'),'Resposta AJAX trouxe controles adicionais no painel; cancelar sem Salvar.')
                exigir(len(p['textareas'])<=1,'Resposta AJAX trouxe múltiplos textareas; cancelar sem Salvar.')
                return p if len(p['textareas'])==1 and cb.is_selected() else False
            self.wait.until(renderizou,message='Checkbox marcado, mas não surgiu um único textarea superior após AJAX; nenhuma tentativa de Salvar permitida.')
        ta,novo_cb,b,novo_vinculo=self._controles()
        exigir(novo_vinculo['checkboxId']==antes['vinculo']['checkboxId'] and novo_cb.is_selected(),'Checkbox mudou de identidade após AJAX.')
        real=ta.get_attribute('value')
        self.diagnostico_renderizacao={'texto_real':real,'marcado':True,'vinculo':novo_vinculo,
                                      'resposta_real_ou_fixture':'conforme ambiente registrado no relatório'}
        exigir(self._inventario((novo_vinculo['textoId'],novo_vinculo['checkboxId']))==antes['campos_preservados']['informacoes_adicionais'],'Resposta AJAX alterou campo não autorizado.')
        alvo=deepcopy(antes)
        alvo.update(texto=real,marcado=True,vinculo=novo_vinculo,vinculo_confirmado=True,
                    renderizacao_condicional=False,renderizado_apos_marcacao=True,motivo_preparacao_bloqueada=None)
        self.__alvo_condicional=deepcopy(alvo)
        if exigir_vazio:
            exigir(real=='','Valor real do textarea renderizado não está vazio; cancelar sem preencher ou Salvar.')
        return alvo

    def marcar_checkbox(self, antes):
        ta,cb,_=self._alvos(antes)
        exigir(ta.get_attribute('value')==FRASE and not cb.is_selected(),'Estado inesperado antes da marcação.')
        exigir(self._inventario((antes['vinculo']['textoId'],antes['vinculo']['checkboxId']))==antes['campos_preservados']['informacoes_adicionais'],'Outro campo mudou antes da marcação.')
        self._consumir('checkbox')
        self.__driver.execute_script('arguments[0].click();',cb)
        from utils import _ajax_primefaces_pronto
        self.wait.until(lambda _: _ajax_primefaces_pronto(self.guard))

    def conferir_pendente(self, antes, texto):
        ta,cb,b=self._alvos(antes)
        exigir(ta.get_attribute('value')==texto and cb.is_selected(),'Valores pendentes não correspondem ao plano.')
        ids=(antes['vinculo']['textoId'],antes['vinculo']['checkboxId'])
        exigir(self._inventario(ids)==antes['campos_preservados']['informacoes_adicionais'],'Outro campo foi alterado antes de Salvar.')
        self.__alvos=(ta,cb,b,antes['vinculo'])
        self.__estado_base=antes
        self.__mensagens_antes=self.guard.execute_script(SCRIPT_MENSAGENS)

    def salvar_uma_vez(self):
        self._contexto()
        self._consumir('salvar')
        self.conferir_pendente(self.__estado_base,FRASE)
        _,_,botao,_=self.__alvos
        # Um único clique, sem _clicar_com_fallback e sem aceitar alertas genéricos.
        botao.click()
        from utils import _ajax_primefaces_pronto
        def confirmado(_):
            self._contexto()
            if not _ajax_primefaces_pronto(self.guard):return False
            mensagens=self.guard.execute_script(SCRIPT_MENSAGENS)
            novas=[m for m in mensagens if m not in self.__mensagens_antes]
            exigir(not any(re.search(r'erro|falha|inv[aá]lid',m,re.I) for m in novas),'Sistema informou erro ao salvar.')
            return next((m for m in novas if re.search(r'sucesso|salv[oa]|atualizad|gravad',m,re.I)),False)
        return self.wait.until(confirmado)

    def recarregar_do_servidor(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        self._contexto()
        url=self.__driver.execute_script('return location.href;')
        antigo=self.__driver.find_element(By.TAG_NAME,'html')
        # Novo GET do iframe confirmado, sem reenviar o formulário salvo.
        self.__driver.execute_script('window.location.replace(arguments[0]);',url)
        self.wait.until(EC.staleness_of(antigo))
        self.__driver.switch_to.default_content()
        from diagnostico_estrutura_sch import contexto_iframe
        exigir(contexto_iframe(self.__driver)==CONTEXTO,'Tela recarregada divergiu do requerimento.')


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requerimento',required=True)
    parser.add_argument('--simulacao',required=True)
    parser.add_argument('--sha256-simulacao',required=True)
    parser.add_argument('--debugger-address',required=True)
    parser.add_argument('--caminho-driver',required=True)
    parser.add_argument('--saida',required=True)
    parser.add_argument('--executar-real',action='store_true',help='Exige autorização institucional válida e confirmação interativa; não usar nesta etapa de preparação.')
    parser.add_argument('--autorizacao')
    args=parser.parse_args()
    from uuid import uuid4
    pasta=Path(args.saida)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    try:
        exigir(normalizar_requerimento(args.requerimento)==REQUERIMENTO,'Outro requerimento proibido.')
        arquivo=Path(args.simulacao)
        exigir(sha256(arquivo.read_bytes()).hexdigest()==args.sha256_simulacao,'Hash da simulação não corresponde ao revisado.')
        baseline=validar_simulacao(ler_json(arquivo),args.requerimento)
        baseline['fonte_simulacao']={'arquivo':str(arquivo.resolve()),'sha256':args.sha256_simulacao}
        exigir(re.fullmatch(r'(127\.0\.0\.1|localhost):\d{1,5}',args.debugger_address),'Conexão deve ser local.')
        provedor=None
        if args.executar_real:
            exigir(args.autorizacao and sys.stdin.isatty(),'Gravação exige arquivo de autorização e terminal interativo.')
            exigir(not TRAVA_REAL.exists(),'Já houve tentativa real reservada. Revisão humana obrigatória; sem retry.')
            original=sha256(Path(args.autorizacao).read_bytes()).hexdigest()
            def provedor():
                exigir(sha256(Path(args.autorizacao).read_bytes()).hexdigest()==original,'Arquivo de autorização foi alterado.')
                return validar_autorizacao(ler_json(args.autorizacao))
            provedor()
        from navegador import criar_driver
        driver,wait,_,_=criar_driver(navegador='chrome',pasta_base=pasta,caminho_driver=args.caminho_driver,debugger_address=args.debugger_address)
        downloads=pasta/'browser_downloads';downloads.mkdir(parents=True,exist_ok=True)
        driver.execute_cdp_cmd('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads.resolve())})
        def confirmar(plano):
            print(json.dumps(plano,ensure_ascii=False,indent=2),flush=True)
            print('Autorização institucional declarada:',provedor(),flush=True)
            return input(f'Digite exatamente {plano["confirmacao_exigida"]!r} para habilitar a tentativa única: ')
        r=executar(SeleniumRestrito(driver,wait,pasta),baseline,pasta,
                   executar_real=args.executar_real,obter_autorizacao=provedor,confirmar=confirmar,
                   trava=TRAVA_REAL,ambiente='gravacao_real' if args.executar_real else 'simulacao')
        r['fonte_simulacao']={'arquivo':str(arquivo.resolve()),'sha256':args.sha256_simulacao}
        persistir(r,pasta)
        print(r['status'])
        for falha in r.get('falhas',[]):
            print('[PREPARACAO][BLOQUEADO] '+falha,flush=True)
        return 0 if r['status'] in {'preparado_sem_gravacao','preparado_condicional_sem_gravacao','confirmado_apos_releitura_servidor'} else 1
    except (Exception, KeyboardInterrupt) as exc:
        persistir({'ambiente':'gravacao_real' if args.executar_real else 'simulacao','status':'bloqueado_antes_da_execucao',
                   'requerimento':args.requerimento,'falhas':[f'{type(exc).__name__}: {exc}'],
                   'salvamento':{'tentativa_iniciada':False}},pasta)
        print(f'Bloqueado: {exc}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
