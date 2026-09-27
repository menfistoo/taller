"""Freeze main.py into a single executable: python build.py"""


def build() -> None:
    import PyInstaller.__main__    # here, so importing this module needs nothing

    PyInstaller.__main__.run(
        ["main.py", "--onefile", "--name", "%%name%%", "--clean", "--noconfirm"]
    )


if __name__ == "__main__":
    build()
