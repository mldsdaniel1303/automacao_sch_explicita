import copy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import validacao_ajax_supervisionada as v
import teste_controlado_acompanhar as b
from test_renderizacao_condicional import CondicionalFalso,evidencia


def autorizacao():
    return {'autorizado':True,'ciente_alteracao_estado_sessao':True,'requerimento':b.REQUERIMENTO,
            'acoes':copy.deepcopy(v.ACOES),'referencia_institucional':'FIXTURE SEM VALIDADE INSTITUCIONAL',
            'responsavel_autorizacao':'Fictício','operador':'Fictício',
            'valida_ate':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}


class FalsoSomenteAjax(CondicionalFalso):
    def __init__(self):
        super().__init__();self.valor='';self.falha_ajax=False;self.dom_depois={};self.resposta_ajax={}
        self.dom={'checkbox':{'marcado':False},'textAreaPanel':{'textareas':[]},'inferior':{'sha256_valor':'igual'}}
    def capturar_dom(self):return copy.deepcopy(self.dom)
    def habilitar_observacao(self,*args):self._acao('habilitar_ajax')
    def marcar_e_observar(self,antes):
        self._acao('marcar_ajax')
        self.dom_depois={'checkbox':{'marcado':True},'textAreaPanel':{'textareas':[{'id':'superior','valor':self.valor}]},'inferior':{'sha256_valor':'igual'}}
        self.resposta_ajax={'http_200_novo':True}
        if self.falha_ajax:
            self.dom_depois['textAreaPanel']['textareas']=[]
            raise b.Cancelado('Campo não apareceu')
        resultado=copy.deepcopy(antes);resultado.update(texto=self.valor,vinculo={'textoId':'superior'})
        return resultado
    def preencher_superior(self,*a):raise AssertionError('Preenchimento não pode ser chamado')
    def salvar_uma_vez(self,*a):raise AssertionError('Salvar não pode ser chamado')


class ValidacaoAjaxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pasta=Path(self.temp.name);self.a=FalsoSomenteAjax();self.baseline={'texto':'','marcado':False}
    def rodar(self,**kw):
        auth=autorizacao()
        args={'interagir':True,'autorizacao':lambda:copy.deepcopy(auth),'confirmar':lambda _:v.CONFIRMACAO,
              'trava':self.pasta/'reserva.json','ambiente':'testes_automatizados'}
        args.update(kw)
        return v.executar(self.a,self.baseline,self.pasta,**args)
    def test_padrao_prepara_sem_interagir(self):
        r=v.executar(self.a,self.baseline,self.pasta)
        self.assertEqual(r['status'],'preparado_sem_interacao');self.assertEqual(self.a.chamadas,[])
        self.assertFalse((self.pasta/'reserva.json').exists())
    def test_sucesso_observa_vazio_sem_preencher_ou_salvar(self):
        r=self.rodar()
        self.assertEqual(r['status'],'observado_textarea_vazio')
        self.assertEqual(self.a.chamadas,['habilitar_ajax','marcar_ajax'])
        self.assertFalse(r['salvamento']['tentativa_iniciada']);self.assertFalse(r['preenchimento_permitido'])
        self.assertEqual(r['valor_real_preservado'],'')
        self.assertTrue(r['observacao_ajax_confirmada']);self.assertTrue(r['estado_servidor_indeterminado'])
    def test_conteudo_real_registrado_sem_sobrescrever(self):
        self.a.valor='Conteúdo do servidor'
        r=self.rodar()
        self.assertEqual(r['status'],'observado_com_conteudo_preservado')
        self.assertEqual(r['valor_real_preservado'],self.a.valor)
        self.assertNotIn('salvar',self.a.chamadas)
    def test_autorizacao_de_salvamento_nao_e_aceita(self):
        auth=autorizacao();auth['acoes']=b.ACOES
        r=self.rodar(autorizacao=lambda:auth)
        self.assertTrue(r['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_autorizacao_e_ciencia_obrigatorias(self):
        for chave,valor in [('autorizado',False),('ciente_alteracao_estado_sessao',False),
                            ('referencia_institucional',''),('valida_ate','2020-01-01T00:00:00+00:00')]:
            auth=autorizacao();auth[chave]=valor
            r=self.rodar(autorizacao=lambda:auth)
            self.assertTrue(r['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_confirmacao_antiga_ou_implicita_nao_aceita(self):
        for frase in ('sim','Pronto',b.CONFIRMACAO,b.CONFIRMACAO_CONDICIONAL,''):
            r=self.rodar(confirmar=lambda _:frase)
            self.assertTrue(r['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_outro_requerimento_bloqueia(self):
        self.a.inicial['identidade']['requerimento']='00001/25'
        self.assertTrue(self.rodar()['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_estado_inicial_marcado_bloqueia(self):
        self.a.inicial['marcado']=True
        self.assertTrue(self.rodar()['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_mudanca_durante_confirmacao_bloqueia(self):
        def confirmar(_):self.a.dom['inferior']['sha256_valor']='mudou';return v.CONFIRMACAO
        self.assertTrue(self.rodar(confirmar=confirmar)['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_ausencia_campo_mantem_estado_indeterminado_e_nao_repete(self):
        self.a.falha_ajax=True;r=self.rodar()
        self.assertTrue(r['estado_servidor_indeterminado']);self.assertFalse(r['salvamento']['tentativa_iniciada'])
        self.assertEqual(r['dom_depois']['textAreaPanel']['textareas'],[])
        self.assertTrue((self.pasta/'reserva.json').exists())
        self.a=FalsoSomenteAjax();r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_http_nao_confirmado_nao_e_aprovado_por_dom_apenas(self):
        original=self.a.marcar_e_observar
        def marcar(antes):
            r=original(antes);self.a.resposta_ajax={'http_200_novo':False};return r
        self.a.marcar_e_observar=marcar
        r=self.rodar();self.assertTrue(r['falhas']);self.assertTrue(r['estado_servidor_indeterminado'])
    def test_descricao_inferior_alterada_interrompe_sem_salvar(self):
        original=self.a.marcar_e_observar
        def marcar(antes):
            r=original(antes);self.a.dom_depois['inferior']={'sha256_valor':'mudou'};return r
        self.a.marcar_e_observar=marcar
        r=self.rodar();self.assertTrue(r['falhas']);self.assertNotIn('salvar',self.a.chamadas)
    def test_candidatos_duplicados_sao_registrados_e_recusados(self):
        original=self.a.marcar_e_observar
        def marcar(antes):
            r=original(antes);self.a.dom_depois['textAreaPanel']['textareas'].append({'id':'outro','valor':'Não tocar'});return r
        self.a.marcar_e_observar=marcar
        r=self.rodar();self.assertTrue(r['falhas'])
        self.assertEqual(len(r['dom_depois']['textAreaPanel']['textareas']),2)
        self.assertFalse(r['salvamento']['tentativa_iniciada'])
    def test_checkbox_desmarcado_apos_ajax_nao_aprova(self):
        original=self.a.marcar_e_observar
        def marcar(antes):
            r=original(antes);self.a.dom_depois['checkbox']['marcado']=False;return r
        self.a.marcar_e_observar=marcar
        r=self.rodar();self.assertTrue(r['falhas']);self.assertTrue(r['estado_servidor_indeterminado'])
    def test_autorizacao_mudou_apos_operador_cancela(self):
        auth=autorizacao()
        def confirmar(_):auth['operador']='Outro';return v.CONFIRMACAO
        r=self.rodar(autorizacao=lambda:auth,confirmar=confirmar)
        self.assertTrue(r['falhas']);self.assertEqual(self.a.chamadas,[])
    def test_adaptador_proibe_escrita_mesmo_habilitado(self):
        a=object.__new__(v.SeleniumSomenteAjax)
        a._SeleniumRestrito__habilitado=True;a._SeleniumRestrito__consumidos=set()
        for operacao in (lambda:a.preencher_superior(None,'x'),lambda:a.salvar_uma_vez(),
                         lambda:a.marcar_checkbox(None),lambda:a.recarregar_do_servidor(),
                         lambda:a.habilitar({},{}),lambda:a._consumir('texto'),lambda:a._consumir('salvar')):
            with self.assertRaises(b.Cancelado):operacao()
        a._consumir('checkbox')
        with self.assertRaises(b.Cancelado):a._consumir('checkbox')
    def test_observador_reusa_marcacao_sem_exigir_valor_vazio(self):
        a=object.__new__(v.SeleniumSomenteAjax);a.guard=Mock()
        a.guard.execute_script.side_effect=[{'agora':10,'recursos':[]},
            {'agora':30,'recursos':[{'inicio':11,'caminho':b.CONTEXTO['caminho'],'status':200}]}]
        a.capturar_dom=Mock(return_value={'checkbox':{'marcado':True}})
        with patch.object(b.SeleniumRestrito,'marcar_e_aguardar_superior',return_value={'texto':'Existente'}) as marcar:
            r=a.marcar_e_observar({'inicial':True})
        marcar.assert_called_once_with({'inicial':True},exigir_vazio=False)
        self.assertEqual(r['texto'],'Existente');self.assertTrue(a.resposta_ajax['http_200_novo'])
    def test_recurso_http_antigo_ou_outra_rota_nao_comprova_ajax(self):
        a=object.__new__(v.SeleniumSomenteAjax);a.guard=Mock()
        a.guard.execute_script.side_effect=[{'agora':10,'recursos':[]},{'recursos':[
            {'inicio':5,'caminho':b.CONTEXTO['caminho'],'status':200},
            {'inicio':11,'caminho':'/keepAlive','status':200},
            {'inicio':11,'caminho':b.CONTEXTO['caminho'],'status':0}]}]
        a.capturar_dom=Mock(return_value={})
        with patch.object(b.SeleniumRestrito,'marcar_e_aguardar_superior',return_value={}):a.marcar_e_observar({})
        self.assertFalse(a.resposta_ajax['http_200_novo'])
    def test_cli_outro_requerimento_nao_conecta(self):
        args=['cmd','--requerimento','99999/25','--simulacao','x','--sha256-simulacao','x',
              '--debugger-address','127.0.0.1:1','--caminho-driver','x','--saida',str(self.pasta)]
        with patch.object(sys,'argv',args),patch('navegador.criar_driver') as criar:
            self.assertEqual(v.main(),1)
        criar.assert_not_called()
    def test_modelo_institucional_permanece_desautorizado(self):
        raiz=Path(__file__).resolve().parents[1]
        auth=b.ler_json(raiz/'docs/autorizacao_ajax_01553_25.modelo.json')
        self.assertIs(auth['autorizado'],False)
        with self.assertRaises(b.Cancelado):v.validar_autorizacao(auth)

    @unittest.skipUnless(os.environ.get('SCH_TEST_BROWSER')=='1','Browser local opcional')
    def test_evidencia_http_200_passiva_em_servidor_local(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from threading import Thread
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body=b'<html>Fixture local</html>' if self.path=='/' else b'resposta AJAX local'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        raiz=Path(__file__).resolve().parents[1]
        driver_path=raiz/'diagnostico_sch/drivers/chromedriver-win64/chromedriver.exe'
        browser=raiz/'diagnostico_sch/drivers/chrome-win64/chrome.exe'
        d=None
        try:
            if not browser.exists() or not driver_path.exists():self.skipTest('binários locais ausentes')
            opts=webdriver.ChromeOptions();opts.binary_location=str(browser)
            for f in ('--headless=new','--disable-background-networking','--no-first-run'):opts.add_argument(f)
            d=webdriver.Chrome(service=Service(str(driver_path)),options=opts)
            url=f'http://127.0.0.1:{server.server_address[1]}/';d.get(url)
            self.assertEqual(d.current_url,url)
            antes=d.execute_script(v.SCRIPT_RECURSOS)
            d.execute_async_script("const done=arguments[0],x=new XMLHttpRequest();x.open('GET','/mosaico/sch/worklist/analise/requerimento?nao_logar=token');x.onload=()=>setTimeout(done,0);x.send();")
            depois=d.execute_script(v.SCRIPT_RECURSOS)
            novos=[r for r in depois['recursos'] if r['inicio']>=antes['agora']]
            self.assertEqual(novos[-1]['status'],200)
            self.assertEqual(novos[-1]['caminho'],b.CONTEXTO['caminho'])
            self.assertNotIn('token',json.dumps(depois))
        finally:
            if d:d.quit()  # Somente o Chrome headless local criado neste teste.
            server.shutdown();server.server_close();thread.join(timeout=1)


if __name__=='__main__':unittest.main()
