import copy
from pathlib import Path
import sys
import unittest
import tempfile
import hashlib
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'automacao_sch_explicita'))
import fluxo_sch as f
import funcoes_sch as s
import gerador_relatorio as g
import pdf_parser as p
import mvp_simplificada_re as m
from selenium.common.exceptions import TimeoutException


class ExecucaoRETests(unittest.TestCase):
    def test_datas_integradas_preservam_eventos_e_origens(self):
        for inicial, revisao, sch, status in [('15/05/2026','10/06/2026','15/05/2026','ok'),
                ('18/05/2026','04/08/2026','18/05/2026','ok'),
                ('10/06/2026','01/09/2026','02/03/2027','divergente')]:
            dados={'data_certificacao':inicial,'data_emissao':revisao,'data_validade':'10/06/2028'}
            resumo={'modo_analise_re':'analise_simplificada'}
            with patch.object(f,'parsear_certificado_pdf',return_value=copy.deepcopy(dados)), patch.object(f,'avaliar_validade_cct',return_value={}):
                f._conferir_cct_sch_independente_re(None,None,{},'fake.pdf',
                    {'data_certificado':sch,'data_validade':'10/06/2028'},resumo,False)
            self.assertEqual(resumo['comparacao_datas_sch_cct']['status_geral'],status)
            self.assertEqual(resumo['dados_pdf']['data_emissao'],revisao)
            self.assertEqual(resumo['dados_pdf']['data_certificacao'],inicial)
            linhas=dict(g._linhas_tabela_cct(resumo))
            self.assertEqual(linhas['Data de emissão'],revisao)
            self.assertEqual(linhas['Data da certificação inicial'],inicial)

    def test_rotulo_bilingue_nao_aceita_endereco(self):
        for texto in ('Rod Br-999, Km 10, CEP: 00000-000', '381 Estrada, Km 10, Armz 2',
                      'No. B602, Building 1, Street 2'):
            self.assertTrue(p._parece_endereco_empresa(texto))
            self.assertEqual(p._empresa_em_rotulo_bilingue(['Nome e endereço do solicitante '+texto], 'solicitante'),'')
        self.assertFalse(p._parece_endereco_empresa('Empresa Sintetica LTDA'))

    def test_tipo_explicito_eta_prevalece_sobre_mencao_rr(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as pasta:
            arquivo=Path(pasta)/'sintetico.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((30,30),'TIPO DE PRODUTO / Type of Product:\nEstacao terminal de acesso - ETA\nObservacao: radiacao restrita')
                pdf.save(arquivo)
            dados=p.parsear_certificado_pdf(arquivo)
        self.assertEqual(dados['tipo_produto'],'Estacao terminal de acesso - ETA')

    def test_sigla_documental_nao_cria_equivalencia_entre_eta_e_rr(self):
        req={'tipo_produto':'Estação Terminal de Acesso'}
        for nome,diverge in [('Estação terminal de acesso – ETA',False),('Transceptor de Radiação Restrita',True)]:
            r=s.comparar_dados_sch_x_cct(req,{'tipo_produto':nome,'tipo_produto_origem':'rotulo_explicito_cct'},modo_simplificado=True)
            self.assertEqual(next(c for c in r['comparacoes'] if c['campo']=='tipo_produto')['diverge'],diverge)

    def salvar(self, texto='obs', erro=None):
        driver=Mock();botao=Mock();driver.find_elements.return_value=[botao]
        botao.is_displayed.return_value=True;botao.is_enabled.return_value=True
        botao.click.side_effect=erro;driver.execute_script.return_value=texto
        return driver,botao

    def contexto_salvar(self):
        from contextlib import ExitStack
        c=ExitStack()
        for nome in ('entrar_iframe_detalhe_analise','esperar_tela_carregar','clicar_aba_caracteristicas_tecnicas'):
            c.enter_context(patch.object(s,nome))
        c.enter_context(patch.object(s,'WebDriverWait')).return_value.until.side_effect=TimeoutException('sem alerta')
        c.enter_context(patch.object(m,'ler_observacao_atual_re',return_value={'localizado':True,'texto':'obs'}))
        return c

    def test_salvar_uma_vez_e_reabrir_antes_de_confirmar(self):
        driver,botao=self.salvar()
        with self.contexto_salvar(), patch.object(s,'_clicar_com_fallback') as retry:
            r=s.salvar_caracteristicas_tecnicas(driver,Mock(),'obs',confirmacao_conservadora=True)
            s.clicar_aba_caracteristicas_tecnicas.assert_called_once()
        self.assertTrue(r['confirmado_apos_salvar']);botao.click.assert_called_once();retry.assert_not_called()

    def test_sem_confirmacao_nao_significa_gravacao_falhou(self):
        driver,botao=self.salvar('outro')
        with self.contexto_salvar(), patch.object(m,'ler_observacao_atual_re',return_value={'localizado':True,'texto':'outro'}):
            r=s.salvar_caracteristicas_tecnicas(driver,Mock(),'obs',confirmacao_conservadora=True)
        self.assertIsNone(r['salvo']);self.assertTrue(r['estado_servidor_indeterminado'])
        botao.click.assert_called_once()

    def test_timeout_no_clique_nunca_usa_fallback(self):
        driver,botao=self.salvar(erro=TimeoutException('resposta perdida'))
        with self.contexto_salvar(), patch.object(s,'_clicar_com_fallback') as retry:
            with self.assertRaises(TimeoutException):s.salvar_caracteristicas_tecnicas(driver,Mock(),'obs',confirmacao_conservadora=True)
        botao.click.assert_called_once();retry.assert_not_called()

    def test_estado_pendente_bloqueia_nova_tentativa(self):
        req={'_salvamento_ct_pendente':{'estado_servidor_indeterminado':True}}
        with patch.object(m,'ler_observacao_atual_re') as ler:
            with self.assertRaises(m.SalvamentoCTIndeterminado):m.preencher_caracteristicas_conservadoras_re(None,None,req,[],{})
        ler.assert_not_called()

    def test_erro_na_releitura_preserva_tentativa_pendente_no_relatorio(self):
        req={'requerimento':'00123/99','tipo_produto':'Transceptor de Radiação Restrita',
             'modelo_sch_dados_gerais':'Modelo','_salvamento_ct_pendente':{'tentativa_iniciada':True}}
        resumo={'pdf_cct':'fake.pdf','dados_pdf':{'numero_certificado':'TEST'},
                'dados_certificado_sch':{'numero_certificado':'TEST'},
                'conferencia_sch_cct':{'status_geral':'parcial'}}
        with tempfile.TemporaryDirectory() as pasta:
            arquivo=Path(pasta)/'fake.pdf';arquivo.write_bytes(b'fixture sintetica')
            resumo['pdf_cct']=str(arquivo)
            resumo['confirmacao_cct_re']={'status':'confirmado','arquivo':str(arquivo),
                'sha256':hashlib.sha256(arquivo.read_bytes()).hexdigest()}
            with patch.object(f,'extrair_dados_certificado_sch',return_value={'numero_certificado':'TEST','modelo_sch_dados_gerais':'Modelo'}), \
                 patch.object(f,'preencher_caracteristicas_conservadoras_re',side_effect=TimeoutException('releitura')):
                r=f._preencher_abas_com_regras_em_analise_no_re(Mock(),Mock(),req,resumo)
        self.assertTrue(r['caracteristicas_tecnicas']['estado_servidor_indeterminado'])
        self.assertFalse(r['caracteristicas_tecnicas']['repetir_automaticamente'])

    def test_relatorio_preserva_indeterminacao(self):
        texto=g._html_preenchimento_simplificado_re({'modo_analise_re':'analise_simplificada',
            'preenchimento_analise_simplificada_re':{'caracteristicas_tecnicas':{'estado_servidor_indeterminado':True}}})
        self.assertIn('INDETERMINADO',texto)


if __name__=='__main__':unittest.main()
