"""Somente consolidação local; nunca conecta ao navegador ou ao SCH."""
import json
from pathlib import Path
import re
import sys

pasta=Path(__file__).resolve().parent
raiz=pasta.parents[1]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
import validacao_ajax_supervisionada as v

raw=(raiz/'diagnostico_sch/testes_validacao_ajax_supervisionada.log').read_bytes()
log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
n=re.search(r'Ran (\d+) tests',log)
assert n and re.search(r'^OK\s*$',log,re.M) and not re.search(r'^FAILED',log,re.M)
modelo=v.base.ler_json(raiz/'docs/autorizacao_ajax_01553_25.modelo.json')
assert modelo['autorizado'] is False and modelo['ciente_alteracao_estado_sessao'] is False
r={'ambiente':'preparacao_codigo_sem_interacao_real_SCH','status':'procedimento_supervisionado_preparado',
   'requerimento_permitido':v.base.REQUERIMENTO,
   'identidade_a_revalidar':{'contexto':v.base.CONTEXTO,'tipo':v.base.TIPO,'certificado':v.base.CERTIFICADO,'modelo':v.base.MODELO},
   'autorizacao_institucional_recebida_nesta_tarefa':False,'confirmacao_operador_recebida':False,
   'confirmacao_futura_exigida':v.CONFIRMACAO,'acoes_autorizaveis_exclusivas':v.ACOES,
   'dom_inicial_real_nesta_tarefa':None,'resposta_ajax_real_nesta_tarefa':None,
   'acoes_reais_executadas':{'marcar':0,'preencher':0,'Salvar':0,'Aprovar':0,'Recusar':0,'Exigencia':0},
   'reserva_real_existe':v.base.TRAVA_REAL.exists(),
   'testes_locais':{'aprovados':int(n.group(1)),'anteriores_preservados':174,'novos':int(n.group(1))-174,
                    'ambiente':'Memória, HTML local e HTTP em 127.0.0.1 com headless próprio. Nenhum SCH autenticado.',
                    'log':'diagnostico_sch/testes_validacao_ajax_supervisionada.log'},
   'protecao':{'texto_e_salvar_negados_mesmo_habilitado':True,'autorizacao_especifica_e_TTY':True,
               'reserva_unica_compartilhada_com_teste_salvamento':True,'sem_retry_ou_reversao':True,
               'DOM_e_HTTP_novo_observados_passivamente':True,'conteudo_nao_vazio_registrado_sem_sobrescrever':True,
               'estado_servidor_permanece_indeterminado_sem_prova_de_persistencia':True},
   'pendencias':['Autorização institucional e confirmação explícita do operador.',
                 'Uma interação real supervisionada posterior para comprovar a resposta e o campo real.',
                 'Nenhum preenchimento ou salvamento é autorizado por este modo ou por este relatório.'],
   'procedimento':'docs/VALIDACAO_AJAX_SUPERVISIONADA.md','modelo_autorizacao':'docs/autorizacao_ajax_01553_25.modelo.json'}
v.base.persistir(r,pasta)
print(json.dumps({'status':r['status'],'testes':r['testes_locais']['aprovados'],
                  'interacoes_SCH_executadas':0,'saida':str(pasta)},ensure_ascii=True))
