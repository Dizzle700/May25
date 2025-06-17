# core/image_augmenter.py
import os
import random
from typing import List, Dict, Tuple, Optional, Any
import shutil
import cv2 # Needed for saving augmented images
import numpy as np  # Add the missing numpy import
import albumentations as A
from albumentations.augmentations.crops import transforms as crop_transforms

from .models import AppData, ImageAnnotation, BoundingBox
from . import utils
from . import formats # Import the format savers

class AugmentationConfig:
    """Configuration for different augmentation types"""
    def __init__(self):
        # Default values for augmentation parameters
        self.geometric_transforms_prob = 0.5
        self.color_transforms_prob = 0.5
        self.weather_transforms_prob = 0.3
        self.noise_transforms_prob = 0.3
        self.blur_transforms_prob = 0.3
        
        # Specific transform probabilities within each category
        self.hflip_prob = 0.5
        self.vflip_prob = 0.5
        self.rotate_prob = 0.3
        self.rotate_limit = 30  # degrees
        self.brightness_contrast_prob = 0.5
        self.hue_saturation_prob = 0.3
        self.rgb_shift_prob = 0.3
        self.blur_prob = 0.3
        self.gaussian_noise_prob = 0.3

        # Add the missing fields
        self.shift_scale_rotate_prob = 0.3
        self.elastic_transform_prob = 0.1
        self.grid_distortion_prob = 0.1
        self.optical_distortion_prob = 0.1
        self.clahe_prob = 0.3
        self.channel_shuffle_prob = 0.1
        self.gamma_prob = 0.3
        self.fog_prob = 0.3
        self.rain_prob = 0.2
        self.sunflare_prob = 0.1
        self.shadow_prob = 0.2
        self.iso_noise_prob = 0.3
        self.jpeg_compression_prob = 0.3
        self.posterize_prob = 0.2
        self.equalize_prob = 0.2
        self.gaussian_blur_prob = 0.3
        self.motion_blur_prob = 0.2
        self.median_blur_prob = 0.2
        self.glass_blur_prob = 0.1

class ImageAugmenter:
    """Handles image augmentation operations using Albumentations library."""
    def __init__(self):
        self.config = AugmentationConfig()
        # Default enabled states for transform categories
        self.enabled_transforms = {
            "geometric": True,
            "color": True,
            "weather": True,
            "noise": True,
            "blur": True
        }
        
    def create_transform_pipeline(self, include_geometric=None, include_color=None, 
                                include_weather=None, include_noise=None, include_blur=None,
                                custom_config=None):
        """
        Create an Albumentations transform pipeline with specified transform categories.
        
        Args:
            include_geometric: Whether to include geometric transforms (None means use enabled_transforms setting)
            include_color: Whether to include color transforms (None means use enabled_transforms setting)
            include_weather: Whether to include weather transforms (None means use enabled_transforms setting)
            include_noise: Whether to include noise transforms (None means use enabled_transforms setting)
            include_blur: Whether to include blur transforms (None means use enabled_transforms setting)
            custom_config: Optional custom configuration object
            
        Returns:
            Albumentations Compose object with the specified transforms
        """
        config = custom_config if custom_config else self.config
        transforms_list = []
        
        # Use provided values or fall back to enabled_transforms
        include_geometric = self.enabled_transforms["geometric"] if include_geometric is None else include_geometric
        include_color = self.enabled_transforms["color"] if include_color is None else include_color
        include_weather = self.enabled_transforms["weather"] if include_weather is None else include_weather
        include_noise = self.enabled_transforms["noise"] if include_noise is None else include_noise
        include_blur = self.enabled_transforms["blur"] if include_blur is None else include_blur
        
        # Geometric transforms
        if include_geometric:
            geometric_transforms = []
            
            # Basic flips and rotations
            if config.hflip_prob > 0:
                geometric_transforms.append(A.HorizontalFlip(p=config.hflip_prob))
            if config.vflip_prob > 0:
                geometric_transforms.append(A.VerticalFlip(p=config.vflip_prob))
            if config.rotate_prob > 0:
                geometric_transforms.append(A.Rotate(limit=config.rotate_limit, p=config.rotate_prob))
            
            # More advanced geometric transforms
            geometric_transforms.extend([
                A.ShiftScaleRotate(shift_limit=0.1, scale_limit=0.1, rotate_limit=15, p=config.shift_scale_rotate_prob),
                A.ElasticTransform(alpha=1, sigma=50, alpha_affine=50, p=config.elastic_transform_prob),
                A.GridDistortion(num_steps=5, distort_limit=0.3, p=config.grid_distortion_prob),
                A.OpticalDistortion(distort_limit=0.2, shift_limit=0.15, p=config.optical_distortion_prob)
            ])
            
            if geometric_transforms:
                transforms_list.append(
                    A.OneOf(geometric_transforms, p=config.geometric_transforms_prob)
                )
        
        # Color transforms
        if include_color:
            color_transforms = []
            
            if config.brightness_contrast_prob > 0:
                color_transforms.append(A.RandomBrightnessContrast(p=config.brightness_contrast_prob))
            if config.hue_saturation_prob > 0:
                color_transforms.append(A.HueSaturationValue(p=config.hue_saturation_prob))
            if config.rgb_shift_prob > 0:
                color_transforms.append(A.RGBShift(p=config.rgb_shift_prob))
            
            # More color transforms
            color_transforms.extend([
                A.CLAHE(clip_limit=4.0, tile_grid_size=(8, 8), p=config.clahe_prob),
                A.RandomGamma(gamma_limit=(80, 120), p=config.gamma_prob),
                A.ChannelShuffle(p=config.channel_shuffle_prob),
                A.ToGray(p=0.1), # ToGray does not have a probability, it's either on or off
                A.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1, p=0.3) # This one is also hardcoded, but not in the dialog
            ])
            
            if color_transforms:
                transforms_list.append(
                    A.OneOf(color_transforms, p=config.color_transforms_prob)
                )
        
        # Weather transforms
        if include_weather:
            weather_transforms = [
                A.RandomFog(fog_coef_lower=0.1, fog_coef_upper=0.3, alpha_coef=0.1, p=config.fog_prob),
                A.RandomRain(slant_lower=-10, slant_upper=10, drop_length=20, drop_width=1, drop_color=(200, 200, 200), p=config.rain_prob),
                A.RandomSunFlare(flare_roi=(0, 0, 1, 0.5), angle_lower=0, angle_upper=1, num_flare_circles_lower=6, num_flare_circles_upper=10, p=config.sunflare_prob),
                A.RandomShadow(shadow_roi=(0, 0.5, 1, 1), p=config.shadow_prob)
            ]
            
            if weather_transforms:
                transforms_list.append(
                    A.OneOf(weather_transforms, p=config.weather_transforms_prob)
                )
        
        # Noise transforms
        if include_noise:
            noise_transforms = []
            
            if config.gaussian_noise_prob > 0:
                noise_transforms.append(A.GaussNoise(p=config.gaussian_noise_prob))
                
            # More noise transforms
            noise_transforms.extend([
                A.ISONoise(color_shift=(0.01, 0.05), intensity=(0.1, 0.5), p=config.iso_noise_prob),
                A.ImageCompression(quality_lower=70, quality_upper=90, p=config.jpeg_compression_prob),
                A.Posterize(num_bits=4, p=config.posterize_prob),
                A.Equalize(p=config.equalize_prob)
            ])
            
            if noise_transforms:
                transforms_list.append(
                    A.OneOf(noise_transforms, p=config.noise_transforms_prob)
                )
                
        # Blur transforms
        if include_blur:
            blur_transforms = []
            
            if config.blur_prob > 0:
                blur_transforms.append(A.Blur(blur_limit=7, p=config.blur_prob))
                
            # More blur transforms
            blur_transforms.extend([
                A.GaussianBlur(blur_limit=7, p=config.gaussian_blur_prob),
                A.MotionBlur(blur_limit=7, p=config.motion_blur_prob),
                A.MedianBlur(blur_limit=7, p=config.median_blur_prob),
                A.GlassBlur(sigma=0.7, max_delta=4, iterations=2, p=config.glass_blur_prob)
            ])
            
            if blur_transforms:
                transforms_list.append(
                    A.OneOf(blur_transforms, p=config.blur_transforms_prob)
                )
                
        # If we have no transforms, add at least one simple transform
        if not transforms_list:
            transforms_list.append(A.HorizontalFlip(p=0.5))
                
        # Create the final transform pipeline
        transform = A.Compose(
            transforms_list,
            # Specify that we're working with bounding boxes in YOLO format
            bbox_params=A.BboxParams(
                format='yolo',  # [x_center, y_center, width, height] normalized
                label_fields=['class_labels'],
                min_visibility=0.3,  # Minimum visibility of a bbox after transforms
                min_area=25  # Minimum area in pixels for bbox to be preserved
            )
        )
        
        return transform

    def augment(self, annotation_data: ImageAnnotation, num_augmentations: int = 5) -> Dict[str, Tuple[ImageAnnotation, np.ndarray]]:
        """
        Generate augmented versions of an image with its annotations.
        
        Args:
            annotation_data: Original image annotation data
            num_augmentations: Number of augmented versions to create
            
        Returns:
            Dictionary mapping new image paths to (ImageAnnotation, np.ndarray) tuples
        """
        augmented_data = {}
        
        # Load the original image
        image = cv2.imread(annotation_data.image_path)
        if image is None:
            print(f"Error: Could not load image {annotation_data.image_path}")
            return {}
            
        # Convert BGR to RGB for processing
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # Extract bounding boxes in YOLO format
        bboxes = []
        class_labels = []
        for box in annotation_data.boxes:
            if box.class_id >= 0:  # Skip boxes with invalid class IDs
                bboxes.append(box.bbox_norm)
                class_labels.append(box.class_id)
        
        # Create different augmentation pipelines for variety, based on enabled transforms
        augmentation_types = []
        
        # Only add transform types that are enabled
        if (self.enabled_transforms["geometric"] or self.enabled_transforms["color"] or 
            self.enabled_transforms["weather"] or self.enabled_transforms["noise"] or 
            self.enabled_transforms["blur"]):
            # All enabled transforms
            augmentation_types.append(self.create_transform_pipeline())
        
        # Add specialized transform pipelines
        if self.enabled_transforms["color"]:
            # Color transforms only
            augmentation_types.append(self.create_transform_pipeline(
                include_geometric=False, include_weather=False, 
                include_noise=False, include_blur=False))
                
        if self.enabled_transforms["geometric"]:
            # Geometric transforms only
            augmentation_types.append(self.create_transform_pipeline(
                include_color=False, include_weather=False,
                include_noise=False, include_blur=False))
                
        if self.enabled_transforms["weather"] and self.enabled_transforms["noise"]:
            # Weather and noise transforms
            augmentation_types.append(self.create_transform_pipeline(
                include_geometric=False, include_color=False))
                
        if self.enabled_transforms["blur"] and self.enabled_transforms["noise"]:
            # Blur and noise transforms
            augmentation_types.append(self.create_transform_pipeline(
                include_geometric=False, include_color=False, 
                include_weather=False))
        
        # If no transform types were added, add a default one
        if not augmentation_types:
            augmentation_types.append(self.create_transform_pipeline(
                include_geometric=True, include_color=True,
                include_weather=False, include_noise=False, include_blur=False))
        
        # Create the specified number of augmentations
        for i in range(num_augmentations):
            # Select a random transform or cycle through them
            transform_idx = i % len(augmentation_types)
            transform = augmentation_types[transform_idx]
            
            # Apply the augmentation transforms
            try:
                if bboxes:
                    transformed = transform(image=image, bboxes=bboxes, class_labels=class_labels)
                    aug_image = transformed['image']
                    aug_bboxes = transformed['bboxes']
                    aug_class_labels = transformed['class_labels']
                else:
                    # For images without annotations, apply transforms without bounding boxes
                    transform_no_bbox = A.Compose(transform.transforms)
                    transformed = transform_no_bbox(image=image)
                    aug_image = transformed['image']
                    aug_bboxes = []
                    aug_class_labels = []
            except Exception as e:
                print(f"Error applying transforms: {str(e)}")
                continue
            
            # Create a new path for the augmented image
            base_name = os.path.basename(annotation_data.image_path)
            name, ext = os.path.splitext(base_name)
            aug_type = self._get_augmentation_type_name(transform_idx)
            aug_path = f"{os.path.dirname(annotation_data.image_path)}/aug_{name}_{aug_type}_{i}{ext}"
            
            # Create a new BoundingBox list from the augmented boxes
            new_boxes = []
            for j, (bbox, class_id) in enumerate(zip(aug_bboxes, aug_class_labels)):
                # Create normalized box coordinates
                bbox_norm = tuple(bbox)  # Already in YOLO format
                
                # Calculate pixel coordinates
                img_h, img_w = aug_image.shape[:2]
                x_center, y_center, width, height = bbox
                x_min = int((x_center - width/2) * img_w)
                y_min = int((y_center - height/2) * img_h)
                x_max = int((x_center + width/2) * img_w)
                y_max = int((y_center + height/2) * img_h)
                bbox_pixels = (x_min, y_min, x_max, y_max)
                
                # Create the bounding box
                new_box = BoundingBox(
                    class_id=class_id,
                    bbox_norm=bbox_norm,
                    bbox_pixels=bbox_pixels,
                    confidence=1.0  # Augmented boxes inherit full confidence
                )
                new_boxes.append(new_box)
            
            # Create a new annotation object
            aug_annotation = ImageAnnotation(
                image_path=aug_path,
                width=aug_image.shape[1],
                height=aug_image.shape[0],
                boxes=new_boxes,
                processed=True,
                augmented_from=annotation_data.image_path
            )
            
            # Convert back to BGR for OpenCV
            aug_image_bgr = cv2.cvtColor(aug_image, cv2.COLOR_RGB2BGR)
            
            # Add to the result dictionary
            augmented_data[aug_path] = (aug_annotation, aug_image_bgr)
        
        return augmented_data
    
    def _get_augmentation_type_name(self, transform_idx: int) -> str:
        """Get a descriptive name for the augmentation type"""
        types = ["all", "color", "geom", "weather", "blur"]
        return types[transform_idx % len(types)]
        
    def augment_batch(self, annotations_dict: Dict[str, ImageAnnotation], num_augmentations: int = 5) -> Dict[str, Tuple[ImageAnnotation, np.ndarray]]:
        """
        Generate augmented versions of multiple images with their annotations.
        
        Args:
            annotations_dict: Dictionary of image paths to annotations
            num_augmentations: Number of augmentations per image
            
        Returns:
            Dictionary mapping new image paths to (ImageAnnotation, np.ndarray) tuples
        """
        all_augmented_data = {}
        
        for image_path, annotation_data in annotations_dict.items():
            img_augmented_data = self.augment(annotation_data, num_augmentations)
            all_augmented_data.update(img_augmented_data)
            
        return all_augmented_data

# Remove the rest of the DataHandler class or reimplement the appropriate methods
# in the proper file (data_handler.py)
