# Revisão final e diagnóstico exclusivamente de leitura

Atualização da revisão local em 12/11/2026: 234 testes principais e 7 privados aprovados. Um erro intermitente de acesso ao arquivo temporário de relatório ocorreu na primeira execução; o reteste isolado e a repetição completa passaram, com os logs preservados localmente. A contagem de pares, SAR e campos comparados agora reflete a reclassificação conservadora entre partes do certificado, mantendo o resumo anterior para auditoria. Coincidências numéricas continuam separadas de identidade técnica confirmada.

O replay offline do comparador tradicional encontrou mudanças de identidade previstas no parser compartilhado; isso não equivale a validar operacionalmente as filas. O teste Selenium em HTML local confirmou compatibilidade entre o navegador e o driver oficial do mesmo build, sem desabilitar segurança. A captura autenticada via Selenium e a nova tentativa do serviço bloqueado permanecem pendentes; somente um novo PDF de identidade válido permite prosseguir. O relatório detalhado e os testes com dados reais permanecem privados em `dados_locais/`.

A preparação ocorre na branch de correções. Não há integração do diagnóstico ao menu, processamento de fila, aprovação, preenchimento ou salvamento. Nenhuma publicação, merge ou criação de executável faz parte desta etapa.

## Proteções e uso

`automacao_sch_explicita/diagnostico_final_cct.py` trabalha somente no requerimento que o operador abriu manualmente e que consta de um plano privado. Exige número confirmado pelo PDF de Visualizar Requerimento e vínculo do iframe, certificado e modelo esperados. A coleta preserva cada tabela, seção, família, cabeçalho, célula, ordem e informação de origem. Leituras sucessivas devem ser estáveis; paginação, virtualização, campos ocultos e larguras inconsistentes interrompem a validação.

O diagnóstico utiliza a barreira de leitura existente, com navegação limitada a Dados Gerais, Características Técnicas, Anexos e categoria CCT. Não navega a Acompanhar Processo ou ao editor de minuta. Scripts desconhecidos, comandos de teclado, ações de formulário e comandos arbitrários são bloqueados. O download exige os metadados do CCT mais recente e sua confirmação de hash/identidade, reaproveitando as funções existentes.

O link precisa apontar exatamente para a rota HTTPS de download do SCH, com identificador numérico único e sem handler de clique. Controles X, URLs de outros domínios e mudança de URL após autorização são bloqueados. Essa checagem independe do seletor que encontrou o elemento.

O operador faz o login e abre uma tela por vez. O plano é um JSON local com uma lista `casos`, contendo `requerimento`, `certificado` e `modelo`. Não distribua planos reais como exemplos públicos.

Exemplo de comando, preenchendo os valores entre marcadores com os dados locais:

```powershell
& 'C:\Program Files\Python312\python.exe' -B automacao_sch_explicita/diagnostico_final_cct.py --plano dados_locais/plano_validacao_final.json --requerimento '<numero/ano>' --driver '<caminho-do-driver-compativel>' --navegador edge --debugger 127.0.0.1:9324
```

O navegador deve estar aberto com depuração local e um perfil dedicado. Não desative verificações de certificado/TLS ou compatibilidade para contornar erros. Se não houver driver oficial compatível, registre o impedimento; uma leitura passiva por outro mecanismo deve ser identificada como tal e não valida o Selenium.

Os relatórios JSON e HTML são gravados somente em `dados_locais/validacao_final`, em diretório novo por execução. Contêm as tabelas completas, identidade, origem e hash do CCT, comparação por tabela, divergências, informações inconclusivas e auditoria. Qualquer falha fica registrada e não inicia outra tentativa de gravação, pois não há rotina de escrita neste caminho. A janela do operador permanece aberta.

## Resultado da revisão de código

- A captura e o comparador mantêm tabelas básicas, secundárias e de intensidade separadas. Ausência de seção explícita ou de correspondência única não é resolvida pela posição da tabela.
- Potência conduzida, saída, EIRP, SAR e intensidade permanecem grandezas distintas. Não há conversão de coincidência EIRP em potência de saída.
- A apresentação da análise simplificada deixou de imprimir uma mensagem genérica de conferência OK para um resultado sem declaração de conformidade integral.
- A comparação suplementar de SAR não pode gerar divergência quando a associação original das linhas é inconclusiva.
- Um par único dentro de uma parte do CCT não é considerado único quando a mesma faixa reaparece em outra parte associada. Modos celulares agrupados no SCH não são equiparados a um modo isolado sem regra de agregação comprovada. Alertas reclassificados permanecem rastreáveis como inconclusivos.
- O consolidado conta também resultados com limitações explícitas como inconclusivos; ausência de divergências não comprova conformidade integral.
- Foram comparadas com a base as rotinas de seleção, filtros, tipos RE, comparação de versões, preenchimentos e aprovação, além do main. As rotinas protegidas não receberam alterações nesta revisão. Os parâmetros novos dos comparadores permanecem exclusivos do modo simplificado.

O parser e a normalização são bibliotecas compartilhadas. Portanto, a preservação das rotinas e os testes aprovados **não garantem ausência de impacto nos valores extraídos** em todas as filas. É necessário replay representativo e conferência operacional antes da liberação.

## Separação dos dados e testes

- `dados_locais/`, `tests_local/`, PDFs, transcrições reais em `tests/fixtures/ccts/`, diretórios de diagnóstico e resultados internos são ignorados pelo Git.
- Os CCTs e extratos de relatórios reais da revisão ficam em `dados_locais/ccts`; os contratos correspondentes ficam em `tests_local`.
- Os testes públicos de captura usam valores artificiais em `tests/fixtures_sinteticas.py`. Testes legados opcionais devem pular explicitamente quando não há PDFs ou modelos institucionais privados.
- Oito scripts internos foram retirados somente do índice. Os arquivos locais foram mantidos. Isso não remove conteúdo de commits anteriores nem constitui autorização para publicar outros artefatos.
- Artefatos antigos de build/dist e entrypoints restritos já versionados precisam de revisão antes de qualquer publicação pública. Nenhum push foi realizado e o histórico não foi reescrito.
- A documentação legada fica ignorada por padrão por conter resultados internos; este documento descreve apenas o procedimento genérico e pode acompanhar o código.

Testes públicos e privados são executados separadamente:

```powershell
$env:SCH_TEST_BROWSER='1'
& 'C:\Program Files\Python312\python.exe' -B -m unittest discover -s tests -q
& 'C:\Program Files\Python312\python.exe' -B -m unittest discover -s tests_local -q
```

Uma cópia temporária sem PDFs, relatórios, diagnósticos ou documentação privada também deve executar a suíte pública sem erros, com skips explícitos para pré-requisitos locais ausentes. Skips não comprovam validação dos casos reais.

Resultado local desta revisão: 233 testes principais e 7 privados aprovados. Na cópia sem dados privados foram executados 217 testes, com 24 skips explícitos e nenhuma falha. Houve uma falha intermitente de acesso a arquivo temporário durante uma tentativa anterior; o log foi preservado e as execuções posteriores concluíram sem erro. Uma comparação AST confirmou 27 rotinas protegidas sem alteração e o main preservado. Esses resultados não substituem o teste autenticado do Selenium em navegador/driver compatíveis.

A execução autenticada desta etapa utilizou um adaptador CDP local privado após o driver oficial disponível não atender ao navegador instalado. As ações permaneceram limitadas às mesmas abas de leitura, à visualização PDF e ao link GET do CCT. A identidade foi conferida pelo PDF e pelo contexto do iframe; certificado/modelo, metadados do anexo e hash do novo arquivo foram conferidos separadamente. Uma execução foi interrompida por HTTP 500 do PDF de identidade; nenhum dado faltante foi substituído por amostra ou por identificação presumida. Os resultados individuais e o consolidado permanecem em `dados_locais/revisao_final` e `dados_locais/validacao_final_cdp`.

## Critérios antes da liberação

1. Completar as capturas autenticadas de todos os casos do plano, com identidade confirmada antes/depois e tabelas integrais estáveis.
2. Confirmar o CCT mais recente por metadados atuais e novo download, sem reutilização por nome.
3. Revisar os pares ambíguos, linhas não associadas, unidades não interpretadas e divergências cadastrais com evidência original.
4. Reexecutar casos representativos dos fluxos tradicionais de Retorno Para Estudo e Em Análise, sem ações de escrita nesta validação.
5. Revisar os artefatos históricos e fontes restritas antes de qualquer distribuição pública.

Enquanto houver captura pendente, incompatibilidade do navegador/driver ou associação não resolvida, a liberação permanece pendente. Relatórios locais de preparação não devem ser apresentados como validação autenticada concluída.
