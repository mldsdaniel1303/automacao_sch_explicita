"""Contratos sintéticos: valores medidos não provam identidade técnica."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'automacao_sch_explicita'))
import extracao_cct as e
import gerador_relatorio as g


def tabela(linhas, cab=None):
    return {'cabecalho': cab or ['Frequência (MHz)', 'Potência de Saída (W)', 'Tecnologias'],
            'linhas': linhas,
            'origens_linhas': [{'pagina': 7, 'tabela': 2, 'linha': i + 10,
                               'geometria': {'bbox': [0, i, 10, i + 1]}}
                              for i in range(len(linhas))]}


class IdentidadeContextoTests(unittest.TestCase):
    def test_tecnologias_distintas_na_mesma_faixa_nao_provam_divergencia(self):
        for comparador in (e.comparar_correspondencias, e.comparar_registros):
            for a, b in [('GSM', 'LTE'), ('LTE', 'WCDMA'), ('WCDMA', 'GSM')]:
                with self.subTest(comparador=comparador.__name__, a=a, b=b):
                    r = comparador(tabela([['800 a 810', '0,1', a]]),
                                   tabela([['800 a 810', '0,2', b]]))
                    self.assertEqual(r['status'], 'comparacao_parcial')
                    self.assertFalse(r['divergencias'])
                    self.assertNotIn('potencia_saida_w', r['campos_comparados'])

    def test_grupo_de_modos_nao_equivale_a_modo_isolado(self):
        r = e.comparar_correspondencias(tabela([['800 a 810', '0,1', 'GSM/GPRS/EDGE']]),
                                       tabela([['800 a 810', '0,2', 'GSM 850']]))
        self.assertFalse(r['detalhes_correspondencias'][0]['correspondencia_identificada'])
        self.assertFalse(r['divergencias'])

    def test_tecnologia_ausente_nao_identifica_modo_celular(self):
        for tecnologia in ('', '-', 'unknown'):
            r = e.comparar_correspondencias(tabela([['800 a 810', '0,1', tecnologia]]),
                                           tabela([['800 a 810', '0,2', 'LTE']]))
            self.assertEqual(r['status'], 'comparacao_parcial')
            self.assertFalse(r['divergencias'])

    def test_sem_tecnologia_mas_com_emissao_nao_adivinha_modo(self):
        cab = ['Frequência (MHz)', 'Potência de Saída (W)', 'Tecnologias', 'Emissões']
        r = e.comparar_registros(tabela([['800 a 810', '0,1', '-', '5M00G7W']], cab),
                                tabela([['800 a 810', '0,2', '-', '5M00G7W']], cab))
        self.assertFalse(r['divergencias'])
        self.assertEqual(r['status'], 'comparacao_parcial')

    def test_technologies_em_ingles_preserva_modo(self):
        cab = ['Frequency (MHz)', 'Output Power (W)', 'Technologies']
        r = e.comparar_registros(tabela([['800 a 810', '0,1', 'LTE']], cab),
                                tabela([['800 a 810', '0,2', 'GSM']], cab))
        self.assertFalse(r['divergencias'])
        self.assertEqual(r['status'], 'comparacao_parcial')

    def test_modo_celular_identico_permite_comparar_valores(self):
        for comparador in (e.comparar_correspondencias, e.comparar_registros):
            r = comparador(tabela([['800 a 810', '0,1', 'LTE']]),
                           tabela([['800 a 810', '0,2', 'LTE']]))
            self.assertEqual(r['status'], 'divergente')
            self.assertEqual(r['divergencias'][0]['coluna'], 'potencia_saida_w')

    def test_tecnologia_textual_nao_equivale_a_tecnica_generica(self):
        cab = ['Frequência (MHz)', 'Potência de Saída (W)', 'Tecnologias', 'Modulação']
        for comparador in (e.comparar_correspondencias, e.comparar_registros):
            r = comparador(tabela([['800 a 810', '0,1', 'Modo proprietário', 'QPSK']], cab),
                           tabela([['800 a 810', '0,2', 'OFDM', 'QPSK']], cab))
            self.assertEqual(r['status'], 'comparacao_parcial')
            self.assertFalse(r['divergencias'])

    def test_texto_de_modo_nao_identificado_nao_prova_identidade(self):
        for valor in ('Tecnologia não identificada', 'not identified', 'desconhecida'):
            r = e.comparar_correspondencias(tabela([['800 a 810', '0,1', valor]]),
                                           tabela([['800 a 810', '0,2', valor]]))
            self.assertEqual(r['status'], 'comparacao_parcial')
            self.assertFalse(r['divergencias'])

    def test_frequencias_repetidas_nao_pareiam_por_valores_medidos(self):
        for campo in ('Potência de Saída (W)', 'Potência EIRP (W)', 'Intensidade de Campo (uV/m)'):
            cab = ['Frequência (MHz)', campo]
            a = tabela([['800 a 810', '0,1'], ['800 a 810', '0,2']], cab)
            b = tabela(list(reversed(a['linhas'])), cab)
            r = e.comparar_registros(a, b)
            self.assertEqual(r['status'], 'comparacao_parcial')
            self.assertFalse(r['divergencias'])
            self.assertFalse(any(x['correspondencia_identificada'] for x in r['correspondencias_registros']))

    def test_potencias_coincidentes_com_contextos_incompativeis(self):
        a = tabela([['800 a 810', '0,1', 'GSM'], ['800 a 810', '0,2', 'LTE']])
        b = tabela([['800 a 810', '0,1', 'WCDMA'], ['800 a 810', '0,2', 'WCDMA']])
        for comparador in (e.comparar_correspondencias, e.comparar_registros):
            r = comparador(a, b)
            self.assertEqual(r['status'], 'comparacao_parcial')
            self.assertFalse(r['divergencias'])

    def test_modulacoes_incompativeis_nao_pareiam_por_intensidade(self):
        cab = ['Frequência (MHz)', 'Intensidade de Campo (uV/m)', 'Distância (m)', 'Modulação']
        a = tabela([['100', '1', '3', 'ASK'], ['100', '2', '3', 'FSK']], cab)
        b = tabela([['100', '1', '3', 'QPSK'], ['100', '2', '3', 'QPSK']], cab)
        r = e.comparar_registros(a, b)
        self.assertEqual(r['status'], 'comparacao_parcial')
        self.assertFalse(r['divergencias'])

    def test_pares_reordenados_por_contexto_nao_por_potencia(self):
        a = tabela([['800 a 810', '0,1', 'GSM'], ['800 a 810', '0,1', 'LTE']])
        b = tabela([['800 a 810', '0,2', 'LTE'], ['800 a 810', '0,1', 'GSM']])
        r = e.comparar_registros(a, b)
        self.assertEqual(r['status'], 'divergente')
        self.assertEqual(len(r['divergencias']), 1)
        self.assertEqual(r['divergencias'][0]['origem_sch']['original'][2], 'LTE')
        self.assertEqual(r['divergencias'][0]['origem_cct']['original'][2], 'LTE')

    def test_unicidade_exigida_nos_dois_sentidos(self):
        cab = ['Frequência (MHz)', 'Potência de Saída (W)', 'Emissão']
        a = tabela([['800 a 810', '0,1', 'AAA'], ['800 a 810', '0,2', '']], cab)
        b = tabela([['800 a 810', '0,1', 'AAA'], ['800 a 810', '0,2', 'BBB']], cab)
        for comparador, chave in ((e.comparar_correspondencias, 'detalhes_correspondencias'),
                                  (e.comparar_registros, 'correspondencias_registros')):
            r = comparador(a, b)
            self.assertFalse(any(d['correspondencia_identificada'] for d in r[chave]))
            self.assertFalse(r['divergencias'])

    def test_proveniencia_contextos_e_entradas_preservados(self):
        a = tabela([['800 a 810', '0,1', 'LTE']])
        b = tabela([['800 a 810', '0,1', 'GSM']])
        antes = copy.deepcopy((a, b))
        r = e.comparar_correspondencias(a, b)
        d = r['detalhes_correspondencias'][0]
        self.assertEqual(d['origem_sch']['pagina_origem'], 7)
        rejeitado = d['candidatos_rejeitados_por_contexto'][0]
        self.assertTrue(rejeitado['coincide_saida'])
        self.assertTrue(d['coincide_saida'])  # Observação numérica, sem identidade.
        self.assertFalse(d['correspondencia_identificada'])
        self.assertEqual(rejeitado['origem_cct']['tabela_origem'], 2)
        self.assertEqual(rejeitado['contexto_cct']['modos_celulares'], ['gsm'])
        self.assertTrue(rejeitado['origem_cct']['geometria'])
        self.assertEqual((a, b), antes)


class EstadosRelatorioTests(unittest.TestCase):
    def test_nao_conforme_com_hifens_sublinhados_e_caixa(self):
        for valor in ('Não Conforme', 'não-conforme', 'nao_conforme', 'NÃO-CONFORME',
                      'NÃO_CONFORME', 'não - conforme', 'não–conforme', 'não—conforme',
                      'produto_nao_conforme', 'Resultado: NÃO-CONFORME.'):
            for entrada in (valor, {'status': valor}, {'resultado': valor}):
                with self.subTest(entrada=entrada):
                    self.assertEqual(g._normalizar_status_conferencia(entrada), 'NC')
                    self.assertIn('>NC</td>', g._td_status_conferencia(entrada))

    def test_correcao_de_negacao_preserva_demais_estados(self):
        for valor, esperado in [('Conforme', 'C'), ('CONFORME', 'C'), ('ok', 'C'),
                                ('REVISAR', 'REVISAR'), ('comparacao_parcial', 'REVISAR'),
                                ('ERRO', 'ERRO'), ('erro_extracao', 'ERRO'),
                                ('N/A', 'N/A'), ('nao_aplicavel', 'N/A')]:
            with self.subTest(valor=valor):
                self.assertEqual(g._normalizar_status_conferencia(valor), esperado)

    def test_parcial_erro_e_nao_aplicavel_sao_distintos(self):
        for valor, esperado in [('comparacao_parcial', 'REVISAR'), ('inconclusivo', 'REVISAR'),
                                ('erro_extracao', 'ERRO'), ('falha_extracao', 'ERRO'),
                                ('nao_aplicavel', 'N/A'), ('nao_aplicavel_ausencia_confirmada', 'N/A')]:
            for entrada in (valor, {'status': valor}):
                with self.subTest(entrada=entrada):
                    self.assertEqual(g._normalizar_status_conferencia(entrada), esperado)
                    self.assertIn('>' + esperado + '</td>', g._td_status_conferencia(entrada))

    def test_estado_desconhecido_nao_prova_nao_aplicabilidade(self):
        for valor in ('', None, 'estado_novo', 'sem_tabela', 'nao_verificado'):
            self.assertEqual(g._normalizar_status_conferencia(valor), 'REVISAR')

    def test_tabela_resumida_nao_converte_parcial_ou_erro_em_nc_ou_na(self):
        for valor, esperado in [('comparacao_parcial', 'REVISAR'), ('erro_extracao', 'ERRO')]:
            item = {'campo': 'tabela_tecnica', 'status': valor, 'detalhes_tabela': {'status': valor}}
            texto = g._criar_tabela_comparacao({'conferencia_sch_cct': {'comparacoes': [item]}})
            self.assertIn('>' + esperado + '</td>', texto)
            self.assertNotIn('>N/A</td>', texto)
            self.assertNotIn('>NC</td>', texto)


if __name__ == '__main__':
    unittest.main()
