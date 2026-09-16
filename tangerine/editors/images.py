"""Photo editors: compress, collage, crop, redact, background, edit,
annotate and metadata.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import progress, settings, tools
from .base import ToolDialog, pil_to_qimage, run_batch
from .ui.canvas import AnnotateCanvas, CropCanvas, RedactCanvas, _draw_op


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------

class CompressDialog(ToolDialog):
    def __init__(self, paths, family: str, parent: QWidget | None = None):
        super().__init__("Compress", parent)
        self._paths = [Path(p) for p in paths]
        self._family = family
        count = len(self._paths)
        heading = QLabel(
            self._paths[0].name if count == 1 else f"{count} files"
        )
        heading.setProperty("dim", True)
        self._body.addWidget(heading)

        form = QFormLayout()
        form.setSpacing(10)
        self.strength = QComboBox()
        self.strength.addItems(["Balanced", "Strong"])
        form.addRow("Compression preset", self.strength)

        self.size = QComboBox()
        self.size.addItems(["Original dimensions", "Limit to 2560 px",
                            "Limit to 1920 px", "Limit to 1280 px"])
        self.size_row = self.size
        form.addRow("Dimensions", self.size)

        self.target_check = QCheckBox("Compress to target file size")
        self.target_kb = QSpinBox()
        self.target_kb.setRange(1, 1024 * 1024)
        self.target_kb.setValue(500)
        self.target_kb.setSuffix(" KB")
        self.target_kb.setEnabled(False)
        self.target_check.toggled.connect(self.target_kb.setEnabled)
        form.addRow(self.target_check, self.target_kb)
        self._body.addLayout(form)

        note = QLabel(
            "Balanced targets about 20% savings with less quality loss. "
            "Strong targets about 50%. The original bytes are kept whenever "
            "re-encoding would make the file larger."
        )
        note.setWordWrap(True)
        note.setProperty("dim", True)
        self._body.addWidget(note)

        if family == "image":
            self.strength.setCurrentIndex(
                1 if settings.get("defaultImageCompressionStrength") == "strong" else 0)
            sizes = ["original", "2560", "1920", "1280"]
            current = str(settings.get("defaultImageCompressionSize", "original"))
            self.size.setCurrentIndex(sizes.index(current) if current in sizes else 0)
        else:
            self.size_row.setVisible(False)
            self.target_check.setVisible(False)
            self.target_kb.setVisible(False)
            key = "defaultVideoCompressionStrength" if family == "video" else "defaultAudioCompressionStrength"
            self.strength.setCurrentIndex(1 if settings.get(key) == "strong" else 0)
        self.add_buttons("Compress")

    def save_defaults(self) -> None:
        strength = "strong" if self.strength.currentIndex() == 1 else "balanced"
        if self._family == "image":
            settings.set("defaultImageCompressionStrength", strength)
            size = ["original", "2560", "1920", "1280"][self.size.currentIndex()]
            settings.set("defaultImageCompressionSize", size)
        elif self._family == "video":
            settings.set("defaultVideoCompressionStrength", strength)
        else:
            settings.set("defaultAudioCompressionStrength", strength)
        settings.save()

    def _accept_clicked(self) -> None:
        strength = "strong" if self.strength.currentIndex() == 1 else "balanced"
        max_edge = None
        if self._family == "image" and self.size.currentIndex() > 0:
            max_edge = int(["", "2560", "1920", "1280"][self.size.currentIndex()])
        target = None
        if self._family == "image" and self.target_check.isChecked():
            target = max(1024, self.target_kb.value() * 1024)
        self.save_defaults()

        if self._family == "image":
            run_batch(self._paths, lambda p, ctx, reserved: tools.compress_image(
                p, strength, max_edge, target, ctx, reserved), "Compressing")
        elif self._family == "video":
            run_batch(self._paths, lambda p, ctx, reserved: tools.compress_video(
                p, strength, ctx, reserved), "Compressing")
        else:
            run_batch(self._paths, lambda p, ctx, reserved: tools.compress_audio(
                p, strength, ctx, reserved), "Compressing")
        self.accept()


# ---------------------------------------------------------------------------
# Collage
# ---------------------------------------------------------------------------

class CollageDialog(ToolDialog):
    def __init__(self, paths, parent: QWidget | None = None):
        super().__init__("Create Collage", parent)
        self._paths = [Path(p) for p in paths]
        self._thumb_dir = Path(tempfile.mkdtemp(prefix="tangerine_collage_"))
        self._thumbs: dict[Path, Path] = {}
        self._make_thumbs()
        self.finished.connect(self._cleanup_thumbs)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(280)
        self._preview_timer.timeout.connect(self._refresh_preview)

        top = QHBoxLayout()
        top.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(9)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Grid", "Horizontal", "Vertical", "Featured"])
        form.addRow("Layout", self.layout_combo)

        self.resolution = QComboBox()
        self.resolution.addItems(["Source size", "2000 px", "1500 px", "1080 px"])
        form.addRow("Image area", self.resolution)

        self.fit = QComboBox()
        self.fit.addItems(["Fill cell", "Contain"])
        form.addRow("Image fit", self.fit)

        self.spacing = QSpinBox()
        self.spacing.setRange(0, 96)
        form.addRow("Spacing", self.spacing)

        self.padding = QSpinBox()
        self.padding.setRange(0, 160)
        form.addRow("Padding", self.padding)

        self.radius = QSpinBox()
        self.radius.setRange(0, 64)
        form.addRow("Rounded corners", self.radius)

        self.background = QComboBox()
        self.background.addItems(["White", "Black", "Transparent"])
        form.addRow("Background", self.background)
        top.addLayout(form)

        self.preview = QLabel()
        self.preview.setFixedSize(330, 250)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setProperty("card", True)
        self.preview.setStyleSheet(
            "background: rgba(127,127,127,0.12); border-radius: 10px;"
        )
        top.addWidget(self.preview)
        self._body.addLayout(top)

        order_group = QGroupBox("Order")
        order_layout = QHBoxLayout(order_group)
        self.order_list = QListWidget()
        self.order_list.setFixedHeight(96)
        order_layout.addWidget(self.order_list, 1)
        buttons = QVBoxLayout()
        up = QPushButton("Move up")
        down = QPushButton("Move down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        order_layout.addLayout(buttons)
        self._body.addWidget(order_group)

        for path in self._paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.order_list.addItem(item)

        defaults = {
            "layout": settings.get("collageLayout", "grid"),
            "spacing": settings.get("collageSpacing", 12),
            "padding": settings.get("collagePadding", 24),
            "corner_radius": settings.get("collageCornerRadius", 12),
            "background": settings.get("collageBackground", "white"),
            "resolution": settings.get("collageResolution", "source"),
            "fit": settings.get("collageFit", "fill"),
        }
        layouts = ["grid", "horizontal", "vertical", "featured"]
        self.layout_combo.setCurrentIndex(
            layouts.index(defaults["layout"]) if defaults["layout"] in layouts else 0)
        self.spacing.setValue(int(defaults["spacing"]))
        self.padding.setValue(int(defaults["padding"]))
        self.radius.setValue(int(defaults["corner_radius"]))
        backgrounds = ["white", "black", "transparent"]
        self.background.setCurrentIndex(
            backgrounds.index(defaults["background"]) if defaults["background"] in backgrounds else 0)
        if str(defaults["resolution"]) == "source":
            self.resolution.setCurrentIndex(0)
        else:
            match = {"2000": 1, "1500": 2, "1080": 3}.get(str(defaults["resolution"]), 0)
            self.resolution.setCurrentIndex(match)
        self.fit.setCurrentIndex(0 if defaults["fit"] == "fill" else 1)

        for widget in (self.layout_combo, self.resolution, self.fit, self.background):
            widget.currentIndexChanged.connect(self._queue_preview)
        for widget in (self.spacing, self.padding, self.radius):
            widget.valueChanged.connect(self._queue_preview)
        self.order_list.model().rowsMoved.connect(self._queue_preview)

        self.add_buttons("Create Collage")
        QTimer.singleShot(80, self._refresh_preview)

    def _make_thumbs(self) -> None:
        for index, path in enumerate(self._paths):
            try:
                image = tools.load_image(path).convert("RGBA")
                image.thumbnail((480, 480))
                thumb = self._thumb_dir / f"thumb_{index:03d}.png"
                image.save(thumb, "PNG")
                self._thumbs[path] = thumb
            except Exception:
                self._thumbs[path] = path

    def _cleanup_thumbs(self) -> None:
        directory = getattr(self, "_thumb_dir", None)
        if directory is None:
            return
        self._thumb_dir = None
        shutil.rmtree(directory, ignore_errors=True)

    def _ordered_paths(self) -> list[Path]:
        ordered = []
        pool = list(self._paths)
        for index in range(self.order_list.count()):
            data = self.order_list.item(index).data(Qt.ItemDataRole.UserRole)
            if data is None:
                continue
            path = Path(data)
            if path in pool:
                ordered.append(path)
                pool.remove(path)
        ordered.extend(pool)
        return ordered

    def _thumb_paths(self) -> list[Path]:
        return [self._thumbs.get(path, path) for path in self._ordered_paths()]

    def _move(self, delta: int) -> None:
        row = self.order_list.currentRow()
        new_row = row + delta
        if row < 0 or new_row < 0 or new_row >= self.order_list.count():
            return
        item = self.order_list.takeItem(row)
        self.order_list.insertItem(new_row, item)
        self.order_list.setCurrentRow(new_row)

    def _options(self) -> dict:
        resolution = "source"
        if self.resolution.currentIndex() > 0:
            resolution = int(["", "2000", "1500", "1080"][self.resolution.currentIndex()])
        return {
            "layout": ["grid", "horizontal", "vertical", "featured"][self.layout_combo.currentIndex()],
            "spacing": self.spacing.value(),
            "padding": self.padding.value(),
            "corner_radius": self.radius.value(),
            "background": ["white", "black", "transparent"][self.background.currentIndex()],
            "resolution": resolution,
            "fit": "fill" if self.fit.currentIndex() == 0 else "contain",
        }

    def _queue_preview(self) -> None:
        self._preview_timer.start()

    def _refresh_preview(self) -> None:
        options = self._options()
        if options["resolution"] != "source":
            options["resolution"] = min(int(options["resolution"]), 480)
        try:
            out = tools.make_collage(
                self._thumb_paths(), options,
                tools.Ctx(progress=lambda v: None, status=lambda s: None),
                set(),
            )
            pixmap = QPixmap(str(out))
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(
                    self.preview.size() - QSize(12, 12),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        except Exception:
            self.preview.setText("Preview unavailable")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cleanup_thumbs()
        super().closeEvent(event)

    def __del__(self) -> None:
        try:
            self._cleanup_thumbs()
        except Exception:
            pass

    def save_defaults(self) -> None:
        options = self._options()
        settings.update({
            "collageLayout": options["layout"],
            "collageSpacing": options["spacing"],
            "collagePadding": options["padding"],
            "collageCornerRadius": options["corner_radius"],
            "collageBackground": options["background"],
            "collageResolution": options["resolution"],
            "collageFit": options["fit"],
        })
        settings.save()

    def _accept_clicked(self) -> None:
        self.save_defaults()
        options = self._options()
        ordered = self._ordered_paths()
        progress.run_job("Building collage", lambda ctx: [
            tools.make_collage(ordered, options, ctx, set())
        ])
        self.accept()


# ---------------------------------------------------------------------------
# Crop image
# ---------------------------------------------------------------------------

class CropImageDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Crop", parent)
        self._path = Path(path)
        self.canvas = CropCanvas(self._path)
        self.canvas.setFixedSize(620, 420)
        self._body.addWidget(self.canvas)

        row = QHBoxLayout()
        self.aspect = QComboBox()
        self.aspect.addItems(["Free", "1:1", "3:2", "4:3", "16:9", "9:16"])
        row.addWidget(QLabel("Aspect"))
        row.addWidget(self.aspect)
        row.addSpacing(12)
        self.w_spin = QSpinBox()
        self.w_spin.setRange(1, self.canvas.image.width)
        self.w_spin.setValue(self.canvas.image.width)
        self.h_spin = QSpinBox()
        self.h_spin.setRange(1, self.canvas.image.height)
        self.h_spin.setValue(self.canvas.image.height)
        row.addWidget(QLabel("W"))
        row.addWidget(self.w_spin)
        row.addWidget(QLabel("H"))
        row.addWidget(self.h_spin)
        row.addStretch(1)
        reset = QPushButton("Select All")
        reset.clicked.connect(self._select_all)
        row.addWidget(reset)
        self._body.addLayout(row)

        self.canvas.changed = self._rect_changed
        self.w_spin.valueChanged.connect(self._size_changed)
        self.h_spin.valueChanged.connect(self._size_changed)
        self.aspect.currentIndexChanged.connect(self._aspect_changed)
        self.add_buttons("Crop")

    def _select_all(self) -> None:
        self.canvas.rect = [0.0, 0.0, float(self.canvas.image.width), float(self.canvas.image.height)]
        self.w_spin.setValue(self.canvas.image.width)
        self.h_spin.setValue(self.canvas.image.height)
        self.canvas.update()

    def _rect_changed(self, rect) -> None:
        self.w_spin.blockSignals(True)
        self.h_spin.blockSignals(True)
        self.w_spin.setValue(max(1, int(rect[2])))
        self.h_spin.setValue(max(1, int(rect[3])))
        self.w_spin.blockSignals(False)
        self.h_spin.blockSignals(False)

    def _size_changed(self) -> None:
        x, y, _, _ = self.canvas.rect
        w = self.w_spin.value()
        h = self.h_spin.value()
        x, y, w, h = self.canvas.clamp_box(x, y, float(w), float(h))
        self.canvas.rect = [x, y, w, h]
        self.canvas.update()

    def _aspect_changed(self) -> None:
        ratios = {0: None, 1: 1.0, 2: 1.5, 3: 4 / 3, 4: 16 / 9, 5: 9 / 16}
        ratio = ratios[self.aspect.currentIndex()]
        if ratio is None:
            return
        img_w, img_h = self.canvas.image.width, self.canvas.image.height
        cx, cy = img_w / 2, img_h / 2
        w = min(img_w, img_h * ratio)
        h = w / ratio
        if h > img_h:
            h = img_h
            w = h * ratio
        self.canvas.rect = [cx - w / 2, cy - h / 2, w, h]
        self._rect_changed(self.canvas.rect)
        self.canvas.update()

    def _accept_clicked(self) -> None:
        x, y, w, h = self.canvas.rect
        box = (int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        if box[2] < 2 or box[3] < 2:
            QMessageBox.warning(self, "Crop", "Select a crop area first.")
            return
        progress.run_job(
            f"Cropping {self._path.name}",
            lambda ctx: [tools.crop_image(self._path, box, ctx, set())],
        )
        self.accept()


# ---------------------------------------------------------------------------
# Redact photo
# ---------------------------------------------------------------------------

class RedactPhotoDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Redact Photo", parent)
        self._path = Path(path)
        self.canvas = RedactCanvas(self._path)
        self.canvas.setFixedSize(620, 420)
        self._body.addWidget(self.canvas)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Solid", "Blur"])
        row.addWidget(QLabel("Effect"))
        row.addWidget(self.mode)
        self.color_button = QPushButton("Color")
        self.color_button.clicked.connect(self._pick_color)
        self._color = QColor("#000000")
        self._sync_color()
        row.addWidget(self.color_button)
        self.mode.currentIndexChanged.connect(
            lambda: self.color_button.setEnabled(self.mode.currentIndex() == 0))
        row.addStretch(1)
        detect = QPushButton("Detect Faces")
        detect.clicked.connect(self._detect_faces)
        row.addWidget(detect)
        remove = QPushButton("Remove Selected")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(remove)
        self._body.addLayout(row)

        hint = QLabel("Drag on the photo to draw a redaction box. Select a box and press Delete to remove it.")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        self._body.addWidget(hint)
        self.add_buttons("Save Redacted Copy")

    def _sync_color(self) -> None:
        self.color_button.setStyleSheet(
            f"border-left: 16px solid {self._color.name()}; padding-left: 8px;")

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Redaction Color")
        if chosen.isValid():
            self._color = chosen
            self._sync_color()
            for index in range(len(self.canvas.boxes)):
                self.canvas.boxes[index]["color"] = self._color.name()
            self.canvas.update()

    def _detect_faces(self) -> None:
        try:
            faces = tools.detect_faces(self._path)
        except Exception as error:
            QMessageBox.warning(self, "Detect Faces", str(error))
            return
        if not faces:
            QMessageBox.information(self, "Detect Faces", "No faces were detected.")
            return
        for x, y, w, h in faces:
            self.canvas.boxes.append({
                "x": float(x), "y": float(y), "w": float(w), "h": float(h),
                "mode": "blur", "color": self._color.name(),
            })
        self.canvas.update()

    def _remove_selected(self) -> None:
        if self.canvas.selected >= 0:
            self.canvas.boxes.pop(self.canvas.selected)
            self.canvas.selected = -1
            self.canvas.update()

    def _accept_clicked(self) -> None:
        if not self.canvas.boxes:
            QMessageBox.warning(self, "Redact Photo", "Draw at least one redaction box.")
            return
        mode = "solid" if self.mode.currentIndex() == 0 else "blur"
        boxes = [
            (int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"]),
             mode, self._color.name())
            for b in self.canvas.boxes
        ]
        progress.run_job(
            f"Redacting {self._path.name}",
            lambda ctx: [tools.redact_photo(self._path, boxes, ctx, set())],
        )
        self.accept()


# ---------------------------------------------------------------------------
# Add background
# ---------------------------------------------------------------------------

class BackgroundDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Add Background", parent)
        self._path = Path(path)
        self._color = QColor("#FFFFFF")
        image = tools.load_image(self._path)
        self._img_w, self._img_h = image.width, image.height

        form = QFormLayout()
        form.setSpacing(10)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self._sync_color()
        form.addRow("Background", self.color_button)
        self.margin = QSpinBox()
        self.margin.setRange(0, 512)
        self.margin.setValue(0)
        self.margin.setSuffix(" px")
        form.addRow("Margin", self.margin)
        self._body.addLayout(form)

        note = QLabel("The image is centered on a canvas of the chosen color. "
                      "Transparent areas show the background.")
        note.setProperty("dim", True)
        note.setWordWrap(True)
        self._body.addWidget(note)
        self.add_buttons("Save with Background")

    def _sync_color(self) -> None:
        self.color_button.setStyleSheet(
            f"border-left: 16px solid {self._color.name()}; padding-left: 8px;")
        self.color_button.setText(self._color.name())

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Background Color")
        if chosen.isValid():
            self._color = chosen
            self._sync_color()

    def _accept_clicked(self) -> None:
        margin = self.margin.value()
        width = self._img_w + margin * 2
        height = self._img_h + margin * 2
        progress.run_job(
            f"Adding background to {self._path.name}",
            lambda ctx: [tools.add_background(
                self._path, self._color.name(), width, height, ctx, set())],
        )
        self.accept()


# ---------------------------------------------------------------------------
# Edit photo
# ---------------------------------------------------------------------------

class EditPhotoDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Edit Photo", parent)
        self._path = Path(path)
        self._image = tools.load_image(self._path)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(140)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.preview = QLabel()
        self.preview.setFixedSize(560, 320)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background: rgba(127,127,127,0.12); border-radius: 10px;")
        self._body.addWidget(self.preview)

        form = QFormLayout()
        form.setSpacing(10)

        def slider_row(label: str, min_v: int, max_v: int, value: int):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(value)
            spin = QSpinBox()
            spin.setRange(min_v, max_v)
            spin.setValue(value)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(self._queue_preview)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(spin)
            form.addRow(label, row)
            return slider

        self.brightness = slider_row("Brightness", 40, 160, 100)
        self.contrast = slider_row("Contrast", 40, 160, 100)
        self.saturation = slider_row("Saturation", 0, 200, 100)
        self.sharpness = slider_row("Sharpness", 0, 300, 100)
        self._body.addLayout(form)

        self.add_buttons("Save Copy")
        QTimer.singleShot(60, self._refresh_preview)

    def _enhanced(self, image):
        from PIL import ImageEnhance

        result = image
        result = ImageEnhance.Brightness(result).enhance(self.brightness.value() / 100.0)
        result = ImageEnhance.Contrast(result).enhance(self.contrast.value() / 100.0)
        result = ImageEnhance.Color(result).enhance(self.saturation.value() / 100.0)
        result = ImageEnhance.Sharpness(result).enhance(self.sharpness.value() / 100.0)
        return result

    def _queue_preview(self) -> None:
        self._preview_timer.start()

    def _refresh_preview(self) -> None:
        preview = self._image.copy()
        preview.thumbnail((520, 290))
        enhanced = self._enhanced(preview)
        self.preview.setPixmap(QPixmap.fromImage(pil_to_qimage(enhanced.convert("RGBA"))))

    def _accept_clicked(self) -> None:
        path = self._path
        values = (self.brightness.value(), self.contrast.value(),
                  self.saturation.value(), self.sharpness.value())

        def work(ctx):
            from PIL import ImageEnhance

            image = tools.load_image(path)
            ctx.status(f"Editing {path.name}")
            image = ImageEnhance.Brightness(image).enhance(values[0] / 100.0)
            image = ImageEnhance.Contrast(image).enhance(values[1] / 100.0)
            image = ImageEnhance.Color(image).enhance(values[2] / 100.0)
            image = ImageEnhance.Sharpness(image).enhance(values[3] / 100.0)
            out = tools._unique(path.parent, f"{path.stem} Edited", ".png", set())
            image.convert("RGBA").save(out, "PNG")
            ctx.progress(1.0)
            return [out]

        progress.run_job(f"Editing {path.name}", work)
        self.accept()


# ---------------------------------------------------------------------------
# Annotate photo
# ---------------------------------------------------------------------------

class AnnotateDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Annotate Photo", parent)
        self._path = Path(path)
        self.canvas = AnnotateCanvas(self._path)
        self.canvas.setFixedSize(620, 420)
        self._body.addWidget(self.canvas)

        row = QHBoxLayout()
        self.tool_buttons = {}
        for key, label in (("arrow", "Arrow"), ("pen", "Draw"), ("rect", "Rect"),
                           ("ellipse", "Ellipse"), ("text", "Text"),
                           ("highlight", "Highlight"), ("callout", "Number")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self._select_tool(k))
            self.tool_buttons[key] = button
            row.addWidget(button)
        self.tool_buttons["arrow"].setChecked(True)
        row.addStretch(1)
        color_button = QPushButton("Color")
        color_button.clicked.connect(self._pick_color)
        row.addWidget(color_button)
        row.addWidget(QLabel("Size"))
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, 12)
        self.width_slider.setValue(3)
        self.width_slider.setFixedWidth(90)
        self.width_slider.valueChanged.connect(
            lambda v: setattr(self.canvas, "width", v))
        row.addWidget(self.width_slider)
        self._body.addLayout(row)

        bottom = QHBoxLayout()
        undo = QPushButton("Undo")
        undo.clicked.connect(self.canvas.undo)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.canvas.reset_ops)
        bottom.addWidget(undo)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        self._body.addLayout(bottom)
        self._color_button = color_button
        self._sync_color()
        self.add_buttons("Save Annotated Copy")

    def _select_tool(self, key: str) -> None:
        self.canvas.tool = key
        for name, button in self.tool_buttons.items():
            button.setChecked(name == key)

    def _sync_color(self) -> None:
        self._color_button.setStyleSheet(
            f"border-left: 16px solid {self.canvas.color}; padding-left: 8px;")

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.canvas.color), self, "Annotation Color")
        if chosen.isValid():
            self.canvas.color = chosen.name()
            self._sync_color()

    def _accept_clicked(self) -> None:
        if not self.canvas.ops:
            QMessageBox.warning(self, "Annotate Photo", "Add at least one annotation.")
            return
        path = self._path
        ops = list(self.canvas.ops)

        def work(ctx):
            ctx.status(f"Rendering annotations for {path.name}")
            qimage = pil_to_qimage(self.canvas.image)
            painter = QPainter(qimage)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for op in ops:
                _draw_op(painter, op, 1.0, QPointF(0.0, 0.0))
            painter.end()
            out = tools._unique(path.parent, f"{path.stem} Annotated", ".png", set())
            qimage.save(str(out), "PNG")
            ctx.progress(1.0)
            return [out]

        progress.run_job(f"Annotating {path.name}", work)
        self.accept()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class MetadataDialog(ToolDialog):
    EDITABLE = {name: tag for tag, name in tools.EXIF_TAGS.items()}

    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Metadata", parent)
        self._path = Path(path)
        self._rows = tools.read_metadata(self._path)

        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

        self.table = QTableWidget(len(self._rows), 2)
        self.table.setHorizontalHeaderLabels(["Field", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumSize(560, 360)
        for row, (name, value) in enumerate(self._rows):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(value))
        self.table.resizeColumnToContents(0)
        self._body.addWidget(self.table)

        self._status = QLabel()
        self._status.setProperty("dim", True)
        self._body.addWidget(self._status)

        box = QDialogButtonBox()
        save = box.addButton("Save Copy", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("accent", True)
        if self._can_strip():
            remove_all = box.addButton("Remove All", QDialogButtonBox.ButtonRole.DestructiveRole)
            remove_all.clicked.connect(self._remove_all)
        close = box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(self._save_copy)
        close.clicked.connect(self.reject)
        self._body.addWidget(box)
        self._refresh_status()

    def _can_strip(self) -> bool:
        return self._path.suffix.lower() not in (".pdf", ".txt")

    def _refresh_status(self) -> None:
        ext = self._path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif"):
            self._status.setText(
                f"Editing metadata writes a separate copy: {self._path.stem} Metadata{self._path.suffix}. "
                "Fields not listed here are preserved.")
        elif self._can_strip():
            self._status.setText(
                "This format keeps a read-only metadata view here. Remove All strips "
                "metadata into a separate copy.")
        else:
            self._status.setText("This format keeps a read-only metadata view here.")

    def _fields(self) -> dict[int, str]:
        fields: dict[int, str] = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if name_item is None or value_item is None:
                continue
            tag = self.EDITABLE.get(name_item.text())
            if tag is not None:
                fields[tag] = value_item.text()
        return fields

    def _is_image(self) -> bool:
        return self._path.suffix.lower() in (
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif")

    def _save_copy(self) -> None:
        if not self._is_image():
            message = "Saving edited metadata is available for images."
            if self._can_strip():
                message += " Use Remove All to strip metadata from this file."
            QMessageBox.information(self, "Metadata", message)
            return
        fields = self._fields()
        path = self._path
        progress.run_job(
            f"Writing metadata for {path.name}",
            lambda ctx: [tools.write_metadata_image(path, fields, False, ctx, set())],
        )
        self.accept()

    def _remove_all(self) -> None:
        path = self._path
        progress.run_job(
            f"Removing metadata from {path.name}",
            lambda ctx: [tools.strip_metadata(path, ctx, set())],
        )
        self.accept()
