"""
Qt6/Qt5 GUI for Surface Kernel ISO Injector.

Uses qtpy for Qt5/Qt6 compatibility. Falls back to direct imports if qtpy
is not available.
"""

import sys
import traceback
from pathlib import Path

# Qt compatibility layer - try qtpy first, then direct imports
try:
    from qtpy.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
        QProgressBar, QTextEdit, QGroupBox, QMessageBox, QSplitter,
        QFrame, QSizePolicy, QStatusBar,
    )
    from qtpy.QtCore import Qt, QThread, Signal as pyqtSignal, QSize
    from qtpy.QtGui import QFont, QTextCursor, QIcon
    QT_API = "qtpy"
except ImportError:
    try:
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
            QProgressBar, QTextEdit, QGroupBox, QMessageBox, QSplitter,
            QFrame, QSizePolicy, QStatusBar,
        )
        from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
        from PyQt6.QtGui import QFont, QTextCursor, QIcon
        QT_API = "PyQt6"
    except ImportError:
        try:
            from PyQt5.QtWidgets import (
                QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
                QProgressBar, QTextEdit, QGroupBox, QMessageBox, QSplitter,
                QFrame, QSizePolicy, QStatusBar,
            )
            from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
            from PyQt5.QtGui import QFont, QTextCursor, QIcon
            QT_API = "PyQt5"
        except ImportError:
            print(
                "ERROR: No Qt bindings found.\n"
                "Install one of: pip install PyQt6 / pip install PyQt5 / pip install qtpy\n"
                "Or on Arch: pacman -S python-pyqt6 / python-pyqt5"
            )
            sys.exit(1)

from core.injector import Injector, InjectionError
from core.surface_devices import (
    get_device,
    get_device_categories,
    list_devices,
)
from core.kernel import fetch_latest_kernel_version, KernelError


STYLE_SHEET = """
QMainWindow {
    background-color: #1e1e2e;
}
QWidget {
    color: #cdd6f4;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 28px;
}
QComboBox:hover {
    border-color: #89b4fa;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QLineEdit {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 28px;
}
QLineEdit:focus {
    border-color: #89b4fa;
}
QPushButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: bold;
    min-height: 32px;
}
QPushButton:hover {
    background-color: #b4d0fb;
}
QPushButton:pressed {
    background-color: #74a8fc;
}
QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#browseBtn, QPushButton#outputBrowseBtn {
    min-width: 80px;
    padding: 6px 12px;
}
QPushButton#injectBtn {
    background-color: #a6e3a1;
    font-size: 15px;
    min-height: 40px;
}
QPushButton#injectBtn:hover {
    background-color: #b8edb3;
}
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 6px;
    text-align: center;
    background-color: #313244;
    min-height: 24px;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 5px;
}
QTextEdit {
    background-color: #181825;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px;
    font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
    font-size: 12px;
    color: #a6adc8;
}
QStatusBar {
    background-color: #181825;
    color: #6c7086;
}
QLabel#titleLabel {
    font-size: 20px;
    font-weight: bold;
    color: #89b4fa;
}
QLabel#subtitleLabel {
    font-size: 12px;
    color: #6c7086;
}
"""


class InjectionWorker(QThread):
    """Background thread for running the injection process."""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, iso_path, device, output_path):
        super().__init__()
        self.iso_path = iso_path
        self.device = device
        self.output_path = output_path

    def run(self):
        try:
            injector = Injector(self.iso_path, self.device, self.output_path)
            injector.set_progress_callback(
                lambda pct, msg: self.progress.emit(pct, msg)
            )
            result = injector.inject()
            self.finished.emit(str(result))
        except (InjectionError, Exception) as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Surface Kernel ISO Injector")
        self.setMinimumSize(QSize(700, 600))
        self.resize(780, 680)
        self.setStyleSheet(STYLE_SHEET)

        self._worker: InjectionWorker | None = None
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(12)

        # Title
        title = QLabel("Surface Kernel ISO Injector")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Inject the linux-surface kernel into your Arch Linux installer ISO"
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # Device selection
        dev_group = QGroupBox("Surface Device")
        dev_layout = QVBoxLayout(dev_group)

        self.device_combo = QComboBox()
        self._populate_devices()
        dev_layout.addWidget(self.device_combo)

        self.device_info = QLabel("")
        self.device_info.setWordWrap(True)
        dev_layout.addWidget(self.device_info)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self._on_device_changed()

        layout.addWidget(dev_group)

        # ISO selection
        iso_group = QGroupBox("Arch Linux ISO")
        iso_layout = QHBoxLayout(iso_group)

        self.iso_input = QLineEdit()
        self.iso_input.setPlaceholderText("Select an Arch Linux .iso file...")
        iso_layout.addWidget(self.iso_input)

        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("browseBtn")
        browse_btn.clicked.connect(self._browse_iso)
        iso_layout.addWidget(browse_btn)

        layout.addWidget(iso_group)

        # Output selection
        out_group = QGroupBox("Output ISO")
        out_layout = QHBoxLayout(out_group)

        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText(
            "Output path (leave blank for auto)"
        )
        out_layout.addWidget(self.output_input)

        out_browse = QPushButton("Browse")
        out_browse.setObjectName("outputBrowseBtn")
        out_browse.clicked.connect(self._browse_output)
        out_layout.addWidget(out_browse)

        layout.addWidget(out_group)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.check_btn = QPushButton("Check Dependencies")
        self.check_btn.clicked.connect(self._check_deps)
        btn_layout.addWidget(self.check_btn)

        self.version_btn = QPushButton("Check Kernel Version")
        self.version_btn.clicked.connect(self._check_version)
        btn_layout.addWidget(self.version_btn)

        layout.addLayout(btn_layout)

        # Inject button
        self.inject_btn = QPushButton("Inject Surface Kernel")
        self.inject_btn.setObjectName("injectBtn")
        self.inject_btn.clicked.connect(self._start_injection)
        layout.addWidget(self.inject_btn)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Log output
        log_group = QGroupBox("Log Output")
        log_layout = QVBoxLayout(log_group)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(120)
        log_layout.addWidget(self.log_output)

        layout.addWidget(log_group)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"Ready | Qt backend: {QT_API}")

    def _populate_devices(self):
        categories = get_device_categories()
        for cat_name, devices in categories.items():
            self.device_combo.addItem(f"── {cat_name} ──", None)
            # Make category headers non-selectable
            idx = self.device_combo.count() - 1
            model = self.device_combo.model()
            item = model.item(idx)
            if item:
                item.setEnabled(False)

            for dev_id, dev in devices:
                self.device_combo.addItem(f"  {dev.name}", dev_id)

        # Select first selectable item
        for i in range(self.device_combo.count()):
            if self.device_combo.itemData(i) is not None:
                self.device_combo.setCurrentIndex(i)
                break

    def _on_device_changed(self):
        dev_id = self.device_combo.currentData()
        if dev_id is None:
            self.device_info.setText("")
            return
        dev = get_device(dev_id)
        if dev:
            pkgs = ", ".join([dev.kernel_variant] + dev.extra_packages)
            text = f"{dev.description}\nPackages: {pkgs}"
            if dev.notes:
                text += f"\nNote: {dev.notes}"
            self.device_info.setText(text)

    def _browse_iso(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Arch Linux ISO", "",
            "ISO Images (*.iso);;All Files (*)"
        )
        if path:
            self.iso_input.setText(path)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Output ISO", "",
            "ISO Images (*.iso);;All Files (*)"
        )
        if path:
            self.output_input.setText(path)

    def _log(self, message: str, color: str = "#cdd6f4"):
        self.log_output.append(f'<span style="color:{color}">{message}</span>')
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_output.setTextCursor(cursor)

    def _check_deps(self):
        from core.iso import ArchISO
        import shutil

        self._log("Checking dependencies...", "#89b4fa")
        tools = {
            "xorriso": "libisoburn",
            "unsquashfs": "squashfs-tools",
            "mksquashfs": "squashfs-tools",
            "curl": "curl",
            "arch-chroot": "arch-install-scripts",
        }
        all_ok = True
        for tool, pkg in tools.items():
            found = shutil.which(tool) is not None
            if found:
                self._log(f"  ✓ {tool}", "#a6e3a1")
            else:
                self._log(f"  ✗ {tool} - install with: pacman -S {pkg}", "#f38ba8")
                all_ok = False

        if all_ok:
            self._log("All dependencies satisfied!", "#a6e3a1")
        else:
            self._log("Install missing packages before injecting.", "#fab387")

    def _check_version(self):
        self._log("Querying linux-surface repository...", "#89b4fa")
        try:
            version = fetch_latest_kernel_version()
            self._log(f"Latest linux-surface kernel: {version}", "#a6e3a1")
        except KernelError as exc:
            self._log(f"Error: {exc}", "#f38ba8")

    def _start_injection(self):
        dev_id = self.device_combo.currentData()
        iso_path = self.iso_input.text().strip()
        output_path = self.output_input.text().strip() or None

        # Validate inputs
        if not dev_id:
            QMessageBox.warning(
                self, "No Device Selected",
                "Please select a Surface device from the dropdown."
            )
            return

        if not iso_path:
            QMessageBox.warning(
                self, "No ISO Selected",
                "Please select an Arch Linux ISO file."
            )
            return

        if not Path(iso_path).is_file():
            QMessageBox.warning(
                self, "Invalid ISO",
                f"File not found: {iso_path}"
            )
            return

        device = get_device(dev_id)
        if device is None:
            return

        # Confirm
        pkgs = ", ".join([device.kernel_variant] + device.extra_packages)
        reply = QMessageBox.question(
            self, "Confirm Injection",
            f"Device: {device.name}\n"
            f"ISO: {Path(iso_path).name}\n"
            f"Packages: {pkgs}\n\n"
            f"This requires root privileges and will take several minutes.\n"
            f"Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable UI
        self.inject_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.version_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)

        self._log("Starting injection...", "#89b4fa")

        self._worker = InjectionWorker(iso_path, device, output_path)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)
        self._log(f"[{percent:3d}%] {message}")
        self.status_bar.showMessage(message)

    def _on_finished(self, result_path: str):
        self.progress_bar.setValue(100)
        self.progress_label.setText("Complete!")
        self._log(f"Success! Output: {result_path}", "#a6e3a1")
        self.status_bar.showMessage("Injection complete!")
        self._re_enable_ui()
        QMessageBox.information(
            self, "Success",
            f"Surface kernel injected successfully!\n\nOutput: {result_path}"
        )

    def _on_error(self, error_msg: str):
        self.progress_bar.setValue(0)
        self.progress_label.setText("Failed")
        self._log(f"ERROR: {error_msg}", "#f38ba8")
        self.status_bar.showMessage("Injection failed")
        self._re_enable_ui()
        QMessageBox.critical(self, "Injection Failed", error_msg)

    def _re_enable_ui(self):
        self.inject_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.version_btn.setEnabled(True)
        self._worker = None


def run_gui(argv: list[str] | None = None):
    """Entry point for the GUI application."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Surface Kernel ISO Injector")
    window = MainWindow()
    window.show()
    return app.exec()
