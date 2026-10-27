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
        and comp.get('linhas_sch') and comp.get('linhas_cct'))
    executada = conferencia.get('status_geral') in {'ok', 'parcial', 'divergente', 'conforme'}
    return {'apto_preenchimento': executada, 'comparacao_tecnica_integral': integral,
        'comparacao_cct_sch_executada': executada,
        'familias': diagnostico.get('familias') or [],
        'status': 'verificacoes_independentes',
        'motivo': ('Conferência técnica integral.' if integral else
                   'Conferência técnica parcial; tabelas exigem revisão manual.')
                  + ' Preenchimentos dependem de regras próprias e segurança da tela.'}


def compor_acompanhamento_preservado(existente, frase):
    """Retorna (novo_texto, precisa_adicionar). Nunca apaga texto anterior."""
    existente = str(existente or '')
    frase = str(frase or '').strip()
    if not frase:
        return existente, False
    if normalizar(frase) in normalizar(existente):
        return existente, False
    return ('\n'.join(p for p in (existente, frase) if p)), True


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
    status_obs = 'preservada' if texto.strip() else 'revisao_manual'
    # Sem regra extraída, a função compartilhada aplicaria fallback genérico.
    if not texto.strip() and str(dados_pdf.get('observacao_texto') or '').strip():
        analise = decidir_texto_observacao_por_cct(dados_pdf)
        texto = analise['texto']
        if not preencher_observacao_caracteristicas(driver, wait, texto):
            raise RuntimeError('Observação não confirmada após preenchimento.')
        mudou = True
        status_obs = 'preenchida'
    titulo = preencher_titulo_caracteristicas_secundarias_se_existir(
        driver=driver, wait=wait, req=req, dados_pdf=dados_pdf,
    ) or {}
    if titulo.get('motivo') == 'campo_ja_correto':
        titulo['status'] = 'preservado'
    if titulo.get('status') in {'erro', 'erro_confirmacao'}:
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
        'classificacao': dados_pdf.get('observacao_classificacao') or '',
        'preenchido_automaticamente': mudou,
        'titulo_caracteristicas_secundarias': titulo,
        'salvo': bool(salvamento.get('salvo')),
        'confirmado_apos_salvar': bool(salvamento.get('confirmado_apos_salvar')),
        'sem_alteracao': not (mudou or mudou_titulo),
        'mensagem': 'Observação e CTS avaliados independentemente.'}


def preencher_acompanhamento_seguro_re(driver, wait, frase):
    """Adiciona a frase da Portaria 2257 somente se ausente, preservando todo texto."""
    from funcoes_sch import (
        clicar_aba_informacoes_adicionais,
        entrar_iframe_detalhe_analise,
        marcar_acompanhar_processo,
        preencher_acompanhar_processo,
        salvar_informacoes_adicionais,
        _localizar_textarea_acompanhar_processo,
        _localizar_checkbox_acompanhar_processo,
        _checkbox_esta_marcado,
    )
    clicar_aba_informacoes_adicionais(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    # O textarea pode não existir enquanto o checkbox estiver desmarcado.
    # Primeiro habilita o acompanhamento; só depois lê TODO o texto existente.
    if not marcar_acompanhar_processo(driver, wait):
        raise RuntimeError('Acompanhar Processo não foi marcado.')
    entrar_iframe_detalhe_analise(driver, wait)
    campo = _localizar_textarea_acompanhar_processo(driver, wait, timeout=6)
    anterior = str(campo.get_attribute('value') or '')
    novo, adicionar = compor_acompanhamento_preservado(anterior, frase)
    if adicionar and not preencher_acompanhar_processo(driver, wait, novo):
        raise RuntimeError('A frase não foi confirmada no textarea Acompanhar Processo.')
    # Salva inclusive se a frase já existia mas a caixa estava desmarcada.
    salvo = bool(salvar_informacoes_adicionais(driver, wait))
    clicar_aba_informacoes_adicionais(driver, wait)
    entrar_iframe_detalhe_analise(driver, wait)
    verificado = _localizar_textarea_acompanhar_processo(driver, wait, timeout=6)
    gravado = str(verificado.get_attribute('value') or '')
    caixa = _localizar_checkbox_acompanhar_processo(driver, wait, timeout=5)
    marcado = bool(caixa is not None and _checkbox_esta_marcado(caixa))
    confirmado = (marcado and normalizar(frase) in normalizar(gravado) and
                  (not anterior.strip() or normalizar(anterior) in normalizar(gravado)))
    return {
        'status': 'confirmado' if salvo and confirmado else 'erro_confirmacao',
        'texto': frase, 'texto_anterior_preservado': bool(anterior.strip()),
        'texto_ja_existia': not adicionar, 'adicionado': adicionar,
        'preenchido_automaticamente': bool(salvo and confirmado),
        'salvo': salvo, 'confirmado_apos_salvar': confirmado,
        'modo_preenchimento': 'acompanhar_processo',
        'mensagem': ('Frase já existente, sem duplicação.' if not adicionar else
                     'Frase acrescentada preservando o conteúdo anterior.'),
    }
