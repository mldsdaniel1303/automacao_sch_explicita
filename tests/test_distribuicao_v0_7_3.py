from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import main as entrada
import verificacao_pacote as verificar


class DistribuicaoTests(unittest.TestCase):
    def test_menu_mantem_quatro_opcoes_e_sair_sem_fluxo(self):
        saida=StringIO()
        with patch.object(entrada,'limpar_tela'),redirect_stdout(saida),patch.object(entrada,'perguntar_opcao',return_value='0'),patch.object(entrada,'executar_fluxo_sch') as sch:
            self.assertEqual(entrada.main(),0)
        menu=saida.getvalue()
        self.assertIn('v0.7.3-testes',menu)
        for texto in ('1. Processar','2. Analisar','3. Retorno','4. Retorno','0. Sair'):self.assertIn(texto,menu)
        self.assertNotIn('5.',menu)
        self.assertNotIn('validacao_ajax_supervisionada',menu)
        self.assertNotIn('teste_controlado_acompanhar',menu)
        sch.assert_not_called()

    def test_flag_offline_nao_entra_no_menu_nem_espera_input(self):
        import fluxo_sch
        with patch.object(sys,'argv',['main.py','--verificar-pacote','--saida','x.json']),patch.object(verificar,'verificar_cli',return_value=0) as offline,patch.object(fluxo_sch,'executar_fluxo_sch') as sch,patch('builtins.input',side_effect=AssertionError('Não deve pedir input no autoteste')):
            with self.assertRaises(SystemExit) as sair:
                runpy.run_path(entrada.__file__,run_name='__main__')
        self.assertEqual(sair.exception.code,0)
        offline.assert_called_once_with(['--saida','x.json']);sch.assert_not_called()

    def test_autoteste_pdf_real_e_configuracao_sem_navegador(self):
        with patch('navegador.criar_driver') as navegador,redirect_stdout(StringIO()):
            r=verificar.verificar()
        self.assertEqual(r['status'],'ok',r.get('falhas'))
        self.assertEqual(r['pdf_nativo'],'ok')
        self.assertTrue(all(r['configuracao'].values()))
        self.assertIn('extracao_cct',r['modulos']);self.assertIn('pymupdf',r['modulos'])
        navegador.assert_not_called()

    def test_autoteste_tres_ccts_inclui_carregador_sem_rf(self):
        pasta=Path(__file__).resolve().parents[1]/'tests/fixtures/ccts'
        if not (pasta/'CPQD-i_12407_NOV_00A X.pdf').is_file():
            self.skipTest('Teste local: PDFs reais privados ausentes.')
        with patch('navegador.criar_driver') as navegador,redirect_stdout(StringIO()):
            r=verificar.verificar(pasta)
        self.assertEqual(r['status'],'ok',r.get('falhas'))
        self.assertEqual(len(r['ccts']),3)
        moderna=next(c for c in r['ccts'] if '13048' in c['arquivo'])
        self.assertEqual(moderna['diagnostico'],'sem_tabela_rf')
        self.assertEqual(moderna['linhas'],0)
        self.assertEqual(r['comparacao_cpqd_fixture']['resumo']['linhas_ambiguas'],18)
        self.assertFalse(r['sar_cpqd']['preencher_frase'])
        navegador.assert_not_called()


if __name__=='__main__':unittest.main()
