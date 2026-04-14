import json
import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def aguardar_enter(mensagem):
    input(f"{mensagem}\nPressione Enter para continuar...")


def esperar_tela_carregar(driver, tempo_extra=1.5):
    candidatos = [
        "//*[contains(@class,'loading')]",
        "//*[contains(@class,'spinner')]",
        "//*[contains(@class,'overlay')]",
        "//*[contains(., 'Processando')]",
        "//*[contains(., 'Carregando')]",
    ]

    for xpath in candidatos:
        try:
            WebDriverWait(driver, 3).until_not(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception:
            pass

    time.sleep(tempo_extra)


def salvar_json(caminho, dados):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def carregar_regras(caminho="config/regras.json"):
    base_dir = Path(__file__).resolve().parent
    caminho_regras = base_dir / caminho

    with open(caminho_regras, "r", encoding="utf-8") as f:
        return json.load(f)


def nome_seguro(texto):
    texto = str(texto or "")
    proibidos = '<>:"/\\|?*'

    for c in proibidos:
        texto = texto.replace(c, "_")

    return texto.strip() or "sem_nome"