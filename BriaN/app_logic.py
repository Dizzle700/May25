import torch
from torchvision import transforms
from PIL import Image
import os
import numpy as np # Keep if needed by model or transforms

# Lazy load transformers to speed up initial app load if check_dependencies is robust
try:
    from transformers import AutoModelForImageSegmentation
except ImportError:
    AutoModelForImageSegmentation = None # Will be checked by dependency checker

class BackgroundRemoverCore:
    def __init__(self):
        self.model = None
        self.device = None
        self.transform_image = None
        self.model_name = 'briaai/RMBG-2.0' # or APP_CONFIG["model_name"]
        self.image_size = (1024, 1024) # or APP_CONFIG["model_image_size"]
        self.model_loaded = False
        self._determine_initial_device()

    def _determine_initial_device(self):
        if torch.cuda.is_available():
            self.device = torch.device('cuda')
        else:
            self.device = torch.device('cpu')
        print(f"Initial processing device: {self.device.type.upper()}")


    def load_model(self):
        if self.model_loaded:
            return True
        if AutoModelForImageSegmentation is None:
            print("Error: Transformers library not loaded.")
            return False
        try:
            print(f"Loading AI model '{self.model_name}' to {self.device.type.upper()}...")
            self.model = AutoModelForImageSegmentation.from_pretrained(self.model_name, trust_remote_code=True)
            torch.set_float32_matmul_precision('high') # Check PyTorch version compatibility
            self.model.to(self.device)
            self.model.eval()

            self.transform_image = transforms.Compose([
                transforms.Resize(self.image_size),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) # Standard ImageNet normalization
            ])
            self.model_loaded = True
            print("AI Model loaded successfully.")
            return True
        except Exception as e:
            print(f"Error loading AI model: {e}")
            self.model = None
            self.model_loaded = False
            return False

    def get_device_name(self):
        return self.device.type.upper() if self.device else "N/A"

    def switch_device(self):
        if self.device.type == 'cuda':
            self.device = torch.device('cpu')
        elif torch.cuda.is_available():
            self.device = torch.device('cuda')
        else: # Already CPU and no CUDA
            return False # No switch possible

        if self.model: # If model is loaded, move it
            try:
                self.model.to(self.device)
                print(f"Model moved to {self.device.type.upper()}")
            except Exception as e:
                print(f"Error moving model to {self.device.type.upper()}: {e}")
                # Optionally try to revert device or handle error
                return False
        print(f"Processing device switched to {self.device.type.upper()}")
        return True


    def process_single_image(self, image_path, output_dir, output_format="PNG"):
        if not self.model_loaded:
            if not self.load_model(): # Attempt to load if not already
                raise RuntimeError("AI Model not loaded. Cannot process image.")
        try:
            original_image = Image.open(image_path)
            rgb_image = original_image.convert('RGB') # Model expects RGB

            input_tensor = self.transform_image(rgb_image).unsqueeze(0).to(self.device)

            with torch.no_grad():
                preds = self.model(input_tensor)
                # The output structure of RMBG-2.0 might be a tuple,
                # often the last element is the primary segmentation map.
                # Or it could be directly the tensor. Adjust based on actual model output.
                if isinstance(preds, (tuple, list)):
                    mask_tensor = preds[-1].sigmoid().cpu() # Get the last output, apply sigmoid, move to CPU
                else: # Assuming preds is the direct mask tensor
                    mask_tensor = preds.sigmoid().cpu()


            # Create mask from prediction
            pred_mask_pil = transforms.ToPILImage()(mask_tensor[0].squeeze()) # Squeeze batch and channel
            mask_resized = pred_mask_pil.resize(original_image.size, Image.Resampling.LANCZOS)

            # Apply mask as alpha channel
            output_image_rgba = original_image.convert('RGBA')
            output_image_rgba.putalpha(mask_resized)

            base_filename = os.path.splitext(os.path.basename(image_path))[0]
            saved_paths = []

            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            if output_format in ["PNG", "Both"]:
                png_filename = f"{base_filename}_nobg.png"
                png_path = os.path.join(output_dir, png_filename)
                output_image_rgba.save(png_path, format="PNG", optimize=True)
                saved_paths.append(png_path)
                print(f"Saved: {png_path}")

            if output_format in ["WebP", "Both"]:
                webp_filename = f"{base_filename}_nobg.webp"
                webp_path = os.path.join(output_dir, webp_filename)
                output_image_rgba.save(webp_path, format="WebP", lossless=True, quality=100)
                saved_paths.append(webp_path)
                print(f"Saved: {webp_path}")

            return saved_paths[0] if saved_paths else None # Return path to one of the saved images (e.g., PNG)

        except Exception as e:
            print(f"Error processing image {image_path}: {e}")
            # import traceback
            # traceback.print_exc()
            return None


class ImageComposerCore:
    def __init__(self):
        pass # Logic for this is largely in CanvasPane and DraggablePixmapItem

    # You might add helper functions here if complex non-GUI composition logic arises,
    # e.g., advanced blending modes, transformations, etc.
    def example_composition_logic(self):
        print("ImageComposerCore logic placeholder.")
