"""Proteções específicas da opção 4 (RE simplificado).

Não altera o comportamento de Em Análise nem do RE tradicional.
O mapeamento não é feito pelo nome do produto: usa tabelas da tela e a
cobertura real da conferência com o CCT.
"""
from __future__ import annotations

import re
import unicodedata


def normalizar(texto):
    s = unicodedata.normalize('NFKD', str(texto or ''))
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).lower().split())


def avaliar_cobertura_mvp(diagnostico, conferencia, dados_pdf):
    """Autorização conservadora de preenchimento na PRIMEIRA versão pública.

    Apenas uma tabela RF de faixa + potência que efetivamente tenha sido
    comparada com um CCT legível. Todo o restante continua no relatório,
    para revisão, sem qualquer gravação de campos.
    """
    diagnostico = diagnostico or {}
    conferencia = conferencia or {}
    dados_pdf = dados_pdf or {}
    base = {
        'apto_preenchimento': False,
        'familias': diagnostico.get('familias') or [],
        'status': 'revisao_manual',
        'motivo': '',
        'comparacao_cct_sch_executada': conferencia.get('status_geral') in {'ok','parcial','divergente','conforme'},
    }
    if diagnostico.get('status') != 'coletado':
        base['motivo'] = 'Estrutura técnica não identificada com segurança.'
        return base
    tabs = diagnostico.get('tabelas') or []
    if len(tabs) != 1 or tabs[0].get('familia') != 'rf_frequencia_potencia':
        base['motivo'] = 'Estrutura sem suporte de preenchimento nesta versão: somente conferência geral e revisão manual.'
        return base
    comparacao = conferencia.get('comparacao_tabela_tecnica') or {}
    if not (comparacao.get('status') == 'ok' and comparacao.get('usar_potencia') and
            comparacao.get('linhas_sch', 0) and comparacao.get('linhas_cct', 0)):
        base['motivo'] = 'A comparação de frequência e potência não foi confirmada integralmente.'
        return base
    if not str(dados_pdf.get('observacao_texto') or '').strip():
        base['motivo'] = 'CCT sem regra segura de Observação: não utilizar frase genérica de radiação restrita.'
        return base
    base.update(status='habilitado_mvp', apto_preenchimento=True,
                motivo='Tabela RF (frequência e potência) compatível com CCT, elegível para as rotinas existentes de Em Análise.')
    return base


def compor_acompanhamento_preservado(existente, frase):
    """Retorna (novo_texto, precisa_adicionar). Nunca apaga texto anterior."""
    existente = str(existente or '').strip()
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
        preencher_caracteristicas_tecnicas_com_analise,
        preencher_titulo_caracteristicas_secundarias_se_existir,
        salvar_caracteristicas_tecnicas,
    )
    atual = ler_observacao_atual_re(driver, wait)
    if not atual['localizado']:
        raise RuntimeError('Campo Observação não confirmado; nenhuma alteração realizada.')
    if not atual['texto'].strip():
        return preencher_caracteristicas_tecnicas_com_analise(
            driver=driver, wait=wait, req=req, anexos_baixados=anexos_baixados,
            dados_pdf=dados_pdf,
        )
    # Há observação: nunca chamar preenchimento que a substitui.
    titulo = preencher_titulo_caracteristicas_secundarias_se_existir(
        driver=driver, wait=wait, req=req, dados_pdf=dados_pdf,
    ) or {}
    if titulo.get('status') in {'revisar', 'erro', 'erro_confirmacao'}:
        return {
            'status': 'revisao_manual_cts', 'texto': atual['texto'],
            'preenchido_automaticamente': False,
            'titulo_caracteristicas_secundarias': titulo,
            'salvo': False, 'confirmado_apos_salvar': False,
            'mensagem': 'Título de características secundárias inconclusivo; etapas seguintes bloqueadas.',
        }
    if titulo.get('preenchido') or titulo.get('corrigido'):
        texto_titulo = titulo.get('titulo_esperado') or ''
        salvamento = salvar_caracteristicas_tecnicas(
            driver, wait, texto_esperado=atual['texto'],
            titulo_secundario_esperado=texto_titulo,
        ) or {}
        salvo = bool(salvamento.get('salvo'))
        confirmado = bool(salvamento.get('confirmado_apos_salvar'))
        status = 'titulo_cts_tratado' if salvo and confirmado else 'erro_confirmacao_cts'
    else:
        # nenhuma escrita; não se exige clicar em salvar
        salvo = True
        confirmado = True
        status = 'observacao_preservada_sem_alteracao'
    return {
        'status': status, 'texto': atual['texto'],
        'classificacao': dados_pdf.get('observacao_classificacao') or '',
        'preenchido_automaticamente': False,
        'titulo_caracteristicas_secundarias': titulo,
        'salvo': salvo, 'confirmado_apos_salvar': confirmado,
        'mensagem': 'Observação existente preservada integralmente.',
    }


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
