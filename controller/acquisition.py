# controller/acquisition.py
"""Mesure dans un fil d'exécution à part : un balayage peut durer plusieurs minutes."""
import threading

from PyQt6 import QtCore

from instrument.hp4194a import Cancelled, InstrumentError, SweepSettings, open_instrument


class AcquisitionWorker(QtCore.QThread):

    progress = QtCore.pyqtSignal(float)             # avancement 0..1
    done = QtCore.pyqtSignal(object, object, str)   # f, z, identification de l'appareil
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, link: str, address: int, settings: SweepSettings, parent=None):
        super().__init__(parent)
        self.link, self.address, self.settings = link, address, settings
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self):
        try:
            with open_instrument(self.link, self.address) as instrument:
                identity = instrument.identify()
                f, z = instrument.measure(self.settings, progress=self.progress.emit,
                                          cancel=self._cancel.is_set)
        except Cancelled:
            self.cancelled.emit()
        except InstrumentError as error:
            self.failed.emit(str(error))
        except Exception as error:      # erreur imprévue : affichée, pas avalée
            self.failed.emit(f"{type(error).__name__} : {error}")
        else:
            self.done.emit(f, z, identity)
