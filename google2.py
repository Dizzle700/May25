import os
import re
import requests
import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext, ttk
import threading
import time
from datetime import datetime
import webbrowser
from PIL import Image, ImageTk
import io
import queue
from dotenv import load_dotenv
import configparser

# --- Configuration ---

load_dotenv()  # Load variables from .env file

# Define filter options
IMG_SIZE_OPTIONS = ["any", "huge", "icon", "large", "medium", "small", "xlarge", "xxlarge"]
IMG_TYPE_OPTIONS = ["any", "clipart", "face", "lineart", "stock", "photo", "animated"]
IMG_COLOR_TYPE_OPTIONS = ["any", "color", "gray", "mono"]
FILE_TYPE_OPTIONS = ["any", "bmp", "gif", "jpg", "png", "svg", "webp"]
SAFE_SEARCH_OPTIONS = ["off", "active", "high", "medium"]

# Color scheme
COLORS = {
    "primary": "#8e44ad",      # Dark Purple
    "primary_dark": "#6c3483", # Even Darker Purple
    "secondary": "#27ae60",    # Emerald Green
    "accent": "#e74c3c",       # Red
    "bg_dark": "#2c3e50",      # Very Dark Blue (almost black)
    "bg_light": "#34495e",     # Dark Slate (for secondary backgrounds)
    "text_dark": "#ecf0f1",    # Light Gray (for text on dark backgrounds)
    "text_light": "#ffffff"    # White (for highlights)
}

# --- Main Application Class ---

class ImageSearchApp:
    def __init__(self, root):
        self.root = root
        self.api_key = os.getenv("API_KEY")
        self.cse_id = os.getenv("CSE_ID")

        # --- State Variables ---
        self.is_paused = threading.Event()
        self.is_stopped = threading.Event()
        self.is_running = False
        self.current_preview = None

        # --- Thread-safe Queue for GUI Updates ---
        self.gui_queue = queue.Queue()

        self.setup_gui()
        self.load_settings() # Load settings on startup
        self.process_gui_queue() # Start listening for GUI updates

    # --- Backend and Worker Thread Logic ---

    def search_images(self, query, num_results, filters):
        """Performs the API call to Google Custom Search."""
        url = "https://customsearch.googleapis.com/customsearch/v1"
        params = {
            'q': query,
            'cx': self.cse_id,
            'key': self.api_key,
            'searchType': 'image',
            'num': num_results
        }

        # Add filters if they are not "any" or "off"
        if filters['img_size'] != "any":
            params['imgSize'] = filters['img_size'].upper()
        if filters['img_type'] != "any":
            params['imgType'] = filters['img_type']
        if filters['img_color_type'] != "any":
            params['imgColorType'] = filters['img_color_type']
        if filters['file_type'] != "any":
            params['fileType'] = filters['file_type']
        if filters['safe_search'] != "off":
            params['safe'] = filters['safe_search']

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            return response.json().get('items', []), None
        except requests.exceptions.RequestException as e:
            return [], f"API request failed: {e}"

    def save_images(self, image_items, save_directory, query, total_images_to_process, selected_file_type):
        """Downloads and saves a list of images."""
        if self.is_stopped.is_set():
            return 0, 0
        
        safe_query = self.sanitize_filename(query)
        query_directory = os.path.join(save_directory, safe_query)
        os.makedirs(query_directory, exist_ok=True)
        
        saved_count = 0
        failed_count = 0
        
        for i, item in enumerate(image_items):
            if self.is_stopped.is_set():
                break
            
            self.is_paused.wait() # This will block if the event is cleared (paused)
            
            image_url = item['link']
            try:
                # Queue preview update to run on the main thread
                self.gui_queue.put(('preview', image_url))
                    
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    # Determine the file extension to use
                    self.gui_queue.put(('log', f"DEBUG: Selected file type received: {selected_file_type}", "info"))

                    if selected_file_type != "any":
                        file_extension = selected_file_type
                    else:
                        # Try to infer from the content type or URL, otherwise default to jpg
                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'png' in content_type or image_url.lower().endswith('.png'):
                            file_extension = 'png'
                        elif 'gif' in content_type or image_url.lower().endswith('.gif'):
                            file_extension = 'gif'
                        elif 'bmp' in content_type or image_url.lower().endswith('.bmp'):
                            file_extension = 'bmp'
                        elif 'svg' in content_type or image_url.lower().endswith('.svg'):
                            file_extension = 'svg'
                        elif 'webp' in content_type or image_url.lower().endswith('.webp'):
                            file_extension = 'webp'
                        else:
                            file_extension = 'jpg' # Default fallback
                    
                    self.gui_queue.put(('log', f"DEBUG: Final file extension determined: {file_extension}", "info"))

                    image_name = f"{safe_query}_{i+1}_{timestamp}.{file_extension}"
                    image_path = os.path.join(query_directory, image_name)
                    
                    with open(image_path, 'wb') as f:
                        f.write(response.content)
                    self.gui_queue.put(('log', f"✓ Saved {image_name}", "success"))
                    saved_count += 1
                else:
                    self.gui_queue.put(('log', f"✗ Failed to download image #{i+1}: HTTP {response.status_code}", "error"))
                    failed_count += 1
            except Exception as e:
                self.gui_queue.put(('log', f"✗ Error downloading image #{i+1}: {str(e)[:100]}", "error"))
                failed_count += 1
            finally:
                # Queue progress update
                self.gui_queue.put(('progress_step',))
        
        return saved_count, failed_count
    
    def search_worker(self, queries, num_images, filters, save_directory):
        """The main function for the worker thread."""
        total_saved = 0
        total_failed = 0
        start_time = time.time()
        
        total_images_to_process = len(queries) * num_images
        self.gui_queue.put(('progress_max', total_images_to_process))

        for query in queries:
            if self.is_stopped.is_set():
                break
            
            self.is_paused.wait()
            
            if query.strip():
                self.gui_queue.put(('log', f"🔍 Searching for: {query}", "heading"))
                image_items, error = self.search_images(query, num_images, filters)
                
                if error:
                    self.gui_queue.put(('log', error, "error"))
                    # If API fails, we still need to advance the progress bar for this query
                    for _ in range(num_images):
                        self.gui_queue.put(('progress_step',))
                    continue

                if image_items:
                    self.gui_queue.put(('log', f"Found {len(image_items)} images for '{query}'", "info"))
                    selected_file_type = filters.get('file_type', 'jpg') # Default to 'jpg' if not found
                    saved, failed = self.save_images(image_items, save_directory, query, total_images_to_process, selected_file_type)
                    total_saved += saved
                    total_failed += failed
                    folder_path = os.path.join(save_directory, self.sanitize_filename(query))
                    self.gui_queue.put(('log', f"• Images saved to: {folder_path}", "info"))
                else:
                    self.gui_queue.put(('log', f"No images found for '{query}'", "warning"))
                    # If no images are found, advance the progress bar
                    for _ in range(num_images):
                        self.gui_queue.put(('progress_step',))
            else:
                # If a line is empty, advance the progress bar
                for _ in range(num_images):
                    self.gui_queue.put(('progress_step',))
            
        duration = round(time.time() - start_time, 1)
        
        # --- Final summary ---
        summary_messages = [
            ("\n==== SUMMARY ====", "heading"),
            (f"• Queries processed: {len(queries)}", "info"),
            (f"• Images saved: {total_saved}", "success"),
            (f"• Failed downloads: {total_failed}", "error" if total_failed > 0 else "info"),
            (f"• Time taken: {duration} seconds", "info"),
            (f"• Save location: {save_directory}", "info")
        ]
        
        for msg, level in summary_messages:
            self.gui_queue.put(('log', msg, level))
            
        # Signal completion
        self.gui_queue.put(('complete', f"Search finished. Saved {total_saved} images."))

    # --- GUI Methods (Callbacks and Updates) ---

    def on_search(self):
        """Callback for the 'Search' button."""
        # --- 1. Pre-flight checks ---
        if self.is_running:
            messagebox.showwarning("Warning", "A search is already in progress.")
            return

        save_directory = self.save_dir_entry.get()
        if not save_directory or not os.path.isdir(save_directory):
            messagebox.showwarning("Warning", "Please select a valid save directory.")
            return
            
        if not os.access(save_directory, os.W_OK):
            messagebox.showerror("Error", f"No write permissions for directory:\n{save_directory}")
            return

        queries = [q.strip() for q in self.query_text.get("1.0", tk.END).splitlines() if q.strip()]
        if not queries:
            messagebox.showwarning("Warning", "Please enter at least one search query.")
            return

        try:
            num_images = int(self.num_images_entry.get())
            if not (0 < num_images <= 10):
                messagebox.showwarning("Warning", "Number of images must be between 1 and 10 (API limit per query).")
                return
        except ValueError:
            messagebox.showwarning("Warning", "Please enter a valid number of images.")
            return

        # --- 2. Get settings ---
        filters = {
            'img_size': self.img_size_combobox.get(),
            'img_type': self.img_type_combobox.get(),
            'img_color_type': self.img_color_type_combobox.get(),
            'file_type': self.file_type_combobox.get(),
            'safe_search': self.safe_search_combobox.get()
        }
        
        # --- 3. Start the process ---
        self.is_running = True
        self.is_paused.set() # Set to not-paused state
        self.is_stopped.clear()
        
        self.update_ui_for_running_state()
        self.output_text.delete(1.0, tk.END)
        self.progress['value'] = 0

        # Create and start the worker thread
        threading.Thread(
            target=self.search_worker,
            args=(queries, num_images, filters, save_directory),
            daemon=True
        ).start()

    def on_pause(self):
        """Toggles the paused state."""
        if not self.is_paused.is_set(): # If it's paused (cleared)
            self.is_paused.set() # Resume
            self.pause_button['text'] = "Pause"
            self.status_label.config(text="Status: Running...", fg=COLORS["secondary"])
        else:
            self.is_paused.clear() # Pause
            self.pause_button['text'] = "Resume"
            self.status_label.config(text="Status: Paused", fg=COLORS["accent"])

    def on_stop(self):
        """Stops the current search."""
        if messagebox.askyesno("Stop Search", "Are you sure you want to stop the current search?"):
            self.is_stopped.set()
            self.is_paused.set() # Ensure any paused thread can check the stop flag and exit
            self.update_ui_for_stopped_state()
            self.log("Search stopped by user.", "warning")

    def process_gui_queue(self):
        """Processes messages from the worker thread to safely update the GUI."""
        try:
            while True:
                command, *args = self.gui_queue.get_nowait()
                
                if command == 'log':
                    self.log(*args)
                elif command == 'preview':
                    self.display_preview(*args)
                elif command == 'progress_max':
                    self.progress['maximum'] = args[0]
                elif command == 'progress_step':
                    self.progress.step()
                elif command == 'complete':
                    self.update_ui_for_finished_state()
                    messagebox.showinfo("Complete", args[0])
                elif command == 'error': # Generic error handling
                    messagebox.showerror("Error", args[0])

        except queue.Empty:
            pass # No more messages
        finally:
            self.root.after(100, self.process_gui_queue)

    def display_preview(self, image_url):
        """Fetches an image from a URL and displays it in the preview pane."""
        def fetch_image():
            try:
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    image_data = Image.open(io.BytesIO(response.content))
                    image_data.thumbnail((300, 200))
                    photo = ImageTk.PhotoImage(image_data)
                    
                    self.current_preview = photo # Keep reference
                    self.preview_label.config(image=photo, text="")
                else:
                    self.preview_label.config(image='', text="Preview unavailable")
            except Exception:
                self.preview_label.config(image='', text="Preview failed")
        
        # Run image fetching in a separate thread to not freeze the GUI
        threading.Thread(target=fetch_image, daemon=True).start()

    # --- UI Update and Helper Methods ---

    def update_ui_for_running_state(self):
        self.search_button['state'] = tk.DISABLED
        self.pause_button['text'] = "Pause"
        self.pause_button['state'] = tk.NORMAL
        self.stop_button['state'] = tk.NORMAL
        self.status_label.config(text="Status: Running...", fg=COLORS["secondary"])

    def update_ui_for_stopped_state(self):
        self.is_running = False
        self.search_button['state'] = tk.NORMAL
        self.pause_button['state'] = tk.DISABLED
        self.pause_button['text'] = "Pause"
        self.stop_button['state'] = tk.DISABLED
        self.status_label.config(text="Status: Stopped", fg=COLORS["accent"])

    def update_ui_for_finished_state(self):
        self.is_running = False
        self.search_button['state'] = tk.NORMAL
        self.pause_button['state'] = tk.DISABLED
        self.pause_button['text'] = "Pause"
        self.stop_button['state'] = tk.DISABLED
        self.status_label.config(text="Status: Completed", fg=COLORS["primary"])
        self.progress['value'] = self.progress['maximum']

    def log(self, message, level="normal"):
        """Inserts a colored message into the log window."""
        tags = (level,) if level != "normal" else ()
        self.output_text.insert(tk.END, message + "\n", tags)
        self.output_text.see(tk.END)

    def select_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.save_dir_entry.delete(0, tk.END)
            self.save_dir_entry.insert(0, directory)

    def open_save_location(self):
        directory = self.save_dir_entry.get()
        if directory and os.path.isdir(directory):
            webbrowser.open(directory)
        else:
            messagebox.showwarning("Warning", "Please select a valid save directory first.")

    def sanitize_filename(self, name):
        """Removes characters that are invalid for file/directory names."""
        name = name.replace(" ", "_")
        return re.sub(r'[\\/*?:"<>|]', "", name)

    def on_closing(self):
        """Handles the window close event."""
        if self.is_running:
            if messagebox.askyesno("Quit", "A search is in progress. Are you sure you want to quit?"):
                self.is_stopped.set()
                self.is_paused.set()
                self.save_settings() # Save settings before destroying
                self.root.destroy()
        else:
            self.save_settings() # Save settings before destroying
            self.root.destroy()

    def save_settings(self):
        """Saves current GUI settings to a config.ini file."""
        config = configparser.ConfigParser()
        config['SETTINGS'] = {
            'query_text': self.query_text.get("1.0", tk.END).strip(),
            'num_images': self.num_images_entry.get(),
            'img_size': self.img_size_combobox.get(),
            'img_type': self.img_type_combobox.get(),
            'img_color_type': self.img_color_type_combobox.get(),
            'file_type': self.file_type_combobox.get(),
            'safe_search': self.safe_search_combobox.get(),
            'save_directory': self.save_dir_entry.get()
        }
        try:
            with open('config.ini', 'w') as configfile:
                config.write(configfile)
            self.log("Settings saved to config.ini", "info")
        except Exception as e:
            self.log(f"Error saving settings: {e}", "error")

    def load_settings(self):
        """Loads GUI settings from a config.ini file."""
        config = configparser.ConfigParser()
        try:
            config.read('config.ini')
            if 'SETTINGS' in config:
                settings = config['SETTINGS']
                self.query_text.delete("1.0", tk.END)
                self.query_text.insert("1.0", settings.get('query_text', ''))
                self.num_images_entry.delete(0, tk.END)
                self.num_images_entry.insert(0, settings.get('num_images', '10'))
                
                self.img_size_combobox.set(settings.get('img_size', IMG_SIZE_OPTIONS[0]))
                self.img_type_combobox.set(settings.get('img_type', IMG_TYPE_OPTIONS[0]))
                self.img_color_type_combobox.set(settings.get('img_color_type', IMG_COLOR_TYPE_OPTIONS[0]))
                self.file_type_combobox.set(settings.get('file_type', FILE_TYPE_OPTIONS[0]))
                self.safe_search_combobox.set(settings.get('safe_search', SAFE_SEARCH_OPTIONS[0]))
                
                self.save_dir_entry.delete(0, tk.END)
                self.save_dir_entry.insert(0, settings.get('save_directory', os.getcwd())) # Default to current working directory
            self.log("Settings loaded from config.ini", "info")
        except Exception as e:
            self.log(f"Error loading settings: {e}", "warning")

    # --- GUI Setup ---

    def setup_gui(self):
        """Builds the entire graphical user interface."""
        self.root.title("Modern Image Search")
        self.root.geometry("950x700")
        self.root.configure(bg=COLORS["bg_dark"]) # Changed to bg_dark for overall dark theme
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Styles ---
        style = ttk.Style()
        style.theme_use('clam')

        # General style for rounded corners and dark theme
        style.configure("RoundedFrame.TFrame", background=COLORS["bg_light"], relief="flat", borderwidth=0)
        style.configure("RoundedLabelFrame.TLabelframe", background=COLORS["bg_light"], foreground=COLORS["text_dark"], relief="flat", borderwidth=0)
        style.configure("RoundedLabelFrame.TLabelframe.Label", background=COLORS["bg_light"], foreground=COLORS["text_dark"])

        style.configure("TProgressbar", thickness=25, troughcolor=COLORS["bg_dark"], background=COLORS["primary"], borderwidth=0, relief="flat")
        style.configure("TCombobox", fieldbackground=COLORS["bg_dark"], background=COLORS["bg_dark"], foreground=COLORS["text_dark"], arrowcolor=COLORS["primary"], selectbackground=COLORS["primary_dark"], selectforeground="white", borderwidth=0, relief="flat")
        style.map('TCombobox', fieldbackground=[('readonly', COLORS["bg_dark"])])

        # Style for buttons to have rounded appearance
        style.configure("TButton",
                        background=COLORS["primary"],
                        foreground=COLORS["text_light"],
                        font=("Helvetica", 10, "bold"),
                        relief="flat",
                        borderwidth=0,
                        focusthickness=0,
                        focuscolor=COLORS["primary_dark"])
        style.map("TButton",
                  background=[('active', COLORS["primary_dark"])],
                  foreground=[('disabled', COLORS["text_dark"])])

        title_font = ("Helvetica", 16, "bold")
        heading_font = ("Helvetica", 12, "bold")
        normal_font = ("Helvetica", 10)

        # --- Main Layout ---
        main_frame = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=20, pady=20) # Changed to bg_dark
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Image Search & Download", font=title_font, bg=COLORS["bg_dark"], fg=COLORS["primary"]).pack(pady=(0, 15)) # Changed to bg_dark

        left_panel = tk.Frame(main_frame, bg=COLORS["bg_dark"], padx=10, pady=10) # Changed to bg_dark
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_panel = tk.Frame(main_frame, bg=COLORS["bg_dark"], padx=10, pady=10, width=300) # Already bg_dark
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        right_panel.pack_propagate(False)

        # --- Search Queries ---
        query_frame = tk.LabelFrame(left_panel, text="Search Queries", font=heading_font, bg=COLORS["bg_light"], fg=COLORS["text_dark"], padx=10, pady=10, relief="flat", borderwidth=0) # Changed bg and added relief/borderwidth
        query_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        tk.Label(query_frame, text="Enter search queries (one per line):", bg=COLORS["bg_light"], fg=COLORS["text_dark"], font=normal_font).pack(anchor=tk.W, pady=(5, 5))
        self.query_text = scrolledtext.ScrolledText(query_frame, width=50, height=8, font=normal_font, bg=COLORS["bg_dark"], fg=COLORS["text_light"], insertbackground=COLORS["text_light"], relief="flat", borderwidth=0) # Changed bg/fg/insertbackground/relief/borderwidth
        self.query_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # --- Settings ---
        settings_frame = tk.LabelFrame(left_panel, text="Settings", font=heading_font, bg=COLORS["bg_light"], fg=COLORS["text_dark"], padx=10, pady=10, relief="flat", borderwidth=0) # Changed bg and added relief/borderwidth
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        # --- Number of Images ---
        num_images_frame = tk.Frame(settings_frame, bg=COLORS["bg_light"]) # Changed bg
        num_images_frame.pack(fill=tk.X, pady=5)
        tk.Label(num_images_frame, text="Images per query (1-10):", bg=COLORS["bg_light"], fg=COLORS["text_dark"], font=normal_font, width=25, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 10))
        self.num_images_entry = tk.Entry(num_images_frame, font=normal_font, bg=COLORS["bg_dark"], fg=COLORS["text_light"], insertbackground=COLORS["text_light"], relief="flat", borderwidth=0) # Changed bg/fg/insertbackground/relief/borderwidth
        self.num_images_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.num_images_entry.insert(0, "10")

        # --- Filter Dropdowns ---
        self.img_size_combobox = self.create_filter_dropdown(settings_frame, "Image Size:", IMG_SIZE_OPTIONS)
        self.img_type_combobox = self.create_filter_dropdown(settings_frame, "Image Type:", IMG_TYPE_OPTIONS)
        self.img_color_type_combobox = self.create_filter_dropdown(settings_frame, "Image Color Type:", IMG_COLOR_TYPE_OPTIONS)
        self.file_type_combobox = self.create_filter_dropdown(settings_frame, "File Type:", FILE_TYPE_OPTIONS)
        self.safe_search_combobox = self.create_filter_dropdown(settings_frame, "Safe Search:", SAFE_SEARCH_OPTIONS)

        # --- Save Directory ---
        save_dir_frame = tk.Frame(settings_frame, bg=COLORS["bg_light"]) # Changed bg
        save_dir_frame.pack(fill=tk.X, pady=5)
        tk.Label(save_dir_frame, text="Save directory:", bg=COLORS["bg_light"], fg=COLORS["text_dark"], font=normal_font, width=25, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 10))
        self.save_dir_entry = tk.Entry(save_dir_frame, font=normal_font, bg=COLORS["bg_dark"], fg=COLORS["text_light"], insertbackground=COLORS["text_light"], relief="flat", borderwidth=0) # Changed bg/fg/insertbackground/relief/borderwidth
        self.save_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(save_dir_frame, text="Browse", command=self.select_directory).pack(side=tk.LEFT) # Changed to ttk.Button for styling

        # --- Control Buttons ---
        control_frame = tk.Frame(left_panel, bg=COLORS["bg_dark"], pady=10) # Changed to bg_dark
        control_frame.pack(fill=tk.X)
        self.search_button = ttk.Button(control_frame, text="Search and Save Images", command=self.on_search) # Changed to ttk.Button
        self.search_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self.pause_button = ttk.Button(control_frame, text="Pause", state=tk.DISABLED, command=self.on_pause) # Changed to ttk.Button
        self.pause_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        self.stop_button = ttk.Button(control_frame, text="Stop", state=tk.DISABLED, command=self.on_stop) # Changed to ttk.Button
        self.stop_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        # --- Progress Indicator ---
        progress_frame = tk.Frame(left_panel, bg=COLORS["bg_dark"], pady=5) # Changed to bg_dark
        progress_frame.pack(fill=tk.X)
        self.status_label = tk.Label(progress_frame, text="Status: Ready", font=normal_font, bg=COLORS["bg_dark"], fg=COLORS["primary"]) # Changed to bg_dark
        self.status_label.pack(anchor=tk.W, pady=(0, 5))
        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", length=400, mode="determinate", style="TProgressbar")
        self.progress.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(progress_frame, text="Open Save Location", command=self.open_save_location).pack(anchor=tk.E) # Changed to ttk.Button

        # --- Output Log ---
        output_frame = tk.LabelFrame(left_panel, text="Log", font=heading_font, bg=COLORS["bg_light"], fg=COLORS["text_dark"], padx=10, pady=10, relief="flat", borderwidth=0) # Changed bg and added relief/borderwidth
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.output_text = scrolledtext.ScrolledText(output_frame, width=80, height=12, font=("Consolas", 9), bg=COLORS["bg_dark"], fg=COLORS["text_light"], insertbackground=COLORS["text_light"], relief="flat", borderwidth=0) # Changed bg/fg/insertbackground/relief/borderwidth
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.tag_configure("success", foreground=COLORS["secondary"])
        self.output_text.tag_configure("error", foreground=COLORS["accent"])
        self.output_text.tag_configure("warning", foreground="#f39c12") # Keep orange for warning
        self.output_text.tag_configure("info", foreground=COLORS["primary"])
        self.output_text.tag_configure("heading", foreground="#9b59b6", font=("Consolas", 9, "bold")) # Keep purple for heading

        # --- Preview Area ---
        preview_frame = tk.LabelFrame(right_panel, text="Image Preview", font=heading_font, bg=COLORS["bg_light"], fg=COLORS["text_dark"], padx=10, pady=10, relief="flat", borderwidth=0) # Changed bg and added relief/borderwidth
        preview_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_label = tk.Label(preview_frame, text="Preview will appear here", bg=COLORS["bg_dark"], fg=COLORS["text_light"], width=30, height=15, relief="flat", borderwidth=0) # Changed bg/fg and added relief/borderwidth
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        tk.Label(right_panel, text="Google Custom Search Image Downloader", font=("Helvetica", 8), bg=COLORS["bg_dark"], fg=COLORS["text_light"]).pack(side=tk.BOTTOM, pady=10) # Already bg_dark

        # --- Initial Instructions ---
        self.log("🔎 Welcome to the Modern Image Search Tool!", "heading")
        self.log("• Enter search terms (one per line)", "info")
        self.log("• Set images per query (API max is 10)", "info")
        self.log("• Choose a save directory and click 'Browse'", "info")
        self.log("• Click 'Search and Save Images' to begin", "info")

    def create_filter_dropdown(self, parent, label_text, options_list):
        """Helper to create a labeled combobox for filters."""
        frame = tk.Frame(parent, bg=COLORS["bg_light"]) # Changed bg
        frame.pack(fill=tk.X, pady=2)
        tk.Label(frame, text=label_text, bg=COLORS["bg_light"], fg=COLORS["text_dark"], font=("Helvetica", 10), width=25, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 10))
        combobox = ttk.Combobox(frame, values=options_list, font=("Helvetica", 10), state="readonly", width=10) # Reduced width to 10
        combobox.current(0)
        combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return combobox

if __name__ == "__main__":
    if not os.getenv("API_KEY") or not os.getenv("CSE_ID"):
        messagebox.showerror("Configuration Error", "API_KEY or CSE_ID not found.\nPlease create a .env file with these values.")
    else:
        root = tk.Tk()
        app = ImageSearchApp(root)
        root.mainloop()
