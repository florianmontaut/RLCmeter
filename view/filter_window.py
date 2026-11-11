# view/filter_window.py
"""
Fenêtre « Création de filtre » : réglages à gauche (topologie, composants, source et
charge, résultats), réponse du filtre à droite (gain d'insertion et phase).
Aucune logique ici : voir controller/filter_controller.py.
"""
import pyqtgraph as pg
from pyqtgraph.parametertree import ParameterTree
from PyQt6 import QtCore, QtGui, QtWidgets

from ressources import theme
from view.main_window import ICON, FrequencyAxis


class FilterWindow(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setWindowTitle("RLCmeter — création de filtre")
        self.setWindowIcon(QtGui.QIcon(str(ICON)))
        self.resize(1150, 700)

        self.paramTree = ParameterTree(showHeader=False)
        self.paramTree.setMinimumWidth(380)

        self.graph = pg.GraphicsLayoutWidget()
        self.plot_gain = self.graph.addPlot(
            row=0, col=0, axisItems={"bottom": FrequencyAxis("bottom")})
        self.plot_phase = self.graph.addPlot(
            row=1, col=0, axisItems={"bottom": FrequencyAxis("bottom")})
        self.plot_phase.setXLink(self.plot_gain)
        for plot in (self.plot_gain, self.plot_phase):
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLogMode(x=True, y=False)
        self.plot_gain.getAxis("bottom").setStyle(showValues=False)
        self.plot_gain.setLabel("left", "Gain d'insertion", units="dB")
        self.plot_gain.getAxis("left").enableAutoSIPrefix(False)
        self.plot_phase.setLabel("left", "Phase", units="°")
        self.plot_phase.getAxis("left").enableAutoSIPrefix(False)
        self.plot_phase.setLabel("bottom", "Fréquence")

        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)

        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graph, 1)
        layout.addWidget(self.message)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.paramTree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(splitter)

    def apply_graph_theme(self):
        self.graph.setBackground(theme.colors()["graph_bg"])
        for plot in (self.plot_gain, self.plot_phase):
            theme.style_plot(plot)
