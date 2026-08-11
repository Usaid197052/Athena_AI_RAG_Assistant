# Athena Packaging

## Layout (onedir)

```text
dist/Athena/
├── Athena.exe
├── .env / .env.example
├── config/
│   └── permissions.yaml
├── data/
├── logs/
└── ... bundled libs ...
```

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Requires the project `.venv` and installs PyInstaller if needed.

## Run

```powershell
dist\Athena\Athena.exe              # tray
dist\Athena\Athena.exe --voice      # voice loop
dist\Athena\Athena.exe --dashboard  # Owl's Vigil HUD
dist\Athena\Athena.exe --health     # health check
```

## Windows startup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1
```

Prefers `dist\Athena\Athena.exe` when present; otherwise falls back to `app.py` via `.venv`.

## Notes

- Frozen builds resolve writable `PROJECT_ROOT` to the folder containing `Athena.exe`.
- The build copies `.env` from the project when present (local secrets stay out of git).
- Also copies `INSTRUCTIONS.txt`, `skills/`, and the application registry when available.
- Voice/STT/TTS stacks are large; ensure those packages are installed in `.venv` before building if you need them inside the exe.
- Do not commit `build/` or `dist/`.
