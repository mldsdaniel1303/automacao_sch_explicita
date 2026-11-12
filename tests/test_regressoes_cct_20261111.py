"""PDFs reais locais; testes sintéticos de DOM não comprovam captura autenticada."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ/'automacao_sch_explicita'))
import pdf_parser as p
import funcoes_sch as f
import diagnostico_estrutura_sch as d
import extracao_cct as e




def tabela(freq, campo='Potência Máxima de Saída (W)', valor='0,1', **meta):
    return dict(cabecalho=['Faixa de Frequências (MHz)',campo],linhas=[[freq,valor]],
                total_linhas=1,total_colunas=2,**meta)


class MultitabelasTests(unittest.TestCase):
    def test_desdobramento_preserva_linha_original_e_faixa(self):
        from mvp_simplificada_re import expandir_faixas_explicitas_re
        t=tabela('898,5 a 901 e 907,5 a 915')
        antes=copy.deepcopy(t)
        r=expandir_faixas_explicitas_re(t)
        self.assertEqual(len(r['linhas']),2)
        self.assertEqual([o['linha'] for o in r['origens_linhas']],[1,1])
        self.assertEqual(r['origens_linhas'][0]['faixa_original'],t['linhas'][0][0])
        self.assertEqual(t,antes)

    def test_coleta_tres_tabelas_preserva_ordem_familia_e_originais(self):
        tabs=[tabela('824 a 849',secao='basicas'),tabela('2400 a 2483,5',secao='secundarias'),
              tabela('13,56','Intensidade de Campo (uV/m)','3,8217')]
        original=copy.deepcopy(tabs);driver=Mock();driver.execute_script.return_value={'pronto':True,'tabelas':tabs}
        with patch.object(f,'clicar_aba_caracteristicas_tecnicas'),patch.object(f,'entrar_iframe_detalhe_analise'),patch('controles_acompanhar.aguardar_ajax'):
            r=d.extrair_tabela_dom_para_comparacao(driver,Mock())
        self.assertEqual(r['total_tabelas'],3)
        self.assertEqual([t['ordem_dom'] for t in r['tabelas']],[1,2,3])
        self.assertEqual(r['tabelas'][2]['familia'],'rf_intensidade_sem_distancia')
        for a,b in zip(original,r['tabelas']):
            self.assertEqual(a['cabecalho'],b['cabecalho']);self.assertEqual(a['linhas'],b['linhas'])

    def test_compara_familias_independentes_sem_usar_ordem(self):
        a=tabela('824 a 849');b=tabela('2400 a 2483,5')
        nfc={'cabecalho':['Frequência (MHz)','Intensidade de Campo (uV/m)','Distância (m)'],
             'linhas':[['13,56','3,8217','30']]}
        r=f.comparar_conjunto_tabelas_simplificado({'tabelas':[a,b,nfc]}, {'tabelas_identificadas':[nfc,b,a]})
        self.assertEqual(len(r['tabelas']),3)
        self.assertEqual(r['status'],'ok');self.assertFalse(r['conformidade_integral'])
        self.assertEqual([x['partes_cct'][0]['tabela_cct'] for x in r['tabelas']],[3,2,1])

    def test_tabelas_ambiguas_nao_sao_pareadas_por_indice(self):
        t=tabela('2400 a 2483,5')
        r=f.comparar_conjunto_tabelas_simplificado({'tabelas':[t,t]}, {'tabelas_identificadas':[t,t]})
        self.assertEqual(r['status'],'comparacao_parcial')
        self.assertFalse(r['divergencias'])
        self.assertTrue(all(not x['partes_cct'] for x in r['tabelas']))

    def test_grandezas_conduzida_saida_eirp_distintas(self):
        a=tabela('2400 a 2483,5','Potência conduzida (W)')
        for b in (tabela('2400 a 2483,5'),tabela('2400 a 2483,5','Potência EIRP (W)')):
            r=f.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[b]})
            self.assertEqual(r['status'],'comparacao_parcial')
            self.assertFalse(r['divergencias'])

    def test_sar_cabeca_por_par_unico(self):
        a={'cabecalho':['Frequência (MHz)','Potência de Saída (W)','SAR Cabeça (W/kg)'],
           'linhas':[['2400 a 2483,5','0,1','0,2']]}
        b=copy.deepcopy(a);b['linhas'][0][2]='0,3'
        r=f.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[b]})
        self.assertEqual(r['status'],'divergente')
        self.assertTrue(any(v['coluna']=='sar_cabeca_w_kg' for v in r['divergencias']))

    def test_conduzida_compara_mesma_grandeza_em_mw_e_w(self):
        a=tabela('2400 a 2483,5','Potência Conduzida (mW)','2')
        b=tabela('2400 a 2483,5','Potência Conduzida (W)','0,002')
        r=f.comparar_conjunto_tabelas_simplificado({'tabelas':[a]},{'tabelas_identificadas':[b]})
        self.assertEqual(r['status'],'ok')
        self.assertIn('potencia_conduzida_w',r['campos_comparados'])

    def test_relatorio_mostra_tabelas_e_escapa_conteudo(self):
        import gerador_relatorio as g
        comp={'status':'comparacao_parcial','tabelas':[{'tabela_sch':1,'familia':'potencia',
              'cabecalho':['<script>'],'partes_cct':[{'tabela_cct':2,'paginas_cct':[3],
              'comparacao':{'status':'comparacao_parcial','inconclusivos':['revisar']}}]}]}
        html=g._html_comparacao_tabela_tecnica({'conferencia_sch_cct':{'comparacao_tabela_tecnica':comp}})
        self.assertIn('Tabela SCH 1',html);self.assertIn('Tabela CCT 2',html)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)

    def test_cpqd_apenas_capa_nao_referencia_ou_nome_do_arquivo(self):
        self.assertEqual(p.extrair_numero_certificado_por_contexto('CPQD 28770\nRelatório AM 69041-025'),'CPQD 28770')
        self.assertEqual(p.extrair_numero_certificado_por_contexto('Referência ao certificado CPQD 28770 no histórico'),'')
        self.assertEqual(p.extrair_numero_certificado_por_contexto('CPQD 28770-NOV-00B'),'')
        with self.assertRaises(ValueError):p.extrair_numero_certificado_por_contexto('CPQD 28770\nCPQD 28771')

    def test_celula_vazia_nao_herda_frequencia(self):
        rows=[[(0,0,100,20),(100,0,200,20)],[(0,20,100,40),(100,20,200,40)],
              [None,(100,40,200,60)]]
        raw=[['Frequência (MHz)','Potência de Saída (W)'],['2400 a 2483,5','0,1'],[None,'0,2']]
        obj=Mock();obj.rows=[Mock(cells=r) for r in rows];obj.extract.return_value=raw;obj.bbox=(0,0,200,60);obj.page=None
        g=p._extrair_tabela_tecnica_por_geometria(obj)
        self.assertEqual(g[-1][0],'')
        regs,rejeitadas=e.registros({'cabecalho':g[0],'linhas':g[1:]})
        self.assertEqual(len(regs),1);self.assertEqual(len(rejeitadas),1)


if __name__=='__main__':unittest.main()
