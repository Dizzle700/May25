import os
from PIL import Image

def resize_and_crop(image, size):
    # Resize and crop to keep aspect ratio, center crop
    w, h = image.size
    scale = size / min(w, h)
    nw, nh = int(w * scale), int(h * scale)
    image = image.resize((nw, nh), Image.LANCZOS)
    left = (nw - size) // 2
    top = (nh - size) // 2
    return image.crop((left, top, left + size, top + size))

def resize_and_crop_folder(folder, size):
    out_folder = os.path.join(folder, f"resized_{size}")
    os.makedirs(out_folder, exist_ok=True)
    for fname in os.listdir(folder):
        if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
            img_path = os.path.join(folder, fname)
            img = Image.open(img_path)
            img = resize_and_crop(img, size)
            img.save(os.path.join(out_folder, fname))