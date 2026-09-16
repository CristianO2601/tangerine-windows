import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if "--version" in sys.argv:
    try:
        from tangerine.paths import APP_VERSION

        print(f"Tangerine {APP_VERSION}")
    except Exception:
        print("Tangerine (version unknown)")
    raise SystemExit(0)

try:
    from tangerine.main import main
except Exception as exc:
    message = f"Tangerine failed to start: {exc}\n\n{traceback.format_exc()}"
    try:
        crash = Path(os.environ.get("APPDATA", "")) / "Tangerine" / "crash.log"
        crash.parent.mkdir(parents=True, exist_ok=True)
        with crash.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Tangerine", 0x10)
    except Exception:
        pass
    raise SystemExit(1)

if __name__ == "__main__":
    sys.exit(main())
