import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import simulacao_simplificada_re as sim
import mvp_simplificada_re as m
import fluxo_sch as f
import funcoes_sch as s


class SimulacaoTests(unittest.TestCase):
    def base(self):
        req={'requerimento':'01553/25','tipo_produto':'Transceptor de Radiação Restrita','modelo_sch_dados_gerais':'SM-X520'}
        dados={'numero_certificado':'CPQD-I 12407','tipo_produto':req['tipo_produto'],
               'observacao_texto':s.OBS_RADIACAO_RESTRITA,'texto_completo':'SAR Corpo: 1,270 W/kg. Ensaio de SAR não aplicável.',
               'tabela_tecnica_cct':{'cabecalho':['SAR Corpo (W/kg)'],'linhas':[['1,270']]},'diagnostico_extracao':{'status':'valida'}}
        resumo={'pdf_cct':'cct.pdf','dados_pdf':dados,'dados_certificado_sch':{'numero_certificado':'CPQD-i 12407'},
                'conferencia_sch_cct':{'status_geral':'parcial','comparacao_tabela_tecnica':{'status':'comparacao_parcial',
                    'resumo_correspondencias':{'linhas_ambiguas':18,'coincidencias_numericas_apenas_eirp':18},'divergencias':[]}}}
        estado={'observacao':{'localizado':True,'texto':s.OBS_RADIACAO_RESTRITA},
                'cts':{'localizado':False,'valor':None},'acompanhar':{'localizado':True,'valor':'Anterior','marcado':False}}
        return req,resumo,estado

    def test_parcial_nao_bloqueia_independentes_e_sar_real_preserva(self):
        req,resumo,estado=self.base()
        r=m.planejar_acoes_simplificadas(req,resumo,estado)
        self.assertFalse(r['comparacao_parcial_bloqueia_globalmente'])
        self.assertEqual(r['observacao']['decisao'],'preservar_existente')
        self.assertFalse(r['sar']['preencher_frase'])
        self.assertEqual(r['corrigir_minuta']['decisao'],'nao_abrir_nem_alterar_minuta')
        self.assertTrue(any(a['campo']=='Texto superior Acompanhar Processo' for a in r['campos_que_seriam_alterados']))
        self.assertFalse(any(a['campo']=='Observação' for a in r['campos_que_seriam_alterados']))

    def test_campos_nao_lidos_nao_sao_tratados_como_vazios(self):
        req,resumo,estado=self.base();estado['acompanhar']={'localizado':False}
        r=m.planejar_acoes_simplificadas(req,resumo,estado)
        self.assertEqual(r['acompanhar_processo']['decisao'],'revisar_campo_superior_nao_confirmado')
        self.assertFalse(r['campos_que_seriam_alterados'])

    def test_produto_fora_do_escopo_preservado(self):
        req,resumo,estado=self.base();req['tipo_produto']='Carregador para Telefone Celular'
        self.assertEqual(m.planejar_acoes_simplificadas(req,resumo,estado)['status'],'bloqueado_tipo_produto')

    def test_cts_sem_evidencia_nao_e_alterado(self):
        req,resumo,estado=self.base();estado['cts']={'localizado':True,'valor':'Existente'}
        with patch.object(s,'diagnosticar_titulo_caracteristicas_secundarias',return_value={'titulo':'','status':'revisar'}):
            r=m.planejar_acoes_simplificadas(req,resumo,estado)
        self.assertEqual(r['cts']['decisao'],'revisar_sem_evidencia_segura')
        self.assertFalse(any(a['campo']=='CTS' for a in r['campos_que_seriam_alterados']))

    def test_cts_sugestao_reutiliza_diagnostico(self):
        req,resumo,estado=self.base();estado['cts']={'localizado':True,'valor':'Antigo'}
        diag={'titulo':'Título seguro','status':'identificado','origens':['CCT explícito'],'pontuacao':110}
        with patch.object(s,'diagnosticar_titulo_caracteristicas_secundarias',return_value=diag):
            r=m.planejar_acoes_simplificadas(req,resumo,estado)
        self.assertEqual(r['cts']['origem_e_criterios'],diag)
        self.assertTrue(any(a['campo']=='CTS' for a in r['campos_que_seriam_alterados']))

    def test_guard_bloqueia_comandos_indiretos(self):
        bruto=Mock();guard=sim.DriverSomenteLeitura(bruto,{})
        e=Mock();e.text='Salvar';e.tag_name='button'
        elemento=sim.ElementoLeitura(e,guard)
        operacoes=[lambda:elemento.click(),lambda:elemento.send_keys('x'),lambda:elemento.clear(),lambda:elemento.submit(),
                   lambda:guard.execute_script('arguments[0].value="x";',elemento),
                   lambda:guard.execute_script('arguments[0].click();',elemento),
                   lambda:guard.execute_async_script('x'),lambda:guard.execute_cdp_cmd('Input.dispatchKeyEvent',{}),
                   lambda:guard.execute('actions',{}),lambda:guard.get('https://example.com'),lambda:guard.quit(),lambda:guard.close()]
        for operacao in operacoes:
            with self.assertRaises(sim.AcaoBloqueada):operacao()
        bruto.execute_script.assert_not_called()
        e.click.assert_not_called()

    def test_script_de_leitura_e_allowlist_selada(self):
        bruto=Mock();bruto.execute_script.return_value=3
        guard=sim.DriverSomenteLeitura(bruto,{})
        guard.registrar('return 3;')
        self.assertEqual(guard.execute_script('return 3;'),3)
        with self.assertRaises(sim.AcaoBloqueada):guard.registrar('document.body.innerHTML="";')
        guard._selado=True
        with self.assertRaises(sim.AcaoBloqueada):guard.registrar('return 4;')

    def test_clique_js_so_em_navegacao_validada(self):
        bruto=Mock();guard=sim.DriverSomenteLeitura(bruto,{})
        guard.verificar_contexto=Mock()
        e=Mock();e.text='Dados Gerais';e.tag_name='button'
        guard.execute_script('arguments[0].click();',sim.ElementoLeitura(e,guard))
        bruto.execute_script.assert_called_once_with('arguments[0].click();',e)
        e.text='Aprovar'
        with self.assertRaises(sim.AcaoBloqueada):guard.execute_script('arguments[0].click();',sim.ElementoLeitura(e,guard))
        self.assertEqual(bruto.execute_script.call_count,1)

    def test_fluxo_real_simulado_reutiliza_gate_sem_escrita(self):
        req,resumo,estado=self.base();guard=sim.DriverSomenteLeitura(Mock(),{})
        with patch.object(f,'extrair_dados_certificado_sch',return_value={'numero_certificado':'CPQD-i 12407','modelo_sch_dados_gerais':'SM-X520'}), \
             patch.object(f,'preencher_caracteristicas_conservadoras_re') as ct, \
             patch.object(f,'preencher_minuta_sar_se_necessario') as sar, \
             patch.object(f,'preencher_acompanhamento_seguro_re') as acomp:
            r=f._preencher_abas_com_regras_em_analise_no_re(guard,Mock(),req,resumo,simulacao=True,estado_simulacao=estado)
        self.assertEqual(r['status'],'simulado')
        self.assertFalse(r['executado']);self.assertEqual(r['gravacoes_executadas'],0)
        ct.assert_not_called();sar.assert_not_called();acomp.assert_not_called()

    def test_certificado_divergente_mantem_bloqueio_real(self):
        req,resumo,estado=self.base();resumo['dados_pdf']['numero_certificado']='OUTRO-1'
        r=f._preencher_abas_com_regras_em_analise_no_re(sim.DriverSomenteLeitura(Mock(),{}),Mock(),req,resumo,simulacao=True,estado_simulacao=estado)
        self.assertEqual(r['status'],'bloqueado_certificado_nao_correspondente')

    def test_sem_protecao_simulacao_e_recusada(self):
        req,resumo,estado=self.base()
        with self.assertRaises(RuntimeError):
            f._preencher_abas_com_regras_em_analise_no_re(Mock(),Mock(),req,resumo,simulacao=True,estado_simulacao=estado)

    def test_rotina_sar_real_nao_abre_minuta_com_sar_numerico(self):
        req,resumo,estado=self.base()
        driver=Mock()
        r=s.preencher_minuta_sar_se_necessario(driver,Mock(),resumo['dados_pdf'],preservar_existente=True)
        self.assertFalse(r['preencher_frase']);self.assertFalse(r['salvo'])
        self.assertFalse(driver.mock_calls)

    def test_sessao_expirada_bloqueia_antes_de_navegar(self):
        contexto={'caminho':'/mosaico/sch/worklist/analise/requerimento','idRequerimento':'81916','codCct':['88178'],'codInstancia':['411471']}
        bruto=Mock()
        bruto.execute_script.return_value={'principal':False,'url':'https://sistemasnet.anatel.gov.br/mosaico/sch/worklist/analise/requerimento?idRequerimento=81916&codCct=88178&codInstancia=411471','ultimo_status':401}
        guard=sim.DriverSomenteLeitura(bruto,contexto)
        with self.assertRaises(sim.AcaoBloqueada):guard.verificar_contexto()
        self.assertIn('401',guard.eventos[-1]['acao'])

    def test_helper_real_de_escrita_nao_consegue_alterar_campo(self):
        bruto=Mock();guard=sim.DriverSomenteLeitura(bruto,{})
        e=Mock();e.tag_name='textarea';e.get_attribute.return_value='Valor existente'
        protegido=sim.ElementoLeitura(e,guard)
        # A rotina de escrita existente é chamada, não substituída por stub.
        with self.assertRaises(sim.AcaoBloqueada):
            s._preencher_campo_sem_apagar_se_ja_tem_valor(guard,protegido,'Novo título')
        e.clear.assert_not_called();e.send_keys.assert_not_called()
        self.assertTrue(any(ev.get('status')=='bloqueada_simulacao' for ev in guard.eventos))

    def test_integracao_offline_cct_real_e_metadata_sintetica(self):
        import json
        raiz=Path(__file__).resolve().parents[1]
        pasta=raiz/'tests/fixtures/ccts'
        if not (pasta/'CPQD-i_12407_NOV_00A X.pdf').exists():self.skipTest('CCT real ausente')
        visual=json.loads((pasta/'sch_cpqd_transcricao_capturas.json').read_text(encoding='utf-8'))
        req,resumo,estado=self.base()
        estado.update(tipo_produto=req['tipo_produto'],dados_certificado_sch={'numero_certificado':'CPQD-i 12407','modelo_sch_dados_gerais':'SM-X520'},
                      tabelas_dom={'tabelas':[{'cabecalho_visivel':visual['cabecalho'],'linhas_visiveis':visual['linhas']}]},
                      anexos_cct=[{'categoria':'CCT','id':'1','data_hora':'05/09/2026 00:20','nome_anexo':'CPQD-i_12407_NOV_00A X','arquivo':''}])
        guard=sim.DriverSomenteLeitura(Mock(),{})
        with tempfile.TemporaryDirectory() as saida,patch.object(f,'extrair_dados_certificado_sch',return_value=estado['dados_certificado_sch']):
            r=sim.analisar_estado_integrado(guard,estado,'01553/25',saida,pasta)
        self.assertEqual(r['status'],'simulado')
        self.assertEqual(r['comparacao_cct_sch']['comparacao_tabela_tecnica']['resumo_correspondencias']['linhas_ambiguas'],18)
        self.assertEqual(r['plano']['gravacoes_executadas'],0)

    def test_cct_mais_recente_ausente_nao_usa_anterior(self):
        req,resumo,estado=self.base()
        estado.update(tipo_produto=req['tipo_produto'],dados_certificado_sch={'numero_certificado':'CPQD-i 12407'},
                      anexos_cct=[{'categoria':'CCT','id':'1','data_hora':'01/01/2025 10:00','nome_anexo':'antigo','arquivo':''},
                                  {'categoria':'CCT','id':'2','data_hora':'01/01/2026 10:00','nome_anexo':'novo','arquivo':''}])
        with tempfile.TemporaryDirectory() as pasta:
            (Path(pasta)/'antigo.pdf').write_bytes(b'%PDF')
            r=sim.analisar_estado_integrado(sim.DriverSomenteLeitura(Mock(),{}),estado,'01553/25',pasta,pasta)
        self.assertEqual(r['status'],'bloqueado_pre_condicoes')
        self.assertEqual(r['selecao_cct']['status'],'cct_mais_recente_indisponivel')

    def test_download_so_ultimo_anexo_forca_novos_bytes_e_revalida_metadados(self):
        metadados=[{'categoria':'CCT','id':'17','data_hora':'06/03/2025 18:38','nome_anexo':'velho','arquivo':''},
                   {'categoria':'CCT','id':'32','data_hora':'05/09/2026 00:20','nome_anexo':'novo','arquivo':''}]
        driver=Mock();driver.somente_leitura=False
        with tempfile.TemporaryDirectory() as pasta,patch.object(s,'clicar_aba_anexos'),patch.object(s,'clicar_categoria_anexo'),patch.object(s,'listar_ccts_categoria_atual_re',side_effect=[copy.deepcopy(metadados),copy.deepcopy(metadados)]),patch.object(s,'baixar_anexos_da_categoria_atual',return_value=[]) as baixar:
            selecao,registros=s.baixar_cct_mais_recente_confirmado_re(driver,Mock(),{},pasta,pasta)
        self.assertTrue(baixar.call_args.kwargs['forcar_download'])
        self.assertEqual(baixar.call_args.kwargs['ids_permitidos'],['32'])
        self.assertEqual(selecao['status'],'cct_mais_recente_indisponivel')
        alterados=copy.deepcopy(metadados);alterados[1]['data_hora']='06/09/2026 00:20'
        with tempfile.TemporaryDirectory() as pasta,patch.object(s,'clicar_aba_anexos'),patch.object(s,'clicar_categoria_anexo'),patch.object(s,'listar_ccts_categoria_atual_re',side_effect=[metadados,alterados]),patch.object(s,'baixar_anexos_da_categoria_atual',return_value=[]):
            selecao,_=s.baixar_cct_mais_recente_confirmado_re(driver,Mock(),{},pasta,pasta)
        self.assertEqual(selecao['status'],'metadados_alterados')

    def test_download_guard_permite_somente_link_exato_uma_vez(self):
        bruto=Mock();guard=sim.DriverSomenteLeitura(bruto,{})
        guard.verificar_contexto=Mock()
        alvo={'id':'32','data_hora':'05/09/2026 00:20','nome_anexo':'CCT','tipo_documento':'Certificado de Conformidade Técnica - CCT'}
        e=Mock();e.id='arquivo32';e.tag_name='a';e.text='CCT'
        e.get_attribute.side_effect=lambda nome: 'https://sistemasnet.anatel.gov.br/mosaico/sch/download?id=123' if nome=='href' else None
        elemento=sim.ElementoLeitura(e,guard)
        vinculo={'tag':'A','celula':4,'linha':['32',alvo['tipo_documento'],'',alvo['data_hora'],'CCT']}
        bruto.execute_script.return_value=vinculo
        guard.registrar(sim.SCRIPT_VINCULO_DOWNLOAD)
        guard.definir_alvo_download_cct(alvo)
        guard.autorizar_download_cct(elemento,alvo)
        elemento.click()
        self.assertEqual(bruto.execute_script.call_args.args,('arguments[0].click();',e))
        with self.assertRaises(sim.AcaoBloqueada):elemento.click()
        self.assertEqual(sum(ev.get('acao')=='download_cct_somente_leitura' for ev in guard.eventos),1)

    def test_metadados_alterados_bloqueiam_simulacao_mesmo_com_arquivo_local(self):
        req,resumo,estado=self.base()
        estado.update(exigir_download_real=True,selecao_download={'status':'metadados_alterados','arquivo':''})
        with tempfile.TemporaryDirectory() as pasta:
            r=sim.analisar_estado_integrado(sim.DriverSomenteLeitura(Mock(),{}),estado,'01553/25',pasta,pasta)
        self.assertEqual(r['status'],'bloqueado_identidade_download')

    def test_identidade_download_nao_aceita_fixture_por_nome(self):
        req,resumo,estado=self.base()
        selecao={'status':'selecionado','arquivo':'cct.pdf','id':'32','data_hora':'05/09/2026 00:20','nome_anexo':'CCT'}
        r=f.confirmar_identidade_cct_baixado_re(selecao,[dict(selecao,origem='local_por_nome')],{},req)
        self.assertEqual(r['status'],'bloqueado')

    def test_identidade_download_pdf_real_hash_modelo_e_certificado(self):
        import hashlib
        arquivo=Path(__file__).resolve().parents[1]/'tests/fixtures/ccts/CPQD-i_12407_NOV_00A X.pdf'
        if not arquivo.exists():self.skipTest('PDF real ausente')
        sha=hashlib.sha256(arquivo.read_bytes()).hexdigest()
        selecao={'status':'selecionado','arquivo':str(arquivo),'id':'32','data_hora':'05/09/2026 00:20','nome_anexo':arquivo.stem}
        registro=dict(selecao,origem='download_sch_nesta_execucao',download_confirmado=True,sha256=sha)
        sch={'numero_certificado':'CPQD-i 12407','modelo_sch_dados_gerais':'SM-X520'}
        r=f.confirmar_identidade_cct_baixado_re(selecao,[registro],sch,{})
        self.assertEqual(r['status'],'confirmado')
        self.assertEqual(r['sha256'],sha)
        with patch.object(f,'parsear_certificado_pdf',return_value={'numero_certificado':'OUTRO','modelo':'SM-X520'}):
            self.assertEqual(f.confirmar_identidade_cct_baixado_re(selecao,[registro],sch,{})['status'],'bloqueado')
        with patch.object(f,'parsear_certificado_pdf',return_value={'numero_certificado':'CPQD-i 12407','modelo':'OUTRO'}):
            self.assertEqual(f.confirmar_identidade_cct_baixado_re(selecao,[registro],sch,{})['status'],'bloqueado')
        registro['sha256']='0'*64
        self.assertEqual(f.confirmar_identidade_cct_baixado_re(selecao,[registro],sch,{})['status'],'bloqueado')

    def test_download_bytes_invalidos_bloqueiam_mesmo_com_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as pasta:
            arquivo=Path(pasta)/'cct.pdf';arquivo.write_bytes(b'nao e PDF')
            selecao={'status':'selecionado','arquivo':str(arquivo),'id':'32'}
            registro=dict(selecao,origem='download_sch_nesta_execucao',download_confirmado=True,sha256=hashlib.sha256(arquivo.read_bytes()).hexdigest())
            self.assertEqual(f.confirmar_identidade_cct_baixado_re(selecao,[registro],{}, {})['status'],'bloqueado')

    def test_gate_opcao4_exige_download_confirmado_antes_de_qualquer_escrita(self):
        req,resumo,estado=self.base()
        with patch.object(f,'preencher_caracteristicas_conservadoras_re') as escrever:
            r=f._preencher_abas_com_regras_em_analise_no_re(Mock(),Mock(),req,resumo)
        self.assertEqual(r['status'],'bloqueado_identidade_download')
        escrever.assert_not_called()

    def test_cts_ausente_confirmado_e_indicio_nao_confundem_com_complementares(self):
        driver=Mock()
        driver.execute_script.return_value={'texto':'Características Técnicas Básicas Especificações Complementares','rotulos':[], 'campos':[],'navegacao':[]}
        with patch.object(s,'_localizar_campo_titulo_caracteristicas_secundarias',return_value=None):
            self.assertEqual(s.diagnosticar_campo_cts_re(driver)['status'],'nao_aplicavel_ausencia_confirmada')
            driver.execute_script.return_value['texto']+=' Características Técnicas Secundárias'
            self.assertEqual(s.diagnosticar_campo_cts_re(driver)['status'],'revisar_localizacao')

    def test_cts_seletor_legado_nao_autoriza_campo_sem_rotulo_associado(self):
        driver=Mock();campo=Mock();campo.get_attribute.return_value='outro'
        evidencia={'texto':'Características Técnicas Básicas','rotulos':[],'campos':[{'id':'outro','rotulos':['Especificações Complementares']}],'navegacao':[]}
        driver.execute_script.return_value=evidencia
        with patch.object(s,'_localizar_campo_titulo_caracteristicas_secundarias',return_value=campo):
            self.assertEqual(s.diagnosticar_campo_cts_re(driver)['status'],'revisar_identidade_campo')
            evidencia['campos'][0]['rotulos']=['Título/Descrição para Características Técnicas Secundárias']
            self.assertEqual(s.diagnosticar_campo_cts_re(driver)['status'],'localizado_confirmado')

    def test_download_guard_recusa_alvo_ou_link_sem_vinculo(self):
        guard=sim.DriverSomenteLeitura(Mock(),{})
        guard.verificar_contexto=Mock()
        e=Mock();alvo={'id':'32','data_hora':'05/09/2026 00:20','nome_anexo':'CCT','tipo_documento':'Certificado de Conformidade Técnica - CCT'}
        guard.definir_alvo_download_cct(alvo)
        with self.assertRaises(sim.AcaoBloqueada):
            guard.autorizar_download_cct(e,dict(alvo,id='17'))
        guard.execute_script=Mock(return_value={'tag':'A','celula':0,'linha':[]})
        with self.assertRaises(sim.AcaoBloqueada):guard.autorizar_download_cct(e,alvo)
        guard._driver.execute_script.assert_not_called()

    def test_cli_utiliza_modulo_canonico_da_barreira(self):
        import runpy
        with patch.object(sim,'main') as entrada:
            runpy.run_path(sim.__file__,run_name='__main__')
        entrada.assert_called_once_with()

    def test_anexos_relocaliza_apos_atualizacao_ajax(self):
        from selenium.common.exceptions import StaleElementReferenceException
        guard=Mock(); wait=Mock()
        guard.execute_script.side_effect=[StaleElementReferenceException(),[['1','CCT','Detalhe','01/01/2026 12:00','CCT.pdf']]]
        with patch.object(s,'localizar_tabela_anexos',side_effect=['antiga','nova']) as localizar:
            linhas=sim.ler_linhas_anexos(guard,wait)
        self.assertEqual(linhas[0][-1],'CCT.pdf')
        self.assertEqual(localizar.call_count,2)
        self.assertEqual(guard.execute_script.call_args.args,(sim.SCRIPT_LINHAS_ANEXOS,'nova'))

    def test_anexos_instaveis_interrompem_sem_repeticao_ilimitada(self):
        from selenium.common.exceptions import StaleElementReferenceException
        guard=Mock();guard.execute_script.side_effect=StaleElementReferenceException()
        with patch.object(s,'localizar_tabela_anexos') as localizar:
            with self.assertRaises(StaleElementReferenceException):
                sim.ler_linhas_anexos(guard,Mock())
        self.assertEqual(localizar.call_count,3)

    def test_relatorio_simulado_escapa_conteudo_e_nao_confirma_escrita(self):
        with tempfile.TemporaryDirectory() as pasta:
            sim.salvar_relatorios({'modo':'simulacao','status':'bloqueado_pre_condicoes','motivo':'<script>','gravacoes_executadas':0},pasta)
            texto=(Path(pasta)/'simulacao_opcao4.html').read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;',texto)
        self.assertIn('Nenhum campo foi gravado',texto)


if __name__=='__main__':unittest.main()
