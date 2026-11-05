"""PDF real + exemplos SCH fornecidos em texto; demais cenários são sintéticos."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ/'automacao_sch_explicita'))
import extracao_cct as e
import pdf_parser as p
import funcoes_sch as s
import gerador_relatorio as g
import mvp_simplificada_re as m


class CorrespondenciaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pasta = RAIZ/'tests/fixtures/ccts'
        pdf = pasta/'CPQD-i_12407_NOV_00A X.pdf'
        if not pdf.exists():
            raise unittest.SkipTest('PDF CPQD real ausente')
        with contextlib.redirect_stdout(io.StringIO()):
            cls.dados = p.parsear_certificado_pdf(pdf)
        cls.referencias = json.loads((pasta/'referencias_sch_cpqd_prompt.json').read_text(encoding='utf-8'))
        cls.capturas = json.loads((pasta/'sch_cpqd_transcricao_capturas.json').read_text(encoding='utf-8'))

    def test_oito_referencias_nao_sao_35_linhas_sch(self):
        tab = self.dados['tabela_tecnica_cct']
        self.assertEqual(len(tab['linhas']),35)
        self.assertEqual(tab['paginas_origem'],[4,5])
        r = s.comparar_tabelas_tecnicas_sch_cct(self.referencias,tab)
        detalhes = r['detalhes_correspondencias']
        self.assertEqual(len(detalhes),8)
        self.assertEqual(sum(d['coincide_saida'] for d in detalhes),6)
        self.assertEqual(sum(d['coincide_eirp'] and not d['coincide_saida'] for d in detalhes),2)
        self.assertFalse(any(d['correspondencia_identificada'] for d in detalhes))
        self.assertEqual(r['status'],'comparacao_parcial')
        self.assertFalse(r['divergencias'])
        self.assertFalse(self.referencias['captura_selenium'])

    def test_normalizacao_tecnica_sem_validar_tecnologia_completa(self):
        for a,b,esperado in [('FHSS – BT EDR','SALTO EM FREQUÊNCIA','FHSS'),
                             ('DSSS – BT LE','SEQUÊNCIA DIRETA','DSSS'),
                             ('OFDM–802.11ax','OFDM','OFDM')]:
            self.assertEqual(e.tecnica_transmissao(a),esperado)
            self.assertEqual(e.tecnica_transmissao(a),e.tecnica_transmissao(b))

    def sinteticas(self):
        cab = ['Faixa de Frequências (MHz)','Potência Máxima de Saída (W)',
               'Designação de Emissões','Tecnologias','Tipo de Modulação','SAR (W/kg) Corpo']
        cct = {'cabecalho':cab+['Valor Médio de Potência EIRP (W)'],
               'linhas':[['2400 a 2483,5','0,0170','674KF7W','DSSS – BT LE','GFSK','-',''],
                         ['2400 a 2483,5','0,4852','11M0D7W','DSSS – 802.11b','DBPSK DQPSK CCK','1,270','']],
               'origens_linhas':[{'pagina':4},{'pagina':4}]}
        sch = {'cabecalho':cab,'linhas':[['2400 a 2483,5','0,4852','11M0D7W','SEQUÊNCIA DIRETA','DBPSK DQPSK CCK','1,27'],
                                         ['2400 a 2483,5','0,017','674KF7W','SEQUÊNCIA DIRETA','GFSK','-']]}
        return sch,cct

    def test_contexto_linhas_reordenadas_decimais_e_sar(self):
        sch,cct = self.sinteticas()
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(r['status'],'ok')
        self.assertEqual([d['linha_cct'] for d in r['detalhes_correspondencias']],[2,1])
        self.assertEqual(r['detalhes_correspondencias'][0]['sar_resultado'],'coincidente')
        self.assertIn('Tecnologia completa',r['campos_nao_validados'][0])

    def test_potencia_ou_sar_nao_desambiguam_tecnica_generica(self):
        sch,cct = self.sinteticas()
        for tab in (sch,cct):
            for linha in tab['linhas']:
                linha[2],linha[4] = '', ''
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(r['status'],'comparacao_parcial')
        self.assertFalse(any(d['correspondencia_identificada'] for d in r['detalhes_correspondencias']))
        self.assertFalse(r['divergencias'])

    def test_duplicatas_nao_selecionadas_por_ordem(self):
        sch,cct = self.sinteticas()
        sch['linhas'] = [sch['linhas'][0]]*2
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertFalse(any(d['correspondencia_identificada'] for d in r['detalhes_correspondencias']))

    def test_eirp_somente_coincidencia_sem_conformidade(self):
        sch = {'cabecalho':['Frequência (MHz)','Potência de Saída (W)'],'linhas':[['5470 a 5725','0,0121']]}
        cct = {'cabecalho':['Frequência (MHz)','Potência de Saída (W)','Potência EIRP (W)'],
               'linhas':[['5470 a 5725','0,0612','0,0121']], 'origens_linhas':[{'pagina':5}]}
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(r['status'],'comparacao_parcial')
        self.assertEqual(r['detalhes_correspondencias'][0]['resultado'],'coincidencia_apenas_eirp')
        self.assertFalse(r['divergencias'])
        cct['linhas'][0][1]='-'
        d = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)['detalhes_correspondencias'][0]
        self.assertIsNone(d['potencia_saida_cct'])
        self.assertEqual(d['eirp_cct'],.0121)

    def test_sar_na_coluna_correta_com_prioridade_sobre_nota(self):
        sar = s.analisar_sar_cct(self.dados)
        self.assertTrue(sar['sar_aplicavel'])
        self.assertFalse(sar['preencher_frase'])
        self.assertEqual(len(sar['valores_sar_encontrados']),16)
        self.assertIn('Ensaio de SAR não aplicável',self.dados['texto_completo'])
        sch,cct = self.sinteticas()
        sch['linhas'][0][5]='0,7'
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(r['divergencias'][0]['coluna'],'sar_corpo_w_kg')

    def test_observacao_existente_e_especificacoes_sem_escrita(self):
        frase = s.OBS_RADIACAO_RESTRITA
        with patch.object(m,'ler_observacao_atual_re',return_value={'localizado':True,'texto':frase}), \
             patch.object(s,'preencher_observacao_caracteristicas') as escrever, \
             patch.object(s,'diagnosticar_campo_cts_re',return_value={'status':'nao_aplicavel_ausencia_confirmada','motivo':'Ausência confirmada na fixture unitária'}), \
             patch.object(s,'preencher_titulo_caracteristicas_secundarias_se_existir',return_value={'status':'nao_aplicavel'}), \
             patch.object(s,'salvar_caracteristicas_tecnicas') as salvar:
            r = m.preencher_caracteristicas_conservadoras_re(None,None,{'tipo_produto':'Transceptor de Radiação Restrita'},[],self.dados)
        self.assertTrue(r['sem_alteracao'])
        escrever.assert_not_called()
        salvar.assert_not_called()
        texto = 'Bluetooth e Wi-Fi. EIRP. SAR. Ganho combinado. Ambientes internos.'
        diag = e.diagnosticar_especificacoes(texto,self.dados['texto_completo'])
        self.assertFalse(diag['editar_campo'])
        self.assertTrue(diag['itens']['eirp']['sch'])
        self.assertEqual(e.diagnosticar_especificacoes('',self.dados['texto_completo'])['status'],'sch_nao_disponivel')

    def test_relatorio_preserva_originais_e_escapa_conteudo(self):
        sch,cct = self.sinteticas()
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        r['detalhes_correspondencias'][0]['motivo'] += '<script>'
        html = g._html_comparacao_tabela_tecnica({'dados_pdf':self.dados,'conferencia_sch_cct':{'comparacao_tabela_tecnica':r}})
        self.assertIn('Potência SCH W',html)
        self.assertIn('Valores originais',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)

    def test_tecnica_generica_nao_produz_cobertura_integral(self):
        sch,cct = self.sinteticas()
        comp = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        diag = {'status':'coletado','tabelas':[{'familia':'rf_frequencia_potencia'}]}
        cobertura = m.avaliar_cobertura_mvp(diag,{'status_geral':'ok','comparacao_tabela_tecnica':comp},self.dados)
        self.assertFalse(cobertura['comparacao_tecnica_integral'])
        self.assertTrue(cobertura['apto_preenchimento'])

    def test_transcricao_visual_35_sem_duplicar_sobreposicao(self):
        self.assertEqual(len(self.capturas['linhas']),35)
        self.assertEqual(self.capturas['total_linhas_visiveis'],35)
        self.assertTrue(self.capturas['conferencia_visual_sch'])
        self.assertFalse(self.capturas['captura_selenium'])
        regs, rejeitadas = e.registros(self.capturas)
        self.assertFalse(rejeitadas)
        self.assertEqual([sum(r['frequencia_inicial_mhz']==f for r in regs) for f in (2400,5725,5150,5470)],[8,9,9,9])
        self.assertEqual(self.capturas['linhas'][10][2],'36M3D7W')
        self.assertEqual(sum(l[5]!='-' for l in self.capturas['linhas']),16)

    def test_capturas_17_pares_e_18_coincidencias_eirp_ambiguas(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(self.capturas,self.dados['tabela_tecnica_cct'])
        self.assertEqual(r['status'],'comparacao_parcial')
        self.assertFalse(r['divergencias'])
        self.assertEqual(r['resumo_correspondencias'],{'pares_identificados':17,'linhas_ambiguas':18,
            'coincidencias_numericas_saida':17,'coincidencias_numericas_apenas_eirp':18,
            'sar_comparado_em_par_identificado':8})
        for d in r['detalhes_correspondencias'][:17]:
            self.assertEqual(d['pagina'],4)
            self.assertEqual(d['resultado'],'coincidente_saida')
        for d in r['detalhes_correspondencias'][17:]:
            self.assertEqual(len(d['candidatos']),3)
            self.assertFalse(d['correspondencia_identificada'])
            self.assertTrue(d['coincide_eirp'])
            self.assertFalse(d['coincide_saida'])
            self.assertTrue(all(c['pagina']==5 for c in d['candidatos']))

    def test_capturas_independem_ordem_das_duas_tabelas(self):
        cct = copy.deepcopy(self.dados['tabela_tecnica_cct'])
        sch = copy.deepcopy(self.capturas)
        cct['linhas'].reverse()
        cct['origens_linhas'].reverse()
        sch['linhas'].reverse()
        r = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
        self.assertEqual(r['resumo_correspondencias']['pares_identificados'],17)
        self.assertEqual(r['resumo_correspondencias']['linhas_ambiguas'],18)
        self.assertFalse(r['divergencias'])
        self.assertTrue(all(d['pagina']==4 for d in r['detalhes_correspondencias'] if d['correspondencia_identificada']))

    def test_sar_capturas_nao_e_usado_para_desempatar(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(self.capturas,self.dados['tabela_tecnica_cct'])
        for d in r['detalhes_correspondencias']:
            if d['linha_sch']<=17 and d['sar_corpo_sch_w_kg'] is not None:
                self.assertEqual(d['sar_resultado'],'coincidente')
            elif d['linha_sch']>17 and d['sar_corpo_sch_w_kg'] is not None:
                self.assertTrue(any(c['coincide_sar_corpo'] for c in d['candidatos']))
                self.assertFalse(d['correspondencia_identificada'])
        self.assertFalse(s.analisar_sar_cct(self.dados)['preencher_frase'])

    def test_especificacoes_visiveis_ganhos_e_sem_edicao(self):
        antes = copy.deepcopy(self.capturas)
        diag = e.diagnosticar_especificacoes(self.capturas['especificacoes_complementares'],self.dados['texto_completo'])
        self.assertTrue(all(v['sch'] and v['cct'] for v in diag['itens'].values()))
        self.assertEqual(diag['ganhos_combinados']['coincidentes'],[
            {'frequencia_inicial_mhz':5150.,'frequencia_final_mhz':5350.,'ganho_dbi':-7.13},
            {'frequencia_inicial_mhz':5470.,'frequencia_final_mhz':5725.,'ganho_dbi':-7.03}])
        self.assertFalse(diag['editar_campo'])
        self.assertEqual(antes,self.capturas)
        self.assertEqual(self.capturas['observacao'],s.OBS_RADIACAO_RESTRITA)

    def test_relatorio_distingue_sar_candidato_e_captura_visual(self):
        r = s.comparar_tabelas_tecnicas_sch_cct(self.capturas,self.dados['tabela_tecnica_cct'])
        html = g._html_comparacao_tabela_tecnica({'dados_pdf':self.dados,'conferencia_sch_cct':{'comparacao_tabela_tecnica':r}})
        self.assertIn('Transcrição manual',html)
        self.assertIn('SAR Corpo SCH W/kg',html)
        self.assertIn('SAR Corpo CCT W/kg',html)
        self.assertIn('par identificado: False',html)
        self.assertIn('Coincidência numérica não comprova identidade',html)


if __name__ == '__main__':
    unittest.main()
