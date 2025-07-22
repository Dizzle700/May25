# image_processor.py

import torch
from PIL import Image
from transformers import AutoModelForImageSegmentation, AutoProcessor
from torchvision.transforms.functional import to_pil_image
import numpy as np
from skimage.measure import find_contours

class ImageProcessor:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        
        # Load model and processor
        model_id = "briaai/RMBG-2.0"
        self.model = AutoModelForImageSegmentation.from_pretrained(model_id, trust_remote_code=True).to(self.device)
        self.processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

    def remove_background(self, pil_image):
        """Removes the background from a PIL image."""
        original_size = pil_image.size
        # Convert image to RGB if it has an alpha channel
        if pil_image.mode == 'RGBA':
            pil_image = pil_image.convert('RGB')
            
        inputs = self.processor(images=pil_image, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        mask = torch.nn.functional.interpolate(
            outputs.logits.unsqueeze(1),
            size=original_size,
            mode="bilinear",
            align_corners=False
        ).squeeze(1)
        
        mask = (mask.sigmoid() * 255).byte().cpu().squeeze()
        
        # Create a new image with a transparent background
        result_img = Image.new("RGBA", original_size, (0, 0, 0, 0))
        result_img.paste(pil_image.convert("RGBA"), (0, 0), Image.fromarray(mask.numpy(), mode='L'))
        
        return result_img, mask

    def create_bounding_box_image(self, original_image, mask_tensor):
        """Creates an image with bounding boxes drawn on it."""
        mask_np = mask_tensor.cpu().numpy()
        # Find contours at a constant value of 128 (mid-gray)
        contours = find_contours(mask_np, 128)

        # Create a copy to draw on
        image_with_box = original_image.copy().convert("RGBA")
        
        if not contours:
            return image_with_box # Return original if no object found

        # Combine all contour points to find the overall bounding box
        all_points = np.concatenate(contours, axis=0)
        
        # find_contours returns (row, col) which corresponds to (y, x)
        y_min, x_min = all_points.min(axis=0)
        y_max, x_max = all_points.max(axis=0)
        
        # Create a drawing context
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image_with_box)
        
        # Draw the rectangle (x_min, y_min, x_max, y_max)
        draw.rectangle(
            [x_min, y_min, x_max, y_max], 
            outline="red", 
            width=3
        )
        
        return image_with_box