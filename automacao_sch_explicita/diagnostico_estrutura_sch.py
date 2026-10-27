"""Diagnóstico SOMENTE LEITURA da aba Características Técnicas no SCH.

Não modifica o DOM, não envia formulários nem salva alterações. Requer que o
Selenium esteja autenticado e posicionado em um requerimento.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def classificar_tabela_tecnica(cabecalho):
    """Classifica pelos CABEÇALHOS reais, jamais pelo tipo de produto."""
    campos = " | ".join(_normalizar(c) for c in (cabecalho or []))
    if not campos.strip(" |"):
        return "indefinida"
    frequencia = "frequenc" in campos or "frequency" in campos
    potencia = "potencia" in campos or "power" in campos
    intensidade = "intensidade de campo" in campos or "field strength" in campos
    distancia = "distancia" in campos or "distance" in campos
    fisicos = any(p in campos for p in (
        "tipo de cabo", "blindagem", "bitola", "condutor", "quantidade de pares",
        "material da capa", "comportamento frente", "categoria", "tipo de fibra",
    ))
    if frequencia and intensidade:
        return "rf_intensidade_distancia" if distancia else "rf_intensidade_sem_distancia"
    if frequencia and potencia:
        return "rf_frequencia_potencia"
    if fisicos:
        return "caracteristicas_fisicas"
    if frequencia:
        return "rf_outros_campos"
    return "outra_tabela"


# Coleta compacta e determinística, executada uma só vez dentro do iframe ativo.
# Nunca usa atribuições ou dispatchEvent; somente consulta o DOM.
_SCRIPT_LER_ESTRUTURAS = r"""
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none');
const txt = e => String(e?.innerText || e?.textContent || '').replace(/\s+/g, ' ').trim();
const bases = ['frequenc', 'potencia', 'intensidade', 'distancia', 'modulac', 'designacao', 'emiss', 'tecnolog', 'sar', 'categoria', 'tipo de cabo', 'blindagem', 'condutor', 'bitola', 'pares', 'material da capa', 'chama', 'antena acoplada', 'tipo de fibra'];
const matchesHeader = vals => vals.filter(v => bases.some(k => norm(v).includes(k))).length;
const saida = {tabelas: [], campos_textuais: [], advertencias: []};
// .rows do HTMLTableElement evita a maior parte dos <tr> das tabelas aninhadas.
for (const tabela of document.querySelectorAll('table')) {
  if (!visible(tabela)) continue;
  const linhas = Array.from(tabela.rows || []);
  if (!linhas.length) continue;
  let idx = -1, cab = [], marcador = 0;
  for (let i = 0; i < Math.min(linhas.length, 5); i++) {
    const celulas = Array.from(linhas[i].cells || []);
    if (celulas.length < 2) continue;
    const valores = celulas.map(txt);
    const score = matchesHeader(valores);
    if (score > marcador) { idx = i; cab = valores; marcador = score; }
  }
  if (idx < 0 || marcador === 0) continue; // ignora menus e tabelas do layout
  const corpo = linhas.slice(idx + 1).filter(l => l.cells && l.cells.length >= 2);
  const amostra = corpo.slice(0, 8).map(l => Array.from(l.cells).map(c => txt(c).slice(0, 180)));
  saida.tabelas.push({
    indice: saida.tabelas.length + 1, cabecalho: cab.map(c => c.slice(0, 180)),
    total_linhas: corpo.length, linhas_exemplo: amostra,
    identificador_html: String(tabela.id || '').slice(0, 100),
    colunas: cab.length
  });
}
// Busca textos nomeados (independente da tag/ordem do layout).
const elementos = Array.from(document.querySelectorAll('label, span, div, td, th, strong, b'))
 .filter(e => visible(e) && !e.querySelector('label, span, div, td, th, strong, b'));
for (const [nome, padrao] of [
 ['observacao', /^observacao\s*:?$/],
 ['titulo_caracteristicas_secundarias', /titulo\s*\/\s*descricao.*caracteristicas tecnicas secundarias/],
 ['especificacoes_complementares', /^especificacoes complementares\s*:?$/]
]) {
  let encontrados = 0;
  for (const rotulo of elementos) {
    if (!padrao.test(norm(txt(rotulo)))) continue;
    // Prioriza campo no mesmo contêiner; não inclui textos de outras abas.
    let area = rotulo.parentElement;
    let editor = null;
    for (let k=0; k<4 && area && !editor; k++, area=area.parentElement) {
      const possiveis = Array.from(area.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]'));
      editor = possiveis.find(visible) || null;
    }
    let valor = editor ? (editor.value ?? editor.innerText ?? '') : '';
    if (nome === 'especificacoes_complementares' && !editor) {
      const seguinte = rotulo.nextElementSibling || rotulo.parentElement?.nextElementSibling;
      valor = seguinte ? txt(seguinte) : '';
    }
    // Não salvar conteúdo longo nem justificar conclusão apenas por texto recortado.
    saida.campos_textuais.push({nome, ordem: ++encontrados,
      campo_editavel_detectado: !!editor,
      preenchido: !!String(valor).trim(),
      caracteres: String(valor).length,
      amostra: String(valor).replace(/\s+/g,' ').slice(0, 160)});
    if (encontrados >= 12) break;
  }
}
return saida;
"""


def diagnosticar_estrutura_atual(driver, wait, req):
    """Abre aba técnica e devolve catálogo sem clique em Salvar ou anexos."""
    # Importação tardia: não obriga Selenium durante os testes de classificação.
    from funcoes_sch import (
        clicar_aba_caracteristicas_tecnicas,
        entrar_iframe_detalhe_analise,
    )

    resultado = {
        "status": "erro",
        "requerimento": str((req or {}).get("requerimento") or ""),
        "tipo_produto": str((req or {}).get("tipo_produto") or ""),
        "somente_leitura": True,
        "data_inspecao": datetime.now().isoformat(),
        "tabelas": [], "campos_textuais": [], "familias": [],
        "total_tabelas": 0,
        "motivo": "",
    }
    try:
        clicar_aba_caracteristicas_tecnicas(driver, wait)
        entrar_iframe_detalhe_analise(driver, wait)
        bruto = driver.execute_script(_SCRIPT_LER_ESTRUTURAS) or {}
        tabelas = bruto.get("tabelas") or []
        for tab in tabelas:
            tab["familia"] = classificar_tabela_tecnica(tab.get("cabecalho"))
        resultado["tabelas"] = tabelas
        resultado["campos_textuais"] = bruto.get("campos_textuais") or []
        resultado["total_tabelas"] = len(tabelas)
        resultado["familias"] = sorted({t["familia"] for t in tabelas}) or ["somente_texto_ou_sem_tabela"]
        resultado["status"] = "coletado"
        if not tabelas:
            resultado["motivo"] = "Nenhuma tabela técnica reconhecida pelos cabeçalhos; verificar os campos textuais."
    except Exception as exc:
        resultado["motivo"] = f"Falha na inspeção: {type(exc).__name__}: {exc}"
    return resultado


def exibir_resumo_diagnostico(resultado):
    numero = resultado.get("requerimento", "")
    print(f"[SCH][RE][DIAGNOSTICO] {numero} | Status: {resultado.get('status')}")
    print(f"[SCH][RE][DIAGNOSTICO] Tabelas: {resultado.get('total_tabelas', 0)} | Famílias: {', '.join(resultado.get('familias') or [])}")
    for tab in resultado.get("tabelas") or []:
        print(f"  Tabela {tab.get('indice')}: {tab.get('familia')} | linhas={tab.get('total_linhas')} | colunas={tab.get('colunas')}")
        print(f"    Cabeçalhos: {' | '.join(tab.get('cabecalho') or [])[:350]}")
    for campo in resultado.get("campos_textuais") or []:
        print(f"  Campo {campo['nome']} #{campo['ordem']}: {'preenchido' if campo['preenchido'] else 'vazio'}")
    if resultado.get("motivo"):
        print(f"[SCH][RE][DIAGNOSTICO] {resultado['motivo']}")
