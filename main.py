# main.py
"""RLCmeter : mesure et modélisation d'impédance avec un HP 4194A."""
import pathlib
import sys

from PyQt6.QtWidgets import QApplication

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from controller.main_controller import MainController      # noqa: E402
from view.main_window import MainWindow                    # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    controller = MainController(window, ROOT / "library", ROOT / "settings.json")
    window.controller = controller          # garde le contrôleur en vie avec la fenêtre
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
