"""Consolidação local dos resultados da execução autenticada, sem escrita SCH."""
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

pasta=Path(__file__).resolve().parent
raiz=pasta.parents[1]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
from diagnostico_estrutura_sch import comparar_captura_visual
from simulacao_simplificada_re import salvar_relatorios

r=json.loads((pasta/'simulacao_opcao4.json').read_text(encoding='utf-8'))
assert r['status']=='simulado' and r['gravacoes_executadas']==0
prova=r['confirmacao_cct_re']
assert prova['status']=='confirmado'
assert hashlib.sha256(Path(prova['arquivo']).read_bytes()).hexdigest()==prova['sha256']
log=(pasta/'testes.log').read_bytes()
log=log.decode('utf-16' if log.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
numero=re.search(r'Ran (\d+) tests',log)
assert numero and re.search(r'^OK\s*$',log,re.M) and not re.search(r'^FAILED',log,re.M)
r['testes']={'aprovados':int(numero.group(1)),'resultado':'OK','log':str(pasta/'testes.log'),
             'anteriores_preservados':115,'novos':int(numero.group(1))-115}
fixture=json.loads((raiz/'tests/fixtures/ccts/sch_cpqd_transcricao_capturas.json').read_text(encoding='utf-8'))
r['comparacao_fixture_visual']=comparar_captura_visual(r['estado_leitura']['tabelas_dom']['tabelas'][0],fixture)
r['captura_autenticada_real']=True
r['identidade_iframe']=json.loads((raiz/'diagnostico_sch/01553_25/20261104_114814/captura_sch.json').read_text(encoding='utf-8'))['identidade_antes']['vinculo_iframe']
r['navegador_aberto_ao_final']=bool(json.load(urllib.request.urlopen('http://127.0.0.1:58473/json/version',timeout=5)).get('Browser'))
r['acoes_ainda_bloqueadas']=[
    'Todas as gravações nesta etapa; teste posterior exige autorização específica.',
    'Aprovar/Recusar e aprovação automática.',
    'Modificar CTS ausente, Especificações Complementares, datas ou resolver EIRP automaticamente.',
    'Percorrer a fila em teste controlado: o escopo proposto é somente 01553/25.',
]
salvar_relatorios(r,pasta)
print(json.dumps({'status':r['status'],'sha256':prova['sha256'],'testes':r['testes']['aprovados'],
                  'fixture':r['comparacao_fixture_visual']['status'],
                  'pronto_limitado':r['plano']['pronto_para_escrita_controlada'],
                  'navegador_aberto':r['navegador_aberto_ao_final']},ensure_ascii=True))
