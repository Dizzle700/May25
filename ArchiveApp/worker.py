# worker.py
import os
import zipfile
import subprocess
from PyQt6.QtCore import QObject, pyqtSignal

class ArchiveWorker(QObject):
    """
    Worker object to handle the archiving process in a separate thread.
    Communicates with the main thread via signals.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, files_to_archive, archive_path, archive_format, source_folder, password=""):
        super().__init__()
        self.files_to_archive = files_to_archive
        self.archive_path = archive_path
        self.archive_format = archive_format
        self.source_folder = source_folder
        self.password = password
        self.is_running = True

    def run(self):
        """The main work method."""
        try:
            if self.archive_format == 'zip':
                self._create_zip()
            elif self.archive_format == 'rar':
                self._create_rar()
        except Exception as e:
            self.error.emit(f"An unexpected error occurred: {e}")

    def _create_zip(self):
        """
        Creates a .zip archive.
        Note: Python's built-in zipfile module does not support password protection.
        If a password is provided, it will be ignored for ZIP archives.
        """
        if self.password:
            self.error.emit("ZIP archiving with password is not supported by the built-in Python zipfile module. Password will be ignored.")

        total_files = len(self.files_to_archive)
        with zipfile.ZipFile(self.archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, file_path in enumerate(self.files_to_archive):
                if not self.is_running:
                    self.error.emit("Process cancelled.")
                    return
                
                # Arcname is the path inside the zip file
                arcname = os.path.relpath(file_path, self.source_folder)
                
                # Handle directories and their contents
                if os.path.isdir(file_path):
                    # Add the directory itself
                    zipf.write(file_path, arcname)
                    for root, _, files in os.walk(file_path):
                        for file in files:
                            full_sub_path = os.path.join(root, file)
                            sub_arcname = os.path.relpath(full_sub_path, self.source_folder)
                            zipf.write(full_sub_path, sub_arcname)
                else:
                    zipf.write(file_path, arcname)

                progress_percent = int(((i + 1) / total_files) * 100)
                self.progress.emit(progress_percent)
        
        self.finished.emit(f"Successfully created: {os.path.basename(self.archive_path)}")

    def _create_rar(self):
        """Creates a .rar archive using the rar command-line tool."""
        # Check for rar executable
        try:
            subprocess.run(['rar'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.error.emit("RAR Error: 'rar' command not found.\nPlease install WinRAR/RAR and ensure it's in your system's PATH.")
            return

        # The rar command 'a' (add) creates an archive.
        # -r recurses into directories.
        # -p<password> sets the password.
        command = ['rar', 'a', '-r']
        if self.password:
            command.append(f'-p{self.password}')
        command.append(self.archive_path)
        command.extend([os.path.relpath(f, self.source_folder) for f in self.files_to_archive])

        # We need to run the command from the source folder for relative paths to work correctly
        process = subprocess.Popen(command, cwd=self.source_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        # Note: True progress for RAR CLI is complex. We will simulate it.
        total_files = len(self.files_to_archive)
        for i in range(total_files):
            if not self.is_running:
                process.terminate()
                self.error.emit("Process cancelled.")
                return
            self.progress.emit(int(((i + 1) / total_files) * 99)) # Simulate up to 99%
        
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            self.progress.emit(100)
            self.finished.emit(f"Successfully created: {os.path.basename(self.archive_path)}")
        else:
            self.error.emit(f"RAR Error: {stderr.strip()}")
            
    def stop(self):
        self.is_running = False
