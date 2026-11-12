import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'automacao_sch_explicita'))
import extracao_cct as e
import pdf_parser as p
import funcoes_sch as s
import gerador_relatorio as g


def tabela(linhas=None, cab=None):
    return {'cabecalho': cab or ['Faixa de Frequências Tx (MHz)', 'Potência Máxima de Saída (W)'],
            'linhas': linhas if linhas is not None else [['2400 a 2483,5', '0,1']]}


class ExtracaoTests(unittest.TestCase):
    def test_cabecalhos_semanticos(self):
        for cab in ['Faixa de Frequências', 'Faixa de Frequências Tx', 'Frequência de Operação', 'Frequency range']:
            self.assertEqual(e.coluna(cab), 'frequencia')
        self.assertEqual(e.coluna('Frequência Inicial'), 'frequencia_inicial')
        self.assertEqual(e.coluna('Frequência Final'), 'frequencia_final')
        self.assertEqual(e.coluna('Potência Média EIRP'), 'potencia_eirp')
        self.assertEqual(e.coluna('Potência Máxima de Saída'), 'potencia_saida')
        self.assertEqual(e.coluna('Potência radiada'), 'nao_interpretado')

    def test_multilinha(self):
        bruto = [['Faixa de Frequências (MHz)', 'Potência'], ['', 'Máxima de'], ['', 'Saída (W)'], ['2400 a 2483,5', '0,1']]
        tabs = e.montar_tabelas([{'pagina': 4, 'bruto': bruto, 'estrategia': 'teste'}])
        self.assertEqual(tabs[0]['cabecalho'][1], 'Potência Máxima de Saída (W)')
        self.assertEqual(tabs[0]['origens_linhas'][0]['linha'], 4)

    def test_colunas_e_linhas_reordenadas(self):
        a = tabela([['2400 a 2483,5', '0,1'], ['900 a 915', '0,2']])
        b = tabela([['0,2', '900 a 915'], ['0,1', '2400 a 2483,5']], list(reversed(a['cabecalho'])))
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(a,b)['status'], 'ok')

    def test_unidades_equivalentes(self):
        b = tabela([['2,4 a 2,4835', '100']], ['Frequência de Operação (GHz)', 'Potência de Saída (mW)'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(),b)['status'], 'ok')

    def test_unidades_explicitas(self):
        b = tabela([['2,4 a 2,4835 GHz', '100 mW']], ['Frequência de Operação', 'Potência de Saída'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(),b)['status'], 'ok')

    def test_dbm_nao_linear(self):
        b = tabela([['2400 a 2483,5', '20 dBm']])
        self.assertIsNone(e.registros(b)[0][0]['potencia_saida_w'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(),b)['status'], 'comparacao_parcial')

    def test_faixas_agrupadas(self):
        a = tabela([['898,5 a 901 e 905 a 915 MHz', '0,1']])
        b = tabela([['905 a 915', '0,1'], ['898,5 a 901', '0,1']])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(a,b)['status'], 'ok')
        self.assertFalse(e.intervalos('898 a 901 e outra faixa', 'MHz'))
        self.assertFalse(e.intervalos('2 a 3 GHz e 900 a 915 MHz', 'MHz'))

    def test_numeros(self):
        self.assertEqual(e.numero('1.234,5'), 1234.5)
        self.assertEqual(e.numero('1,234.5'), 1234.5)
        self.assertEqual(e.numero('0.1'), .1)

    def test_duplicados_sao_ambiguos(self):
        b = tabela([['2400 a 2483,5', '0,1']] * 2)
        r = s.comparar_tabelas_tecnicas_sch_cct(tabela(), b)
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])

    def test_sem_frequencia(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(tabela(), tabela([['', '0,1']]))
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])

    def test_sem_potencia(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(tabela(), tabela([['2400 a 2483,5', '']]))
        self.assertEqual(r['status'], 'comparacao_parcial')

    def test_faixa_sem_par_nao_prova_divergencia(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(tabela(), tabela([['900 a 915', '0,1']]))
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])

    def test_divergencia_comprovada(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(tabela(), tabela([['2400 a 2483,5', '0,2']]))
        self.assertEqual(r['status'], 'divergente')
        self.assertEqual(len(r['divergencias']), 1)

    def test_limites_separados(self):
        b = tabela([['2400', '2483,5', '0,1']], ['Frequência Inicial (MHz)', 'Frequência Final (MHz)', 'Potência de Saída (W)'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(),b)['status'], 'ok')

    def test_grandeza_desconhecida(self):
        b = tabela(cab=['Faixa de Frequências (MHz)', 'Potência radiada (W)'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(), b)['status'], 'comparacao_parcial')

    def test_tabela_desconhecida(self):
        self.assertEqual(e.montar_tabelas([{'pagina': 1, 'bruto': [['Nome', 'Modelo'], ['A', 'B']], 'estrategia': 'teste'}]), [])

    def test_nao_herdar_frequencia_ausente(self):
        regs, descartadas = e.registros(tabela([['2400 a 2483,5', '0,1'], ['', '0,2']]))
        self.assertEqual(len(regs), 1)
        self.assertEqual(len(descartadas), 1)

    def test_colunas_duplicadas(self):
        b = tabela([['2400 a 2483,5', '0,1', '0,2']], tabela()['cabecalho'] + ['Potência de Saída (W)'])
        self.assertFalse(e.registros(b)[0])

    def test_continuidade_explicita(self):
        partes = e.montar_tabelas([{'pagina': pg, 'bruto': [tabela()['cabecalho'], linha],
                                   'estrategia': 'teste', 'continuacao_explicita': pg==5}
                                  for pg,linha in [(4,['2400 a 2483,5','0,1']), (5,['900 a 915','0,2'])]])
        tabs, avisos, total = e.reconstruir(partes)
        self.assertEqual(total, 1)
        self.assertEqual(tabs[0]['paginas_origem'], [4,5])
        self.assertEqual(tabs[0]['origens_linhas'][1]['pagina'], 5)
        self.assertFalse(avisos)
        partes[1]['continuacao_explicita'] = False
        tabs, avisos, total = e.reconstruir(partes)
        self.assertEqual(len(tabs), 2)
        self.assertTrue(avisos)

    def test_tabelas_distintas_nao_unidas_por_colunas(self):
        partes = e.montar_tabelas([{'pagina': 4, 'bruto': [tabela()['cabecalho'], ['2400 a 2483,5','0,1']], 'estrategia': 'teste'},
                                  {'pagina': 5, 'bruto': [['Frequência (MHz)', 'Potência EIRP (W)'], ['900 a 915','0,2']], 'estrategia': 'teste', 'continuacao_explicita': True}])
        self.assertEqual(len(e.reconstruir(partes)[0]), 2)

    def test_selecao_por_cobertura_valida(self):
        ruim = tabela([['ruído', '1']]*10)
        boa = tabela()
        self.assertIs(e.selecionar([ruim, boa]), boa)
        self.assertIs(e.selecionar([boa, tabela()]), boa)

    def test_pdf_sem_texto(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'vazio.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.save(caminho)
            with contextlib.redirect_stdout(io.StringIO()):
                r = p.parsear_certificado_pdf(caminho)
            self.assertEqual(r['diagnostico_extracao']['status'], 'sem_texto_interpretavel')

    def test_selecao_complementar_integrada(self):
        pagina = SimpleNamespace(extract_text=lambda: 'Frequência Potência', find_tables=lambda: [], extract_tables=lambda cfg: [])
        pdf = unittest.mock.MagicMock()
        pdf.__enter__.return_value.pages = [pagina]
        complementar = [{'pagina':1,'bruto':[tabela()['cabecalho']] + tabela()['linhas'], 'estrategia':'pymupdf_linhas'}]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta)/'teste.pdf'
            caminho.touch()
            with patch.object(p.pdfplumber,'open', return_value=pdf), patch.object(e,'extrair_complementar', return_value=complementar), contextlib.redirect_stdout(io.StringIO()):
                r = p.parsear_certificado_pdf(caminho)
        self.assertEqual(r['tabela_tecnica_cct']['origem_extracao'], 'pymupdf_linhas')

    def test_relatorio_diagnostico(self):
        r = {'dados_pdf': {'diagnostico_extracao': {'status': 'parcial', 'alertas': ['<revisar>']}}}
        html = g._html_conferencia_bloco(r)
        self.assertIn('Diagnóstico da extração', html)
        self.assertIn('&lt;revisar&gt;', html)

    def test_extracao_parcial_nao_da_ok(self):
        b = dict(tabela(), status_extracao='parcial')
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(tabela(), b)['status'], 'comparacao_parcial')

    def test_mesma_frequencia_com_valores_distintos(self):
        a = tabela([['2400 a 2483,5', '0,1'], ['2400 a 2483,5', '0,2']])
        b = dict(a, linhas=list(reversed(a['linhas'])))
        # Valores distintos não identificam os modos sem contexto técnico.
        r = s.comparar_tabelas_tecnicas_sch_cct(a,b)
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])
        self.assertFalse(any(d['correspondencia_identificada'] for d in r['correspondencias_registros']))

    def test_falha_arquivo(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.parsear_certificado_pdf(None)['diagnostico_extracao']['status'], 'falha_extracao')
            self.assertEqual(p.parsear_certificado_pdf('inexistente_293084.pdf')['diagnostico_extracao']['status'], 'falha_extracao')

    def test_pdf_sintetico_duas_paginas(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta)/'duas_paginas.pdf'
            with pymupdf.open() as pdf:
                for pg, faixa in [(1, '2400 a 2483,5'), (2, '900 a 915')]:
                    page = pdf.new_page()
                    page.insert_text((40,70), 'Continuacao' if pg==2 else 'Dados tecnicos')
                    for y in [100,125,150]:
                        page.draw_line((40,y),(550,y))
                    for x in [40,300,550]:
                        page.draw_line((x,100),(x,150))
                    for x,y,t in [(45,116,'Faixa de Frequencias (MHz)'), (305,116,'Potencia de Saida (W)'),
                                  (45,141,faixa), (305,141,'0,1')]:
                        page.insert_text((x,y),t)
                pdf.save(caminho)
            with patch.object(e,'extrair_complementar') as complemento, contextlib.redirect_stdout(io.StringIO()):
                r = p.parsear_certificado_pdf(caminho)
            complemento.assert_not_called()
            self.assertEqual(r['diagnostico_extracao']['tabelas_reconstruidas'], 1)
            self.assertEqual(r['tabela_tecnica_cct']['paginas_origem'], [1,2])
            self.assertEqual(len(r['tabela_tecnica_cct']['registros_normalizados']), 2)

    def test_regressao_ncc_disponivel(self):
        arquivos = list(Path('validacao_sch_05100_24').rglob('NCC*.pdf'))
        if not arquivos:
            self.skipTest('CCT NCC não disponível neste checkout')
        with contextlib.redirect_stdout(io.StringIO()):
            r = p.parsear_certificado_pdf(arquivos[0])
        self.assertEqual(r['diagnostico_extracao']['paginas_examinadas'], 3)
        self.assertEqual(r['diagnostico_extracao']['paginas_utilizadas'], [2])
        self.assertEqual(r['diagnostico_extracao']['linhas_recuperadas'], 5)
        self.assertEqual(r['diagnostico_extracao']['intervalos_normalizados'], 6)
        import json
        resumo = json.loads((arquivos[0].parents[1]/'resumo.json').read_text(encoding='utf-8-sig'))
        comparacao = s.comparar_tabelas_tecnicas_sch_cct(resumo['tabela_tecnica_sch'], r['tabela_tecnica_cct'])
        self.assertEqual(comparacao['status'], 'ok')
        self.assertFalse(comparacao['divergencias'])

    def test_intensidade_logaritmica_nao_linear(self):
        self.assertIsNone(e.escalar('40 dBuV/m', 'Intensidade de Campo (dBuV/m)', 'intensidade_campo'))

    def test_intensidade_exige_distancia_compativel(self):
        a = tabela([['2400 a 2483,5', '100', '3']],
                   ['Frequência (MHz)', 'Intensidade de Campo (uV/m)', 'Distância (m)'])
        b = tabela([['2400 a 2483,5', '0,1', '300']],
                   ['Frequência (MHz)', 'Intensidade de Campo (mV/m)', 'Distância (cm)'])
        self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct(a,b)['status'], 'ok')
        b['linhas'][0][2] = '100'
        r = s.comparar_tabelas_tecnicas_sch_cct(a,b)
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])

    def test_mesma_grandeza_unidades_distintas_em_partes(self):
        tab = tabela([['2400 a 2483,5', '0,1', ''], ['900 a 915', '', '100']],
                     ['Frequência (MHz)', 'Potência de Saída (W)', 'Potência de Saída (mW)'])
        regs, rejeitadas = e.registros(tab)
        self.assertFalse(rejeitadas)
        self.assertEqual([r['potencia_saida_w'] for r in regs], [.1, .1])

    def test_fixture_cpqd_nao_confunde_eirp(self):
        import json
        caminho = Path('validacao_tabelas_cpqd/tabela_extraida.json')
        if not caminho.exists():
            self.skipTest('Fixture JSON não disponível')
        tab = json.loads(caminho.read_text(encoding='utf-8-sig'))
        regs, descartadas = e.registros(tab)
        self.assertTrue(regs)
        self.assertFalse(descartadas)
        self.assertTrue(any(r['potencia_eirp_w'] is not None for r in regs))
        self.assertTrue(any(r['potencia_saida_w'] != r['potencia_eirp_w'] and r['potencia_eirp_w'] is not None for r in regs))


if __name__ == '__main__':
    unittest.main()
