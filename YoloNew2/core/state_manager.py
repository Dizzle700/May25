import os
import json
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import AppData, ImageAnnotation, BoundingBox

class StateManager:
    """
    Manages saving and loading of application state.
    Handles automatic saving of annotations and app configuration.
    """
    
    def __init__(self, auto_save_interval: int = 60):
        """
        Initialize the state manager.
        
        Args:
            auto_save_interval: Time between auto-saves in seconds
        """
        self.app_data: Optional[AppData] = None
        self.auto_save_interval = auto_save_interval
        self.last_save_time = 0
        self.app_state_dir = self._get_app_state_dir()
        self.state_file = os.path.join(self.app_state_dir, "app_state.json")
        self.annotations_file = os.path.join(self.app_state_dir, "annotations.pickle")
        self.config_file = os.path.join(self.app_state_dir, "config.json")
        self._ensure_state_dir_exists()
        
    def _get_app_state_dir(self) -> str:
        """Get the directory for storing application state files"""
        # Create a directory in the user's home directory
        home_dir = os.path.expanduser("~")
        app_dir = os.path.join(home_dir, ".yolo_dataset_creator")
        return app_dir
        
    def _ensure_state_dir_exists(self):
        """Create state directory if it doesn't exist"""
        os.makedirs(self.app_state_dir, exist_ok=True)
        
    def set_app_data(self, app_data: AppData):
        """Set the application data reference"""
        self.app_data = app_data
        
    def auto_save_if_needed(self) -> bool:
        """
        Check if auto-save is needed and save if necessary
        
        Returns:
            True if auto-save was performed, False otherwise
        """
        if not self.app_data:
            return False
            
        current_time = time.time()
        if current_time - self.last_save_time >= self.auto_save_interval:
            self.save_state()
            self.last_save_time = current_time
            return True
        return False
            
    def save_state(self):
        """Save the current application state"""
        if not self.app_data:
            return
            
        # Save annotations
        self._save_annotations()
        
        # Save classes and model path
        self._save_config()
        
        # Save basic state info (image lists, etc.)
        self._save_basic_state()
            
    def _save_annotations(self):
        """Save all annotations to a file"""
        # We use pickle for annotations because they can be complex
        try:
            with open(self.annotations_file, 'wb') as f:
                # Create a serializable version of image annotations
                serializable_annotations = {}
                for image_path, annotation in self.app_data.images.items():
                    # Clone the annotation, but remove the _temp_image_data
                    # which can't be pickled efficiently
                    annotation_copy = ImageAnnotation(
                        image_path=annotation.image_path,
                        width=annotation.width,
                        height=annotation.height,
                        boxes=annotation.boxes,
                        processed=annotation.processed,
                        augmented_from=annotation.augmented_from
                    )
                    serializable_annotations[image_path] = annotation_copy
                    
                pickle.dump(serializable_annotations, f)
        except Exception as e:
            print(f"Error saving annotations: {e}")
            
    def _save_config(self):
        """Save configuration data (classes, model path)"""
        try:
            config = {
                "classes": self.app_data.classes,
                "model_path": self.app_data.model_path
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
            
    def _save_basic_state(self):
        """Save basic state info"""
        try:
            # Just save the list of image paths for now
            state = {
                "images": list(self.app_data.images.keys()),
                "last_saved": time.time()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Error saving basic state: {e}")
            
    def load_state(self) -> bool:
        """
        Load the saved application state
        
        Returns:
            True if state was loaded successfully, False otherwise
        """
        if not self.app_data:
            print("Cannot load state: app_data is not set")
            return False
            
        # Check if state files exist
        if not (os.path.exists(self.config_file) or os.path.exists(self.annotations_file)):
            print("No state files found to load")
            return False
            
        success = True
        
        # Load configuration
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.app_data.classes = config.get("classes", [])
                    self.app_data.model_path = config.get("model_path", None)
            except Exception as e:
                print(f"Error loading config: {e}")
                success = False
                
        # Load annotations
        if os.path.exists(self.annotations_file):
            try:
                with open(self.annotations_file, 'rb') as f:
                    loaded_images = pickle.load(f)
                    if loaded_images:
                        self.app_data.images = loaded_images
            except Exception as e:
                print(f"Error loading annotations: {e}")
                success = False
                
        # Update last save time
        self.last_save_time = time.time()
        return success
        
    def clear_state(self):
        """Clear all saved state files"""
        for file_path in [self.state_file, self.annotations_file, self.config_file]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error removing state file {file_path}: {e}") 