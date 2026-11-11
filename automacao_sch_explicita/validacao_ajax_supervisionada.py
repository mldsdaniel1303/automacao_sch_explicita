"""Diagnóstico independente: preparação por padrão; apenas uma marcação autorizada.

Não dispõe de preenchimento, Salvar, Aprovar, Recusar, Exigência ou reversão.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import teste_controlado_acompanhar as base

CONFIRMACAO = 'CONFIRMO SOMENTE MARCAR E OBSERVAR AJAX 01553/25'
ACOES = ['marcar_checkbox_uma_vez', 'observar_resposta_ajax_sem_preencher_sem_salvar']
SCRIPT_RECURSOS = """return {agora:performance.now(),recursos:performance.getEntriesByType('resource').filter(e=>e.initiatorType==='xmlhttprequest').map(e=>({inicio:e.startTime,duracao:e.duration,caminho:new URL(e.name).pathname,status:e.responseStatus??null}))};"""


def validar_autorizacao(a):
    base.exigir(a.get('autorizado') is True,'Autorização institucional específica ausente.')
    base.exigir(a.get('requerimento')==base.REQUERIMENTO and a.get('acoes')==ACOES,
                'Autorização deve permitir exclusivamente marcar e observar; autorização de salvar não é aceita.')
    base.exigir(a.get('ciente_alteracao_estado_sessao') is True,'Exige ciência da possível alteração de estado da sessão.')
    for nome in ('referencia_institucional','responsavel_autorizacao','operador'):
        base.exigir(isinstance(a.get(nome),str) and bool(a[nome].strip()),f'Autorização sem {nome}.')
    try:
        validade=datetime.fromisoformat(a['valida_ate'].replace('Z','+00:00'))
        base.exigir(validade.tzinfo is not None and validade>datetime.now(timezone.utc),'Autorização expirada ou sem fuso.')
    except (KeyError,TypeError,ValueError) as exc:
        raise base.Cancelado('Validade da autorização inválida.') from exc
    return a


def executar(adapter, baseline, pasta, interagir=False, autorizacao=None, confirmar=None,
             trava=None, ambiente='preparacao_somente_leitura'):
    base.exigir(ambiente in {'preparacao_somente_leitura','interacao_ajax_real','testes_automatizados'},'Ambiente inválido.')
    base.exigir(not interagir or ambiente in {'interacao_ajax_real','testes_automatizados'},'Modo de interação inconsistente.')
    base.exigir(ambiente!='interacao_ajax_real' or not (Path(pasta)/'resultado.json').exists(),'Não sobrescrever auditoria real.')
    r={'ambiente':ambiente,'requerimento':base.REQUERIMENTO,'status':'iniciado',
       'fonte_simulacao':baseline.get('fonte_simulacao'),'antes':None,'dom_antes':None,'dom_depois':None,
       'autorizacao':None,'confirmacao_operador':None,'marcacao_tentada':False,
       'salvamento':{'tentativa_iniciada':False,'proibido_neste_modo':True},'preenchimento_permitido':False,
       'estado_servidor_indeterminado':False,'eventos':[],'falhas':[],
       'observacao_ajax_confirmada':False,
       'datas_para_revisao_humana':baseline.get('datas_para_revisao'),
       'limites':['Não preenche, salva, aprova, recusa, envia exigência ou desfaz alterações.',
                  'Marcação AJAX pode alterar estado da sessão mesmo sem Salvar.',
                  '18 correspondências EIRP permanecem inconclusivas.']}
    def registrar(etapa):
        r['eventos'].append({'etapa':etapa,'utc':datetime.now(timezone.utc).isoformat()})
        base.persistir(r,pasta)
    try:
        registrar('inicio_sem_interacao')
        if interagir:
            base.exigir(autorizacao is not None,'Falta autorização institucional.')
            r['autorizacao']=deepcopy(validar_autorizacao(autorizacao()))
        antes=adapter.coletar()
        r['antes']=antes
        base.validar_identidade_estado(antes,baseline)
        dom=adapter.capturar_dom()
        r['dom_antes']=dom
        base.exigir(base.estado_condicional(antes),'Exige checkbox desmarcado, painel inicialmente sem textarea e callback exato confirmado.')
        base.exigir(dom['checkbox']['marcado'] is False and not dom['textAreaPanel']['textareas'],
                    'DOM inicial mudou ou já contém candidatos; não interagir.')
        registrar('identidade_e_dom_inicial_confirmados')
        if not interagir:
            r['status']='preparado_sem_interacao'
            registrar('encerrado_somente_leitura')
            return r
        base.exigir(confirmar is not None,'Falta confirmação explícita do operador.')
        proposta={'requerimento':base.REQUERIMENTO,'antes':antes,'dom_inicial':dom,
                  'acao':'Marcar uma única vez e observar. NÃO preencher, salvar ou desfazer.',
                  'risco':'AJAX pode alterar estado da sessão.', 'confirmacao_exigida':CONFIRMACAO}
        resposta=confirmar(proposta)
        base.exigir(resposta==CONFIRMACAO,'Confirmação exata ausente; nenhuma marcação habilitada.')
        r['confirmacao_operador']={'frase':resposta,'operador':r['autorizacao']['operador'],
                                   'utc':datetime.now(timezone.utc).isoformat()}
        base.exigir(validar_autorizacao(autorizacao())==r['autorizacao'],'Autorização mudou após confirmação.')
        novo=adapter.coletar()
        base.validar_identidade_estado(novo,baseline)
        base.exigir(base.estado_condicional(novo) and novo==antes and adapter.capturar_dom()==dom,
                    'Estado/DOM mudou durante a confirmação; cancelar antes da marcação.')
        base.exigir(trava is not None,'Reserva de tentativa única não configurada.')
        Path(trava).parent.mkdir(parents=True,exist_ok=True)
        with Path(trava).open('x',encoding='utf-8') as f:
            json.dump({'modo':'somente_validacao_ajax','requerimento':base.REQUERIMENTO,
                       'autorizacao':r['autorizacao'],'confirmacao':r['confirmacao_operador'],
                       'relatorio':str(Path(pasta).resolve())},f,ensure_ascii=False,indent=2)
        registrar('tentativa_unica_reservada')
        adapter.habilitar_observacao(r['autorizacao'],r['confirmacao_operador'])
        r['marcacao_tentada']=True
        r['estado_servidor_indeterminado']=True
        registrar('marcacao_unica_e_observacao_sem_preencher_sem_salvar')
        renderizado=adapter.marcar_e_observar(antes)
        r['resultado_renderizacao']=renderizado
        r['dom_depois']=adapter.dom_depois
        r['resposta_ajax']=adapter.resposta_ajax
        base.exigir(adapter.resposta_ajax.get('http_200_novo') is True,'Resposta HTTP/AJAX do servidor não confirmada; revisar sem repetir.')
        base.exigir(r['dom_depois']['checkbox']['marcado'] is True,'Checkbox não permaneceu marcado.')
        candidatos=r['dom_depois']['textAreaPanel']['textareas']
        base.exigir(len(candidatos)==1,'Resposta sem candidato único no painel superior.')
        base.exigir(candidatos[0]['id']==renderizado['vinculo']['textoId'],'ID do campo renderizado divergiu.')
        base.exigir(r['dom_depois'].get('inferior')==dom.get('inferior'),'Descrição inferior mudou.')
        r['valor_real_preservado']=renderizado['texto']
        r['campos_preservados']={'descricao_inferior':True,'demais_controles_informacoes_adicionais':True,
                                 'limite':'Comparação do DOM; não é auditoria do banco de dados ou prova de persistência.'}
        r['status']='observado_com_conteudo_preservado' if renderizado['texto'] else 'observado_textarea_vazio'
        r['observacao_ajax_confirmada']=True
        # O DOM e a resposta foram observados, mas não verificam persistência
        # nem autorizam limpar a reserva ou considerar a sessão inalterada.
        r['estado_servidor_indeterminado']=True
        r['estado_sessao']='Checkbox marcado observado; nenhuma persistência em banco ou salvamento foi comprovado.'
        registrar('observacao_concluida_parar_para_revisao_do_operador')
    except (Exception,KeyboardInterrupt) as exc:
        r['status']='interrompido_sem_retry'
        r['falhas'].append(f'{type(exc).__name__}: {exc}')
        for origem,destino in (('dom_depois','dom_depois'),('resposta_ajax','resposta_ajax'),('diagnostico_renderizacao','resultado_renderizacao')):
            valor=getattr(adapter,origem,None)
            if isinstance(valor,dict):r[destino]=valor
        registrar('interrompido_sem_repetir_ou_desfazer')
    finally:
        if isinstance(getattr(adapter,'diagnostico_coleta',None),list):r['diagnostico_coleta']=adapter.diagnostico_coleta
        base.persistir(r,pasta)
    return r


class SeleniumSomenteAjax(base.SeleniumRestrito):
    """A única mutação habilitável é a marcação uma vez; texto/Salvar sempre negados."""
    def __init__(self,driver,wait,pasta):
        super().__init__(driver,wait,pasta)
        self.guard._selado=False;self.guard.registrar(SCRIPT_RECURSOS);self.guard._selado=True

    def habilitar(self,*args,**kwargs):
        raise base.Cancelado('Autorização de preenchimento/salvamento proibida no diagnóstico AJAX.')

    def habilitar_observacao(self,a,c):
        validar_autorizacao(a)
        base.exigir(c.get('frase')==CONFIRMACAO,'Confirmação específica da observação ausente.')
        reserva=base.ler_json(base.TRAVA_REAL)
        base.exigir(reserva.get('modo')=='somente_validacao_ajax' and reserva.get('autorizacao')==a
                    and reserva.get('confirmacao')==c,'Reserva não corresponde à observação autorizada.')
        base.exigir(not self._SeleniumRestrito__habilitado,'Modo já habilitado nesta instância.')
        self._contexto()
        self._SeleniumRestrito__habilitado=True

    def _consumir(self,etapa):
        base.exigir(etapa=='checkbox','Este modo proíbe preenchimento e salvamento, mesmo após autorização.')
        super()._consumir(etapa)

    def preencher_superior(self,*args,**kwargs):raise base.Cancelado('Preenchimento proibido no diagnóstico AJAX.')
    def salvar_uma_vez(self,*args,**kwargs):raise base.Cancelado('Salvar proibido no diagnóstico AJAX.')
    def marcar_checkbox(self,*args,**kwargs):raise base.Cancelado('Marcação fora da sequência exclusiva proibida.')
    def recarregar_do_servidor(self,*args,**kwargs):raise base.Cancelado('Não recarregar ou desfazer o estado observado automaticamente.')

    def capturar_dom(self):
        self._contexto()
        r=self.guard.execute_script(base.SCRIPT_EVENTOS_ACOMPANHAR)
        if r.get('inferior'):
            valor=r['inferior'].pop('valor','')
            r['inferior']['sha256_valor']=sha256(valor.encode('utf-8')).hexdigest()
        # Funções/configuração voláteis não entram na comparação do DOM entre confirmações.
        return {k:r.get(k) for k in ('checkbox','painel','textAreaPanel','inferior')}

    def marcar_e_observar(self,antes):
        inicio=self.guard.execute_script(SCRIPT_RECURSOS)
        try:
            return super().marcar_e_aguardar_superior(antes,exigir_vazio=False)
        finally:
            # Melhor esforço de leitura pós-falha, sem repetir a marcação.
            falha_em_curso=sys.exc_info()[0] is not None
            try:
                self.dom_depois=self.capturar_dom()
                fim=self.guard.execute_script(SCRIPT_RECURSOS)
                novos=[r for r in fim['recursos'] if r['inicio']>=inicio['agora'] and r['caminho']==base.CONTEXTO['caminho']]
                self.resposta_ajax={'recursos_novos':novos,'http_200_novo':any(r['status']==200 for r in novos),
                                    'metodo':'PerformanceResourceTiming passivo; sem interceptar ou repetir requisições.'}
            except Exception as exc:
                self.resposta_ajax={'http_200_novo':False,'falha_leitura':f'{type(exc).__name__}: {exc}'}
                if not falha_em_curso:raise


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    for nome in ('requerimento','simulacao','sha256-simulacao','debugger-address','caminho-driver','saida'):
        p.add_argument('--'+nome,required=True)
    p.add_argument('--interagir-ajax',action='store_true',help='Somente após autorização institucional; nunca preenche ou salva.')
    p.add_argument('--autorizacao')
    args=p.parse_args()
    pasta=Path(args.saida)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    try:
        base.exigir(base.normalizar_requerimento(args.requerimento)==base.REQUERIMENTO,'Somente 01553/25 permitido.')
        fonte=Path(args.simulacao)
        base.exigir(sha256(fonte.read_bytes()).hexdigest()==args.sha256_simulacao,'Snapshot revisado mudou.')
        baseline=base.validar_simulacao(base.ler_json(fonte),args.requerimento)
        baseline['fonte_simulacao']={'arquivo':str(fonte.resolve()),'sha256':args.sha256_simulacao}
        base.exigir(re.fullmatch(r'(localhost|127\.0\.0\.1):\d{1,5}',args.debugger_address),'Conexão deve ser local.')
        provedor=None
        if args.interagir_ajax:
            base.exigir(args.autorizacao and sys.stdin.isatty(),'Interação exige autorização específica e terminal interativo.')
            base.exigir(not base.TRAVA_REAL.exists(),'Tentativa já reservada; revisão humana obrigatória, sem repetir.')
            hash_auth=sha256(Path(args.autorizacao).read_bytes()).hexdigest()
            def provedor():
                base.exigir(sha256(Path(args.autorizacao).read_bytes()).hexdigest()==hash_auth,'Arquivo de autorização mudou.')
                return validar_autorizacao(base.ler_json(args.autorizacao))
            provedor()
        from navegador import criar_driver
        d,w,_,_=criar_driver(navegador='chrome',pasta_base=pasta,caminho_driver=args.caminho_driver,debugger_address=args.debugger_address)
        downloads=pasta/'browser_downloads';downloads.mkdir(parents=True,exist_ok=True)
        d.execute_cdp_cmd('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads.resolve())})
        def confirmar(proposta):
            print(json.dumps(proposta,ensure_ascii=False,indent=2),flush=True)
            return input(f'Digite exatamente {CONFIRMACAO!r}: ')
        r=executar(SeleniumSomenteAjax(d,w,pasta),baseline,pasta,interagir=args.interagir_ajax,
                   autorizacao=provedor,confirmar=confirmar,trava=base.TRAVA_REAL,
                   ambiente='interacao_ajax_real' if args.interagir_ajax else 'preparacao_somente_leitura')
        print(r['status']);print(pasta)
        for falha in r['falhas']:print('[AJAX][INTERROMPIDO] '+falha,flush=True)
        return 1 if r['falhas'] else 0
    except (Exception,KeyboardInterrupt) as exc:
        base.persistir({'ambiente':'interacao_ajax_real' if args.interagir_ajax else 'preparacao_somente_leitura',
                       'status':'bloqueado_antes_da_interacao','marcacao_tentada':False,
                       'salvamento':{'proibido_neste_modo':True,'tentativa_iniciada':False},
                       'falhas':[f'{type(exc).__name__}: {exc}']},pasta)
        print(f'[AJAX][BLOQUEADO] {type(exc).__name__}: {exc}',flush=True)
        print(pasta,flush=True)
        return 1


if __name__=='__main__':raise SystemExit(main())
