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


def _normalizar_navegador(navegador):
    navegador = str(navegador or "").strip().lower()

    aliases_chrome = {
        "1",
        "chrome",
        "google chrome",
        "google",
    }

    aliases_edge = {
        "2",
        "edge",
        "microsoft edge",
        "msedge",
    }

    if navegador in aliases_chrome:
        return "chrome"

    if navegador in aliases_edge:
        return "edge"

    raise ValueError(f"Navegador inválido: {navegador}")


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


def _prefs_download(download_dir):
    return {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,

        # Mantém PDF como download, evitando abrir em aba do navegador.
        "plugins.always_open_pdf_externally": True,

        # Evita popups e prompts que podem travar a automação.
        "profile.default_content_settings.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1,
        "profile.default_content_setting_values.notifications": 2,

        # Evita prompts de senha/salvamento.
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,

        # Mantém navegação/downloads mais estáveis.
        "safebrowsing.enabled": True,
    }


def _argumentos_comuns():
    return [
        "--start-maximized",
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-infobars",
        "--disable-extensions",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ]


def _aplicar_configuracoes_comuns(options, download_dir):
    options.add_experimental_option("prefs", _prefs_download(download_dir))

    # Pode reduzir alguns avisos/ruídos visuais do navegador.
    # Mesmo assim, o aviso de automação pode aparecer em alguns ambientes.
    try:
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    except Exception:
        pass

    for argumento in _argumentos_comuns():
        options.add_argument(argumento)

    return options


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

    # Mantém o navegador aberto mesmo quando o Python/Selenium termina.
    options.add_experimental_option("detach", True)

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

    # Mantém o navegador aberto mesmo quando o Python/Selenium termina.
    options.add_experimental_option("detach", True)

    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-blink-features=AutomationControlled")

    return options


def _criar_driver_chrome(options):
    try:
        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    except Exception as e:
        print(f"[NAVEGADOR][WARN] ChromeDriverManager falhou: {e}")
        print("[NAVEGADOR] Tentando iniciar Chrome com Selenium Manager...")

        service = ChromeService()
        return webdriver.Chrome(service=service, options=options)


def _criar_driver_edge(options):
    try:
        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=options)

    except Exception as e:
        print(f"[NAVEGADOR][WARN] EdgeChromiumDriverManager falhou: {e}")
        print("[NAVEGADOR] Tentando iniciar Edge com Selenium Manager...")

        service = EdgeService()
        return webdriver.Edge(service=service, options=options)


def _configurar_driver(driver, timeout_padrao):
    try:
        driver.maximize_window()
    except Exception:
        pass

    try:
        driver.set_page_load_timeout(max(int(timeout_padrao) * 3, 30))
    except Exception:
        pass

    try:
        driver.set_script_timeout(max(int(timeout_padrao) * 2, 20))
    except Exception:
        pass

    return driver


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

    navegador = _normalizar_navegador(navegador)

    if navegador == "chrome":
        options = _criar_opcoes_chrome(downloads)
        driver = _criar_driver_chrome(options)

    elif navegador == "edge":
        options = _criar_opcoes_edge(downloads)
        driver = _criar_driver_edge(options)

    else:
        raise ValueError(f"Navegador inválido: {navegador}")

    driver = _configurar_driver(driver, timeout_padrao)
    wait = WebDriverWait(driver, timeout_padrao)

    print("\n" + "=" * 80)
    print("[NAVEGADOR] Driver iniciado com sucesso")
    print(f"[NAVEGADOR] Navegador: {navegador}")
    print(f"[NAVEGADOR] Pasta base: {base}")
    print(f"[NAVEGADOR] Pasta de downloads: {downloads}")
    print("=" * 80)

    return driver, wait, str(base), str(downloads)