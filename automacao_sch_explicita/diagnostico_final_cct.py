"""Diagnóstico supervisionado independente. Não chama filas nem preenchimentos."""
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import time

from diagnostico_estrutura_sch import (
    normalizar_requerimento, contexto_iframe, confirmar_por_visualizacao,
    extrair_tabela_dom_para_comparacao, _SCRIPT_TABELAS_COMPLETAS,
    classificar_tabela_tecnica,
)
from simulacao_simplificada_re import preparar_guard


def diretorio_privado(caminho):
    raiz = Path(__file__).resolve().parents[1]/'dados_locais'
    pasta = Path(caminho).resolve()
    if not pasta.is_relative_to(raiz.resolve()):
        raise ValueError('Plano e saída devem permanecer em dados_locais, fora da distribuição pública.')
    return pasta


def validar_caso(caso):
    for chave in ('requerimento', 'certificado', 'modelo'):
        if not str(caso.get(chave) or '').strip():
            raise ValueError(f'Identidade esperada ausente: {chave}')
    return dict(caso, requerimento=normalizar_requerimento(caso['requerimento']))


def salvar_relatorio(resultado, pasta):
    pasta = diretorio_privado(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta/'resultado.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    corpo = ['<meta charset="utf-8"><title>Diagnóstico de leitura CCT × SCH</title>',
             '<h1>Diagnóstico autenticado exclusivamente de leitura</h1>',
             '<p>Sem preenchimento, salvamento, minuta ou aprovação. Conformidade integral não declarada.</p>',
             '<pre>'+escape(json.dumps({k:v for k,v in resultado.items() if k not in
                 ('tabelas_completas','comparacao','prova_cct')}, ensure_ascii=False, indent=2, default=str))+'</pre>']
    for tabela in (resultado.get('tabelas_completas') or {}).get('tabelas', []):
        corpo.append('<h2>Tabela '+escape(str(tabela.get('ordem_dom')))+' — '+escape(str(tabela.get('familia')))+
                     '</h2><p>Seção: '+escape(str(tabela.get('secao')))+'; linhas: '+escape(str(tabela.get('total_linhas')))+
                     '</p><table border="1"><tr>'+''.join('<th>'+escape(str(c))+'</th>' for c in tabela['cabecalho'])+'</tr>')
        for linha in tabela['linhas']:
            corpo.append('<tr>'+''.join('<td style="white-space:pre-wrap">'+escape(str(v))+'</td>' for v in linha)+'</tr>')
        corpo.append('</table>')
    comp = resultado.get('comparacao')
    if comp:
        from gerador_relatorio import _html_comparacao_tabela_tecnica
        corpo.append(_html_comparacao_tabela_tecnica({'conferencia_sch_cct':{'comparacao_tabela_tecnica':comp}}))
        for chave, titulo in [('divergencias','Divergências efetivas'),('inconclusivos','Informações inconclusivas')]:
            corpo.append('<h2>'+titulo+'</h2><pre>'+escape(json.dumps(comp.get(chave, []), ensure_ascii=False, indent=2, default=str))+'</pre>')
    (pasta/'resultado.html').write_text(''.join(corpo), encoding='utf-8')


def executar(driver, wait, caso, pasta):
    """Uma tela selecionada manualmente; qualquer falha interrompe sem retry/escrita."""
    import funcoes_sch as sch
    from fluxo_sch import confirmar_identidade_cct_baixado_re
    from mvp_simplificada_re import expandir_faixas_explicitas_re, normalizar
    caso = validar_caso(caso)
    pasta = diretorio_privado(pasta)
    pasta.mkdir(parents=True, exist_ok=False)
    downloads = pasta/'browser_downloads'
    downloads.mkdir()
    # Configuração de destino local do navegador; não altera dados do SCH.
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior':'allow','downloadPath':str(downloads)})
    r = {'status':'interrompido','somente_leitura':True,'gravacoes_executadas':0,
         'captura_autenticada_real':False,'conformidade_integral':False,
         'requerimento':caso['requerimento'],'data_utc':datetime.now(timezone.utc).isoformat(),
         'etapas':[],'navegador_encerrado':False}
    guard = None

    @contextmanager
    def etapa(nome):
        evento={'nome':nome,'status':'iniciado'};r['etapas'].append(evento);inicio=time.monotonic()
        print(f'[DIAGNOSTICO][INICIO] {nome}',flush=True)
        try:
            yield
            evento['status']='ok'
        except Exception as exc:
            evento.update(status='falha',erro=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            evento['duracao_s']=round(time.monotonic()-inicio,3)
            print(f'[DIAGNOSTICO][{evento["status"]}] {nome} | {evento["duracao_s"]}s',flush=True)
            salvar_relatorio(r,pasta)
    try:
        with etapa('confirmar_numero_por_visualizacao_pdf_e_vinculo_iframe'):
            r['identidade_pdf']=confirmar_por_visualizacao(driver,caso['requerimento'],downloads)
            contexto=r['identidade_pdf'].get('vinculo_iframe') or contexto_iframe(driver)
            guard=preparar_guard(driver,contexto)
            guard.navegacoes=frozenset({'dados gerais','caracteristicas tecnicas','anexos',
                                      'certificado de conformidade tecnica - cct'})
        with etapa('ler_certificado_e_modelo_sem_preencher'):
            guard.verificar_contexto()
            dados=sch.extrair_dados_certificado_sch(guard,wait)
            r['dados_certificado_sch']=dados
            norm=lambda v: re.sub(r'[^a-z0-9]','',normalizar(v))
            if norm(dados.get('numero_certificado')) != norm(caso['certificado']):
                raise RuntimeError('Certificado da tela não corresponde ao plano privado.')
            if sch._comparar_modelos_sch_x_cct(caso['modelo'],dados.get('modelo_sch_dados_gerais')).get('status')!='ok':
                raise RuntimeError('Modelo da tela não corresponde ao plano privado.')
        with etapa('coletar_todas_tabelas_dom_e_confirmar_estabilidade'):
            guard.verificar_contexto()
            tabelas=extrair_tabela_dom_para_comparacao(guard,wait)
            r['tabelas_completas']=tabelas
            anterior=None
            def estavel(_):
                nonlocal anterior
                bruto=guard.execute_script(_SCRIPT_TABELAS_COMPLETAS)
                pronto=bruto.get('pronto') and anterior==bruto
                anterior=bruto
                return bruto if pronto else False
            snapshot=wait.until(estavel,message='Tabelas não estabilizaram; não presumir completude.')
            capturadas=[t for t in snapshot.get('tabelas',[]) if t.get('total_linhas') and
                        classificar_tabela_tecnica(t['cabecalho']).startswith('rf_')]
            assinatura=lambda ts:[(t['cabecalho'],t['linhas']) for t in ts]
            if assinatura(capturadas)!=assinatura(tabelas['tabelas']):
                raise RuntimeError('Tabelas mudaram entre leituras; comparação bloqueada.')
            guard.verificar_contexto()
            r['captura_autenticada_real']=True
        with etapa('baixar_cct_mais_recente_e_confirmar_hash_identidade'):
            req={'requerimento':caso['requerimento'],'certificado':dados['numero_certificado'],
                 'modelo_sch_dados_gerais':dados['modelo_sch_dados_gerais']}
            selecao,anexos=sch.baixar_cct_mais_recente_confirmado_re(guard,wait,req,pasta,downloads)
            r['selecao_cct']=selecao
            prova=confirmar_identidade_cct_baixado_re(selecao,anexos,dados,req)
            r['prova_cct']=prova
            if prova.get('status')!='confirmado':
                raise RuntimeError('Novo download/identidade do CCT não confirmados: '+str(prova.get('motivos')))
        with etapa('comparar_tabelas_e_datas_sem_acoes_de_escrita'):
            pdf=prova['dados_pdf']
            r['comparacao']=sch.comparar_conjunto_tabelas_simplificado(expandir_faixas_explicitas_re(tabelas),pdf['tabela_tecnica_cct'])
            r['datas']=sch.comparar_datas_certificado_sch_x_cct(dados,pdf,distinguir_eventos=True)
            r['sar']=sch.analisar_sar_cct(pdf)
            guard.verificar_contexto()
            r['status']='diagnostico_concluido_sem_declarar_conformidade_integral'
    except Exception as exc:
        r['falha']=f'{type(exc).__name__}: {exc}'
    finally:
        if guard is not None:
            r['auditoria']=guard.eventos
        salvar_relatorio(r,pasta)
    return r


def main():
    import argparse
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.support.ui import WebDriverWait
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plano',required=True)
    parser.add_argument('--requerimento',required=True)
    parser.add_argument('--driver',required=True)
    parser.add_argument('--debugger',default='127.0.0.1:9323')
    parser.add_argument('--navegador',choices=('chrome','edge'),default='chrome')
    args=parser.parse_args()
    if not re.fullmatch(r'127\.0\.0\.1:\d{2,5}',args.debugger):
        raise ValueError('Somente debugger local é permitido.')
    plano=json.loads(diretorio_privado(args.plano).read_text(encoding='utf-8'))
    casos=[validar_caso(c) for c in plano['casos'] if normalizar_requerimento(c['requerimento'])==normalizar_requerimento(args.requerimento)]
    if len(casos)!=1:
        raise ValueError('Requerimento ausente ou duplicado no plano privado.')
    if args.navegador=='edge':
        options=webdriver.EdgeOptions();options.debugger_address=args.debugger
        driver=webdriver.Edge(service=EdgeService(args.driver),options=options)
    else:
        options=webdriver.ChromeOptions();options.debugger_address=args.debugger
        driver=webdriver.Chrome(service=Service(args.driver),options=options)
    try:
        pasta=Path(__file__).resolve().parents[1]/'dados_locais/validacao_final'/normalizar_requerimento(args.requerimento).replace('/','_')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        resultado=executar(driver,WebDriverWait(driver,15),casos[0],pasta)
        print(json.dumps({'status':resultado['status'],'saida':str(pasta),'gravacoes_executadas':0},ensure_ascii=True))
        return 0 if resultado['status'].startswith('diagnostico_concluido') else 1
    finally:
        driver.service.stop()  # Nunca driver.quit(): manter a janela do operador.


if __name__=='__main__':
    raise SystemExit(main())
