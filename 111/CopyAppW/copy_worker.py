import os
import shutil
import stat
import time # для демонстрации os.sync()

from PyQt6.QtCore import QThread, pyqtSignal

class CopyWorker(QThread):
    progress_update = pyqtSignal(int, str)  # процент, имя текущего файла
    file_verified = pyqtSignal(str, bool) # имя файла, результат проверки (True/False)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, source_files, dest_folder, make_readonly, verify_copy):
        super().__init__()
        self.source_files = source_files
        self.dest_folder = dest_folder
        self.make_readonly = make_readonly
        self.verify_copy = verify_copy
        self.running = True

    def run(self):
        total_files = len(self.source_files)
        if total_files == 0:
            self.finished.emit("Нет файлов для копирования.")
            return

        try:
            if not os.path.exists(self.dest_folder):
                os.makedirs(self.dest_folder, exist_ok=True)
            elif not os.path.isdir(self.dest_folder):
                self.error_occurred.emit(f"Целевой путь '{self.dest_folder}' не является директорией.")
                return

            for i, source_path in enumerate(self.source_files):
                if not self.running:
                    self.finished.emit("Копирование прервано.")
                    return

                if not os.path.isfile(source_path):
                    self.error_occurred.emit(f"Источник '{source_path}' не является файлом. Пропускаем.")
                    continue

                file_name = os.path.basename(source_path)
                dest_path = os.path.join(self.dest_folder, file_name)

                self.progress_update.emit(int((i / total_files) * 100), f"Копирование: {file_name}")

                # 1. Копирование
                shutil.copy2(source_path, dest_path) # copy2 сохраняет метаданные

                # 2. Принудительная синхронизация с диском (важно для последовательной записи)
                # Открываем файл в бинарном режиме для записи, чтобы получить файловый дескриптор
                # Это гарантирует, что os.sync() сработает на конкретном файле (в некоторых ОС)
                # Однако, для простоты и кросс-платформенности, вызов os.sync() после shutil.copy2
                # обычно заставляет ОС сбросить ВСЕ буферы записи на диск.
                # Для большей уверенности на Linux можно использовать `fsync` на файловом дескрипторе.
                # На Windows `FlushFileBuffers` вызывается `shutil` при закрытии файла.
                # os.sync() - это более широкий системный вызов.
                try:
                    # Этот блок не всегда необходим, shutil.copy2 обычно сам закрывает файл
                    # и данные начинают записываться. os.sync() ниже - это более общий сброс.
                    # fd = os.open(dest_path, os.O_RDWR)
                    # os.fsync(fd)
                    # os.close(fd)
                    pass # Пока оставим shutil.copy2 и os.sync()
                except Exception as e_sync_detail:
                    print(f"Предупреждение при детальной синхронизации {dest_path}: {e_sync_detail}")
                
                os.sync() # ЗАСТАВЛЯЕМ ОС ЗАПИСАТЬ ДАННЫЕ НА ДИСК
                # Для демонстрации можно добавить небольшую паузу, чтобы увидеть эффект
                # time.sleep(0.1) # Убрать в реальном приложении

                # 3. Установка "только для чтения"
                if self.make_readonly:
                    current_mode = os.stat(dest_path).st_mode
                    # Убираем права на запись для всех, оставляем права на чтение
                    # S_IREAD - read by owner
                    # S_IRGRP - read by group
                    # S_IROTH - read by others
                    os.chmod(dest_path, current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH | \
                                       stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


                # 4. Проверка файла (по размеру)
                if self.verify_copy:
                    verified = False
                    try:
                        source_size = os.path.getsize(source_path)
                        dest_size = os.path.getsize(dest_path)
                        if source_size == dest_size:
                            verified = True
                        self.file_verified.emit(f"{file_name}", verified)
                        if not verified:
                             self.error_occurred.emit(f"Ошибка верификации (размер): {file_name} (Источник: {source_size}, Копия: {dest_size})")
                             # Можно добавить опцию прерывания при ошибке верификации
                    except OSError as e_verify:
                        self.error_occurred.emit(f"Ошибка при верификации {file_name}: {e_verify}")
                        self.file_verified.emit(f"{file_name}", False)


                self.progress_update.emit(int(((i + 1) / total_files) * 100), f"Скопирован: {file_name}")

            self.finished.emit(f"Копирование {total_files} файлов завершено.")

        except Exception as e:
            self.error_occurred.emit(f"Ошибка в процессе копирования: {str(e)}")

    def stop(self):
        self.running = False