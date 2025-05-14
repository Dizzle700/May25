import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import os
import sys
import platform
import subprocess
import sqlite3
import hashlib
import threading
import logging
import configparser
import json
from queue import Queue
from typing import List, Tuple, Optional, Dict, Any
import time
from datetime import datetime
import numpy as np
from PIL import Image, ImageTk
import imagehash
import torch
from transformers import AutoProcessor, AutoModel
from sklearn.metrics.pairwise import cosine_similarity
from collections import OrderedDict

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("WARNING: Faiss library not found. Similarity search will be slow. Install with 'pip install faiss-cpu'")

import sv_ttk  # Modern theme for tkinter

# --- Constants ---
DB_SCHEMA_VERSION = 3 # Increment this if schema changes significantly
CONFIG_VERSION = 2 # Increment this if config structure changes

class ImageScanner:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Image Scanner v3.1 (Faiss {'Enabled' if FAISS_AVAILABLE else 'Disabled'})")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Apply modern theme
        sv_ttk.set_theme("dark")

        # Initialize core attributes
        self.is_scanning = False
        self.stop_scan = False
        self.batch_queue = Queue()
        self.setup_logging()
        self.config = self.load_config() # Now returns the config object

        # Faiss related attributes
        self.faiss_index = None
        self.faiss_id_map: Dict[int, int] = {} # Maps faiss index pos -> db image id
        self.faiss_index_path = "image_index.faiss"
        self.faiss_map_path = "image_index_map.json"
        self.faiss_dimension = 512 # CLIP base model dimension
        self.faiss_lock = threading.Lock() if FAISS_AVAILABLE else None

        # Database setup (after config)
        self.conn = None # Initialize conn to None
        self.db_path = "" # Initialize db_path
        self.setup_db_connection()

        # Image processor setup (after config, before faiss build)
        self.processor = None
        self.model = None
        self.image_processor_ready = self.setup_image_processor()

        # Load/Build Faiss Index (after DB and model)
        if FAISS_AVAILABLE and self.image_processor_ready:
            self._load_or_build_faiss_index()
        elif not FAISS_AVAILABLE:
             self.log_message("Faiss not installed, similarity search will be slow.", "warning")
        elif not self.image_processor_ready:
             self.log_message("Image processor failed to load, similarity search disabled.", "warning")


        # Cache for image vectors (LRU)
        self.max_cache_size = int(self.config.get('PROCESSING', 'cache_size', fallback='500'))
        self.vector_cache = OrderedDict()

        # GUI
        self.setup_gui()
        self.log_message("Application initialized.")
        if not self.image_processor_ready:
            self.log_message("WARNING: CLIP model failed to load. Vector similarity features disabled.", "error")


    def setup_logging(self):
        """Configure logging with file and console output"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        # Prevent duplicate handlers if re-initialized
        if not self.logger.hasHandlers():
            fh = logging.FileHandler('image_scanner.log', encoding='utf-8')
            ch = logging.StreamHandler(sys.stdout) # Use sys.stdout
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)
            self.logger.addHandler(fh)
            self.logger.addHandler(ch)

    def load_config(self) -> configparser.ConfigParser:
        """Load configuration with default values, version check, and error handling"""
        config = configparser.ConfigParser()
        config_file = 'config.ini'

        default_config = {
            'GENERAL': {
                'config_version': str(CONFIG_VERSION)
            },
            'DATABASE': {
                'db_path': 'image_db.sqlite',
                'db_schema_version': str(DB_SCHEMA_VERSION)
            },
            'PROCESSING': {
                'batch_size': '50',
                'max_workers': '4', # Note: max_workers is defined but not explicitly used for threading pool
                'cache_size': '500',
                'similarity_threshold': '0.85',
                'faiss_search_k': '10' # Number of neighbours to retrieve from Faiss
            },
            'UI': {
                'theme': 'dark',
                'log_max_lines': '1000'
            }
        }

        try:
            if os.path.exists(config_file):
                config.read(config_file)
                # Basic version check (can be expanded)
                if int(config.get('GENERAL', 'config_version', fallback='0')) < CONFIG_VERSION:
                     self.log_message("Config file is outdated. Backing up and creating new one.", "warning")
                     os.rename(config_file, config_file + ".bak")
                     config = configparser.ConfigParser() # Reset config
                     config.read_dict(default_config)
                     with open(config_file, 'w') as cf:
                        config.write(cf)
                else:
                    # Ensure all sections/keys exist, adding defaults if missing
                    for section, values in default_config.items():
                        if not config.has_section(section):
                            config.add_section(section)
                        for key, value in values.items():
                            if not config.has_option(section, key):
                                config.set(section, key, value)

            else:
                self.log_message("Config file not found. Creating default config.ini.", "info")
                config.read_dict(default_config)
                with open(config_file, 'w') as cf:
                    config.write(cf)

        except Exception as e:
            self.log_message(f"Config loading/validation failed: {e}. Using defaults.", "error")
            config = configparser.ConfigParser() # Reset config
            config.read_dict(default_config)

        return config


    def setup_db_connection(self) -> None:
        """Setup SQLite database connection and ensure schema is up-to-date"""
        try:
            db_path_cfg = self.config.get('DATABASE', 'db_path', fallback='image_db.sqlite')
            self.db_path = os.path.abspath(db_path_cfg)
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                self.log_message(f"Created database directory: {db_dir}", "info")

            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False, # Necessary for multi-threading
                isolation_level=None # Enable autocommit mode
            )
            self.conn.execute("PRAGMA journal_mode=WAL") # Write Ahead Logging for concurrency
            self.conn.execute("PRAGMA synchronous=NORMAL") # Slightly less durable, faster writes
            self.conn.execute("PRAGMA foreign_keys=ON") # Enforce foreign key constraints

            # Check and potentially upgrade schema
            self._check_db_schema()

            self.log_message(f"Database connected: {self.db_path}", "info")

        except sqlite3.Error as e:
            self.log_message(f"Database connection error to {self.db_path}: {e}", "error")
            messagebox.showerror("Database Error", f"Failed to connect to database: {e}\nApplication might not function correctly.")
            self.conn = None # Ensure conn is None if setup fails
        except Exception as e:
            self.log_message(f"Unexpected error during database setup: {e}", "error")
            messagebox.showerror("Setup Error", f"An unexpected error occurred during DB setup: {e}")
            self.conn = None


    def _check_db_schema(self):
        """Check current DB schema version and create/update tables."""
        if not self.conn: return

        try:
            cursor = self.conn.execute("PRAGMA user_version")
            current_version = cursor.fetchone()[0]
        except sqlite3.Error:
            current_version = 0 # Assume new database if user_version pragma fails

        if current_version < DB_SCHEMA_VERSION:
            self.log_message(f"Database schema outdated (Current: v{current_version}, Required: v{DB_SCHEMA_VERSION}). Updating...", "warning")
            # --- Migration Logic would go here ---
            # Example: If migrating from v1 to v2:
            # if current_version < 2:
            #     self.conn.execute("ALTER TABLE images ADD COLUMN new_column TEXT;")
            # if current_version < 3:
            #     # Add changes for v3
            #     pass

            # For this version, we just create tables if they don't exist
            self.create_tables() # Ensure tables exist

            # Update the schema version in the database
            self.conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
            self.log_message(f"Database schema updated to v{DB_SCHEMA_VERSION}.", "info")
        else:
             self.create_tables() # Still ensure tables exist even if version matches
             self.log_message(f"Database schema is up-to-date (v{DB_SCHEMA_VERSION}).", "info")


    def create_tables(self) -> None:
        """Create database tables if they don't exist."""
        if not self.conn: return
        try:
            with self.conn: # Use 'with' for transaction atomicity on creation
                # Use TEXT affinity for hashes, REAL for floats
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        format TEXT,
                        width INTEGER,
                        height INTEGER,
                        file_hash TEXT UNIQUE NOT NULL, -- Make file hash mandatory and unique
                        perceptual_hash TEXT,
                        absolute_path TEXT NOT NULL UNIQUE, -- Path should also be unique
                        relative_path TEXT,
                        image_vector BLOB, -- Store vectors as BLOB
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        last_scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'active' CHECK(status IN ('active', 'deleted', 'missing'))
                    )
                """)
                # Consider index on lower(absolute_path) if case-insensitive lookup needed often
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_file_hash ON images (file_hash)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_perceptual_hash ON images (perceptual_hash)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON images (absolute_path)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_last_scanned ON images (last_scanned_at)")

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS scan_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        folder_path TEXT,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        total_images_found INTEGER DEFAULT 0,
                        processed_files INTEGER DEFAULT 0,
                        new_files_added INTEGER DEFAULT 0,
                        similar_pairs_found INTEGER DEFAULT 0,
                        status TEXT CHECK(status IN ('running', 'completed', 'aborted', 'failed'))
                    )
                """)

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS similar_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        image1_id INTEGER NOT NULL,
                        image2_id INTEGER NOT NULL,
                        similarity_score REAL NOT NULL,
                        type TEXT CHECK(type IN ('vector', 'phash', 'exact')), -- Type of similarity
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (image1_id, image2_id), -- Prevent duplicate pairs
                        FOREIGN KEY (image1_id) REFERENCES images (id) ON DELETE CASCADE,
                        FOREIGN KEY (image2_id) REFERENCES images (id) ON DELETE CASCADE
                    )
                """)
                # Index for faster lookup of pairs involving a specific image
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_similar_image1 ON similar_images (image1_id)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_similar_image2 ON similar_images (image2_id)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_similarity_score ON similar_images (similarity_score DESC)")

        except sqlite3.Error as e:
            self.log_message(f"Table creation/verification error: {e}", "error")
            raise # Re-raise after logging


    def setup_image_processor(self) -> bool:
        """Setup CLIP model with error handling and optimization"""
        try:
            model_name = "openai/clip-vit-base-patch32"
            self.log_message(f"Loading image processor and model: {model_name}...", "info")
            self.processor = AutoProcessor.from_pretrained(model_name)
            self.model = AutoModel.from_pretrained(model_name)

            # Move model to GPU if available
            if torch.cuda.is_available():
                self.log_message("CUDA detected. Moving model to GPU.", "info")
                self.model = self.model.cuda()
            else:
                self.log_message("CUDA not detected. Using CPU for model inference.", "info")

            self.model.eval() # Set model to evaluation mode
            # Store dimension for Faiss
            self.faiss_dimension = self.model.config.projection_dim
            self.log_message(f"Image processor ready (Vector dimension: {self.faiss_dimension}).", "info")
            return True

        except Exception as e:
            self.log_message(f"FATAL: Image processor/model setup failed: {e}", "error")
            self.log_message("Vector generation and similarity search will be disabled.", "error")
            self.processor = None
            self.model = None
            return False

    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """L2 normalize vectors for cosine similarity using inner product."""
        if vectors.ndim == 1: # Handle single vector case
             vectors = vectors.reshape(1, -1)
        norm = np.linalg.norm(vectors, axis=1, keepdims=True)
        norm[norm == 0] = 1e-10 # Avoid division by zero
        return vectors / norm

    def _load_or_build_faiss_index(self):
        """Load Faiss index from disk or build it from the database."""
        if not FAISS_AVAILABLE or not self.conn or not self.image_processor_ready:
            self.log_message("Faiss index cannot be loaded or built (Dependencies missing or DB/Model error).", "warning")
            return

        if os.path.exists(self.faiss_index_path) and os.path.exists(self.faiss_map_path):
            try:
                self.log_message(f"Loading Faiss index from {self.faiss_index_path}...", "info")
                with self.faiss_lock:
                    self.faiss_index = faiss.read_index(self.faiss_index_path)
                    with open(self.faiss_map_path, 'r') as f:
                        # Convert JSON keys back to int
                        self.faiss_id_map = {int(k): v for k, v in json.load(f).items()}
                index_size = self.faiss_index.ntotal if self.faiss_index else 0
                map_size = len(self.faiss_id_map)
                if index_size != map_size:
                     self.log_message(f"Warning: Faiss index size ({index_size}) mismatch with map size ({map_size}). Rebuilding.", "warning")
                     self._build_faiss_index() # Rebuild if sizes mismatch
                else:
                     self.log_message(f"Faiss index loaded successfully ({index_size} vectors).", "info")

            except Exception as e:
                self.log_message(f"Failed to load Faiss index/map: {e}. Rebuilding...", "error")
                self._build_faiss_index()
        else:
            self.log_message("No existing Faiss index found. Building from database...", "info")
            self._build_faiss_index()

    def _build_faiss_index(self):
        """Builds the Faiss index from scratch using data from the database."""
        if not FAISS_AVAILABLE or not self.conn or not self.image_processor_ready or not self.faiss_lock:
             return # Cannot build

        self.log_message("Starting Faiss index build process...", "info")
        start_time = time.time()
        vectors = []
        ids = []
        try:
            cursor = self.conn.execute("SELECT id, image_vector FROM images WHERE image_vector IS NOT NULL AND status = 'active'")
            fetched_count = 0
            for row_id, vector_blob in cursor:
                 if vector_blob:
                     vec = np.frombuffer(vector_blob, dtype=np.float32)
                     # Verify dimension before adding
                     if vec.shape[0] == self.faiss_dimension:
                         vectors.append(vec)
                         ids.append(row_id)
                         fetched_count += 1
                     else:
                          self.log_message(f"Skipping vector for ID {row_id}: Incorrect dimension {vec.shape[0]}, expected {self.faiss_dimension}", "warning")


            if not vectors:
                self.log_message("No vectors found in database to build Faiss index.", "info")
                # Create an empty index if needed
                with self.faiss_lock:
                    self.faiss_index = faiss.IndexFlatIP(self.faiss_dimension) # IP = Inner Product (for Cosine Sim)
                    self.faiss_id_map = {}
                return

            vectors_np = np.array(vectors, dtype=np.float32)
            normalized_vectors = self._normalize_vectors(vectors_np)

            self.log_message(f"Building Faiss index with {len(ids)} vectors...", "info")
            with self.faiss_lock:
                # Using IndexFlatIP requires normalized vectors for cosine similarity
                self.faiss_index = faiss.IndexFlatIP(self.faiss_dimension)
                self.faiss_index.add(normalized_vectors)
                # Create the mapping from the Faiss index position (0 to N-1) to the database ID
                self.faiss_id_map = {i: db_id for i, db_id in enumerate(ids)}

            end_time = time.time()
            self.log_message(f"Faiss index built successfully in {end_time - start_time:.2f} seconds ({self.faiss_index.ntotal} vectors).", "info")

            # Optionally save the newly built index immediately
            # self._save_faiss_index()

        except sqlite3.Error as e:
            self.log_message(f"Database error during Faiss index build: {e}", "error")
        except Exception as e:
            self.log_message(f"Unexpected error during Faiss index build: {e}", "error")
            # Reset index state if build fails
            with self.faiss_lock:
                self.faiss_index = None
                self.faiss_id_map = {}


    def _save_faiss_index(self):
        """Save the current Faiss index and ID map to disk."""
        if not FAISS_AVAILABLE or not self.faiss_lock: return

        with self.faiss_lock: # Ensure exclusive access while saving
            if self.faiss_index is not None and self.faiss_id_map is not None:
                try:
                    self.log_message(f"Saving Faiss index ({self.faiss_index.ntotal} vectors) to {self.faiss_index_path}...", "info")
                    faiss.write_index(self.faiss_index, self.faiss_index_path)
                    with open(self.faiss_map_path, 'w') as f:
                        json.dump(self.faiss_id_map, f)
                    self.log_message("Faiss index and map saved successfully.", "info")
                except Exception as e:
                    self.log_message(f"Error saving Faiss index or map: {e}", "error")
            else:
                 self.log_message("Faiss index or map is empty, nothing to save.", "info")

    def setup_gui(self) -> None:
        """Setup enhanced GUI with modern controls and similarity view"""
        self.root.geometry('1000x750') # Slightly larger default size
        self.root.minsize(800, 600)

        # Create main container with padding
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Control Section ---
        self.control_section = ttk.Frame(self.main_frame)
        self.control_section.pack(fill=tk.X, pady=(0, 10))

        # Folder selection frame
        self.folder_frame = ttk.LabelFrame(self.control_section, text="Scan Directory", padding=10)
        self.folder_frame.pack(fill=tk.X, pady=5)
        self.folder_path = tk.StringVar()
        ttk.Entry(self.folder_frame, textvariable=self.folder_path, width=80).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(self.folder_frame, text="Browse", command=self.browse_folder).pack(side=tk.RIGHT) # Removed style, sv_ttk handles it

        # Control buttons frame
        self.control_buttons_frame = ttk.Frame(self.control_section)
        self.control_buttons_frame.pack(fill=tk.X, pady=5)

        self.scan_btn = ttk.Button(self.control_buttons_frame, text="Start Scan", command=self.start_scan, style='Accent.TButton')
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_btn = ttk.Button(self.control_buttons_frame, text="Stop Scan", command=self.stop_scanning, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Missing Files Button (initially disabled)
        self.check_files_btn = ttk.Button(self.control_buttons_frame, text="Check Missing Files", command=self.check_missing_files, state=tk.DISABLED)
        self.check_files_btn.pack(side=tk.LEFT, padx=5)
        # TODO: Enable check_files_btn after implementing the function


        # Options frame
        self.options_frame = ttk.LabelFrame(self.control_buttons_frame, text="Options", padding=5)
        self.options_frame.pack(side=tk.LEFT, padx=10, fill=tk.X)

        self.similarity_threshold = tk.DoubleVar(value=float(self.config.get('PROCESSING', 'similarity_threshold', fallback='0.85')))
        ttk.Label(self.options_frame, text="Similarity Threshold:").pack(side=tk.LEFT, padx=(0, 5))
        self.similarity_slider = ttk.Scale(self.options_frame, from_=0.5, to=1.0, variable=self.similarity_threshold, orient=tk.HORIZONTAL, length=150, command=self._update_threshold_display)
        self.similarity_slider.pack(side=tk.LEFT, padx=(0, 5))
        self.threshold_display = tk.StringVar(value=f"{self.similarity_threshold.get():.2f}")
        ttk.Label(self.options_frame, textvariable=self.threshold_display, width=4).pack(side=tk.LEFT)


        # Status indicators (right aligned)
        self.status_frame = ttk.Frame(self.control_buttons_frame)
        self.status_frame.pack(side=tk.RIGHT, padx=5)
        self.status_label = ttk.Label(self.status_frame, text="Idle", font=("", 10, "bold"), anchor=tk.E)
        self.status_label.pack(side=tk.RIGHT)


        # --- Progress Section ---
        self.progress_frame = ttk.LabelFrame(self.control_section, text="Scan Progress", padding=5)
        self.progress_frame.pack(fill=tk.X, pady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)

        self.stats_frame = ttk.Frame(self.progress_frame)
        self.stats_frame.pack(fill=tk.X, padx=5)
        self.stats_processed = ttk.Label(self.stats_frame, text="Processed: 0/0", width=20)
        self.stats_processed.pack(side=tk.LEFT, padx=(0, 10))
        self.stats_new = ttk.Label(self.stats_frame, text="New: 0", width=15)
        self.stats_new.pack(side=tk.LEFT, padx=(0, 10))
        self.stats_similar = ttk.Label(self.stats_frame, text="Similar Pairs: 0", width=20)
        self.stats_similar.pack(side=tk.LEFT, padx=(0, 10))
        self.stats_speed = ttk.Label(self.stats_frame, text="Speed: 0.0 img/sec", width=20)
        self.stats_speed.pack(side=tk.LEFT)

        # --- Paned Window (Log and Similar Images) ---
        self.paned_window = ttk.PanedWindow(self.main_frame, orient=tk.VERTICAL) # Changed to Vertical split
        self.paned_window.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Similar images section (Top Pane)
        self.similar_frame_outer = ttk.LabelFrame(self.paned_window, text="Similar Images Found (During Scan)", padding=5)
        self.paned_window.add(self.similar_frame_outer, weight=3) # Give more weight initially

        # Create a frame for the similar images with scrollbar
        self.similar_container = ttk.Frame(self.similar_frame_outer)
        self.similar_container.pack(fill=tk.BOTH, expand=True)
        self.similar_canvas = tk.Canvas(self.similar_container, highlightthickness=0) # Removed border
        self.similar_scrollbar_y = ttk.Scrollbar(self.similar_container, orient=tk.VERTICAL, command=self.similar_canvas.yview)
        self.similar_scrollbar_x = ttk.Scrollbar(self.similar_container, orient=tk.HORIZONTAL, command=self.similar_canvas.xview)
        self.similar_canvas.configure(yscrollcommand=self.similar_scrollbar_y.set, xscrollcommand=self.similar_scrollbar_x.set)

        self.similar_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.similar_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.similar_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Create a frame inside the canvas for the image pairs
        self.similar_images_frame = ttk.Frame(self.similar_canvas)
        self.similar_canvas_window = self.similar_canvas.create_window((0, 0), window=self.similar_images_frame, anchor=tk.NW)

        # Configure canvas scrolling
        self.similar_images_frame.bind("<Configure>", lambda e: self.similar_canvas.configure(scrollregion=self.similar_canvas.bbox("all")))
        self.similar_canvas.bind_all("<MouseWheel>", self._on_mousewheel) # Bind mouse wheel globally


        # Log section (Bottom Pane)
        self.log_frame = ttk.LabelFrame(self.paned_window, text="Log", padding=5)
        self.paned_window.add(self.log_frame, weight=1) # Less weight

        self.log_text = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, height=10, font=("Consolas", 9) if platform.system() == "Windows" else ("Monaco", 10), relief=tk.FLAT)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # Configure tags for log levels
        self.log_text.tag_configure("info", foreground="grey")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("error", foreground="#FF6B6B") # Use hex for better control
        self.log_text.tag_configure("critical", foreground="red", font=("", 9, "bold"))
        self.log_text.tag_configure("similar", foreground="#4EC9B0") # Teal color
        self.log_text.tag_configure("debug", foreground="purple") # For potential debug messages
        self.log_text.tag_configure("timestamp", foreground="#777777") # Dim timestamp

        # Dictionary to store image references (to prevent garbage collection)
        self.image_references = {}
        self.similar_pair_widgets = {} # Track widgets associated with a pair ID

        # --- Status Bar ---
        self.status_bar = ttk.Frame(self.main_frame, padding=(5, 2))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.db_status_label = ttk.Label(self.status_bar, text=f"DB: {os.path.basename(self.db_path) if self.db_path else 'N/A'}", anchor=tk.W)
        self.db_status_label.pack(side=tk.LEFT)
        # Consider adding Faiss status here
        self.faiss_status_label = ttk.Label(self.status_bar, text=f"Faiss: {'Ready' if FAISS_AVAILABLE and self.faiss_index else ('Disabled' if not FAISS_AVAILABLE else 'Not Loaded')}", anchor=tk.W)
        self.faiss_status_label.pack(side=tk.LEFT, padx=(10, 0))
        self.version_label = ttk.Label(self.status_bar, text="v3.1", anchor=tk.E)
        self.version_label.pack(side=tk.RIGHT)

    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling, directing to the correct canvas."""
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None: return

        # Check if the scroll event is over the similar_canvas or its children
        is_over_similar = False
        w = widget
        while w is not None:
            if w == self.similar_canvas:
                is_over_similar = True
                break
            w = w.master

        if is_over_similar:
            # Scroll similar_canvas vertically
            delta = -1 * (event.delta // 120) # Windows/macOS delta convention
            if platform.system() == 'Linux': # Handle Linux button 4/5
                 if event.num == 4: delta = -1
                 elif event.num == 5: delta = 1
                 else: delta = 0

            self.similar_canvas.yview_scroll(delta, "units")
        # Add elif for log_text if it has issues, but ScrolledText usually handles it
        # elif widget == self.log_text or widget.master == self.log_text:
        #     # ScrolledText should handle this automatically
        #     pass


    def _update_threshold_display(self, *args):
        """Updates the label next to the similarity slider."""
        self.threshold_display.set(f"{self.similarity_threshold.get():.2f}")


    def open_image(self, path):
        """Open image using default system viewer, robustly."""
        try:
            if not os.path.exists(path):
                self.log_message(f"Cannot open image: File not found at {path}", "error")
                messagebox.showerror("File Not Found", f"The image file could not be found:\n{path}")
                return

            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', path], check=True)
            else:  # Linux and other Unix-like
                subprocess.run(['xdg-open', path], check=True)
        except FileNotFoundError:
             self.log_message(f"Cannot open image: Command not found (e.g., 'open' or 'xdg-open'). Is it installed?", "error")
             messagebox.showerror("Error", "Could not find the command to open the image. Please ensure 'open' (macOS) or 'xdg-open' (Linux) is available.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error opening image '{path}' with system viewer: {e}", "error")
            messagebox.showerror("Error", f"Failed to open the image using the system viewer:\n{e}")
        except Exception as e:
            self.log_message(f"Unexpected error opening image '{path}': {e}", "error")
            messagebox.showerror("Error", f"An unexpected error occurred while trying to open the image:\n{e}")

    def browse_folder(self) -> None:
        """Open folder selection dialog."""
        initial_dir = os.path.expanduser("~")
        # Use last selected folder if available
        last_folder = self.folder_path.get()
        if last_folder and os.path.isdir(last_folder):
             initial_dir = last_folder

        folder = filedialog.askdirectory(initialdir=initial_dir, title="Select Folder to Scan")
        if folder:
            self.folder_path.set(folder)
            self.log_message(f"Selected folder: {folder}", "info")

    def log_message(self, message: str, level="info") -> None:
        """Log message to logger and update GUI log text."""
        timestamp = datetime.now().strftime("%H:%M:%S") # Shorter timestamp for GUI

        # Log to file/console via logger
        if level == "debug": self.logger.debug(message)
        elif level == "info": self.logger.info(message)
        elif level == "warning": self.logger.warning(message)
        elif level == "error": self.logger.error(message)
        elif level == "critical": self.logger.critical(message)
        elif level == "similar": self.logger.info(message) # Log similar findings as info
        else: self.logger.info(message) # Default to info

        # Schedule GUI update
        def update_gui():
            try:
                # Apply tag based on message level for color coding
                tag = level if level in ["warning", "error", "critical", "similar", "debug"] else "info"

                self.log_text.configure(state=tk.NORMAL) # Enable writing
                self.log_text.insert(tk.END, f"[{timestamp}] ", ("timestamp",))
                self.log_text.insert(tk.END, f"{message}\n", (tag,))
                self.log_text.see(tk.END) # Scroll to the end
                self.log_text.configure(state=tk.DISABLED) # Disable writing (read-only)

                # Limit log size in GUI
                max_lines = int(self.config.get('UI', 'log_max_lines', fallback='1000'))
                # More efficient line count and deletion
                num_lines = int(self.log_text.index('end-1c').split('.')[0])
                if num_lines > max_lines:
                    self.log_text.configure(state=tk.NORMAL)
                    self.log_text.delete('1.0', f'{num_lines - max_lines}.0')
                    self.log_text.configure(state=tk.DISABLED)
            except tk.TclError as e:
                # Handle cases where the widget might be destroyed during update
                self.logger.warning(f"GUI update failed (widget likely destroyed): {e}")
            except Exception as e:
                 self.logger.error(f"Unexpected error during GUI log update: {e}")


        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(0, update_gui)


    def get_image_vector(self, image_path: str) -> Optional[np.ndarray]:
        """Get image feature vector with caching and error handling."""
        if not self.image_processor_ready or self.processor is None or self.model is None:
             #self.log_message(f"Skipping vector generation for {os.path.basename(image_path)}: Image processor not ready.", "warning")
             return None # Cannot generate if model isn't loaded

        # Check cache first
        if image_path in self.vector_cache:
            # Move accessed item to the end (most recently used)
            self.vector_cache.move_to_end(image_path)
            #self.log_message(f"Vector cache hit for {os.path.basename(image_path)}", "debug")
            return self.vector_cache[image_path]

        # If not in cache, generate vector
        try:
            # Use context manager for image opening
            with Image.open(image_path) as image:
                # Ensure image is in RGB format for CLIP
                if image.mode != 'RGB':
                    image = image.convert('RGB')

                inputs = self.processor(images=image, return_tensors="pt", padding=True, truncation=True)

                # Move inputs to GPU if model is on GPU
                if next(self.model.parameters()).is_cuda:
                    inputs = {k: v.cuda() for k, v in inputs.items()}

                with torch.no_grad(): # Disable gradient calculation for inference
                    image_features = self.model.get_image_features(**inputs)

                # Move features back to CPU and convert to numpy
                vector = image_features.cpu().numpy()[0]

                # Add to cache and maintain cache size
                self.vector_cache[image_path] = vector
                if len(self.vector_cache) > self.max_cache_size:
                    self.vector_cache.popitem(last=False) # Remove least recently used

                return vector

        except FileNotFoundError:
             self.log_message(f"Error generating vector: File not found at {image_path}", "error")
             return None
        except UnidentifiedImageError: # Catch PIL specific error
             self.log_message(f"Error generating vector: Cannot identify image file {image_path}. May be corrupt or unsupported.", "error")
             return None
        except Exception as e:
            # Log detailed error, including image path
            self.log_message(f"Error generating vector for '{os.path.basename(image_path)}': {type(e).__name__} - {e}", "error")
            # Optionally log the full path for easier debugging if needed
            # self.logger.error(f"Full path with error: {image_path}")
            return None

    def calculate_file_hash(self, file_path: str) -> Optional[str]:
        """Calculate SHA-256 hash of file content."""
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                # Read in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
             self.log_message(f"Error calculating hash: File not found at {file_path}", "error")
             return None
        except OSError as e: # Catch potential OS errors like permission denied
             self.log_message(f"Error calculating hash for {file_path}: OS error - {e}", "error")
             return None
        except Exception as e:
            self.log_message(f"Unexpected error calculating hash for {file_path}: {e}", "error")
            return None


    def find_similar_images(self, current_image_id: int, image_vector: Optional[np.ndarray], file_hash: str, perceptual_hash: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Find similar images using Faiss (if available) or database scan.
        Checks for exact hash, perceptual hash, and vector similarity.

        Args:
            current_image_id: The database ID of the image being checked.
            image_vector: The feature vector of the current image (can be None).
            file_hash: The SHA256 hash of the current image.
            perceptual_hash: The perceptual hash (e.g., average hash) of the current image.
            file_path: The absolute path of the current image.

        Returns:
            A list of dictionaries, each representing a similar image found.
            Keys: 'id', 'path', 'score', 'type' ('exact', 'vector', 'phash')
        """
        similar_images_found: List[Dict[str, Any]] = []
        threshold = self.similarity_threshold.get()
        processed_pairs = set() # Keep track of (id1, id2) pairs to avoid duplicates like (A,B) and (B,A)

        def add_similar(img1_id, img2_id, score, sim_type, path=""):
            # Ensure order to avoid duplicates (smaller id first)
            id1, id2 = min(img1_id, img2_id), max(img1_id, img2_id)
            if (id1, id2, sim_type) in processed_pairs:
                 return # Already processed this pair type

            # Fetch path if not provided (needed for display)
            if not path and self.conn:
                try:
                    cursor = self.conn.execute("SELECT absolute_path FROM images WHERE id = ?", (img2_id,))
                    result = cursor.fetchone()
                    if result: path = result[0]
                    else: return # Cannot add if path lookup fails
                except sqlite3.Error as e:
                     self.log_message(f"DB error fetching path for ID {img2_id}: {e}", "error")
                     return

            similar_images_found.append({
                "id": img2_id,      # ID of the *similar* image
                "path": path,       # Path of the *similar* image
                "score": score,
                "type": sim_type
            })
            processed_pairs.add((id1, id2, sim_type))

        if not self.conn: return [] # Cannot proceed without DB

        try:
            # 1. Check for Exact Duplicates (File Hash)
            # Find *other* images with the same hash
            cursor = self.conn.execute(
                "SELECT id, absolute_path FROM images WHERE file_hash = ? AND id != ?",
                (file_hash, current_image_id)
            )
            for match_id, match_path in cursor:
                add_similar(current_image_id, match_id, 1.0, 'exact', match_path)

            # 2. Check Vector Similarity (using Faiss if available)
            if FAISS_AVAILABLE and self.faiss_index is not None and image_vector is not None and self.faiss_lock:
                 with self.faiss_lock: # Lock during search
                     if self.faiss_index.ntotal > 0: # Only search if index has items
                         k = min(int(self.config.get('PROCESSING', 'faiss_search_k', fallback='11')), self.faiss_index.ntotal) # Search for k neighbours (+1 for potential self)
                         if k > 0:
                             normalized_query_vector = self._normalize_vectors(image_vector.reshape(1, -1))

                             # Perform the search
                             # D = distances (inner products for IndexFlatIP), I = indices (positions in faiss index)
                             distances, indices = self.faiss_index.search(normalized_query_vector, k)

                             # Process results
                             for i in range(indices.shape[1]):
                                 faiss_idx = indices[0, i]
                                 if faiss_idx == -1: continue # Invalid index from Faiss search

                                 db_id = self.faiss_id_map.get(faiss_idx)
                                 similarity_score = distances[0, i] # Inner product is cosine similarity for normalized vectors

                                 # Ensure it's not the image itself and meets threshold
                                 if db_id is not None and db_id != current_image_id and similarity_score >= threshold:
                                     # Path needs to be fetched separately as Faiss only stores IDs
                                     add_similar(current_image_id, db_id, float(similarity_score), 'vector')


            # 3. Fallback/Alternative: Perceptual Hash Similarity (if Faiss not used or desired)
            # This part can be computationally intensive if done across the whole DB.
            # Consider adding an option to enable/disable this.
            # For now, we'll skip the broad p-hash check if Faiss was used,
            # unless specifically required. If Faiss is *not* available,
            # a p-hash check might be a useful fallback, but it's slow.
            # Example (if you want to add it):
            # if not FAISS_AVAILABLE and perceptual_hash:
            #    phash_threshold = 10 # Example Hamming distance threshold
            #    cursor = self.conn.execute("SELECT id, absolute_path, perceptual_hash FROM images WHERE perceptual_hash IS NOT NULL AND id != ?", (current_image_id,))
            #    current_phash_obj = imagehash.hex_to_hash(perceptual_hash)
            #    for match_id, match_path, db_phash_str in cursor:
            #        if db_phash_str:
            #            db_phash_obj = imagehash.hex_to_hash(db_phash_str)
            #            hamming_distance = current_phash_obj - db_phash_obj
            #            if hamming_distance <= phash_threshold:
            #                # Score could be inverse distance, e.g., 1.0 - (hamming_distance / 64.0)
            #                phash_score = max(0.0, 1.0 - (hamming_distance / 64.0)) # Normalize score roughly
            #                add_similar(current_image_id, match_id, phash_score, 'phash', match_path)


        except sqlite3.Error as e:
            self.log_message(f"Database error finding similar images for {file_path}: {e}", "error")
        except Exception as e:
            self.log_message(f"Unexpected error finding similar images for {file_path}: {e}", "error")
            # If Faiss error occurs, log it specifically
            if FAISS_AVAILABLE and "faiss" in str(e).lower():
                self.log_message(f"Faiss search error: {e}", "error")

        # Sort by score descending before returning
        similar_images_found.sort(key=lambda x: x["score"], reverse=True)
        return similar_images_found


    def process_image(self, file_path: str, relative_path: str) -> Tuple[Optional[int], List[Dict]]:
        """
        Process a single image: calculate hashes, vector, check DB, and find similar.
        Returns the database ID of the processed image (new or existing) and list of similar images found.
        """
        if not self.conn: return None, []

        similar_images_found = []
        db_image_id = None

        try:
            # 1. Basic File Info & Hash Calculation
            file_size = os.path.getsize(file_path)
            file_hash = self.calculate_file_hash(file_path)
            if not file_hash:
                self.log_message(f"Skipping {file_path}: Failed to calculate file hash.", "warning")
                return None, [] # Cannot proceed without hash

            # 2. Check if image (by hash) already exists in DB
            cursor = self.conn.execute("SELECT id, last_scanned_at FROM images WHERE file_hash = ?", (file_hash,))
            existing_image = cursor.fetchone()

            current_timestamp = datetime.now().isoformat(sep=' ', timespec='seconds')

            if existing_image:
                # Image exists, update last_scanned_at
                db_image_id = existing_image[0]
                self.conn.execute("UPDATE images SET last_scanned_at = ?, status = 'active' WHERE id = ?", (current_timestamp, db_image_id))
                #self.log_message(f"Image already in DB (ID: {db_image_id}): {os.path.basename(file_path)}. Updated scan time.", "debug")
                # Optionally, re-run similarity check for existing images if needed,
                # but typically done only for new images. For now, return empty list.
                # If re-check needed: Need vector and phash for existing image too.
                return db_image_id, [] # Return existing ID, no *new* similarities found *by this function call*
            else:
                # 3. New Image: Process fully (Metadata, Hashes, Vector)
                try:
                     with Image.open(file_path) as img:
                         width, height = img.size
                         format_name = img.format
                         # Perceptual Hash
                         try:
                             phash = str(imagehash.average_hash(img))
                         except Exception as phash_e:
                              self.log_message(f"Could not calculate perceptual hash for {file_path}: {phash_e}", "warning")
                              phash = None
                except UnidentifiedImageError:
                     self.log_message(f"Skipping {file_path}: Cannot identify image format.", "warning")
                     return None, []
                except Exception as img_e:
                     self.log_message(f"Error reading image metadata for {file_path}: {img_e}", "error")
                     return None, [] # Skip if basic image reading fails


                # Image Vector
                image_vector = self.get_image_vector(file_path)
                image_vector_blob = image_vector.tobytes() if image_vector is not None else None

                # 4. Insert New Image into Database
                image_data = (
                    os.path.basename(file_path), file_size, format_name, width, height,
                    file_hash, phash, file_path, relative_path, image_vector_blob,
                    current_timestamp, current_timestamp # created_at, last_scanned_at
                )

                try:
                     cursor = self.conn.execute("""
                        INSERT INTO images (
                            name, size, format, width, height,
                            file_hash, perceptual_hash, absolute_path, relative_path, image_vector,
                            created_at, last_scanned_at, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                     """, image_data)
                     db_image_id = cursor.lastrowid
                     #self.log_message(f"Added new image to DB (ID: {db_image_id}): {os.path.basename(file_path)}", "debug")
                     self.stats_new_count += 1 # Increment new count stat

                     # 5. Find Similar Images for the *newly added* image
                     if db_image_id is not None:
                         similar_images_found = self.find_similar_images(
                             current_image_id=db_image_id,
                             image_vector=image_vector,
                             file_hash=file_hash,
                             perceptual_hash=phash,
                             file_path=file_path
                         )

                         # 6. Store found similarities in the database
                         if similar_images_found:
                             similarity_data = [
                                 (min(db_image_id, sim['id']), max(db_image_id, sim['id']), sim['score'], sim['type'])
                                 for sim in similar_images_found
                             ]
                             # Use INSERT OR IGNORE to handle potential unique constraint violations gracefully
                             # This prevents errors if the reverse pair (e.g., B vs A) was somehow already inserted
                             self.conn.executemany("""
                                 INSERT OR IGNORE INTO similar_images
                                 (image1_id, image2_id, similarity_score, type)
                                 VALUES (?, ?, ?, ?)
                             """, similarity_data)
                             self.stats_similar_pairs_count += len(similarity_data) # Update pair count

                     # Return the new ID and the similarities found *for this new image*
                     return db_image_id, similar_images_found

                except sqlite3.IntegrityError as ie:
                     # This might happen if UNIQUE constraint on path or hash fails concurrently,
                     # although the initial check should prevent most hash collisions.
                     self.log_message(f"Database integrity error processing {file_path}: {ie}. Might be a race condition or duplicate path.", "error")
                     # Attempt to fetch the ID again in case it was inserted by another thread just now
                     cursor = self.conn.execute("SELECT id FROM images WHERE file_hash = ?", (file_hash,))
                     existing_image = cursor.fetchone()
                     if existing_image:
                         return existing_image[0], []
                     else:
                         return None, [] # Failed to insert or find
                except sqlite3.Error as dbe:
                    self.log_message(f"Database error inserting image {file_path}: {dbe}", "error")
                    return None, []


        except FileNotFoundError:
            # This might happen if file deleted between os.walk and processing
            self.log_message(f"Skipping {file_path}: File not found during processing.", "warning")
            return None, []
        except Exception as e:
            self.log_message(f"Unexpected error processing {file_path}: {type(e).__name__} - {e}", "error")
            import traceback
            self.logger.error(traceback.format_exc()) # Log stack trace for unexpected errors
            return None, []

        # Fallback return (should ideally not be reached)
        return db_image_id, similar_images_found


    def add_to_similar_tree(self, original_path: str, original_id: int, similar_images: List[Dict]) -> None:
        """Add similar image pair entries to the GUI with previews and actions."""
        if not similar_images or original_id is None:
            return

        # Use root.after to ensure GUI updates happen on the main thread
        self.root.after(0, self._update_similar_tree_gui, original_path, original_id, similar_images)

    def _update_similar_tree_gui(self, original_path: str, original_id: int, similar_images: List[Dict]):
        """Helper function to perform the actual GUI updates for similar pairs."""
        thumb_size = (120, 120) # Slightly larger thumbnails

        for sim_info in similar_images:
            sim_id = sim_info['id']
            sim_path = sim_info['path']
            sim_score = sim_info['score']
            sim_type = sim_info['type']

            # Create a unique identifier for the PAIR widget (order invariant)
            pair_key = tuple(sorted((original_id, sim_id))) + (sim_type,)
            if pair_key in self.similar_pair_widgets:
                 continue # Don't add the same pair widget twice

            # Format similarity score and type
            if sim_type == 'exact':
                score_formatted = "Exact Match"
            else:
                score_formatted = f"{sim_score*100:.1f}% ({sim_type})"

            # --- Create Widgets for the Pair ---
            try:
                # Frame for the entire pair row
                pair_frame = ttk.Frame(self.similar_images_frame, padding=5, style='Card.TFrame') # Use Card style if available
                pair_frame.pack(fill=tk.X, expand=True, pady=5, padx=5)
                self.similar_pair_widgets[pair_key] = pair_frame # Track the widget

                # --- Original Image Side ---
                original_frame = ttk.Frame(pair_frame)
                original_frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
                ttk.Label(original_frame, text="Original", font=("", 9, "bold")).pack(anchor=tk.CENTER, pady=(0, 3))
                orig_img_widget = self._create_image_widget(original_frame, original_path, thumb_size, f"orig_{original_id}_{sim_id}")
                if orig_img_widget:
                    orig_img_widget.pack(padx=5, pady=5)
                    # Buttons below original
                    orig_button_frame = ttk.Frame(original_frame)
                    orig_button_frame.pack(pady=(5,0))
                    ttk.Button(orig_button_frame, text="Open", width=8, command=lambda p=original_path: self.open_image(p)).pack(side=tk.LEFT, padx=2)
                    # Optional: Delete original button (use with caution)
                    # ttk.Button(orig_button_frame, text="Delete", width=8, style='Danger.TButton', command=lambda p=original_path, pk=pair_key: self.delete_image_action(p, original_id, pk)).pack(side=tk.LEFT, padx=2)


                # --- Similarity Info Column ---
                info_frame = ttk.Frame(pair_frame)
                info_frame.pack(side=tk.LEFT, padx=10, fill=tk.Y, anchor=tk.CENTER)
                ttk.Label(info_frame, text="Similarity", font=("", 9, "bold")).pack(pady=(0,3))
                ttk.Label(info_frame, text=score_formatted, anchor=tk.CENTER).pack(pady=2)
                # Add maybe paths here?
                ttk.Label(info_frame, text=f"{os.path.basename(original_path)}", wraplength=150, justify=tk.CENTER, foreground="grey").pack(pady=1)
                ttk.Label(info_frame, text=f"<->", font=("", 12, "bold")).pack(pady=1)
                ttk.Label(info_frame, text=f"{os.path.basename(sim_path)}", wraplength=150, justify=tk.CENTER, foreground="grey").pack(pady=1)


                # --- Similar Image Side ---
                similar_frame = ttk.Frame(pair_frame)
                similar_frame.pack(side=tk.LEFT, padx=(10, 0), fill=tk.Y) # Changed from RIGHT to LEFT
                ttk.Label(similar_frame, text="Similar Found", font=("", 9, "bold")).pack(anchor=tk.CENTER, pady=(0, 3))
                sim_img_widget = self._create_image_widget(similar_frame, sim_path, thumb_size, f"sim_{original_id}_{sim_id}")
                if sim_img_widget:
                    sim_img_widget.pack(padx=5, pady=5)
                    # Buttons below similar
                    sim_button_frame = ttk.Frame(similar_frame)
                    sim_button_frame.pack(pady=(5,0))
                    ttk.Button(sim_button_frame, text="Open", width=8, command=lambda p=sim_path: self.open_image(p)).pack(side=tk.LEFT, padx=2)
                    ttk.Button(sim_button_frame, text="Delete", width=8, style="Accent.TButton", command=lambda p=sim_path, sim_db_id=sim_id, pk=pair_key: self.delete_image_action(p, sim_db_id, pk)).pack(side=tk.LEFT, padx=2)


                # Update similar count displayed in stats
                # Note: self.stats_similar_pairs_count is updated when inserting to DB
                self.stats_similar.config(text=f"Similar Pairs: {self.stats_similar_pairs_count}")

                # Log the found pair
                log_level = "similar" if sim_type != 'exact' else "info"
                self.log_message(f"{score_formatted}: {os.path.basename(original_path)} <=> {os.path.basename(sim_path)}", level=log_level)

            except tk.TclError as e:
                 # Handle cases where the widget might be destroyed during update
                 self.logger.warning(f"GUI update for similar pair failed (widget likely destroyed): {e}")
            except Exception as e:
                self.log_message(f"Error creating similar image widget for {original_path} vs {sim_path}: {e}", level="error")
                import traceback
                self.logger.error(traceback.format_exc())


    def _create_image_widget(self, parent_frame, image_path: str, thumb_size: tuple, ref_key: str) -> Optional[ttk.Label]:
        """Loads, resizes, and creates a Label widget for an image preview."""
        try:
            img = Image.open(image_path)
            img.thumbnail(thumb_size, Image.Resampling.LANCZOS) # Use LANCZOS for better resize quality
            photo = ImageTk.PhotoImage(img)

            # Store reference to prevent garbage collection
            self.image_references[ref_key] = photo

            # Create label with image
            image_label = ttk.Label(parent_frame, image=photo, relief=tk.GROOVE, borderwidth=1)
            # Tooltip showing full path on hover
            # Requires an external tooltip library or custom implementation
            # Simple alternative: bind mouse enter/leave to update a status bar label
            def on_enter(e): self.status_bar.config(text=image_path)
            def on_leave(e): self.status_bar.config(text="") # Clear status bar
            # image_label.bind("<Enter>", on_enter)
            # image_label.bind("<Leave>", on_leave)
            return image_label

        except FileNotFoundError:
            self.log_message(f"Preview error: Image file not found at {image_path}", level="warning")
            # Return a placeholder label
            return ttk.Label(parent_frame, text="Not Found", relief=tk.GROOVE, borderwidth=1, width=thumb_size[0]//8, height=thumb_size[1]//16, anchor=tk.CENTER)
        except Exception as e:
            self.log_message(f"Error loading image preview for {image_path}: {e}", level="error")
            # Return a placeholder label
            return ttk.Label(parent_frame, text="Load Error", relief=tk.GROOVE, borderwidth=1, width=thumb_size[0]//8, height=thumb_size[1]//16, anchor=tk.CENTER)


    def delete_image_action(self, image_path: str, image_db_id: int, pair_key: tuple) -> None:
        """Handles the deletion process for an image, including file, DB, and GUI update."""
        if not self.conn:
             messagebox.showerror("Error", "Database connection not available.")
             return

        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to permanently delete this file?\n\n{image_path}\n\nThis action cannot be undone.",
            icon='warning'
        )

        if confirm:
            try:
                # 1. Delete the file from disk
                os.remove(image_path)
                self.log_message(f"Deleted file: {image_path}", level="warning")

                # 2. Update the database record status to 'deleted' (or remove)
                # Using 'deleted' status allows potential recovery or tracking
                with self.conn:
                    # Mark image as deleted
                    self.conn.execute("UPDATE images SET status = 'deleted', image_vector = NULL WHERE id = ?", (image_db_id,))
                    # Remove associated similarity pairs (handled by ON DELETE CASCADE if deleting row)
                    # If only updating status, manually delete pairs:
                    self.conn.execute("DELETE FROM similar_images WHERE image1_id = ? OR image2_id = ?", (image_db_id, image_db_id))

                # 3. Remove the corresponding widget from the GUI
                if pair_key in self.similar_pair_widgets:
                    widget_to_remove = self.similar_pair_widgets.pop(pair_key)
                    if widget_to_remove.winfo_exists():
                        widget_to_remove.destroy()
                    # Update layout
                    self.similar_canvas.configure(scrollregion=self.similar_canvas.bbox("all"))
                else:
                     self.log_message(f"Could not find widget for pair key {pair_key} to remove.", "warning")


                # 4. Optionally remove from Faiss index (requires rebuilding or selective removal if supported)
                # Simple approach: Rebuild index periodically or on next startup.
                # More complex: Track deleted IDs and filter results / remove from index directly if possible.
                # For now, we rely on the next rebuild/load to clean up the index.


                # Update stats (decrementing might be complex if pairs are shared, just refresh might be better)
                # self.stats_similar_pairs_count -= 1 # Approximate update
                # self.stats_similar.config(text=f"Similar Pairs: {self.stats_similar_pairs_count}")

                messagebox.showinfo("Deleted", f"Successfully deleted:\n{os.path.basename(image_path)}")

            except FileNotFoundError:
                self.log_message(f"Error deleting file {image_path}: Already deleted or moved.", level="error")
                messagebox.showerror("Delete Error", "File not found. It might have been already deleted.")
                 # Also mark as deleted in DB if file is gone
                with self.conn:
                     self.conn.execute("UPDATE images SET status = 'missing' WHERE id = ?", (image_db_id,))
            except OSError as e:
                self.log_message(f"Error deleting file {image_path}: {e}", level="error")
                messagebox.showerror("Delete Error", f"Could not delete file: {e}\nCheck permissions or if the file is in use.")
            except sqlite3.Error as e:
                self.log_message(f"Database error updating status for deleted image ID {image_db_id}: {e}", level="error")
                messagebox.showerror("Database Error", f"File deleted, but failed to update database record: {e}")
            except Exception as e:
                self.log_message(f"Unexpected error during deletion of {image_path}: {e}", level="error")
                messagebox.showerror("Error", f"An unexpected error occurred during deletion: {e}")


    def batch_faiss_updater(self):
        """Dedicated thread/task to update Faiss index periodically from a queue."""
        # This function is intended to run in a separate thread
        # It would pull (db_id, vector_blob) tuples from a queue populated after batch inserts
        # And add them to the Faiss index, protected by the faiss_lock.
        # For simplicity in this version, the update happens directly after the batch insert query
        # in the main `scan_images` loop logic, but a separate updater thread could be more robust
        # for very high insertion rates.
        pass # Placeholder for potential future implementation


    def scan_images(self) -> None:
        """Scan folder for images, process them, and update database/GUI."""
        folder_path = self.folder_path.get()
        if not folder_path or not os.path.isdir(folder_path): # Check if directory
            self.log_message("Invalid or no folder selected!", "error")
            self.cleanup_scan(status='failed')
            return

        if not self.conn:
             self.log_message("Database connection not available. Cannot start scan.", "error")
             self.cleanup_scan(status='failed')
             return

        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
        self.log_message(f"Starting scan of folder: {folder_path}", "info")
        self.log_message(f"Supported extensions: {', '.join(image_extensions)}", "info")

        # Find all image files first to get total count
        all_image_files = []
        try:
            for root, _, files in os.walk(folder_path):
                if self.stop_scan: break
                for filename in files:
                    if os.path.splitext(filename)[1].lower() in image_extensions:
                        all_image_files.append(os.path.join(root, filename))
            total_files = len(all_image_files)
        except Exception as e:
             self.log_message(f"Error during initial file discovery: {e}", "error")
             self.cleanup_scan(status='failed')
             return


        if total_files == 0:
            self.log_message("No images found in selected folder or subfolders.", "warning")
            self.cleanup_scan(status='completed') # Completed, but found nothing
            return

        # --- Scan Initialization ---
        start_time = time.time()
        scan_id = self.log_scan_start(folder_path, total_files)
        processed_files_count = 0
        self.stats_new_count = 0 # Reset scan-specific stats
        self.stats_similar_pairs_count = 0 # Reset scan-specific stats
        last_update_time = start_time
        faiss_updates_pending: List[Tuple[int, np.ndarray]] = [] # Collect vectors for Faiss update

        # Clear previous similar images view
        for widget in self.similar_images_frame.winfo_children():
            widget.destroy()
        self.image_references.clear()
        self.similar_pair_widgets.clear()
        self.similar_canvas.configure(scrollregion=self.similar_canvas.bbox("all")) # Reset scroll region


        # --- Main Scan Loop ---
        try:
            for file_path in all_image_files:
                if self.stop_scan:
                    self.log_message("Scan aborted by user.", "warning")
                    break

                relative_path = os.path.relpath(file_path, folder_path)

                # Process the image (includes DB check/insert, vector gen, similarity search)
                db_image_id, similar_images = self.process_image(file_path, relative_path)

                processed_files_count += 1

                # If new similarities were found for this image, display them
                if db_image_id is not None and similar_images:
                    self.add_to_similar_tree(file_path, db_image_id, similar_images)

                # If a *new* image was added and has a vector, queue it for Faiss update
                if db_image_id is not None and self.stats_new_count > 0 and FAISS_AVAILABLE and self.faiss_index is not None:
                    # We need the vector again (or ideally get it back from process_image)
                    # Let's re-fetch from cache/generate if needed for Faiss update
                    vec = self.get_image_vector(file_path)
                    if vec is not None:
                        faiss_updates_pending.append((db_image_id, vec))


                # --- Progress Update ---
                current_time = time.time()
                if current_time - last_update_time >= 1.0 or processed_files_count == total_files:
                    elapsed = current_time - start_time
                    images_per_second = processed_files_count / elapsed if elapsed > 0 else 0
                    self.update_progress(processed_files_count, total_files, self.stats_new_count, self.stats_similar_pairs_count, images_per_second)
                    last_update_time = current_time

            # --- Post-Scan Faiss Update ---
            if FAISS_AVAILABLE and self.faiss_index is not None and faiss_updates_pending and self.faiss_lock:
                 self.log_message(f"Adding {len(faiss_updates_pending)} new vectors to Faiss index...", "info")
                 new_vectors_np = np.array([item[1] for item in faiss_updates_pending], dtype=np.float32)
                 normalized_new_vectors = self._normalize_vectors(new_vectors_np)
                 new_db_ids = [item[0] for item in faiss_updates_pending]

                 with self.faiss_lock:
                     start_faiss_pos = self.faiss_index.ntotal
                     self.faiss_index.add(normalized_new_vectors)
                     # Update the map: new Faiss positions map to the new DB IDs
                     for i, db_id in enumerate(new_db_ids):
                         self.faiss_id_map[start_faiss_pos + i] = db_id
                 self.log_message(f"Finished adding vectors to Faiss. Index size: {self.faiss_index.ntotal}", "info")


            # --- Scan Completion Logging ---
            final_status = 'aborted' if self.stop_scan else 'completed'
            elapsed_final = time.time() - start_time
            self.log_scan_end(scan_id, processed_files_count, self.stats_new_count, self.stats_similar_pairs_count, final_status)

            self.log_message(f"Scan {final_status}. Processed {processed_files_count}/{total_files} images in {elapsed_final:.2f} seconds.", "info")
            self.log_message(f"Added {self.stats_new_count} new images to the database.", "info")
            self.log_message(f"Found {self.stats_similar_pairs_count} new similar pairs.", "info")

        except Exception as e:
            final_status = 'failed'
            self.log_message(f"Critical error during scan loop: {e}", "critical")
            import traceback
            self.logger.critical(traceback.format_exc()) # Log full traceback for critical errors
            if scan_id: self.log_scan_end(scan_id, processed_files_count, self.stats_new_count, self.stats_similar_pairs_count, final_status)
            messagebox.showerror("Scan Error", f"A critical error occurred during the scan:\n{e}\nCheck logs for details.")

        finally:
            self.cleanup_scan(final_status)


    def log_scan_start(self, folder_path: str, total_images: int) -> Optional[int]:
        """Log scan start in history table and return scan ID."""
        if not self.conn: return None
        try:
            start_time_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
            cursor = self.conn.execute("""
                INSERT INTO scan_history (folder_path, start_time, total_images_found, status)
                VALUES (?, ?, ?, ?)
            """, (folder_path, start_time_iso, total_images, 'running'))
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.log_message(f"Failed to log scan start: {e}", "error")
            return None

    def log_scan_end(self, scan_id: Optional[int], processed: int, new: int, similar: int, status: str) -> None:
        """Update scan history with completion status and stats."""
        if not self.conn or scan_id is None: return
        try:
            end_time_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
            self.conn.execute("""
                UPDATE scan_history
                SET end_time = ?, processed_files = ?, new_files_added = ?, similar_pairs_found = ?, status = ?
                WHERE id = ?
            """, (end_time_iso, processed, new, similar, status, scan_id))
        except sqlite3.Error as e:
            self.log_message(f"Failed to log scan end for ID {scan_id}: {e}", "error")


    def update_progress(self, processed: int, total: int, new: int, similar: int, speed: float) -> None:
        """Update progress indicators on GUI thread-safely."""
        def update_gui():
            if total > 0:
                 progress_percent = (processed / total) * 100
            else:
                 progress_percent = 0
            self.progress_var.set(progress_percent)
            self.stats_processed.config(text=f"Processed: {processed}/{total}")
            self.stats_new.config(text=f"New: {new}")
            self.stats_similar.config(text=f"Similar Pairs: {similar}")
            self.stats_speed.config(text=f"Speed: {speed:.1f} img/sec")
            # Force GUI update if needed, especially during long loops
            # self.root.update_idletasks()

        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(0, update_gui)

    def start_scan(self) -> None:
        """Start the scanning process in a separate thread."""
        if self.is_scanning:
            self.log_message("Scan already in progress.", "warning")
            return

        # Basic checks before starting thread
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
             messagebox.showerror("Error", "Please select a valid directory to scan.")
             return
        if not self.conn:
             messagebox.showerror("Error", "Database connection is not available. Cannot start scan.")
             return
        # Optional: Check if image processor is ready if vectors are crucial
        # if not self.image_processor_ready:
        #     if not messagebox.askokcancel("Warning", "Image processor (CLIP) failed to load. Similarity search will be limited or disabled. Continue?"):
        #         return


        self.is_scanning = True
        self.stop_scan = False

        # Update UI state
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.check_files_btn.config(state=tk.DISABLED) # Disable during scan
        self.status_label.config(text="Scanning...", foreground="orange")
        self.progress_var.set(0) # Reset progress bar

        # --- Start Scanner Thread ---
        # No separate batch processor needed with autocommit and direct processing
        scanner_thread = threading.Thread(target=self.scan_images, name="ScannerThread", daemon=True)
        scanner_thread.start()

        self.log_message("Scan thread started...")

    def stop_scanning(self) -> None:
        """Signal the scanning thread to stop."""
        if not self.is_scanning:
            return
        self.stop_scan = True
        self.log_message("Stop signal sent to scanner thread...", "warning")
        self.status_label.config(text="Stopping...", foreground="red")
        self.stop_btn.config(state=tk.DISABLED) # Prevent multiple clicks

    def cleanup_scan(self, status: str) -> None:
        """Clean up UI and state after scan completion, failure, or abortion."""
        self.is_scanning = False
        # self.stop_scan = False # Keep stop_scan as is, indicates if stopped manually

        # Update UI state on the main thread
        def update_gui():
            self.scan_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.check_files_btn.config(state=tk.NORMAL) # Re-enable check files button

            if status == 'completed':
                final_text = "Idle (Completed)"
                final_color = "green"
            elif status == 'aborted':
                final_text = "Idle (Aborted)"
                final_color = "yellow"
            elif status == 'failed':
                final_text = "Idle (Failed)"
                final_color = "red"
            else:
                final_text = "Idle"
                final_color = sv_ttk.get_theme() # Use theme's default text color

            self.status_label.config(text=final_text, foreground=final_color)

            # Save current config settings (like threshold)
            self._save_config()

        if hasattr(self, 'root') and self.root.winfo_exists():
             self.root.after(0, update_gui)


    def _save_config(self):
         """Save current configuration to config.ini"""
         if not self.config: return
         try:
             # Update config object with current values if needed
             self.config.set('PROCESSING', 'similarity_threshold', str(self.similarity_threshold.get()))
             self.config.set('UI', 'theme', sv_ttk.get_theme()) # Save current theme

             with open('config.ini', 'w') as configfile:
                 self.config.write(configfile)
             #self.log_message("Configuration saved.", "debug")
         except Exception as e:
             self.log_message(f"Error saving configuration: {e}", "error")


    def on_closing(self) -> None:
        """Handle window closing: stop scan, save index, close DB."""
        if self.is_scanning:
            if messagebox.askokcancel("Quit", "A scan is in progress. Abort scan and quit?"):
                self.stop_scan = True
                # Give the scan thread a moment to acknowledge the stop signal
                self.log_message("Aborting scan and shutting down...", "warning")
                # Might need to join the thread here if crucial cleanup happens there
                # scanner_thread.join(timeout=2.0) # Example wait
            else:
                return # User cancelled quit

        # Save Faiss index before closing
        if FAISS_AVAILABLE and self.faiss_index is not None:
             self._save_faiss_index()

        # Save configuration
        self._save_config()

        # Close database connection
        if self.conn:
            try:
                self.log_message("Closing database connection.", "info")
                self.conn.close()
                self.conn = None
            except Exception as e:
                self.log_message(f"Error closing database connection: {e}", "error")

        self.log_message("Exiting application.", "info")
        self.root.destroy()


    def check_missing_files(self) -> None:
        """Scans the database for entries whose paths no longer exist."""
        if not self.conn:
             messagebox.showerror("Error", "Database connection not available.")
             return
        if self.is_scanning:
             messagebox.showwarning("Busy", "Cannot check for missing files while a scan is running.")
             return

        self.log_message("Starting check for missing files in the database...", "info")
        missing_count = 0
        checked_count = 0
        missing_ids = []

        try:
             # Disable buttons during check
             self.scan_btn.config(state=tk.DISABLED)
             self.check_files_btn.config(state=tk.DISABLED)
             self.status_label.config(text="Checking files...", foreground="blue")
             self.root.update_idletasks() # Force GUI update

             cursor = self.conn.execute("SELECT id, absolute_path FROM images WHERE status = 'active'")
             rows = cursor.fetchall()
             total_to_check = len(rows)
             self.log_message(f"Checking {total_to_check} active image paths...", "info")
             # Simple progress display in log
             update_interval = max(1, total_to_check // 20) # Update log ~20 times

             for i, (img_id, path) in enumerate(rows):
                 checked_count += 1
                 if not os.path.exists(path):
                     missing_count += 1
                     missing_ids.append(img_id)
                     self.log_message(f"Missing file detected (ID: {img_id}): {path}", "warning")

                 if i % update_interval == 0 or i == total_to_check - 1:
                      self.log_message(f"Checked {checked_count}/{total_to_check} paths...", "debug")
                      # Optional: Update a temporary status label/progress bar

             self.log_message(f"Finished check. Found {missing_count} missing files.", "info")

             if missing_ids:
                 if messagebox.askyesno("Update Database", f"{missing_count} images in the database seem to be missing from the filesystem.\n\nDo you want to mark them as 'missing' in the database?"):
                     with self.conn:
                         # Update status in chunks for potentially large lists
                         chunk_size = 100
                         for i in range(0, len(missing_ids), chunk_size):
                             chunk = missing_ids[i:i + chunk_size]
                             placeholders = ','.join('?' for _ in chunk)
                             self.conn.execute(f"UPDATE images SET status = 'missing', image_vector = NULL WHERE id IN ({placeholders})", chunk)
                     self.log_message(f"Marked {len(missing_ids)} images as 'missing' in the database.", "info")
                     # Consider prompting for Faiss rebuild after marking many missing
                     if len(missing_ids) > 100 and FAISS_AVAILABLE: # Arbitrary threshold
                          if messagebox.askyesno("Faiss Index", "Many files were marked missing. Rebuild the Faiss similarity index now to remove them? (Recommended)"):
                               self._build_faiss_index()

                 else:
                     self.log_message("User chose not to update database for missing files.", "info")

        except sqlite3.Error as e:
             self.log_message(f"Database error during missing file check: {e}", "error")
             messagebox.showerror("Database Error", f"An error occurred while checking files: {e}")
        except Exception as e:
             self.log_message(f"Unexpected error during missing file check: {e}", "error")
             messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
             # Re-enable buttons and reset status
             self.scan_btn.config(state=tk.NORMAL)
             self.check_files_btn.config(state=tk.NORMAL)
             self.status_label.config(text="Idle", foreground=sv_ttk.get_theme()) # Use theme default
             self.root.update_idletasks()


if __name__ == "__main__":
    # Setup main window
    root = tk.Tk()

    # Create and run the application
    try:
        app = ImageScanner(root)

        # Center window on screen (optional, but nice)
        root.update_idletasks() # Ensure window dimensions are calculated
        window_width = root.winfo_width()
        window_height = root.winfo_height()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x_coordinate = int((screen_width / 2) - (window_width / 2))
        y_coordinate = int((screen_height / 2) - (window_height / 2))
        root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")

        root.mainloop()

    except Exception as main_e:
        # Catch critical startup errors (e.g., DB connection, model load)
        logging.basicConfig(level=logging.ERROR, filename='image_scanner_crash.log')
        logging.exception("Critical error during application startup or main loop.")
        # Try showing an error message box if Tkinter is still usable
        try:
            messagebox.showerror("Fatal Error", f"A critical error occurred: {main_e}\n\nCheck image_scanner_crash.log for details.\nApplication will now exit.")
        except Exception:
            print(f"FATAL ERROR: {main_e}. Application cannot continue.")
        sys.exit(1) # Exit with error code