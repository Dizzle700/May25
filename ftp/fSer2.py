import os
import sys
import socket
import json
import ipaddress
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import hashlib
import queue

from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

# --- Configuration ---
CONFIG_FILE = "ftp_server_config.json"
DEFAULT_PERMISSIONS_MAP = {
    "List (l,e)": "el",  # Enter dir, List files
    "Download (r)": "r",
    "Upload (w)": "w",
    "Append (a)": "a",
    "Delete (d)": "d",
    "Rename (f)": "f",
    "Make Dir (m)": "m",
}

# --- UI Theming ---
BG_COLOR = "#1a1a2e"
TEXT_COLOR = "#ffffff"
ENTRY_BG = "#16213e"
ACCENT_COLOR = "#4f8a8b"
SUCCESS_COLOR = "#57cc99"
WARNING_COLOR = "#fb8b24"
ERROR_COLOR = "#e74c3c"
BUTTON_TEXT_COLOR = "#000000"

# --- Custom Authorizer for Hashed Passwords ---
class CustomAuthorizer(DummyAuthorizer):
    """
    A custom authorizer that handles salted and hashed passwords for security.
    """
    # This attribute will hold a queue for thread-safe logging
    log_queue: queue.Queue | None = None

    def validate_authentication(self, username, password, handler):
        try:
            # The stored 'pwd' is in the format "salt:hashed_password"
            stored_data = self.user_table[username]['pwd']
            salt, stored_hash = stored_data.split(':', 1)

            # Hash the incoming password with the stored salt to see if it matches
            pwd_hash = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            )
            pwd_hash = pwd_hash.hex()

            if pwd_hash != stored_hash:
                raise AuthenticationFailed("Invalid password.")

        except (KeyError, ValueError, IndexError):
            # This handles cases where user is not found or password format is wrong
            raise AuthenticationFailed("Authentication failed.")
        except Exception:
            raise AuthenticationFailed("An unexpected error occurred during authentication.")

# --- Custom FTP Handler for Logging ---
class CustomFTPHandler(FTPHandler):
    """
    Custom handler to override methods and provide better logging via a queue.
    """
    def on_login(self, username):
        if self.authorizer and hasattr(self.authorizer, 'log_queue') and self.authorizer.log_queue:
            self.authorizer.log_queue.put(("SUCCESS", f"User '{username}' logged in from {self.remote_ip}"))

    def on_login_failed(self, username, password):
        # This callback in pyftpdlib does not receive the failure reason ('why').
        # The reason is sent to the client, but not passed to this handler method.
        if self.authorizer and hasattr(self.authorizer, 'log_queue') and self.authorizer.log_queue:
            self.authorizer.log_queue.put(("WARNING", f"Login failed for user '{username}'. IP: {self.remote_ip}"))


class Tooltip:
    """Simple tooltip class for Tkinter widgets."""
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None) -> None:
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#333333", foreground="white", relief='solid', borderwidth=1,
                         font=("Helvetica", 9, "normal"), padx=5, pady=3)
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None) -> None:
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None


class FTPServerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Advanced FTP Server")
        self.root.geometry("650x700")
        self.root.resizable(True, True)
        self.root.configure(bg=BG_COLOR)

        self.server: FTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.is_server_running: bool = False

        self.log_queue = queue.Queue()
        self.config: dict = self._load_config()
        self._initialize_vars_from_config()

        self.create_widgets()
        self.queue_log("FTP Server GUI initialized. Load settings or configure.")
        self.check_log_queue()  # Start listening for log messages
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _initialize_vars_from_config(self) -> None:
        """Initialize tk.StringVar and tk.BooleanVar from loaded config."""
        # Main settings - Default to 0.0.0.0 for better compatibility
        self.ip_var = tk.StringVar(value=self.config.get("ip", "0.0.0.0"))
        self.port_var = tk.StringVar(value=self.config.get("port", "2121"))
        self.user_var = tk.StringVar(value=self.config.get("username", "user"))
        self.pass_var = tk.StringVar(value=self.config.get("password", ""))
        self.folder_var = tk.StringVar(value=self.config.get("shared_folder", ""))
        self.banner_var = tk.StringVar(value=self.config.get("banner", "Welcome to PyFTPd Server!"))

        # User Permissions
        self.user_perm_vars: dict[str, tk.BooleanVar] = {}
        saved_user_perms = self.config.get("user_permissions", {"List (l,e)": True, "Download (r)": True})
        for desc in DEFAULT_PERMISSIONS_MAP:
            self.user_perm_vars[desc] = tk.BooleanVar(value=saved_user_perms.get(desc, False))

        # Anonymous settings
        self.anon_enabled_var = tk.BooleanVar(value=self.config.get("anonymous_enabled", False))
        self.anon_folder_var = tk.StringVar(value=self.config.get("anonymous_folder", ""))
        self.anon_perm_vars: dict[str, tk.BooleanVar] = {}
        saved_anon_perms = self.config.get("anonymous_permissions", {"List (l,e)": True, "Download (r)": True})
        for desc in DEFAULT_PERMISSIONS_MAP:
            self.anon_perm_vars[desc] = tk.BooleanVar(value=saved_anon_perms.get(desc, False))

        # FTPS settings
        self.ftps_enabled_var = tk.BooleanVar(value=self.config.get("ftps_enabled", False))
        self.cert_file_var = tk.StringVar(value=self.config.get("cert_file", ""))
        self.key_file_var = tk.StringVar(value=self.config.get("key_file", ""))

    def _get_permissions_string(self, perm_vars: dict[str, tk.BooleanVar]) -> str:
        """Constructs the pyftpdlib permission string from BooleanVars."""
        perms = ""
        for desc, var in perm_vars.items():
            if var.get():
                perms += DEFAULT_PERMISSIONS_MAP[desc]
        return "".join(sorted(list(set(perms))))  # Remove duplicates and sort

    def _hash_password(self, password: str) -> str:
        """Hashes a password with a new salt using PBKDF2-HMAC-SHA256."""
        salt = os.urandom(16).hex()
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return f"{salt}:{pwd_hash.hex()}"

    def _load_config(self) -> dict:
        """Loads configuration from JSON file."""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            return {}
        except (IOError, json.JSONDecodeError) as e:
            messagebox.showerror("Config Error", f"Could not load config: {e}")
            return {}

    def _save_config(self) -> None:
        """Saves current settings to JSON file, hashing the password if it's new."""
        password = self.pass_var.get()
        # Only hash the password if it's not empty and doesn't look like our salt:hash format.
        if password and ':' not in password:
            hashed_password = self._hash_password(password)
            self.pass_var.set(hashed_password) # Update the UI variable to reflect the hash
            self.queue_log("New password has been hashed for secure storage.")
        else:
            hashed_password = password # It's already hashed or empty

        current_config = {
            "ip": self.ip_var.get(),
            "port": self.port_var.get(),
            "username": self.user_var.get(),
            "password": hashed_password,
            "shared_folder": self.folder_var.get(),
            "banner": self.banner_var.get(),
            "user_permissions": {desc: var.get() for desc, var in self.user_perm_vars.items()},
            "anonymous_enabled": self.anon_enabled_var.get(),
            "anonymous_folder": self.anon_folder_var.get(),
            "anonymous_permissions": {desc: var.get() for desc, var in self.anon_perm_vars.items()},
            "ftps_enabled": self.ftps_enabled_var.get(),
            "cert_file": self.cert_file_var.get(),
            "key_file": self.key_file_var.get(),
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(current_config, f, indent=4)
            self.queue_log("Configuration saved successfully.")
        except IOError as e:
            messagebox.showerror("Config Error", f"Could not save config: {e}")

    def create_widgets(self) -> None:
        """Creates all UI widgets, organized into tabs."""
        main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = tk.Label(main_frame, text="Advanced FTP Server Control",
                               font=("Helvetica", 16, "bold"), bg=BG_COLOR, fg=TEXT_COLOR)
        title_label.pack(pady=(0, 10))

        self.notebook = ttk.Notebook(main_frame)
        style = ttk.Style()
        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure("TNotebook.Tab", background=ACCENT_COLOR, foreground=TEXT_COLOR, padding=[10, 5], font=("Helvetica", 10))
        style.map("TNotebook.Tab", background=[("selected", ENTRY_BG)], foreground=[("selected", TEXT_COLOR)])

        self.tab_main = ttk.Frame(self.notebook, style="TFrame")
        self.tab_anon = ttk.Frame(self.notebook, style="TFrame")
        self.tab_ftps = ttk.Frame(self.notebook, style="TFrame")
        self.tab_log = ttk.Frame(self.notebook, style="TFrame")

        self.notebook.add(self.tab_main, text='Main Settings')
        self.notebook.add(self.tab_anon, text='Anonymous Access')
        self.notebook.add(self.tab_ftps, text='FTPS (Secure)')
        self.notebook.add(self.tab_log, text='Server Log')
        self.notebook.pack(expand=True, fill='both', pady=5)

        self._create_main_settings_panel(self.tab_main)
        self._create_anonymous_panel(self.tab_anon)
        self._create_ftps_panel(self.tab_ftps)
        self._create_log_panel(self.tab_log)
        self._create_controls_panel(main_frame)

    def _create_styled_frame(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG_COLOR, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        return frame
    
    # --- GUI Panel Creation (remains largely the same, minor tooltip updates) ---

    def _create_main_settings_panel(self, parent_tab: ttk.Frame) -> None:
        """Creates the UI for main server settings."""
        frame = self._create_styled_frame(parent_tab)
        
        ip_port_frame = tk.Frame(frame, bg=BG_COLOR)
        ip_port_frame.pack(fill=tk.X, pady=5)

        tk.Label(ip_port_frame, text="IP Address:", bg=BG_COLOR, fg=TEXT_COLOR).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ip_entry = tk.Entry(ip_port_frame, textvariable=self.ip_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, width=20)
        ip_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        Tooltip(ip_entry, "Server IP address (0.0.0.0 for all interfaces)")
        tk.Button(ip_port_frame, text="📋", command=lambda: self._copy_to_clipboard(self.ip_var.get()),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, width=2).grid(row=0, column=2, padx=(0,10))


        tk.Label(ip_port_frame, text="Port:", bg=BG_COLOR, fg=TEXT_COLOR).grid(row=0, column=3, sticky="w", padx=5, pady=2)
        port_entry = tk.Entry(ip_port_frame, textvariable=self.port_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, width=7)
        port_entry.grid(row=0, column=4, sticky="ew", padx=5, pady=2)
        Tooltip(port_entry, "Server port (e.g., 21 or 2121)")
        tk.Button(ip_port_frame, text="📋", command=lambda: self._copy_to_clipboard(self.port_var.get()),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, width=2).grid(row=0, column=5, padx=(0,5))
        ip_port_frame.columnconfigure(1, weight=1)
        ip_port_frame.columnconfigure(4, weight=1)

        user_frame = tk.Frame(frame, bg=BG_COLOR)
        user_frame.pack(fill=tk.X, pady=5)
        tk.Label(user_frame, text="Username:", bg=BG_COLOR, fg=TEXT_COLOR).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        tk.Entry(user_frame, textvariable=self.user_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR).grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        
        tk.Label(user_frame, text="Password:", bg=BG_COLOR, fg=TEXT_COLOR).grid(row=0, column=2, sticky="w", padx=5, pady=2)
        self.pass_entry = tk.Entry(user_frame, textvariable=self.pass_var, show="*", bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        self.pass_entry.grid(row=0, column=3, sticky="ew", padx=5, pady=2)
        self.show_pass_var = tk.BooleanVar()
        tk.Checkbutton(user_frame, text="Show", variable=self.show_pass_var, command=self._toggle_password,
                       bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=ENTRY_BG, activebackground=BG_COLOR, activeforeground=TEXT_COLOR
                       ).grid(row=0, column=4, padx=5)
        user_frame.columnconfigure(1, weight=1)
        user_frame.columnconfigure(3, weight=1)

        folder_frame = tk.Frame(frame, bg=BG_COLOR)
        folder_frame.pack(fill=tk.X, pady=5)
        tk.Label(folder_frame, text="Shared Folder:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        folder_entry = tk.Entry(folder_frame, textvariable=self.folder_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(folder_entry, "The main directory this user can access.")
        tk.Button(folder_frame, text="Browse", command=lambda v=self.folder_var: self.browse_folder(v),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=8).pack(side=tk.RIGHT, padx=5)

        perm_frame = tk.LabelFrame(frame, text="User Permissions", bg=BG_COLOR, fg=TEXT_COLOR, padx=5, pady=5)
        perm_frame.pack(fill=tk.X, pady=10)
        
        row, col = 0, 0
        for i, (desc, _) in enumerate(DEFAULT_PERMISSIONS_MAP.items()):
            chk = tk.Checkbutton(perm_frame, text=desc, variable=self.user_perm_vars[desc],
                                 bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=ENTRY_BG,
                                 activebackground=BG_COLOR, activeforeground=TEXT_COLOR)
            chk.grid(row=row, column=col, sticky="w", padx=5, pady=2)
            Tooltip(chk, f"Allow user to: {desc.lower()}")
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        banner_frame = tk.Frame(frame, bg=BG_COLOR)
        banner_frame.pack(fill=tk.X, pady=5)
        tk.Label(banner_frame, text="Server Banner:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        banner_entry = tk.Entry(banner_frame, textvariable=self.banner_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        banner_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(banner_entry, "Message shown to clients on connection.")


    def _create_anonymous_panel(self, parent_tab: ttk.Frame) -> None:
        frame = self._create_styled_frame(parent_tab)

        tk.Checkbutton(frame, text="Enable Anonymous Access", variable=self.anon_enabled_var,
                       bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=ENTRY_BG,
                       activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
                       font=("Helvetica", 11, "bold")).pack(anchor="w", pady=5)

        anon_folder_frame = tk.Frame(frame, bg=BG_COLOR)
        anon_folder_frame.pack(fill=tk.X, pady=5)
        tk.Label(anon_folder_frame, text="Anonymous Folder:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        anon_folder_entry = tk.Entry(anon_folder_frame, textvariable=self.anon_folder_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        anon_folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(anon_folder_entry, "Directory for anonymous users (if enabled).")
        tk.Button(anon_folder_frame, text="Browse", command=lambda v=self.anon_folder_var: self.browse_folder(v),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=8).pack(side=tk.RIGHT, padx=5)

        anon_perm_frame = tk.LabelFrame(frame, text="Anonymous Permissions", bg=BG_COLOR, fg=TEXT_COLOR, padx=5, pady=5)
        anon_perm_frame.pack(fill=tk.X, pady=10)
        row, col = 0, 0
        for i, (desc, _) in enumerate(DEFAULT_PERMISSIONS_MAP.items()):
            chk = tk.Checkbutton(anon_perm_frame, text=desc, variable=self.anon_perm_vars[desc],
                                 bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=ENTRY_BG,
                                 activebackground=BG_COLOR, activeforeground=TEXT_COLOR)
            chk.grid(row=row, column=col, sticky="w", padx=5, pady=2)
            Tooltip(chk, f"Allow anonymous users to: {desc.lower()}")
            col += 1
            if col >= 3:
                col = 0
                row += 1
    
    def _create_ftps_panel(self, parent_tab: ttk.Frame) -> None:
        frame = self._create_styled_frame(parent_tab)

        tk.Checkbutton(frame, text="Enable FTPS (FTP over SSL/TLS)", variable=self.ftps_enabled_var,
                       bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=ENTRY_BG,
                       activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
                       font=("Helvetica", 11, "bold")).pack(anchor="w", pady=5)

        cert_frame = tk.Frame(frame, bg=BG_COLOR)
        cert_frame.pack(fill=tk.X, pady=5)
        tk.Label(cert_frame, text="Certificate File (.pem):", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        cert_entry = tk.Entry(cert_frame, textvariable=self.cert_file_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        cert_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(cert_entry, "Path to SSL certificate file (e.g., cert.pem).")
        tk.Button(cert_frame, text="Browse", command=lambda v=self.cert_file_var: self.browse_file(v, [("PEM files", "*.pem"), ("All files", "*.*")]),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=8).pack(side=tk.RIGHT, padx=5)

        key_frame = tk.Frame(frame, bg=BG_COLOR)
        key_frame.pack(fill=tk.X, pady=5)
        tk.Label(key_frame, text="Private Key File (.key):", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        key_entry = tk.Entry(key_frame, textvariable=self.key_file_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(key_entry, "Path to SSL private key file (e.g., key.key or key.pem).")
        tk.Button(key_frame, text="Browse", command=lambda v=self.key_file_var: self.browse_file(v, [("Key files", "*.key"),("PEM files", "*.pem"), ("All files", "*.*")]),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=8).pack(side=tk.RIGHT, padx=5)
        
        tk.Label(frame, text="Note: FTPS requires a valid SSL certificate and private key.",
                 font=("Helvetica", 9, "italic"), bg=BG_COLOR, fg=WARNING_COLOR).pack(pady=10)

    def _create_log_panel(self, parent_tab: ttk.Frame) -> None:
        """Creates the server log panel."""
        frame = self._create_styled_frame(parent_tab)
        self.log_text = tk.Text(frame, height=15, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, wrap=tk.WORD, relief=tk.FLAT, borderwidth=0)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(0,5))
        scrollbar = tk.Scrollbar(frame, command=self.log_text.yview, bg=BG_COLOR, troughcolor=ENTRY_BG)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(0,5))
        self.log_text.config(yscrollcommand=scrollbar.set, state=tk.DISABLED)
        log_button_frame = tk.Frame(frame, bg=BG_COLOR)
        log_button_frame.pack(fill=tk.X)
        tk.Button(log_button_frame, text="Clear Log", command=self._clear_log, bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=10, pady=3).pack(side=tk.LEFT, padx=5)

    def _create_controls_panel(self, parent_frame: tk.Frame) -> None:
        """Creates the main server control buttons and status."""
        button_frame = tk.Frame(parent_frame, bg=BG_COLOR)
        button_frame.pack(fill=tk.X, pady=(10,5))

        self.start_button = tk.Button(button_frame, text="Start Server", command=self.start_server, bg=SUCCESS_COLOR, fg=BUTTON_TEXT_COLOR, activebackground="#46a37a", activeforeground=BUTTON_TEXT_COLOR, bd=0, padx=10, pady=5, width=15, font=("Helvetica", 10, "bold"))
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(button_frame, text="Stop Server", command=self.stop_server, bg=WARNING_COLOR, fg=BUTTON_TEXT_COLOR, activebackground="#c87019", activeforeground=BUTTON_TEXT_COLOR, bd=0, padx=10, pady=5, width=15, state=tk.DISABLED, font=("Helvetica", 10, "bold"))
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.save_config_button = tk.Button(button_frame, text="Save Settings", command=self._save_config, bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, activebackground="#3a686a", activeforeground=BUTTON_TEXT_COLOR, bd=0, padx=10, pady=5, width=15, font=("Helvetica", 10, "bold"))
        self.save_config_button.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="Server is stopped.")
        self.status_label = tk.Label(button_frame, textvariable=self.status_var, bg=BG_COLOR, fg=WARNING_COLOR, font=("Helvetica", 10, "bold"))
        self.status_label.pack(side=tk.RIGHT, padx=10)

    # --- Utility and Helper Methods ---
    def _toggle_password(self) -> None:
        self.pass_entry.config(show="" if self.show_pass_var.get() else "*")

    def _copy_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.queue_log(f"Copied '{text}' to clipboard.")

    def get_local_ip(self) -> str:
        """Attempts to get a non-loopback local IP address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.1)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def browse_folder(self, var_to_set: tk.StringVar) -> None:
        folder_path = filedialog.askdirectory(initialdir=var_to_set.get() or os.getcwd())
        if folder_path:
            var_to_set.set(folder_path)
            self.queue_log(f"Selected folder: {folder_path}")

    def browse_file(self, var_to_set: tk.StringVar, filetypes: list[tuple[str,str]]) -> None:
        file_path = filedialog.askopenfilename(initialdir=os.path.dirname(var_to_set.get() or os.getcwd()), filetypes=filetypes)
        if file_path:
            var_to_set.set(file_path)
            self.queue_log(f"Selected file: {file_path}")

    def validate_inputs(self) -> bool:
        """Validates all necessary inputs before starting the server."""
        ip = self.ip_var.get().strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            messagebox.showerror("Invalid IP", "Please enter a valid IP address (e.g., 192.168.1.100 or 0.0.0.0).")
            return False

        try:
            port = int(self.port_var.get().strip())
            if not (1 <= port <= 65535): raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a number between 1 and 65535.")
            return False

        if not self.user_var.get().strip() and not self.anon_enabled_var.get():
            messagebox.showerror("No Users", "Username cannot be empty if anonymous access is disabled.")
            return False

        shared_folder = self.folder_var.get().strip()
        if self.user_var.get().strip() and not os.path.isdir(shared_folder):
            messagebox.showerror("Invalid Folder", "Please select a valid shared folder for the main user.")
            return False
        
        if self.anon_enabled_var.get():
            anon_folder = self.anon_folder_var.get().strip()
            if not os.path.isdir(anon_folder):
                messagebox.showerror("Invalid Anonymous Folder", "Please select a valid folder for anonymous access or disable it.")
                return False

        if self.ftps_enabled_var.get():
            if not os.path.isfile(self.cert_file_var.get().strip()):
                messagebox.showerror("Invalid Certificate", "FTPS enabled: Certificate file not found or invalid.")
                return False
            if not os.path.isfile(self.key_file_var.get().strip()):
                messagebox.showerror("Invalid Key", "FTPS enabled: Private key file not found or invalid.")
                return False
        return True

    def _set_input_widgets_state(self, state: str):
        """Disables or enables all input widgets to prevent changes while running."""
        for tab in [self.tab_main, self.tab_anon, self.tab_ftps]:
            for widget in tab.winfo_children():
                self._set_state_recursive(widget, state)

    def _set_state_recursive(self, widget, state: str):
        """Recursively set state for a widget and its children."""
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass  # Widget doesn't have a 'state' option.
        for child in widget.winfo_children():
            self._set_state_recursive(child, state)

    # --- Logging and Queue Management ---
    def queue_log(self, message: str, level: str = "INFO"):
        """Puts a log message onto the thread-safe queue."""
        self.log_queue.put((level, message))

    def check_log_queue(self):
        """Periodically checks the queue for new log messages and displays them."""
        try:
            while True:
                level, message = self.log_queue.get_nowait()
                self._log_to_widget(message, level)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_log_queue)  # Check again in 100ms

    def _log_to_widget(self, message: str, level: str) -> None:
        """Logs a message to the text widget with a timestamp and level."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted_message)
        
        tag_name = f"level_{level.lower()}"
        color = {
            "ERROR": ERROR_COLOR, "WARNING": WARNING_COLOR, "SUCCESS": SUCCESS_COLOR
        }.get(level, TEXT_COLOR)
        self.log_text.tag_configure(tag_name, foreground=color)
        self.log_text.tag_add(tag_name, f"end-{len(formatted_message)+1}c", "end-1c")
        
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.queue_log("Log cleared.")

    # --- Server Control Logic ---
    def start_server(self) -> None:
        if not self.validate_inputs():
            return
        if self.is_server_running:
            self.queue_log("Server is already running.", "WARNING")
            return

        self._set_input_widgets_state(tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.save_config_button.config(state=tk.DISABLED)
        self.status_var.set("Server is starting...")
        self.status_label.config(fg=WARNING_COLOR)

        server_params = {
            "ip": self.ip_var.get().strip(),
            "port": int(self.port_var.get().strip()),
            "username": self.user_var.get().strip(),
            "password": self.pass_var.get(),
            "user_permissions": self._get_permissions_string(self.user_perm_vars),
            "shared_folder": self.folder_var.get().strip(),
            "banner": self.banner_var.get().strip(),
            "anon_enabled": self.anon_enabled_var.get(),
            "anon_folder": self.anon_folder_var.get().strip(),
            "anon_permissions": self._get_permissions_string(self.anon_perm_vars),
            "ftps_enabled": self.ftps_enabled_var.get(),
            "cert_file": self.cert_file_var.get().strip(),
            "key_file": self.key_file_var.get().strip()
        }

        self.server_thread = threading.Thread(target=self._run_server, args=(server_params,), daemon=True)
        self.server_thread.start()

    def _run_server(self, params: dict) -> None:
        """The actual server execution logic (runs in a thread)."""
        try:
            authorizer = CustomAuthorizer()
            authorizer.log_queue = self.log_queue # Pass queue for logging from handler

            if params["username"]:
                authorizer.add_user(params["username"], params["password"], params["shared_folder"], perm=params["user_permissions"])

            if params["anon_enabled"]:
                authorizer.add_anonymous(params["anon_folder"], perm=params["anon_permissions"])
            
            handler_class = CustomFTPHandler
            if params["ftps_enabled"]:
                handler_class.certfile = params["cert_file"]
                handler_class.keyfile = params["key_file"]
                handler_class.tls_control_required = True
                handler_class.tls_data_required = True

            handler_class.authorizer = authorizer
            if params["banner"]:
                handler_class.banner = params["banner"]

            self.server = FTPServer((params["ip"], params["port"]), handler_class)
            self.server.max_cons = 256
            self.server.max_cons_per_ip = 5

            self.is_server_running = True
            self.root.after(0, self._server_started_successfully, params["ip"], params["port"], params["ftps_enabled"])
            self.server.serve_forever()

        except socket.error as e:
            msg = f"Error: Port {params['port']} on IP {params['ip']} is already in use." if e.errno == socket.errno.EADDRINUSE else f"Network Error starting server: {e}"
            self.log_queue.put(("ERROR", msg))
            self.root.after(0, self._server_start_failed)
        except Exception as e:
            import traceback
            self.log_queue.put(("ERROR", f"Critical error starting server: {e}"))
            self.log_queue.put(("ERROR", traceback.format_exc()))
            self.root.after(0, self._server_start_failed)
        finally:
            if self.is_server_running:
                self.root.after(0, self._server_stopped_ui_update)

    def _server_started_successfully(self, ip: str, port: int, ftps: bool) -> None:
        protocol = "FTPS" if ftps else "FTP"
        display_ip = ip
        if ip == '0.0.0.0':
            local_ip = self.get_local_ip()
            display_ip = f"{local_ip} (listening on all interfaces)"
        
        self.queue_log(f"{protocol} Server started on {display_ip}:{port}", "SUCCESS")
        if self.user_var.get().strip():
             self.queue_log(f"User '{self.user_var.get().strip()}' configured with permissions: {self._get_permissions_string(self.user_perm_vars)}")
        if self.anon_enabled_var.get():
            self.queue_log(f"Anonymous access enabled. Folder: {self.anon_folder_var.get().strip()}, Perms: {self._get_permissions_string(self.anon_perm_vars)}")
        
        self.status_var.set(f"{protocol} Server is running")
        self.status_label.config(fg=SUCCESS_COLOR)

    def _server_start_failed(self) -> None:
        self.is_server_running = False
        self.server = None
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.save_config_button.config(state=tk.NORMAL)
        self._set_input_widgets_state(tk.NORMAL)
        self.status_var.set("Server start failed.")
        self.status_label.config(fg=ERROR_COLOR)

    def stop_server(self) -> None:
        if self.server and self.is_server_running:
            self.queue_log("Stopping server...", "INFO")
            # server.close_all() will make serve_forever() return, triggering the finally block
            threading.Thread(target=self.server.close_all, daemon=True).start()
        else:
            self.queue_log("Server is not running or already stopping.", "WARNING")
            self._server_stopped_ui_update()

    def _server_stopped_ui_update(self) -> None:
        if not self.is_server_running and self.status_var.get() == "Server is stopped.":
            return # Avoid redundant updates
            
        self.is_server_running = False
        self.server = None
        self.server_thread = None

        self.queue_log("Server stopped.", "INFO")
        self.status_var.set("Server is stopped.")
        self.status_label.config(fg=WARNING_COLOR)
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.save_config_button.config(state=tk.NORMAL)
        self._set_input_widgets_state(tk.NORMAL)

    def _on_closing(self) -> None:
        if self.is_server_running:
            if messagebox.askyesno("Server Running", "The FTP server is still running. Do you want to stop it and exit?"):
                self.stop_server()
                self.root.after(500, self._save_and_destroy)
            else:
                return
        else:
            self._save_and_destroy()

    def _save_and_destroy(self) -> None:
        self._save_config()
        self.root.destroy()

def main():
    root = tk.Tk()
    try:
        # This helps find the icon when bundled with PyInstaller
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        if sys.platform == "win32":
            icon_path = os.path.join(base_path, 'ftp_icon.ico')
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
    except Exception as e:
        print(f"Could not set window icon: {e}")

    app = FTPServerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
