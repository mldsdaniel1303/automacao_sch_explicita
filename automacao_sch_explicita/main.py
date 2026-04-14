from pathlib import Path
import re
import sys

from fluxo_sch import executar_fluxo_sch
from modo_analise_local import executar_modo_analise_local


def perguntar_opcao(mensagem, opcoes_validas):
    while True:
        valor = input(mensagem).strip()
        if valor in opcoes_validas:
            return valor
        print(f"[ERRO] Opção inválida. Escolha uma destas: {', '.join(opcoes_validas)}")


def perguntar_inteiro_opcional(mensagem):
    while True:
        valor = input(mensagem).strip()
        if not valor:
            return None
        if valor.isdigit() and int(valor) > 0:
            return int(valor)
        print("[ERRO] Digite um número inteiro maior que zero, ou pressione Enter para todos.")


def perguntar_sim_nao(mensagem, padrao=True):
    sufixo = " [S/n]: " if padrao else " [s/N]: "
    valor = input(mensagem + sufixo).strip().lower()

    if not valor:
        return padrao

    return valor in {"s", "sim", "y", "yes", "1"}


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
    digitado = input("Digite o caminho da pasta ou pressione Enter para usar a pasta padrão: ").strip()

    if digitado:
        return Path(digitado).expanduser().resolve()

    return pasta_padrao


def normalizar_pasta_base_fluxo(pasta):
    """
    Garante que o fluxo completo sempre use a pasta BASE da execução,
    evitando que o usuário escolha subpastas internas e acabe duplicando
    a estrutura de saída.
    """
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

    # Caso o usuário selecione uma subpasta interna da estrutura
    if nome in subpastas_internas:
        print(f"[INFO] A pasta selecionada foi '{pasta.name}'. Usando a pasta pai como saída base.")
        return pasta.parent

    # Caso selecione diretamente a pasta de um requerimento:
    # .../requerimentos/123456
    if re.fullmatch(r"\d{3,}", pasta.name or ""):
        if pasta.parent.name.lower() == "requerimentos":
            print(
                f"[INFO] Pasta de requerimento detectada ('{pasta.name}'). "
                f"Usando a pasta base da execução."
            )
            return pasta.parent.parent

    # Caso selecione .../requerimentos/123456/anexos
    if nome == "anexos":
        pai = pasta.parent
        avo = pai.parent
        if re.fullmatch(r"\d{3,}", pai.name or "") and avo.name.lower() == "requerimentos":
            print(
                f"[INFO] Pasta de anexos de requerimento detectada ('{pasta.name}'). "
                f"Usando a pasta base da execução."
            )
            return avo.parent

    return pasta


def exibir_menu():
    print("\n" + "=" * 90)
    print("AUTOMAÇÃO SCH - MENU PRINCIPAL")
    print("=" * 90)
    print("1. Fluxo completo SCH")
    print("2. Somente analisar requerimentos já baixados")
    print("0. Sair")
    print("=" * 90)


def coletar_opcoes_fluxo_completo():
    print("\n=== FLUXO COMPLETO SCH ===")
    print("Este modo abre o SCH, entra na fila, baixa anexos, analisa documentos e")
    print("opcionalmente preenche abas no sistema.")

    pasta_escolhida = escolher_pasta(
        "Escolha a pasta base da execução",
        Path.cwd() / "automacao_sch_output",
    )

    pasta_base = normalizar_pasta_base_fluxo(pasta_escolhida)

    limite = perguntar_inteiro_opcional(
        "\nQuantos requerimentos deseja processar? "
        "(Enter = todos): "
    )

    processar_somente_pendentes = perguntar_sim_nao(
        "Deseja processar somente requerimentos ainda não processados?",
        padrao=False,
    )

    processar_apenas_radiacao_restrita = perguntar_sim_nao(
        "Deseja manter o filtro de radiação restrita?",
        padrao=True,
    )

    preencher_sch = perguntar_sim_nao(
        "Deseja preencher abas do SCH durante o processamento?",
        padrao=True,
    )

    preencher_caracteristicas = preencher_sch and perguntar_sim_nao(
        "Deseja preencher Características Técnicas?",
        padrao=True,
    )

    preencher_informacoes_adicionais = preencher_sch and perguntar_sim_nao(
        "Deseja preencher Informações Adicionais?",
        padrao=False,
    )

    preencher_minuta = preencher_sch and perguntar_sim_nao(
        "Deseja preencher Minuta?",
        padrao=True,
    )

    pausar_antes_anexos = perguntar_sim_nao(
        "Deseja manter pausa manual antes da aba Anexos?",
        padrao=False,
    )

    return {
        "pasta_base": pasta_base,
        "limite_requerimentos": limite,
        "processar_somente_pendentes": processar_somente_pendentes,
        "processar_apenas_radiacao_restrita": processar_apenas_radiacao_restrita,
        "preencher_caracteristicas": preencher_caracteristicas,
        "preencher_informacoes_adicionais": preencher_informacoes_adicionais,
        "preencher_minuta": preencher_minuta,
        "pausar_antes_anexos": pausar_antes_anexos,
    }


def coletar_opcoes_analise_local():
    print("\n=== SOMENTE ANÁLISE LOCAL ===")
    print("Este modo NÃO abre o SCH.")
    print("Ele apenas analisa documentos já baixados e gera relatórios.")
    print("\nVocê pode selecionar uma destas opções de pasta:")
    print("1. A pasta base da execução, que contém 'requerimentos/'")
    print("2. A própria pasta 'requerimentos/'")
    print("3. A pasta de um único requerimento")
    print("\nExemplos aceitos:")
    print(r"  C:\Projetos\automacao_sch_output")
    print(r"  C:\Projetos\automacao_sch_output\requerimentos")
    print(r"  C:\Projetos\automacao_sch_output\requerimentos\123456")

    pasta_base = escolher_pasta(
        "Escolha a pasta para análise local",
        Path.cwd() / "automacao_sch_output",
    )

    limite = perguntar_inteiro_opcional(
        "\nQuantos requerimentos deseja analisar? "
        "(Enter = todos): "
    )

    processar_somente_pendentes = perguntar_sim_nao(
        "Deseja analisar somente requerimentos ainda não analisados?",
        padrao=False,
    )

    return {
        "pasta_base": pasta_base,
        "limite_requerimentos": limite,
        "processar_somente_pendentes": processar_somente_pendentes,
    }


def main():
    try:
        while True:
            exibir_menu()
            opcao = perguntar_opcao("\nEscolha uma opção: ", {"0", "1", "2"})

            if opcao == "0":
                print("[INFO] Encerrando programa.")
                return

            if opcao == "1":
                opcoes = coletar_opcoes_fluxo_completo()

                print("\n" + "=" * 90)
                print("RESUMO DA EXECUÇÃO - FLUXO COMPLETO")
                print("=" * 90)
                print(f"Pasta base: {opcoes['pasta_base']}")
                print(f"Limite de requerimentos: {opcoes['limite_requerimentos'] or 'todos'}")
                print(f"Somente pendentes: {'sim' if opcoes['processar_somente_pendentes'] else 'não'}")
                print(f"Filtro radiação restrita: {'sim' if opcoes['processar_apenas_radiacao_restrita'] else 'não'}")
                print(f"Preencher Características Técnicas: {'sim' if opcoes['preencher_caracteristicas'] else 'não'}")
                print(f"Preencher Informações Adicionais: {'sim' if opcoes['preencher_informacoes_adicionais'] else 'não'}")
                print(f"Preencher Minuta: {'sim' if opcoes['preencher_minuta'] else 'não'}")
                print(f"Pausa antes de anexos: {'sim' if opcoes['pausar_antes_anexos'] else 'não'}")
                print("=" * 90)

                if perguntar_sim_nao("Deseja iniciar agora?", padrao=True):
                    executar_fluxo_sch(**opcoes)
                else:
                    print("[INFO] Execução cancelada pelo usuário.")
                return

            if opcao == "2":
                opcoes = coletar_opcoes_analise_local()

                print("\n" + "=" * 90)
                print("RESUMO DA EXECUÇÃO - ANÁLISE LOCAL")
                print("=" * 90)
                print(f"Pasta selecionada: {opcoes['pasta_base']}")
                print(f"Limite de requerimentos: {opcoes['limite_requerimentos'] or 'todos'}")
                print(f"Somente pendentes: {'sim' if opcoes['processar_somente_pendentes'] else 'não'}")
                print("=" * 90)

                if perguntar_sim_nao("Deseja iniciar agora?", padrao=True):
                    executar_modo_analise_local(**opcoes)
                else:
                    print("[INFO] Execução cancelada pelo usuário.")
                return

    except KeyboardInterrupt:
        print("\n[INFO] Execução interrompida pelo usuário.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERRO] Falha geral no programa: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()