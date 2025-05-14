"""
DataHandler module - Manages application data (images, annotations, classes) (PyQt6)
"""

import os
import shutil
import random
import cv2
import yaml
import json
import numpy as np
from typing import List, Dict, Tuple, Optional, Callable
from PyQt6.QtCore import QRect
from pathlib import Path

# Use local imports due to flat structure
from utils import ensure_dir, xyxy_to_cxcywh_normalized, cxcywh_normalized_to_xyxy, clamp

class DataHandler:
    """
    Handles all data management for the YOLO Dataset Creator application.
    Annotations are stored internally in YOLO format (normalized cx, cy, w, h).
    """
    def __init__(self):
        self.image_paths: List[str] = []
        self.model_path: Optional[str] = None
        self.class_names: List[str] = []
        # {image_path: [{'class_id': int, 'bbox': [cx, cy, w, h], 'confidence': float, 'model_class_id': int}, ...]}
        self.annotations: Dict[str, List[dict]] = {}
        # {original_path: [(augmented_image_np, augmented_annotations_list), ...]}
        self.augmented_images: Dict[str, List[Tuple[np.ndarray, List[dict]]]] = {}
        self._image_dims_cache: Dict[str, Tuple[int, int]] = {} # Cache image dimensions (w, h)
        self._dirty: bool = False # Track unsaved changes

    # --- Dirty State Management ---
    def set_dirty(self, dirty: bool = True):
        self._dirty = dirty

    def is_dirty(self) -> bool:
        return self._dirty

    # --- Helper to get relative path ---
    def _get_relative_path(self, target_path: Optional[str], base_dir: Path) -> Optional[str]:
        if target_path is None:
            return None
        try:
            # Try to make path relative
            relative_path = Path(os.path.relpath(target_path, base_dir))
            return str(relative_path)
        except ValueError:
            # If paths are on different drives (Windows), keep absolute path
            return target_path

    # --- Helper to get absolute path ---
    def _get_absolute_path(self, relative_or_absolute_path: Optional[str], base_dir: Path) -> Optional[str]:
        if relative_or_absolute_path is None:
            return None
        path_obj = Path(relative_or_absolute_path)
        if path_obj.is_absolute():
            return str(path_obj)
        else:
            # Resolve relative path based on the project file's directory
            absolute_path = (base_dir / path_obj).resolve()
            return str(absolute_path)


    # --- Project Save/Load ---
    def save_project(self, file_path: str) -> bool:
        """Save the current project state to a JSON file."""
        project_file = Path(file_path)
        base_dir = project_file.parent

        # Prepare data for saving (using relative paths where possible)
        project_data = {
            "version": "0.1.0", # Project file format version
            "model_path": self._get_relative_path(self.model_path, base_dir),
            "class_names": self.class_names,
            "image_data": {}
        }

        for img_path_abs in self.image_paths:
             img_path_rel = self._get_relative_path(img_path_abs, base_dir)
             if img_path_rel: # Only save if relative path could be determined
                 project_data["image_data"][img_path_rel] = {
                      "annotations": self.annotations.get(img_path_abs, [])
                      # Note: Augmented data is not saved in the project file, it's regenerated
                 }

        try:
            with open(project_file, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=4)
            self.set_dirty(False) # Mark as saved
            print(f"Project saved successfully to {file_path}")
            return True
        except IOError as e:
            print(f"Error saving project file {file_path}: {e}")
            return False
        except TypeError as e:
            print(f"Error serializing project data to JSON: {e}")
            return False

    def load_project(self, file_path: str) -> bool:
        """Load project state from a JSON file."""
        project_file = Path(file_path)
        if not project_file.is_file():
            print(f"Error: Project file not found: {file_path}")
            return False

        base_dir = project_file.parent

        try:
            with open(project_file, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
        except IOError as e:
            print(f"Error reading project file {file_path}: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"Error parsing project file {file_path}: {e}")
            return False

        # --- Clear existing data ---
        self.image_paths = []
        self.model_path = None
        self.class_names = []
        self.annotations = {}
        self.augmented_images = {}
        self._image_dims_cache = {}
        self._dirty = False

        # --- Load data from file ---
        # Basic version check (optional but recommended)
        file_version = project_data.get("version", "0.0.0")
        # if file_version != "0.1.0":
        #     print(f"Warning: Loading project file version {file_version}, expected 0.1.0. Compatibility issues may arise.")

        self.class_names = project_data.get("class_names", [])
        relative_model_path = project_data.get("model_path")
        self.model_path = self._get_absolute_path(relative_model_path, base_dir)

        image_data = project_data.get("image_data", {})
        loaded_image_paths = []
        for img_path_rel, data in image_data.items():
            img_path_abs = self._get_absolute_path(img_path_rel, base_dir)
            if img_path_abs and os.path.isfile(img_path_abs): # Check if file still exists
                 if self._get_image_dims(img_path_abs) != (0, 0): # Check if readable
                    loaded_image_paths.append(img_path_abs)
                    self.annotations[img_path_abs] = data.get("annotations", [])
                 else:
                      print(f"Warning: Could not read dimensions for image {img_path_abs} referenced in project. Skipping.")
            else:
                 print(f"Warning: Image file not found: {img_path_abs} (relative: {img_path_rel}). Removing from project.")

        self.image_paths = loaded_image_paths
        self.set_dirty(False) # Mark as clean after load
        print(f"Project loaded successfully from {file_path}")
        return True

    def _get_image_dims(self, image_path: str) -> Tuple[int, int]:
        """Get image dimensions (width, height), using cache or loading."""
        if image_path in self._image_dims_cache:
            return self._image_dims_cache[image_path]
        try:
            img = cv2.imread(image_path)
            if img is not None:
                h, w = img.shape[:2]
                self._image_dims_cache[image_path] = (w, h)
                return w, h
        except Exception as e:
            print(f"Error reading image dimensions for {image_path}: {e}")
        return 0, 0 # Indicate failure

    def add_images(self, file_paths: List[str]) -> int:
        """Add valid image files to the project."""
        added_count = 0
        current_paths = set(self.image_paths)
        changed = False # Track if data actually changed
        for path in file_paths:
            if path not in current_paths and os.path.isfile(path):
                # Basic check if it's an image (can be improved)
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')):
                    # Pre-cache dimensions
                    if self._get_image_dims(path) != (0, 0):
                        self.image_paths.append(path)
                        self.annotations[path] = [] # Initialize empty annotations
                        added_count += 1
                        changed = True
                    else:
                         print(f"Warning: Could not read dimensions for {path}. Skipping.")
        if changed: self.set_dirty()
        return added_count

    def remove_image(self, image_path: str) -> bool:
        """Remove an image and its data."""
        if image_path in self.image_paths:
            self.image_paths.remove(image_path)
            self.annotations.pop(image_path, None)
            self.augmented_images.pop(image_path, None)
            self._image_dims_cache.pop(image_path, None)
            self.set_dirty()
            return True
        return False

    def set_model_path(self, model_path: Optional[str]) -> bool:
        """Set the path to the YOLO model."""
        new_path = None
        if model_path and os.path.isfile(model_path):
            new_path = model_path
        elif model_path is None:
             new_path = None # Allow clearing

        if new_path != self.model_path:
            self.model_path = new_path
            self.set_dirty()
            return True
        # If path is invalid but was provided, return False
        if model_path and new_path is None:
             return False
        # If path is the same or clearing an already None path, return True (no change needed)
        return True

    def add_class(self, class_name: str) -> bool:
        """Add a new class name if it doesn't exist."""
        if class_name and class_name not in self.class_names:
            self.class_names.append(class_name)
            self.set_dirty()
            return True
        return False

    def remove_class(self, class_name: str) -> bool:
        """Remove a class and update annotations."""
        if class_name in self.class_names:
            try:
                class_id_to_remove = self.class_names.index(class_name)
                self.class_names.pop(class_id_to_remove) # Remove name from list

                # Update annotations: set removed class_id to -1, shift subsequent ids down
                for img_path in self.annotations:
                    updated_anns = []
                    for ann in self.annotations[img_path]:
                        current_id = ann['class_id']
                        if current_id == class_id_to_remove:
                            ann['class_id'] = -1 # Mark as unassigned
                            updated_anns.append(ann)
                        elif current_id > class_id_to_remove:
                            ann['class_id'] -= 1 # Decrement higher IDs
                            updated_anns.append(ann)
                        else:
                            updated_anns.append(ann) # Keep lower IDs and -1
                    self.annotations[img_path] = updated_anns
                # Also update augmented annotations if necessary (though usually saved after final classes)
                for orig_path in self.augmented_images:
                     new_aug_list = []
                     for img_data, aug_anns in self.augmented_images[orig_path]:
                          updated_aug_anns = []
                          for ann in aug_anns:
                               current_id = ann['class_id']
                               if current_id == class_id_to_remove:
                                    ann['class_id'] = -1
                                    updated_aug_anns.append(ann)
                               elif current_id > class_id_to_remove:
                                    ann['class_id'] -= 1
                                    updated_aug_anns.append(ann)
                               else:
                                    updated_aug_anns.append(ann)
                          new_aug_list.append( (img_data, updated_aug_anns) )
                     self.augmented_images[orig_path] = new_aug_list

                self.set_dirty() # Mark dirty if class was successfully removed
                return True
            except ValueError: # Should not happen if class_name in self.class_names
                return False
        return False

    def update_annotations_from_detections(self, image_path: str, detections: List[dict]):
        """
        Update annotations from model detections. Assigns class_id = -1.
        Detections format: [{'bbox_xyxy': [x1,y1,x2,y2], 'confidence': float, 'model_class_id': int}]
        """
        if image_path not in self.image_paths:
            print(f"Warning: Cannot update annotations for unknown image path: {image_path}")
            return False

        img_w, img_h = self._get_image_dims(image_path)
        if img_w == 0 or img_h == 0:
            print(f"Warning: Cannot update annotations, invalid dimensions for: {image_path}")
            return False

        new_annotations = []
        for det in detections:
            xyxy = det['bbox_xyxy']
            yolo_bbox = xyxy_to_cxcywh_normalized(xyxy, img_w, img_h)

            # Clamp normalized values just in case
            yolo_bbox = [clamp(c, 0.0, 1.0) for c in yolo_bbox]

            annotation = {
                'class_id': -1, # Start as unassigned
                'bbox': yolo_bbox,
                'confidence': det.get('confidence', 1.0),
                'model_class_id': det.get('model_class_id', -1) # Store original model prediction
            }
            new_annotations.append(annotation)

        # Only mark dirty if the new annotations are different from the old ones
        if self.annotations.get(image_path) != new_annotations:
             self.annotations[image_path] = new_annotations
             self.set_dirty()
        return True

    def add_manual_box(self, image_path: str, box_rect_img_coords: QRect) -> int:
        """
        Adds a manually drawn box (in image pixel coordinates) as an annotation.
        Returns the index of the added box, or -1 on failure.
        """
        if image_path not in self.image_paths: return -1

        img_w, img_h = self._get_image_dims(image_path)
        if img_w == 0 or img_h == 0: return -1

        xyxy = [
            box_rect_img_coords.left(), box_rect_img_coords.top(),
            box_rect_img_coords.right(), box_rect_img_coords.bottom()
        ]
        yolo_bbox = xyxy_to_cxcywh_normalized(xyxy, img_w, img_h)
        yolo_bbox = [clamp(c, 0.0, 1.0) for c in yolo_bbox] # Clamp

        annotation = {
            'class_id': -1, # Start as unassigned
            'bbox': yolo_bbox,
            'confidence': 1.0, # Manual box has max confidence
            'model_class_id': -1
        }
        self.annotations[image_path].append(annotation)
        self.set_dirty()
        return len(self.annotations[image_path]) - 1 # Return index of the new box


    def assign_class_to_box(self, image_path: str, box_index: int, class_id: int) -> bool:
        """Assign a class_id to a specific bounding box."""
        current_class_id = -2 # Use a value that class_id cannot be
        if (image_path in self.annotations and
            0 <= box_index < len(self.annotations[image_path])):
            current_class_id = self.annotations[image_path][box_index].get('class_id', -1)

        if current_class_id != class_id: # Check if assignment actually changes the class
            if (0 <= class_id < len(self.class_names)): # Ensure class_id is valid
                 self.annotations[image_path][box_index]['class_id'] = class_id
                 self.set_dirty()
                 return True
            elif (class_id == -1): # Allow unassigning
                 self.annotations[image_path][box_index]['class_id'] = -1
                 self.set_dirty()
                 return True

            print(f"Warning: Failed to assign invalid class {class_id} to box {box_index} for image {image_path}")
            return False
        else:
            # No change needed, assignment successful in the sense that the state is correct
            return True


    def delete_box(self, image_path: str, box_index: int) -> bool:
         """Delete a specific bounding box annotation."""
         if (image_path in self.annotations and
             0 <= box_index < len(self.annotations[image_path])):
             del self.annotations[image_path][box_index]
             self.set_dirty()
             return True
         return False


    def add_augmented_images(self, image_path: str, augmented_data: List[Tuple[np.ndarray, List[dict]]]):
        """Store augmented images and their annotations. Does not mark project as dirty."""
        # Augmented images are considered transient and don't dirty the project file
        if image_path in self.image_paths:
            if image_path not in self.augmented_images:
                self.augmented_images[image_path] = []
            self.augmented_images[image_path].extend(augmented_data)
            # Do NOT set dirty here
            return True
        return False

    def clear_augmented_images(self):
        """Clear all previously generated augmented images. Does not mark project as dirty."""
        self.augmented_images = {}
        # Do NOT set dirty here

    def save_yolo_dataset(self, output_dir: str, train_split: float = 0.8,
                          progress_callback: Optional[Callable[[int, int, str], None]] = None) -> bool:
        """Save the dataset in YOLO format (images, labels, data.yaml, train.txt, val.txt)."""
        if not self.class_names:
            print("Error: Cannot save dataset without class names defined.")
            if progress_callback: progress_callback(0, 1, "Error: No classes defined")
            return False

        # Filter only images with assigned annotations
        annotated_paths = {
            p for p, anns in self.annotations.items()
            if any(a['class_id'] >= 0 for a in anns)
        }
        augmented_annotated = {
             p for p, aug_list in self.augmented_images.items()
             if any(any(a['class_id'] >= 0 for a in anns) for _, anns in aug_list)
        }
        # Combine original and augmented paths that have valid annotations
        paths_to_save = list(annotated_paths)
        augmented_to_save = {p: data for p, data in self.augmented_images.items() if p in augmented_annotated}


        if not paths_to_save and not augmented_to_save:
             print("Error: No images with assigned annotations found to save.")
             if progress_callback: progress_callback(0, 1, "Error: No annotated images to save")
             return False

        try:
            dataset_dir = os.path.join(output_dir, 'yolo_dataset') # More descriptive name
            images_dir = os.path.join(dataset_dir, 'images')
            labels_dir = os.path.join(dataset_dir, 'labels')
            train_dir = os.path.join(images_dir, 'train')
            val_dir = os.path.join(images_dir, 'val')
            train_labels_dir = os.path.join(labels_dir, 'train')
            val_labels_dir = os.path.join(labels_dir, 'val')

            ensure_dir(dataset_dir)
            ensure_dir(train_dir)
            ensure_dir(val_dir)
            ensure_dir(train_labels_dir)
            ensure_dir(val_labels_dir)

            all_data_items = [] # List of tuples: (source_path, dest_img_folder, dest_lbl_folder, annotations, base_name_modifier)

            # Prepare original images data
            for img_path in paths_to_save:
                 # Only include if it has assigned annotations
                 valid_anns = [ann for ann in self.annotations.get(img_path, []) if ann['class_id'] >= 0]
                 if valid_anns:
                      all_data_items.append((img_path, None, None, valid_anns, "")) # Folders decided during split

            # Prepare augmented images data
            for orig_img_path, augmented_list in augmented_to_save.items():
                orig_base_name = os.path.splitext(os.path.basename(orig_img_path))[0]
                for j, (aug_img_np, aug_annotations) in enumerate(augmented_list):
                    valid_aug_anns = [ann for ann in aug_annotations if ann['class_id'] >= 0]
                    if valid_aug_anns:
                         modifier = f"_aug_{j+1}"
                         # Store numpy array directly to avoid re-reading
                         all_data_items.append((aug_img_np, None, None, valid_aug_anns, modifier))


            total_items = len(all_data_items)
            if total_items == 0:
                 print("Error: No valid annotations found in selected images or augmentations.")
                 if progress_callback: progress_callback(0, 1, "Error: No valid annotations to save")
                 return False

            # Shuffle and split
            random.shuffle(all_data_items)
            split_idx = int(total_items * train_split)
            train_items = all_data_items[:split_idx]
            val_items = all_data_items[split_idx:]

            # Assign destination folders
            for i in range(len(train_items)):
                 train_items[i] = (train_items[i][0], train_dir, train_labels_dir, train_items[i][3], train_items[i][4])
            for i in range(len(val_items)):
                 val_items[i] = (val_items[i][0], val_dir, val_labels_dir, val_items[i][3], val_items[i][4])

            combined_items = train_items + val_items
            total_steps = len(combined_items) + 1 # +1 for data.yaml

            # Process and save items
            saved_image_paths_rel = {'train': [], 'val': []} # Store relative paths for yaml
            processed_count = 0

            for item_data in combined_items:
                processed_count += 1
                source_data, dest_img_dir, dest_lbl_dir, annotations_to_save, name_modifier = item_data
                set_name = os.path.basename(dest_img_dir) # 'train' or 'val'

                if progress_callback:
                    progress_callback(processed_count, total_steps, f"Saving {set_name} item {processed_count}/{total_items}")

                # Determine base name and source type
                if isinstance(source_data, str): # Original image path
                    img_path = source_data
                    img_to_save = cv2.imread(img_path)
                    if img_to_save is None: continue
                    base_name = os.path.splitext(os.path.basename(img_path))[0]
                elif isinstance(source_data, np.ndarray): # Augmented image data
                    img_to_save = source_data
                    # Need to find original path to generate base name (a bit convoluted)
                    # This assumes augmented_images keys match image_paths
                    # A better approach might be to store the original base name with augmented data
                    base_name = "augmented" # Fallback name
                    for p, aug_list in augmented_to_save.items():
                         if any(id(item[0]) == id(img_to_save) for item in aug_list):
                              base_name = os.path.splitext(os.path.basename(p))[0]
                              break

                else: continue # Should not happen

                # Save image (always as jpg for consistency)
                final_base_name = f"{base_name}{name_modifier}"
                dest_img_path = os.path.join(dest_img_dir, f"{final_base_name}.jpg")
                cv2.imwrite(dest_img_path, img_to_save, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

                # Save label file
                label_path = os.path.join(dest_lbl_dir, f"{final_base_name}.txt")
                with open(label_path, 'w') as f:
                    for ann in annotations_to_save:
                        class_id = ann['class_id']
                        bbox = ann['bbox'] # Assumed to be valid YOLO format [cx, cy, w, h]
                        bbox_str = ' '.join([f"{coord:.6f}" for coord in bbox])
                        f.write(f"{class_id} {bbox_str}\n")

                # Store relative path for data.yaml (relative to dataset_dir)
                rel_img_path = os.path.join('images', set_name, f"{final_base_name}.jpg")
                saved_image_paths_rel[set_name].append(rel_img_path)


            # Save data.yaml
            if progress_callback:
                progress_callback(total_steps, total_steps, "Saving data.yaml")

            # Use relative paths inside data.yaml, assuming execution from output_dir
            data_yaml_content = {
                 # The paths below are relative *from the dataset_dir*
                 'path': dataset_dir, # Root path of the dataset
                 'train': os.path.join('images', 'train'), # Path to train images folder
                 'val': os.path.join('images', 'val'),     # Path to val images folder
                 #'test': '', # Optional test set path

                 # Classes
                 'nc': len(self.class_names),
                 'names': self.class_names
            }

            # ---- Alternative data.yaml using train.txt/val.txt ----
            # train_txt_path = os.path.join(dataset_dir, 'train.txt')
            # val_txt_path = os.path.join(dataset_dir, 'val.txt')
            # with open(train_txt_path, 'w') as f:
            #     f.write('\n'.join(saved_image_paths_rel['train']))
            # with open(val_txt_path, 'w') as f:
            #     f.write('\n'.join(saved_image_paths_rel['val']))
            # data_yaml_content = {
            #     'train': 'train.txt', # Path relative to dataset_dir
            #     'val': 'val.txt',     # Path relative to dataset_dir
            #     'nc': len(self.class_names),
            #     'names': self.class_names
            # }
            # --------------------------------------------------------


            with open(os.path.join(dataset_dir, 'data.yaml'), 'w') as f:
                yaml.dump(data_yaml_content, f, default_flow_style=None, sort_keys=False)

            if progress_callback:
                progress_callback(total_steps, total_steps, "Dataset saved successfully")

            return True

        except Exception as e:
            print(f"Error saving dataset: {e}")
            import traceback
            traceback.print_exc()
            if progress_callback:
                progress_callback(processed_count, total_steps, f"Error: {e}")
            return False