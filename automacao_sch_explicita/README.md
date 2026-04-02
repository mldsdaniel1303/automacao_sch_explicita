# Automação SCH explícita

Esta versão mantém o que já estava funcionando no projeto anterior:
- escolha do navegador
- pasta de saída
- login manual
- leitura da fila Em Análise
- abertura do requerimento
- aba Anexos
- download dos anexos
- parser do CCT
- preenchimento da minuta
- resumo em JSON

A diferença é a arquitetura:
- **seletores de interface** ficam no código, dentro das funções
- **regras de negócio** ficam em `config/regras.json`

## Estrutura

- `main.py`: entrada da automação
- `fluxo_sch.py`: fluxo principal
- `funcoes_sch.py`: funções explícitas do SCH, com XPaths dentro delas
- `navegador.py`: criação do driver e diretórios
- `pdf_parser.py`: leitura do PDF do CCT
- `utils.py`: utilidades gerais
- `config/regras.json`: regras de interpretação de tabela e anexos

## Como rodar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## O que ajustar no primeiro teste real

Os pontos mais prováveis de ajuste fino são:
- XPath da fila **Em Análise**
- XPath da aba **Anexos**
- iframe correto dos anexos
- seletor do botão de download
- campos reais da **Minuta**

Esses ajustes agora ficam simples porque cada seletor está dentro da função correspondente.
