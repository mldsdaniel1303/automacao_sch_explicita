"""Lê metadados de closures via CDP. Não chama handlers nem pausa a página."""
import json
from pathlib import Path
import sys

raiz=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(raiz/'automacao_sch_explicita'))
from navegador import criar_driver
from teste_controlado_acompanhar import SeleniumRestrito

pasta=Path(__file__).parent
d,w,_,_=criar_driver(navegador='chrome',pasta_base=pasta,
    caminho_driver=raiz/'diagnostico_sch/drivers/chromedriver156/chromedriver-win64/chromedriver.exe',debugger_address='127.0.0.1:58473')
a=SeleniumRestrito(d,w,pasta)
a._contexto()
expressao="""(()=>{const id='formAnalise:checkBoxAcompanharProcesso_input';let doc=document;
 if(!doc.getElementById(id)){const frame=Array.from(document.querySelectorAll('iframe')).find(f=>{try{return new URL(f.src).searchParams.get('idRequerimento')==='81916'}catch(_){return false}});doc=frame?.contentDocument}
 if(!doc)throw Error('Documento fixado não encontrado');
 const ev=doc.defaultView.jQuery._data(doc.getElementById(id),'events');return ev.change[0].handler;})()"""
def propriedades(obj):
    return d.execute_cdp_cmd('Runtime.getProperties',{'objectId':obj,'ownProperties':True})
try:
    with a._etapa('renderizacao.ler_closure_change_sem_executar'):
        fn=d.execute_cdp_cmd('Runtime.evaluate',{'expression':expressao,'objectGroup':'sch_inspecao_leitura','returnByValue':False,'silent':True})
        if fn.get('exceptionDetails'):raise RuntimeError('Handler change não acessível no documento fixado.')
        props=propriedades(fn['result']['objectId'])
        scopes=next(p['value']['objectId'] for p in props.get('internalProperties',[]) if p['name']=='[[Scopes]]')
        resultado={'handler':fn['result'].get('description'),'closures':[]}
        for p in propriedades(scopes).get('result',[]):
            valor=p.get('value') or {}
            if valor.get('description')!='Closure':continue
            closure={}
            for campo in propriedades(valor['objectId']).get('result',[]):
                v=campo.get('value') or {}
                if campo['name']=='c' and v.get('type')=='function':
                    closure['callback_change']=v.get('description')
                if campo['name']=='b' and v.get('objectId'):
                    objeto=propriedades(v['objectId'])
                    for item in objeto.get('result',[]):
                        iv=item.get('value') or {}
                        if item['name']=='id':closure['widget_id']=iv.get('value')
                        if item['name']=='cfg' and iv.get('objectId'):
                            cfg=propriedades(iv['objectId'])
                            closure['cfg_chaves']=[c['name'] for c in cfg.get('result',[])]
            if closure:resultado['closures'].append(closure)
    a._contexto()
    (pasta/'callback_change.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(resultado,ensure_ascii=True))
finally:
    d.execute_cdp_cmd('Runtime.releaseObjectGroup',{'objectGroup':'sch_inspecao_leitura'})
