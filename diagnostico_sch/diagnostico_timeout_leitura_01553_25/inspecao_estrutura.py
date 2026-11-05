"""Inspeção de leitura; não altera campos ou abre outras seções."""
import json
from pathlib import Path
import sys

raiz=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
from navegador import criar_driver
from diagnostico_estrutura_sch import contexto_iframe
from teste_controlado_acompanhar import CONTEXTO
import funcoes_sch as s

d,w,_,_=criar_driver(navegador='chrome',pasta_base=Path(__file__).parent,
    caminho_driver=raiz/'diagnostico_sch/drivers/chromedriver156/chromedriver-win64/chromedriver.exe',debugger_address='127.0.0.1:58473')
if contexto_iframe(d)!=CONTEXTO:
    raise RuntimeError('Contexto divergente; inspeção cancelada.')
ta=s._localizar_textarea_acompanhar_processo(d,w,timeout=2)
cb=s._localizar_checkbox_acompanhar_processo(d,w,timeout=2)
r=d.execute_script("""const desc=e=>({id:e.id,tag:e.tagName,tipo:e.type,rotulos:Array.from(e.labels||[]).map(l=>({texto:l.textContent,para:l.htmlFor}))});
return [arguments[0],arguments[1]].map(e=>{let p=e;const ancestrais=[];for(let i=0;p&&i<5;i++,p=p.parentElement){ancestrais.push({id:p.id,tag:p.tagName,campos:Array.from(p.querySelectorAll('input:not([type=hidden]),textarea')).map(desc),rotulos:Array.from(p.querySelectorAll('label,legend,h1,h2,h3,td,span')).filter(l=>!l.children.length && /acompanhar|processo|informaç|descriç|justifica/i.test(l.textContent)).map(l=>({texto:l.textContent,para:l.htmlFor,id:l.id}))})}return {alvo:desc(e),ancestrais}});""",ta,cb)
(Path(__file__).parent/'estrutura_controles.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=True))
