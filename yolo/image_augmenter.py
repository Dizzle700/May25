"""
Image Augmenter module - Handles image augmentation using Albumentations (PyQt6 version)
"""

import cv2
import numpy as np
import albumentations as A
from typing import List, Tuple, Dict, Optional, Self

# Use local imports due to flat structure
from utils import clamp

class ImageAugmenter:
    """Handles image augmentation using Albumentations library."""

    # Define available augmentations and their default states
    DEFAULT_AUG_OPTIONS = {
        "HorizontalFlip": True,
        "ShiftScaleRotate": True,
        "RandomBrightnessContrast": True,
        "HueSaturationValue": False,
        "RGBShift": False,
        "GaussianBlur": False,
        "GaussNoise": False,
        "ImageCompression": False,
        "GridDistortion": False,
        # Add more as needed, matching the keys below
    }

    def __init__(self):
        self.current_options = self.DEFAULT_AUG_OPTIONS.copy()
        self.transform = self._build_transform(self.current_options)

    def get_augmentation_options(self) -> Dict[str, bool]:
        """Return the dictionary of available augmentation options and their current state."""
        return self.current_options.copy()

    def update_transform(self, options: Dict[str, bool]):
        """Update the current options and rebuild the transform pipeline."""
        self.current_options = options
        self.transform = self._build_transform(self.current_options)
        print(f"Augmentation transform updated with options: {self.current_options}") # Debug print

    def _build_transform(self, options: Dict[str, bool]) -> A.Compose:
        """Build the augmentation pipeline based on the provided options."""
        transforms_list = []

        # Conditionally add transforms based on options dict
        if options.get("HorizontalFlip", False):
            transforms_list.append(A.HorizontalFlip(p=0.5))

        if options.get("ShiftScaleRotate", False):
            transforms_list.append(A.ShiftScaleRotate(shift_limit=0.06, scale_limit=0.1, rotate_limit=15, p=0.7,
                                   border_mode=cv2.BORDER_CONSTANT, value=[128,128,128]))

        if options.get("RandomBrightnessContrast", False):
            transforms_list.append(A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5))

        if options.get("HueSaturationValue", False):
            transforms_list.append(A.HueSaturationValue(hue_shift_limit=10, sat_shift_limit=15, val_shift_limit=10, p=0.3))

        if options.get("RGBShift", False):
            transforms_list.append(A.RGBShift(r_shift_limit=10, g_shift_limit=10, b_shift_limit=10, p=0.2))

        if options.get("GaussianBlur", False):
            transforms_list.append(A.GaussianBlur(blur_limit=(3, 5), p=0.2))

        if options.get("GaussNoise", False):
            transforms_list.append(A.GaussNoise(var_limit=(10.0, 50.0), p=0.2))

        if options.get("ImageCompression", False):
            transforms_list.append(A.ImageCompression(quality_lower=85, quality_upper=95, p=0.2))

        if options.get("GridDistortion", False):
            transforms_list.append(A.GridDistortion(p=0.1))

        # Ensure bbox_params are always included
        bbox_params = A.BboxParams(
            format='yolo',
            label_fields=['class_labels'],
            min_visibility=0.2,
            min_area=16
        )

        # Handle case where no augmentations are selected
        if not transforms_list:
            # Return a Compose with just identity transform if needed, or handle differently
            # For now, return Compose which might do nothing if list is empty before bbox
             print("Warning: No augmentation options selected.")
             # You might want to add A.NoOp() if the list is empty, but Compose handles it.

        return A.Compose(transforms_list, bbox_params=bbox_params)

    def set_custom_transform(self, transform: A.Compose):
         # This might be deprecated now, or adapted to work with the options structure
         print("Warning: set_custom_transform is potentially deprecated by the options-based approach.")
         # ... (keep existing validation or adapt/remove) ...
         # If keeping, ensure it updates self.current_options somehow or bypasses it.
         self.transform = transform

    def augment_image(self,
                       image_bgr: np.ndarray,
                       annotations: List[Dict],
                       num_augmentations: int = 5
                       ) -> List[Tuple[np.ndarray, List[Dict]]]:
        """
        Apply augmentations to a BGR image and its annotations using the current transform.
        (Docstring largely unchanged)
        """
        # Filter annotations to only include those with valid class IDs for augmentation
        valid_annotations = [ann for ann in annotations if ann.get('class_id', -1) >= 0]

        if not valid_annotations:
            return []
        if num_augmentations <= 0:
            return [] # Don't augment if count is 0

        results = []
        bboxes_orig = [ann['bbox'] for ann in valid_annotations]
        class_labels_orig = [ann['class_id'] for ann in valid_annotations]
        other_data_orig = [{k: v for k, v in ann.items() if k not in ['bbox', 'class_id']} for ann in valid_annotations]

        # Get the currently configured transform
        current_transform = self.transform

        for _ in range(num_augmentations):
            try:
                # Important: Convert BGR to RGB for Albumentations
                image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

                transformed = current_transform(
                    image=image_rgb,
                    bboxes=bboxes_orig,
                    class_labels=class_labels_orig
                )

                augmented_image_rgb = transformed['image']
                augmented_bboxes = transformed['bboxes']
                augmented_class_labels = transformed['class_labels']

                if not augmented_bboxes:
                    continue

                augmented_image_bgr = cv2.cvtColor(augmented_image_rgb, cv2.COLOR_RGB2BGR)

                augmented_annotations = []
                for i, bbox in enumerate(augmented_bboxes):
                    clamped_bbox = [clamp(c, 0.0, 1.0) for c in bbox]
                    if clamped_bbox[2] <= 0 or clamped_bbox[3] <= 0: continue

                    new_ann = {
                        'class_id': augmented_class_labels[i],
                        'bbox': clamped_bbox
                    }
                    if i < len(other_data_orig):
                        new_ann.update(other_data_orig[i])
                    augmented_annotations.append(new_ann)

                if augmented_annotations:
                    results.append((augmented_image_bgr, augmented_annotations))

            except Exception as e:
                print(f"Error during augmentation iteration: {e}")
                continue

        return results

    def preview_augmentations(self,
                             image_bgr: np.ndarray,
                             annotations: List[Dict],
                             num_samples: int = 3
                             ) -> List[Tuple[np.ndarray, List[Dict]]]:
        """Generate a few samples of augmentations for preview."""
        return self.augment_image(image_bgr, annotations, num_augmentations=num_samples)