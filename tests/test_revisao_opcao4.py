import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import controles_acompanhar as c
import funcoes_sch as sch
from diagnostico_estrutura_sch import separar_tabelas_comparaveis


class RevisaoTests(unittest.TestCase):
    def executar(self, anterior='Outro', depois='Frase', marcado=True, falha=None, inventarios=None):
        driver, wait, cb, campo, botao = (Mock() for _ in range(5))
        cb.is_selected.return_value = True
        campo.get_attribute.side_effect = [anterior, anterior, 'Frase']
        driver.execute_script.return_value = {'valido': True}
        if falha == 'salvar': botao.click.side_effect = RuntimeError('resposta incerta')
        with contextlib.ExitStack() as st:
            for nome in ('clicar_aba_informacoes_adicionais','entrar_iframe_detalhe_analise'):
                st.enter_context(patch.object(sch, nome))
            st.enter_context(patch.object(c, 'aguardar_ajax'))
            st.enter_context(patch.object(c, 'ler_controles', return_value=(cb, campo)))
            st.enter_context(patch.object(c, 'marcar_visual', return_value=campo))
            st.enter_context(patch.object(c, 'inventario_preservado', side_effect=inventarios or [[], [], []]))
            st.enter_context(patch.object(sch, '_achar_primeiro_elemento_visivel', return_value=botao))
            releitura=st.enter_context(patch.object(c, 'reler_apos_salvar',
                return_value={'texto':depois,'marcado':marcado,'reabertura_confirmada':True}))
            if falha == 'releitura': releitura.side_effect = RuntimeError('sem nova renderizacao')
            with contextlib.redirect_stdout(io.StringIO()):
                r=c.executar_acompanhamento_opcao4(driver, wait, 'Frase')
        return r, campo, botao

    def test_persistencia_exige_valor_exato_checkbox_e_demais_campos(self):
        for anterior, depois, marcado, ok in [('Outro','Frase',True,True),
                ('Frase','Frase',True,True),('Outro','Outro Frase',True,False),
                ('Outro','Frase',False,False)]:
            with self.subTest(depois=depois, marcado=marcado):
                r, campo, botao=self.executar(anterior, depois, marcado)
                self.assertEqual(r['confirmado_apos_salvar'], ok)
                self.assertEqual(r['salvo'], ok)
                botao.click.assert_called_once()
                self.assertEqual(campo.clear.called, anterior!='Frase')

    def test_sem_retry_apos_salvar_ou_releitura_incerta(self):
        for falha in ('salvar','releitura'):
            r, _, botao=self.executar(falha=falha)
            self.assertFalse(r['confirmado_apos_salvar'])
            self.assertTrue(r['estado_servidor_indeterminado'])
            self.assertEqual(r['tentativas_salvamento'], 1)
            botao.click.assert_called_once()

    def test_mudanca_outro_campo_bloqueia_salvar(self):
        r, _, botao=self.executar(inventarios=[[], [{'id':'formAnalise:descricao','valor':'alterado'}]])
        botao.click.assert_not_called()
        self.assertEqual(r['tentativas_salvamento'], 0)

    def test_sem_recriacao_nao_confirma_persistencia(self):
        with patch.object(sch,'clicar_aba_dados_gerais'), patch.object(sch,'clicar_aba_informacoes_adicionais'), patch.object(sch,'entrar_iframe_detalhe_analise'), patch.object(c,'aguardar_ajax'):
            wait=Mock(); wait.until.side_effect=RuntimeError('elemento antigo ainda presente')
            with self.assertRaises(RuntimeError): c.reler_apos_salvar(Mock(), wait, Mock())

    def test_checkbox_oculto_nunca_recebe_clique(self):
        driver, wait, cb, campo, visual=(Mock() for _ in range(5))
        cb.is_selected.side_effect=[False, True]
        visual.is_displayed.return_value=True; visual.is_enabled.return_value=True
        driver.execute_script.return_value={'valido':True,'caixa':visual}
        wait.until.side_effect=lambda fn, **kw: fn(driver)
        with patch.object(c,'ler_controles',return_value=(cb,campo)), patch.object(c,'aguardar_ajax'), patch('utils._ajax_primefaces_pronto',return_value=True):
            self.assertIs(c.marcar_visual(driver,wait),campo)
        visual.click.assert_called_once(); cb.click.assert_not_called()

    def test_interceptado_nao_dispara_fallback(self):
        driver, cb, visual=(Mock() for _ in range(3)); cb.is_selected.return_value=False
        driver.execute_script.return_value={'valido':True,'caixa':visual}
        visual.click.side_effect=RuntimeError('intercepted')
        with patch.object(c,'ler_controles',return_value=(cb,None)):
            with self.assertRaises(RuntimeError): c.marcar_visual(driver,Mock())
        visual.click.assert_called_once(); cb.click.assert_not_called()
        self.assertFalse(any('click()' in str(x) for x in driver.execute_script.call_args_list))

    def test_descarta_tabela_vazia_e_layout(self):
        aceitas, descartadas=separar_tabelas_comparaveis([
            {'cabecalho':['Frequência','Potência'],'total_linhas':35},
            {'cabecalho':['SAR','Observação'],'total_linhas':0},
            {'cabecalho':['Menu','Ações'],'total_linhas':2}])
        self.assertEqual(len(aceitas),1); self.assertEqual(len(descartadas),2)
        self.assertEqual(aceitas[0]['total_linhas'],35)

    def test_descricao_inferior_rejeitada(self):
        driver, cb, inferior=(Mock() for _ in range(3))
        driver.find_elements.side_effect=[[cb],[Mock()],[Mock()],[Mock()],[inferior]]
        driver.execute_script.side_effect=[{'checkbox_no_painel':True,'textAreaPanel':'painel',
            'textareas':['formAnalise:descricao'],'outros_controles':[]},False]
        with self.assertRaises(RuntimeError): c.ler_controles(driver)

    def test_captura_completa_preserva_35_linhas_e_rejeita_incompletude(self):
        import copy
        import diagnostico_estrutura_sch as diag
        raiz=Path(__file__).resolve().parents[1]
        fixture=json.loads((raiz/'tests/fixtures/ccts/sch_cpqd_transcricao_capturas.json').read_text(encoding='utf-8'))
        tab=dict(fixture,total_linhas=35,total_colunas=6)
        for alteracao, ok in [({},True),({'total_linhas':0},False),
                ({'paginacao_detectada':[{}]},False),({'virtualizacao_detectada':True},False),
                ({'total_linhas_aria':'100'},False),({'linhas':[['incompleta']]},False)]:
            with self.subTest(alteracao=alteracao), patch.object(sch,'clicar_aba_caracteristicas_tecnicas'), patch.object(sch,'entrar_iframe_detalhe_analise'), patch.object(c,'aguardar_ajax'):
                candidata=copy.deepcopy(tab); candidata.update(alteracao)
                driver=Mock(); driver.execute_script.return_value={'pronto':True,'tabelas':[candidata,{'total_linhas':0,'cabecalho':['Recusar','SAR']} ]}
                if ok:
                    capturada=diag.extrair_tabela_dom_para_comparacao(driver,Mock())
                    self.assertEqual(capturada['linhas'],fixture['linhas'])
                    self.assertEqual(len(capturada['linhas']),35)
                else:
                    with self.assertRaises(RuntimeError): diag.extrair_tabela_dom_para_comparacao(driver,Mock())

    @unittest.skipUnless(os.environ.get('SCH_TEST_BROWSER')=='1','HTML local: SCH_TEST_BROWSER=1')
    def test_dom_local_widget_ajax_painel_e_tabela_de_layout(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait
        from diagnostico_estrutura_sch import _SCRIPT_LER_ESTRUTURAS
        raiz=Path(__file__).resolve().parents[1]
        opts=webdriver.ChromeOptions()
        opts.binary_location=str(raiz/'diagnostico_sch/drivers/chrome-win64/chrome.exe')
        for flag in ('--headless=new','--disable-background-networking','--no-first-run'): opts.add_argument(flag)
        driver=webdriver.Chrome(service=Service(str(raiz/'diagnostico_sch/drivers/chromedriver-win64/chromedriver.exe')),options=opts)
        self.addCleanup(driver.quit)
        with tempfile.TemporaryDirectory() as pasta:
            pagina=Path(pasta)/'teste.html'
            pagina.write_text('''<meta charset="utf-8"><form>
<div id="formAnalise:acompanharProcessoPanel">
<div id="formAnalise:checkBoxAcompanharProcesso"><input style="position:absolute;left:-9999px" type="checkbox" id="formAnalise:checkBoxAcompanharProcesso_input">
<div class="ui-chkbox-box" style="width:40px;height:40px;border:1px solid">Marcar</div></div>
Desejo acompanhar este processo.<div id="formAnalise:textAreaPanel"></div></div>
<textarea id="formAnalise:descricao">inferior intacto</textarea>
<table><tr><td><table><tr><th>Frequencia</th><th>Potencia</th></tr><tr><td>2400</td><td>0,3</td></tr></table></td><td>Recusar</td></tr></table>
</form><script>
window.jQuery={active:0};window.PrimeFaces={ajax:{Queue:{isEmpty:()=>jQuery.active===0}}};
document.querySelector('.ui-chkbox-box').onclick=()=>{document.getElementById('formAnalise:checkBoxAcompanharProcesso_input').checked=true;jQuery.active=1;
setTimeout(()=>{document.getElementById('formAnalise:textAreaPanel').innerHTML='<textarea id="superior">valor real servidor simulado</textarea>';jQuery.active=0;},120)};
</script>''',encoding='utf-8')
            driver.get(pagina.as_uri())
            self.assertIsNone(c.ler_controles(driver)[1])
            campo=c.marcar_visual(driver,WebDriverWait(driver,3))
            self.assertEqual(campo.get_attribute('value'),'valor real servidor simulado')
            self.assertEqual(driver.find_element('id','formAnalise:descricao').get_attribute('value'),'inferior intacto')
            bruto=driver.execute_script(_SCRIPT_LER_ESTRUTURAS)
            self.assertEqual(len(bruto['tabelas']),1)
            self.assertEqual(bruto['tabelas'][0]['colunas'],2)
            self.assertEqual(bruto['tabelas'][0]['total_linhas'],1)
            driver.execute_script("document.getElementById('formAnalise:textAreaPanel').innerHTML='<textarea id=duplicado></textarea><textarea id=outro></textarea>'")
            with self.assertRaises(RuntimeError): c.ler_controles(driver)


if __name__=='__main__': unittest.main()
