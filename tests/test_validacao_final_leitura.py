import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ/'automacao_sch_explicita'))
import diagnostico_final_cct as diag
import funcoes_sch as sch
import diagnostico_estrutura_sch as estrutura
import simulacao_simplificada_re as sim


class RevisaoFinalTests(unittest.TestCase):
    def test_plano_incompleto_e_saida_publica_bloqueados(self):
        with self.assertRaises(ValueError):diag.validar_caso({'requerimento':'00123/99'})
        with self.assertRaises(ValueError):diag.diretorio_privado(RAIZ/'docs')

    def test_linhas_ou_cabecalhos_ocultos_nao_sao_captura_completa(self):
        for tab in ({'linhas_dom':[{'visivel':False}]}, {'celulas_cabecalho':[{'visivel':False}]}):
            with self.assertRaises(RuntimeError):estrutura._validar_tabela_dom_completa(tab)

    def test_parcial_nao_imprime_conferencia_ok(self):
        r={'modo_comparacao':'simplificada','conformidade_integral':False,
           'status_geral':'parcial','divergencias':[]}
        out=io.StringIO()
        with contextlib.redirect_stdout(out):sch.avisar_resultado_conferencia_sch_cct(r)
        self.assertNotIn('Conferência SCH x CCT OK',out.getvalue())
        self.assertIn('conformidade integral não declarada',out.getvalue())

    def test_comparador_tradicional_nao_aciona_colecao(self):
        with patch.object(sch,'comparar_tabelas_tecnicas_sch_cct',return_value={'status':'ok'}) as antigo, patch.object(sch,'comparar_conjunto_tabelas_simplificado') as novo:
            sch.comparar_dados_sch_x_cct({}, {})
        antigo.assert_called_once();novo.assert_not_called()

    def test_sar_nao_diverge_se_identidade_da_linha_e_inconclusiva(self):
        t={'cabecalho':['Frequência (MHz)','Potência de Saída (W)','SAR Cabeça (W/kg)'],
           'linhas':[['200 a 201','0,1','0,2']]}
        outro=dict(t,linhas=[['200 a 201','0,1','0,3']])
        parcial={'status':'comparacao_parcial','divergencias':[],
                 'detalhes_correspondencias':[{'correspondencia_identificada':False}]}
        with patch.object(sch,'comparar_tabelas_tecnicas_sch_cct',return_value=parcial):
            r=sch.comparar_conjunto_tabelas_simplificado({'tabelas':[t]},{'tabelas_identificadas':[outro]})
        self.assertEqual(r['status'],'comparacao_parcial');self.assertFalse(r['divergencias'])

    def test_mesma_faixa_em_partes_distintas_nao_prova_par_unico(self):
        a={'cabecalho':['Frequência (MHz)','Potência de Saída (W)'],'linhas':[['200 a 201','0,1']]}
        b=dict(a,linhas=[['200 a 201','0,2']])
        r=sch.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[a,b]})
        self.assertEqual(r['status'],'comparacao_parcial');self.assertFalse(r['divergencias'])
        self.assertTrue(any(p['comparacao'].get('divergencias_reclassificadas_como_inconclusivas')
                            for t in r['tabelas'] for p in t['partes_cct']))

    def test_tecnologia_agrupada_sch_nao_identifica_modo_isolado_cct(self):
        cab=['Frequência (MHz)','Potência de Saída (W)','Designação de Emissões','Tecnologia','Tipo de Modulação']
        a={'cabecalho':cab,'linhas':[['900 a 901','0,234','5M00G7W','WCDMA/HSDPA/HSUPA','QPSK 16QAM']]}
        b={'cabecalho':cab,'linhas':[['900 a 901','0,218','5M00G7W','WCDMA','QPSK 16QAM']]}
        r=sch.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[b]})
        self.assertEqual(r['status'],'comparacao_parcial');self.assertFalse(r['divergencias'])

    def test_resumo_e_sar_refletem_reclassificacao_no_conjunto(self):
        cab=['Frequência (MHz)','Potência de Saída (W)','Designação de Emissões','Tecnologia','Tipo de Modulação','SAR (W/kg) Corpo']
        a={'cabecalho':cab,'linhas':[['900 a 901','0,1','5M00G7W','WCDMA/HSDPA/HSUPA','QPSK','0,2']]}
        b={'cabecalho':cab,'linhas':[['900 a 901','0,1','5M00G7W','WCDMA','QPSK','0,2']]}
        r=sch.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[b]})
        comp=r['tabelas'][0]['partes_cct'][0]['comparacao']
        resumo=comp['resumo_correspondencias']
        self.assertEqual(resumo['pares_identificados'],0)
        self.assertEqual(resumo['sar_comparado_em_par_identificado'],0)
        self.assertEqual(resumo['coincidencias_numericas_saida'],1)
        self.assertEqual(comp['resumo_antes_reclassificacao']['pares_identificados'],1)
        self.assertEqual(comp['detalhes_correspondencias'][0]['sar_resultado'],'nao_comparado')
        self.assertNotIn('potencia_saida_w',comp['campos_comparados'])
        self.assertNotIn('sar_corpo_w_kg',comp['campos_comparados'])
        self.assertFalse(r['conformidade_integral'])

    def test_barreira_rejeita_escrita_e_script_desconhecido(self):
        guard=sim.DriverSomenteLeitura(Mock(),{})
        for acao in (lambda:guard.execute_script("document.forms[0].submit()"),
                     lambda:guard.send_keys('x'),lambda:guard.execute_cdp_cmd('Runtime.evaluate',{})):
            with self.assertRaises(sim.AcaoBloqueada):acao()

    def download_falso(self):
        bruto=Mock();guard=sim.DriverSomenteLeitura(bruto,{})
        guard.verificar_contexto=Mock()
        alvo={'id':'1','data_hora':'01/01/2099 10:00','nome_anexo':'ARQUIVO','tipo_documento':'CCT'}
        e=Mock();e.id='arquivo';e.tag_name='a';e.text='ARQUIVO'
        attrs={'href':'https://sistemasnet.anatel.gov.br/mosaico/sch/download?id=123','onclick':None}
        e.get_attribute.side_effect=lambda n:attrs.get(n)
        elemento=sim.ElementoLeitura(e,guard)
        bruto.execute_script.return_value={'tag':'A','celula':4,'linha':['1','CCT','',alvo['data_hora'],'ARQUIVO']}
        guard.registrar(sim.SCRIPT_VINCULO_DOWNLOAD);guard.definir_alvo_download_cct(alvo)
        return bruto,guard,alvo,elemento,attrs

    def test_link_x_ou_url_nao_download_nunca_pode_ser_autorizado(self):
        for href,handler in [('#','PrimeFaces.ab({})'),('javascript:void(0)',None),
                ('https://example.com/download?id=123',None),
                ('https://sistemasnet.anatel.gov.br/mosaico/sch/download?id=1&id=2',None)]:
            bruto,guard,alvo,e,attrs=self.download_falso();attrs.update(href=href,onclick=handler)
            with self.subTest(href=href),self.assertRaises(sim.AcaoBloqueada):guard.autorizar_download_cct(e,alvo)
            bruto.execute_script.assert_not_called()

    def test_troca_de_href_apos_autorizacao_bloqueia_clique(self):
        bruto,guard,alvo,e,attrs=self.download_falso()
        guard.autorizar_download_cct(e,alvo)
        attrs['href']='https://sistemasnet.anatel.gov.br/mosaico/sch/download?id=999'
        with self.assertRaises(sim.AcaoBloqueada):e.click()
        self.assertFalse(any(c.args[0]=='arguments[0].click();' for c in bruto.execute_script.call_args_list))

    def test_cli_edge_so_conecta_apos_plano_valido_sem_fechar_navegador(self):
        base=RAIZ/'dados_locais';base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as pasta:
            plano=Path(pasta)/'plano.json'
            plano.write_text(json.dumps({'casos':[{'requerimento':'00123/99','certificado':'CERT TESTE','modelo':'MODELO TESTE'}]}),encoding='utf-8')
            args=['diag','--plano',str(plano),'--requerimento','00123/99','--driver','driver.exe',
                  '--navegador','edge','--debugger','127.0.0.1:9324']
            with patch.object(sys,'argv',args),patch('selenium.webdriver.Edge') as edge,patch('selenium.webdriver.Chrome') as chrome,patch.object(diag,'executar',return_value={'status':'diagnostico_concluido_sem_declarar_conformidade_integral'}):
                with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(diag.main(),0)
            edge.assert_called_once();chrome.assert_not_called()
            edge.return_value.quit.assert_not_called();edge.return_value.service.stop.assert_called_once()

    def test_cli_fora_plano_nao_conecta(self):
        base=RAIZ/'dados_locais';base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as pasta:
            plano=Path(pasta)/'plano.json';plano.write_text('{"casos":[]}',encoding='utf-8')
            args=['diag','--plano',str(plano),'--requerimento','00123/99','--driver','driver.exe']
            with patch.object(sys,'argv',args),patch('selenium.webdriver.Edge') as edge,patch('selenium.webdriver.Chrome') as chrome:
                with self.assertRaises(ValueError):diag.main()
            edge.assert_not_called();chrome.assert_not_called()

    def fluxo_falso(self, modelo='MODELO TESTE'):
        base=RAIZ/'dados_locais'
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as pasta, contextlib.ExitStack() as st:
            saida=Path(pasta)/'execucao';driver=Mock();guard=Mock();guard.eventos=[]
            t={'cabecalho':['Frequência (MHz)','Potência de Saída (W)'],
               'linhas':[['200 a 201','0,1']],'total_linhas':1,'ordem_dom':1,'familia':'rf_frequencia_potencia'}
            guard.execute_script.return_value={'pronto':True,'tabelas':[t]}
            st.enter_context(patch.object(diag,'confirmar_por_visualizacao',return_value={'requerimento':'00123/99','vinculo_iframe':{'id':'teste'}}))
            st.enter_context(patch.object(diag,'preparar_guard',return_value=guard))
            st.enter_context(patch.object(sch,'extrair_dados_certificado_sch',return_value={'numero_certificado':'CERT TESTE','modelo_sch_dados_gerais':modelo}))
            captura=st.enter_context(patch.object(diag,'extrair_tabela_dom_para_comparacao',return_value={'tabelas':[t]}))
            download=st.enter_context(patch.object(sch,'baixar_cct_mais_recente_confirmado_re',return_value=({'id':'teste'},[])))
            st.enter_context(patch('fluxo_sch.confirmar_identidade_cct_baixado_re',return_value={'status':'confirmado',
                'dados_pdf':{'tabela_tecnica_cct':t}}))
            proibidos=[st.enter_context(patch.object(sch,n,side_effect=AssertionError('Rotina de escrita proibida'))) for n in
                ('salvar_informacoes_adicionais','preencher_acompanhar_processo','marcar_acompanhar_processo','preencher_minuta_sar_se_necessario')]
            class Wait:
                def until(self, fn, **kw):
                    for _ in range(3):
                        r=fn(None)
                        if r:return r
                    raise RuntimeError('Não estabilizou')
            with contextlib.redirect_stdout(io.StringIO()):
                r=diag.executar(driver,Wait(),{'requerimento':'00123/99','certificado':'CERT TESTE','modelo':'MODELO TESTE'},saida)
            self.assertTrue((saida/'resultado.json').is_file())
            self.assertTrue((saida/'resultado.html').is_file())
            for proibido in proibidos:proibido.assert_not_called()
            driver.quit.assert_not_called()
            self.assertNotIn('informacoes adicionais',guard.navegacoes)
            return r,captura.called,download.called

    def test_orquestracao_somente_leitura_com_relatório(self):
        r,_,_=self.fluxo_falso()
        self.assertTrue(r['status'].startswith('diagnostico_concluido'))
        self.assertEqual(r['gravacoes_executadas'],0)
        self.assertFalse(r['conformidade_integral'])

    def test_identidade_errada_interrompe_antes_de_captura_download(self):
        r,captura,download=self.fluxo_falso(modelo='OUTRO MODELO')
        self.assertEqual(r['status'],'interrompido')
        self.assertFalse(captura);self.assertFalse(download)


if __name__=='__main__':unittest.main()
