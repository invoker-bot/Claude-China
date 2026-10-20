import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from claude_china.desktop.entry import main

    raise SystemExit(main())
