import importlib
import os
from PyQt6.QtCore import QFile, QTextStream, QStandardPaths
from PyQt6.QtGui import QIcon

APP_CONFIG = {
    "app_name": "Smart Background Remover & Compositor",
    "version": "1.0.0",
    "author": "Your Name/Organization",
    "stylesheet_path": "brian/assets/material_dark.qss",
    "icons_dir": "brian/assets/icons/",
    "default_output_subdir": "processed_images",
    "model_name": "briaai/RMBG-2.0",
    "model_image_size": (1024, 1024),
    "required_modules": [
        'PyQt6', 'PIL', 'torch', 'torchvision', 'transformers', 'numpy'
    ],
    "grid_options": ["Freeform", "1x1", "2x2", "2x3", "3x2", "3x3", "1x3", "3x1"]
}

def check_dependencies(required_modules_list):
    """Check if all required dependencies are available."""
    missing_modules = []
    for module_name in required_modules_list:
        try:
            importlib.import_module(module_name if module_name != "PIL" else "PIL.Image")
        except ImportError:
            missing_modules.append(module_name)

    if missing_modules:
        error_message = "The following required modules are missing:\n" + "\n".join(missing_modules)
        pip_install_command = "pip install " + " ".join(m.lower() for m in missing_modules)
        if 'PIL' in missing_modules: # Pillow is installed as 'pillow'
            pip_install_command = pip_install_command.replace(" pil", " pillow")

        error_message += f"\n\nPlease install them using:\n{pip_install_command}"
        return False, error_message
    return True, "All dependencies are available."

def load_stylesheet(qss_file_path):
    """Loads a QSS file and returns its content as a string."""
    qss_file = QFile(qss_file_path)
    if qss_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        stream = QTextStream(qss_file)
        stylesheet_content = stream.readAll()
        qss_file.close()
        return stylesheet_content
    else:
        print(f"Error: Could not open stylesheet file: {qss_file_path} - {qss_file.errorString()}")
        return None

def get_icon_path(icon_filename):
    """Constructs the full path to an icon file."""
    return os.path.join(APP_CONFIG["icons_dir"], icon_filename)

def get_app_icon(icon_filename="app_icon.png"): # Default app icon name
    """Returns a QIcon object for the application."""
    path = get_icon_path(icon_filename)
    if os.path.exists(path):
        return QIcon(path)
    print(f"Warning: App icon not found at {path}")
    return QIcon() # Return empty icon


def get_default_output_dir(input_dir=None):
    """
    Determines a default output directory.
    - If input_dir is provided, creates a subdir within it.
    - Otherwise, uses a 'Processed Images' folder in user's Pictures directory.
    """
    if input_dir and os.path.isdir(input_dir):
        return os.path.join(input_dir, APP_CONFIG["default_output_subdir"])
    else:
        pictures_location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        return os.path.join(pictures_location, APP_CONFIG["app_name"] + " Output")


# Example of how you might store more complex config, e.g., grid definitions
GRID_DEFINITIONS = {
    "1x1": (1,1),
    "2x2": (2,2),
    "2x3": (2,3),
    # ... and so on
}
APP_CONFIG["grid_definitions"] = GRID_DEFINITIONS
