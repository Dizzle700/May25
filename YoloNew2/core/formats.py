# core/formats.py
import os
import shutil
import json
import yaml
import cv2 # For saving augmented images if needed here
import xml.etree.ElementTree as ET
from xml.dom import minidom # For pretty printing XML
from typing import List, Dict, Tuple

from .models import AppData, ImageAnnotation, BoundingBox
from . import utils

# --- Helper ---
def _prepare_output_dirs(dataset_root: str, format_type: str):
    """Creates standard directory structures."""
    dirs_to_create = []
    if format_type == 'yolo':
        dirs_to_create = [
            os.path.join(dataset_root, "images", "train"),
            os.path.join(dataset_root, "images", "val"),
            os.path.join(dataset_root, "labels", "train"),
            os.path.join(dataset_root, "labels", "val"),
        ]
    elif format_type in ['coco', 'voc']:
        # COCO often uses train2017, val2017 structure, VOC uses JPEGImages, Annotations
        # Let's use a common structure for simplicity unless strictly needed
        dirs_to_create = [
            os.path.join(dataset_root, "images"), # Store all images together initially
            os.path.join(dataset_root, "annotations"), # Store annotation files (json/xml)
        ]
        if format_type == 'voc':
             # VOC standard names
             if os.path.exists(os.path.join(dataset_root, "images")):
                 os.rename(os.path.join(dataset_root, "images"), os.path.join(dataset_root, "JPEGImages"))
             if os.path.exists(os.path.join(dataset_root, "annotations")):
                  os.rename(os.path.join(dataset_root, "annotations"), os.path.join(dataset_root, "Annotations"))
             dirs_to_create = [os.path.join(dataset_root, "JPEGImages"),
                               os.path.join(dataset_root, "Annotations"),
                               os.path.join(dataset_root,"ImageSets", "Main")] # For train/val lists


    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)
    return { "root": dataset_root } # Return paths if needed, adapt per format


def _save_or_copy_image(img_data: ImageAnnotation, target_dir: str, filename: str):
    """Saves augmented image data or copies original file."""
    target_path = os.path.join(target_dir, filename)
    
    # Check if this is an augmented image that exists on disk
    if img_data.augmented_from is not None and os.path.exists(img_data.image_path):
        try:
            # Ensure directory exists right before copying
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(img_data.image_path, target_path)
        except Exception as e:
            print(f"Error copying augmented image {img_data.image_path} to {target_path}: {e}")
    # Check if temporary image data exists (for augmentation during the current session)
    elif hasattr(img_data, '_temp_image_data') and img_data._temp_image_data is not None:
        try:
            # Ensure directory exists right before saving
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            success = cv2.imwrite(target_path, img_data._temp_image_data)
            if not success:
                 print(f"Error: Failed to save augmented image: {target_path}")
            # Optionally release memory after saving: img_data._temp_image_data = None
        except Exception as e:
            print(f"Error saving augmented image {filename}: {e}")
    # Original image, copy it
    elif img_data.augmented_from is None and os.path.exists(img_data.image_path):
        try:
             # Ensure directory exists right before copying
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(img_data.image_path, target_path)
        except Exception as e:
            print(f"Error copying original image {img_data.image_path} to {target_path}: {e}")
    else:
         print(f"Warning: Could not find source for image: {img_data.image_path} (Original exists: {os.path.exists(img_data.image_path)}, Augmented source: {img_data.augmented_from})")


# --- YOLO Format ---
def save_yolo(app_data: AppData, dataset_root: str, train_list: List[str], val_list: List[str]):
    print("Saving in YOLO format...")
    dirs = _prepare_output_dirs(dataset_root, 'yolo')
    img_train_dir = os.path.join(dataset_root, "images", "train")
    lbl_train_dir = os.path.join(dataset_root, "labels", "train")
    img_val_dir = os.path.join(dataset_root, "images", "val")
    lbl_val_dir = os.path.join(dataset_root, "labels", "val")

    all_image_files = [] # Store relative paths for train.txt/val.txt

    # Process Training Data
    print(f"  Processing {len(train_list)} training images...")
    for img_path in train_list:
        img_data = app_data.images[img_path]
        if not img_data.boxes: continue # Should be pre-filtered, but double-check

        base_filename = os.path.basename(img_path)
        name, ext = os.path.splitext(base_filename)
        target_img_filename = base_filename # Keep original name or rename? Keep for now.
        target_lbl_filename = f"{name}.txt"
        relative_img_path = os.path.join("images", "train", target_img_filename) # Relative to dataset_root

        # Save/Copy Image
        _save_or_copy_image(img_data, img_train_dir, target_img_filename)

        # Save Label File
        label_path = os.path.join(lbl_train_dir, target_lbl_filename)
        with open(label_path, 'w') as f:
            for box in img_data.boxes:
                if box.class_id < 0: continue # Skip unassigned boxes
                cx, cy, w, h = box.bbox_norm
                f.write(f"{box.class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
        all_image_files.append((relative_img_path, 'train'))


    # Process Validation Data
    print(f"  Processing {len(val_list)} validation images...")
    for img_path in val_list:
        img_data = app_data.images[img_path]
        if not img_data.boxes: continue

        base_filename = os.path.basename(img_path)
        name, ext = os.path.splitext(base_filename)
        target_img_filename = base_filename
        target_lbl_filename = f"{name}.txt"
        relative_img_path = os.path.join("images", "val", target_img_filename)

        _save_or_copy_image(img_data, img_val_dir, target_img_filename)

        label_path = os.path.join(lbl_val_dir, target_lbl_filename)
        with open(label_path, 'w') as f:
            for box in img_data.boxes:
                 if box.class_id < 0: continue
                 cx, cy, w, h = box.bbox_norm
                 f.write(f"{box.class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
        all_image_files.append((relative_img_path, 'val'))

    # Write train.txt and val.txt
    print("  Writing train.txt and val.txt...")
    with open(os.path.join(dataset_root, "train.txt"), 'w', encoding='utf-8') as f_train, \
         open(os.path.join(dataset_root, "val.txt"), 'w', encoding='utf-8') as f_val:
        for rel_path, split in all_image_files:
             # Write path relative to the txt file location (dataset_root)
             # Usually needs to be like "./images/train/img.jpg"
             path_to_write = f"./{rel_path.replace(os.sep, '/')}"
             if split == 'train':
                 f_train.write(path_to_write + '\n')
             else:
                 f_val.write(path_to_write + '\n')


    # Write data.yaml
    print("  Writing data.yaml...")
    data_yaml = {
        'path': dataset_root, # Absolute path or relative to where training starts? Usually relative path from YAML needed. Let's use '.' assuming train script runs from where YAML is.
        'train': './train.txt', # Relative path to image list
        'val': './val.txt',     # Relative path to image list
        'nc': len(app_data.classes),
        'names': app_data.classes
    }
    with open(os.path.join(dataset_root, 'data.yaml'), 'w', encoding='utf-8') as f:
        yaml.dump(data_yaml, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    print("YOLO format saving complete.")


# --- COCO Format ---
def save_coco(app_data: AppData, dataset_root: str, train_list: List[str], val_list: List[str]):
    print("Saving in COCO format...")
    dirs = _prepare_output_dirs(dataset_root, 'coco')
    img_dir = os.path.join(dataset_root, "images") # Store all images here
    anno_dir = os.path.join(dataset_root, "annotations")

    coco_data = {
        "info": {"description": "Dataset created by YOLO Dataset Creator", "version": "1.0", "year": 2024},
        "licenses": [{"url": "", "id": 0, "name": "Placeholder License"}],
        "categories": [{"id": i, "name": name, "supercategory": "object"} for i, name in enumerate(app_data.classes)],
        "images": [],
        "annotations": []
    }

    image_id_counter = 1
    annotation_id_counter = 1
    path_to_id_map = {}

    all_paths = train_list + val_list
    print(f"  Processing {len(all_paths)} total images for COCO...")

    for img_path in all_paths:
        img_data = app_data.images[img_path]
        if not img_data.boxes: continue # Skip images without annotations for COCO annotations file

        base_filename = os.path.basename(img_path)
        # Save/Copy Image (all to the main images dir)
        _save_or_copy_image(img_data, img_dir, base_filename)

        # Add Image entry
        image_entry = {
            "id": image_id_counter,
            "width": img_data.width,
            "height": img_data.height,
            "file_name": base_filename, # Store only filename
            "license": 0,
            "date_captured": ""
        }
        coco_data["images"].append(image_entry)
        path_to_id_map[img_path] = image_id_counter

        # Add Annotation entries for this image
        for box in img_data.boxes:
             if box.class_id < 0: continue # Skip unassigned

             # Convert YOLO norm [cx,cy,w,h] to COCO pixel [xmin, ymin, w, h]
             pixels = utils.normalized_to_pixel(box.bbox_norm, img_data.width, img_data.height)
             if not pixels: continue
             x_min, y_min, x_max, y_max = pixels
             coco_w = x_max - x_min
             coco_h = y_max - y_min
             coco_bbox = [x_min, y_min, coco_w, coco_h]
             area = coco_w * coco_h

             annotation_entry = {
                 "id": annotation_id_counter,
                 "image_id": image_id_counter,
                 "category_id": box.class_id, # Assumes class_id matches category id
                 "bbox": coco_bbox,
                 "area": area,
                 "iscrowd": 0, # Standard value
                 "segmentation": [] # Not supported by this tool
             }
             coco_data["annotations"].append(annotation_entry)
             annotation_id_counter += 1

        image_id_counter += 1

    # Save the COCO JSON file
    # Usually split into train/val JSONs, but let's save one combined for simplicity
    # User can filter based on train.txt/val.txt if needed
    json_path = os.path.join(anno_dir, "instances.json") # Common name
    print(f"  Writing COCO JSON to {json_path}...")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(coco_data, f, indent=2, ensure_ascii=False)

    # Save train.txt/val.txt (optional for COCO, but useful) containing filenames
    print("  Writing train.txt and val.txt (containing filenames)...")
    with open(os.path.join(dataset_root, "train.txt"), 'w', encoding='utf-8') as f_train, \
         open(os.path.join(dataset_root, "val.txt"), 'w', encoding='utf-8') as f_val:
        for img_path in train_list:
             f_train.write(os.path.basename(img_path) + '\n')
        for img_path in val_list:
             f_val.write(os.path.basename(img_path) + '\n')


    print("COCO format saving complete.")


# --- Pascal VOC Format ---
def save_voc(app_data: AppData, dataset_root: str, train_list: List[str], val_list: List[str]):
    print("Saving in Pascal VOC format...")
    dirs = _prepare_output_dirs(dataset_root, 'voc')
    img_dir = os.path.join(dataset_root, "JPEGImages")
    anno_dir = os.path.join(dataset_root, "Annotations")
    imagesets_dir = os.path.join(dataset_root, "ImageSets", "Main")


    all_paths = train_list + val_list
    print(f"  Processing {len(all_paths)} total images for VOC...")

    image_basenames = [] # Store basenames without extension for ImageSets

    for img_path in all_paths:
        img_data = app_data.images[img_path]
        if not img_data.boxes: continue # Skip images without annotations for VOC XML

        base_filename = os.path.basename(img_path)
        name, ext = os.path.splitext(base_filename)
        image_basenames.append((name, img_path in train_list)) # Store basename and split info

        # Save/Copy Image
        _save_or_copy_image(img_data, img_dir, base_filename)

        # Create XML Annotation File
        annotation = ET.Element("annotation")

        ET.SubElement(annotation, "folder").text = "JPEGImages" # Or extract from path if needed
        ET.SubElement(annotation, "filename").text = base_filename
        ET.SubElement(annotation, "path").text = os.path.join(img_dir, base_filename) # Optional full path

        source = ET.SubElement(annotation, "source")
        ET.SubElement(source, "database").text = "Unknown"

        size = ET.SubElement(annotation, "size")
        ET.SubElement(size, "width").text = str(img_data.width)
        ET.SubElement(size, "height").text = str(img_data.height)
        ET.SubElement(size, "depth").text = "3" # Assume color images

        ET.SubElement(annotation, "segmented").text = "0"

        for box in img_data.boxes:
             if box.class_id < 0: continue # Skip unassigned

             obj = ET.SubElement(annotation, "object")
             ET.SubElement(obj, "name").text = app_data.classes[box.class_id]
             ET.SubElement(obj, "pose").text = "Unspecified"
             ET.SubElement(obj, "truncated").text = "0" # Heuristic, could try to calculate
             ET.SubElement(obj, "difficult").text = "0" # Standard value

             bndbox = ET.SubElement(obj, "bndbox")
             # Convert YOLO norm to VOC pixel [xmin, ymin, xmax, ymax]
             pixels = utils.normalized_to_pixel(box.bbox_norm, img_data.width, img_data.height)
             if not pixels: continue
             x_min, y_min, x_max, y_max = pixels

             ET.SubElement(bndbox, "xmin").text = str(x_min)
             ET.SubElement(bndbox, "ymin").text = str(y_min)
             ET.SubElement(bndbox, "xmax").text = str(x_max)
             ET.SubElement(bndbox, "ymax").text = str(y_max)

        # Save XML (pretty printed)
        xml_path = os.path.join(anno_dir, f"{name}.xml")
        try:
            # Rough string
            rough_string = ET.tostring(annotation, 'utf-8')
            # Pretty print
            reparsed = minidom.parseString(rough_string)
            pretty_xml = reparsed.toprettyxml(indent="  ")

            # Write pretty XML (ensure directories exist)
            os.makedirs(os.path.dirname(xml_path), exist_ok=True)
            with open(xml_path, 'w', encoding='utf-8') as f:
                 # Remove extra newlines added by toprettyxml
                 lines = [line for line in pretty_xml.split('\n') if line.strip()]
                 f.write('\n'.join(lines))

        except Exception as xml_e:
             print(f"Error writing XML for {name}: {xml_e}")


    # Write ImageSets files (train.txt, val.txt)
    print("  Writing ImageSets files...")
    with open(os.path.join(imagesets_dir, "train.txt"), 'w', encoding='utf-8') as f_train, \
         open(os.path.join(imagesets_dir, "val.txt"), 'w', encoding='utf-8') as f_val, \
         open(os.path.join(imagesets_dir, "trainval.txt"), 'w', encoding='utf-8') as f_trainval: # Common practice
        for basename, is_train in image_basenames:
             f_trainval.write(basename + '\n')
             if is_train:
                 f_train.write(basename + '\n')
             else:
                 f_val.write(basename + '\n')


    print("Pascal VOC format saving complete.")