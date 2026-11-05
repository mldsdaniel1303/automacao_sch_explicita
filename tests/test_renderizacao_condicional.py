import copy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import teste_controlado_acompanhar as t
from test_controlado_acompanhar import AdaptadorFalso,estado,autorizacao

CALLBACK="function(event) {PrimeFaces.ab({source:'formAnalise:checkBoxAcompanharProcesso',event:'change',process:'formAnalise:checkBoxAcompanharProcesso',update:'formAnalise:textAreaPanel'}, arguments[1]);}"


def evidencia():
    from hashlib import sha256
    return {'callback_change':CALLBACK,'sha256_callback':sha256(CALLBACK.encode()).hexdigest(),
            'vinculo_ajax_confirmado':True,'handler_executado':False}


class CondicionalFalso(AdaptadorFalso):
    def __init__(self):
        super().__init__()
        self.inicial.update(texto=None,renderizacao_condicional=True,evidencia_ajax=evidencia(),vinculo_confirmado=False,
            vinculo={'textoId':None,'checkboxId':'cb','salvarId':None,'valido':False,'status':'campo_superior_nao_renderizado'})
        self.valor_renderizado='';self.nao_aparece=False
    def marcar_e_aguardar_superior(self,antes):
        self._acao('checkbox_ajax')
        if self.nao_aparece:raise t.Cancelado('Não apareceu textarea após AJAX')
        alvo=estado();alvo.update(texto=self.valor_renderizado,marcado=True,renderizado_apos_marcacao=True)
        self.diagnostico_renderizacao={'texto_real':self.valor_renderizado,'marcado':True}
        if self.valor_renderizado:raise t.Cancelado('Valor real não vazio')
        return alvo
    def coletar(self):
        if 'reload' in self.chamadas:
            if self.apos is not None:return copy.deepcopy(self.apos)
            return dict(estado(),texto=t.FRASE,marcado=True)
        return super().coletar()


class RenderizacaoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pasta=Path(self.temp.name)
        self.adapter=CondicionalFalso();self.baseline={'texto':'','marcado':False}
    def rodar(self,**kw):
        a=autorizacao();a['permitir_renderizacao_condicional']=True
        args={'executar_real':True,'obter_autorizacao':lambda:copy.deepcopy(a),
              'confirmar':lambda _:t.CONFIRMACAO_CONDICIONAL,'trava':self.pasta/'reserva.json',
              'ambiente':'testes_automatizados'}
        args.update(kw)
        return t.executar(self.adapter,self.baseline,self.pasta,**args)

    def test_callback_observado_e_alvo_exato_sem_aceitar_outros_comandos(self):
        self.assertTrue(t.vinculo_ajax_confirmado(CALLBACK))
        self.assertTrue(t.vinculo_ajax_confirmado(CALLBACK.replace("'",'"')))
        for codigo in (CALLBACK.replace('textAreaPanel','descricao'),CALLBACK.replace("event:'change'","event:'click'"),
                       CALLBACK.replace('process:', 'outro:'),CALLBACK.replace('}', ';evil();}',1)):
            self.assertFalse(t.vinculo_ajax_confirmado(codigo))

    def test_preparacao_condicional_preserva_valor_desconhecido_sem_marcar(self):
        r=t.executar(self.adapter,self.baseline,self.pasta)
        self.assertEqual(r['status'],'preparado_condicional_sem_gravacao')
        self.assertIsNone(r['antes']['texto']);self.assertEqual(self.adapter.chamadas,[])
        self.assertFalse((self.pasta/'reserva.json').exists())

    def test_relacao_nao_comprovada_mantem_bloqueio(self):
        self.adapter.inicial['evidencia_ajax']['callback_change']=CALLBACK.replace('textAreaPanel','outro')
        r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_autorizacao_anterior_nao_habilita_ordem_condicional(self):
        a=autorizacao()
        r=self.rodar(obter_autorizacao=lambda:a)
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_confirmacao_antiga_nao_habilita_marcacao_previa(self):
        r=self.rodar(confirmar=lambda _:t.CONFIRMACAO)
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_sequencia_condicional_uma_marcacao_antes_do_preenchimento(self):
        r=self.rodar()
        self.assertEqual(r['status'],'confirmado_apos_releitura_servidor')
        self.assertEqual(self.adapter.chamadas,['habilitar','checkbox_ajax','texto','conferir','salvar','reload'])
        self.assertEqual(r['apos_renderizacao']['texto'],'')
        self.assertEqual(r['confirmacao_operador']['frase'],t.CONFIRMACAO_CONDICIONAL)
        self.assertTrue((self.pasta/'reserva.json').exists())

    def test_sem_textarea_cancela_sem_salvar_e_sem_repetir(self):
        self.adapter.nao_aparece=True
        r=self.rodar()
        self.assertEqual(self.adapter.chamadas,['habilitar','checkbox_ajax'])
        self.assertFalse(r['salvamento']['tentativa_iniciada']);self.assertTrue(r['estado_servidor_indeterminado'])
        self.assertTrue((self.pasta/'reserva.json').exists())
        self.adapter=CondicionalFalso()
        r=self.rodar();self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_conteudo_real_nao_vazio_e_registrado_e_preservado(self):
        self.adapter.valor_renderizado='Existente — não sobrescrever'
        r=self.rodar()
        self.assertEqual(r['apos_renderizacao']['texto_real'],self.adapter.valor_renderizado)
        self.assertNotIn('texto',self.adapter.chamadas);self.assertNotIn('salvar',self.adapter.chamadas)
        self.assertTrue(r['estado_servidor_indeterminado'])

    def test_checkbox_marcado_inicial_ou_identidade_divergente_nao_e_condicao_legitima(self):
        for chave,valor in [('marcado',True),('texto','Existente')]:
            self.adapter=CondicionalFalso();self.adapter.inicial[chave]=valor
            r=self.rodar();self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas,[])

    def test_falha_pos_salvar_nao_tenta_nova_marcacao_ou_gravacao(self):
        self.adapter.apos=dict(estado(),texto='',marcado=False)
        r=self.rodar()
        self.assertTrue(r['falhas']);self.assertEqual(self.adapter.chamadas.count('salvar'),1)
        self.assertEqual(self.adapter.chamadas.count('checkbox_ajax'),1)

    def test_outros_campos_preservados_com_valor_condicional(self):
        apos=dict(estado(),texto=t.FRASE,marcado=True)
        apos['campos_preservados']['inferior']='alterado'
        self.adapter.apos=apos
        r=self.rodar();self.assertTrue(r['falhas'])
        self.assertEqual(self.adapter.chamadas.count('salvar'),1)

    def test_leitura_da_closure_nao_executa_handler_e_libera_objetos(self):
        a=object.__new__(t.SeleniumRestrito);a._contexto=Mock();d=Mock()
        a._SeleniumRestrito__driver=d
        def cdp(cmd,args):
            if cmd=='Runtime.evaluate':return {'result':{'objectId':'fn'}}
            if cmd=='Runtime.releaseObjectGroup':return {}
            self.assertEqual(cmd,'Runtime.getProperties')
            return {'fn':{'internalProperties':[{'name':'[[Scopes]]','value':{'objectId':'scopes'}}]},
                    'scopes':{'result':[{'value':{'description':'Closure','objectId':'closure'}}]},
                    'closure':{'result':[{'name':'c','value':{'type':'function','description':CALLBACK}}]}}[args['objectId']]
        d.execute_cdp_cmd.side_effect=cdp
        r=a._ler_callback_change()
        self.assertTrue(r['vinculo_ajax_confirmado']);self.assertFalse(r['handler_executado'])
        d.execute_script.assert_not_called()
        self.assertEqual(d.execute_cdp_cmd.call_args.args[0],'Runtime.releaseObjectGroup')

    @unittest.skipUnless(os.environ.get('SCH_TEST_BROWSER')=='1','HTML local opcional: SCH_TEST_BROWSER=1')
    def test_selenium_local_renderiza_apos_ajax_sem_usar_descricao_inferior(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        raiz=Path(__file__).resolve().parents[1]
        browser=raiz/'diagnostico_sch/drivers/chrome-win64/chrome.exe'
        driver_path=raiz/'diagnostico_sch/drivers/chromedriver-win64/chromedriver.exe'
        if not browser.exists() or not driver_path.exists():self.skipTest('binários de teste ausentes')
        opts=webdriver.ChromeOptions();opts.binary_location=str(browser)
        for flag in ('--headless=new','--disable-background-networking','--no-first-run'):opts.add_argument(flag)
        d=webdriver.Chrome(service=Service(str(driver_path)),options=opts)
        try:
            pagina=self.pasta/'fixture_condicional.html'
            pagina.write_text('''<meta charset="utf-8"><form>
<span id="formAnalise:acompanharProcessoPanel"><b>Acompanhar Processo</b>
<div id="formAnalise:checkBoxAcompanharProcesso"><input id="formAnalise:checkBoxAcompanharProcesso_input" type="checkbox">
<div class="ui-chkbox-box" style="width:30px;height:30px;border:1px solid">Marcar</div></div>
<label for="formAnalise:checkBoxAcompanharProcesso">Desejo acompanhar este processo.</label>
<span id="formAnalise:textAreaPanel"></span></span>
<textarea id="formAnalise:descricao">inferior preservado</textarea><textarea id="ocd">Justificativa OCD</textarea>
<input id="data" value="06/03/2025"><table><tr><td>Dados técnicos preservados</td></tr></table>
<button type="button" id="save" onclick="window.salvos++;document.getElementById('msg').innerText='Salvo com sucesso'">Salvar</button><span id="msg" role="alert"></span></form>
<script>window.salvos=0;window.requisicoes=[];window.jQuery={active:0,_data:(el)=>({change:el.id==='formAnalise:checkBoxAcompanharProcesso_input'?[{handler:window.handler}]:[]})};
window.PrimeFaces={ajax:{Queue:{isEmpty:()=>jQuery.active===0}},ab:cfg=>{window.requisicoes.push(cfg);jQuery.active=1;setTimeout(()=>{if(document.getElementById('formAnalise:checkBoxAcompanharProcesso_input').checked&&window.modo!=='ausente'){let t=document.createElement('textarea');t.id='superiorRenderizado';t.value=window.valorInicial||'';document.getElementById(cfg.update).appendChild(t);if(window.modo==='duplo'){let extra=document.createElement('textarea');extra.id='outro';document.getElementById(cfg.update).appendChild(extra)}if(window.modo==='outro_campo'){document.getElementById('ocd').value='alterado pela fixture'}}jQuery.active=0;},30)}};
(function(){let b={},c=function(event) {PrimeFaces.ab({source:'formAnalise:checkBoxAcompanharProcesso',event:'change',process:'formAnalise:checkBoxAcompanharProcesso',update:'formAnalise:textAreaPanel'}, arguments[1]);};window.handler=function(f){c.call(b,f)};})();
const cb=document.getElementById('formAnalise:checkBoxAcompanharProcesso_input');cb.addEventListener('change',window.handler);
document.querySelector('.ui-chkbox-box').addEventListener('click',()=>{cb.checked=!cb.checked;cb.dispatchEvent(new Event('change'))});
</script>''',encoding='utf-8')
            d.get(pagina.as_uri())
            a=t.SeleniumRestrito(d,WebDriverWait(d,3),self.pasta)
            a._contexto=lambda:self.assertEqual(d.current_url,pagina.as_uri())
            a._SeleniumRestrito__habilitado=True;a._SeleniumRestrito__condicional=True
            cb=a.guard.envolver(d.find_element(By.ID,'formAnalise:checkBoxAcompanharProcesso_input'))
            def localizar(*args,**kw):return a.guard.envolver(d.find_element(By.ID,'superiorRenderizado'))
            with redirect_stdout(StringIO()),patch.object(t.s,'_localizar_checkbox_acompanhar_processo',return_value=cb),patch.object(t.s,'_localizar_textarea_acompanhar_processo',side_effect=localizar):
                _,_,_,vinculo=a._controles(permitir_painel_sem_textarea=True)
                antes=dict(estado(),texto=None,marcado=False,vinculo=vinculo,vinculo_confirmado=False,
                           renderizacao_condicional=True,evidencia_ajax=a._ler_callback_change(),
                           campos_preservados={'informacoes_adicionais':a._inventario((vinculo['checkboxId'],))})
                self.assertTrue(t.estado_condicional(antes))
                self.assertEqual(d.execute_script('return window.requisicoes.length'),0)
                renderizado=a.marcar_e_aguardar_superior(antes)
                self.assertEqual(renderizado['texto'],'');self.assertTrue(renderizado['marcado'])
                a.preencher_superior(renderizado,t.FRASE)
                a.conferir_pendente(renderizado,t.FRASE)
                a.salvar_uma_vez()
                with self.assertRaises(t.Cancelado):a.marcar_e_aguardar_superior(antes)
                self.assertEqual(d.execute_script('return window.salvos'),1)
                self.assertEqual(d.execute_script('return window.requisicoes.length'),1)
                self.assertEqual(d.find_element(By.ID,'formAnalise:descricao').get_attribute('value'),'inferior preservado')
                self.assertEqual(d.find_element(By.ID,'ocd').get_attribute('value'),'Justificativa OCD')
            for modo in ('ausente','duplo','nao_vazio','outro_campo'):
                with self.subTest(modo=modo):
                    d.get(pagina.as_uri())
                    d.execute_script('window.modo=arguments[0];window.valorInicial=arguments[1];',modo,'Existente' if modo=='nao_vazio' else '')
                    a=t.SeleniumRestrito(d,WebDriverWait(d,1),self.pasta)
                    a._contexto=lambda:self.assertEqual(d.current_url,pagina.as_uri())
                    a._SeleniumRestrito__habilitado=True;a._SeleniumRestrito__condicional=True
                    cb=a.guard.envolver(d.find_element(By.ID,'formAnalise:checkBoxAcompanharProcesso_input'))
                    with redirect_stdout(StringIO()),patch.object(t.s,'_localizar_checkbox_acompanhar_processo',return_value=cb),patch.object(t.s,'_localizar_textarea_acompanhar_processo',side_effect=localizar):
                        _,_,_,vinculo=a._controles(permitir_painel_sem_textarea=True)
                        antes=dict(estado(),texto=None,marcado=False,vinculo=vinculo,vinculo_confirmado=False,
                                   renderizacao_condicional=True,evidencia_ajax=a._ler_callback_change(),
                                   campos_preservados={'informacoes_adicionais':a._inventario((vinculo['checkboxId'],))})
                        motivos={'ausente':'não surgiu','duplo':'múltiplos','nao_vazio':'não está vazio','outro_campo':'alterou campo'}
                        with self.assertRaisesRegex(t.Cancelado,motivos[modo]):a.marcar_e_aguardar_superior(antes)
                    self.assertEqual(d.execute_script('return window.salvos'),0)
                    self.assertEqual(d.execute_script('return window.requisicoes.length'),1)
                    self.assertEqual(d.find_element(By.ID,'formAnalise:descricao').get_attribute('value'),'inferior preservado')
        finally:
            d.quit()  # Encerra apenas a fixture local, nunca o navegador SCH.


if __name__=='__main__':unittest.main()
