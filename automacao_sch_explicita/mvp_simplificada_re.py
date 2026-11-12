"""Proteções específicas da opção 4 (RE simplificado).

Não altera o comportamento de Em Análise nem do RE tradicional.
Cada ação possui sua própria regra; cobertura técnica parcial não autoriza
nem bloqueia indiscriminadamente as demais ações.
"""
from __future__ import annotations

import re
import unicodedata


def normalizar(texto):
    s = unicodedata.normalize('NFKD', str(texto or ''))
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).lower().split())


def avaliar_cobertura_mvp(diagnostico, conferencia, dados_pdf):
    """Cobertura técnica independente das regras de cada preenchimento."""
    diagnostico, conferencia, dados_pdf = diagnostico or {}, conferencia or {}, dados_pdf or {}
    tabs = diagnostico.get('tabelas') or []
    comp = conferencia.get('comparacao_tabela_tecnica') or {}
    integral = bool(diagnostico.get('status') == 'coletado' and len(tabs) == 1
        and tabs[0].get('familia') == 'rf_frequencia_potencia'
        and comp.get('status') == 'ok' and comp.get('usar_potencia')
        and not comp.get('campos_nao_validados')
        and comp.get('linhas_sch') and comp.get('linhas_cct'))
    executada = conferencia.get('status_geral') in {'ok', 'parcial', 'divergente', 'conforme'}
    return {'apto_preenchimento': executada, 'comparacao_tecnica_integral': integral,
        'comparacao_cct_sch_executada': executada,
        'familias': diagnostico.get('familias') or [],
        'status': 'verificacoes_independentes',
        'motivo': ('Conferência técnica integral.' if integral else
                   'Conferência técnica parcial; tabelas exigem revisão manual.')
                  + ' Preenchimentos dependem de regras próprias e segurança da tela.'}


def expandir_faixas_explicitas_re(tabela):
    """Desdobra faixas explícitas ligadas por 'e' sem alterar os dados originais.

    Evita perder 905–915 ao comparar uma célula '898,5 a 901 e 905 a 915'.
    Aceita apenas a gramática completa de intervalos; textos ambíguos permanecem.
    """
    from funcoes_sch import _mapear_colunas_relevantes
    tabela = tabela or {}
    if tabela.get('tabelas'):
        return dict(tabela, tabelas=[expandir_faixas_explicitas_re(t) for t in tabela['tabelas']])
    indice = _mapear_colunas_relevantes(tabela.get('cabecalho') or []).get('faixa_freq_tx')
    linhas, origens = [], []
    numero = r"[0-9]+(?:[.,][0-9]+)?"
    intervalo = numero + r"\s*(?:a|até|ate|[-–—])\s*" + numero
    padrao = intervalo + r"(?:\s+e\s+" + intervalo + r")+"
    for numero_origem, original in enumerate(tabela.get('linhas') or [], 1):
        anteriores = tabela.get('origens_linhas') or []
        origem = dict(anteriores[numero_origem-1]) if numero_origem <= len(anteriores) else {'linha': numero_origem}
        linha = list(original)
        valor = str(linha[indice] or '').strip() if indice is not None and indice < len(linha) else ''
        if re.fullmatch(padrao, valor, flags=re.I):
            for faixa in re.split(r"\s+e\s+", valor, flags=re.I):
                nova = list(linha)
                nova[indice] = faixa
                linhas.append(nova)
                origens.append(dict(origem, faixa_original=valor))
        else:
            linhas.append(linha)
            origens.append(origem)
    return dict(tabela, linhas=linhas, origens_linhas=origens)


def compor_acompanhamento_preservado(existente, frase):
    """Retorna (novo_texto, precisa_adicionar). Nunca apaga texto anterior."""
    existente = str(existente or '')
    frase = str(frase or '').strip()
    if not frase:
        return existente, False
    if normalizar(frase) in normalizar(existente):
        return existente, False
    return ('\n'.join(p for p in (existente, frase) if p)), True


def planejar_acoes_simplificadas(req, resumo, estado):
    """Plano puro da opção 4; usa os mesmos decisores de Observação, CTS e SAR."""
    from fluxo_sch import _tipo_produto_permitido_simplificada
    from funcoes_sch import (decidir_texto_observacao_por_cct,diagnosticar_titulo_caracteristicas_secundarias,
                            analisar_sar_cct,TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES)
    dados=resumo.get('dados_pdf') or {}
    if not _tipo_produto_permitido_simplificada(req):
        return {'status':'bloqueado_tipo_produto','motivo':'Produto fora do escopo existente da opção 4.',
                'campos_que_seriam_alterados':[],'acoes_bloqueadas':['Todos os preenchimentos: produto não permitido.']}
    obs=estado.get('observacao') or {}
    cts=estado.get('cts') or {}
    acomp=estado.get('acompanhar') or {}
    sugestao_obs=decidir_texto_observacao_por_cct(dados)
    titulo=diagnosticar_titulo_caracteristicas_secundarias(req=req,dados_pdf=dados,contexto_sch=cts.get('contexto') or {})
    sar=analisar_sar_cct(dados)
    acoes=[];preservados=[];bloqueadas=[]
    if not obs.get('localizado'):
        decisao_obs='revisar_campo_nao_confirmado';bloqueadas.append('Observação: campo não confirmado.')
    elif str(obs.get('texto') or '').strip():
        decisao_obs='preservar_existente';preservados.append('Observação')
    elif dados.get('observacao_texto') or all(normalizar(x.get('tipo_produto'))=='transceptor de radiacao restrita' for x in (req,dados)):
        decisao_obs='preencher_e_confirmar_salvamento'
        acoes.append({'campo':'Observação','atual':obs.get('texto'),'sugerido':sugestao_obs['texto'],'salvar_e_confirmar':True})
    else:
        decisao_obs='revisar_sem_regra_segura';bloqueadas.append('Observação: ausência de regra segura da opção 4.')
    sugerido=titulo.get('titulo') or ''
    if cts.get('status') in {'revisar_localizacao','revisar_identidade_campo'}:
        decisao_cts='revisar_localizacao_sem_alterar';bloqueadas.append('CTS: identidade/localização não confirmada; nenhuma edição deste campo.')
    elif not cts.get('localizado'):
        decisao_cts='nao_aplicavel_campo_ausente'
    elif not sugerido:
        decisao_cts='revisar_sem_evidencia_segura';bloqueadas.append('CTS: sem evidência suficiente para título.')
    elif str(cts.get('valor') or '').strip()==sugerido.strip():
        decisao_cts='preservar_existente';preservados.append('CTS')
    else:
        decisao_cts='corrigir_ou_preencher_e_confirmar_salvamento'
        acoes.append({'campo':'CTS','atual':cts.get('valor'),'sugerido':sugerido,'salvar_e_confirmar':True})
    if sar.get('preencher_frase'):
        decisao_minuta='avaliar_minuta_preservando_existente_antes_de_preencher'
        bloqueadas.append('Corrigir Minuta: inspeção adicional necessária; simulação não abre o editor nem aplica frase.')
    else:
        decisao_minuta='nao_abrir_nem_alterar_minuta'
        preservados.append('Corrigir Minuta / Especificações Complementares')
    frase=TEXTO_INFORMACOES_ADICIONAIS_ANALISE_SIMPLES
    if not acomp.get('localizado'):
        decisao_acomp='revisar_campo_superior_nao_confirmado';bloqueadas.append('Acompanhar Processo: campo superior não confirmado; não supor valor vazio.')
    else:
        alterar=str(acomp.get('valor') or '').strip()!=frase.strip()
        decisao_acomp='substituir_texto_marcar_salvar_e_confirmar' if alterar else 'preservar_texto_confirmar_marcacao_e_salvamento'
        if alterar:
            acoes.append({'campo':'Texto superior Acompanhar Processo','atual':acomp.get('valor'),'sugerido':frase,'salvar_e_confirmar':True})
        else:
            preservados.append('Texto superior Acompanhar Processo')
        if acomp.get('marcado') is False:
            acoes.append({'campo':'Marcação Acompanhar Processo','atual':False,'sugerido':True,'salvar_e_confirmar':True})
    comp=(resumo.get('conferencia_sch_cct') or {}).get('comparacao_tabela_tecnica') or {}
    return {'status':'simulado','comparacao_parcial_bloqueia_globalmente':False,
            'motivo':'Status parcial é aceito no gate real; cada ação tem regra e confirmação próprias.',
            'situacoes_tecnicas':{'divergencia_comprovada':bool(comp.get('divergencias')),
                'extracao':(dados.get('diagnostico_extracao') or {}).get('status'),
                'correspondencias_ambiguas':(comp.get('resumo_correspondencias') or {}).get('linhas_ambiguas'),
                'coincidencias_apenas_eirp':(comp.get('resumo_correspondencias') or {}).get('coincidencias_numericas_apenas_eirp'),
                'equivalencia_saida_eirp_confirmada':False,'status_comparacao':comp.get('status')},
            'observacao':{'atual':obs,'sugestao':sugestao_obs,'decisao':decisao_obs},
            'cts':{'atual':cts,'sugerido':sugerido,'origem_e_criterios':titulo,'decisao':decisao_cts},
            'sar':sar,'corrigir_minuta':{'decisao':decisao_minuta,'frase_generica_autorizada':bool(sar.get('preencher_frase'))},
            'acompanhar_processo':{'atual':acomp,'sugerido':frase,'decisao':decisao_acomp,
                'limite':'A rotina real salva inclusive com texto já igual; a simulação não salva nem confirma gravação.'},
            'campos_que_seriam_alterados':acoes,'campos_preservados':preservados,
            'acoes_bloqueadas':bloqueadas+['Todas as gravações: modo de simulação.','Aprovação automática: não participa da opção 4.'],
            'acoes_independentes_prontas':[a for a in acoes if a['campo']!='CTS' or cts.get('status')=='localizado_confirmado'],
            'pronto_para_escrita_controlada':bool(estado.get('exigir_download_real') and estado.get('identidade_cct_confirmada') and cts.get('status')=='nao_aplicavel_ausencia_confirmada' and acomp.get('localizado') and acomp.get('checkbox_encontrado') and obs.get('localizado') and not comp.get('divergencias')),
            'limite_prontidao':'Prontidão refere-se apenas às ações independentes listadas, com identidade do novo download e campos confirmados. Não equivale a conformidade integral nem comprova salvamento. Escrita exige autorização posterior restrita ao requerimento selecionado.'}


def ler_observacao_atual_re(driver, wait):
    """Lê a observação visível antes da edição; em dúvida, retorna localizado=False."""
    from selenium.webdriver.common.by import By
    from funcoes_sch import clicar_aba_caracteristicas_tecnicas, entrar_iframe_detalhe_analise
    clicar_aba_caracteristicas_tecnicas(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    seletores = [
        "//*[self::label or self::span or self::td][contains(normalize-space(.),'Observação')]/following::textarea[1]",
        "//textarea[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'observ')]",
        "//textarea[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'observ')]",
    ]
    for xpath in seletores:
        for el in driver.find_elements(By.XPATH, xpath):
            if el.is_displayed():
                return {'localizado': True, 'texto': str(el.get_attribute('value') or '')}
    return {'localizado': False, 'texto': ''}


def preencher_caracteristicas_conservadoras_re(driver, wait, req, anexos_baixados, dados_pdf):
    """Usa a função de Em Análise sem substituir observações pré-existentes."""
    from funcoes_sch import (
        preencher_observacao_caracteristicas, decidir_texto_observacao_por_cct,
        preencher_titulo_caracteristicas_secundarias_se_existir,
        salvar_caracteristicas_tecnicas,
    )
    atual = ler_observacao_atual_re(driver, wait)
    if not atual['localizado']:
        raise RuntimeError('Campo Observação não confirmado; nenhuma alteração realizada.')
    texto = atual['texto']
    mudou = False
    analise = {}
    status_obs = 'preservada' if texto.strip() else 'revisao_manual'
    # Reutiliza as frases de Em Análise. O padrão de radiação restrita
    # também pode ser usado quando SCH e CCT confirmam explicitamente esse
    # tipo; nunca transferir esse fallback para uma ETA sem regra no CCT.
    regra_cct = bool(str(dados_pdf.get('observacao_texto') or '').strip())
    rr_confirmada = all(
        normalizar(fonte.get('tipo_produto')) == 'transceptor de radiacao restrita'
        for fonte in (req or {}, dados_pdf)
    )
    if not texto.strip() and (regra_cct or rr_confirmada):
        analise = decidir_texto_observacao_por_cct(dados_pdf)
        texto = analise['texto']
        if not preencher_observacao_caracteristicas(driver, wait, texto):
            raise RuntimeError('Observação não confirmada após preenchimento.')
        mudou = True
        status_obs = 'preenchida'
    from funcoes_sch import diagnosticar_campo_cts_re
    evidencia_cts=diagnosticar_campo_cts_re(driver)
    if evidencia_cts['status']=='localizado_confirmado':
        titulo = preencher_titulo_caracteristicas_secundarias_se_existir(
            driver=driver, wait=wait, req=req, dados_pdf=dados_pdf,
        ) or {}
    else:
        titulo={'status':'nao_aplicavel' if evidencia_cts['status']=='nao_aplicavel_ausencia_confirmada' else 'revisar',
                'preenchido':False,'motivo':evidencia_cts['motivo'],'diagnostico_localizacao':evidencia_cts}
    if titulo.get('motivo') == 'campo_ja_correto':
        titulo['status'] = 'preservado'
    if titulo.get('status') not in {'preservado', 'revisar', 'nao_aplicavel', 'preenchido', 'corrigido'}:
        raise RuntimeError('Não foi possível confirmar CTS; edição interrompida.')
    mudou_titulo = bool(titulo.get('preenchido') or titulo.get('corrigido'))
    salvamento = {}
    if mudou or mudou_titulo:
        salvamento = salvar_caracteristicas_tecnicas(
            driver, wait, texto_esperado=texto,
            titulo_secundario_esperado=titulo.get('titulo_esperado') or '',
        ) or {}
        if not salvamento.get('salvo') or not salvamento.get('confirmado_apos_salvar'):
            raise RuntimeError('Salvamento de Características Técnicas não confirmado.')
        verificada = ler_observacao_atual_re(driver, wait)
        if not verificada['localizado'] or verificada['texto'] != texto:
            raise RuntimeError('Observação não foi preservada/gravada integralmente após salvar.')
    return {'status': status_obs, 'texto': texto,
        'observacao': {'status': status_obs},
        'classificacao': analise.get('classificacao') or dados_pdf.get('observacao_classificacao') or '',
        'origem': analise.get('origem') or ('existente_sch' if atual['texto'].strip() else 'revisao_manual'),
        'motivos': analise.get('motivos') or [],
        'preenchido_automaticamente': mudou,
        'titulo_caracteristicas_secundarias': titulo,
        'salvo': bool(salvamento.get('salvo')),
        'confirmado_apos_salvar': bool(salvamento.get('confirmado_apos_salvar')),
        'sem_alteracao': not (mudou or mudou_titulo),
        'mensagem': ('Observação existente preservada.' if atual['texto'].strip() else
                     'Frase aplicável de Em Análise preenchida e confirmada.' if mudou else
                     'CCT sem regra segura para Observação deste produto; revisão manual, sem aplicar frase genérica de Radiação Restrita à ETA.')}


def preencher_acompanhamento_seguro_re(driver, wait, frase):
    """Substitui somente o textarea superior pela frase configurada e confirma."""
    from controles_acompanhar import executar_acompanhamento_opcao4
    novo = str(frase or '').strip()
    if not novo:
        raise RuntimeError('Frase de acompanhamento vazia; nenhuma alteração realizada.')
    return executar_acompanhamento_opcao4(driver, wait, novo)
