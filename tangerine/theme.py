"""Tangerine visual theme: colors, palette helpers, shared stylesheets.

The macOS app draws a frosted "liquid glass" fan with an orange accent taken
from the app icon. On Windows the same language is expressed with rounded
corners, translucent surfaces and the orange accent.
"""

ACCENT = "#F87800"
ACCENT_BRIGHT = "#F8A850"
ACCENT_DARK = "#D96800"

FAN_PETAL_RADIUS = 148.0
FAN_CENTER_RADIUS = 46.0
FAN_HOVER_LIFT = 10.0

LIGHT = {
    "window": "#F5F3F0",
    "card": "#FFFFFF",
    "card_alt": "#F7F5F2",
    "text": "#1D1B18",
    "text_dim": "#6E6A64",
    "border": "#E2DED8",
    "field": "#FFFFFF",
    "hover": "#F1EDE8",
    "glass": (250, 248, 245, 235),
    "glass_edge": (200, 193, 184, 220),
    "petal": (255, 255, 255, 240),
    "petal_edge": (214, 208, 200, 235),
    "petal_text": "#26231F",
    "shadow": (0, 0, 0, 70),
}

DARK = {
    "window": "#1C1A18",
    "card": "#26241F",
    "card_alt": "#2E2B26",
    "text": "#F2EFEA",
    "text_dim": "#A6A099",
    "border": "#3A3733",
    "field": "#2A2723",
    "hover": "#332F2A",
    "glass": (32, 30, 27, 235),
    "glass_edge": (90, 84, 77, 220),
    "petal": (44, 41, 37, 240),
    "petal_edge": (96, 89, 81, 235),
    "petal_text": "#F2EFEA",
    "shadow": (0, 0, 0, 120),
}


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def is_dark() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            return False
        from PySide6.QtCore import Qt

        scheme = app.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        return False


def rgba(c) -> str:
    if isinstance(c, str):
        return c
    r, g, b, a = c
    return f"rgba({r}, {g}, {b}, {a})"


def stylesheet(dark: bool) -> str:
    p = palette(dark)
    return f"""
    QWidget {{
        color: {p['text']};
        font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog, #SettingsRoot {{
        background: {p['window']};
    }}
    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: 10px;
        background: {p['card']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p['text_dim']};
        padding: 7px 14px;
        margin-right: 4px;
        border-radius: 7px;
    }}
    QTabBar::tab:selected {{
        background: {p['card']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-bottom-color: {p['card']};
    }}
    QTabBar::tab:hover:!selected {{
        background: {p['hover']};
        color: {p['text']};
    }}
    QGroupBox {{
        border: 1px solid {p['border']};
        border-radius: 10px;
        background: {p['card_alt']};
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {p['text_dim']};
    }}
    QPushButton {{
        background: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 6px 14px;
    }}
    QPushButton:hover {{
        background: {p['hover']};
    }}
    QPushButton:pressed {{
        background: {p['card_alt']};
    }}
    QPushButton:disabled {{
        color: {p['text_dim']};
    }}
    QPushButton[accent="true"] {{
        background: {ACCENT};
        border: 1px solid {ACCENT_DARK};
        color: #FFFFFF;
        font-weight: 600;
    }}
    QPushButton[accent="true"]:hover {{
        background: {ACCENT_BRIGHT};
    }}
    QPushButton[accent="true"]:disabled {{
        background: {p['card_alt']};
        border-color: {p['border']};
        color: {p['text_dim']};
    }}
    QPushButton[flat="true"] {{
        background: transparent;
        border: none;
        color: {ACCENT};
        padding: 4px 6px;
    }}
    QPushButton[flat="true"]:hover {{
        color: {ACCENT_BRIGHT};
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {p['field']};
        border: 1px solid {p['border']};
        border-radius: 7px;
        padding: 5px 8px;
        selection-background-color: {ACCENT};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background: {p['card']};
        border: 1px solid {p['border']};
        selection-background-color: {ACCENT};
        selection-color: #FFFFFF;
        outline: none;
    }}
    QCheckBox, QRadioButton {{
        spacing: 7px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p['border']};
        background: {p['field']};
    }}
    QCheckBox::indicator {{
        border-radius: 4px;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT_DARK};
        image: none;
    }}
    QRadioButton::indicator:checked {{
        background: {ACCENT};
        border: 4px solid {ACCENT};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {p['border']};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: #FFFFFF;
        border: 2px solid {ACCENT};
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 9px;
    }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border']}; border-radius: 4px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['text_dim']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['border']}; border-radius: 4px; min-width: 24px;
    }}
    QMenu {{
        background: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {ACCENT};
        color: #FFFFFF;
    }}
    QMenu::separator {{
        height: 1px; background: {p['border']}; margin: 4px 8px;
    }}
    QLabel[muted="true"] {{ color: {p['text_dim']}; }}
    QToolTip {{
        background: {p['card']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        padding: 5px 8px;
    }}
    QListWidget, QTreeWidget, QTableWidget {{
        background: {p['field']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 5px 6px;
        border-radius: 6px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {ACCENT};
        color: #FFFFFF;
    }}
    QHeaderView::section {{
        background: {p['card_alt']};
        border: none;
        border-bottom: 1px solid {p['border']};
        padding: 5px 8px;
        font-weight: 600;
    }}
    QProgressBar {{
        border: 1px solid {p['border']};
        border-radius: 6px;
        background: {p['card_alt']};
        text-align: center;
        color: {p['text']};
        height: 12px;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 5px;
    }}
    """
