"""Captura DOM local/mocks; estes testes não comprovam autenticação no SCH."""
import copy
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

RAIZ = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0,str(RAIZ/'automacao_sch_explicita'))
import diagnostico_estrutura_sch as d
import funcoes_sch as s
import navegador as n


def identidade(numero='01553/25'):
    return {'frame':'iframe','evidencias':[{'rotulo':'Requerimento','valores':[numero]}]}


class CapturaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fixtures_sinteticas import tabela_sintetica
        cls.fixture = tabela_sintetica()

    def tabela(self):
        return {'cabecalho':self.fixture['cabecalho'], 'cabecalho_visivel':self.fixture['cabecalho'],
                'linhas':copy.deepcopy(self.fixture['linhas']), 'linhas_visiveis':copy.deepcopy(self.fixture['linhas']),
                'identificador_html':'tecnica', 'total_linhas':35,'total_colunas':6,'colunas_por_linha':[6]*35,
                'paginacao_detectada':[],'virtualizacao_detectada':False,'total_linhas_aria':None}

    def test_identidade_exata_no_iframe(self):
        self.assertEqual(d.confirmar_identidade(identidade('1553/2025'),'01553/25')['requerimento'],'01553/25')
        for bruto in [identidade('01554/25'),identidade('01553/24'),{'frame':'principal','evidencias':identidade()['evidencias']},
                      {'frame':'iframe','evidencias':[]},
                      {'frame':'iframe','evidencias':[{'valores':['01553/25 01554/25']}]}]:
            with self.subTest(bruto=bruto),self.assertRaises(RuntimeError):
                d.confirmar_identidade(bruto,'01553/25')

    def test_cnpj_nao_e_numero_de_requerimento(self):
        bruto={'frame':'iframe','evidencias':[{'rotulo':'CPF/CNPJ:','valores':['00.280.273/0002-18']}]}
        with self.assertRaises(RuntimeError):
            d.confirmar_identidade(bruto,'00273/02')

    def test_identidade_rotulada_pdf_visualizacao(self):
        self.assertEqual(d.identidade_pdf('REQUERIMENTO Nº: 01553/25\nModelo: SM-X520','01553/25'),'01553/25')
        for texto in ['CPF/CNPJ: 00.280.273/0002-18','REQUERIMENTO Nº: 01554/25',
                      'REQUERIMENTO Nº: 01553/25 REQUERIMENTO Nº: 01554/25']:
            with self.subTest(texto=texto),self.assertRaises(RuntimeError):
                d.identidade_pdf(texto,'01553/25')

    def test_fixture_35_todas_colunas_e_multiplicidade(self):
        tabela = self.tabela()
        tabela['linhas_visiveis'].reverse()
        self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'ok')
        for coluna in range(6):
            alterada = self.tabela()
            alterada['linhas_visiveis'][0][coluna]='999999'
            with self.subTest(coluna=coluna):
                self.assertEqual(d.comparar_captura_visual(alterada,self.fixture)['status'],'divergente')
        tabela = self.tabela()
        tabela['linhas_visiveis'][0]=tabela['linhas_visiveis'][1]
        self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'divergente')

    def test_cabecalho_reordenado_sem_mudar_origem(self):
        tabela = self.tabela()
        antes = copy.deepcopy(tabela)
        tabela['cabecalho_visivel']=list(reversed(tabela['cabecalho_visivel']))
        tabela['linhas_visiveis']=[list(reversed(l)) for l in tabela['linhas_visiveis']]
        self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'ok')
        self.assertEqual(tabela['linhas'],antes['linhas'])

    def test_traco_nao_e_vazio_ou_zero(self):
        for valor in ['', '0']:
            tabela=self.tabela()
            tabela['linhas_visiveis'][0][5]=valor
            self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'divergente')

    def test_largura_e_cabecalhos_ambiguos(self):
        tabela=self.tabela();tabela['linhas_visiveis'][0].pop()
        self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'inconclusiva')
        tabela=self.tabela();tabela['cabecalho_visivel']=list(tabela['cabecalho_visivel'])
        tabela['cabecalho_visivel'][1]=tabela['cabecalho_visivel'][0]
        self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'inconclusiva')

    def capturar_mock(self, primeiro=None, ultimo=None, tabela=None, host='https://sistemasnet.anatel.gov.br/mosaico/sch/worklist/visualizar'):
        driver=Mock();driver.current_url=host
        snapshot={'pronto':True,'tabelas':[tabela or self.tabela()]}
        driver.execute_script.side_effect=[primeiro or identidade(),copy.deepcopy(snapshot),copy.deepcopy(snapshot),ultimo or identidade()]
        with tempfile.TemporaryDirectory() as pasta, patch.object(s,'entrar_iframe_detalhe_analise'), \
             patch.object(s,'clicar_aba_caracteristicas_tecnicas') as abrir:
            resultado=d.capturar_requerimento_somente_leitura(driver,Mock(),'01553/25',pasta)
            salvo=json.loads((Path(pasta)/'captura_sch.json').read_text(encoding='utf-8'))
            self.assertEqual(salvo,resultado)
        return resultado,abrir

    def test_captura_mock_guarda_todas_as_linhas_originais(self):
        tabela=self.tabela();tabela['linhas'][0][0]='  2.400,0 a 2.483,5\n'
        resultado,_=self.capturar_mock(tabela=tabela)
        self.assertEqual(resultado['status'],'capturado')
        self.assertEqual(resultado['tabela_capturada']['total_linhas'],35)
        self.assertEqual(resultado['tabela_capturada']['linhas'][0][0],'  2.400,0 a 2.483,5\n')

    def test_relatorio_derivado_nao_perde_originais_e_escapa_html(self):
        tabela=self.tabela();tabela['linhas'][0][0]='<script>valor original</script>'
        resultado={'requerimento_esperado':'01553/25','status':'capturado','captura_autenticada_real':False,'tabela_capturada':tabela}
        with tempfile.TemporaryDirectory() as pasta:
            destino=Path(pasta)/'relatorio.html'
            d.salvar_relatorio_diagnostico(resultado,destino)
            texto=destino.read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;valor original&lt;/script&gt;',texto)
        self.assertNotIn('<script>valor original',texto)
        self.assertEqual(texto.count('<tbody>'),1)
        self.assertEqual(texto.count('<td style='),35*6)

    def test_identidade_errada_bloqueia_navegacao(self):
        resultado,abrir=self.capturar_mock(primeiro=identidade('01554/25'))
        self.assertEqual(resultado['status'],'erro')
        self.assertFalse(resultado['captura_autenticada_real'])
        abrir.assert_not_called()

    def test_troca_de_requerimento_durante_captura_bloqueia(self):
        resultado,_=self.capturar_mock(ultimo=identidade('01554/25'))
        self.assertEqual(resultado['status'],'erro')
        self.assertFalse(resultado['captura_autenticada_real'])

    def test_host_externo_e_paginacao_nao_comprovam_completude(self):
        resultado,abrir=self.capturar_mock(host='https://example.org/mosaico/sch/')
        self.assertEqual(resultado['status'],'erro');abrir.assert_not_called()
        for campo,valor in [('paginacao_detectada',[{'texto':'Próxima'}]),('virtualizacao_detectada',True),('total_linhas_aria','100')]:
            tabela=self.tabela();tabela[campo]=valor
            with self.subTest(campo=campo):
                resultado,_=self.capturar_mock(tabela=tabela)
                self.assertEqual(resultado['status'],'erro')

    def test_factory_driver_explicito_sem_gerenciador(self):
        with tempfile.TemporaryDirectory() as pasta:
            driver_path=Path(pasta)/'driver.exe';driver_path.touch()
            with patch.object(n,'_criar_driver_chrome') as manager,patch.object(n.webdriver,'Chrome',return_value=Mock()) as chrome:
                n.criar_driver(navegador='chrome',pasta_base=pasta,caminho_driver=driver_path,caminho_navegador=driver_path)
            manager.assert_not_called()
            self.assertEqual(Path(chrome.call_args.kwargs['options'].binary_location).resolve(),driver_path.resolve())

    def test_reconexao_nao_reconfigura_navegador_existente(self):
        with tempfile.TemporaryDirectory() as pasta:
            path=Path(pasta)/'driver.exe';path.touch()
            with patch.object(n,'_criar_opcoes_chrome') as config,patch.object(n.webdriver,'Chrome',return_value=Mock()) as chrome:
                n.criar_driver(navegador='chrome',pasta_base=pasta,caminho_driver=path,debugger_address='127.0.0.1:58471')
            config.assert_not_called()
            options=chrome.call_args.kwargs['options']
            self.assertEqual(options.debugger_address,'127.0.0.1:58471')
            self.assertNotIn('detach',options.experimental_options)

    @unittest.skipUnless(os.environ.get('SCH_TEST_BROWSER')=='1','Teste DOM local opcional: definir SCH_TEST_BROWSER=1 e disponibilizar navegador/driver locais.')
    def test_selenium_dom_local_35_linhas_sem_acoes_de_escrita(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        driver_path=RAIZ/'diagnostico_sch/drivers/chromedriver-win64/chromedriver.exe'
        browser_path=RAIZ/'diagnostico_sch/drivers/chrome-win64/chrome.exe'
        if not driver_path.exists() or not browser_path.exists():
            self.skipTest('Navegador/driver de testes locais indisponíveis')
        options=webdriver.ChromeOptions()
        options.binary_location=str(browser_path)
        for argumento in ['--headless=new','--disable-gpu','--disable-background-networking','--no-first-run']:
            options.add_argument(argumento)
        driver=webdriver.Chrome(service=Service(str(driver_path)),options=options)
        try:
            with tempfile.TemporaryDirectory() as pasta:
                raiz=Path(pasta)
                cab=''.join('<th>'+html.escape(c)+'</th>' for c in self.fixture['cabecalho'])
                linhas=''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in l)+'</tr>' for l in self.fixture['linhas'])
                (raiz/'frame.html').write_text('<meta charset="utf-8"><script>window.escritas=0;</script><span>Requerimento: 01553/25</span>'
                    '<span id="requerimento:cnpj">CPF/CNPJ:</span><span>00.280.273/0002-18</span>'
                    '<table id="layout"><tr><td><table id="tecnica"><tr>'+cab+'</tr>'+linhas+'</table></td></tr></table>'
                    '<button onclick="window.escritas++">Salvar</button><button onclick="window.escritas++">Aprovar</button><button onclick="window.escritas++">Recusar</button>'
                    '<textarea>Observação existente</textarea><div>Especificações Complementares preservadas</div>',encoding='utf-8')
                (raiz/'index.html').write_text('<iframe src="frame.html" style="width:1800px;height:1200px"></iframe>',encoding='utf-8')
                driver.get((raiz/'index.html').as_uri())
                driver.switch_to.frame(driver.find_element(By.TAG_NAME,'iframe'))
                identidade_dom=driver.execute_script(d._SCRIPT_IDENTIDADE)
                self.assertEqual(d.confirmar_identidade(identidade_dom,'01553/25')['requerimento'],'01553/25')
                snapshot=driver.execute_script(d._SCRIPT_TABELAS_COMPLETAS)
                self.assertEqual(len(snapshot['tabelas']),1)
                tabela=snapshot['tabelas'][0]
                self.assertEqual(tabela['total_linhas'],35)
                self.assertEqual(tabela['total_colunas'],6)
                self.assertEqual(tabela['linhas'],self.fixture['linhas'])
                self.assertEqual(d.comparar_captura_visual(tabela,self.fixture)['status'],'ok')
                self.assertEqual(driver.execute_script('return window.escritas;'),0)
                longo='Texto técnico original ' * 100
                (raiz/'outro.html').write_text('<meta charset="utf-8"><table><tr><th>Faixa de Frequência (MHz)</th><th>Intensidade de Campo (uV/m)</th><th>Distância (m)</th></tr>'
                    '<tr><td>900 a 915</td><td>'+longo+'</td><td>3</td></tr></table>',encoding='utf-8')
                driver.switch_to.default_content()
                driver.get((raiz/'outro.html').as_uri())
                outro=driver.execute_script(d._SCRIPT_TABELAS_COMPLETAS)['tabelas'][0]
                self.assertEqual(outro['total_colunas'],3)
                self.assertEqual(outro['linhas'][0][1],longo)
        finally:
            # Encerra somente o navegador headless do teste local, não a sessão SCH.
            driver.quit()


if __name__=='__main__':
    unittest.main()
