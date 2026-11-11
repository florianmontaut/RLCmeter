# view/main_window.py
"""
Fenêtre principale : arborescence de la librairie à gauche, deux graphes en fréquence au
centre, paramètres (acquisition, élément sélectionné) à droite. Aucune logique ici : le
MainController s'y connecte.
"""
import pathlib

import pyqtgraph as pg
from pyqtgraph.parametertree import ParameterTree
from PyQt6 import QtCore, QtGui, QtWidgets

from ressources import theme

ICON = pathlib.Path(__file__).parent.parent / "ressources" / "icons" / "icon.ico"


class FrequencyAxis(pg.AxisItem):
    """Axe des fréquences en échelle log, gradué en clair : 100 Hz, 1 kHz, 1 MHz..."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        if not self.logMode:
            return super().tickStrings(values, scale, spacing)
        return [pg.siFormat(10.0 ** v, precision=3, suffix="Hz") for v in values]


class MainWindow(QtWidgets.QMainWindow):

    # fermeture de la fenêtre (arrêt d'une mesure en cours, enregistrement des réglages)
    closing = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RLCmeter — HP 4194A")
        self.setWindowIcon(QtGui.QIcon(str(ICON)))
        self.resize(1640, 880)
        self._init_actions()
        self._init_menus()
        self._init_toolbar()
        self._init_central()
        self._init_status_bar()

    # ------------------------------------------------------------------ actions
    def _init_actions(self):
        def action(text, icon_name, tip, shortcut=None, checkable=False):
            act = QtGui.QAction(text, self)
            theme.set_action_icon(act, icon_name)
            act.setToolTip(tip)
            act.setCheckable(checkable)
            if shortcut:
                act.setShortcut(QtGui.QKeySequence(shortcut))
                act.setToolTip(f"{tip} ({shortcut})")
            return act

        self.actionTestLink = action("Tester la liaison", "link",
                                     "Tester la liaison avec l'analyseur")
        self.actionMeasure = action("Mesurer", "play", "Lancer un balayage", "F5")
        self.actionFit = action("Ajuster un modèle", "model",
                                "Ajuster un modèle sur la capture sélectionnée", "Ctrl+M")
        self.actionExportSubckt = action("Exporter .subckt", "export",
                                         "Exporter le modèle sélectionné pour LTspice")
        self.actionExportCsv = action("Exporter .csv", "table",
                                      "Exporter la capture sélectionnée en .csv")
        self.actionDelete = action("Supprimer", "trash",
                                   "Supprimer la capture ou le modèle sélectionné", "Del")
        self.actionDark = action("Thème sombre", "moon", "Thème sombre", checkable=True)
        # barre de menus
        self.actionOpen = action("Ouvrir...", "open", "Ouvrir une capture (.json)", "Ctrl+O")
        self.actionSaveAs = action("Sauvegarder sous...", "save",
                                   "Copier la capture sélectionnée dans un fichier", "Ctrl+S")
        self.actionQuit = action("Quitter", "stop", "Quitter RLCmeter", "Ctrl+Q")
        self.actionOptions = action("Options...", "settings", "Options de RLCmeter")
        self.actionFilter = action("Création de filtre...", "filter",
                                   "Combiner des composants en filtre et estimer sa réponse")
        self.actionTutorial = action("Tutoriel", "file", "Tutoriel", "F1")
        self.actionAbout = QtGui.QAction("À propos", self)
        # librairie
        self.actionAddToLibrary = action(
            "Ajouter à la librairie", "import",
            "Ranger la mesure sélectionnée dans la librairie, avec sa fiche", "Ctrl+L")
        self.actionEditComponent = action("Modifier la fiche...", "file",
                                          "Modifier la fiche du composant sélectionné")
        self.actionShowDrafts = QtGui.QAction("Brouillons des sessions précédentes", self)
        self.actionShowDrafts.setCheckable(True)
        self.actionShowDrafts.setToolTip(
            "Afficher aussi les mesures des sessions précédentes non ajoutées à la librairie")

    def _init_menus(self):
        bar = self.menuBar()
        self.menuFile = bar.addMenu("Fichier")
        self.menuFile.addActions([self.actionOpen, self.actionSaveAs])
        self.menuFile.addSeparator()
        self.menuFile.addActions([self.actionAddToLibrary, self.actionEditComponent,
                                  self.actionShowDrafts])
        self.menuFile.addSeparator()
        self.menuFile.addActions([self.actionExportSubckt, self.actionExportCsv])
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionQuit)
        self.menuTools = bar.addMenu("Utilitaires")
        self.menuTools.addActions([self.actionOptions, self.actionFilter])
        self.menuHelp = bar.addMenu("Aide")
        self.menuHelp.addActions([self.actionTutorial, self.actionAbout])

    def _init_toolbar(self):
        self.toolbar = QtWidgets.QToolBar("Barre d'outils", self)
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QtCore.QSize(20, 20))
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.toolbar.addActions([self.actionTestLink, self.actionMeasure])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.actionFit, self.actionAddToLibrary])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.actionExportSubckt, self.actionExportCsv])
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.actionDelete)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QtWidgets.QLabel(" Affichage : "))
        self.displayCombo = QtWidgets.QComboBox()
        self.toolbar.addWidget(self.displayCombo)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                             QtWidgets.QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addAction(self.actionDark)

    # ------------------------------------------------------------------ zone centrale
    def _init_central(self):
        edit = (QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked)

        # session : mesures faites depuis l'ouverture (brouillons), et leurs modèles
        self.tree = QtWidgets.QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(edit)

        # librairie : composants caractérisés, triables et filtrables ; mesures et
        # modèles en lignes enfants
        self.searchEdit = QtWidgets.QLineEdit()
        self.searchEdit.setPlaceholderText("Rechercher (nom, fabricant, code Fay, valeur...)")
        self.searchEdit.setClearButtonEnabled(True)
        self.kindFilter = QtWidgets.QComboBox()
        self.technologyFilter = QtWidgets.QComboBox()
        self.manufacturerFilter = QtWidgets.QComboBox()
        filters = QtWidgets.QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        for combo in (self.kindFilter, self.technologyFilter, self.manufacturerFilter):
            combo.setSizeAdjustPolicy(
                QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            filters.addWidget(combo, 1)
        self.libraryTree = QtWidgets.QTreeView()
        self.libraryTree.setSortingEnabled(True)
        self.libraryTree.setAlternatingRowColors(True)
        self.libraryTree.setEditTriggers(edit)
        self.libraryTree.setUniformRowHeights(True)
        self.libraryCount = QtWidgets.QLabel()

        def panel(title, *content):
            box = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(box)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            label = QtWidgets.QLabel(f"<b>{title}</b>")
            layout.addWidget(label)
            for item in content:
                if isinstance(item, QtWidgets.QLayout):
                    layout.addLayout(item)
                else:
                    layout.addWidget(item)
            return box

        self.leftSplitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.leftSplitter.addWidget(panel("Session", self.tree))
        self.leftSplitter.addWidget(panel("Librairie", self.searchEdit, filters,
                                          self.libraryTree, self.libraryCount))
        self.leftSplitter.setStretchFactor(0, 1)
        self.leftSplitter.setStretchFactor(1, 2)
        self.leftSplitter.setMinimumWidth(380)

        # graphes : même axe des fréquences (log), une grandeur chacun
        self.graph = pg.GraphicsLayoutWidget()
        self.plot_top = self.graph.addPlot(
            row=0, col=0, axisItems={"bottom": FrequencyAxis("bottom")})
        self.plot_bottom = self.graph.addPlot(
            row=1, col=0, axisItems={"bottom": FrequencyAxis("bottom")})
        self.plot_bottom.setXLink(self.plot_top)
        for plot in (self.plot_top, self.plot_bottom):
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLogMode(x=True, y=False)
        self.plot_top.getAxis("bottom").setStyle(showValues=False)
        self.plot_bottom.setLabel("bottom", "Fréquence")
        self.legend = self.plot_top.addLegend(offset=(-10, 10))

        # paramètres : acquisition en haut, élément sélectionné en bas
        self.acquisitionTree = ParameterTree(showHeader=False)
        self.selectionTree = ParameterTree(showHeader=False)
        self.paramSplitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.paramSplitter.addWidget(self.acquisitionTree)
        self.paramSplitter.addWidget(self.selectionTree)
        self.paramSplitter.setMinimumWidth(330)
        self.paramSplitter.setSizes([330, 430])

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.leftSplitter)
        self.splitter.addWidget(self.graph)
        self.splitter.addWidget(self.paramSplitter)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([600, 680, 340])
        self.splitter.setCollapsible(1, False)
        self.setCentralWidget(self.splitter)

    def _init_status_bar(self):
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

    def apply_graph_theme(self):
        """Fond et axes des graphes aux couleurs du thème courant."""
        self.graph.setBackground(theme.colors()["graph_bg"])
        for plot in (self.plot_top, self.plot_bottom):
            theme.style_plot(plot)
        self.legend.setLabelTextColor(theme.colors()["graph_text"])

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
