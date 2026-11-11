# ressources/theme.py
"""
Thème de l'interface (clair / sombre), en un seul endroit :
    - couleurs de l'application (passées à qdarktheme) et feuille de style complémentaire ;
    - couleurs du graphique pyqtgraph (fond, axes, textes) ;
    - icônes au trait (ressources/icons/*.svg, tracées en « currentColor ») teintées à la
      couleur du thème, ou à celle d'une voie dans les arbres ;
    - barre de titre des fenêtres (Windows), voir style_title_bar.
L'option « Dark mode » choisit le thème sombre ; sinon, le thème suit celui de Windows.
"""
import ctypes
import pathlib
import re
import sys

import darkdetect
import pyqtgraph as pg
import qdarktheme
from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets

ICONS = pathlib.Path(__file__).parent / "icons"

LIGHT = {
    "window":       "#F7F8FA",
    "panel":        "#FFFFFF",
    "header":       "#EEF0F3",
    "text":         "#2B2F36",
    "muted":        "#6B7280",
    "border":       "#DDE1E6",
    "accent":       "#0B6BCB",
    "highlight":    "#DCEBFA",
    "danger":       "#C62828",
    "graph_bg":     "#FFFFFF",
    "graph_axis":   "#8A919C",
    "graph_text":   "#4B5361",
}

DARK = {
    "window":       "#1C1F24",
    "panel":        "#22262C",
    "header":       "#2A2E35",
    "text":         "#E3E6EA",
    "muted":        "#9AA3AE",
    "border":       "#353A42",
    "accent":       "#5AA2F0",
    "highlight":    "#24384F",
    "danger":       "#FF6B6B",
    "graph_bg":     "#16181C",
    "graph_axis":   "#6B7380",
    "graph_text":   "#AEB6C0",
}

# fond du graphique par défaut (option « Graph Background color ») : remplacé par celui du
# thème ; une autre couleur choisie par l'utilisateur est conservée
DEFAULT_GRAPH_BACKGROUND = "#ffffff"

# opacité du fond des lignes de voies dans les arbres (couleur de la voie)
ROW_TINT_ALPHA = 45

# Feuille de style ajoutée à celle de qdarktheme : barre d'outils plate, panneaux sans
# cadre, en-têtes discrets.
QSS = """
QToolBar {{
    background: {window};
    border: none;
    border-bottom: 1px solid {border};
    padding: 3px 6px;
    spacing: 2px;
}}
QToolBar QToolButton {{
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
}}
QToolBar QToolButton:hover {{
    background: {highlight};
}}
QToolBar QToolButton:pressed {{
    border-color: {accent};
}}
QToolBar::separator {{
    background: {border};
    width: 1px;
    margin: 5px 6px;
}}
QFrame#frame, QFrame#frame_4 {{
    border: none;
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 4px;
}}
QHeaderView::section {{
    background: {header};
    color: {muted};
    border: none;
    border-right: 1px solid {border};
    padding: 3px 6px;
}}
QStatusBar {{
    background: {window};
    border-top: 1px solid {border};
    color: {muted};
}}
"""

_dark = False
_icon_cache: dict = {}
# actions à icône du thème : réteintées au changement de thème
_themed_actions: list = []


def is_dark(dark_mode: bool = False) -> bool:
    """Thème sombre : option « Dark mode », ou thème sombre de Windows."""
    return bool(dark_mode) or darkdetect.theme() == "Dark"


def colors(dark: bool | None = None) -> dict:
    """Couleurs du thème (thème courant par défaut)."""
    if dark is None:
        dark = _dark
    return DARK if dark else LIGHT


def color(name: str) -> QtGui.QColor:
    return QtGui.QColor(colors()[name])


def _qdarktheme_colors(c: dict) -> dict:
    return {
        "primary":                      c["accent"],
        "background":                   c["window"],
        "foreground":                   c["text"],
        "border":                       c["border"],
        "toolbar.background":           c["window"],
        "statusBar.background":         c["window"],
        "treeSectionHeader.background": c["header"],
        "tableSectionHeader.background": c["header"],
    }


def stylesheet(dark: bool, extra_qss: str = "") -> str:
    c = colors(dark)
    name = "dark" if dark else "light"
    return (qdarktheme.load_stylesheet(name, custom_colors=_qdarktheme_colors(c))
            + QSS.format(**c) + extra_qss)


def palette(dark: bool) -> QtGui.QPalette:
    name = "dark" if dark else "light"
    return qdarktheme.load_palette(name, custom_colors=_qdarktheme_colors(colors(dark)))


def apply(app, dark_mode: bool = False, extra_qss: str = "") -> None:
    """Applique le thème à l'application (feuille de style, palette, pyqtgraph, icônes)."""
    global _dark
    _dark = is_dark(dark_mode)
    c = colors()
    app.setPalette(palette(_dark))
    app.setStyleSheet(stylesheet(_dark, extra_qss))
    # graphiques créés ensuite (ex: fenêtre Benchmark)
    pg.setConfigOption("background", c["graph_bg"])
    pg.setConfigOption("foreground", c["graph_text"])
    _retint_actions()
    _style_title_bars(app)


# ---------------------------------------------------------------- barre de titre
# La barre de titre est dessinée par Windows (DWM), pas par la feuille de style. Plutôt
# qu'une fenêtre sans cadre (FramelessWindowHint : déplacement, redimensionnement, ancrage
# et ombre à refaire), on demande à DWM :
#   - le mode sombre de la barre (Windows 10 2004+ ; attribut 19 avant) ;
#   - sa couleur et celle du titre, à celles du thème (Windows 11 ; refusé sans effet
#     sur Windows 10, où la barre est alors grise foncée ou claire).
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
WM_NCACTIVATE = 0x0086
# fenêtres ayant une barre de titre (pas les menus, info-bulles...)
_TITLED = (QtCore.Qt.WindowType.Window, QtCore.Qt.WindowType.Dialog)


def _colorref(color: str) -> int:
    """Couleur Windows (COLORREF : 0x00BBGGRR)."""
    c = QtGui.QColor(color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def _native_windows() -> bool:
    return sys.platform == "win32" and QtGui.QGuiApplication.platformName() == "windows"


def _set_dwm_attribute(hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), ctypes.c_uint(attribute),
                    ctypes.byref(data), ctypes.sizeof(data))
    return result == 0


def style_title_bar(widget: QtWidgets.QWidget, dark: bool | None = None) -> None:
    """Barre de titre de la fenêtre widget aux couleurs du thème (Windows seulement)."""
    if not _native_windows() or not widget.isWindow() or widget.windowType() not in _TITLED:
        return
    dark = _current(dark)
    c = colors(dark)
    hwnd = int(widget.winId())
    if not _set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark)):
        _set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, int(dark))
    _set_dwm_attribute(hwnd, DWMWA_CAPTION_COLOR, _colorref(c["window"]))
    _set_dwm_attribute(hwnd, DWMWA_TEXT_COLOR, _colorref(c["text"]))
    _set_dwm_attribute(hwnd, DWMWA_BORDER_COLOR, _colorref(c["border"]))
    # fenêtre déjà affichée : Windows ne redessine la barre qu'au prochain changement de
    # fenêtre active ; on le simule (WM_NCACTIVATE inverse, puis état réel)
    if widget.isVisible():
        active = widget.isActiveWindow()
        for state in (not active, active):
            ctypes.windll.user32.SendMessageW(ctypes.c_void_p(hwnd), WM_NCACTIVATE,
                                              int(state), 0)


class _TitleBarFilter(QtCore.QObject):
    """Barre de titre de chaque fenêtre affichée (fenêtre principale, Benchmark, dialogues)."""

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Show and isinstance(obj, QtWidgets.QWidget)                 and obj.isWindow():
            style_title_bar(obj)
        return False


_title_bar_filter = None


def _style_title_bars(app) -> None:
    global _title_bar_filter
    if not _native_windows():
        return
    if _title_bar_filter is None:
        _title_bar_filter = _TitleBarFilter()
        app.installEventFilter(_title_bar_filter)
    # différé : au changement de palette, Qt rétablit lui-même la barre de titre
    # d'après le thème de Windows ; nos réglages doivent passer après
    QtCore.QTimer.singleShot(0, lambda: [style_title_bar(widget)
                                         for widget in app.topLevelWidgets()
                                         if widget.isVisible()])


# ---------------------------------------------------------------- graphique
def graph_background(option_color, dark: bool | None = None):
    """Fond du graphique : celui du thème si l'option est restée à sa valeur par défaut."""
    if pg.mkColor(option_color).name().lower() == DEFAULT_GRAPH_BACKGROUND:
        return colors(dark)["graph_bg"]
    return option_color


def style_plot(plot_item: pg.PlotItem, dark: bool | None = None) -> None:
    """Axes et textes d'un PlotItem aux couleurs du thème (la grille suit les axes)."""
    c = colors(dark)
    for name in ("left", "bottom", "right", "top"):
        axis = plot_item.getAxis(name)
        axis.setPen(pg.mkPen(c["graph_axis"]))
        axis.setTextPen(pg.mkPen(c["graph_text"]))


# ---------------------------------------------------------------- icônes
def icon(name: str, tint=None) -> QtGui.QIcon:
    """
    Icône ressources/icons/<name>.svg tracée à la couleur tint (QColor ou "#rrggbb"),
    par défaut celle des icônes du thème courant.
    """
    tint = QtGui.QColor(tint if tint is not None else colors()["muted"])
    key = (name, tint.name(QtGui.QColor.NameFormat.HexArgb))
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    svg = svg.replace("currentColor", tint.name())
    if tint.alpha() < 255:
        svg = svg.replace("<svg ", f'<svg opacity="{tint.alphaF():.3f}" ', 1)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    result = QtGui.QIcon()
    for size in (16, 24, 32, 48):
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    _icon_cache[key] = result
    return result


def set_action_icon(action: QtGui.QAction, name: str) -> None:
    """Icône du thème sur une action, réteintée au changement de thème."""
    action.setIcon(icon(name))
    _themed_actions.append((action, name))


def _retint_actions() -> None:
    alive = []
    for action, name in _themed_actions:
        try:
            action.setIcon(icon(name))
        except RuntimeError:    # action détruite (fenêtre fermée)
            continue
        alive.append((action, name))
    _themed_actions[:] = alive


# ---------------------------------------------------------------- annotations
# Textes du graphique : noirs par défaut. En thème sombre, ce noir (couleur du texte et
# couleurs écrites dans son html) est affiché à la couleur de texte du thème ; le projet
# enregistre toujours le noir, pour que l'annotation reste lisible en thème clair.
ANNOTATION_DEFAULT = "#000000"


def _current(dark):
    return _dark if dark is None else dark


def annotation_color(color, dark: bool | None = None) -> QtGui.QColor:
    """Couleur affichée d'une annotation de couleur enregistrée color."""
    color = QtGui.QColor(color)
    if _current(dark) and color == QtGui.QColor(ANNOTATION_DEFAULT):
        return QtGui.QColor(DARK["text"])
    return color


def stored_annotation_color(color, dark: bool | None = None) -> QtGui.QColor:
    """Couleur enregistrée d'une annotation affichée en color (inverse d'annotation_color)."""
    color = QtGui.QColor(color)
    if _current(dark) and color == QtGui.QColor(DARK["text"]):
        return QtGui.QColor(ANNOTATION_DEFAULT)
    return color


def _swap_html_color(html: str, old: str, new: str) -> str:
    return re.sub(rf"color:\s*{old}(?![0-9a-f])", f"color:{new}", html, flags=re.IGNORECASE)


def annotation_html(html: str, dark: bool | None = None) -> str:
    """Html affiché d'une annotation (texte noir à la couleur du thème sombre)."""
    if _current(dark):
        return _swap_html_color(html, ANNOTATION_DEFAULT, DARK["text"])
    return html


def stored_annotation_html(html: str, dark: bool | None = None) -> str:
    """Html enregistré d'une annotation affichée (inverse d'annotation_html)."""
    if _current(dark):
        return _swap_html_color(html, DARK["text"], ANNOTATION_DEFAULT)
    return html


def row_tint(pen_color) -> QtGui.QBrush:
    """Fond discret d'une ligne de voie dans les arbres : couleur de la voie, très atténuée."""
    tint = QtGui.QColor(pen_color)
    tint.setAlpha(ROW_TINT_ALPHA)
    return QtGui.QBrush(tint)
