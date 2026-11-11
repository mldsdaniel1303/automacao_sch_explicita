"""Relatório de preparação do código. Não conecta ao navegador ou ao SCH."""
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

pasta=Path(__file__).resolve().parent
raiz=pasta.parents[1]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
import teste_controlado_acompanhar as t

fonte=raiz/'diagnostico_sch/correcoes_finais_01553_25/simulacao_opcao4.json'
sim=t.ler_json(fonte)
baseline=t.validar_simulacao(sim,t.REQUERIMENTO)
log=(raiz/'diagnostico_sch/testes_controlado_preparacao.log').read_bytes()
log=log.decode('utf-16' if log.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
total=re.search(r'Ran (\d+) tests',log)
assert total and re.search(r'^OK\s*$',log,re.M) and not re.search(r'^FAILED',log,re.M)
assert not t.TRAVA_REAL.exists(), 'Há reserva real: revisar antes de declarar preparação sem tentativa.'
r={'ambiente':'preparacao_codigo_sem_conexao_SCH','status':'implementado_e_testado_sem_gravacao_real',
   'identidade_de_referencia':baseline['simulacao'],
   'fonte_simulacao':{'arquivo':str(fonte),'sha256':sha256(fonte.read_bytes()).hexdigest()},
   'antes':{'origem':'Snapshot autenticado anterior; não é uma nova leitura do SCH nesta tarefa.',
            'texto':baseline['texto'],'marcado':baseline['marcado']},
   'proposto':{'texto':t.FRASE,'marcado':True},
   'autorizacao':{'institucional_recebida_nesta_etapa':False,'confirmacao_operador':None,
                  'modelo_desautorizado':'docs/autorizacao_controlada_01553_25.modelo.json'},
   'salvamento':{'tentativa_iniciada':False,'cliques_Salvar_no_SCH':0},
   'depois':None,'confirmacao_persistencia_real':'Não executada; depende do teste institucional posterior.',
   'campos_preservados':'Nenhum campo do SCH foi acessado para escrita nesta tarefa. Comparações de persistência reais pendentes.',
   'datas_para_revisao_humana':baseline['datas_para_revisao'],
   'testes':{'ambiente':'memória e HTML file:// em headless próprio','aprovados':int(total.group(1)),
             'anteriores_preservados':125,'novos':int(total.group(1))-125,
             'log':'diagnostico_sch/testes_controlado_preparacao.log'},
   'falhas_pendentes':[],
   'limites':['Escrita exige autorização institucional e confirmação TTY posterior.',
             'Somente 01553/25 e Acompanhar Processo superior.',
             'Reserva persistente exclusiva; sem retry, fallback ou reversão.',
             'Mensagem e persistência reais ainda não exercitadas.',
             'Inventário é evidência DOM, não auditoria do banco de dados.',
             '18 correspondências EIRP inconclusivas preservadas.'],
   'documentacao':'docs/TESTE_CONTROLADO_ACOMPANHAR.md'}
t.persistir(r,pasta)
print(json.dumps({'status':r['status'],'testes_aprovados':r['testes']['aprovados'],
                  'tentativa_real':False,'saida':str(pasta)},ensure_ascii=True))
