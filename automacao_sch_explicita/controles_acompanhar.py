"""Shared identification of the upper panel; no diagnostic entrypoints."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC


def aguardar_ajax(driver, wait):
    from utils import _documento_pronto, _ajax_primefaces_pronto
    wait.until(lambda _: _documento_pronto(driver) and _ajax_primefaces_pronto(driver),
               message='Acompanhar Processo: documento/fila AJAX não ficaram prontos.')


def ler_controles(driver):
    def unico(identificador):
        elementos = driver.find_elements(By.ID, identificador)
        if len(elementos) != 1:
            raise RuntimeError(f'Controle ausente ou duplicado: {identificador}')
        return elementos[0]
    cb = unico('formAnalise:checkBoxAcompanharProcesso_input')
    for identificador in ('formAnalise:acompanharProcessoPanel', 'formAnalise:textAreaPanel',
                          'formAnalise:checkBoxAcompanharProcesso'):
        unico(identificador)
    painel = driver.execute_script(SCRIPT_PAINEL_SUPERIOR, cb)
    if not painel or not painel.get('checkbox_no_painel') or not painel.get('textAreaPanel'):
        raise RuntimeError('Vínculo do checkbox com o painel superior não confirmado.')
    ids = painel.get('textareas') or []
    if len(ids) > 1 or painel.get('outros_controles'):
        raise RuntimeError('Painel superior ambíguo ou com controles inesperados.')
    campo = unico(ids[0]) if ids else None
    if campo is not None:
        valido = driver.execute_script("""const [ta,cb]=arguments,p=document.getElementById('formAnalise:textAreaPanel');
return !!(p&&p.contains(ta)&&ta.tagName==='TEXTAREA'&&ta.id!=='formAnalise:descricao'&&ta.form&&ta.form===cb.form&&!ta.disabled);""", campo, cb)
        if not valido:
            raise RuntimeError('Textarea não pertence ao painel superior correto.')
    return cb, campo


def inventario_preservado(driver):
    return driver.execute_script("""return Array.from(document.querySelectorAll('input,textarea,select'))
.filter(e=>e.type!=='hidden'&&e.type!=='submit'&&e.type!=='button'&&e.id!=='formAnalise:checkBoxAcompanharProcesso_input'&&!e.closest('[id="formAnalise:textAreaPanel"]'))
.map(e=>({id:e.id,nome:e.name,tipo:e.type,valor:e.value,marcado:e.checked??null}));""")


def marcar_visual(driver, wait):
    cb, _ = ler_controles(driver)
    if not cb.is_selected():
        normal = driver.execute_script(SCRIPT_CAIXA_NORMAL, cb)
        caixa = normal.get('caixa') if normal else None
        if not normal or not normal.get('valido') or caixa is None or not caixa.is_displayed() or not caixa.is_enabled():
            raise RuntimeError('Widget visual PrimeFaces não confirmado; nenhum fallback permitido.')
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", caixa)
        print('[SCH][OPCAO4] Clique único no widget visual PrimeFaces; aguardando AJAX.')
        caixa.click()
    aguardar_ajax(driver, wait)
    def renderizado(_):
        from utils import _ajax_primefaces_pronto
        if not _ajax_primefaces_pronto(driver):
            return False
        caixa_atual, campo = ler_controles(driver)
        return campo if caixa_atual.is_selected() and campo is not None and campo.is_displayed() else False
    return wait.until(renderizado, message='Checkbox/textarea superior não confirmados após AJAX; não salvar.')


def reler_apos_salvar(driver, wait, antigo):
    import funcoes_sch as sch
    sch.clicar_aba_dados_gerais(driver, wait)
    aguardar_ajax(driver, wait)
    sch.clicar_aba_informacoes_adicionais(driver, wait)
    sch.entrar_iframe_detalhe_analise(driver, wait)
    aguardar_ajax(driver, wait)
    wait.until(EC.staleness_of(antigo), message='Textarea anterior não foi recriado; persistência não comprovada.')
    cb, campo = ler_controles(driver)
    if campo is None:
        raise RuntimeError('Campo superior ausente após reabertura.')
    return {'texto': str(campo.get_attribute('value') or ''), 'marcado': cb.is_selected(),
            'reabertura_confirmada': True}


def executar_acompanhamento_opcao4(driver, wait, texto):
    import funcoes_sch as sch
    r = {'status': 'erro_confirmacao', 'texto': texto, 'salvo': False,
         'confirmado_apos_salvar': False, 'preenchido_automaticamente': False,
         'tentativas_salvamento': 0, 'estado_servidor_indeterminado': False,
         'modo_preenchimento': 'acompanhar_processo', 'reabertura_confirmada': False}
    try:
        sch.clicar_aba_informacoes_adicionais(driver, wait)
        sch.entrar_iframe_detalhe_analise(driver, wait)
        aguardar_ajax(driver, wait)
        cb, inicial = ler_controles(driver)
        r['antes'] = {'marcado': cb.is_selected(),
                      'texto': str(inicial.get_attribute('value') or '') if inicial is not None else None}
        preservado = inventario_preservado(driver)
        campo = marcar_visual(driver, wait)
        anterior = str(campo.get_attribute('value') or '')
        r['texto_real_apos_ajax'] = anterior
        r['substituido'] = anterior != texto
        r['texto_ja_existia'] = anterior == texto
        r['texto_anterior_preservado'] = anterior == texto
        if anterior != texto:
            campo.clear()
            campo.send_keys(texto)
            campo.send_keys(sch.Keys.TAB)
            aguardar_ajax(driver, wait)
        cb, campo = ler_controles(driver)
        if campo is None or not cb.is_selected() or campo.get_attribute('value') != texto:
            raise RuntimeError('Valor exato/checkbox não confirmado antes de Salvar.')
        if inventario_preservado(driver) != preservado:
            raise RuntimeError('Outros controles mudaram; cancelar sem Salvar.')
        botao = sch._achar_primeiro_elemento_visivel(driver, sch.XPATHS_SALVAR_INFORMACOES_ADICIONAIS,
                                                    'Salvar superior', timeout=5)
        if not driver.execute_script(SCRIPT_VINCULO, campo, cb, botao).get('valido'):
            raise RuntimeError('Salvar não vinculado ao formulário/painel superior.')
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
        r['tentativas_salvamento'] = 1
        r['estado_servidor_indeterminado'] = True
        print('[SCH][OPCAO4] Salvar: tentativa única; persistência ainda não confirmada.')
        botao.click()
        r['clique_salvar_executado'] = True
        aguardar_ajax(driver, wait)
        depois = reler_apos_salvar(driver, wait, campo)
        r['apos'] = depois
        r['reabertura_confirmada'] = depois['reabertura_confirmada']
        r['campos_preservados'] = inventario_preservado(driver) == preservado
        confirmado = (depois['texto'] == texto and depois['marcado'] and r['campos_preservados'])
        r.update(salvo=confirmado, confirmado_apos_salvar=confirmado,
                 preenchido_automaticamente=confirmado,
                 estado_servidor_indeterminado=not confirmado,
                 status='confirmado' if confirmado else 'erro_confirmacao')
        print(f'[SCH][OPCAO4] Persistência após reabertura: {confirmado}; checkbox={depois["marcado"]}; outros controles preservados={r["campos_preservados"]}.')
    except Exception as exc:
        r['erro'] = f'{type(exc).__name__}: {exc}'
        print(f'[SCH][OPCAO4][INTERROMPIDO] {r["erro"]}; sem repetição automática.')
    return r


SCRIPT_VINCULO = r"""const [ta,cb,b]=arguments;
 const n=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim().toLowerCase();
 const unico=e=>Array.from(document.querySelectorAll('[id]')).filter(x=>x.id===e.id).length===1;
 let sec=ta; while(sec && !sec.contains(cb)) sec=sec.parentElement;
 return {textoId:ta.id,checkboxId:cb.id,salvarId:b.id,
  diagnostico:{tag_texto:ta.tagName,tipo_checkbox:cb.type,ids_unicos:unico(ta)&&unico(cb)&&unico(b),
    mesmo_formulario:ta.form===cb.form&&ta.form===b.form,
    ancestral_comum:sec?{tag:sec.tagName,id:sec.id,textareas:sec.querySelectorAll('textarea').length,checkboxes:sec.querySelectorAll('input[type=checkbox]').length,marcador:n(sec.innerText||sec.textContent).includes('desejo acompanhar este processo')}:null,
    legenda_salvar:n(b.innerText||b.value)},
  valido:!!(sec && ta.tagName==='TEXTAREA' && cb.type==='checkbox' && ta.id && cb.id && b.id &&
    sec.querySelectorAll('textarea').length===1 && sec.querySelectorAll('input[type=checkbox]').length===1 &&
    n(sec.innerText||sec.textContent).includes('desejo acompanhar este processo') &&
    unico(ta) && unico(cb) && unico(b) && ta.form===cb.form && ta.form===b.form && n(b.innerText||b.value)==='salvar')};"""

SCRIPT_PAINEL_SUPERIOR = """const p=document.getElementById('formAnalise:acompanharProcessoPanel'),cb=arguments[0];
return {painel:p?.id??null,checkbox_no_painel:!!(p&&p.contains(cb)),checkboxId:cb.id,
 textareas:p?Array.from(p.querySelectorAll('textarea')).map(e=>e.id):[],
 outros_controles:Array.from(p?.querySelector('[id="formAnalise:textAreaPanel"]')?.querySelectorAll('input:not([type=hidden]),select,[contenteditable=true]')||[]).map(e=>({id:e.id,tag:e.tagName})),
 textAreaPanel:p?.querySelector('[id="formAnalise:textAreaPanel"]')?.id??null};"""

SCRIPT_CAIXA_NORMAL = """const cb=arguments[0],w=document.getElementById('formAnalise:checkBoxAcompanharProcesso'),p=document.getElementById('formAnalise:acompanharProcessoPanel');
const caixas=w?Array.from(w.querySelectorAll('.ui-chkbox-box')):[];
return {valido:!!(w&&p&&p.contains(w)&&w.contains(cb)&&caixas.length===1&&!cb.disabled),caixa:caixas.length===1?caixas[0]:null};"""
