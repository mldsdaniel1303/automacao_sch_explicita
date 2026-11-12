"""Valores artificiais para testes públicos; não são transcrição de um processo SCH."""


def tabela_sintetica():
    return {'cabecalho':['Faixa de Frequências Tx (MHz)', 'Potência Máxima de Saída (W)',
                        'Designação de Emissões','Tecnologias','Tipo de Modulação','SAR (W/kg) Corpo'],
            'linhas':[[f'{100+i} a {101+i}', f'0,{1000+i}', f'X{i}', 'OFDM',
                       'QPSK', '-'] for i in range(35)]}
