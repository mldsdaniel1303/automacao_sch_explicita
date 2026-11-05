"""Autoteste explícito e offline da distribuição congelada; não acessa o SCH."""
from pathlib import Path
from importlib import import_module, util, metadata
import json
import sys
import tempfile


def verificar(ccts=None):
    from versao import VERSAO_APLICATIVO
    r={'versao':VERSAO_APLICATIVO,'frozen':bool(getattr(sys,'frozen',False)),
       'modo':'verificacao_offline_sem_SCH','modulos':{},'dependencias':{},'ccts':[],'falhas':[]}
    try:
        for nome in ('extracao_cct','pdf_parser','mvp_simplificada_re','caracteristicas_secundarias',
                     'fluxo_sch','funcoes_sch','controles_acompanhar','gerador_relatorio','selenium','webdriver_manager',
                     'pdfplumber','pdfminer','pymupdf','fitz'):
            modulo=import_module(nome)
            caminho=Path(modulo.__file__).resolve()
            r['modulos'][nome]=str(caminho)
            if r['frozen'] and not caminho.is_relative_to(Path(sys._MEIPASS).resolve()):
                raise RuntimeError(f'Módulo fora do pacote: {nome}')
        for nome in ('selenium','webdriver-manager','pdfplumber','pdfminer.six','PyMuPDF'):
            r['dependencias'][nome]=metadata.version(nome)
        from utils import carregar_regras
        r['configuracao']={'regras':bool(carregar_regras()),'regras_produtos':bool(carregar_regras('config/regras_produtos.json'))}
        if not all(r['configuracao'].values()):raise RuntimeError('Configuração ausente ou vazia.')
        if r['frozen']:
            r['rotinas_restritas_excluidas']={n:util.find_spec(n) is None for n in ('teste_controlado_acompanhar','validacao_ajax_supervisionada')}
            if not all(r['rotinas_restritas_excluidas'].values()):raise RuntimeError('Entrypoint restrito indevidamente distribuído.')
        import pymupdf
        import fitz
        import pdfplumber
        from extracao_cct import extrair_complementar
        with tempfile.TemporaryDirectory(prefix='sch_offline_') as pasta:
            pdf=Path(pasta)/'nativo.pdf'
            with pymupdf.open() as doc:
                pagina=doc.new_page()
                pagina.insert_text((30,30),'Verificacao offline Automacao SCH')
                doc.save(pdf)
            with fitz.open(pdf) as doc:
                if len(doc)!=1 or 'Verificacao offline' not in doc[0].get_text():raise RuntimeError('Leitura nativa PyMuPDF/fitz falhou.')
            with pdfplumber.open(pdf) as doc:
                if 'Verificacao offline' not in doc.pages[0].extract_text():raise RuntimeError('Leitura pdfplumber falhou.')
            extrair_complementar(pdf)  # Exercita também find_tables e extensões nativas.
        r['pdf_nativo']='ok'
        if ccts:
            from pdf_parser import parsear_certificado_pdf
            for caminho in sorted(Path(ccts).glob('*.pdf')):
                dados=parsear_certificado_pdf(caminho)
                r['ccts'].append({'arquivo':caminho.name,'certificado':dados.get('numero_certificado'),
                    'modelo':dados.get('modelo'),'linhas':len((dados.get('tabela_tecnica_cct') or {}).get('linhas') or []),
                    'diagnostico':(dados.get('diagnostico_extracao') or {}).get('status')})
                sem_rf_legitimo=((dados.get('diagnostico_extracao') or {}).get('status')=='sem_tabela_rf'
                                and bool(dados.get('caracteristicas_eletricas') or dados.get('modelos_part_numbers')))
                if not dados.get('numero_certificado') or not dados.get('modelo') or not ((dados.get('tabela_tecnica_cct') or {}).get('linhas') or sem_rf_legitimo):
                    raise RuntimeError(f'CCT não extraído: {caminho.name}')
                if '12407' in (dados.get('numero_certificado') or ''):
                    fixture=Path(ccts)/'sch_cpqd_transcricao_capturas.json'
                    if fixture.is_file():
                        import funcoes_sch as sch
                        tabela=json.loads(fixture.read_text(encoding='utf-8'))
                        comp=sch.comparar_tabelas_tecnicas_sch_cct(tabela,dados['tabela_tecnica_cct'])
                        r['comparacao_cpqd_fixture']={'status':comp.get('status'),
                            'resumo':comp.get('resumo_correspondencias'),'divergencias_comprovadas':len(comp.get('divergencias') or [])}
                        resumo=comp.get('resumo_correspondencias') or {}
                        if resumo.get('pares_identificados')!=17 or resumo.get('linhas_ambiguas')!=18 or comp.get('divergencias'):
                            raise RuntimeError('Regressão da comparação CPQD: preservar 17 pares e 18 ambiguidades EIRP.')
                        sar=sch.analisar_sar_cct(dados)
                        r['sar_cpqd']={k:sar.get(k) for k in ('status','preencher_frase','sar_aplicavel')}
                        if sar.get('preencher_frase') or not sar.get('sar_aplicavel'):
                            raise RuntimeError('Regressão SAR: o CPQD possui SAR aplicável.')
            if not r['ccts']:raise RuntimeError('Pasta de CCTs sem PDFs.')
        r['status']='ok'
    except Exception as exc:
        r['status']='erro';r['falhas'].append(f'{type(exc).__name__}: {exc}')
    return r


def verificar_cli(args=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ccts',help='Pasta local opcional para verificar extração de PDFs reais.')
    parser.add_argument('--saida',help='Arquivo JSON local com o resultado.')
    opcoes=parser.parse_args(args)
    r=verificar(opcoes.ccts)
    if opcoes.saida:
        pasta=Path(opcoes.saida);pasta.parent.mkdir(parents=True,exist_ok=True)
        pasta.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=True,indent=2))
    return 0 if r['status']=='ok' else 1
