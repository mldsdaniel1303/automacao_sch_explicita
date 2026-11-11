"""Inspeciona eventos e configuração; nunca dispara eventos do checkbox."""
import json
from pathlib import Path
import sys

raiz=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
from navegador import criar_driver
from teste_controlado_acompanhar import CONTEXTO, SeleniumRestrito

pasta=Path(__file__).parent
d,w,_,_=criar_driver(navegador='chrome',pasta_base=pasta,
    caminho_driver=raiz/'diagnostico_sch/drivers/chromedriver156/chromedriver-win64/chromedriver.exe',debugger_address='127.0.0.1:58473')
a=SeleniumRestrito(d,w,pasta)
a._contexto()
resultado=a.investigar_renderizacao()
a._contexto()
if not resultado['checkbox'] or resultado['checkbox']['marcado']:
    raise RuntimeError('Estado inicial inesperado; inspeção não alterou checkbox.')
(pasta/'dom_eventos.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(resultado,ensure_ascii=True))
