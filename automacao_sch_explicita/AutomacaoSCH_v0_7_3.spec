# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

APP = Path(SPECPATH).resolve()
datas = [(str(APP / 'config' / nome), 'config') for nome in ('regras.json', 'regras_produtos.json')]
binaries = []
hiddenimports = ['extracao_cct', 'pdf_parser', 'mvp_simplificada_re', 'controles_acompanhar',
                 'caracteristicas_secundarias', 'verificacao_pacote', 'versao',
                 'pymupdf', 'fitz', 'pymupdf._mupdf', 'pymupdf._extra']
for pacote in ('selenium', 'webdriver_manager', 'pdfplumber', 'pdfminer', 'pymupdf', 'fitz'):
    dados, binarios, modulos = collect_all(pacote)
    datas += dados
    binaries += binarios
    hiddenimports += modulos
for distribuicao in ('selenium', 'webdriver-manager', 'pdfplumber', 'pdfminer.six', 'PyMuPDF'):
    datas += copy_metadata(distribuicao)

a = Analysis(
    [str(APP / 'main.py')], pathex=[str(APP)], binaries=binaries, datas=datas,
    hiddenimports=sorted(set(hiddenimports)), hookspath=[], hooksconfig={}, runtime_hooks=[],
    # APIs de diagnóstico usadas como biblioteca permanecem resolvidas.
    # Os dois entrypoints restritos de escrita/validação não são distribuídos.
    excludes=['teste_controlado_acompanhar', 'validacao_ajax_supervisionada'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='AutomacaoSCH_v0_7_3',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
    version=str(APP / 'versao_windows_v0_7_3.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name='AutomacaoSCH_v0_7_3')
