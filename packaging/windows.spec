# PyInstaller specification for Human2API Windows x64 executable
block_cipher = None
a = Analysis(["../scripts/cli_entry.py"], pathex=["../src"], binaries=[], datas=[("../src/human2api/static", "human2api/static"), ("../src/human2api/examples", "human2api/examples")], hiddenimports=["cryptography", "selenium"], hookspath=[], runtime_hooks=[], excludes=[], cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], name="h2a", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
