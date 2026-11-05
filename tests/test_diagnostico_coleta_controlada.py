from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, PropertyMock

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import teste_controlado_acompanhar as t
import diagnostico_estrutura_sch as d
from selenium.common.exceptions import TimeoutException


class LogsColetaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pasta=Path(self.temp.name)

    def adapter(self):
        a=object.__new__(t.SeleniumRestrito)
        a.pasta=self.pasta;a.diagnostico_coleta=[];a.guard=Mock()
        a.guard.execute_script.return_value={'documento':'complete','jquery_ativo':0}
        return a

    def test_logs_inicio_fim_tempo_e_persistencia(self):
        a=self.adapter();out=StringIO()
        with redirect_stdout(out),a._etapa('dados_gerais.aguardar_documento_ajax'):
            pass
        self.assertIn('[INICIO]',out.getvalue());self.assertIn('[OK]',out.getvalue())
        salvo=json.loads((self.pasta/'coleta_diagnostico.json').read_text(encoding='utf-8'))
        self.assertEqual(salvo[0]['status'],'concluida');self.assertGreaterEqual(salvo[0]['duracao_s'],0)

    def test_timeout_vazio_recebe_etapa_traceback_e_estado_ajax(self):
        a=self.adapter();out=StringIO()
        with redirect_stdout(out):
            with self.assertRaisesRegex(t.Cancelado,'pdf.esperar_download_estavel_45s'):
                with a._etapa('pdf.esperar_download_estavel_45s'):
                    raise TimeoutException()
        evento=a.diagnostico_coleta[0]
        self.assertEqual(evento['status'],'falha')
        self.assertIn('TimeoutException',evento['traceback'])
        self.assertEqual(evento['estado_carregamento']['jquery_ativo'],0)
        self.assertIn('[FALHA]',out.getvalue())

    def test_falha_diagnostico_nao_oculta_causa_original(self):
        a=self.adapter();a.guard.execute_script.side_effect=RuntimeError('janela fechada')
        with redirect_stdout(StringIO()),self.assertRaisesRegex(t.Cancelado,'contexto.*identidade divergente'):
            with a._etapa('contexto'):
                raise RuntimeError('identidade divergente')
        self.assertEqual(a.diagnostico_coleta[0]['falha_diagnostico'],'RuntimeError')

    def test_resultado_inclui_etapa_exata_e_nao_habilita_escrita(self):
        a=Mock();a.diagnostico_coleta=[{'etapa':'pdf.esperar_download_estavel_45s','status':'falha'}]
        a.coletar.side_effect=t.Cancelado('pdf.esperar_download_estavel_45s: sem arquivo')
        r=t.executar(a,{'texto':'','marcado':False},self.pasta)
        self.assertIsNone(r['antes']);self.assertFalse(r['salvamento']['tentativa_iniciada'])
        self.assertEqual(r['diagnostico_coleta'],a.diagnostico_coleta)
        a.habilitar.assert_not_called();a.salvar_uma_vez.assert_not_called()

    def test_wait_documento_ajax_utiliza_limite_existente_e_mensagem(self):
        a=self.adapter();a.wait=Mock()
        a._aguardar_ajax()
        self.assertIn('limite já configurado',a.wait.until.call_args.kwargs['message'])

    def test_painel_sem_textarea_nao_chama_localizador_que_poderia_pegar_descricao(self):
        a=self.adapter();a.wait=Mock();cb=Mock()
        painel={'painel':'formAnalise:acompanharProcessoPanel','checkbox_no_painel':True,
                'checkboxId':'cb','textareas':[],'textAreaPanel':'formAnalise:textAreaPanel'}
        a.guard.execute_script.return_value=painel
        with redirect_stdout(StringIO()),patch.object(t.s,'_localizar_checkbox_acompanhar_processo',return_value=cb),patch.object(t.s,'_localizar_textarea_acompanhar_processo') as localizar:
            ta,caixa,botao,vinculo=a._controles(permitir_painel_sem_textarea=True)
            self.assertIsNone(ta);self.assertIsNone(botao);self.assertIs(caixa,cb)
            self.assertFalse(vinculo['valido'])
            with self.assertRaisesRegex(t.Cancelado,'não renderizado'):a._controles()
        localizar.assert_not_called();cb.click.assert_not_called()

    def test_coleta_leitura_completa_nao_inventa_valor_de_campo_ausente(self):
        a=self.adapter();a.wait=Mock();a._contexto=Mock();a._aguardar_ajax=Mock()
        a._inventario=Mock(return_value={'descricao_inferior':'preservada'})
        a._ler_callback_change=Mock(return_value={'vinculo_ajax_confirmado':False})
        a._SeleniumRestrito__identidade_pdf={'requerimento':t.REQUERIMENTO,'vinculo_iframe':t.CONTEXTO}
        cb=Mock();cb.is_selected.return_value=False
        a._controles=Mock(return_value=(None,cb,None,{'textoId':None,'checkboxId':'cb','salvarId':None,'valido':False}))
        with redirect_stdout(StringIO()),patch.object(t.s,'extrair_dados_certificado_sch',return_value={'numero_certificado':t.CERTIFICADO,'modelo_sch_dados_gerais':t.MODELO}),patch.object(t.s,'_texto_visivel_sch',return_value=''),patch.object(t.s,'_extrair_valor_sch_por_rotulo',return_value=t.TIPO),patch.object(t.s,'clicar_aba_caracteristicas_tecnicas'),patch.object(t.s,'clicar_aba_anexos'),patch.object(t.s,'clicar_aba_informacoes_adicionais'):
            r=a.coletar()
        self.assertTrue(r['coleta_leitura_concluida']);self.assertIsNone(r['texto'])
        self.assertFalse(r['vinculo_confirmado']);self.assertFalse(r['marcado'])
        self.assertIn('desconhecido',r['motivo_preparacao_bloqueada'])
        self.assertIsNone(a._SeleniumRestrito__alvos)

    def test_preparacao_bloqueia_valor_desconhecido_mas_preserva_antes_coletado(self):
        a=Mock();a.diagnostico_coleta=[]
        a.coletar.return_value={'identidade':{'requerimento':t.REQUERIMENTO,'contexto':t.CONTEXTO,
                                            'tipo_produto':t.TIPO,'certificado':t.CERTIFICADO,'modelo':t.MODELO},
                              'vinculo_confirmado':False,'texto':None,'marcado':False,
                              'motivo_preparacao_bloqueada':'Campo superior não renderizado; desconhecido.'}
        r=t.executar(a,{'texto':'','marcado':False},self.pasta)
        self.assertIsNotNone(r['antes']);self.assertIsNone(r['antes']['texto'])
        self.assertIn('não renderizado',r['falhas'][0])
        a.habilitar.assert_not_called();a.salvar_uma_vez.assert_not_called()

    def driver_pdf(self):
        driver=Mock();driver.current_window_handle='principal'
        driver.window_handles=['principal']
        botao=Mock();botao.is_displayed.return_value=True
        driver.find_elements.return_value=[botao]
        return driver,botao

    def test_timeout_pdf_descreve_pasta_arquivos_aba_sem_expor_query(self):
        driver,botao=self.driver_pdf()
        driver.current_url='https://sistemasnet.anatel.gov.br/mosaico/sch/rest/visualizarPdf/requerimento?segredo=nao_logar'
        driver.title='PDF'
        with patch.object(type(driver),'window_handles',new_callable=PropertyMock,create=True) as abas,patch.object(d,'contexto_iframe',return_value=t.CONTEXTO),patch('selenium.webdriver.support.ui.WebDriverWait') as wait:
            abas.side_effect=[['principal'],['principal','pdf']]
            wait.return_value.until.side_effect=TimeoutException()
            with self.assertRaises(TimeoutException) as erro:
                d.confirmar_por_visualizacao(driver,t.REQUERIMENTO,self.pasta)
        self.assertIn('45s',str(erro.exception));self.assertIn('novas_abas',str(erro.exception))
        self.assertNotIn('segredo',str(erro.exception))
        botao.click.assert_called_once_with()
        driver.switch_to.window.assert_called_with('principal')

    def test_pdf_download_maiusculo_temporario_e_numero_real(self):
        import pymupdf
        driver,botao=self.driver_pdf()
        def aguardar(predicado):
            arquivo=self.pasta/'NOVO.PDF'
            with pymupdf.open() as pdf:
                pagina=pdf.new_page();pagina.insert_text((20,30),'Requerimento: 01553/25')
                pdf.save(arquivo)
            tmp=self.pasta/'NOVO.PDF.crdownload';tmp.write_bytes(b'parcial')
            self.assertFalse(predicado(driver));tmp.unlink()
            self.assertFalse(predicado(driver))
            return predicado(driver)
        with patch.object(d,'contexto_iframe',return_value=t.CONTEXTO),patch('selenium.webdriver.support.ui.WebDriverWait') as wait:
            wait.return_value.until.side_effect=aguardar
            r=d.confirmar_por_visualizacao(driver,t.REQUERIMENTO,self.pasta)
        self.assertEqual(r['requerimento'],t.REQUERIMENTO)
        self.assertEqual(r['origem_pdf'],'download_chrome')
        self.assertEqual(wait.call_args.args[1],45)
        botao.click.assert_called_once_with()

    def test_pdf_inline_aceita_so_nova_aba_da_rota_exata(self):
        driver,botao=self.driver_pdf()
        driver.current_url='https://sistemasnet.anatel.gov.br/mosaico/sch/rest/visualizarPdf/requerimento?id=novo'
        import pymupdf
        def baixar(drv,url,pasta):
            with pymupdf.open() as pdf:
                pagina=pdf.new_page();pagina.insert_text((20,30),'Requerimento: 01553/25')
                pdf.save(self.pasta/'aba.pdf')
        def aguardar(predicado):
            self.assertFalse(predicado(driver));self.assertFalse(predicado(driver))
            return predicado(driver)
        with patch.object(type(driver),'window_handles',new_callable=PropertyMock,create=True) as abas,patch.object(d,'contexto_iframe',return_value=t.CONTEXTO),patch.object(d,'_baixar_visualizacao_pdf_aba',side_effect=baixar) as baixar_mock,patch('selenium.webdriver.support.ui.WebDriverWait') as wait:
            abas.side_effect=[['principal'],['principal','pdf']]
            wait.return_value.until.side_effect=aguardar
            r=d.confirmar_por_visualizacao(driver,t.REQUERIMENTO,self.pasta)
        self.assertEqual(r['origem_pdf'],'aba_pdf_sch_get_autenticado')
        baixar_mock.assert_called_once();botao.click.assert_called_once_with()

    def test_http_pdf_nao_aceita_outro_host_rota_login_redirect_ou_html(self):
        driver=Mock();driver.get_cookies.return_value=[]
        for url in ('https://outro.example/arquivo.pdf','http://sistemasnet.anatel.gov.br/mosaico/sch/rest/visualizarPdf/requerimento',
                    'https://sistemasnet.anatel.gov.br/login'):
            with self.subTest(url=url),patch('urllib.request.build_opener') as abrir:
                with self.assertRaises(RuntimeError):d._baixar_visualizacao_pdf_aba(driver,url,self.pasta)
                abrir.assert_not_called()
        driver.execute_script.return_value='Chrome teste'
        url='https://sistemasnet.anatel.gov.br/mosaico/sch/rest/visualizarPdf/requerimento'
        with patch('urllib.request.build_opener') as abrir:
            resposta=abrir.return_value.open.return_value.__enter__.return_value
            resposta.status=200;resposta.read.return_value=b'<html>login</html>'
            with self.assertRaisesRegex(RuntimeError,'não é um PDF'):d._baixar_visualizacao_pdf_aba(driver,url,self.pasta)
            classe=abrir.call_args.args[0]
            with self.assertRaisesRegex(RuntimeError,'redirecionou'):classe.redirect_request(None,None,None,None,None,None)
        self.assertFalse(list(self.pasta.glob('*.pdf')))


if __name__=='__main__':unittest.main()
