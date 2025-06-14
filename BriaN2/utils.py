# utils.py

import os
from PyQt6.QtGui import QPixmap, QImage
from PIL import Image
from PIL.ImageQt import ImageQt

def get_default_output_dir(input_dir):
    """Returns a default output directory named 'output' inside the input directory."""
    if not input_dir:
        return ""
    output_dir = os.path.join(input_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def pil_to_qpixmap(pil_image):
    """Converts a PIL Image to a QPixmap."""
    if pil_image.mode == "RGBA":
        qimage = ImageQt(pil_image)
    else:
        qimage = ImageQt(pil_image.convert("RGBA"))
    
    return QPixmap.fromImage(qimage)