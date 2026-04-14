from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def _perguntar_navegador():
    print("\nEscolha o navegador:")
    print("1. Chrome")
    print("2. Edge")

    while True:
        opcao = input("Opção [1/2]: ").strip() or "1"
        if opcao == "1":
            return "chrome"
        if opcao == "2":
            return "edge"
        print("[ERRO] Opção inválida. Escolha 1 ou 2.")


def _resolver_pastas(
    pasta_base=None,
    pasta_saida_base=None,
    pasta_saida=None,
    pasta_download=None,
):
    base = (
        pasta_base
        or pasta_saida_base
        or pasta_saida
        or (Path.cwd() / "automacao_sch_output")
    )

    base = Path(base).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)

    pasta_requerimentos = base / "requerimentos"
    pasta_relatorios = base / "relatorios"
    pasta_requerimentos.mkdir(parents=True, exist_ok=True)
    pasta_relatorios.mkdir(parents=True, exist_ok=True)

    if pasta_download:
        downloads = Path(pasta_download).expanduser().resolve()
    else:
        downloads = base / "browser_downloads"

    downloads.mkdir(parents=True, exist_ok=True)

    return base, downloads


def _criar_opcoes_chrome(download_dir):
    options = webdriver.ChromeOptions()

    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    }

    options.add_experimental_option("prefs", prefs)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-blink-features=AutomationControlled")

    return options


def _criar_opcoes_edge(download_dir):
    options = webdriver.EdgeOptions()
    options.use_chromium = True

    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    }

    options.add_experimental_option("prefs", prefs)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-blink-features=AutomationControlled")

    return options


def criar_driver(
    navegador=None,
    pasta_base=None,
    pasta_saida_base=None,
    pasta_saida=None,
    pasta_download=None,
    timeout_padrao=15,
):
    """
    Retorna:
        driver, wait, pasta_base_resolvida, pasta_download_resolvida

    Compatível com chamadas antigas e novas:
        criar_driver()
        criar_driver(pasta_base="...")
        criar_driver(pasta_saida_base="...")
        criar_driver(pasta_saida="...")
        criar_driver(pasta_base="...", pasta_download="...")
    """

    base, downloads = _resolver_pastas(
        pasta_base=pasta_base,
        pasta_saida_base=pasta_saida_base,
        pasta_saida=pasta_saida,
        pasta_download=pasta_download,
    )

    if not navegador:
        navegador = _perguntar_navegador()

    navegador = str(navegador).strip().lower()

    if navegador == "chrome":
        options = _criar_opcoes_chrome(downloads)
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

    elif navegador == "edge":
        options = _criar_opcoes_edge(downloads)
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)

    else:
        raise ValueError(f"Navegador inválido: {navegador}")

    wait = WebDriverWait(driver, timeout_padrao)

    print("\n" + "=" * 80)
    print("[NAVEGADOR] Driver iniciado com sucesso")
    print(f"[NAVEGADOR] Navegador: {navegador}")
    print(f"[NAVEGADOR] Pasta base: {base}")
    print(f"[NAVEGADOR] Pasta de downloads: {downloads}")
    print("=" * 80)

    return driver, wait, str(base), str(downloads)