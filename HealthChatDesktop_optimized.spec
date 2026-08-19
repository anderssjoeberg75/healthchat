# -*- mode: python ; coding: utf-8 -*-
"""
HealthChat Desktop v4.1.0 - PyInstaller Specification
Only excludes large third-party packages that are definitely unused.
Never excludes stdlib modules - they are small and have hidden dependencies.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

datas = [
    ('logo.ico', '.'),
    ('logo.png', '.'),
]

binaries = []
extra_hidden = []

for pkg in ['numpy', 'matplotlib', 'chardet', 'charset_normalizer', 'requests', 'garth', 'garminconnect']:
    try:
        p_datas, p_binaries, p_hidden = collect_all(pkg)
        datas += p_datas
        binaries += p_binaries
        extra_hidden += p_hidden
    except Exception:
        pass

try:
    datas += collect_data_files('anthropic')
except Exception:
    pass

a = Analysis(
    ['HealthChatDesktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=extra_hidden + [
        'garmin_db',
        'fitbit_handler',
        'charts_view',
        'sqlite3',
        'garth',
        'garth.http',
        'garth.sso',
        'openai',
        'openai.types',
        'anthropic',
        'anthropic._client',
        'anthropic._streaming',
        'google.genai',
        'google.genai.types',
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'docx',
        'reportlab.pdfgen.canvas',
        'reportlab.lib.pagesizes',
        'reportlab.lib.colors',
        'PIL._tkinter_finder',
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.messagebox',
        'tkinter.commondialog',
        'tkinter.dialog',
        'tkinter.constants',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Large unused third-party packages only - never exclude stdlib
        'pandas',
        'scipy',
        'sklearn',
        'scikit-learn',
        'tensorflow',
        'torch',
        'keras',
        'statsmodels',
        'seaborn',
        'flask',
        'django',
        'fastapi',
        'aiohttp',
        'tornado',
        'bottle',
        'cherrypy',
        'sqlalchemy',
        'psycopg2',
        'pymongo',
        'redis',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'wx',
        'kivy',
        'IPython',
        'ipython',
        'jupyter',
        'notebook',
        'ipykernel',
        'Cython',
        'pyximport',
        'sphinx',
        'docutils',
        'pygments',
        'pygame',
        'pytest',
        '_pytest',
        'hypothesis',
        'nose',
        'coverage',
        'tkinter.dnd',
        'tkinter.test',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HealthChatDesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HealthChatDesktop',
)
