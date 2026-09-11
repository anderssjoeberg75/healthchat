# Kompilering efter kodändringar

När kodändringar görs i HealthChat:
1. Kör alltid enhetstester (pytest).
2. Kompilera alltid applikationen med PyInstaller:
   pyinstaller --noconfirm HealthChatDesktop_optimized.spec
3. Signera den nya binären:
   powershell -ExecutionPolicy Bypass -File .\sign_executable.ps1
4. Verifiera att dist\HealthChatDesktop\HealthChatDesktop.exe har uppdaterats och signerats (Valid).
