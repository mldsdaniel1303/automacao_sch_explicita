import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'automacao_sch_explicita'))
import fluxo_sch as f
import funcoes_sch as s
import mvp_simplificada_re as m
import gerador_relatorio as g

class SimplificadaTests(unittest.TestCase):
    def setUp(self):
        self.logs = contextlib.redirect_stdout(io.StringIO())
        self.logs.__enter__()
        self.addCleanup(self.logs.__exit__, None, None, None)
        cts=patch.object(s,'diagnosticar_campo_cts_re',return_value={'status':'localizado_confirmado','motivo':'Campo confirmado na fixture unitária'})
        cts.start();self.addCleanup(cts.stop)

    def test_sintaxe(self):
        for p in Path('automacao_sch_explicita').glob('*.py'):
            with self.subTest(arquivo=p.name):
                compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec')

    def test_filtros_independentes(self):
        for tipo, permitido in [(' Estação  Terminal de Acesso ', True),
                ('Transceptor de Radiação Restrita', True), ('Telefone Móvel Celular', False), ('', False)]:
            with self.subTest(tipo=tipo), patch.object(f, '_tipo_produto_no_escopo_automatico_retorno') as antigo:
                req = {'tipo_produto': tipo, 'texto_linha': 'Estação Terminal de Acesso'}
                self.assertEqual(f._tipo_produto_permitido_simplificada(req), permitido)
                self.assertEqual(f._definir_escopos_re(req, modo='analise_simplificada')['comparacao_cct_sch'], permitido)
                antigo.assert_not_called()
        with patch.object(f, '_tipo_produto_permitido_simplificada') as novo:
            f._definir_escopos_re({'tipo_produto': 'Telefone Móvel Celular'}, modo='comparar_versoes')
            novo.assert_not_called()

    def test_sem_modulo_tradicional(self):
        escopos = f._escopos_para_modo_re({'analise_tradicional_re': True, 'comparacao_cct_sch': True}, 'analise_simplificada')
        self.assertFalse(escopos['analise_tradicional_re'])
        src = Path('automacao_sch_explicita/fluxo_sch.py').read_text(encoding='utf-8')
        self.assertIn('executar_envio_retorno_para_estudo = False', src)

    def test_cobertura_parcial(self):
        for status in ['ok', 'parcial', 'divergente']:
            with self.subTest(status=status):
                r = m.avaliar_cobertura_mvp({}, {'status_geral': status}, {})
                self.assertTrue(r['apto_preenchimento'])
                self.assertFalse(r['comparacao_tecnica_integral'])

    def test_observacao_e_cts(self):
        rr, eta = 'Transceptor de Radiação Restrita', 'Estação Terminal de Acesso'
        for tipo, regra, anterior, cts, escreve in [
                (rr, '', '', {'status':'nao_aplicavel'}, True),
                (eta, '', '', {'status':'revisar'}, False),
                (eta, 'Produto não acabado', '', {'status':'revisar'}, True),
                (rr, '', 'Existente', {'status':'preservado'}, False)]:
            with self.subTest(tipo=tipo, regra=regra, anterior=anterior), contextlib.ExitStack() as st:
                esperado = regra or s.OBS_RADIACAO_RESTRITA
                st.enter_context(patch.object(m, 'ler_observacao_atual_re', side_effect=[{'localizado':True,'texto':anterior}, {'localizado':True,'texto':esperado}]))
                obs = st.enter_context(patch.object(s, 'preencher_observacao_caracteristicas', return_value=True))
                st.enter_context(patch.object(s, 'preencher_titulo_caracteristicas_secundarias_se_existir', return_value=cts))
                st.enter_context(patch.object(s, 'salvar_caracteristicas_tecnicas', return_value={'salvo':True,'confirmado_apos_salvar':True}))
                r = m.preencher_caracteristicas_conservadoras_re(None,None,{'tipo_produto':tipo},[],{'tipo_produto':tipo,'observacao_texto':regra})
                self.assertEqual(obs.called, escreve)
                self.assertEqual(r['sem_alteracao'], not escreve)

    def test_cts_resposta_vazia_bloqueia(self):
        with patch.object(m,'ler_observacao_atual_re',return_value={'localizado':True,'texto':'Existente'}), patch.object(s,'preencher_titulo_caracteristicas_secundarias_se_existir',return_value={}):
            with self.assertRaises(RuntimeError): m.preencher_caracteristicas_conservadoras_re(None,None,{},[],{})

    def test_integracao_e_bloqueios(self):
        for caso in ['ok','certificado','certificado_sem_numero','modelo','iframe','ct','sar_vazio','sar_salvamento','sar_retorno','acompanhamento']:
            with self.subTest(caso=caso), contextlib.ExitStack() as st:
                resumo={'pdf_cct':'cct.pdf','dados_pdf':{'numero_certificado':'123'},'dados_certificado_sch':{'numero_certificado':'123'},'conferencia_sch_cct':{'status_geral':'parcial'}}
                # Prova sintética da nova pré-condição; os bloqueios anteriores
                # continuam exercitados individualmente abaixo, sem removê-los.
                import tempfile,hashlib
                pasta=st.enter_context(tempfile.TemporaryDirectory())
                arquivo=Path(pasta)/'cct.pdf';arquivo.write_bytes(b'fixture-unitaria')
                resumo['pdf_cct']=str(arquivo)
                resumo['confirmacao_cct_re']={'status':'confirmado','arquivo':str(arquivo),'sha256':hashlib.sha256(arquivo.read_bytes()).hexdigest()}
                if caso=='certificado': resumo['dados_pdf']['numero_certificado']='456'
                if caso=='certificado_sem_numero':
                    resumo['dados_pdf']['numero_certificado']='---'
                    resumo['dados_certificado_sch']['numero_certificado']='???'
                req={'requerimento':'05100/24','modelo_sch_dados_gerais':'Modelo'}
                st.enter_context(patch.object(f,'extrair_dados_certificado_sch',return_value={'numero_certificado':'123','modelo_sch_dados_gerais':'Outro' if caso=='modelo' else 'Modelo'},side_effect=RuntimeError('iframe') if caso=='iframe' else None))
                st.enter_context(patch.object(f,'preencher_caracteristicas_conservadoras_re',return_value={} if caso=='ct' else {'sem_alteracao':True}))
                sar={} if caso=='sar_vazio' else {'status':'preenchido','preencher_frase':True,'salvo':caso!='sar_salvamento','confirmado_apos_salvar':True,'retornou_para_requerimento':caso!='sar_retorno'}
                st.enter_context(patch.object(f,'preencher_minuta_sar_se_necessario',return_value=sar))
                acomp=st.enter_context(patch.object(f,'preencher_acompanhamento_seguro_re',return_value={'salvo':True,'confirmado_apos_salvar':caso!='acompanhamento'}))
                r=f._preencher_abas_com_regras_em_analise_no_re(None,None,req,resumo)
                self.assertEqual(r['status']=='concluido',caso=='ok')
                self.assertEqual(acomp.called,caso in {'ok','acompanhamento'})

    def test_acompanhamento_substitui_e_confirma(self):
        import controles_acompanhar as c
        for ok in (True, False):
            esperado={'status':'confirmado' if ok else 'erro_confirmacao',
                      'confirmado_apos_salvar':ok,'salvo':ok}
            with patch.object(c,'executar_acompanhamento_opcao4',return_value=esperado) as rotina:
                r=m.preencher_acompanhamento_seguro_re(None,None,'Frase')
                self.assertEqual(r['status']=='confirmado',ok)
                rotina.assert_called_once_with(None,None,'Frase')

    def test_frase_vazia_nao_altera_tela(self):
        with patch.object(s,'clicar_aba_informacoes_adicionais') as abrir:
            with self.assertRaises(RuntimeError): m.preencher_acompanhamento_seguro_re(None,None,'')
            abrir.assert_not_called()

    def test_sar_valores_tem_prioridade(self):
        r=s.analisar_sar_cct({'texto_completo':'Ensaio de SAR não aplicável. SAR cabeça: 0,85 W/kg', 'tabela_tecnica_cct':{'cabecalho':['SAR Cabeça (W/kg)'],'linhas':[['0,85']]}})
        self.assertTrue(r['sar_aplicavel'])
        self.assertFalse(r['preencher_frase'])

    def test_faixas_multiplas_sem_falso_positivo(self):
        tabela = {'cabecalho':['Faixa de Frequências Tx (MHz)', 'Potência Máxima de Saída (W)'], 'linhas':[['898,5 a 901 e 905 a 915','0,2333']]}
        expandida = m.expandir_faixas_explicitas_re(tabela)
        self.assertEqual(len(expandida['linhas']),2)
        self.assertEqual(len(tabela['linhas']),1)
        sch = dict(tabela, linhas=[['898.5 a 901','0.2333'], ['905 a 915','0.2333']])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(sch,expandida)['status'],'ok')
        ambigua = dict(tabela,linhas=[['898 a 901 e outra faixa','0,2']])
        self.assertEqual(m.expandir_faixas_explicitas_re(ambigua)['linhas'],ambigua['linhas'])

    def test_catalogo_cts_e_produto_principal(self):
        self.assertEqual(len(s.TITULOS_CARACTERISTICAS_SECUNDARIAS),11)
        for registro in s.TITULOS_CARACTERISTICAS_SECUNDARIAS:
            with self.subTest(categoria=registro['categoria']):
                resultado = s.diagnosticar_titulo_caracteristicas_secundarias(
                    req={'tipo_produto':'Estação Terminal de Acesso'},
                    dados_pdf={'texto_completo':registro['titulo']})
                self.assertEqual(resultado['titulo'],registro['titulo'])
        resultado = s.diagnosticar_titulo_caracteristicas_secundarias(
            req={'tipo_produto':'Transceptor de Radiação Restrita'},
            dados_pdf={'texto_completo':'Transceptor de Radiação Restrita'})
        self.assertFalse(resultado['titulo'])

    def test_sar_nao_confunde_potencia_com_sar(self):
        texto = ('SAR Cabeça (W/kg) SAR corpo (W/kg) Potência (W)\n'
                 '2400,0 - 2483,5 0,0003 GFSK - - 1 Bluetooth\n'
                 'Ensaio de SAR não aplicável: potência inferior a 20 mW.')
        self.assertFalse(s._texto_tem_valores_sar_em_contexto(texto)['tem_sar'])
        self.assertTrue(s.analisar_sar_cct({'texto_completo':texto})['sar_nao_aplicavel'])
        for texto in ['SAR cabeça: 0,85 W/kg', 'SAR corpo = 1.25', 'SAR: 2 W/kg']:
            with self.subTest(texto=texto):
                self.assertTrue(s._texto_tem_valores_sar_em_contexto(texto)['tem_sar'])

    def test_cct_mais_novo_e_falha_sem_fallback_antigo(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as pasta:
            antigo = Path(pasta) / 'antigo.pdf'
            novo = Path(pasta) / 'novo.pdf'
            antigo.write_bytes(b'%PDF-1.4')
            novo.write_bytes(b'%PDF-1.4')
            anexos = [
                {'categoria':'CCT','id':'2','data_hora':'11/07/2024 09:51','arquivo':str(antigo)},
                {'categoria':'CCT','id':'23','data_hora':'07/09/2026 08:33','arquivo':str(novo)},
            ]
            resultado = f._selecionar_cct_mais_recente_re(anexos,pasta)
            self.assertEqual(resultado['arquivo'],str(novo))
            anexos[1]['arquivo'] = str(Path(pasta) / 'indisponivel.pdf')
            resultado = f._selecionar_cct_mais_recente_re(anexos,pasta)
            self.assertEqual(resultado['status'],'cct_mais_recente_indisponivel')
            self.assertFalse(resultado['arquivo'])
            anexos[1]['data_hora'] = ''
            self.assertEqual(f._selecionar_cct_mais_recente_re(anexos,pasta)['status'],
                             'data_anexo_indisponivel')

    def test_resumo_opcao4_separado_do_tradicional(self):
        from datetime import datetime
        agora = datetime(2026,10,28,10,0)
        resultado = {'modo_analise_re':'analise_simplificada',
                     'requerimento':{'requerimento':'05100/24','tipo_produto':'ETA'},
                     'conferencia_sch_cct':{'status_geral':'parcial'}}
        html = g._html_consolidado_retorno_para_estudo([resultado],'teste',agora,agora)
        self.assertIn('Resumo da análise documental e técnica',html)
        self.assertIn('Campos inconclusivos',html)
        self.assertNotIn('<th>Números RE</th>',html)
        self.assertNotIn('<th>Docs obrigatórios</th>',html)
        self.assertNotIn('NÃO ANALISADO',html)
        resultado['modo_analise_re']='comparar_versoes'
        with patch.object(g,'_html_consolidado_simplificada_re') as novo:
            html = g._html_consolidado_retorno_para_estudo([resultado],'teste',agora,agora)
            novo.assert_not_called()
        self.assertIn('Números RE',html)

    def test_tabelas_paginas_com_colunas_distintas(self):
        import pdf_parser as parser
        partes = [
            [['Faixa de Frequências (MHz)', 'Potência Máxima de Saída (W)', 'SAR Corpo (W/kg)'],
             ['2400 a 2483,5', '0,0033', '-']],
            [['Faixa de Frequências (MHz)', 'Valor Médio de Potência EIRP (W)',
              'Potência Máxima de Saída (W)', 'SAR Corpo (W/kg)'],
             ['5470 a 5725', '0,0121', '0,0612', '0,938']],
        ]
        tabela = parser._extrair_tabela_tecnica_cct_de_tabelas(partes)
        self.assertEqual(len(tabela['linhas']), 2)
        cab = tabela['cabecalho']
        saida = cab.index('Potência Máxima de Saída (W)')
        eirp = cab.index('Valor Médio de Potência EIRP (W)')
        sar = cab.index('SAR Corpo (W/kg)')
        self.assertEqual(tabela['linhas'][1][saida], '0,0612')
        self.assertEqual(tabela['linhas'][1][eirp], '0,0121')
        self.assertEqual(tabela['linhas'][1][sar], '0,938')
        self.assertEqual(tabela['linhas'][0][eirp], '')

    def test_eirp_nao_vira_divergencia_de_saida(self):
        cct = {'cabecalho':['Faixa de Frequências (MHz)', 'Potência Máxima de Saída (W)',
                           'Valor Médio de Potência EIRP (W)'],
               'linhas':[['2400 a 2483,5', '0,0033', ''], ['5470 a 5725','0,0612','0,0121']],
               'paginas_origem':[4,5], 'origens_linhas':[{'pagina':4},{'pagina':5}]}
        sch = {'cabecalho':['Faixa de Frequências (MHz)', 'Potência Máxima de Saída (W)'],
               'linhas':[['2400 a 2483,5','0,0033'], ['5470 a 5725','0,0121']]}
        resultado = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(resultado['status'], 'comparacao_parcial')
        self.assertFalse(resultado['divergencias'])
        self.assertEqual(resultado['inconclusivos'][0]['pagina'],5)
        sch['linhas'][0][1] = '0,9999'
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(sch,cct)['status'],'divergente')

    def test_geometria_cabecalho_em_tres_linhas(self):
        import pdf_parser as parser
        from types import SimpleNamespace
        dados = [
            ['Faixa de Frequências (MHz)', '', 'Potência', '', 'SAR'],
            ['', '', 'Máxima de', '', 'Corpo'], ['', '', 'Saída (W)', '', '(W/kg)'],
            ['2400 a 2483,5', '0,0033', '', '0,9', ''],
        ]
        cells = [
            [(0,0,100,30),None,(110,0,190,10),None,(210,0,290,10)],
            [None,None,(110,10,190,20),None,(210,10,290,20)],
            [None,None,(110,20,190,30),None,(210,20,290,30)],
            [(0,30,100,50),(100,30,200,50),None,(200,30,300,50),None],
        ]
        tabela = SimpleNamespace(rows=[SimpleNamespace(cells=c) for c in cells],extract=lambda:dados)
        resultado = parser._extrair_tabela_tecnica_por_geometria(tabela)
        self.assertEqual(resultado[0][1],'Potência Máxima de Saída (W)')
        self.assertEqual(resultado[1],['2400 a 2483,5','0,0033','0,9'])

    def test_relatorio_parcial(self):
        r={'modo_analise_re':'analise_simplificada','conferencia_sch_cct':{'status_geral':'parcial'}}
        self.assertEqual(g._resultado_executivo_retorno(r),'Analisado — revisão manual')
        self.assertIn('Título das Características Técnicas Secundárias',g._html_preenchimento_simplificado_re(r))

if __name__ == '__main__': unittest.main()
