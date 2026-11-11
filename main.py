# main.py
"""RLCmeter : mesure et modélisation d'impédance avec un HP 4194A."""
import pathlib
import sys

from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from controller.main_controller import MainController      # noqa: E402
from view.main_window import MainWindow                    # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    controller = MainController(window, ROOT / "library", ROOT / "settings.json",
                                ROOT / "brouillons")
    window.show()
    code = app.exec()
    # Destruction dans l'ordre, tant que l'application Qt existe : la fenêtre (et ses
    # vues, modèles, graphes), puis le contrôleur. Laissée au ramasse-miettes de Python,
    # elle se faisait dans un ordre quelconque et pouvait planter en sortie.
    window.deleteLater()
    QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
    del controller, window
    return code


if __name__ == "__main__":
    sys.exit(main())
