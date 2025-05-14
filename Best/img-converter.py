import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
from PIL import Image
import numpy as np
import time
from pathlib import Path
import queue
import pandas as pd
import math

class ImageConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("Comfy Image Converter")
        self.root.geometry("700x550")
        self.root.configure(bg="#2D3250")
        
        self.setup_styles()
        self.setup_variables()
        self.create_widgets()
        
        # Queue for thread communication
        self.queue = queue.Queue()
        self.update_progress()
    
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.style.configure('TFrame', background="#2D3250")
        self.style.configure('TButton', background="#7077A1", foreground="#FFFFFF", font=('Arial', 10, 'bold'))
        self.style.configure('TLabel', background="#2D3250", foreground="#F6F6F6", font=('Arial', 10))
        self.style.configure('TCheckbutton', background="#2D3250", foreground="#F6F6F6", font=('Arial', 10))
        self.style.configure('Header.TLabel', background="#2D3250", foreground="#F6B17A", font=('Arial', 14, 'bold'))
        self.style.configure("blue.Horizontal.TProgressbar", background="#7077A1")
        self.style.configure('TEntry', fieldbackground="#424769", foreground="#FFFFFF")
    
    def setup_variables(self):
        self.folder_path = tk.StringVar()
        self.quality_var = tk.StringVar(value="85")  # StringVar for quality
        self.dpcm_var = tk.BooleanVar(value=True)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Ready")
        self.is_processing = False
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(padx=20, pady=20, fill=tk.BOTH, expand=True)
        
        # Header
        header_label = ttk.Label(main_frame, text="Comfy Image Converter", style="Header.TLabel")
        header_label.pack(pady=(0, 20))
        
        # Input folder selection
        folder_frame = ttk.Frame(main_frame)
        folder_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(folder_frame, text="Input Folder:").pack(side=tk.LEFT, padx=5)
        
        self.folder_entry = ttk.Entry(folder_frame, textvariable=self.folder_path)
        self.folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        browse_btn = ttk.Button(folder_frame, text="Browse", command=self.browse_folder)
        browse_btn.pack(side=tk.LEFT, padx=5)
        
        # Quality selection (Entry + Slider)
        quality_frame = ttk.Frame(main_frame)
        quality_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(quality_frame, text="JPEG/WebP Quality (70-100):").pack(side=tk.LEFT, padx=5)
        
        # Validation for Entry
        def validate_quality_input(action, value_if_allowed):
            if action == "1":  # Insertion
                if not value_if_allowed.isdigit():
                    return False
                try:
                    quality = int(value_if_allowed)
                    return 70 <= quality <= 100
                except ValueError:
                    return False
            return True
        
        vcmd = (self.root.register(validate_quality_input), '%d', '%P')
        
        self.quality_entry = ttk.Entry(
            quality_frame,
            textvariable=self.quality_var,
            width=5,
            validate="key",
            validatecommand=vcmd
        )
        self.quality_entry.pack(side=tk.LEFT, padx=5)
        
        # Slider for quality
        self.quality_slider = ttk.Scale(
            quality_frame,
            from_=70,
            to=100,
            orient=tk.HORIZONTAL,
            length=200,
            command=self.update_quality_from_slider
        )
        self.quality_slider.set(85)  # Default value
        self.quality_slider.pack(side=tk.LEFT, padx=10)
        
        # Sync Entry with Slider
        self.quality_var.trace("w", self.update_slider_from_entry)
        
        # DPCM check
        dpcm_frame = ttk.Frame(main_frame)
        dpcm_frame.pack(fill=tk.X, pady=5)
        
        dpcm_check = ttk.Checkbutton(dpcm_frame, text="Calculate DPCM Correlation", variable=self.dpcm_var)
        dpcm_check.pack(side=tk.LEFT, padx=5)
        
        # Convert button
        convert_frame = ttk.Frame(main_frame)
        convert_frame.pack(fill=tk.X, pady=10)
        
        self.convert_btn = ttk.Button(convert_frame, text="Convert Images", command=self.start_conversion)
        self.convert_btn.pack(pady=10)
        
        # Progress bar
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(progress_frame, text="Progress:").pack(anchor=tk.W)
        
        self.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=300, 
                                         mode='determinate', variable=self.progress_var,
                                         style="blue.Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # Status
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(status_frame, text="Status:").pack(anchor=tk.W)
        
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                    wraplength=650, justify=tk.LEFT)
        self.status_label.pack(fill=tk.X, pady=5)
        
        # Results display
        results_frame = ttk.Frame(main_frame)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        ttk.Label(results_frame, text="Results:").pack(anchor=tk.W)
        
        self.results_text = tk.Text(results_frame, height=10, bg="#424769", fg="white", 
                                  font=('Consolas', 10))
        self.results_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        scrollbar = ttk.Scrollbar(self.results_text, command=self.results_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.config(yscrollcommand=scrollbar.set)
        self.results_text.config(state=tk.DISABLED)
    
    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path.set(folder_selected)
    
    def update_quality_from_slider(self, value):
        """Update Entry from Slider"""
        self.quality_var.set(str(int(float(value))))
    
    def update_slider_from_entry(self, *args):
        """Update Slider from Entry"""
        try:
            value = int(self.quality_var.get())
            if 70 <= value <= 100:
                self.quality_slider.set(value)
        except ValueError:
            pass  # Ignore invalid input, validation handles it
    
    def update_results(self, message):
        self.results_text.config(state=tk.NORMAL)
        self.results_text.insert(tk.END, message + "\n")
        self.results_text.see(tk.END)
        self.results_text.config(state=tk.DISABLED)
    
    def start_conversion(self):
        if self.is_processing:
            messagebox.showinfo("Processing", "Conversion is already in progress!")
            return
            
        path = self.folder_path.get()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Error", "Please select a valid folder!")
            return
        
        # Ensure quality has a valid value
        try:
            quality = int(self.quality_var.get())
            if not (70 <= quality <= 100):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Quality must be a number between 70 and 100!")
            self.quality_var.set("85")
            self.quality_slider.set(85)
            return
        
        # Clear previous results
        self.results_text.config(state=tk.NORMAL)
        self.results_text.delete(1.0, tk.END)
        self.results_text.config(state=tk.DISABLED)
        
        self.is_processing = True
        self.convert_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        
        conversion_thread = threading.Thread(target=self.convert_images)
        conversion_thread.daemon = True
        conversion_thread.start()
    
    def convert_images(self):
        try:
            folder_path = self.folder_path.get()
            quality = int(self.quality_var.get())
            calc_dpcm = self.dpcm_var.get()
            
            jpeg_folder = os.path.join(folder_path, "jpeg_output")
            webp_folder = os.path.join(folder_path, "webp_output")
            
            os.makedirs(jpeg_folder, exist_ok=True)
            os.makedirs(webp_folder, exist_ok=True)
            
            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']
            image_files = []
            
            for ext in image_extensions:
                image_files.extend(list(Path(folder_path).glob(f"*{ext}")))
                image_files.extend(list(Path(folder_path).glob(f"*{ext.upper()}")))
            
            total_images = len(image_files)
            
            if total_images == 0:
                self.queue.put(("status", "No image files found in the selected folder."))
                self.queue.put(("complete", None))
                return
            
            self.queue.put(("status", f"Found {total_images} images. Starting conversion..."))
            
            finished_count = 0
            dpcm_results = {}
            total_jpeg_dpcm = 0
            total_webp_dpcm = 0
            successful_dpcm_count = 0
            total_original_size = 0
            total_jpeg_size = 0
            total_webp_size = 0
            
            def process_image(img_path):
                nonlocal finished_count, total_jpeg_dpcm, total_webp_dpcm, successful_dpcm_count
                nonlocal total_original_size, total_jpeg_size, total_webp_size
                
                try:
                    img_filename = os.path.basename(img_path)
                    name_without_ext = os.path.splitext(img_filename)[0]
                    
                    original_size = os.path.getsize(img_path) / 1024
                    total_original_size += original_size
                    
                    img = Image.open(img_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    jpeg_path = os.path.join(jpeg_folder, f"{name_without_ext}.jpg")
                    img.save(jpeg_path, 'JPEG', quality=quality)
                    
                    webp_path = os.path.join(webp_folder, f"{name_without_ext}.webp")
                    img.save(webp_path, 'WEBP', quality=quality)
                    
                    jpeg_size = os.path.getsize(jpeg_path) / 1024
                    webp_size = os.path.getsize(webp_path) / 1024
                    
                    total_jpeg_size += jpeg_size
                    total_webp_size += webp_size
                    
                    jpeg_size_diff = original_size - jpeg_size
                    webp_size_diff = original_size - webp_size
                    
                    jpeg_size_percent = (jpeg_size_diff / original_size) * 100 if original_size > 0 else 0
                    webp_size_percent = (webp_size_diff / original_size) * 100 if original_size > 0 else 0
                    
                    dpcm_results[img_filename] = {
                        "original_size_kb": round(original_size, 2),
                        "jpeg_size_kb": round(jpeg_size, 2),
                        "webp_size_kb": round(webp_size, 2),
                        "jpeg_size_reduction_kb": round(jpeg_size_diff, 2),
                        "webp_size_reduction_kb": round(webp_size_diff, 2),
                        "jpeg_size_reduction_percent": round(jpeg_size_percent, 2),
                        "webp_size_reduction_percent": round(webp_size_percent, 2),
                    }
                    
                    if calc_dpcm:
                        jpeg_corr, webp_corr = self.calculate_dpcm(img_path, jpeg_path, webp_path)
                        jpeg_corr = round(jpeg_corr, 5)
                        webp_corr = round(webp_corr, 5)
                        
                        dpcm_results[img_filename].update({
                            "jpeg_correlation": jpeg_corr,
                            "webp_correlation": webp_corr,
                        })
                        
                        if jpeg_corr > 0 and webp_corr > 0:
                            jpeg_diff_percent = (1 - jpeg_corr) * 100
                            webp_diff_percent = (1 - webp_corr) * 100
                            
                            dpcm_results[img_filename].update({
                                "jpeg_diff_percent": round(jpeg_diff_percent, 5),
                                "webp_diff_percent": round(webp_diff_percent, 5)
                            })
                            
                            total_jpeg_dpcm += jpeg_corr
                            total_webp_dpcm += webp_corr
                            successful_dpcm_count += 1
                    
                    finished_count += 1
                    progress = (finished_count / total_images) * 100
                    
                    self.queue.put(("progress", progress))
                    self.queue.put(("result", f"Converted: {img_filename}"))
                    
                except Exception as e:
                    self.queue.put(("result", f"Error converting {img_path}: {str(e)}"))
            
            worker_threads = []
            num_threads = min(os.cpu_count() or 4, total_images)
            
            for i in range(num_threads):
                thread_images = image_files[i::num_threads]
                thread = threading.Thread(target=lambda files=thread_images: [process_image(f) for f in files])
                thread.daemon = True
                worker_threads.append(thread)
                thread.start()
            
            for thread in worker_threads:
                thread.join()
            
            if dpcm_results:
                excel_path = os.path.join(folder_path, "conversion_results.xlsx")
                
                avg_jpeg_dpcm = round(total_jpeg_dpcm / successful_dpcm_count, 5) if successful_dpcm_count > 0 else 0
                avg_webp_dpcm = round(total_webp_dpcm / successful_dpcm_count, 5) if successful_dpcm_count > 0 else 0
                
                avg_jpeg_diff_percent = round((1 - avg_jpeg_dpcm) * 100, 5) if avg_jpeg_dpcm > 0 else 0
                avg_webp_diff_percent = round((1 - avg_webp_dpcm) * 100, 5) if avg_webp_dpcm > 0 else 0
                
                total_jpeg_diff = total_original_size - total_jpeg_size
                total_webp_diff = total_original_size - total_webp_size
                
                total_jpeg_diff_percent = (total_jpeg_diff / total_original_size) * 100 if total_original_size > 0 else 0
                total_webp_diff_percent = (total_webp_diff / total_original_size) * 100 if total_original_size > 0 else 0
                
                summary_data = {
                    "Metric": [
                        "Total Images",
                        "Total Original Size (KB)",
                        "Total JPEG Size (KB)",
                        "Total WebP Size (KB)",
                        "Total JPEG Size Reduction (KB)",
                        "Total WebP Size Reduction (KB)",
                        "Total JPEG Size Reduction (%)",
                        "Total WebP Size Reduction (%)",
                        "Images with DPCM Calculation",
                        "Average JPEG Correlation",
                        "Average WebP Correlation",
                        "Average JPEG Difference (%)",
                        "Average WebP Difference (%)"
                    ],
                    "Value": [
                        total_images,
                        round(total_original_size, 2),
                        round(total_jpeg_size, 2),
                        round(total_webp_size, 2),
                        round(total_jpeg_diff, 2),
                        round(total_webp_diff, 2),
                        round(total_jpeg_diff_percent, 2),
                        round(total_webp_diff_percent, 2),
                        successful_dpcm_count,
                        avg_jpeg_dpcm,
                        avg_webp_dpcm,
                        avg_jpeg_diff_percent,
                        avg_webp_diff_percent
                    ]
                }
                
                summary_df = pd.DataFrame(summary_data)
                individual_data = []
                for img_name, data in dpcm_results.items():
                    row = {"Image": img_name}
                    row.update(data)
                    individual_data.append(row)
                
                individual_df = pd.DataFrame(individual_data)
                
                with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
                    summary_df.to_excel(writer, sheet_name='Summary', index=False)
                    individual_df.to_excel(writer, sheet_name='Individual Results', index=False)
                    
                    workbook = writer.book
                    summary_sheet = writer.sheets['Summary']
                    
                    header_format = workbook.add_format({
                        'bold': True,
                        'bg_color': '#7077A1',
                        'font_color': 'white',
                        'border': 1
                    })
                    
                    for col_num, value in enumerate(summary_df.columns.values):
                        summary_sheet.write(0, col_num, value, header_format)
                
                self.queue.put(("result", f"\nResults saved to Excel file: {excel_path}"))
                self.queue.put(("result", f"\nSummary Results:"))
                self.queue.put(("result", f"Total images: {total_images}"))
                self.queue.put(("result", f"Total original size: {round(total_original_size, 2)} KB"))
                self.queue.put(("result", f"Total JPEG size: {round(total_jpeg_size, 2)} KB (saved {round(total_jpeg_diff_percent, 2)}%)"))
                self.queue.put(("result", f"Total WebP size: {round(total_webp_size, 2)} KB (saved {round(total_webp_diff_percent, 2)}%)"))
                
                if calc_dpcm and successful_dpcm_count > 0:
                    self.queue.put(("result", f"\nDPCM Correlation Results:"))
                    self.queue.put(("result", f"Images with DPCM calculation: {successful_dpcm_count}"))
                    self.queue.put(("result", f"Average JPEG correlation: {avg_jpeg_dpcm} (diff: {avg_jpeg_diff_percent}%)"))
                    self.queue.put(("result", f"Average WebP correlation: {avg_webp_dpcm} (diff: {avg_webp_diff_percent}%)"))
            
            self.queue.put(("status", f"Conversion complete! Converted {finished_count} images."))
            self.queue.put(("complete", None))
            
        except Exception as e:
            self.queue.put(("status", f"Error during conversion: {str(e)}"))
            self.queue.put(("complete", None))
    
    def calculate_dpcm(self, original_path, jpeg_path, webp_path):
        try:
            original_img = np.array(Image.open(original_path).convert('L'))
            jpeg_img = np.array(Image.open(jpeg_path).convert('L'))
            webp_img = np.array(Image.open(webp_path).convert('L'))
            
            jpeg_correlation = np.corrcoef(original_img.flat, jpeg_img.flat)[0, 1]
            webp_correlation = np.corrcoef(original_img.flat, webp_img.flat)[0, 1]
            
            return jpeg_correlation, webp_correlation
        except Exception:
            return (0, 0)
    
    def update_progress(self):
        try:
            while True:
                message_type, data = self.queue.get_nowait()
                
                if message_type == "progress":
                    self.progress_var.set(data)
                elif message_type == "status":
                    self.status_var.set(data)
                elif message_type == "result":
                    self.update_results(data)
                elif message_type == "complete":
                    self.is_processing = False
                    self.convert_btn.config(state=tk.NORMAL)
                
                self.queue.task_done()
        except queue.Empty:
            pass
        
        self.root.after(100, self.update_progress)

def main():
    root = tk.Tk()
    app = ImageConverter(root)
    root.mainloop()

if __name__ == "__main__":
    main()