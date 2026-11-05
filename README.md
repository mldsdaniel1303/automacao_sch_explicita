# Automação SCH - ANATEL

Projeto de automação desenvolvido em Python para auxiliar na análise, conferência e processamento de requerimentos no sistema **SCH/Mosaico da Agência Nacional de Telecomunicações (ANATEL)**.

A automação utiliza Selenium para interagir com o SCH, realizar a coleta de informações, baixar documentos, interpretar Certificados de Conformidade Técnica (CCT), analisar Relatórios de Avaliação da Conformidade Técnica (RACT) e comparar informações dos certificados com os dados cadastrados no sistema.

Além da fila **Em Análise**, o projeto também contempla a fila **Retorno Para Estudo**, oferecendo dois modos de processamento: análise tradicional de RE e Análise Simplificada.

O sistema possui mecanismos de validação, geração de relatórios, preenchimento automático de determinados campos e proteção contra alterações quando os dados não podem ser confirmados com segurança.

**Versão de referência:** v0.7.3

---

## 1. Principais funcionalidades

A automação permite:

- Acessar o SCH/Mosaico com login manual do usuário.
- Selecionar o navegador Google Chrome ou Microsoft Edge.
- Coletar requerimentos nas filas configuradas.
- Identificar tipos de produto e aplicar filtros.
- Selecionar e baixar documentos associados aos requerimentos.
- Identificar o CCT mais recente com base nos metadados dos anexos.
- Extrair informações de certificados emitidos por diferentes OCDs.
- Reconhecer tabelas técnicas presentes em múltiplas páginas.
- Comparar características técnicas cadastradas no SCH com informações dos CCTs.
- Identificar correspondências, divergências e situações inconclusivas.
- Verificar informações de SAR e sua aplicabilidade.
- Aplicar regras técnicas e normativas conforme o tipo de produto.
- Preencher Observação e Características Técnicas Secundárias quando aplicável.
- Executar operações de Corrigir Minuta nas situações previstas.
- Preencher e confirmar informações da seção Acompanhar Processo.
- Gerar relatórios HTML e JSON detalhados.
- Registrar alertas e situações que exigem revisão humana.
- Preservar o navegador aberto ao final do processamento, quando configurado.

A automação não substitui a análise técnica realizada pelos servidores e analistas responsáveis.

---

## 2. Estrutura do projeto

A estrutura principal do repositório é semelhante a:

```text
automacao_sch_explicita/
│
├── automacao_sch_explicita/
│   ├── main.py
│   ├── fluxo_sch.py
│   ├── funcoes_sch.py
│   ├── navegador.py
│   ├── pdf_parser.py
│   ├── extracao_cct.py
│   ├── analise_requerimentos.py
│   ├── base_requisitos.py
│   ├── regras_produtos.py
│   ├── caracteristicas_secundarias.py
│   ├── mvp_simplificada_re.py
│   ├── controles_acompanhar.py
│   ├── diagnostico_estrutura_sch.py
│   ├── gerador_relatorio.py
│   ├── modo_analise_local.py
│   ├── utils.py
│   ├── verificacao_pacote.py
│   ├── AutomacaoSCH_v0_7_3.spec
│   └── config/
│
├── tests/
├── docs/
├── requirements.txt
├── README.md
└── .gitignore
```

A localização de arquivos auxiliares pode variar conforme a organização do repositório.

Os diretórios `build`, `dist`, `diagnostico_sch` e as pastas de saída são utilizados durante testes e execuções e não devem ser confundidos com o código-fonte principal.

---

## 3. Requisitos

Para executar a automação pelo código-fonte:

- Windows.
- Python 3.12, versão utilizada na validação da v0.7.3.
- Google Chrome ou Microsoft Edge.
- Git, para atualização do repositório.
- Dependências Python listadas em `requirements.txt`.
- Acesso autorizado ao sistema SCH/Mosaico.
- Conexão com a rede necessária para acessar o SCH.

Para utilizar o executável distribuído, normalmente não é necessário instalar Python, desde que o pacote tenha sido corretamente compilado com suas dependências.

O acesso ao SCH continua exigindo autenticação manual.

---

## 4. Instalação em um novo computador

### 4.1. Clonar ou atualizar o repositório

Para uma instalação nova:

```powershell
git clone URL_DO_REPOSITORIO
```

Para atualizar uma cópia já existente:

```powershell
git pull origin main
```

Confirme que está na branch correta antes de atualizar.

### 4.2. Criar o ambiente virtual

Na raiz do projeto:

```powershell
py -3.12 -m venv .venv
```

Ativar:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4.3. Instalar as dependências

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Verificar a instalação:

```powershell
python -m pip check
```

Caso o sistema informe bibliotecas ausentes, confira se o ambiente virtual está ativado e se a instalação das dependências terminou corretamente.

---

## 5. Como executar a automação

Na pasta raiz do repositório:

```powershell
python .\automacao_sch_explicita\main.py
```

Também é possível acessar diretamente a pasta do código:

```powershell
cd .\automacao_sch_explicita
python main.py
```

O programa apresenta um menu interativo contendo os módulos disponíveis.

### Modos principais

| Opção | Funcionalidade |
|---|---|
| 1 | Fluxo completo SCH — Em Análise |
| 2 | Análise local de requerimentos já baixados |
| 3 | Retorno Para Estudo — análise tradicional |
| 4 | Retorno Para Estudo — Análise Simplificada |

A numeração e os textos apresentados devem ser conferidos no menu da versão instalada.

As operações executadas dependem das configurações selecionadas pelo usuário.

---

## 6. Fila Em Análise

A fila **Em Análise** utiliza o fluxo principal de avaliação dos requerimentos.

### Etapas principais

1. Abrir o SCH/Mosaico.
2. Aguardar o login manual.
3. Selecionar a fila Em Análise.
4. Configurar quantidade de registros por página.
5. Coletar e identificar os requerimentos.
6. Aplicar os filtros configurados.
7. Abrir cada requerimento selecionado.
8. Extrair informações de Dados Gerais.
9. Identificar e baixar os documentos necessários.
10. Localizar e interpretar o CCT.
11. Realizar a conferência SCH × CCT.
12. Aplicar as regras técnicas e normativas.
13. Avaliar Observação e Características Técnicas Secundárias.
14. Analisar SAR e Corrigir Minuta, quando aplicável.
15. Executar os preenchimentos habilitados.
16. Gerar relatórios e registrar inconsistências.

### Conferência SCH × CCT

A automação compara, quando disponíveis e interpretáveis:

- Número do certificado.
- Número de homologação.
- Modelo.
- Fabricante.
- Tipo de produto.
- Nome comercial como informação contextual.
- Data de emissão.
- Data de validade.
- Frequências de operação.
- Potências técnicas.
- Intensidade de campo, quando aplicável.
- Informações de emissão e modulação como contexto.
- SAR, quando aplicável e interpretável.

A ausência de informação ou uma correspondência inconclusiva deve ser registrada para revisão, e não interpretada automaticamente como conformidade.

### Observação

A rotina de Em Análise utiliza informações do CCT e regras técnicas do projeto para decidir o texto de Observação.

Entre os tratamentos existentes estão:

- Equipamentos de Radiocomunicação de Radiação Restrita.
- Produtos não acabados e equipamentos destinados à integração.
- Outras situações tratadas pelas regras de produto.

O texto aplicado depende da classificação e das evidências extraídas do certificado.

### Características Técnicas Secundárias

O sistema pode preencher ou corrigir o campo **Título/Descrição para Características Técnicas Secundárias** quando há informação suficiente para identificar a característica correta.

A decisão considera informações do produto, do certificado e das características cadastradas no SCH.

Quando não existe correspondência confiável, o campo deve ser encaminhado para revisão, evitando preenchimentos arbitrários.

### SAR

A automação verifica a aplicabilidade do ensaio de Taxa de Absorção Específica (SAR), considerando as informações disponíveis no CCT e as regras implementadas.

Quando existem valores reais de SAR, o sistema não deve inserir genericamente a frase:

> Ensaio de SAR não aplicável.

O preenchimento ou tratamento de SAR em Corrigir Minuta deve respeitar as condições técnicas aplicáveis.

---

## 7. Retorno Para Estudo — análise tradicional

A fila **Retorno Para Estudo** possui um fluxo tradicional próprio, destinado à avaliação das alterações apresentadas pelo OCD.

Esse módulo é independente da Análise Simplificada.

### Operações realizadas

- Seleção da fila Retorno Para Estudo.
- Identificação dos requerimentos elegíveis.
- Leitura das Informações Adicionais e Justificativa do OCD.
- Identificação dos tipos de RE solicitados.
- Abertura de Comparar Versões.
- Conferência das informações anteriores e atuais.
- Verificação das alterações aplicáveis ao tipo de RE.
- Análise de documentos adicionados, quando necessária.
- Aplicação das regras de Características Técnicas Secundárias.
- Tratamento de Corrigir Minuta, quando previsto.
- Geração dos relatórios técnicos.
- Avaliação da possibilidade de aprovação automática, quando habilitada e permitida pelas regras.

### Tipos de RE

As regras são avaliadas conforme o tipo de alteração informado pelo OCD.

A automação possui tratamentos para diferentes motivos, incluindo tipos RE 1, 5, 6, 10, 11 e 12, conforme a cobertura implementada.

Quando existem múltiplos motivos no mesmo requerimento, a análise deve considerar cada motivo individualmente.

### Segurança da análise

Alterações inesperadas, informações ausentes e situações não contempladas pelas regras devem ser registradas para revisão humana.

A aprovação automática não deve ocorrer quando as condições exigidas não forem comprovadas.

Os filtros de tipos de produto e as restrições específicas da análise tradicional permanecem aplicáveis.

---

## 8. Retorno Para Estudo — Análise Simplificada

A **Análise Simplificada** foi acrescentada para permitir uma conferência técnica baseada no CCT e nos dados do SCH sem executar o procedimento tradicional de Comparar Versões.

Esse módulo reutiliza operações e regras técnicas da fila Em Análise, mas mantém verificações e proteções específicas.

### 8.1. Produtos atendidos

Na implementação atual, o módulo possui escopo direcionado a:

- **Transceptor de Radiação Restrita**.
- **Estação Terminal de Acesso**.

Essa restrição refere-se aos tipos de produto elegíveis na Análise Simplificada e não ao organismo que emitiu o certificado.

### 8.2. Documentos utilizados

O modo é configurado para trabalhar com:

- Certificado de Conformidade Técnica (CCT).
- Relatório de Avaliação da Conformidade Técnica (RACT).

A conferência técnica principal utiliza os dados extraídos do CCT e as informações cadastradas no SCH.

### 8.3. Seleção do CCT

Quando existem vários CCTs associados a um requerimento, a automação identifica o mais recente utilizando a Data-Hora dos anexos do SCH, com critérios adicionais de desempate quando necessários.

A seleção não deve depender apenas da ordem visual ou do nome do arquivo.

O certificado selecionado é baixado, interpretado e utilizado na análise.

### 8.4. Comparação técnica

O módulo coleta a tabela de Características Técnicas diretamente do DOM do SCH.

O processo busca:

1. Identificar a tabela técnica correta.
2. Descartar estruturas externas de apresentação.
3. Preservar os cabeçalhos e valores originais.
4. Validar a quantidade de linhas capturadas.
5. Normalizar unidades e valores interpretáveis.
6. Comparar as informações com o CCT.
7. Registrar correspondências e divergências.
8. Classificar situações incompletas ou ambíguas como inconclusivas.

Uma comparação parcial não comprova conformidade integral.

### 8.5. Observação

A opção 4 reutiliza as regras de Observação da fila Em Análise.

Quando a Observação já existe, a rotina conservadora procura preservar o conteúdo em vez de sobrescrevê-lo desnecessariamente.

Quando o preenchimento depende de informação ausente ou incerta, a situação deve ser registrada para revisão.

### 8.6. Características Técnicas Secundárias

A rotina verifica se o campo CTS está disponível e se existe um título confiável para preenchimento.

O campo pode ser considerado não aplicável quando sua ausência legítima é confirmada.

Não é permitido substituir outro campo por um suposto equivalente apenas porque o seletor de CTS não foi encontrado.

### 8.7. SAR

A opção 4 utiliza a lógica de aplicabilidade de SAR proveniente da fila Em Análise.

Se o CCT apresentar valores reais de SAR, a automação identifica sua aplicabilidade e evita inserir a frase de não aplicabilidade.

A análise deve considerar o certificado e não apenas células isoladas sem valores.

### 8.8. Acompanhar Processo

A opção 4 possui uma rotina específica de preenchimento da seção superior **Acompanhar Processo**, localizada na aba Informações Adicionais.

O texto padrão configurado é:

> Este processo foi analisado conforme Portaria n° 2257, de 03 de março de 2022 (Análise Simplificada).

O campo não deve ser confundido com a **Descrição inferior** da aba.

#### Comportamento do checkbox

O SCH utiliza componentes PrimeFaces/JSF.

O campo superior pode não estar presente inicialmente no DOM quando o checkbox **Desejo acompanhar este processo** está desmarcado.

Por isso, a rotina:

1. Confirma a identidade do componente.
2. Utiliza o controle visual correto do checkbox.
3. Aguarda a atualização AJAX.
4. Verifica o painel superior.
5. Identifica o textarea correto.
6. Lê seu conteúdo real.
7. Avalia a necessidade do preenchimento.
8. Verifica o vínculo com o botão Salvar.
9. Executa o salvamento previsto.
10. Navega para outra seção e retorna para conferir a persistência.

Em caso de falha, a operação não deve ser repetida automaticamente sem avaliação do estado do formulário.

### 8.9. Limitações da opção 4

A Análise Simplificada:

- Não executa Comparar Versões.
- Não executa os tratamentos tradicionais de minuta do RE.
- Não aprova requerimentos automaticamente.
- Não recusa requerimentos automaticamente.
- Não altera tabelas técnicas do SCH.
- Não modifica datas divergentes automaticamente.
- Não executa o tratamento tradicional de Especificações Complementares.
- Não considera dados parcialmente interpretados como conformes.

As ações independentes de preenchimento podem ser avaliadas conforme suas próprias regras de segurança, mesmo quando a comparação técnica permanece parcial.

---

## 9. Leitura de CCTs de diferentes OCDs

O parser foi aprimorado para interpretar certificados com diferentes estruturas documentais.

**A automação não é limitada aos certificados da CPQD.**

Ela busca interpretar CCTs emitidos por diversos OCDs, incluindo CPQD, NCC, Moderna e outros.

Os certificados podem apresentar diferenças de:

- Formatação de tabelas.
- Cabeçalhos.
- Quantidade de colunas.
- Organização das informações.
- Quebras de página.
- Células mescladas.
- Unidades de medida.
- Descrição de tecnologias e modulações.
- Organização de potência e EIRP.

O projeto não deve presumir que todos os certificados utilizem o mesmo layout.

### 9.1. Estratégias de extração

O processo utiliza diferentes estratégias, conforme necessário:

**pdfplumber**

Principal biblioteca de leitura de texto e tabelas.

**Análise de geometria**

Ajuda a recuperar informações de tabelas, células e cabeçalhos dispostos em diferentes posições.

**Alinhamento textual**

Pode identificar dados técnicos quando a extração tradicional de tabelas não consegue reconhecer a estrutura.

**PyMuPDF**

Utilizado como recurso complementar de extração, incluindo funcionalidades de identificação de tabelas.

### 9.2. Extração complementar

O módulo `extracao_cct.py` auxilia no processamento de registros, colunas, grandezas, intervalos, unidades e critérios de qualidade.

As informações são selecionadas conforme a qualidade dos dados recuperados.

Alternativas ambíguas ou conflitantes devem gerar alertas, em vez de serem escolhidas arbitrariamente.

### 9.3. Tabelas em várias páginas

A automação pode identificar tabelas técnicas distribuídas em diferentes páginas.

A reconstrução de tabelas depende de evidências de continuidade, como:

- Páginas adjacentes.
- Esquema técnico compatível.
- Unidades compatíveis.
- Indicação de continuação.
- Estrutura coerente das colunas.

Tabelas distintas não devem ser unidas somente porque apresentam cabeçalhos semelhantes.

### 9.4. Diagnóstico da extração

Os resultados podem conter informações como:

- Páginas examinadas.
- Tabelas encontradas.
- Linhas recuperadas.
- Cabeçalhos identificados.
- Unidades reconhecidas.
- Estratégias utilizadas.
- Linhas rejeitadas.
- Registros normalizados.
- Proveniência das informações.
- Alertas e limitações.

Esses dados ajudam a identificar possíveis problemas de leitura e comparação.

### 9.5. Limitações conhecidas

Alguns PDFs podem apresentar estruturas que não são interpretadas integralmente.

PDFs sem camada de texto selecionável podem exigir tratamento adicional. A implementação descrita não inclui OCR como recurso geral.

Nem todos os campos extraídos são necessariamente comparados ou validados tecnicamente.

Os resultados devem distinguir entre informação identificada, correspondência confirmada e situação que exige revisão.

---

## 10. Comparação das tabelas técnicas SCH × CCT

A comparação técnica utiliza os registros extraídos das tabelas do SCH e do CCT.

### 10.1. Informações consideradas

Quando disponíveis:

- Frequência inicial e final.
- Potência máxima de saída.
- Potência EIRP.
- Intensidade de campo.
- Distância associada à intensidade de campo.
- SAR Corpo, nos pares identificados.
- Designação de emissão como contexto.
- Tecnologia como contexto.
- Modulação como contexto.

Taxas de transmissão e outros atributos podem ser extraídos sem necessariamente participar da validação técnica completa.

### 10.2. Normalização

A automação possui tratamentos para unidades como:

- Hz, kHz, MHz e GHz, conforme a grandeza e as regras implementadas.
- W e mW.
- Unidades de intensidade de campo.
- Metros, centímetros e milímetros.

A conversão depende da interpretação segura da grandeza.

Valores logarítmicos, como dBm, não são tratados simplesmente como unidades lineares.

### 10.3. Correspondência de registros

A comparação não depende exclusivamente da ordem das linhas.

Ela considera faixa de frequência, grandeza e informações técnicas de contexto.

Quando existem múltiplas linhas possíveis para uma mesma faixa, a automação precisa de evidências suficientes para confirmar a correspondência.

Se a identidade da linha permanecer ambígua, o resultado deve ser inconclusivo.

### 10.4. Potência de saída e EIRP

Potência máxima de saída e EIRP representam grandezas que não devem ser consideradas equivalentes automaticamente.

Por exemplo:

| Campo | Valor |
|---|---|
| Potência no SCH | 0,0121 W |
| Potência de saída no CCT | 0,0612 W |
| Potência EIRP no CCT | 0,0121 W |

Nesse cenário, o valor do SCH coincide numericamente com o EIRP.

Entretanto, a coincidência isolada não comprova que as grandezas são equivalentes nem que a correspondência técnica está correta.

A automação deve registrar essa situação como inconclusiva quando não houver evidência adicional suficiente.

### 10.5. Classificações

O relatório pode apresentar:

| Status | Significado |
|---|---|
| C | Conforme nos critérios efetivamente verificados |
| NC | Divergência ou não conformidade identificada |
| N/A | Não aplicável |
| REVISAR | Exige conferência humana |
| Comparação parcial | Nem todos os dados puderam ser validados |

Uma comparação parcial não deve ser transformada automaticamente em conformidade ou aprovação.

---

## 11. Validação de datas

A automação compara datas de emissão e validade entre SCH e CCT.

As diferenças são registradas no relatório.

É importante considerar que o SCH e os documentos podem apresentar informações associadas a diferentes eventos ou versões de certificação.

Por isso:

- Divergências exigem revisão.
- Datas não são corrigidas automaticamente.
- A validade é analisada conforme as regras existentes.
- O significado dos campos deve ser confirmado pelo analista quando necessário.

---

## 12. Relatórios e arquivos gerados

Os resultados são gravados na pasta de saída selecionada pelo usuário.

A estrutura pode ser semelhante a:

```text
automacao_sch_output/
│
├── requerimentos/
│   └── 00000_00/
│       ├── resumo.json
│       ├── analise_requerimento.json
│       ├── controle_downloads.json
│       ├── Certificado de Conformidade Técnica - CCT/
│       └── Relatório de Avaliação da Conformidade - RACT/
│
├── req_report/
│   └── 00000_00.html
│
├── relatorio_execucao.json
└── manifest_requerimentos.json
```

Os nomes e arquivos efetivamente produzidos podem variar conforme o módulo, as configurações e os documentos encontrados.

### 12.1. Relatório HTML

O relatório pode apresentar:

- Identificação do requerimento.
- Tipo de análise executada.
- CCT selecionado.
- Critério de seleção do certificado.
- Diagnóstico da extração.
- Informações de Dados Gerais.
- Comparação SCH × CCT.
- Registros técnicos correspondentes.
- Casos de EIRP inconclusivos.
- Informações de SAR.
- Verificação de datas.
- Resultado de Observação e CTS.
- Resultado de Acompanhar Processo.
- Alertas e pendências.
- Situação final do processamento.

### 12.2. Relatório JSON

Os arquivos JSON registram informações estruturadas para auditoria, conferência e integração com outras ferramentas.

Podem incluir dados originais, resultados técnicos, diagnósticos e situações de preenchimento.

### 12.3. Interpretação dos resultados

O status operacional de processamento concluído não significa necessariamente que todas as verificações técnicas foram conformes.

É possível que a automação conclua suas ações permitidas e ainda registre uma comparação técnica parcial que exige revisão.

---

## 13. Testes automatizados

O projeto possui testes automatizados para extração, comparação e proteção dos fluxos de preenchimento.

Na revisão v0.7.3, foi registrada a aprovação de **209 testes**, sem falhas ou testes ignorados.

Esse resultado corresponde à revisão informada e não substitui testes futuros após novas alterações.

Para executar a suíte no ambiente de desenvolvimento:

```powershell
$env:SCH_TEST_BROWSER = '1'
python -B -m unittest discover -s tests -q
```

Verificar também as dependências:

```powershell
python -m pip check
```

Os testes incluem cenários locais e simulações de interface.

Eles não substituem a validação autenticada no SCH.

### Validação de integração

Antes de distribuir uma nova versão, é recomendado verificar:

- Abertura do menu.
- Inicialização do navegador.
- Login manual.
- Seleção da fila.
- Coleta dos requerimentos.
- Download e seleção dos documentos.
- Leitura das tabelas do CCT.
- Captura das tabelas do SCH.
- Comparação técnica.
- Tratamento dos alertas.
- Segurança dos preenchimentos.
- Persistência dos campos salvos.
- Geração dos relatórios.

---

## 14. Geração do executável — v0.7.3

A versão utiliza PyInstaller para gerar um executável Windows.

O pacote deve incluir os módulos Python necessários e as dependências utilizadas na análise dos PDFs, incluindo as bibliotecas nativas do PyMuPDF.

### 14.1. Preparação

Confirme que o ambiente possui Python 3.12 e PyInstaller.

```powershell
python -m pip install pyinstaller
```

Execute os testes automatizados antes da compilação.

### 14.2. Compilar a v0.7.3

Na raiz do repositório:

```powershell
& 'C:\Program Files\Python312\python.exe' -B -m PyInstaller --clean --noconfirm --distpath dist/versao_cpqd --workpath build/versao_cpqd automacao_sch_explicita/AutomacaoSCH_v0_7_3.spec
```

O nome `versao_cpqd` identifica apenas a pasta de distribuição utilizada nessa compilação. **Ele não restringe o programa a certificados da CPQD**.

Para uma distribuição com nome neutro, pode-se utilizar outra pasta, por exemplo `dist/v0_7_3`, desde que os caminhos sejam ajustados de forma consistente.

### 14.3. Estrutura do executável

Exemplo:

```text
dist/
└── versao_cpqd/
    └── AutomacaoSCH_v0_7_3/
        ├── AutomacaoSCH_v0_7_3.exe
        └── _internal/
```

A pasta `_internal` possui dependências necessárias para o funcionamento do programa.

Não distribua somente o arquivo `.exe` quando a compilação utiliza o formato de pasta.

### 14.4. Verificar a compilação

```powershell
Test-Path ".\dist\versao_cpqd\AutomacaoSCH_v0_7_3\AutomacaoSCH_v0_7_3.exe"
```

Se o retorno for `True`, o arquivo existe nesse local.

A existência do arquivo não garante, isoladamente, o funcionamento de todas as rotinas; é necessário executar os testes do pacote.

---

## 15. Distribuição do executável

Para distribuir a automação, compacte toda a pasta gerada pelo PyInstaller.

Exemplo:

```powershell
Compress-Archive `
  -Path ".\dist\versao_cpqd\AutomacaoSCH_v0_7_3" `
  -DestinationPath ".\dist\AutomacaoSCH_v0_7_3_teste.zip" `
  -Force
```

O ZIP deve conter a pasta da aplicação, o executável e o diretório `_internal`.

Após receber o pacote, o usuário deverá extrair seu conteúdo antes de executar o programa.

### Recomendações de distribuição

- Preservar cópias das versões anteriores.
- Identificar claramente a versão do pacote.
- Testar em outro computador Windows.
- Confirmar as versões de Chrome/Edge e os drivers utilizados.
- Não incluir relatórios de requerimentos dentro do ZIP.
- Não incluir arquivos de autorização institucional de testes.
- Utilizar apenas meios de distribuição autorizados pela organização.
- Respeitar eventuais políticas corporativas de segurança e liberação de executáveis.

Não é recomendado tentar contornar bloqueios de segurança do Windows ou do ambiente corporativo.

---

## 16. Git e versionamento

### Verificar alterações

```powershell
git status
```

### Atualizar a branch

```powershell
git pull origin main
```

### Ver arquivos modificados

```powershell
git diff --name-only
```

### Adicionar alterações

Depois de conferir os arquivos que serão versionados:

```powershell
git add README.md
```

Adicione os demais arquivos de código, testes e configuração que façam parte da versão.

Evite utilizar `git add .` sem verificar previamente os arquivos incluídos.

### Criar o commit

```powershell
git commit -m "feat: atualiza automacao SCH v0.7.3 com analise simplificada e melhorias CCT"
```

### Enviar ao GitHub

```powershell
git push origin main
```

O comando considera que `main` seja a branch utilizada pelo projeto.

### Histórico

```powershell
git log --oneline --all --graph --decorate
```

---

## 17. Arquivos que não devem ser versionados

Os seguintes arquivos e diretórios normalmente devem ser ignorados:

```text
.venv/
__pycache__/
*.pyc

build/
dist/

diagnostico_sch/
browser_downloads/

*.log
```

Também não devem ser enviados automaticamente:

- Relatórios contendo dados internos de requerimentos.
- CCTs e RACTs reais sem autorização de compartilhamento.
- Arquivos de autorização institucional preenchidos.
- Informações de sessão.
- Cookies e credenciais.
- Dados internos utilizados em testes autenticados.

As fixtures de testes devem conter apenas dados adequados ao versionamento autorizado.

O arquivo `.gitignore` precisa ser revisado para evitar a inclusão acidental de informações sensíveis.

---

## 18. Atenção ao ambiente virtual

A pasta `.venv` não deve ser copiada entre computadores nem enviada ao GitHub.

Cada ambiente deve criar sua própria instalação.

```powershell
py -3.12 -m venv .venv
```

Copiar um ambiente virtual de outro computador pode provocar falhas de localização do interpretador, como:

```text
No Python at 'C:\Program Files\Python312\python.exe'
```

---

## 19. Limitações e pontos de atenção

### Diferentes formatos de CCT

Os certificados emitidos pelos OCDs não seguem necessariamente o mesmo layout.

A extração pode ser parcial quando houver:

- Tabelas com estrutura incomum.
- Células mescladas.
- Tabelas com cabeçalhos incompletos.
- PDFs sem camada de texto.
- Valores técnicos em formatos não reconhecidos.
- Unidades ausentes.
- Tabelas divididas sem indicação de continuidade.

### Comparação técnica

Uma mesma faixa de frequência pode conter diferentes tecnologias, emissões e valores de potência.

Nem sempre é possível identificar uma correspondência única.

A coincidência numérica entre potência de saída e EIRP não implica conformidade.

### Acesso ao SCH

O portal pode apresentar:

- Carregamentos lentos.
- Sessões expiradas.
- Falhas de AJAX.
- Alterações no DOM.
- Componentes condicionais.
- Campos inicialmente ocultos.
- Erros de salvamento.

A automação utiliza esperas e validações, mas alterações na interface podem exigir manutenção dos seletores.

### Segurança operacional

As ações que modificam o SCH devem ser acompanhadas de validações de identidade e, quando implementado, confirmação da persistência.

Falhas ocorridas após tentativas de salvamento podem deixar o estado do servidor indeterminado.

Nesses casos, é necessário conferir o requerimento antes de qualquer repetição manual ou automatizada.

---

## 20. Principais arquivos e responsabilidades

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Menu e entrada da automação |
| `fluxo_sch.py` | Controle dos fluxos de processamento |
| `funcoes_sch.py` | Interação com o SCH e rotinas auxiliares |
| `navegador.py` | Configuração e inicialização dos navegadores |
| `pdf_parser.py` | Leitura e interpretação dos certificados |
| `extracao_cct.py` | Extração complementar, normalização e comparação de registros |
| `analise_requerimentos.py` | Análise dos dados e documentos |
| `regras_produtos.py` | Regras relacionadas aos tipos de produto |
| `base_requisitos.py` | Requisitos e referências normativas |
| `caracteristicas_secundarias.py` | Interpretação das características técnicas secundárias |
| `mvp_simplificada_re.py` | Regras e verificações independentes da Análise Simplificada |
| `controles_acompanhar.py` | Validação dos controles superiores de Acompanhar Processo |
| `diagnostico_estrutura_sch.py` | Identificação e diagnóstico das tabelas do SCH |
| `gerador_relatorio.py` | Geração de relatórios HTML |
| `verificacao_pacote.py` | Verificação de componentes da distribuição |
| `AutomacaoSCH_v0_7_3.spec` | Configuração PyInstaller da versão |
| `tests/` | Testes automatizados |

---

## 21. Evolução da versão v0.7.3

As principais melhorias desta etapa incluem:

### Leitura de certificados

- Extração complementar com PyMuPDF.
- Melhor identificação de tabelas técnicas.
- Preservação de unidades e grandezas.
- Registro de proveniência.
- Diagnósticos detalhados de extração.
- Suporte a diferentes organizações de tabelas.

### Comparação SCH × CCT

- Captura estruturada da tabela real do SCH.
- Descarte de tabelas externas de apresentação.
- Comparação independente da ordem das linhas.
- Preservação dos valores originais.
- Separação entre potência de saída e EIRP.
- Tratamento de correspondências ambíguas.
- Comparação de SAR em pares identificados.

### Retorno Para Estudo — Análise Simplificada

- Integração de regras da fila Em Análise.
- Seleção do CCT mais recente.
- Conferência técnica independente do RE tradicional.
- Preservação da Observação existente.
- Verificação de CTS.
- Aplicação das regras de SAR.
- Tratamento do campo superior de Acompanhar Processo.
- Espera da renderização AJAX.
- Conferência do salvamento após navegação e retorno.
- Ausência de aprovação automática.

### Testes e manutenção

- Novos testes de integração.
- Ampliação da cobertura de regressão.
- Correções nos componentes PrimeFaces.
- Melhor identificação de estruturas técnicas.
- Atualização da configuração PyInstaller.
- Preservação das rotinas tradicionais.

A validação realizada em um requerimento real demonstrou captura integral de 35 linhas do SCH e do CCT, além de confirmação de preenchimento após reabrir Acompanhar Processo.

Essa validação representa um caso de teste e não garante que todos os certificados e requerimentos apresentarão o mesmo resultado.

---

## 22. Considerações finais

A Automação SCH foi desenvolvida para auxiliar na padronização e na execução das atividades de análise técnica dos requerimentos de certificação de produtos para telecomunicações.

O projeto contempla diferentes OCDs, tipos de produtos e modalidades de análise, utilizando regras técnicas, validações documentais e mecanismos de proteção contra preenchimentos indevidos.

As verificações devem permanecer conservadoras quando os documentos apresentarem informações ausentes, divergentes ou tecnicamente ambíguas.

**A automação é uma ferramenta de apoio ao analista e não substitui sua responsabilidade pela avaliação técnica e pela decisão administrativa.**
