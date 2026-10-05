import sys
import multiprocessing
import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # ОБЯЗАТЕЛЬНО для PyInstaller

    if "--settings" in sys.argv:
        from src.settings_window import run_settings_window
        run_settings_window()
    else:
        main.main()
