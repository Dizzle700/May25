import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListView, QPushButton, QLineEdit,
    QProgressBar, QStatusBar, QSplitter, QTreeView,
    QApplication, QMessageBox, QCheckBox, QLabel
)
from PyQt6.QtCore import QDir, Qt, QUrl, QModelIndex
from PyQt6.QtGui import QDesktopServices, QFileSystemModel

from copy_worker import CopyWorker # Импортируем наш воркер

class FileCopierWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Мощный Файловый Копировщик")
        self.setGeometry(100, 100, 1000, 600)

        self.current_left_path = QDir.homePath()
        self.current_right_path = QDir.homePath()

        # --- Models ---
        self.left_model = QFileSystemModel()
        self.left_model.setRootPath(QDir.rootPath()) # Показываем всю ФС
        self.left_model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)


        self.right_model = QFileSystemModel()
        self.right_model.setRootPath(QDir.rootPath())
        self.right_model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)

        self.setup_ui()

        # Устанавливаем начальные пути для отображения
        self.left_view.setRootIndex(self.left_model.index(self.current_left_path))
        self.right_view.setRootIndex(self.right_model.index(self.current_right_path))
        self.left_path_edit.setText(self.current_left_path)
        self.right_path_edit.setText(self.current_right_path)
        
        self.active_view = self.left_view # По умолчанию левая панель активна

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Path Edits and Up Buttons ---
        path_layout = QHBoxLayout()
        
        left_path_panel = QVBoxLayout()
        self.left_path_edit = QLineEdit(self.current_left_path)
        self.left_path_edit.returnPressed.connect(lambda: self.navigate_path(self.left_path_edit, self.left_view, self.left_model, "left"))
        left_up_button = QPushButton("↑ (Лево)")
        left_up_button.clicked.connect(lambda: self.go_up(self.left_view, self.left_model, self.left_path_edit, "left"))
        left_path_panel.addWidget(self.left_path_edit)
        left_path_panel.addWidget(left_up_button)

        right_path_panel = QVBoxLayout()
        self.right_path_edit = QLineEdit(self.current_right_path)
        self.right_path_edit.returnPressed.connect(lambda: self.navigate_path(self.right_path_edit, self.right_view, self.right_model, "right"))
        right_up_button = QPushButton("↑ (Право)")
        right_up_button.clicked.connect(lambda: self.go_up(self.right_view, self.right_model, self.right_path_edit, "right"))
        right_path_panel.addWidget(self.right_path_edit)
        right_path_panel.addWidget(right_up_button)

        path_layout.addLayout(left_path_panel)
        path_layout.addLayout(right_path_panel)
        main_layout.addLayout(path_layout)

        # --- File Views (Panels) ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_view = QTreeView() # Используем QTreeView для лучшего отображения
        self.left_view.setModel(self.left_model)
        self.left_view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.left_view.header().setStretchLastSection(False) # Для настройки колонок
        # Скрываем лишние колонки, оставляем Имя, Размер, Тип, Дата изменения
        for i in range(1, self.left_model.columnCount()):
             if i not in [0, 1, 2, 3]: # Name, Size, Type, Date Modified
                 self.left_view.setColumnHidden(i, True)
        self.left_view.setColumnWidth(0, 300) # Имя
        self.left_view.setColumnWidth(1, 100) # Размер
        self.left_view.setColumnWidth(3, 150) # Дата
        self.left_view.doubleClicked.connect(lambda index: self.on_item_double_clicked(index, self.left_view, self.left_model, self.left_path_edit, "left"))
        self.left_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.left_view.installEventFilter(self) # Для отслеживания фокуса

        self.right_view = QTreeView()
        self.right_view.setModel(self.right_model)
        self.right_view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.right_view.header().setStretchLastSection(False)
        for i in range(1, self.right_model.columnCount()):
             if i not in [0, 1, 2, 3]:
                 self.right_view.setColumnHidden(i, True)
        self.right_view.setColumnWidth(0, 300)
        self.right_view.setColumnWidth(1, 100)
        self.right_view.setColumnWidth(3, 150)
        self.right_view.doubleClicked.connect(lambda index: self.on_item_double_clicked(index, self.right_view, self.right_model, self.right_path_edit, "right"))
        self.right_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.right_view.installEventFilter(self) # Для отслеживания фокуса

        splitter.addWidget(self.left_view)
        splitter.addWidget(self.right_view)
        splitter.setSizes([self.width() // 2, self.width() // 2]) # Равные панели

        main_layout.addWidget(splitter, 1) # Растягиваем панели

        # --- Options and Controls ---
        controls_layout = QHBoxLayout()
        self.readonly_checkbox = QCheckBox("Сделать 'только для чтения' после копирования")
        self.readonly_checkbox.setChecked(True) # По умолчанию включено
        controls_layout.addWidget(self.readonly_checkbox)

        self.verify_checkbox = QCheckBox("Проверять файлы после копирования (по размеру)")
        self.verify_checkbox.setChecked(True)
        controls_layout.addWidget(self.verify_checkbox)
        
        self.copy_button = QPushButton("F5 Копировать")
        self.copy_button.clicked.connect(self.start_copy_operation)
        controls_layout.addWidget(self.copy_button)
        
        # TODO: Add other buttons like Move (F6), Delete (F8/Del)

        main_layout.addLayout(controls_layout)

        # --- Progress and Status ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готово")

        # Worker thread
        self.copy_worker = None

    def eventFilter(self, source, event):
        if event.type() == event.Type.FocusIn:
            if source is self.left_view:
                self.active_view = self.left_view
                self.status_bar.showMessage("Активна левая панель")
            elif source is self.right_view:
                self.active_view = self.right_view
                self.status_bar.showMessage("Активна правая панель")
        return super().eventFilter(source, event)

    def navigate_path(self, path_edit, view, model, panel_side):
        path = path_edit.text()
        if QDir(path).exists():
            view.setRootIndex(model.index(path))
            if panel_side == "left":
                self.current_left_path = path
            else:
                self.current_right_path = path
        else:
            QMessageBox.warning(self, "Ошибка", f"Путь не найден: {path}")
            path_edit.setText(self.current_left_path if panel_side == "left" else self.current_right_path)


    def go_up(self, view, model, path_edit, panel_side):
        current_qdir = QDir(view.rootIndex().data(QFileSystemModel.FilePathRole))
        if current_qdir.cdUp():
            new_path = current_qdir.absolutePath()
            view.setRootIndex(model.index(new_path))
            path_edit.setText(new_path)
            if panel_side == "left":
                self.current_left_path = new_path
            else:
                self.current_right_path = new_path

    def on_item_double_clicked(self, index: QModelIndex, view, model, path_edit, panel_side):
        file_path = model.filePath(index)
        if model.isDir(index):
            view.setRootIndex(index) # Переходим в директорию
            path_edit.setText(file_path)
            if panel_side == "left":
                self.current_left_path = file_path
            else:
                self.current_right_path = file_path
        else:
            # Открываем файл системным приложением
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось открыть файл: {file_path}\n{e}")

    def get_selected_files(self, view, model) -> list:
        selected_files = []
        indexes = view.selectedIndexes()
        # QTreeView.selectedIndexes() возвращает индексы для всех колонок выбранных строк.
        # Нам нужны только уникальные пути файлов (из первой колонки).
        processed_rows = set()
        for index in indexes:
            if index.row() not in processed_rows: # Обрабатываем каждую строку только один раз
                file_path = model.filePath(index)
                if model.isFile(index): # Копируем только файлы
                    selected_files.append(file_path)
                processed_rows.add(index.row())
        return selected_files

    def start_copy_operation(self):
        if self.copy_worker and self.copy_worker.isRunning():
            reply = QMessageBox.question(self, "Копирование",
                                         "Процесс копирования уже запущен. Остановить его?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.copy_worker.stop()
            return

        if self.active_view == self.left_view:
            source_view = self.left_view
            source_model = self.left_model
            dest_folder = self.right_path_edit.text()
        else:
            source_view = self.right_view
            source_model = self.right_model
            dest_folder = self.left_path_edit.text()

        selected_files = self.get_selected_files(source_view, source_model)

        if not selected_files:
            self.status_bar.showMessage("Файлы для копирования не выбраны.")
            return
        
        if not QDir(dest_folder).exists():
            QMessageBox.warning(self, "Ошибка", f"Папка назначения не существует: {dest_folder}")
            return

        self.copy_button.setEnabled(False)
        self.progress_bar.setValue(0)
        # Важно: создаем новый экземпляр воркера для каждого нового запуска
        self.copy_worker = CopyWorker(
            selected_files,
            dest_folder,
            self.readonly_checkbox.isChecked(),
            self.verify_checkbox.isChecked()
        )
        self.copy_worker.progress_update.connect(self.on_progress_update)
        self.copy_worker.file_verified.connect(self.on_file_verified)
        self.copy_worker.finished.connect(self.on_copy_finished)
        self.copy_worker.error_occurred.connect(self.on_copy_error)
        self.copy_worker.start()
        self.status_bar.showMessage(f"Копирование {len(selected_files)} файлов в {dest_folder}...")

    def on_progress_update(self, percentage, current_file_name):
        self.progress_bar.setValue(percentage)
        self.status_bar.showMessage(current_file_name)

    def on_file_verified(self, file_name, verified_ok):
        status_text = "проверен успешно" if verified_ok else "ОШИБКА ПРОВЕРКИ"
        # Можно добавить вывод в лог или отдельное окно
        print(f"Проверка: {file_name} - {status_text}")
        self.status_bar.showMessage(f"Проверка: {file_name} - {status_text}")


    def on_copy_finished(self, message):
        self.status_bar.showMessage(message)
        self.progress_bar.setValue(100) # Или 0, если задача завершена
        self.copy_button.setEnabled(True)
        # Обновляем представление целевой панели, если она видима
        if self.active_view == self.left_view:
            # self.right_model.setRootPath("") # Хак для обновления
            # self.right_model.setRootPath(QDir.rootPath())
            self.right_view.setRootIndex(self.right_model.index(self.right_path_edit.text()))
        else:
            # self.left_model.setRootPath("") # Хак для обновления
            # self.left_model.setRootPath(QDir.rootPath())
            self.left_view.setRootIndex(self.left_model.index(self.left_path_edit.text()))

    def on_copy_error(self, error_message):
        self.status_bar.showMessage(f"Ошибка: {error_message}")
        QMessageBox.critical(self, "Ошибка копирования", error_message)
        self.progress_bar.setValue(0) # Или оставить текущее значение
        self.copy_button.setEnabled(True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F5:
            self.start_copy_operation()
        # TODO: Add F6 for Move, Del/F8 for Delete
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.copy_worker and self.copy_worker.isRunning():
            reply = QMessageBox.question(self, "Выход",
                                         "Процесс копирования еще активен. Прервать и выйти?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.copy_worker.stop()
                self.copy_worker.wait(2000) # Даем время на завершение
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()