"""Consolida evidências existentes; não conecta ao navegador ou ao SCH."""
import json
from pathlib import Path
import re
import sys

pasta=Path(__file__).resolve().parent
raiz=pasta.parents[1]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
import teste_controlado_acompanhar as t

dom=t.ler_json(pasta/'dom_eventos.json')
assert dom['estado_preservado'] and dom['checkbox']['marcado'] is False
assert dom['handlers_executados'] is False and dom['evidencia_ajax']['vinculo_ajax_confirmado']
assert t.vinculo_ajax_confirmado(dom['evidencia_ajax']['callback_change'])
arquivo=max((pasta/'preparacao_leitura').glob('*/resultado.json'),key=lambda p:p.stat().st_mtime)
preparo=t.ler_json(arquivo)
assert preparo['status']=='preparado_condicional_sem_gravacao'
assert preparo['antes']['texto'] is None and preparo['antes']['marcado'] is False
assert not preparo['salvamento']['tentativa_iniciada'] and not t.TRAVA_REAL.exists()
raw=(raiz/'diagnostico_sch/testes_renderizacao_condicional.log').read_bytes()
log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
numero=re.search(r'Ran (\d+) tests',log)
assert numero and re.search(r'^OK\s*$',log,re.M) and not re.search(r'^FAILED',log,re.M)
r={'ambiente':'investigacao_autenticada_somente_leitura_com_testes_locais_separados',
   'requerimento':t.REQUERIMENTO,'status':'vinculo_ajax_comprovado_sem_exercitar_marcacao_real',
   'estrutura_real':dom,
   'ajax_comprovado':{'source':'formAnalise:checkBoxAcompanharProcesso','event':'change',
                      'process':'formAnalise:checkBoxAcompanharProcesso','update':'formAnalise:textAreaPanel'},
   'resposta_ajax_real_apos_marcacao':{'executada':False,'textarea_criado':'não comprovado por resposta real nesta etapa',
                                      'outras_condicoes_servidor':'não podem ser excluídas pela inspeção do callback'},
   'preparacao_somente_leitura':{'arquivo':str(arquivo),'status':preparo['status'],
                               'texto_inicial':None,'checkbox_inicial':False,'tentativa_salvar':False},
   'rotina_futura':{'autorizacao_condicional_obrigatoria':True,'confirmacao_exata':t.CONFIRMACAO_CONDICIONAL,
                    'sequencia':['identidade e estado','autorização e confirmação','reserva única','clique normal único',
                                 'espera AJAX','único textarea superior','leitura real e cancelamento se não vazio',
                                 'preenchimento autorizado','conferência dos demais campos','Salvar único','releitura do servidor'],
                    'falha_apos_ajax':'reserva retida, estado do servidor indeterminado, sem retry ou desmarcação automática'},
   'testes':{'aprovados':int(numero.group(1)),'anteriores_preservados':161,'novos':int(numero.group(1))-161,
             'ambiente_novos':'memória e HTML file:// em headless próprio; não são prova de resposta real do SCH',
             'log':'diagnostico_sch/testes_renderizacao_condicional.log'},
   'alteracoes_reais':{'marcacoes_checkbox':0,'handlers_checkbox_executados':0,'salvamentos':0,'autorizacao_concedida':False},
   'problemas_restantes':['A resposta real após marcação não foi executada; o servidor ainda pode não renderizar o campo.',
                         'Valor real será lido somente após futura marcação autorizada, sem presumir vazio.',
                         'Mensagem e persistência reais após Salvar permanecem para etapa institucional posterior.'],
   'regras_preservadas':['Descrição inferior','Justificativa OCD','Observação','CTS','SAR','Especificações Complementares',
                       'datas','anexos','tabelas técnicas','18 correspondências EIRP inconclusivas','sem aprovação automática',
                       'fila Em Análise e RE tradicional'],
   'documentacao':'docs/RENDERIZACAO_ACOMPANHAR.md'}
t.persistir(r,pasta)
print(json.dumps({'status':r['status'],'testes':r['testes']['aprovados'],'marcacoes_reais':0,
                  'saida':str(pasta)},ensure_ascii=True))
