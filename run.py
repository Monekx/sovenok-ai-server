import sys

if "--settings" in sys.argv:
    import settings_window
    settings_window.run_settings_window()
else:
    import main
    main.main()
