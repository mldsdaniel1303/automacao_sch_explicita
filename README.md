# Automação SCH Explícita

Automação em Python para apoio à análise de requerimentos no **SCH (Sistema de Certificação e Homologação da Anatel)**.

O projeto automatiza o fluxo operacional de abertura de requerimentos, navegação entre abas, download de anexos, leitura do **CCT (Certificado de Conformidade Técnica)**, preenchimento de campos no sistema e geração de relatórios consolidados.

## Escopo atual

No estado atual, a automação está focada em:

- requerimentos da fila **Em Análise**
- processamento de **produtos de radiação restrita**
- download e organização dos anexos por categoria
- localização e leitura do PDF do **CCT**
- preenchimento automático de:
  - **Características Técnicas**
  - **Informações Adicionais**
  - **Minuta**
- geração de arquivos de controle e relatório por requerimento

## Funcionalidades

- Abre o SCH no navegador escolhido
- Aguarda login manual no sistema
- Acessa a fila **Em Análise**
- Coleta os requerimentos disponíveis
- Filtra o processamento para **radiação restrita**
- Abre cada requerimento individualmente
- Navega pela aba **Anexos**
- Baixa documentos de múltiplas categorias
- Organiza os arquivos por requerimento
- Localiza automaticamente o PDF do **CCT**
- Extrai dados do CCT para uso no preenchimento
- Preenche automaticamente campos do SCH
- Gera:
  - `resumo.json`
  - `controle_downloads.json`
  - `analise_requerimento.json`
  - `relatorio_execucao.json`
  - pasta `req_report`

## Estrutura do projeto

```text
automacao_sch_explicita/
├─ main.py
├─ fluxo_sch.py
├─ funcoes_sch.py
├─ navegador.py
├─ utils.py
├─ pdf_parser.py
├─ analise_requerimentos.py
├─ gerador_relatorio.py
├─ config.json / regras.json (quando aplicável)
├─ automacao_sch_output/
│  ├─ manifest_requerimentos.json
│  ├─ relatorio_execucao.json
│  ├─ req_report/
│  └─ requerimentos/
│     └─ <numero_requerimento>/
│        ├─ resumo.json
│        ├─ controle_downloads.json
│        ├─ analise_requerimento.json
│        └─ <categorias de anexos>/
└─ README.md
