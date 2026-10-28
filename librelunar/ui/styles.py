"""
Stylesheets and theme definitions for LibreLunar.
Clean, minimal, monochrome retro-modern game launcher aesthetic.
"""
import sys
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
if not RESOURCES_DIR.exists():
    RESOURCES_DIR = Path(sys.executable).resolve().parent / "librelunar" / "resources"
CHECKMARK_PNG = (RESOURCES_DIR / "checkmark.png").as_posix()
DROPDOWN_ARROW_PNG = (RESOURCES_DIR / "dropdown_arrow.png").as_posix()
DROPDOWN_ARROW_HOVER_PNG = (RESOURCES_DIR / "dropdown_arrow_hover.png").as_posix()
RADIO_UNCHECKED_PNG = (RESOURCES_DIR / "radio_unchecked.png").as_posix()
RADIO_UNCHECKED_HOVER_PNG = (RESOURCES_DIR / "radio_unchecked_hover.png").as_posix()
RADIO_CHECKED_PNG = (RESOURCES_DIR / "radio_checked.png").as_posix()
RADIO_CHECKED_HOVER_PNG = (RESOURCES_DIR / "radio_checked_hover.png").as_posix()

LAUNCHER_STYLE = f"""
/* Global Window and Base Controls */
QWidget {{
    background-color: #18191e;
    color: #e2e4ea;
    font-family: "Segoe UI", sans-serif;
    font-size: 9pt;
}}

/* Group and Section Labels */
QLabel {{
    color: #9ba1b0;
    font-size: 9pt;
    font-weight: 500;
    margin-bottom: 2px;
}}

QLabel#statusText1 {{
    color: #f3f4f6;
    font-size: 9pt;
    font-weight: 600;
    qproperty-alignment: AlignCenter;
}}

QLabel#statusText2 {{
    color: #9ba1b0;
    font-size: 8pt;
    font-weight: 400;
    qproperty-alignment: AlignCenter;
}}

/* Text Inputs */
QLineEdit {{
    background-color: #24262d;
    border: 1px solid #363944;
    border-radius: 3px;
    padding: 6px 10px;
    color: #ffffff;
    font-size: 9pt;
    selection-background-color: #4a4e5d;
    selection-color: #ffffff;
}}

QLineEdit:focus {{
    border: 1px solid #5a6072;
    background-color: #282a32;
}}

QLineEdit:disabled {{
    background-color: #1f2026;
    color: #636877;
    border-color: #2a2c35;
}}

/* Dropdown ComboBoxes */
QComboBox {{
    background-color: #24262d;
    border: 1px solid #363944;
    border-radius: 3px;
    padding: 6px 10px;
    color: #ffffff;
    font-size: 9pt;
    min-height: 18px;
}}

QComboBox:hover {{
    border: 1px solid #4a4e5d;
}}

QComboBox:focus {{
    border: 1px solid #5a6072;
}}

QComboBox:disabled {{
    background-color: #1f2026;
    color: #636877;
    border-color: #2a2c35;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid #363944;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
    background-color: #202228;
}}

QComboBox::down-arrow {{
    image: url({DROPDOWN_ARROW_PNG});
    width: 10px;
    height: 10px;
}}

QComboBox::down-arrow:hover {{
    image: url({DROPDOWN_ARROW_HOVER_PNG});
}}

QComboBox QAbstractItemView {{
    background-color: #24262d;
    border: 1px solid #363944;
    selection-background-color: #383b46;
    selection-color: #ffffff;
    color: #e2e4ea;
    font-size: 9pt;
    outline: none;
    padding: 4px;
}}

/* General PushButtons (Options, Open Data Folder) */
QPushButton {{
    background-color: #2a2d36;
    border: 1px solid #3b3f4c;
    border-radius: 3px;
    padding: 6px 14px;
    color: #e2e4ea;
    font-size: 9pt;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: #343743;
    border-color: #4b5061;
}}

QPushButton:pressed {{
    background-color: #22242c;
    border-color: #313540;
}}

QPushButton:disabled {{
    background-color: #1f2026;
    color: #5d6270;
    border-color: #2a2c35;
}}

/* Primary Monochrome Launch Button */
QPushButton#launchButton {{
    background-color: #e4e4e7;
    border: 1px solid #ffffff;
    border-radius: 3px;
    padding: 6px 20px;
    color: #121214;
    font-size: 10pt;
    font-weight: 700;
    min-width: 90px;
}}

QPushButton#launchButton:hover {{
    background-color: #ffffff;
    border-color: #ffffff;
}}

QPushButton#launchButton:pressed {{
    background-color: #d4d4d8;
    border-color: #a1a1aa;
}}

QPushButton#launchButton:disabled {{
    background-color: #2a2d36;
    border-color: #333642;
    color: #636877;
}}

/* Monochrome Progress Bar */
QProgressBar {{
    background-color: #24262d;
    border: 1px solid #363944;
    border-radius: 3px;
    height: 16px;
    text-align: center;
    color: #ffffff;
    font-size: 8pt;
    font-weight: 600;
}}

QProgressBar::chunk {{
    background-color: #a1a1aa;
    border-radius: 2px;
}}

/* Checkboxes with Monochrome Tick */
QCheckBox {{
    spacing: 8px;
    color: #e2e4ea;
    font-size: 9pt;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #363944;
    border-radius: 3px;
    background-color: #24262d;
}}

QCheckBox::indicator:hover {{
    border-color: #5a6072;
}}

QCheckBox::indicator:checked {{
    background-color: #3b3f4c;
    border: 1px solid #6b7280;
    image: url({CHECKMARK_PNG});
}}

/* Radio Buttons */
QRadioButton {{
    spacing: 8px;
    color: #e2e4ea;
    font-size: 9pt;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    background: transparent;
    image: url({RADIO_UNCHECKED_PNG});
}}

QRadioButton::indicator:hover {{
    image: url({RADIO_UNCHECKED_HOVER_PNG});
}}

QRadioButton::indicator:checked {{
    image: url({RADIO_CHECKED_PNG});
}}

QRadioButton::indicator:checked:hover {{
    image: url({RADIO_CHECKED_HOVER_PNG});
}}

/* Spinboxes */
QSpinBox {{
    background-color: #24262d;
    border: 1px solid #363944;
    border-radius: 3px;
    padding: 5px 8px;
    color: #ffffff;
    font-size: 9pt;
}}

QSpinBox:focus {{
    border-color: #5a6072;
}}
"""

