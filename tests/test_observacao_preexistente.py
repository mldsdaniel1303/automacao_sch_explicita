"""Contratos sintéticos de preservação, referência processual e salvamento."""
from contextlib import ExitStack
from html.parser import HTMLParser
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from selenium.common.exceptions import TimeoutException

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ/'automacao_sch_explicita'))
import mvp_simplificada_re as m
import funcoes_sch as s
import gerador_relatorio as g

ALVO = 'Texto autorizado pela regra sintética do processo.'


def referencia(texto=ALVO):
    return {'texto': texto, 'origem': 'fixture processual sintética',
            'regra': 'regra sintética explicitamente verificada',
            'evidencia': 'documento sintético do teste', 'comprovada': True}


def dados(texto=ALVO):
    return {'tipo_produto': 'Transceptor de Radiação Restrita',
            'observacao_texto': texto, 'observacao_classificacao': 'regra_sintetica_documentada',
            'observacao_motivos': ['referência sintética de teste; não é o payload de 13/11']}


def plano(atual, alvo=ALVO, produto='Transceptor de Radiação Restrita'):
    with patch.object(s, 'diagnosticar_titulo_caracteristicas_secundarias', return_value={'titulo': ''}), \
         patch.object(s, 'analisar_sar_cct', return_value={'preencher_frase': False}):
        return m.planejar_acoes_simplificadas(
            dict(tipo_produto=produto, **({'referencia_observacao_processual': referencia(alvo)} if alvo else {})), {'dados_pdf': dict(dados(alvo), tipo_produto=produto)},
            {'observacao': {'localizado': True, 'texto': atual},
             'cts': {'localizado': False, 'status': 'nao_aplicavel_ausencia_confirmada'},
             'acompanhar': {'localizado': False}})


def contexto(atual, retorno_salvar=None, erro=None, alvo=ALVO):
    c = ExitStack()
    leituras = [{'localizado': True, 'texto': atual}, {'localizado': True, 'texto': alvo}]
    ler = c.enter_context(patch.object(m, 'ler_observacao_atual_re', side_effect=leituras))
    preencher = c.enter_context(patch.object(s, 'preencher_observacao_caracteristicas', return_value=True))
    salvar = c.enter_context(patch.object(s, 'salvar_caracteristicas_tecnicas',
        return_value=retorno_salvar, side_effect=erro))
    c.enter_context(patch.object(s, 'diagnosticar_campo_cts_re', return_value={
        'status': 'nao_aplicavel_ausencia_confirmada', 'motivo': 'fixture sintética'}))
    c.enter_context(patch.object(s, 'preencher_titulo_caracteristicas_secundarias_se_existir',
        side_effect=AssertionError('CTS não deve ser editado')))
    return c, ler, preencher, salvar


class Linhas(HTMLParser):
    def __init__(self):
        super().__init__(); self.linhas=[]; self.linha=None; self.celula=None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.linha=[]
        elif tag == 'td' and self.linha is not None: self.celula=''
    def handle_data(self, texto):
        if self.celula is not None: self.celula += texto
    def handle_endtag(self, tag):
        if tag == 'td' and self.celula is not None:
            self.linha.append(self.celula); self.celula=None
        elif tag == 'tr' and self.linha is not None:
            self.linhas.append(self.linha); self.linha=None


def linha_relatorio(ct):
    h = g._html_preenchimento_simplificado_re({'modo_analise_re': 'analise_simplificada',
        'preenchimento_analise_simplificada_re': {'caracteristicas_tecnicas': ct}})
    p=Linhas(); p.feed(h)
    return next(l for l in p.linhas if l and 'Observação' in l[0])


class ComportamentoAtualTests(unittest.TestCase):
    def test_valor_correto_preexistente_nao_preenche_nem_salva(self):
        c,ler,preencher,salvar=contexto(ALVO)
        with c:
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),{'referencia_observacao_processual':referencia()},[],dados())
        self.assertEqual(r['status'],'preservada')
        self.assertEqual(r['texto'],ALVO); self.assertTrue(r['sem_alteracao'])
        self.assertTrue(r['observacao']['comparacao']['validado_como_correto'])
        self.assertFalse(r['observacao']['comparacao']['salvamento_anterior_comprovado'])
        self.assertFalse(r['salvo']); self.assertFalse(r['confirmado_apos_salvar'])
        preencher.assert_not_called(); salvar.assert_not_called()

    def test_plano_com_valor_igual_nao_propoe_edicao_da_observacao(self):
        r=plano(ALVO)
        self.assertFalse(any(a['campo']=='Observação' for a in r['campos_que_seriam_alterados']))

    def test_valor_diferente_tambem_e_preservado_sem_escrita(self):
        c,ler,preencher,salvar=contexto('Texto preexistente diferente.')
        with c:
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),{'referencia_observacao_processual':referencia()},[],dados())
        self.assertEqual(r['texto'],'Texto preexistente diferente.')
        self.assertEqual(r['observacao']['comparacao']['status'],'revisar')
        self.assertEqual(r['observacao']['comparacao']['valor_alvo'],ALVO)
        self.assertEqual(r['status'],'preservada')
        preencher.assert_not_called(); salvar.assert_not_called()

    def test_alvo_desconhecido_nao_preenche_campo_vazio(self):
        c,ler,preencher,salvar=contexto('',alvo='')
        with c:
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),
                {'tipo_produto':'Estação Terminal de Acesso'},[],{'tipo_produto':'Estação Terminal de Acesso'})
        self.assertEqual(r['status'],'revisao_manual')
        preencher.assert_not_called(); salvar.assert_not_called()

    def test_confirmacao_futura_somente_mockada(self):
        c,ler,preencher,salvar=contexto('',{'salvo':True,'confirmado_apos_salvar':True})
        req={}
        with c:
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),req,[],dados())
        self.assertTrue(r['salvo']); self.assertTrue(r['confirmado_apos_salvar'])
        salvar.assert_called_once(); self.assertNotIn('_salvamento_ct_pendente',req)

    def test_confirmacao_inconclusiva_nao_repete_na_mesma_execucao(self):
        c,ler,preencher,salvar=contexto('',{'salvo':None,'confirmado_apos_salvar':False,
            'estado_servidor_indeterminado':True,'tentativa_iniciada':True})
        req={}
        with c:
            for tentativa in range(2):
                with self.assertRaises(m.SalvamentoCTIndeterminado):
                    m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),req,[],dados())
        salvar.assert_called_once(); preencher.assert_called_once(); ler.assert_called_once()

    def test_timeout_nao_repete_na_mesma_execucao(self):
        c,ler,preencher,salvar=contexto('',erro=TimeoutException('mock: resposta perdida'))
        req={}
        with c:
            for tentativa in range(2):
                with self.assertRaises(m.SalvamentoCTIndeterminado):
                    m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),req,[],dados())
        salvar.assert_called_once(); ler.assert_called_once()
        self.assertEqual(req['_salvamento_ct_pendente']['causa'],'timeout')

    def test_relatorio_confirmado_e_indeterminado_explicitamente_diferentes(self):
        confirmado=linha_relatorio({'status':'preenchida','salvo':True,'confirmado_apos_salvar':True})
        incerto=linha_relatorio({'status':'resultado_indeterminado','salvo':None,
                                'estado_servidor_indeterminado':True})
        self.assertIn('CONFIRMADO',confirmado[2]); self.assertIn('INDETERMINADO',incerto[2])

    def test_relatorio_preexistente_nao_e_novo_salvamento_confirmado(self):
        l=linha_relatorio({'status':'preservada','sem_alteracao':True,
                           'salvo':False,'confirmado_apos_salvar':False})
        self.assertEqual(l[1],'preservada'); self.assertNotIn('SIM',l[2])


class LacunasContratoTests(unittest.TestCase):
    def test_diferenca_do_alvo_deve_ser_registrada_como_necessidade_de_revisao(self):
        r=plano('Valor incompatível com o alvo sintético comprovado.')
        necessidade=any(a['campo']=='Observação' for a in r['campos_que_seriam_alterados'])
        revisao=any('Observação' in x and ('diverg' in x.lower() or 'alvo' in x.lower()) for x in r['acoes_bloqueadas'])
        self.assertTrue(necessidade or revisao,'Diferença ignorada: plano apenas preserva o existente.')

    def test_alvo_desconhecido_com_campo_preenchido_deve_ficar_inconclusivo(self):
        r=plano('Texto atual.',alvo='',produto='Estação Terminal de Acesso')
        obs=r['observacao']
        self.assertTrue('inconclus' in obs['decisao'] or 'revisar' in obs['decisao'] or
                        (obs.get('comparacao') or {}).get('status') in {'inconclusivo','evidencia_insuficiente'},
                        'Preservação não informa se o alvo é conhecido ou foi validado.')

    def test_relatorio_salvo_sem_confirmacao_nao_pode_dizer_operacao_desnecessaria(self):
        l=linha_relatorio({'status':'preenchida','salvo':True,'confirmado_apos_salvar':False})
        self.assertNotIn('NÃO NECESSÁRIO',l[2], 'Tentativa sem confirmação foi agrupada com operação não necessária.')


class ProtecoesReferenciaTests(unittest.TestCase):
    def test_sugestao_do_parser_nao_comprova_alvo_para_preexistente(self):
        c,ler,preencher,salvar=contexto(ALVO)
        with c:
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),{},[],dados())
        comp=r['observacao']['comparacao']
        self.assertEqual(comp['status'],'inconclusivo')
        self.assertIsNone(comp['valor_alvo'])
        self.assertFalse(comp['validado_como_correto'])
        preencher.assert_not_called(); salvar.assert_not_called()

    def test_prova_incompleta_ou_flag_textual_nao_sao_aceitas(self):
        for chave in ('texto','origem','regra','evidencia','comprovada'):
            ref=referencia();ref.pop(chave)
            self.assertEqual(m.comparar_observacao_preexistente({'localizado':True,'texto':ALVO},ref)['status'],'inconclusivo')
        ref=referencia();ref['comprovada']='True'
        self.assertFalse(m.comparar_observacao_preexistente({'localizado':True,'texto':ALVO},ref)['referencia_comprovada'])

    def test_cts_legitima_independente_de_observacao_correta(self):
        c,ler,preencher,salvar=contexto(ALVO,{'salvo':True,'confirmado_apos_salvar':True})
        with c, patch.object(s,'diagnosticar_campo_cts_re',return_value={'status':'localizado_confirmado'}), \
             patch.object(s,'preencher_titulo_caracteristicas_secundarias_se_existir',return_value={
                 'status':'corrigido','corrigido':True,'titulo_esperado':'Titulo sintetico'}):
            r=m.preencher_caracteristicas_conservadoras_re(Mock(),Mock(),
                {'referencia_observacao_processual':referencia()},[],dados())
        preencher.assert_not_called();salvar.assert_called_once()
        self.assertTrue(r['salvo'])
        self.assertFalse(r['observacao']['salvo'])
        self.assertTrue(r['titulo_caracteristicas_secundarias']['salvo'])
        linha=linha_relatorio(r)
        self.assertIn('CORRETO E PRESERVADO',linha[1])
        self.assertIn('DISPENSÁVEL',linha[2])

    def test_relatorio_valores_e_origem_sao_escapados(self):
        ref=referencia('<script>alvo</script>')
        comp=m.comparar_observacao_preexistente({'localizado':True,'texto':'Texto atual'},ref)
        ct={'status':'preservada','observacao':{'status':'preservada','comparacao':comp,'preexistente':True}}
        h=g._html_preenchimento_simplificado_re({'modo_analise_re':'analise_simplificada',
            'preenchimento_analise_simplificada_re':{'caracteristicas_tecnicas':ct}})
        self.assertIn('REVISAR',h)
        self.assertIn('Alvo comprovado:',h)
        self.assertIn(ref['origem'],h)
        self.assertIn('&lt;script&gt;',h);self.assertNotIn('<script>',h)

    def test_legado_indeterminado_prevalece_sobre_dispensa(self):
        for etapa in ({'salvo':True,'confirmado_apos_salvar':False,'sem_alteracao':True},
                      {'salvo':True,'operacao_necessaria':False},
                      {'tentativa_iniciada':True,'sem_alteracao':True},
                      {'salvo':True,'confirmado_apos_salvar':True,'estado_servidor_indeterminado':True}):
            self.assertIn('INDETERMINADO',g._rotulo_salvamento_simplificado(etapa))
        self.assertIn('DISPENSÁVEL',g._rotulo_salvamento_simplificado({'operacao_necessaria':False}))


if __name__=='__main__':
    unittest.main()
