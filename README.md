# Automação SCH - ANATEL

Projeto de automação para auxiliar a análise de requerimentos no sistema SCH/Mosaico da ANATEL.

A automação acessa a fila **Em Análise**, coleta os requerimentos, baixa anexos selecionados, processa o CCT/RACT, compara dados do SCH com os documentos e, quando habilitado, preenche campos no sistema.

---

## Estrutura do projeto

```text
automacao_sch_explicita/
│
├── automacao_sch_explicita/
│   ├── main.py
│   ├── fluxo_sch.py
│   ├── funcoes_sch.py
│   ├── navegador.py
│   ├── pdf_parser.py
│   ├── analise_requerimentos.py
│   ├── base_requisitos.py
│   ├── caracteristicas_secundarias.py
│   ├── gerador_relatorio.py
│   ├── modo_analise_local.py
│   ├── utils.py
│   └── config/
│
├── AutomacaoSCH.spec
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Requisitos

Antes de rodar o projeto, é necessário ter instalado:

* Python 3.11 ou superior
* Google Chrome ou Microsoft Edge
* Git
* Acesso ao sistema SCH/Mosaico

---

## Instalação em um novo computador

Clone ou atualize o repositório:

```powershell
git pull origin main
```

Crie um ambiente virtual:

```powershell
py -m venv .venv
```

Ative o ambiente virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

Atualize o `pip`:

```powershell
python -m pip install --upgrade pip
```

Instale as bibliotecas do projeto:

```powershell
python -m pip install -r requirements.txt
```

---

## Como rodar a automação

Na pasta raiz do projeto, execute:

```powershell
python .\automacao_sch_explicita\main.py
```

Ou entre na pasta do código:

```powershell
cd .\automacao_sch_explicita
python main.py
```

A automação exibirá um menu com as opções:

```text
1. Fluxo completo SCH
2. Somente analisar requerimentos já baixados
0. Sair
```

---

## Fluxo completo SCH

O fluxo completo pode:

* Abrir o SCH/Mosaico
* Aguardar login manual
* Entrar na fila **Em Análise**
* Coletar requerimentos
* Filtrar por radiação restrita, se desejado
* Abrir cada requerimento
* Extrair dados da aba **Dados Gerais**
* Baixar anexos
* Localizar e processar o CCT
* Comparar SCH x CCT
* Validar datas do certificado
* Analisar tabela técnica
* Analisar SAR
* Preencher Características Técnicas
* Preencher Corrigir Minuta, quando aplicável
* Preencher Informações Adicionais, quando habilitado
* Gerar relatórios por requerimento

---

## Saídas geradas

Os resultados são salvos em uma pasta de saída escolhida durante a execução.

A estrutura gerada é semelhante a:

```text
automacao_sch_output/
│
├── requerimentos/
│   ├── 00000_00/
│   │   ├── resumo.json
│   │   ├── analise_requerimento.json
│   │   ├── controle_downloads.json
│   │   └── arquivos baixados
│
├── req_report/
│   └── relatórios HTML
│
├── relatorio_execucao.json
└── manifest_requerimentos.json
```

---

## Relatórios

A automação gera relatórios HTML com informações como:

* Dados principais do requerimento
* Dados extraídos do CCT
* Conferência SCH x CCT
* Comparação das datas do SCH e do CCT
* Situação SAR / Corrigir Minuta
* Dispositivos normativos encontrados
* Documentos processados
* Alertas e incongruências

---

## Geração do executável

Antes de gerar o executável, compile os arquivos principais:

```powershell
python -m py_compile .\automacao_sch_explicita\main.py .\automacao_sch_explicita\fluxo_sch.py .\automacao_sch_explicita\funcoes_sch.py .\automacao_sch_explicita\pdf_parser.py
```

Se não aparecer nenhum erro, limpe builds antigos:

```powershell
Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
```

Gere o executável com PyInstaller:

```powershell
python -m PyInstaller .\AutomacaoSCH.spec --clean --noconfirm
```

O executável será criado na pasta:

```text
dist/
```

Normalmente a estrutura será:

```text
dist/
└── AutomacaoSCH/
    ├── AutomacaoSCH.exe
    └── _internal/
```

Para distribuir para outros usuários, envie a pasta inteira `AutomacaoSCH`, não apenas o `.exe`.

---

## Como enviar o executável para usuários

O recomendado é compactar localmente a pasta gerada:

```text
dist\AutomacaoSCH
```

Depois envie o `.zip` pelo SharePoint, OneDrive ou outro meio.

Não envie a pasta solta para o SharePoint gerar o `.zip` automaticamente, pois isso pode causar erro de pasta compactada vazia ou incompleta.

---

## Atenção sobre o ambiente virtual

A pasta `.venv` não deve ser enviada para o GitHub.

Cada computador deve criar sua própria `.venv` com:

```powershell
py -m venv .venv
```

Se a `.venv` for copiada de outro computador, ela pode apontar para um Python que não existe e gerar erro como:

```text
No Python at 'C:\Program Files\Python312\python.exe'
```

---

## Comandos Git úteis

Verificar situação do repositório:

```powershell
git status
```

Baixar atualizações do GitHub:

```powershell
git pull origin main
```

Enviar alterações para o GitHub:

```powershell
git add .
git commit -m "Descrição da alteração"
git push origin main
```

Ver histórico de commits:

```powershell
git log --oneline --all --graph --decorate
```

---

## Observações importantes

* O login no SCH é manual.
* O navegador pode exibir aviso de automação; basta continuar o fluxo pelo terminal.
* O sistema SCH pode bloquear salvamentos em alguns casos; por isso algumas etapas validam se o texto foi realmente confirmado após salvar.
* A automação não substitui a revisão técnica humana. Quando o relatório indicar `NC`, `REVISAR` ou divergência, o requerimento deve ser conferido manualmente.
* Os CCTs não são totalmente padronizados entre OCDs, então o parser possui vários tratamentos e fallbacks para tentar extrair os dados corretamente.

---

## Principais análises realizadas

A automação tenta verificar:

* Número do certificado
* Número de homologação
* Modelo
* Nome comercial
* Fabricante
* Tipo de produto
* Datas de emissão e validade
* Tabela técnica SCH x CCT
* Faixa de frequências
* Potência máxima de saída
* Designação de emissões
* Intensidade de campo, quando existir
* SAR Cabeça e SAR Corpo
* Aplicabilidade de SAR
* Normas e atos aplicáveis
* Características técnicas secundárias

---

## Manutenção

Arquivos principais:

```text
main.py
```

Entrada do sistema e menu principal.

```text
fluxo_sch.py
```

Fluxo principal de processamento dos requerimentos.

```text
funcoes_sch.py
```

Funções de interação com o SCH/Mosaico.

```text
pdf_parser.py
```

Extração de dados do CCT.

```text
gerador_relatorio.py
```

Geração dos relatórios HTML.

```text
caracteristicas_secundarias.py
```

Regras para preenchimento de características técnicas secundárias.

```text
base_requisitos.py
```

Regras normativas utilizadas na análise.
