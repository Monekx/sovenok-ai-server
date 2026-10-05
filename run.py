import sys

if "--settings" in sys.argv:
    import src.settings_window
    src.settings_window.run_settings_window()
else:
    import main
    main.main()
