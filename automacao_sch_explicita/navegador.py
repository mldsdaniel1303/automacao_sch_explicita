from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def escolher_navegador():
    print("Escolha o navegador:")
    print("1. Chrome")
    print("2. Edge")
    opcao = input("Opção [1/2]: ").strip()
    return "edge" if opcao == "2" else "chrome"


def preparar_pasta_saida():
    base = Path.cwd() / "automacao_sch_output"
    base.mkdir(parents=True, exist_ok=True)

    pasta_download = base / "browser_downloads"
    pasta_download.mkdir(parents=True, exist_ok=True)

    return base, pasta_download


def criar_driver():
    navegador = escolher_navegador()
    pasta_saida, pasta_download = preparar_pasta_saida()

    if navegador == "chrome":
        options = webdriver.ChromeOptions()
        prefs = {
            "download.default_directory": str(pasta_download),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)
        driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()),
            options=options,
        )
    else:
        options = webdriver.EdgeOptions()
        prefs = {
            "download.default_directory": str(pasta_download),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)
        driver = webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=options,
        )

    driver.maximize_window()
    wait = WebDriverWait(driver, 20)
    return driver, wait, pasta_saida, pasta_download
