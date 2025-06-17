from PIL import Image
import matplotlib.pyplot as plt
import torch
from torchvision import transforms
from transformers import AutoModelForImageSegmentation
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, StringVar
import os
import threading
import warnings
from pathlib import Path
import sys
import importlib

# Suppress warnings
warnings.filterwarnings("ignore", category=FutureWarning)

def check_dependencies():
    """Check if all required dependencies are available."""
    required_modules = [
        'PIL', 'matplotlib', 'torch', 'torchvision', 'transformers', 'numpy'
    ]
    missing_modules = []
    
    for module in required_modules:
        try:
            importlib.import_module(module)
        except ImportError:
            missing_modules.append(module)
    
    if missing_modules:
        error_message = "The following required modules are missing:\n" + "\n".join(missing_modules)
        error_message += "\n\nPlease install them using:\npip install " + " ".join(missing_modules).lower()
        
        # Special case for PIL
        if 'PIL' in missing_modules:
            error_message = error_message.replace("pip install pil", "pip install pillow")
            
        return False, error_message
    
    return True, "All dependencies are available."

class BackgroundRemoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Background Remover")
        self.root.geometry("600x550")  # Increased height to accommodate new option
        self.root.configure(bg="#f0f4f8")
        
        # Set app icon if available
        try:
            self.root.iconbitmap("app_icon.ico")
        except:
            pass
            
        # Variables
        self.input_folder = ""
        self.output_folder = ""
        self.paused = False
        self.stopped = False
        self.processed_count = 0
        self.total_images = 0
        
        # Initialize model
        self.initialize_model()
        
        # Create GUI
        self.create_widgets()
        
    def initialize_model(self):
        # Status label during model loading
        loading_label = tk.Label(self.root, text="Loading AI model...", bg="#f0f4f8", fg="#2a6099", font=("Arial", 12, "bold"))
        loading_label.pack(pady=20)
        self.root.update()
        
        # Load the model
        try:
            self.model = AutoModelForImageSegmentation.from_pretrained('briaai/RMBG-2.0', trust_remote_code=True)
            torch.set_float32_matmul_precision('high')
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self.model.to(self.device)
            self.model.eval()
            
            # Data settings
            self.image_size = (1024, 1024)
            self.transform_image = transforms.Compose([
                transforms.Resize(self.image_size),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
            ])
            
            loading_label.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load model: {str(e)}")
            loading_label.destroy()
            sys.exit(1)
            
    def create_widgets(self):
        # Title
        title_frame = tk.Frame(self.root, bg="#2a6099", padx=10, pady=10)
        title_frame.pack(fill="x")
        
        title_label = tk.Label(title_frame, text="Smart Background Remover", 
                            font=("Arial", 16, "bold"), fg="white", bg="#2a6099")
        title_label.pack()
        
        subtitle_label = tk.Label(title_frame, text="Powered by RMBG-2.0 AI Model", 
                                font=("Arial", 9), fg="white", bg="#2a6099")
        subtitle_label.pack()
        
        # Main content frame
        content_frame = tk.Frame(self.root, bg="#f0f4f8", padx=20, pady=20)
        content_frame.pack(fill="both", expand=True)

        # Input & Output Section (define io_frame first)
        io_frame = tk.LabelFrame(content_frame, text="Input & Output Settings", 
                            bg="#f0f4f8", fg="#2a6099", padx=10, pady=10,
                            font=("Arial", 10, "bold"))
        io_frame.pack(fill="x", pady=10)
        
        # Format selection (moved after io_frame definition)
        format_frame = tk.Frame(io_frame, bg="#f0f4f8")
        format_frame.pack(fill="x", pady=5)
        
        format_label = tk.Label(format_frame, text="Output Format:", width=15, anchor="w", 
                            bg="#f0f4f8", fg="#333333")
        format_label.pack(side="left")
        
        self.format_var = StringVar()
        self.format_var.set("PNG")  # Default format
        
        format_dropdown = ttk.Combobox(format_frame, textvariable=self.format_var, 
                                    values=["PNG", "WebP", "Both"], width=40)
        format_dropdown.pack(side="left", padx=5)
        
        # Input folder selection
        input_frame = tk.Frame(io_frame, bg="#f0f4f8")
        input_frame.pack(fill="x", pady=5)
            
              
        self.input_path_var = StringVar()
        self.input_path_var.set("No folder selected")
        input_path_label = tk.Label(input_frame, textvariable=self.input_path_var, 
                                  bg="white", fg="#555555", padx=5, pady=2, width=40, anchor="w")
        input_path_label.pack(side="left", padx=5)
        
        input_button = tk.Button(input_frame, text="Browse", command=self.select_input_folder,
                               bg="#4a86cf", fg="white", padx=10)
        input_button.pack(side="left")
        
        # Output destination dropdown
        output_frame = tk.Frame(io_frame, bg="#f0f4f8")
        output_frame.pack(fill="x", pady=5)
        
        output_label = tk.Label(output_frame, text="Save To:", width=15, anchor="w", 
                              bg="#f0f4f8", fg="#333333")
        output_label.pack(side="left")
        
        # Output options
        self.output_option = StringVar()
        self.output_options = self.get_output_options()
        self.output_option.set(list(self.output_options.keys())[0]) # Default to first option
        
        output_dropdown = ttk.Combobox(output_frame, textvariable=self.output_option, 
                                      values=list(self.output_options.keys()), width=40)
        output_dropdown.pack(side="left", padx=5)
        
        output_button = tk.Button(output_frame, text="Custom", command=self.select_output_folder,
                               bg="#4a86cf", fg="white", padx=10)
        output_button.pack(side="left")
        
        # Device selection
        device_frame = tk.Frame(io_frame, bg="#f0f4f8")
        device_frame.pack(fill="x", pady=5)
        
        device_label = tk.Label(device_frame, text="Processing Device:", width=15, anchor="w", 
                              bg="#f0f4f8", fg="#333333")
        device_label.pack(side="left")
        
        self.device_var = StringVar()
        self.device_var.set(f"{'GPU' if self.device.type == 'cuda' else 'CPU'}")
        
        device_info = tk.Label(device_frame, textvariable=self.device_var, 
                             bg="#f0f4f8", fg="#333333", width=40, anchor="w")
        device_info.pack(side="left", padx=5)
        
        device_switch = tk.Button(device_frame, text="Switch Device", command=self.switch_device,
                               bg="#4a86cf", fg="white", padx=10)
        device_switch.pack(side="left")
        
        # Progress section
        progress_frame = tk.LabelFrame(content_frame, text="Processing Status", 
                                    bg="#f0f4f8", fg="#2a6099", padx=10, pady=10,
                                    font=("Arial", 10, "bold"))
        progress_frame.pack(fill="x", pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", length=500, mode="determinate")
        self.progress.pack(fill="x", pady=10)
        
        # Status info
        status_frame = tk.Frame(progress_frame, bg="#f0f4f8")
        status_frame.pack(fill="x")
        
        self.status_var = StringVar()
        self.status_var.set("Ready to start")
        
        status_label = tk.Label(status_frame, textvariable=self.status_var, 
                              bg="#f0f4f8", fg="#333333", font=("Arial", 9))
        status_label.pack(side="left")
        
        self.counter_var = StringVar()
        self.counter_var.set("0 / 0 images processed")
        
        counter_label = tk.Label(status_frame, textvariable=self.counter_var, 
                              bg="#f0f4f8", fg="#333333", font=("Arial", 9))
        counter_label.pack(side="right")
        
        # Buttons section
        buttons_frame = tk.Frame(content_frame, bg="#f0f4f8", pady=10)
        buttons_frame.pack(fill="x")
        
        self.start_button = tk.Button(buttons_frame, text="Start Processing", command=self.start_processing,
                                   bg="#28a745", fg="white", font=("Arial", 10, "bold"),
                                   padx=15, pady=5, width=15)
        self.start_button.pack(side="left", padx=5)
        
        self.pause_button = tk.Button(buttons_frame, text="Pause", command=self.pause_processing,
                                   bg="#fd7e14", fg="white", font=("Arial", 10),
                                   padx=15, pady=5, width=15, state=tk.DISABLED)
        self.pause_button.pack(side="left", padx=5)
        
        self.stop_button = tk.Button(buttons_frame, text="Stop", command=self.stop_processing,
                                  bg="#dc3545", fg="white", font=("Arial", 10),
                                  padx=15, pady=5, width=15, state=tk.DISABLED)
        self.stop_button.pack(side="left", padx=5)
        
        # Footer
        footer_frame = tk.Frame(self.root, bg="#2a6099", padx=10, pady=5)
        footer_frame.pack(fill="x", side="bottom")
        
        footer_label = tk.Label(footer_frame, text="© 2025 Smart Background Remover", 
                              fg="white", bg="#2a6099", font=("Arial", 8))
        footer_label.pack()
        
    def get_output_options(self):
        # Create options dictionary with display name and actual paths
        home_dir = str(Path.home())
        return {
            "Same as input folder (subfolder: 'processed')": "input_subfolder",
            f"Downloads folder ({os.path.join(home_dir, 'Downloads')})": os.path.join(home_dir, "Downloads"),
            f"Pictures folder ({os.path.join(home_dir, 'Pictures')})": os.path.join(home_dir, "Pictures"),
            f"Desktop ({os.path.join(home_dir, 'Desktop')})": os.path.join(home_dir, "Desktop"),
            "Custom location...": "custom"
        }
        
    def select_input_folder(self):
        folder = filedialog.askdirectory(title="Select Input Folder with Images")
        if folder:
            self.input_folder = folder
            # Display the path, but shorten if too long
            display_path = folder
            if len(display_path) > 40:
                display_path = "..." + display_path[-37:]
            self.input_path_var.set(display_path)
            
            # Update status
            image_files = [f for f in os.listdir(self.input_folder) 
                          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            self.total_images = len(image_files)
            self.counter_var.set(f"0 / {self.total_images} images processed")
            
            if self.total_images == 0:
                self.status_var.set("No valid images found in the selected folder")
            else:
                self.status_var.set(f"Found {self.total_images} images. Ready to process!")
                
    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Select Custom Output Folder")
        if folder:
            self.output_folder = folder
            # Add a new custom option
            custom_name = f"Custom: {folder}"
            if len(custom_name) > 50:
                custom_name = f"Custom: ...{folder[-47:]}"
            self.output_options[custom_name] = folder
            self.output_option.set(custom_name)
            
    def switch_device(self):
        if self.device.type == 'cuda':
            self.device = torch.device('cpu')
            self.device_var.set("CPU")
        else:
            if torch.cuda.is_available():
                self.device = torch.device('cuda')
                self.device_var.set("GPU")
            else:
                messagebox.showinfo("Info", "GPU not available. Continuing with CPU.")
                return
                
        # Move model to the selected device
        try:
            self.model.to(self.device)
            messagebox.showinfo("Device Changed", f"Switched to {self.device.type.upper()}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to switch device: {str(e)}")
            
    def determine_output_folder(self):
        selected_option = self.output_option.get()
        path = self.output_options[selected_option]
        
        if path == "input_subfolder":
            # Create a 'processed' subfolder in the input folder
            output_dir = os.path.join(self.input_folder, "processed")
        else:
            # Use the selected path
            output_dir = path
            
        # Create the folder if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
        
    def start_processing(self):
        if not self.input_folder:
            messagebox.showerror("Error", "Please select an input folder")
            return
            
        try:
            self.output_folder = self.determine_output_folder()
        except Exception as e:
            messagebox.showerror("Error", f"Error with output folder: {str(e)}")
            return
            
        self.stopped = False
        self.paused = False
        self.processed_count = 0
        
        # Update UI state
        self.start_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL, text="Pause")
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Processing images...")
        
        # Start processing thread
        self.thread = threading.Thread(target=self.process_images)
        self.thread.daemon = True  # Allow app to close even if thread is running
        self.thread.start()
        
    def pause_processing(self):
        self.paused = not self.paused
        self.pause_button.config(text="Resume" if self.paused else "Pause")
        self.status_var.set("Paused" if self.paused else "Processing images...")
        
    def stop_processing(self):
        self.stopped = True
        self.status_var.set("Stopping...")
        
    def process_images(self):
        # Get list of image files
        image_files = [f for f in os.listdir(self.input_folder) 
                      if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        self.total_images = len(image_files)
        self.progress["maximum"] = self.total_images
        
        for i, image_file in enumerate(image_files):
            if self.stopped:
                break
                
            # Handle pause state
            while self.paused:
                if self.stopped:
                    break
                self.root.update()
                continue
                
            # Update status
            self.status_var.set(f"Processing: {image_file}")
            
            # Process the image
            image_path = os.path.join(self.input_folder, image_file)
            try:
                output_path = self.process_image(image_path)
                self.processed_count += 1
            except Exception as e:
                error_msg = f"Error processing {image_file}: {str(e)}"
                self.status_var.set(error_msg)
                print(error_msg)
                
            # Update progress
            self.progress["value"] = i + 1
            self.counter_var.set(f"{self.processed_count} / {self.total_images} images processed")
            self.root.update()
            
        # Processing completed or stopped
        self.progress["value"] = 0
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        
        completion_message = "Processing completed" if not self.stopped else "Processing stopped"
        self.status_var.set(completion_message)
        
        # Show completion dialog
        if not self.stopped:
            messagebox.showinfo("Success", f"Processed {self.processed_count} images successfully!\nSaved to: {self.output_folder}")
            # Open output folder
            try:
                os.startfile(self.output_folder) if os.name == 'nt' else os.system(f'open "{self.output_folder}"')
            except:
                pass
                
    def process_image(self, image_path):
        try:
            # Open the image
            original_image = Image.open(image_path)
            
            # Convert to RGB for model processing
            rgb_image = original_image.convert('RGB')
            
            # Apply transformations for model input
            input_image = self.transform_image(rgb_image).unsqueeze(0).to(self.device)
            
            # Process with model
            with torch.no_grad():
                preds = self.model(input_image)[-1].sigmoid().cpu()
            
            # Create mask from prediction
            pred = preds[0].squeeze()
            pred_pil = transforms.ToPILImage()(pred)
            mask = pred_pil.resize(original_image.size)
            
            # Convert original image to RGBA for transparency if it isn't already
            if original_image.mode != 'RGBA':
                output_image = original_image.convert('RGBA')
            else:
                output_image = original_image.copy()
            
            # Apply mask as alpha channel
            output_image.putalpha(mask)
            
            # Determine output format(s)
            output_format = self.format_var.get()
            base_filename = os.path.splitext(os.path.basename(image_path))[0]
            
            # Save based on selected format
            if output_format in ["PNG", "Both"]:
                png_path = os.path.join(self.output_folder, f"{base_filename}_nobg.png")
                output_image.save(png_path, format="PNG", optimize=True)
                
            if output_format in ["WebP", "Both"]:
                webp_path = os.path.join(self.output_folder, f"{base_filename}_nobg.webp")
                output_image.save(webp_path, format="WebP", lossless=True, quality=100)
            
            # Return one of the output paths (using PNG as default return value)
            return os.path.join(self.output_folder, f"{base_filename}_nobg.png")
            
        except ImportError as e:
            if "numpy" in str(e).lower():
                raise ImportError("NumPy is not available. Please install NumPy with 'pip install numpy'.")
            else:
                raise
        except Exception as e:
            raise Exception(f"Error processing image: {str(e)}")

def main():
    # Check dependencies first
    deps_ok, deps_msg = check_dependencies()
    if not deps_ok:
        # Try to create a simple error window if tkinter is available
        try:
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            messagebox.showerror("Dependency Error", deps_msg)
            root.destroy()
        except:
            # If tkinter is not available, print to console
            print("ERROR: " + deps_msg)
        return
    
    # All dependencies are available, start the app
    root = tk.Tk()
    app = BackgroundRemoverApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()