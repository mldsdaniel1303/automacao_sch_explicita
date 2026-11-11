"""Consolida artefatos locais; consulta apenas o endpoint local do navegador."""
import datetime
import json
from pathlib import Path
import sys
import urllib.request

raiz = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(raiz / 'automacao_sch_explicita'))
from diagnostico_estrutura_sch import comparar_captura_visual
from simulacao_simplificada_re import salvar_relatorios

pasta = Path(__file__).resolve().parent
r = json.loads((pasta / 'simulacao_opcao4.json').read_text(encoding='utf-8'))
assert r['status'] == 'simulado' and r['gravacoes_executadas'] == 0
fixture = json.loads((raiz / 'tests/fixtures/ccts/sch_cpqd_transcricao_capturas.json').read_text(encoding='utf-8'))
r['comparacao_fixture_visual'] = comparar_captura_visual(r['estado_leitura']['tabelas_dom']['tabelas'][0], fixture)
r['captura_autenticada_real'] = True
r['registro_final_em'] = datetime.datetime.now().astimezone().isoformat()
limites = [
    'CTS: campo de título não localizado; revisar antes de autorizar escrita CTS.',
    'PDF local reutilizado por nome do último anexo; sem novo download ou verificação binária.',
    '18 linhas ambíguas com coincidência apenas EIRP; conformidade integral não comprovada.',
]
for limite in limites:
    if limite not in r['riscos']:
        r['riscos'].append(limite)
r['navegador_aberto_ao_final'] = bool(json.load(urllib.request.urlopen('http://127.0.0.1:58473/json/version', timeout=5)).get('Browser'))
salvar_relatorios(r, pasta)
(pasta / 'comparacao_fixture_visual.json').write_text(json.dumps(r['comparacao_fixture_visual'], ensure_ascii=False, indent=2), encoding='utf-8')
falha = pasta / 'falha_leitura.json'
if falha.exists() and not (pasta / 'falha_tentativa_anterior.json').exists():
    falha.rename(pasta / 'falha_tentativa_anterior.json')
print(json.dumps(r['comparacao_fixture_visual'], ensure_ascii=True))
print('Browser aberto:', r['navegador_aberto_ao_final'])
