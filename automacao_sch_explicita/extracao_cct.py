"""Normalização conservadora e extração complementar local de tabelas CCT."""
import re
import unicodedata


def normalizar(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(texto or ''))
                           if not unicodedata.combining(c)).lower().split())


def coluna(texto):
    t = normalizar(texto)
    if 'frequenc' in t or 'frequency' in t:
        return 'frequencia_inicial' if 'inicial' in t else 'frequencia_final' if 'final' in t else 'frequencia'
    if 'eirp' in t:
        return 'potencia_eirp'
    if 'intensidade' in t or 'field strength' in t:
        return 'intensidade_campo'
    if 'distancia' in t or 'distance' in t:
        return 'distancia'
    if any(p in t for p in ('radiada', 'irradiada', 'conduzida', 'conducted', 'radiated')):
        return 'nao_interpretado'
    if ('potencia' in t or 'power' in t) and ('saida' in t or 'output' in t or 'tx power' in t or 'transmit power' in t):
        return 'potencia_saida'
    return 'nao_interpretado'


NUM = r'[+-]?\d+(?:[.,]\d+)*'


def numero(texto):
    t = str(texto).replace('\u00a0', '').replace(' ', '')
    if ',' in t and '.' in t:
        decimal = ',' if t.rfind(',') > t.rfind('.') else '.'
        t = t.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    else:
        t = t.replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def unidade(texto):
    m = re.search(r'(?i)(?<![a-zµμ])(GHz|MHz|kHz|dBm|mW|W|[µμu]V/m|mV/m|cm|mm|m)\b', str(texto))
    return m.group().lower().replace('µ', 'u').replace('μ', 'u') if m else ''


def escalar(valor, cabecalho, campo):
    t = str(valor or '').strip()
    m = re.fullmatch(r'\s*(' + NUM + r')\s*([a-zA-Zµμ/]+)?\s*', t)
    if not m:
        return None
    u = unidade(m.group(2) or '') or unidade(cabecalho)
    fatores = ({'ghz': 1000, 'mhz': 1, 'khz': .001} if campo.startswith('frequencia') else
               {'w': 1, 'mw': .001} if campo.startswith('potencia') else
               {'uv/m': 1, 'mv/m': 1000} if campo == 'intensidade_campo' else
               {'m': 1, 'cm': .01, 'mm': .001})
    n = numero(m.group(1))
    return n * fatores[u] if n is not None and u in fatores else None


def intervalos(valor, cabecalho):
    t = str(valor or '').strip()
    # Unidade final aplica-se a todos os intervalos; nenhuma inferência de MHz.
    u = unidade(t) or unidade(cabecalho)
    if len(set(v.lower() for v in re.findall(r'(?i)GHz|MHz|kHz', t))) > 1:
        return []
    if u not in {'ghz', 'mhz', 'khz'}:
        return []
    t = re.sub(r'(?i)\s*(?:GHz|MHz|kHz)\b', '', t)
    partes = re.split(r'\s+(?:e|and)\s+|\s*;\s*', t)
    saida = []
    for parte in partes:
        m = re.fullmatch(r'\s*(' + NUM + r')\s*(?:a|até|ate|to|[-–—])\s*(' + NUM + r')\s*', parte, re.I)
        if not m:
            return []
        a, b = (escalar(v, u, 'frequencia') for v in m.groups())
        if a is None or b is None or a < 0 or a > b:
            return []
        saida.append((a, b))
    return saida


def registros(tabela):
    cab = tabela.get('cabecalho') or []
    campos = [coluna(c) for c in cab]
    origens = tabela.get('origens_linhas') or []
    saida, rejeitadas = [], []
    for n, linha in enumerate(tabela.get('linhas') or [], 1):
        reconhecidos = [c for c, v in zip(campos, linha) if c != 'nao_interpretado' and str(v or '').strip()]
        if len(set(reconhecidos)) != len(reconhecidos):
            rejeitadas.append({'linha': n, 'motivo': 'colunas_da_mesma_grandeza_ambiguas', 'original': linha})
            continue
        dados = {}
        for campo, header, valor in zip(campos, cab, linha):
            if campo not in dados or str(valor or '').strip():
                dados[campo] = (header, valor)
        faixas = intervalos(dados['frequencia'][1], dados['frequencia'][0]) if 'frequencia' in dados else []
        if not faixas and all(c in dados for c in ('frequencia_inicial', 'frequencia_final')):
            a, b = [escalar(dados[c][1], dados[c][0], c) for c in ('frequencia_inicial', 'frequencia_final')]
            if a is not None and b is not None and 0 <= a <= b:
                faixas = [(a, b)]
        if not faixas:
            rejeitadas.append({'linha': n, 'motivo': 'frequencia_ausente_ou_ambigua', 'original': linha})
            continue
        for a, b in faixas:
            r = {'frequencia_inicial_mhz': a, 'frequencia_final_mhz': b,
                 'original': list(linha), 'linha_origem': n,
                 **(origens[n-1] if n <= len(origens) else {})}
            r['pagina_origem'] = r.get('pagina')
            r['tabela_origem'] = r.get('tabela')
            for campo, sufixo in [('potencia_saida', 'w'), ('potencia_eirp', 'w'),
                                   ('intensidade_campo', 'uv_m'), ('distancia', 'm')]:
                r[campo + '_' + sufixo] = escalar(dados[campo][1], dados[campo][0], campo) if campo in dados else None
            saida.append(r)
    return saida, rejeitadas


def qualidade(tabela):
    regs, rejeitadas = registros(tabela)
    chaves = ('frequencia_inicial_mhz', 'frequencia_final_mhz', 'potencia_saida_w',
              'potencia_eirp_w', 'intensidade_campo_uv_m', 'distancia_m')
    unicos = {tuple(r[k] for k in chaves) for r in regs}
    uteis = sum(any(v is not None for v in chave[2:5]) for chave in unicos)
    return (uteis, len(unicos), -len(rejeitadas) - (len(regs) - len(unicos)))


def extrair_complementar(caminho):
    """Import tardio: não carrega PyMuPDF na inicialização da automação."""
    import pymupdf
    saida = []
    with pymupdf.open(str(caminho)) as pdf:
        for pagina, page in enumerate(pdf, 1):
            for tabela in page.find_tables().tables:
                x0, topo, x1, _ = tabela.bbox
                contexto = page.get_text('text', clip=(x0, max(0, topo-60), x1, topo))
                saida.append({'pagina': pagina, 'bruto': tabela.extract(), 'estrategia': 'pymupdf_linhas',
                              'continuacao_explicita': bool(re.search(r'\bcontinua(?:ção|cao|tion)\b', contexto, re.I))})
    return saida


def montar_tabelas(candidatos):
    """Mantém tabelas distintas; junta só cabeçalhos semânticos idênticos adjacentes."""
    tabelas = []
    for candidato in candidatos:
        bruto = candidato['bruto'] or []
        for inicio in range(min(5, len(bruto))):
            encontrado = False
            for altura in range(1, min(3, len(bruto)-inicio) + 1):
                pedaco = bruto[inicio:inicio+altura]
                cab = [' '.join(str(l[i] or '') for l in pedaco if i < len(l)).strip()
                       for i in range(max(map(len, pedaco)))]
                campos = [coluna(c) for c in cab]
                if not any(c.startswith('frequencia') for c in campos) or not any(c in campos for c in ('potencia_saida', 'potencia_eirp', 'intensidade_campo')):
                    continue
                corpo = bruto[inicio+altura:]
                # Não absorve uma linha de dados como parte do cabeçalho.
                if altura > 1 and any(re.search(r'\d', str(v or '')) and coluna(v) == 'nao_interpretado' for v in pedaco[-1]):
                    continue
                tab = {'cabecalho': cab, 'linhas': [], 'origens_linhas': [],
                       'paginas_origem': [candidato['pagina']], 'origem_extracao': candidato['estrategia'],
                       'continuacao_explicita': candidato.get('continuacao_explicita', False)}
                for numero_linha, linha in enumerate(corpo, inicio+altura+1):
                    if [coluna(c) for c in linha] == campos:
                        continue
                    if not any(str(c or '').strip() for c in linha):
                        continue
                    tab['linhas'].append([str(c or '').strip() for c in linha])
                    tab['origens_linhas'].append({'pagina': candidato['pagina'], 'tabela': len(tabelas)+1, 'linha': numero_linha})
                if registros(tab)[0]:
                    tabelas.append(tab)
                    encontrado = True
                    break
            if encontrado:
                break
    return tabelas


def reconstruir(tabelas):
    """Exige continuidade explícita e cabeçalhos com grandezas/unidades iguais."""
    saida, alertas, total = [], [], 0
    for tab in tabelas:
        if saida:
            anterior = saida[-1]
            assinatura = lambda t: [(coluna(c), unidade(c), normalizar(c) if coluna(c) == 'nao_interpretado' else '')
                                     for c in t['cabecalho']]
            a, b = assinatura(anterior), assinatura(tab)
            adjacente = tab['paginas_origem'][0] == anterior['paginas_origem'][-1] + 1
            if adjacente and sorted(a) == sorted(b) and len(set(a)) == len(a):
                if not tab.get('continuacao_explicita'):
                    alertas.append('Cabeçalhos compatíveis em páginas adjacentes sem continuidade explícita; tabelas mantidas separadas.')
                else:
                    anterior = dict(anterior, linhas=list(anterior['linhas']),
                                    origens_linhas=list(anterior['origens_linhas']),
                                    paginas_origem=anterior['paginas_origem'] + tab['paginas_origem'])
                    for linha, origem in zip(tab['linhas'], tab['origens_linhas']):
                        nova = [linha[b.index(c)] if b.index(c) < len(linha) else '' for c in a]
                        if nova in anterior['linhas']:
                            alertas.append('Registro repetido na continuação preservado como ambiguidade para revisão.')
                        anterior['linhas'].append(nova)
                        anterior['origens_linhas'].append(origem)
                    saida[-1] = anterior
                    total += 1
                    continue
        saida.append(tab)
    return saida, alertas, total


def selecionar(tabelas):
    """Empates preservam pdfplumber; quantidade bruta não mede cobertura técnica."""
    return max(tabelas, key=qualidade) if tabelas else {'cabecalho': [], 'linhas': []}


def classificar_tabela(cabecalho, contexto=''):
    """Classifica por cabeçalhos e grandezas; PoE e alimentação não são RF."""
    t = normalizar(' '.join(str(c or '') for c in cabecalho))
    ctx = normalizar(contexto)
    if 'part number' in t and 'modelo' in t:
        return 'modelos_part_numbers'
    if ('laborator' in t) and ('relatorio' in t or 'test report' in t):
        return 'relatorios_ensaio'
    if ('revisao' in t or 'version' in t or 'versao' in t) and ('emissao' in t or 'issue date' in t or 'emission date' in t):
        return 'historico_revisao'
    if 'alimentacao' in t or 'acessorio' in t:
        return 'alimentacao_acessorios'
    if any(k in t for k in ('unidade fabril', 'unidades fabris', 'factory unit', 'manufacturer units')):
        return 'unidades_fabris'
    campos = [coluna(c) for c in cabecalho]
    if any(c.startswith('frequencia') for c in campos) and any(c in campos for c in ('potencia_saida','potencia_eirp','intensidade_campo')):
        if re.search(r'\b(?:mhz|ghz|khz)\b', t) and 'poe' not in t:
            return 'radiofrequencia'
    if ('entrada' in t and 'saida' in t) or ('poe' in t) or ('caracteristicas tecnicas basicas' in ctx and re.search(r'\b(?:vca|vcc|vac|vdc)\b', t)):
        return 'caracteristicas_eletricas'
    return 'administrativa'


def extrair_estruturas(candidatos):
    """Inventário das tabelas originais, inclusive cabeçalhos internos em molduras."""
    saida = []
    for cand in candidatos:
        if cand['estrategia'] != 'pdfplumber_linhas':
            continue
        bruto = cand.get('bruto_original', cand['bruto']) or []
        if cand['bruto'] and classificar_tabela(cand['bruto'][0]) == 'radiofrequencia':
            bruto = cand['bruto']
        inicio, tipo, indices = 0, 'administrativa', []
        for i, linha in enumerate(bruto):
            preenchidas = [j for j,c in enumerate(linha) if str(c or '').strip()]
            # Molduras de página com parágrafos inteiros não são cabeçalhos.
            if not preenchidas or any(len(str(linha[j])) > 180 for j in preenchidas):
                continue
            classe = classificar_tabela([linha[j] for j in preenchidas])
            if classe != 'administrativa':
                inicio, tipo, indices = i, classe, preenchidas
                break
        if not indices:
            indices = list(range(len(bruto[0]))) if bruto else []
        cab = [str(bruto[inicio][j] or '').replace('\n',' ') for j in indices] if bruto else []
        linhas, origens = [], []
        anterior_lab = None
        for n, original in enumerate(bruto[inicio+1:], inicio+2):
            valores = [original[j] if j < len(original) else '' for j in indices]
            if tipo == 'relatorios_ensaio':
                if any(re.search(r'(?i)observa[çc][õo]es', str(v or '')) for v in valores):
                    break
                if valores and valores[0] is None:
                    valores[0] = anterior_lab
                if valores and valores[0]:
                    anterior_lab = valores[0]
            if any(str(v or '').strip() for v in valores):
                linhas.append([str(v or '').strip() for v in valores])
                origens.append({'pagina':cand['pagina'], 'linha':n})
        saida.append({'tipo':tipo, 'pagina_origem':cand['pagina'], 'cabecalho':cab,
                      'linhas':linhas, 'origens_linhas':origens, 'extrator':cand['estrategia']})
    return saida


def extrair_modelos_part_numbers(estruturas):
    saida = []
    for tab in estruturas:
        if tab['tipo'] != 'modelos_part_numbers':
            continue
        cab = [normalizar(c) for c in tab['cabecalho']]
        modelo = next(i for i,c in enumerate(cab) if 'modelo' in c)
        part = next(i for i,c in enumerate(cab) if 'part number' in c)
        descricao = next((i for i,c in enumerate(cab) if 'descri' in c or 'interface' in c), None)
        for linha in tab['linhas']:
            desc = linha[descricao] if descricao is not None else ''
            poe = re.search(r'(?i)pot[eê]ncia\s+PoE\s*:\s*(' + NUM + r')\s*W\b', desc)
            saida.append({'modelo':linha[modelo], 'part_numbers':linha[part].split(),
                          'descricao_interfaces':desc, 'potencia_poe_w':numero(poe.group(1)) if poe else None,
                          'pagina_origem':tab['pagina_origem']})
    return saida


def extrair_secoes(textos_paginas):
    """Seções textuais mantêm página, ordem e conteúdo, sem alimentar Observação SCH."""
    padrao = re.compile(r'^\s*(?:\d+[)\.]\s*)?\.?\s*(Caracter[ií]sticas T[eé]cnicas B[aá]sicas|Observa[çc][õo]es|Unidade\(s\) Fabril\(is\)|Unidades Fabris|Hist[oó]rico (?:de|da) Revis[aã]o|Relat[oó]rio\(s\) de Testes e Laborat[oó]rio\(s\)|Informa[çc][õo]es Adicionais)\s*[:/]?.*$', re.I | re.M)
    secoes = []
    for pagina, texto in enumerate(textos_paginas, 1):
        marcas = list(padrao.finditer(texto))
        for i, marca in enumerate(marcas):
            conteudo = texto[marca.end():marcas[i+1].start() if i+1 < len(marcas) else len(texto)].strip()
            # Rodapés de emissão não integram a seção nem fornecem datas históricas.
            conteudo = re.split(r'(?im)^\s*(?:Data de emiss[aã]o\s*/|FUNDA[ÇC][AÃ]O CPQD|Certificado de Conformidade T[eé]cnica v[aá]lido)', conteudo)[0].strip()
            titulo = normalizar(marca.group(1))
            tipo = ('caracteristicas_eletricas' if 'caracteristicas tecnicas basicas' in titulo else
                    'unidades_fabris' if 'fabril' in titulo or 'fabris' in titulo else
                    'historico_revisao' if 'historico' in titulo else
                    'relatorios_ensaio' if 'relatorio' in titulo else
                    'observacoes' if 'observac' in titulo else 'administrativa')
            secoes.append({'titulo':marca.group(1), 'tipo':tipo, 'pagina_origem':pagina,
                           'ordem':len(secoes)+1, 'texto':conteudo})
    return secoes


def extrair_caracteristicas_eletricas(secoes):
    saida = []
    for secao in secoes:
        if 'caracteristicas tecnicas basicas' not in normalizar(secao['titulo']):
            continue
        for linha in secao['texto'].splitlines():
            m = re.match(r'(?i)^\s*(\d+\s+)?(Entrada|Sa[ií]das?\s+USB-[AC])\s*:\s*(.+)$', linha)
            if not m:
                continue
            texto = m.group(3)
            tensoes = [{'inicial':numero(a), 'final':numero(b) if b else numero(a), 'unidade':u}
                       for a,b,u in re.findall(r'(' + NUM + r')(?:\s*[-–]\s*(' + NUM + r'))?\s*(Vca|Vcc|VAC|VDC)\b', texto, re.I)]
            # Preserva o pareamento V/A por perfil, em vez de cruzar listas.
            perfis = [{'tensao_v':numero(v), 'tipo_tensao':u, 'corrente_a':numero(a)}
                      for v,u,a in re.findall(r'(' + NUM + r')\s*(Vcc|VDC)\s*/\s*(' + NUM + r')\s*A\b', texto, re.I)]
            correntes = [numero(a) for a in re.findall(r'(' + NUM + r')\s*A\b', texto, re.I)]
            potencias = [numero(w) for w in re.findall(r'(' + NUM + r')\s*W\b', texto, re.I)]
            frequencias = re.findall(r'\d+(?:/\d+)?\s*Hz\b', texto, re.I)
            saida.append({'rotulo':m.group(2), 'quantidade':int(m.group(1)) if m.group(1) else 1,
                          'tensoes':tensoes, 'correntes_a':correntes, 'potencias_w':potencias,
                          'frequencias_alimentacao':frequencias, 'perfis_saida':perfis,
                          'original':linha, 'pagina_origem':secao['pagina_origem'], 'natureza':'eletrica_nao_rf'})
    return saida


def comparar_registros(sch, cct):
    """Só prova divergência quando a faixa e a grandeza têm par único."""
    from collections import defaultdict
    campos = [[coluna(c) for c in t.get('cabecalho') or []] for t in (sch, cct)]
    if not any(any(c.startswith('frequencia') for c in cs) for cs in campos):
        return None
    lados, problemas = [], []
    for nome, tab in [('sch', sch), ('cct', cct)]:
        regs, rejeitadas = registros(tab)
        problemas.extend({'lado': nome, **r} for r in rejeitadas)
        grupos = defaultdict(list)
        for r in regs:
            grupos[(r['frequencia_inicial_mhz'], r['frequencia_final_mhz'])].append(r)
        lados.append(grupos)
    divergencias, comparados = [], []
    for nome, tab in [('sch', sch), ('cct', cct)]:
        if tab.get('status_extracao') in {'parcial', 'ambigua', 'falha_extracao', 'sem_texto_interpretavel'}:
            problemas.append({'lado': nome, 'motivo': 'extracao_' + tab['status_extracao']})
    pares = []
    for faixa in sorted(set(lados[0]) | set(lados[1])):
        a, b = lados[0].get(faixa, []), lados[1].get(faixa, [])
        if len(a) != 1 or len(b) != 1:
            assinatura = lambda r: tuple(r[k] for k in ('potencia_saida_w', 'potencia_eirp_w', 'intensidade_campo_uv_m', 'distancia_m'))
            aa = {assinatura(r): r for r in a}
            bb = {assinatura(r): r for r in b}
            if a and b and len(aa) == len(a) and len(bb) == len(b) and aa.keys() == bb.keys():
                pares.extend((faixa, [r], [bb[chave]]) for chave, r in aa.items())
            else:
                problemas.append({'faixa': faixa, 'motivo': 'correspondencia_ausente_ou_duplicada'})
            continue
        pares.append((faixa, a, b))
    for faixa, a, b in pares:
        for campo in ('potencia_saida_w', 'potencia_eirp_w', 'intensidade_campo_uv_m', 'distancia_m'):
            if campo in {'intensidade_campo_uv_m', 'distancia_m'} and any(r['intensidade_campo_uv_m'] is not None for r in (a[0], b[0])):
                d1, d2 = a[0]['distancia_m'], b[0]['distancia_m']
                if d1 is None or d2 is None or abs(d1-d2) > 1e-9:
                    if campo == 'intensidade_campo_uv_m':
                        problemas.append({'faixa': faixa, 'campo': campo, 'motivo': 'distancia_ausente_ou_distinta'})
                    continue
            # Distância só faz sentido junto da intensidade de campo.
            if campo == 'distancia_m' and not all(r['intensidade_campo_uv_m'] is not None for r in (a[0], b[0])):
                continue
            x, y = a[0][campo], b[0][campo]
            if x is None and y is None:
                continue
            if x is None or y is None:
                problemas.append({'faixa': faixa, 'campo': campo, 'motivo': 'valor_ou_unidade_ausente'})
                continue
            if campo not in comparados:
                comparados.append(campo)
            if abs(x-y) > max(1e-9, max(abs(x), abs(y))*1e-6):
                divergencias.append({'tipo': 'valor_divergente', 'faixa': faixa, 'coluna': campo,
                                     'valor_sch': x, 'valor_cct': y, 'pagina': b[0].get('pagina')})
        if not any(a[0][k] is not None and b[0][k] is not None for k in ('potencia_saida_w', 'potencia_eirp_w', 'intensidade_campo_uv_m')):
            problemas.append({'faixa': faixa, 'motivo': 'grandeza_tecnica_ausente_ou_nao_identificada'})
    return {'status': 'divergente' if divergencias else 'comparacao_parcial' if problemas or not comparados else 'ok',
            'motivo': 'Correspondência por faixa, grandeza e unidade; demais campos não validados.',
            'divergencias': divergencias, 'inconclusivos': problemas,
            'linhas_sch': sum(map(len, lados[0].values())), 'linhas_cct': sum(map(len, lados[1].values())),
            'linhas_extraidas_sch': len(sch.get('linhas') or []), 'linhas_extraidas_cct': len(cct.get('linhas') or []),
            'usar_potencia': any(c.startswith('potencia') for c in comparados),
            'usar_intensidade': 'intensidade_campo_uv_m' in comparados,
            'campos_comparados': ['frequencia_inicial_mhz', 'frequencia_final_mhz'] + comparados,
            'colunas_ignoradas_do_cct': [c for c in cct.get('cabecalho') or [] if coluna(c) == 'nao_interpretado']}


def tecnica_transmissao(valor):
    """Normaliza só a técnica genérica; não valida a tecnologia completa."""
    t = normalizar(valor)
    for tecnica, padrao in [('FHSS', r'\bfhss\b|salto em frequencia'),
                            ('DSSS', r'\bdsss\b|sequencia direta'), ('OFDM', r'\bofdm\b')]:
        if re.search(padrao, t):
            return tecnica
    return ''


def _contexto_registro(registro, cabecalho):
    contexto = {}
    for cab, valor in zip(cabecalho, registro['original']):
        t = normalizar(cab)
        limpo = re.sub(r'[^a-z0-9]+', '', normalizar(valor))
        if 'tecnolog' in t or 'technology' in t:
            contexto['tecnica'] = tecnica_transmissao(valor)
        elif 'emiss' in t and limpo:
            contexto['emissao'] = limpo
        elif 'modula' in t and limpo:
            contexto['modulacao'] = ' '.join(sorted(re.findall(r'[a-z0-9]+', normalizar(valor))))
        elif 'sar' in t and ('corpo' in t or 'body' in t) and re.search(r'w\s*/\s*kg', t):
            m = re.fullmatch(r'\s*(' + NUM + r')\s*(?:W\s*/\s*kg)?\s*', str(valor or ''), re.I)
            contexto['sar_corpo_w_kg'] = numero(m.group(1)) if m else None
    return contexto


def comparar_correspondencias(sch, cct):
    """Correspondência um a um por contexto; coincidência numérica não prova identidade."""
    a, rejeitadas_a = registros(sch)
    b, rejeitadas_b = registros(cct)
    ctx_a = [_contexto_registro(r, sch.get('cabecalho') or []) for r in a]
    ctx_b = [_contexto_registro(r, cct.get('cabecalho') or []) for r in b]
    iguais = lambda x,y: x is not None and y is not None and abs(x-y) <= max(1e-9,max(abs(x),abs(y))*1e-6)
    candidatos, propostas = [], []
    for i, r in enumerate(a):
        mesma_faixa = [j for j,s in enumerate(b) if iguais(r['frequencia_inicial_mhz'],s['frequencia_inicial_mhz'])
                       and iguais(r['frequencia_final_mhz'],s['frequencia_final_mhz'])]
        filtrados = []
        for j in mesma_faixa:
            comuns = [k for k in ('emissao','tecnica','modulacao') if ctx_a[i].get(k) and ctx_b[j].get(k)]
            if all(ctx_a[i][k] == ctx_b[j][k] for k in comuns):
                filtrados.append(j)
        candidatos.append(filtrados)
        propostas.append(filtrados[0] if len(filtrados)==1 else None)
    detalhes, problemas, divergencias, usados = [], [], [], set()
    campos = set()
    for i,r in enumerate(a):
        cand = candidatos[i]
        escolhido = propostas[i]
        identificado = escolhido is not None and propostas.count(escolhido)==1
        comparacoes = []
        for j in cand:
            s = b[j]
            comparacoes.append({'linha_cct':s['linha_origem'], 'pagina':s.get('pagina_origem'),
                               'potencia_saida_cct':s['potencia_saida_w'], 'eirp_cct':s['potencia_eirp_w'],
                               'coincide_saida':iguais(r['potencia_saida_w'],s['potencia_saida_w']),
                               'coincide_eirp':iguais(r['potencia_saida_w'],s['potencia_eirp_w']),
                               'sar_corpo_cct_w_kg':ctx_b[j].get('sar_corpo_w_kg'),
                               'coincide_sar_corpo':iguais(ctx_a[i].get('sar_corpo_w_kg'),ctx_b[j].get('sar_corpo_w_kg'))
                                   if ctx_a[i].get('sar_corpo_w_kg') is not None and ctx_b[j].get('sar_corpo_w_kg') is not None else None,
                               'original_cct':s['original'], 'contexto_cct':ctx_b[j]})
        item = {'linha_sch':r['linha_origem'], 'faixa':[r['frequencia_inicial_mhz'],r['frequencia_final_mhz']],
                'potencia_sch':r['potencia_saida_w'], 'original_sch':r['original'],
                'sar_corpo_sch_w_kg':ctx_a[i].get('sar_corpo_w_kg'),
                'contexto_sch':ctx_a[i], 'candidatos':comparacoes,
                'correspondencia_identificada':identificado,
                'coincide_saida':any(c['coincide_saida'] for c in comparacoes),
                'coincide_eirp':any(c['coincide_eirp'] for c in comparacoes)}
        if not identificado:
            item.update(resultado='correspondencia_ambigua' if cand else 'sem_correspondencia',
                        motivo='Coincidência de potência ou SAR isolada não identifica uma linha em frequência repetida.')
            if item['coincide_eirp'] and not item['coincide_saida']:
                item['motivo'] += ' Valor SCH coincide numericamente apenas com EIRP entre os candidatos; equivalência de grandezas não confirmada.'
        else:
            usados.add(escolhido)
            s = b[escolhido]
            item.update(comparacoes[0])
            campos.update(('frequencia_inicial_mhz','frequencia_final_mhz'))
            if item['coincide_eirp'] and not item['coincide_saida']:
                item.update(resultado='coincidencia_apenas_eirp',
                            motivo='Valor do SCH coincide com a potência média EIRP do CCT, mas a equivalência entre as grandezas não está confirmada. Revisão manual necessária.')
            elif s['potencia_eirp_w'] is not None:
                item.update(resultado='grandeza_potencia_inconclusiva',
                            motivo='CCT contém EIRP; confirmar a grandeza cadastrada no SCH antes de concluir.')
            elif r['potencia_saida_w'] is None or s['potencia_saida_w'] is None:
                item.update(resultado='valor_ausente', motivo='Potência ou unidade não interpretada; não assumir zero.')
            elif item['coincide_saida']:
                campos.add('potencia_saida_w')
                item.update(resultado='coincidente_saida', motivo='Par único por faixa e contexto; potência de saída numericamente coincidente.')
            else:
                campos.add('potencia_saida_w')
                item.update(resultado='divergente_saida', motivo='Par único por faixa e contexto; valores de potência de saída diferentes.')
                divergencias.append({'tipo':'valor_divergente','linha':r['linha_origem'],'coluna':'potencia_saida_w',
                                     'valor_sch':r['potencia_saida_w'],'valor_cct':s['potencia_saida_w']})
            x,y = ctx_a[i].get('sar_corpo_w_kg'),ctx_b[escolhido].get('sar_corpo_w_kg')
            item['sar_corpo_sch_w_kg'],item['sar_corpo_cct_w_kg'] = x,y
            item['sar_resultado'] = 'nao_comparado'
            if x is not None and y is not None:
                campos.add('sar_corpo_w_kg')
                item['sar_resultado'] = 'coincidente' if iguais(x,y) else 'divergente'
                if not iguais(x,y):
                    divergencias.append({'tipo':'valor_divergente','linha':r['linha_origem'],'coluna':'sar_corpo_w_kg','valor_sch':x,'valor_cct':y})
        detalhes.append(item)
        if item['resultado'] != 'coincidente_saida':
            problemas.append(dict(item, campo='Correspondência e grandeza de potência'))
    sem_par = [{'linha_cct':r['linha_origem'],'pagina':r.get('pagina_origem'), 'motivo':'Registro CCT sem par inequívoco na entrada SCH.'}
               for j,r in enumerate(b) if j not in usados]
    problemas.extend({'lado':'sch', **r} for r in rejeitadas_a)
    problemas.extend({'lado':'cct', **r} for r in rejeitadas_b)
    if sem_par:
        problemas.append({'motivo':'Há registros CCT sem correspondência inequívoca; diferença de contagem não prova divergência.'})
    for nome,tab in [('sch',sch),('cct',cct)]:
        if tab.get('status_extracao') in {'parcial','ambigua'}:
            problemas.append({'lado':nome,'motivo':'Extração '+tab['status_extracao']})
    return {'status':'divergente' if divergencias else 'comparacao_parcial' if problemas or not a else 'ok',
            'origem_sch':sch.get('origem'), 'captura_selenium':sch.get('captura_selenium'),
            'conferencia_visual_sch':sch.get('conferencia_visual_sch'),
            'resumo_correspondencias':{
                'pares_identificados':sum(d['correspondencia_identificada'] for d in detalhes),
                'linhas_ambiguas':sum(d['resultado']=='correspondencia_ambigua' for d in detalhes),
                'coincidencias_numericas_saida':sum(d['coincide_saida'] for d in detalhes),
                'coincidencias_numericas_apenas_eirp':sum(d['coincide_eirp'] and not d['coincide_saida'] for d in detalhes),
                'sar_comparado_em_par_identificado':sum(d.get('sar_resultado') in {'coincidente','divergente'} for d in detalhes)},
            'motivo':'Correspondência por faixa e contexto; EIRP e identidade ambígua exigem revisão.',
            'linhas_sch':len(a),'linhas_cct':len(b),'linhas_totais_cct':len(cct.get('linhas') or []),
            'linhas_extraidas_sch':len(sch.get('linhas') or []),'linhas_extraidas_cct':len(cct.get('linhas') or []),
            'detalhes_correspondencias':detalhes,'inconclusivos':problemas,'divergencias':divergencias,
            'registros_cct_sem_par':sem_par, 'campos_comparados':sorted(campos),
            'usar_potencia':'potencia_saida_w' in campos,'usar_intensidade':False,
            'campos_nao_validados':['Tecnologia completa: somente técnica genérica usada como contexto.',
                                    'Designação e modulação usadas para correspondência, sem validação técnica integral.',
                                    'SAR linha a linha somente comparado em pares identificados com valores e unidade explícitos.',
                                    'Taxa de transmissão.'],
            'colunas_ignoradas_do_cct':[], 'paginas_cct':cct.get('paginas_origem') or []}


def diagnosticar_especificacoes(texto_sch, texto_cct):
    """Somente diagnóstico de presença textual; nunca propõe edição do campo."""
    marcadores = {'caracterizacao_produto':r'tablet|transceptor de radiacao restrita',
                  'bluetooth':r'bluetooth|\bbt\b', 'wifi':r'wi.?fi|802\.11',
                  'faixa_5150_5350':r'5150\s*(?:mhz)?\s*(?:a|[-–])\s*5350',
                  'faixa_5470_5725':r'5470\s*(?:mhz)?\s*(?:a|[-–])\s*5725',
                  'uso_interno':r'ambientes internos', 'eirp':r'e\.?i\.?r\.?p',
                  'ganho':r'ganho', 'acessorios':r'acessorios', 'sar':r'\bsar\b'}
    def ganhos(texto):
        return [{'frequencia_inicial_mhz':numero(a), 'frequencia_final_mhz':numero(b), 'ganho_dbi':numero(g)}
                for a,b,g in re.findall(r'ganho combinado na faixa de frequencia de\s*(\d+)\s*mhz\s*a\s*(\d+)\s*mhz\s*:\s*('+NUM+r')\s*dbi', normalizar(texto))]
    ganhos_sch, ganhos_cct = ganhos(texto_sch), ganhos(texto_cct)
    return {'status':'presenca_textual' if texto_sch else 'sch_nao_disponivel', 'editar_campo':False,
            'ganhos_combinados':{'sch':ganhos_sch,'cct':ganhos_cct,
                                'coincidentes':[g for g in ganhos_sch if g in ganhos_cct]},
            'itens':{nome:{'cct':bool(re.search(p,normalizar(texto_cct))),
                           'sch':bool(re.search(p,normalizar(texto_sch))) if texto_sch else None}
                     for nome,p in marcadores.items()},
            'limitacao':'Presença de termos não valida valores, condições ou equivalência técnica.'}
