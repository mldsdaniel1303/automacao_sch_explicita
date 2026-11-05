from pathlib import Path

import os

import re

import sys



from fluxo_sch import executar_fluxo_sch
from versao import VERSAO_APLICATIVO

from funcoes_sch import (

    listar_tipos_produto_tratamento_minuta_retorno,

    listar_tipos_produto_nao_avaliados_retorno,

)

from modo_analise_local import executar_modo_analise_local





LARGURA_MENU = 72



CATEGORIAS_ANEXOS_DISPONIVEIS = [

    "Certificado de Conformidade Técnica - CCT",

    "Relatório de Avaliação da Conformidade - RACT",

    "Relatório de Ensaio",

    "Manual do Produto",

    "Fotos do produto",

    "Fotos internas",

    "Selo ANATEL",

    "ART",

    "Contrato Social",

    "Outros",

]





def limpar_tela():

    """

    Limpa somente as telas de configuração.



    Os logs da execução não são limpos depois que o processamento começa.

    """

    try:

        os.system("cls" if os.name == "nt" else "clear")

    except Exception:

        pass





def linha(caractere="="):

    print(caractere * LARGURA_MENU)





def titulo_secao(titulo):

    print()

    linha("-")

    print(titulo)

    linha("-")





def sim_nao(valor):

    return "Sim" if valor else "Não"





def perguntar_opcao(mensagem, opcoes_validas, padrao=None):

    opcoes_validas = {str(opcao) for opcao in opcoes_validas}



    while True:

        valor = input(mensagem).strip()



        if not valor and padrao is not None:

            valor = str(padrao)



        if valor in opcoes_validas:

            return valor



        print(

            "[ERRO] Opção inválida. Escolha: "

            + ", ".join(sorted(opcoes_validas))

        )





def perguntar_inteiro_positivo(mensagem):

    while True:

        valor = input(mensagem).strip()



        if valor.isdigit() and int(valor) > 0:

            return int(valor)



        print("[ERRO] Digite um número inteiro maior que zero.")





def perguntar_inteiro_opcional(mensagem):

    while True:

        valor = input(mensagem).strip()



        if not valor:

            return None



        if valor.isdigit() and int(valor) > 0:

            return int(valor)



        print(

            "[ERRO] Digite um número inteiro maior que zero "

            "ou pressione Enter para todos."

        )





def perguntar_sim_nao(mensagem, padrao=True):

    sufixo = " [S/n]: " if padrao else " [s/N]: "



    while True:

        valor = input(mensagem + sufixo).strip().lower()



        if not valor:

            return padrao



        if valor in {"s", "sim", "y", "yes", "1"}:

            return True



        if valor in {"n", "nao", "não", "no", "0"}:

            return False



        print("[ERRO] Responda com S para sim ou N para não.")





def escolher_fila_sch():

    titulo_secao("ETAPA 1 DE 7 — FILA DO SCH")

    print("Escolha a fila antes das demais configurações.")

    print()

    print("1. Em Análise")

    print("   Analisa CCT, confere SCH × CCT e pode preencher abas.")

    print()

    print("2. Retorno Para Estudo")

    print("   Compara versões (escopo tradicional) e confere CCT x SCH (escopo amplo).")

    print()

    print("0. Voltar ao menu principal")



    opcao = perguntar_opcao("\nOpção [0-2]: ", {"0", "1", "2"})



    if opcao == "0":

        return None



    return "Em Análise" if opcao == "1" else "Retorno Para Estudo"





def escolher_navegador():

    titulo_secao("ETAPA 2 DE 7 — NAVEGADOR")

    print("1. Chrome")

    print("2. Edge")

    print("0. Voltar")



    opcao = perguntar_opcao("\nOpção [0-2]: ", {"0", "1", "2"})



    if opcao == "0":

        return None



    return "chrome" if opcao == "1" else "edge"





def escolher_requerimentos():

    titulo_secao("ETAPA 3 DE 7 — REQUERIMENTOS")

    print("1. Todos os requerimentos da fila")

    print("2. Processar uma quantidade determinada")

    print("3. Processar um requerimento específico")

    print("0. Voltar")



    opcao = perguntar_opcao("\nOpção [0-3]: ", {"0", "1", "2", "3"})



    if opcao == "0":

        return None



    if opcao == "1":

        descricao = "Todos os requerimentos da fila"

        limite = None

        requerimento_especifico = None



    elif opcao == "2":

        limite = perguntar_inteiro_positivo(

            "Quantidade de requerimentos: "

        )

        requerimento_especifico = None

        descricao = f"Primeiros {limite} requerimento(s) da fila"



    else:

        while True:

            requerimento_especifico = input(

                "Número do requerimento, exemplo 04334/26: "

            ).strip()



            if re.search(r"\d", requerimento_especifico):

                break



            print("[ERRO] Informe um número de requerimento válido.")



        limite = None

        descricao = f"Somente {requerimento_especifico}"



    somente_pendentes = perguntar_sim_nao(

        "Processar somente requerimentos ainda não processados?",

        padrao=False,

    )



    return {

        "descricao_requerimentos": descricao,

        "limite_requerimentos": limite,

        "requerimento_especifico": requerimento_especifico,

        "processar_somente_pendentes": somente_pendentes,

    }







VALORES_REGISTROS_POR_PAGINA = tuple(range(5, 101, 5))





def escolher_quantidade_exibida_sch():

    titulo_secao("ETAPA 4 DE 7 — REGISTROS POR PÁGINA")

    print(

        "Defina quantos requerimentos o SCH deverá exibir de uma vez "

        "na fila selecionada."

    )

    print()

    print("1. 10 requerimentos por página")

    print("2. 25 requerimentos por página")

    print("3. 50 requerimentos por página")

    print("4. 100 requerimentos por página — recomendado")

    print("5. Informar outro valor disponível")

    print("0. Voltar")



    opcao = perguntar_opcao(

        "\nOpção [0-5] (Enter = 4): ",

        {"0", "1", "2", "3", "4", "5"},

        padrao="4",

    )



    if opcao == "0":

        return None



    valores_rapidos = {

        "1": 10,

        "2": 25,

        "3": 50,

        "4": 100,

    }



    if opcao in valores_rapidos:

        return valores_rapidos[opcao]



    valores_texto = ", ".join(str(v) for v in VALORES_REGISTROS_POR_PAGINA)

    print(f"\nValores aceitos pelo SCH: {valores_texto}")



    while True:

        valor = input("Quantidade por página: ").strip()



        if valor.isdigit() and int(valor) in VALORES_REGISTROS_POR_PAGINA:

            return int(valor)



        print(

            "[ERRO] Digite um valor entre 5 e 100, "

            "em intervalos de 5."

        )



def escolher_categorias_anexos():

    titulo_secao("ETAPA 5 DE 7 — DOCUMENTOS")

    print("Quais categorias deseja baixar?")

    print()

    print("1. Todas as categorias")

    print("2. Somente CCT e RACT")

    print("3. Escolher categorias manualmente")

    print("4. Não baixar nenhum documento")

    print("0. Voltar")



    while True:

        opcao = perguntar_opcao(

            "\nOpção [0-4]: ",

            {"0", "1", "2", "3", "4"},

        )



        if opcao == "0":

            return None



        if opcao == "1":

            categorias = list(CATEGORIAS_ANEXOS_DISPONIVEIS)

            descricao = "Todas as categorias"

            break



        if opcao == "2":

            categorias = [

                "Certificado de Conformidade Técnica - CCT",

                "Relatório de Avaliação da Conformidade - RACT",

            ]

            descricao = "Somente CCT e RACT"

            break



        if opcao == "4":

            return {

                "categorias_anexos": [],

                "descricao_categorias": "Nenhum documento",

                "pausar_antes_anexos": False,

            }



        print("\nCategorias disponíveis:")



        for indice, categoria in enumerate(

            CATEGORIAS_ANEXOS_DISPONIVEIS,

            start=1,

        ):

            print(f"{indice:>2}. {categoria}")



        escolha = input(

            "\nDigite os números separados por vírgula. "

            "Exemplo: 1,2,3: "

        ).strip()



        indices = []



        for parte in escolha.split(","):

            parte = parte.strip()



            if parte.isdigit():

                indices.append(int(parte))



        categorias = [

            CATEGORIAS_ANEXOS_DISPONIVEIS[indice - 1]

            for indice in indices

            if 1 <= indice <= len(CATEGORIAS_ANEXOS_DISPONIVEIS)

        ]

        categorias = list(dict.fromkeys(categorias))



        if categorias:

            descricao = "Seleção manual"

            break



        print("[ERRO] Nenhuma categoria válida selecionada.")



    pausar_antes_anexos = perguntar_sim_nao(

        "Pausar para conferência manual antes de baixar os documentos?",

        padrao=False,

    )



    return {

        "categorias_anexos": categorias,

        "descricao_categorias": descricao,

        "pausar_antes_anexos": pausar_antes_anexos,

    }





# Fluxos independentes do Retorno Para Estudo.
MODOS_RE = {
    "comparar_versoes": "Comparar Versões (RE tradicional)",
    "analise_simplificada": "Análise Simplificada (CCT + RACT / CCT x SCH)",
    "ambos": "Análise Completa (dois módulos)",
}
CATEGORIAS_ANALISE_SIMPLIFICADA = [
    "Certificado de Conformidade Técnica - CCT",
    "Relatório de Avaliação da Conformidade - RACT",
]


def escolher_modo_analise_re():
    """Define funções e downloads antes de iniciar o navegador."""
    titulo_secao("ETAPA 5 DE 7 — MODALIDADE DE ANÁLISE DE RE")
    print("1. Comparar Versões — sem download de documentos")
    print("   Tipos RE permitidos, minuta, acompanhamento e possível aprovação.")
    print("2. Análise Simplificada — baixar apenas CCT e RACT")
    print("   Comparar CCT x SCH; sem Comparar Versões ou aprovação.")
    print("3. Análise Completa — executar ambos os módulos")
    print("   CCT e RACT para a conferência e Comparar Versões para RE tradicional.")
    print("0. Voltar")
    opcao = perguntar_opcao("\nOpção [0-3]: ", {"0", "1", "2", "3"})
    return {"0": None, "1": "comparar_versoes", "2": "analise_simplificada", "3": "ambos"}[opcao]


def configurar_documentos_modo_re(modo):
    """RE tradicional não baixa nada; módulo CCT exige as duas categorias."""
    if modo not in MODOS_RE:
        raise ValueError(f"Modo RE desconhecido: {modo}")
    categorias = (
        list(CATEGORIAS_ANALISE_SIMPLIFICADA)
        if modo in {"analise_simplificada", "ambos"}
        else []
    )
    return {
        "categorias_anexos": categorias,
        "descricao_categorias": (
            "Somente CCT e RACT para o módulo de análise simplificada"
            if categorias else "Sem download de anexos — Comparar Versões"
        ),
        "pausar_antes_anexos": False,
    }


def escolher_acoes_da_fila(fila_sch, modo_analise_re=None):

    titulo_secao(f"ETAPA 6 DE 7 — AÇÕES: {fila_sch.upper()}")



    if fila_sch == "Em Análise":

        print(

            "As opções abaixo controlam somente o fluxo da fila "

            "Em Análise."

        )

        print()



        processar_apenas_rr = perguntar_sim_nao(

            "Aplicar filtro de Radiação Restrita?",

            padrao=True,

        )

        preencher_caracteristicas = perguntar_sim_nao(

            "Preencher Características Técnicas?",

            padrao=True,

        )

        preencher_minuta = perguntar_sim_nao(

            "Executar análise de SAR e Corrigir Minuta quando necessário?",

            padrao=True,

        )

        preencher_informacoes = perguntar_sim_nao(

            "Preencher Informações Adicionais?",

            padrao=False,

        )



        return {

            "processar_apenas_radiacao_restrita": processar_apenas_rr,

            "preencher_caracteristicas": preencher_caracteristicas,

            "preencher_minuta": preencher_minuta,

            "preencher_informacoes_adicionais": preencher_informacoes,

            "executar_envio_retorno_para_estudo": False,

        }



    if modo_analise_re not in MODOS_RE:
        raise ValueError("É necessário escolher o tipo de análise de RE.")

    print(f"Modo de análise de RE: {MODOS_RE[modo_analise_re]}")
    tradicional = modo_analise_re in {"comparar_versoes", "ambos"}
    simplificada = modo_analise_re in {"analise_simplificada", "ambos"}
    if tradicional:
        print("[RE TRADICIONAL] Comparar Versões, Tipos RE e tratamento de minuta.")
        print("[RE TRADICIONAL] Nenhum anexo será baixado para este módulo.")
        print("[RE TRADICIONAL] Acompanhamento e aprovação seguem as regras atuais.")
        tipos_minuta = listar_tipos_produto_tratamento_minuta_retorno()
        print("\nTipos permitidos no tratamento tradicional:")
        for tipo in tipos_minuta:
            print(f"- {tipo}")
        tipos_fora_escopo = listar_tipos_produto_nao_avaliados_retorno()
        if tipos_fora_escopo:
            print("\nTipos fora da análise tradicional:")
            for tipo in tipos_fora_escopo:
                print(f"- {tipo}")
    if simplificada:
        print("[SIMPLIFICADA] Conferência e preenchimentos com regras de Em Análise.")
        if modo_analise_re == "analise_simplificada":
            print("[SIMPLIFICADA] Filtro próprio: ETA e Transceptor de Radiação Restrita.")
            print("[SIMPLIFICADA] Observação, CTS, SAR e Acompanhar Processo quando aplicáveis.")
        print("[SIMPLIFICADA] Somente categorias CCT e RACT, quando produto elegível.")
        print("[SIMPLIFICADA] Exclui quatro tipos do art. 3º e modalidade Declaração de Conformidade.")
        print("[SIMPLIFICADA] Não executa aprovação automática.")

    executar_envio = False
    if modo_analise_re != "analise_simplificada":
        executar_envio = perguntar_sim_nao(
            "Permitir aprovação automática para RE tradicional quando apto?",
            padrao=False,
        )
    else:
        print("[SCH][RETORNO] Aprovação automática indisponível na Análise Simplificada.")

    return {

        # Cada modo de RE aplica seu filtro próprio no fluxo, sem o filtro genérico de Em Análise.

        "processar_apenas_radiacao_restrita": False,

        # Estas abas não pertencem ao fluxo de Retorno Para Estudo.

        "preencher_caracteristicas": False,

        "preencher_minuta": False,

        "preencher_informacoes_adicionais": False,

        "executar_envio_retorno_para_estudo": executar_envio,

    }





def escolher_pasta(titulo, pasta_padrao):

    pasta_padrao = Path(pasta_padrao).expanduser().resolve()



    try:

        import tkinter as tk

        from tkinter import filedialog



        root = tk.Tk()

        root.withdraw()

        root.attributes("-topmost", True)



        selecionada = filedialog.askdirectory(

            title=titulo,

            initialdir=str(pasta_padrao),

        )



        root.destroy()



        if selecionada:

            return Path(selecionada).expanduser().resolve()



    except Exception:

        pass



    print(f"[INFO] Pasta padrão sugerida: {pasta_padrao}")



    digitado = input(

        "Digite o caminho ou pressione Enter para usar a pasta padrão: "

    ).strip()



    if digitado:

        return Path(digitado).expanduser().resolve()



    return pasta_padrao





def normalizar_pasta_base_fluxo(pasta):

    pasta = Path(pasta).expanduser().resolve()

    nome = pasta.name.lower()



    subpastas_internas = {

        "browser_downloads",

        "downloads_temp",

        "requerimentos",

        "req_report",

        "relatorios",

        "logs",

        "sem_nome",

        "anexos",

    }



    if nome in subpastas_internas:

        print(

            f"[INFO] A pasta selecionada foi '{pasta.name}'. "

            "Usando a pasta pai como saída base."

        )

        return pasta.parent



    if re.fullmatch(r"\d{3,}", pasta.name or ""):

        if pasta.parent.name.lower() == "requerimentos":

            print(

                f"[INFO] Pasta de requerimento detectada "

                f"('{pasta.name}'). Usando a pasta base da execução."

            )

            return pasta.parent.parent



    if nome == "anexos":

        pai = pasta.parent

        avo = pai.parent



        if (

            re.fullmatch(r"\d{3,}", pai.name or "")

            and avo.name.lower() == "requerimentos"

        ):

            print(

                "[INFO] Pasta de anexos de requerimento detectada. "

                "Usando a pasta base da execução."

            )

            return avo.parent



    return pasta





def escolher_saida_e_comportamento():

    titulo_secao("ETAPA 7 DE 7 — SAÍDA E ENCERRAMENTO")



    pasta_escolhida = escolher_pasta(

        "Escolha a pasta base da execução",

        Path.cwd() / "automacao_sch_output",

    )

    pasta_base = normalizar_pasta_base_fluxo(pasta_escolhida)



    manter_aberto = perguntar_sim_nao(

        "Manter o navegador aberto ao final da execução?",

        padrao=True,

    )



    return {

        "pasta_base": pasta_base,

        "fechar_navegador_ao_final": not manter_aberto,

    }





def coletar_opcoes_fluxo_completo():

    """

    Coleta as configurações na ordem em que elas afetam o fluxo.



    Retorna None quando o analista decide voltar ao menu principal.

    """

    while True:

        limpar_tela()

        linha()

        print("AUTOMAÇÃO SCH — NOVA EXECUÇÃO")

        linha()



        fila_sch = escolher_fila_sch()



        if fila_sch is None:

            return None



        navegador = escolher_navegador()



        if navegador is None:

            continue



        requerimentos = escolher_requerimentos()



        if requerimentos is None:

            continue



        quantidade_exibida_sch = escolher_quantidade_exibida_sch()



        if quantidade_exibida_sch is None:

            continue



        modo_analise_re = None
        if fila_sch == "Retorno Para Estudo":
            modo_analise_re = escolher_modo_analise_re()
            if modo_analise_re is None:
                continue
            documentos = configurar_documentos_modo_re(modo_analise_re)
        else:
            documentos = escolher_categorias_anexos()
            if documentos is None:
                continue

        acoes = escolher_acoes_da_fila(fila_sch, modo_analise_re)

        saida = escolher_saida_e_comportamento()



        opcoes = {

            "fila_sch": fila_sch,
            "modo_analise_re": modo_analise_re,

            "navegador": navegador,

            "quantidade_exibida_sch": quantidade_exibida_sch,

            **requerimentos,

            **documentos,

            **acoes,

            **saida,

        }



        return opcoes





def exibir_resumo_fluxo_completo(opcoes):

    limpar_tela()

    linha()

    print("RESUMO DA EXECUÇÃO")

    linha()



    print(f"Fila: {opcoes['fila_sch']}")
    if opcoes['fila_sch'] == "Retorno Para Estudo":
        print(f"Tipo de análise: {MODOS_RE[opcoes.get('modo_analise_re') or 'ambos']}")

    print(f"Navegador: {opcoes['navegador'].title()}")

    print(f"Requerimentos: {opcoes['descricao_requerimentos']}")

    print(

        "Registros exibidos por página no SCH: "

        f"{opcoes['quantidade_exibida_sch']}"

    )

    print(

        "Somente pendentes: "

        f"{sim_nao(opcoes['processar_somente_pendentes'])}"

    )

    print(f"Pasta de saída: {opcoes['pasta_base']}")



    titulo_secao("DOCUMENTOS")

    print(f"Seleção: {opcoes['descricao_categorias']}")



    if opcoes["categorias_anexos"]:

        for categoria in opcoes["categorias_anexos"]:

            print(f"- {categoria}")

    else:
        print("- Nenhum documento será baixado")



    print(

        "Pausa antes dos documentos: "

        f"{sim_nao(opcoes['pausar_antes_anexos'])}"

    )



    titulo_secao("AÇÕES")



    if opcoes["fila_sch"] == "Em Análise":

        print(

            "Filtro de Radiação Restrita: "

            f"{sim_nao(opcoes['processar_apenas_radiacao_restrita'])}"

        )

        print(

            "Características Técnicas: "

            f"{sim_nao(opcoes['preencher_caracteristicas'])}"

        )

        print(

            "Análise de SAR / Corrigir Minuta: "

            f"{sim_nao(opcoes['preencher_minuta'])}"

        )

        print(

            "Informações Adicionais: "

            f"{sim_nao(opcoes['preencher_informacoes_adicionais'])}"

        )

    else:
        modo = opcoes.get("modo_analise_re") or "ambos"
        tradicional = modo in {"comparar_versoes", "ambos"}
        simplificada = modo in {"analise_simplificada", "ambos"}
        print(f"Comparar Versões: {sim_nao(tradicional)} (tipos RE permitidos)")
        print(f"Conferência CCT x SCH: {sim_nao(simplificada)} (produtos elegíveis)")
        print(f"Download automático de CCT + RACT: {sim_nao(simplificada)}")

        print("Tratamento de Especificações Complementares: " +
              ("Automático quando aplicável" if tradicional else "Não executar"))

        print("Marcação em Acompanhar Processo: " +
              ("Automática e obrigatória no RE tradicional" if tradicional else "Análise Simplificada, substituindo pela frase configurada"))

        print(

            "Aprovação automática quando apto: "

            f"{sim_nao(opcoes['executar_envio_retorno_para_estudo'])}"

        )



    print(

        "Manter navegador aberto ao final: "

        f"{sim_nao(not opcoes['fechar_navegador_ao_final'])}"

    )



    linha()







def coletar_opcoes_retorno_padrao(modo_analise_re="comparar_versoes"):

    """

    Configuração rápida usada pelos analistas no Retorno Para Estudo.



    Valores fixos:

    - fila: Retorno Para Estudo

    - navegador: Chrome

    - requerimentos: todos

    - somente pendentes: não

    - registros por página: 100

    - Comparar Versões: nenhum anexo; Análise Simplificada: somente CCT e RACT

    - navegador permanece aberto ao final



    O usuário escolhe somente:

    - pasta base da execução;

    - permissão para aprovação automática apenas no RE tradicional.

    """

    limpar_tela()

    linha()

    print("RETORNO PARA ESTUDO — " + ("PADRÃO / COMPARAR VERSÕES" if modo_analise_re == "comparar_versoes" else "ANÁLISE SIMPLIFICADA"))

    linha()

    print(

        "Este modo aplica automaticamente a configuração normalmente "

        "utilizada pelos analistas."

    )



    titulo_secao("CONFIGURAÇÕES FIXAS")

    print("Fila: Retorno Para Estudo")

    print("Navegador: Chrome")

    print("Requerimentos: Todos os requerimentos da fila")

    print("Somente requerimentos ainda não processados: Não")

    print("Registros por página: 100")

    # O atalho 3 sempre usa Comparar Versões; o atalho 4 sempre usa CCT x SCH.
    # A escolha dos dois módulos juntos permanece somente na configuração completa.
    if modo_analise_re not in {"comparar_versoes", "analise_simplificada"}:
        raise ValueError(f"Modo não permitido neste atalho: {modo_analise_re}")
    documentos_re = configurar_documentos_modo_re(modo_analise_re)
    print(f"Tipo escolhido: {MODOS_RE[modo_analise_re]}")
    print(f"Downloads: {documentos_re['descricao_categorias']}")

    if modo_analise_re in {"comparar_versoes", "ambos"}:
        print("Tratamento de Especificações Complementares: Automático quando aplicável")
        print("Marcação em Acompanhar Processo: Automática e obrigatória no RE tradicional")
    else:
        print("Filtro próprio: Estação Terminal de Acesso (ETA) e Transceptor de Radiação Restrita")
        print("Características Técnicas e CTS: mesmas regras aplicáveis de Em Análise")
        print("Corrigir Minuta: análise de SAR do CCT, preservando textos existentes")
        print("Acompanhar Processo: registrar Análise Simplificada e confirmar salvamento")
        print("Comparar Versões: Não executar")

    print("Manter navegador aberto ao final: Sim")



    titulo_secao("APROVAÇÃO AUTOMÁTICA")

    executar_envio = False
    if modo_analise_re != "analise_simplificada":
        executar_envio = perguntar_sim_nao(
            "Permitir aprovação automática no módulo tradicional quando apto?",
            padrao=False,
        )
    else:
        print("[SCH][RETORNO] Análise Simplificada: sem aprovação automática.")



    titulo_secao("PASTA DE SAÍDA")

    pasta_escolhida = escolher_pasta(

        "Escolha a pasta base da execução",

        Path.cwd() / "automacao_sch_output",

    )

    pasta_base = normalizar_pasta_base_fluxo(pasta_escolhida)



    return {

        "fila_sch": "Retorno Para Estudo",
        "modo_analise_re": modo_analise_re,

        "navegador": "chrome",

        "quantidade_exibida_sch": 100,

        "descricao_requerimentos": "Todos os requerimentos da fila",

        "limite_requerimentos": None,

        "requerimento_especifico": None,

        "processar_somente_pendentes": False,

        **documentos_re,

        "processar_apenas_radiacao_restrita": False,

        "preencher_caracteristicas": False,

        "preencher_minuta": False,

        "preencher_informacoes_adicionais": False,

        "executar_envio_retorno_para_estudo": executar_envio,

        "pasta_base": pasta_base,

        "fechar_navegador_ao_final": False,

    }





def executar_configuracao_retorno_padrao(modo_analise_re="comparar_versoes"):

    """

    Executa o atalho de Retorno Para Estudo com configuração padrão.



    Depois das duas escolhas permitidas ao usuário, exibe um resumo final

    apenas para conferência antes de iniciar o navegador.

    """

    opcoes = coletar_opcoes_retorno_padrao(modo_analise_re=modo_analise_re)
    if opcoes is None:
        return None

    exibir_resumo_fluxo_completo(opcoes)



    print("CONFIGURAÇÃO: " + ("RE TRADICIONAL / COMPARAR VERSÕES" if modo_analise_re == "comparar_versoes" else "RE / ANÁLISE SIMPLIFICADA"))

    print()

    print("1. Iniciar execução")

    print("0. Voltar ao menu principal")



    decisao = perguntar_opcao(

        "\nOpção [0-1] (Enter = 1): ",

        {"0", "1"},

        padrao="1",

    )



    if decisao == "0":

        return None



    opcoes_execucao = dict(opcoes)

    opcoes_execucao.pop("descricao_requerimentos", None)

    opcoes_execucao.pop("descricao_categorias", None)



    print()

    linha()

    print("INICIANDO AUTOMAÇÃO — RETORNO PARA ESTUDO / " + ("COMPARAR VERSÕES" if modo_analise_re == "comparar_versoes" else "ANÁLISE SIMPLIFICADA"))

    linha()



    executar_fluxo_sch(**opcoes_execucao)

    return True





def coletar_opcoes_analise_local():

    limpar_tela()

    linha()

    print("SOMENTE ANÁLISE LOCAL")

    linha()

    print("Este modo não abre o SCH.")

    print("Ele analisa documentos já baixados e gera relatórios.")

    print()

    print("A pasta pode ser:")

    print("- a base da execução, contendo requerimentos/")

    print("- a própria pasta requerimentos/")

    print("- a pasta de um único requerimento")



    pasta_base = escolher_pasta(

        "Escolha a pasta para análise local",

        Path.cwd() / "automacao_sch_output",

    )



    limite = perguntar_inteiro_opcional(

        "\nQuantos requerimentos deseja analisar? "

        "(Enter = todos): "

    )



    somente_pendentes = perguntar_sim_nao(

        "Analisar somente requerimentos ainda não analisados?",

        padrao=False,

    )



    return {

        "pasta_base": pasta_base,

        "limite_requerimentos": limite,

        "processar_somente_pendentes": somente_pendentes,

    }





def exibir_menu():

    limpar_tela()

    linha()

    print(f"AUTOMAÇÃO SCH — v{VERSAO_APLICATIVO}")

    linha()

    print("1. Processar requerimentos diretamente no SCH")

    print("   Configuração completa / personalizada")

    print()

    print("2. Analisar documentos já baixados")

    print()

    print("3. Retorno Para Estudo — PADRÃO / COMPARAR VERSÕES")

    print("   Chrome | Todos | 100 por página | SEM DOWNLOAD DE ANEXOS")

    print("   Tipos RE, Comparar Versões, minuta e aprovação quando apto")

    print()

    print("4. Retorno Para Estudo — ANÁLISE SIMPLIFICADA")

    print("   Chrome | Todos | 100 por página | BAIXAR CCT E RACT")

    print("   Conferência CCT x SCH | Sem Comparar Versões ou aprovação")

    print()

    print("0. Sair")

    linha()





def executar_configuracao_fluxo_completo():

    while True:

        opcoes = coletar_opcoes_fluxo_completo()



        if opcoes is None:

            return None



        exibir_resumo_fluxo_completo(opcoes)



        print("1. Iniciar execução")

        print("2. Alterar configurações")

        print("0. Voltar ao menu principal")



        decisao = perguntar_opcao(

            "\nOpção [0-2]: ",

            {"0", "1", "2"},

            padrao="1",

        )



        if decisao == "0":

            return None



        if decisao == "2":

            continue



        # Campos usados apenas para apresentação não pertencem à assinatura

        # de executar_fluxo_sch.

        opcoes_execucao = dict(opcoes)

        opcoes_execucao.pop("descricao_requerimentos", None)

        opcoes_execucao.pop("descricao_categorias", None)



        print()

        linha()

        print("INICIANDO AUTOMAÇÃO")

        linha()



        executar_fluxo_sch(**opcoes_execucao)

        return True





def executar_configuracao_analise_local():

    opcoes = coletar_opcoes_analise_local()



    print()

    linha()

    print("RESUMO — ANÁLISE LOCAL")

    linha()

    print(f"Pasta selecionada: {opcoes['pasta_base']}")

    print(

        "Limite de requerimentos: "

        f"{opcoes['limite_requerimentos'] or 'todos'}"

    )

    print(

        "Somente pendentes: "

        f"{sim_nao(opcoes['processar_somente_pendentes'])}"

    )

    linha()



    if perguntar_sim_nao("Iniciar análise local agora?", padrao=True):

        executar_modo_analise_local(**opcoes)

        return True



    return None





def main():

    try:

        while True:

            exibir_menu()

            opcao = perguntar_opcao(

                "\nEscolha uma opção: ",

                {"0", "1", "2", "3", "4"},

            )



            if opcao == "0":

                print("[INFO] Encerrando programa.")

                return 0



            if opcao == "1":

                executou = executar_configuracao_fluxo_completo()



                if executou:

                    return 0



                continue



            if opcao == "2":

                executou = executar_configuracao_analise_local()



                if executou:

                    return 0



                continue



            if opcao == "3":

                executou = executar_configuracao_retorno_padrao(
                    modo_analise_re="comparar_versoes"
                )

                if executou:
                    return 0

                continue

            if opcao == "4":

                executou = executar_configuracao_retorno_padrao(
                    modo_analise_re="analise_simplificada"
                )

                if executou:
                    return 0

                continue



    except KeyboardInterrupt:

        print("\n[INFO] Execução interrompida pelo usuário.")

        print(

            "[INFO] Se o fluxo já havia iniciado, o relatório parcial "

            "é tratado no fluxo_sch.py."

        )

        return 1



    except Exception as e:

        print()

        linha()

        print("[ERRO FATAL] Falha geral no programa.")

        linha()

        print(f"Tipo: {type(e).__name__}")

        print(f"Mensagem: {e}")

        linha()

        return 1





if __name__ == "__main__":

    # Verificação explícita e exclusivamente offline, fora das quatro opções.
    # Não inicia navegador, login ou qualquer fluxo SCH.
    if sys.argv[1:2] == ["--verificar-pacote"]:
        from verificacao_pacote import verificar_cli
        sys.exit(verificar_cli(sys.argv[2:]))

    codigo_saida = 0



    try:

        codigo_saida = main() or 0



    except Exception as e:

        codigo_saida = 1

        print()

        linha()

        print("[ERRO FATAL NÃO TRATADO]")

        linha()

        print(f"Tipo: {type(e).__name__}")

        print(f"Mensagem: {e}")

        linha()



    finally:

        try:

            input("\nPressione Enter para encerrar...")

        except Exception:

            pass



    sys.exit(codigo_saida)
