import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import teste_controlado_acompanhar as t


def estado():
    return {'identidade':{'requerimento':t.REQUERIMENTO,'contexto':copy.deepcopy(t.CONTEXTO),
                         'tipo_produto':t.TIPO,'certificado':t.CERTIFICADO,'modelo':t.MODELO},
            'vinculo_confirmado':True,'vinculo':{'textoId':'superior','checkboxId':'cb','salvarId':'save','valido':True},
            'texto':'','marcado':False,
            'campos_preservados':{'observacao':'correta','cts':None,'tabela':35,'datas':['2025','2026'],
                                 'minuta':'SAR aplicável','anexos':[17,32],'inferior':'preservar'}}


def autorizacao():
    return {'autorizado':True,'requerimento':t.REQUERIMENTO,'acoes':copy.deepcopy(t.ACOES),
            'texto':t.FRASE,'referencia_institucional':'FIXTURE UNITARIA SEM VALIDADE INSTITUCIONAL',
            'responsavel_autorizacao':'Responsavel ficticio','operador':'Operador ficticio',
            'valida_ate':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}


class AdaptadorFalso:
    """Somente memória; jamais conecta ao SCH ou instancia Selenium."""
    def __init__(self):
        self.inicial=estado()
        self.chamadas=[]
        self.falha=None
        self.apos=None
        self.contagens=0

    def coletar(self):
        self.contagens+=1
        if 'reload' in self.chamadas:
            if self.apos is not None:return copy.deepcopy(self.apos)
            return dict(copy.deepcopy(self.inicial),texto=t.FRASE,marcado=True)
        return copy.deepcopy(self.inicial)

    def _acao(self,acao):
        self.chamadas.append(acao)
        if self.falha==acao:raise RuntimeError('Falha injetada '+acao)

    def habilitar(self,*_):self._acao('habilitar')
    def preencher_superior(self,*_):self._acao('texto')
    def marcar_checkbox(self,*_):self._acao('checkbox')
    def conferir_pendente(self,*_):self._acao('conferir')
    def salvar_uma_vez(self):self._acao('salvar');return 'Salvo com sucesso — fixture'
    def recarregar_do_servidor(self):self._acao('reload')


class ControladoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pasta=Path(self.temp.name)
        self.base={'texto':'','marcado':False,'datas_para_revisao':{'emissao':['2025','2026']}}
        self.adapter=AdaptadorFalso()

    def rodar(self,**kw):
        args={'executar_real':True,'obter_autorizacao':autorizacao,'confirmar':lambda _:t.CONFIRMACAO,
              'trava':self.pasta/'trava.json','ambiente':'testes_automatizados'}
        # Autorização deve permanecer byte a byte estável durante a confirmação.
        auth=autorizacao();args['obter_autorizacao']=lambda:copy.deepcopy(auth)
        args.update(kw)
        return t.executar(self.adapter,self.base,self.pasta,**args)

    def test_preparacao_padrao_nao_habilita_nem_grava(self):
        r=t.executar(self.adapter,self.base,self.pasta)
        self.assertEqual(r['status'],'preparado_sem_gravacao')
        self.assertEqual(self.adapter.chamadas,[])
        self.assertFalse((self.pasta/'trava.json').exists())

    def test_sucesso_fake_um_salvamento_e_nova_leitura(self):
        r=self.rodar()
        self.assertEqual(r['status'],'confirmado_apos_releitura_servidor')
        self.assertEqual(self.adapter.chamadas,['habilitar','texto','checkbox','conferir','salvar','reload'])
        self.assertEqual(self.adapter.contagens,3)
        self.assertEqual(r['datas_para_revisao_humana'],self.base['datas_para_revisao'])
        self.assertEqual(r['campos_preservados'],estado()['campos_preservados'])
        self.assertEqual(r['ambiente'],'testes_automatizados')

    def test_outro_requerimento_e_identidades_bloqueiam(self):
        for chave,valor in [('requerimento','99999/25'),('tipo_produto','Outro'),('certificado','OUTRO'),('modelo','SM-X999'),('contexto',{})]:
            with self.subTest(chave=chave):
                self.adapter=AdaptadorFalso();self.adapter.inicial['identidade'][chave]=valor
                r=self.rodar()
                self.assertEqual(r['status'],'interrompido_sem_retry')
                self.assertEqual(self.adapter.chamadas,[])

    def test_ausencia_autorizacao_nao_le_nem_escreve(self):
        r=self.rodar(obter_autorizacao=None)
        self.assertEqual(self.adapter.contagens,0)
        self.assertEqual(self.adapter.chamadas,[])
        self.assertTrue(r['falhas'])

    def test_autorizacao_invalida_ou_ampliada(self):
        for chave,valor in [('autorizado',False),('referencia_institucional',''),('operador',''),
                            ('requerimento','00001/25'),('acoes',['aprovar']),('texto','outra'),
                            ('valida_ate','2020-01-01T00:00:00+00:00'),('valida_ate','2099-01-01')]:
            with self.subTest(chave=chave):
                a=autorizacao();a[chave]=valor
                r=self.rodar(obter_autorizacao=lambda:a)
                self.assertTrue(r['falhas'])
                self.assertEqual(self.adapter.chamadas,[])

    def test_conteudo_inesperado_nao_e_sobrescrito(self):
        self.adapter.inicial['texto']='Conteúdo de outro operador'
        r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_checkbox_ja_marcado_cancela_sem_tentar_desmarcar(self):
        self.adapter.inicial['marcado']=True
        r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_campo_sem_vinculo_cancela(self):
        self.adapter.inicial['vinculo_confirmado']=False
        self.rodar();self.assertEqual(self.adapter.chamadas,[])

    def test_datas_cct_divergentes_sao_registradas_sem_alteracao(self):
        self.base['datas_sch']={'data_certificado':'06/03/2025','data_validade':'06/03/2029'}
        self.adapter.inicial['identidade'].update(self.base['datas_sch'])
        r=self.rodar()
        self.assertEqual(r['status'],'confirmado_apos_releitura_servidor')
        self.assertEqual(r['depois']['identidade']['data_certificado'],'06/03/2025')
        self.adapter=AdaptadorFalso();self.adapter.inicial['identidade'].update(self.base['datas_sch'])
        self.adapter.inicial['identidade']['data_certificado']='04/09/2026'
        r=self.rodar(trava=self.pasta/'outra.json')
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_reserva_impede_concorrencia_mesmo_com_outro_diretorio_de_relatorio(self):
        self.rodar()
        self.adapter=AdaptadorFalso()
        a=autorizacao()
        r=t.executar(self.adapter,self.base,self.pasta/'outro',executar_real=True,
                     obter_autorizacao=lambda:a,confirmar=lambda _:t.CONFIRMACAO,
                     trava=self.pasta/'trava.json',ambiente='testes_automatizados')
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_confirmacao_exata_obrigatoria(self):
        for resposta in ('sim','Pronto','',t.CONFIRMACAO.lower()):
            r=self.rodar(confirmar=lambda _:resposta)
            self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_mudanca_durante_confirmacao_bloqueia(self):
        def alterar(_):
            self.adapter.inicial['campos_preservados']['inferior']='mudou'
            return t.CONFIRMACAO
        r=self.rodar(confirmar=alterar)
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_autorizacao_revogada_apos_confirmar(self):
        a=autorizacao()
        def revogar(_):a['autorizado']=False;return t.CONFIRMACAO
        r=self.rodar(obter_autorizacao=lambda:copy.deepcopy(a),confirmar=revogar)
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_falhas_nao_repetem_nem_revertem_escrita(self):
        for etapa in ('texto','checkbox','conferir','salvar','reload'):
            with self.subTest(etapa=etapa):
                self.adapter=AdaptadorFalso();self.adapter.falha=etapa
                r=self.rodar(trava=self.pasta/(etapa+'.json'))
                self.assertTrue(r['falhas'])
                self.assertLessEqual(self.adapter.chamadas.count('salvar'),1)
                self.assertEqual(self.adapter.chamadas[-1],etapa)
                self.assertTrue((self.pasta/(etapa+'.json')).exists())

    def test_confirmacao_posterior_exige_os_dois_valores(self):
        for texto,marcado in [('',True),(t.FRASE,False),('outro',True)]:
            self.adapter=AdaptadorFalso();self.adapter.apos=dict(estado(),texto=texto,marcado=marcado)
            r=self.rodar(trava=self.pasta/(str(marcado)+str(len(texto))+'.json'))
            self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas.count('salvar'),1)

    def test_mudanca_de_qualquer_outro_campo_interrompe_sem_retry(self):
        for campo in estado()['campos_preservados']:
            self.adapter=AdaptadorFalso();apos=dict(estado(),texto=t.FRASE,marcado=True)
            apos['campos_preservados'][campo]='alteração inesperada'
            self.adapter.apos=apos
            r=self.rodar(trava=self.pasta/(campo+'.json'))
            self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas.count('salvar'),1)

    def test_nova_execucao_mesma_reserva_bloqueada(self):
        self.rodar()
        self.adapter=AdaptadorFalso()
        r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])
        self.assertIn('FileExistsError',r['falhas'][0])

    def test_reserva_e_relatorio_persistem_quando_salvamento_falha(self):
        self.adapter.falha='salvar';r=self.rodar()
        salvo=json.loads((self.pasta/'resultado.json').read_text(encoding='utf-8'))
        self.assertEqual(salvo,r)
        self.assertTrue(r['salvamento']['tentativa_iniciada'])
        self.assertTrue(r['estado_servidor_indeterminado'])
        self.assertTrue((self.pasta/'trava.json').exists())

    def test_interrupcao_manual_preserva_reserva_e_estado_indeterminado(self):
        with patch.object(self.adapter,'salvar_uma_vez',side_effect=KeyboardInterrupt()):
            r=self.rodar()
        self.assertIn('KeyboardInterrupt',r['falhas'][0])
        self.assertTrue(r['estado_servidor_indeterminado'])
        self.assertTrue((self.pasta/'trava.json').exists())

    def test_adaptador_real_nao_expoe_retry_de_salvar(self):
        adapter=object.__new__(t.SeleniumRestrito)
        adapter._SeleniumRestrito__habilitado=False
        adapter._SeleniumRestrito__consumidos=set()
        with self.assertRaises(t.Cancelado):adapter._consumir('salvar')
        adapter._SeleniumRestrito__habilitado=True
        adapter._consumir('salvar')
        with self.assertRaises(t.Cancelado):adapter._consumir('salvar')

    def test_cli_outro_requerimento_bloqueia_antes_de_conectar(self):
        args=['cmd','--requerimento','00001/25','--simulacao','x','--sha256-simulacao','x',
              '--debugger-address','127.0.0.1:1','--caminho-driver','x','--saida',str(self.pasta)]
        with patch.object(sys,'argv',args),patch('navegador.criar_driver') as criar:
            self.assertEqual(t.main(),1)
        criar.assert_not_called()

    def test_relatorio_html_escapa_dados_e_identifica_ambiente(self):
        self.adapter.inicial['texto']='<script>teste</script>'
        r=self.rodar()
        texto=(self.pasta/'resultado.html').read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;',texto)
        self.assertIn('testes_automatizados',texto)
        self.assertNotIn('<script>teste',texto)

    def test_baseline_real_e_modelo_autorizacao_nao_autorizado(self):
        raiz=Path(__file__).resolve().parents[1]
        caminho=raiz/'diagnostico_sch/correcoes_finais_01553_25/simulacao_opcao4.json'
        if not caminho.exists():self.skipTest('artefato autenticado ausente')
        r=t.validar_simulacao(t.ler_json(caminho),t.REQUERIMENTO)
        self.assertEqual(r['texto'],'');self.assertIs(r['marcado'],False)
        with self.assertRaises(t.Cancelado):t.validar_simulacao(t.ler_json(caminho),'00001/25')
        modelo=t.ler_json(raiz/'docs/autorizacao_controlada_01553_25.modelo.json')
        self.assertIs(modelo['autorizado'],False)
        with self.assertRaises(t.Cancelado):t.validar_autorizacao(modelo)

    @unittest.skipUnless(os.environ.get('SCH_TEST_BROWSER')=='1','Selenium local opcional: SCH_TEST_BROWSER=1')
    def test_selenium_local_vinculo_mutacoes_restritas_e_um_clique(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        raiz=Path(__file__).resolve().parents[1]
        browser=raiz/'diagnostico_sch/drivers/chrome-win64/chrome.exe'
        driver_path=raiz/'diagnostico_sch/drivers/chromedriver-win64/chromedriver.exe'
        if not browser.exists() or not driver_path.exists():self.skipTest('binários locais ausentes')
        options=webdriver.ChromeOptions();options.binary_location=str(browser)
        for flag in ('--headless=new','--disable-gpu','--disable-background-networking','--no-first-run'):options.add_argument(flag)
        driver=webdriver.Chrome(service=Service(str(driver_path)),options=options)
        try:
            pagina=self.pasta/'local.html'
            pagina.write_text('''<meta charset="utf-8"><script>window.salvamentos=0;window.proibidos=0;</script>
<form><div id="formAnalise:acompanharProcessoPanel"><label for="cb">Desejo acompanhar este processo.</label>
<input id="cb" type="checkbox"><textarea id="texto"></textarea></div>
<textarea id="inferior">não alterar inferior</textarea><textarea id="observacao">correta</textarea>
<input id="data" value="06/03/2025"><div>Especificações Complementares SAR aplicável</div>
<table><tr><td>2400 a 2483,5</td><td>0,0033</td></tr></table>
<button id="save" type="button" onclick="window.salvamentos++;document.getElementById('msg').innerText='Salvo com sucesso';">Salvar</button>
<button type="button" onclick="window.proibidos++">Aprovar</button>
<button type="button" onclick="window.proibidos++">Recusar</button><div id="msg" role="alert"></div></form>''',encoding='utf-8')
            driver.get(pagina.as_uri())
            adapter=t.SeleniumRestrito(driver,WebDriverWait(driver,3),self.pasta)
            # Somente o adaptador deste documento file:// é habilitado pelo
            # teste. Não há conexão ao navegador autenticado nem ao SCH.
            def contexto_local():self.assertEqual(driver.current_url,pagina.as_uri())
            adapter._contexto=contexto_local
            adapter._SeleniumRestrito__habilitado=True
            superior=adapter.guard.envolver(driver.find_element(By.ID,'texto'))
            checkbox=adapter.guard.envolver(driver.find_element(By.ID,'cb'))
            inferior=adapter.guard.envolver(driver.find_element(By.ID,'inferior'))
            with patch.object(t.s,'_localizar_textarea_acompanhar_processo',return_value=superior),patch.object(t.s,'_localizar_checkbox_acompanhar_processo',return_value=checkbox):
                _,_,_,vinculo=adapter._controles()
                antes={'vinculo':vinculo,'campos_preservados':{'informacoes_adicionais':adapter._inventario(('texto','cb'))}}
                adapter.preencher_superior(antes,t.FRASE)
                adapter.marcar_checkbox(antes)
                adapter.conferir_pendente(antes,t.FRASE)
                self.assertIn('sucesso',adapter.salvar_uma_vez())
                with self.assertRaises(t.Cancelado):adapter.salvar_uma_vez()
                self.assertEqual(adapter._inventario(('texto','cb')),antes['campos_preservados']['informacoes_adicionais'])
                with patch.object(t.s,'_localizar_textarea_acompanhar_processo',return_value=inferior):
                    with self.assertRaises(t.Cancelado):adapter._controles()
                driver.execute_script('arguments[0].id="texto";',driver.find_element(By.ID,'inferior'))
                with self.assertRaises(t.Cancelado):adapter._controles()
                driver.execute_script('arguments[0].id="inferior";',adapter.guard.desembrulhar(inferior))
            self.assertEqual(driver.execute_script('return window.salvamentos'),1)
            self.assertEqual(driver.execute_script('return window.proibidos'),0)
            self.assertEqual(driver.find_element(By.ID,'texto').get_attribute('value'),t.FRASE)
            self.assertTrue(driver.find_element(By.ID,'cb').is_selected())
            self.assertEqual(driver.find_element(By.ID,'inferior').get_attribute('value'),'não alterar inferior')
        finally:
            driver.quit()  # Somente o headless criado pelo teste local.


if __name__=='__main__':unittest.main()
