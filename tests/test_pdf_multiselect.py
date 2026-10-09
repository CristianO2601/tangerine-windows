"""Real Qt selection events and group reordering in the image PDF editor."""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from tangerine.editors.pdf import ImagesPdfDialog


def fixtures(tmp_path):
    files = [tmp_path / f"Page {index}.png" for index in range(5)]
    for index, path in enumerate(files):
        Image.new("RGB", (64 + index, 48), "orange").save(path)
    return files


def test_ctrl_select_and_move_group_preserves_order(qapp, tmp_path):
    files = fixtures(tmp_path)
    dialog = ImagesPdfDialog(files, order="manual")
    dialog.show()
    qapp.processEvents()
    view = dialog.files
    for row in (1, 2):
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         view.visualItemRect(view.item(row)).center())
    assert len(view.selectedItems()) == 2
    dialog.move_item(1)
    assert dialog.selected_paths() == [files[0], files[3], files[1], files[2], files[4]]
    assert {view.row(item) for item in view.selectedItems()} == {2, 3}
    dialog.move_item(-1)
    assert dialog.selected_paths() == files
    dialog.close()


def test_add_remove_multiple_and_preserve_received_order(qapp, tmp_path, monkeypatch):
    files = fixtures(tmp_path)
    dialog = ImagesPdfDialog(files[:2], order="received")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_: ([str(p) for p in files[1:]], ""))
    dialog.add_images()
    assert dialog.selected_paths() == files
    for row in (0, 2, 4):
        dialog.files.item(row).setSelected(True)
    dialog.remove_images()
    assert dialog.selected_paths() == [files[1], files[3]]
    dialog.order.setCurrentIndex(dialog.order.findData("name"))
    dialog.order.setCurrentIndex(dialog.order.findData("received"))
    assert dialog.selected_paths() == [files[1], files[3]]
    dialog.files.selectAll()
    dialog.remove_images()
    dialog._accept_clicked()
    assert dialog.job_window is None and dialog.error.text()
    dialog.close()
