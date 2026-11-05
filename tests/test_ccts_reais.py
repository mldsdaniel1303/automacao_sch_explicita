"""Contratos locais dos CCTs de referência; ausência do PDF é skip explícito.

Expectativas fornecidas na tarefa, ainda sujeitas à conferência visual dos PDFs.
Não substitui os testes de classificação elétrica/modelos nem captura dados SCH.
Defina CCT_TEST_DIR para procurar também em uma pasta fora do checkout.
"""
import contextlib
import copy
import hashlib
import io
import os
from pathlib import Path
import sys
import unittest

RAIZ = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(RAIZ / 'automacao_sch_explicita'))
import extracao_cct as e
import pdf_parser as p
import funcoes_sch as s


class CCTsReaisTests(unittest.TestCase):
    cache = {}

    def ler(self, nome):
        if nome in self.cache:
            return copy.deepcopy(self.cache[nome])
        raizes = [RAIZ]
        if os.environ.get('CCT_TEST_DIR'):
            raizes.append(Path(os.environ['CCT_TEST_DIR']).expanduser())
        arquivos = sorted({p.resolve() for raiz in raizes for p in raiz.rglob(nome) if p.is_file()})
        if not arquivos:
            self.skipTest(f'PDF real ausente: {nome}; disponibilize no projeto ou em CCT_TEST_DIR')
        hashes = {hashlib.sha256(arquivo.read_bytes()).hexdigest() for arquivo in arquivos}
        self.assertEqual(len(hashes), 1, f'Há versões diferentes de {nome}; isole a referência em CCT_TEST_DIR')
        with contextlib.redirect_stdout(io.StringIO()):
            resultado = p.parsear_certificado_pdf(arquivos[0])
        self.assertNotEqual(resultado['diagnostico_extracao']['status'], 'falha_extracao')
        self.cache[nome] = resultado
        return resultado

    def test_cpqd_35_registros_eirp_e_sar(self):
        dados = self.ler('CPQD-i_12407_NOV_00A X.pdf')
        self.assertEqual(dados['diagnostico_extracao']['paginas_examinadas'], 6)
        tab = dados['tabela_tecnica_cct']
        self.assertEqual(len(tab['linhas']), 35)
        origens = tab['origens_linhas']
        self.assertEqual(sum(o['pagina'] == 4 for o in origens), 17)
        self.assertEqual(sum(o['pagina'] == 5 for o in origens), 18)
        partes = tab['tabelas_identificadas']
        self.assertEqual(len(partes), 2)
        self.assertEqual([t['paginas_origem'] for t in partes], [[4], [5]])
        self.assertFalse(any(e.coluna(c) == 'potencia_eirp' for c in partes[0]['cabecalho']))
        self.assertTrue(any(e.coluna(c) == 'potencia_eirp' for c in partes[1]['cabecalho']))
        regs = tab['registros_normalizados']
        exemplo = [r for r in regs if r['pagina_origem'] == 5
                   and r['frequencia_inicial_mhz'] == 5150
                   and r['frequencia_final_mhz'] == 5350
                   and r['potencia_eirp_w'] == .0104
                   and '802.11a' in ' '.join(r['original'])]
        self.assertEqual(len(exemplo), 1, 'Exemplo de EIRP não recuperado de forma inequívoca')
        self.assertIsNone(exemplo[0]['potencia_saida_w'])
        sar = s.analisar_sar_cct(dados)
        self.assertTrue(sar['sar_aplicavel'])
        self.assertTrue(sar['valores_sar_encontrados'])
        self.assertFalse(sar['preencher_frase'])

    def verificar_sem_rf(self, dados, paginas):
        self.assertEqual(dados['diagnostico_extracao']['paginas_examinadas'], paginas)
        self.assertFalse(dados['tabela_tecnica_cct']['linhas'])
        self.assertFalse(dados['tabela_tecnica_cct'].get('registros_normalizados'))

    def test_moderna_eletrica_sem_rf(self):
        dados = self.ler('13048-26_CERT_CONFORMIDADE.pdf')
        self.verificar_sem_rf(dados, 3)
        self.assertIn('caracteristicas tecnicas basicas', e.normalizar(dados['texto_completo']))
        self.assertTrue(dados['data_emissao'])
        self.assertTrue(dados['data_validade'])

    def test_ncc_poe_sem_rf(self):
        dados = self.ler('NCC_30803_26_Rev1_HP.pdf')
        self.verificar_sem_rf(dados, 4)
        self.assertIn('30803', dados['numero_certificado'])
        texto = e.normalizar(dados['texto_completo'])
        self.assertIn('poe', texto)
        for valor in ('405', '125', '390', '248', '770'):
            self.assertIn(valor, texto)

    def test_cpqd_identidade_modelo_datas(self):
        dados = self.ler('CPQD-i_12407_NOV_00A X.pdf')
        self.assertEqual(dados['numero_certificado'], 'CPQD-I 12407')
        self.assertEqual(dados['modelo'], 'SM-X520')
        self.assertEqual(dados['data_emissao'], '04/09/2026')
        self.assertEqual(dados['data_certificacao'], '04/09/2026')
        self.assertEqual(dados['data_validade'], '06/03/2029')

    def test_empresas_e_ocd_sem_rotulos_ou_marca_dagua(self):
        dados = self.ler('13048-26_CERT_CONFORMIDADE.pdf')
        self.assertEqual(dados['fabricante'], 'Dongguan Jing Shun Yuan Electronic Technology Co. Ltd')
        self.assertEqual(dados['solicitante'], 'Sperk Comércio de Acessórios para Celular LTDA')
        self.assertEqual(dados['ocd'], 'Moderna Tecnologia LTDA')
        dados = self.ler('CPQD-i_12407_NOV_00A X.pdf')
        self.assertEqual(dados['solicitante'], 'Samsung Eletrônica da Amazônia Ltda.')
        self.assertEqual(dados['ocd'], 'FUNDAÇÃO CPQD')
        dados = self.ler('NCC_30803_26_Rev1_HP.pdf')
        self.assertEqual(dados['ocd'], 'NCC Certificações do Brasil Ltda')

    def test_classificacao_grandezas_e_erro_extracao(self):
        self.assertEqual(e.classificar_tabela(['Entrada','Saída']), 'caracteristicas_eletricas')
        self.assertEqual(e.classificar_tabela(['Frequência (Hz)','Potência de Saída (W)','PoE']), 'caracteristicas_eletricas')
        self.assertEqual(e.classificar_tabela(['Tipo de Alimentação','Fabricante','Modelo']), 'alimentacao_acessorios')
        self.assertEqual(e.classificar_tabela(['Unidades Fabris']), 'unidades_fabris')
        r = s.comparar_tabelas_tecnicas_sch_cct({}, {'status_extracao':'falha_extracao'})
        self.assertEqual(r['status'],'erro_extracao')
        self.assertFalse(r['divergencias'])

    def test_cpqd_classificacao_e_registros_repetidos(self):
        dados = self.ler('CPQD-i_12407_NOV_00A X.pdf')
        tipos = dados['diagnostico_extracao']['tipos_tabelas']
        self.assertEqual(tipos['radiofrequencia'], 2)
        self.assertEqual(tipos['alimentacao_acessorios'], 1)
        self.assertEqual(tipos['historico_revisao'], 1)
        regs = dados['tabela_tecnica_cct']['registros_normalizados']
        faixa = [r for r in regs if r['frequencia_inicial_mhz'] == 2400]
        self.assertEqual(len(faixa), 8)
        self.assertEqual(len({r['potencia_saida_w'] for r in faixa}), 8)
        self.assertTrue(all(r['potencia_eirp_w'] is None for r in faixa))
        self.assertEqual(len(s.analisar_sar_cct(dados)['valores_sar_encontrados']), 16)

    def test_moderna_perfis_eletricos_e_datas(self):
        dados = self.ler('13048-26_CERT_CONFORMIDADE.pdf')
        regs = dados['caracteristicas_eletricas']
        self.assertEqual(len(regs), 3)
        self.assertEqual(regs[0]['tensoes'], [{'inicial':100.,'final':240.,'unidade':'Vca'}])
        self.assertEqual(regs[0]['correntes_a'], [1.4])
        self.assertEqual(regs[0]['potencias_w'], [140.])
        self.assertEqual(regs[0]['frequencias_alimentacao'], ['50/60Hz'])
        self.assertEqual(regs[1]['potencias_w'], [18.])
        self.assertEqual(regs[2]['potencias_w'], [65.])
        self.assertEqual(regs[2]['quantidade'], 2)
        self.assertEqual(regs[2]['perfis_saida'][-1], {'tensao_v':20.,'tipo_tensao':'Vcc','corrente_a':3.25})
        self.assertTrue(all(r['pagina_origem']==2 and r['natureza']=='eletrica_nao_rf' for r in regs))
        self.assertEqual(dados['tipo_produto'], 'Carregador para Telefone Celular')
        for campo, valor in [('data_certificacao','23/06/2026'), ('data_emissao','20/08/2026'),
                             ('data_alteracao','20/08/2026'), ('data_validade','23/06/2028')]:
            self.assertEqual(dados[campo], valor)

    def test_moderna_observacoes_e_laboratorio(self):
        dados = self.ler('13048-26_CERT_CONFORMIDADE.pdf')
        obs = [sec for sec in dados['secoes_documento'] if sec['tipo']=='observacoes']
        self.assertEqual(len(obs), 2)
        self.assertTrue(all(sec['pagina_origem']==2 for sec in obs))
        self.assertIn('HREBOS', obs[0]['texto'])
        self.assertIn('baseado em ensaio de tipo', obs[1]['texto'])
        self.assertEqual(dados['observacao_texto'], '')
        labs = [t for t in dados['estruturas_documento'] if t['tipo']=='relatorios_ensaio']
        self.assertEqual(len(labs[0]['linhas']), 5)
        self.assertTrue(all('LABELO' in linha[0] for linha in labs[0]['linhas']))

    def test_ncc_modelos_laboratorios_historico(self):
        dados = self.ler('NCC_30803_26_Rev1_HP.pdf')
        modelos = {r['modelo']:r for r in dados['modelos_part_numbers']}
        self.assertEqual(len(modelos), 8)
        esperado = {'BJNGA-AD0114':(['S6X52A','S5T50A'],None),
                    'BJNGA-AD0116':(['S6X54A','S5T52A'],405.),
                    'BJNGA-AD0117':(['S6X57A','S5T54A'],125.),
                    'BJNGA-AD0118':(['S6X56A','S5T53A'],None),
                    'BJNGA-AD0130':(['S6X53A'],390.), 'BJNGA-AD0131':(['S6X55A'],248.),
                    'BJNGA-AD0113':(['S6X50A','S5T49A'],None), 'BJNGA-AD0115':(['S6X51A','S5T51A'],770.)}
        for modelo,(parts,poe) in esperado.items():
            self.assertEqual(modelos[modelo]['part_numbers'],parts)
            self.assertEqual(modelos[modelo]['potencia_poe_w'],poe)
            self.assertEqual(modelos[modelo]['pagina_origem'],3)
        labs = [t for t in dados['estruturas_documento'] if t['tipo']=='relatorios_ensaio']
        self.assertEqual(labs[0]['pagina_origem'],2)
        self.assertEqual(len(labs[0]['linhas']),8)
        self.assertTrue(all('Roseville' in linha[0] for linha in labs[0]['linhas'][:6]))
        self.assertTrue(all('Core Compliance' in linha[0] for linha in labs[0]['linhas'][6:]))
        historico = [t for t in dados['estruturas_documento'] if t['tipo']=='historico_revisao']
        self.assertEqual(historico[0]['pagina_origem'],4)
        self.assertEqual(len(historico[0]['linhas']),2)
        self.assertEqual(dados['data_emissao'],'04/09/2026')
        self.assertEqual(dados['data_certificacao'],'27/07/2026')
        self.assertEqual(dados['data_validade'],'27/07/2029')

    def test_observacao_e_sar_sem_copiar_secoes(self):
        dados = self.ler('CPQD-i_12407_NOV_00A X.pdf')
        self.assertEqual(s.decidir_texto_observacao_por_cct(dados)['texto'], s.OBS_RADIACAO_RESTRITA)
        self.assertFalse(s.analisar_sar_cct(dados)['preencher_frase'])
        for nome in ('13048-26_CERT_CONFORMIDADE.pdf','NCC_30803_26_Rev1_HP.pdf'):
            dados = self.ler(nome)
            self.assertEqual(dados['observacao_texto'],'')
            self.assertFalse(s.analisar_sar_cct(dados)['preencher_frase'])
        regra = p._classificar_observacao_cct('Produto não acabado, de uso interno.')
        self.assertEqual(s.decidir_texto_observacao_por_cct(regra)['texto'], s.OBS_PRODUTO_NAO_ACABADO)

    def test_nao_rf_sem_falsa_divergencia(self):
        for nome in ('13048-26_CERT_CONFORMIDADE.pdf','NCC_30803_26_Rev1_HP.pdf'):
            dados = self.ler(nome)
            cct = dados['tabela_tecnica_cct']
            self.assertEqual(dados['diagnostico_extracao']['status'],'sem_tabela_rf')
            self.assertEqual(s.comparar_tabelas_tecnicas_sch_cct({},cct)['status'],'nao_aplicavel')
            # Entrada SCH sintética: não representa captura do portal.
            sch = {'cabecalho':['Frequência (MHz)','Potência de Saída (W)'], 'linhas':[['2400 a 2483,5','0,1']]}
            comparacao = s.comparar_tabelas_tecnicas_sch_cct(sch,cct)
            self.assertEqual(comparacao['status'],'comparacao_parcial')
            self.assertFalse(comparacao['divergencias'])


if __name__ == '__main__':
    unittest.main()
