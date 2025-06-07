import os
import sys
import socket
import json
import ipaddress
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from pyftpdlib.handlers import FTPHandler, TLS_FTPHandler
from pyftpdlib.servers import FTPServer

# --- Configuration ---
CONFIG_FILE = "ftp_server_config.json"
DEFAULT_PERMISSIONS_MAP = {
    "List (l,e)": "el", # Enter dir, List files
    "Download (r)": "r",
    "Upload (w)": "w",
    "Append (a)": "a",
    "Delete (d)": "d",
    "Rename (f)": "f",
    "Make Dir (m)": "m",
}

# --- UI Theming ---
BG_COLOR = "#1a1a2e" # Dark navy blue
TEXT_COLOR = "#ffffff" # White
ENTRY_BG = "#16213e" # Slightly lighter navy
ACCENT_COLOR = "#4f8a8b" # Teal
SUCCESS_COLOR = "#57cc99" # Mint green
WARNING_COLOR = "#fb8b24" # Orange
ERROR_COLOR = "#e74c3c" # Red
BUTTON_TEXT_COLOR = "#000000"

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

        self.config: dict = self._load_config()
        self._initialize_vars_from_config()

        self.create_widgets()
        self.log("FTP Server GUI initialized. Load settings or configure.")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _initialize_vars_from_config(self) -> None:
        """Initialize tk.StringVar and tk.BooleanVar from loaded config."""
        # Main settings
        self.ip_var = tk.StringVar(value=self.config.get("ip", self.get_local_ip()))
        self.port_var = tk.StringVar(value=self.config.get("port", "2121"))
        self.user_var = tk.StringVar(value=self.config.get("username", "user"))
        self.pass_var = tk.StringVar(value=self.config.get("password", "")) # Default to empty
        self.folder_var = tk.StringVar(value=self.config.get("shared_folder", ""))
        self.banner_var = tk.StringVar(value=self.config.get("banner", "Welcome to PyFTPd Server!"))

        # User Permissions
        self.user_perm_vars: dict[str, tk.BooleanVar] = {}
        saved_user_perms = self.config.get("user_permissions", {"List (l,e)": True, "Download (r)": True}) # Default sensible read
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
        return "".join(sorted(list(set(perms)))) # Remove duplicates and sort

    def _load_config(self) -> dict:
        """Loads configuration from JSON file."""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            return {} # Return empty dict if no file, defaults will be used
        except (IOError, json.JSONDecodeError) as e:
            messagebox.showerror("Config Error", f"Could not load config: {e}")
            return {}

    def _save_config(self) -> None:
        """Saves current settings to JSON file."""
        current_config = {
            "ip": self.ip_var.get(),
            "port": self.port_var.get(),
            "username": self.user_var.get(),
            "password": self.pass_var.get(),
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
            self.log("Configuration saved.")
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
        self._create_controls_panel(main_frame) # Controls outside tabs

    def _create_styled_frame(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG_COLOR, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        return frame

    def _create_main_settings_panel(self, parent_tab: ttk.Frame) -> None:
        """Creates the UI for main server settings."""
        frame = self._create_styled_frame(parent_tab)
        
        # --- IP and Port ---
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

        # --- User Credentials ---
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

        # --- Shared Folder ---
        folder_frame = tk.Frame(frame, bg=BG_COLOR)
        folder_frame.pack(fill=tk.X, pady=5)
        tk.Label(folder_frame, text="Shared Folder:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=5, pady=2)
        folder_entry = tk.Entry(folder_frame, textvariable=self.folder_var, bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        Tooltip(folder_entry, "The main directory this user can access.")
        tk.Button(folder_frame, text="Browse", command=lambda v=self.folder_var: self.browse_folder(v),
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=8).pack(side=tk.RIGHT, padx=5)

        # --- User Permissions ---
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
            if col >= 3: # Max 3 checkboxes per row
                col = 0
                row += 1
        
        # --- Banner ---
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

        self.log_text = tk.Text(frame, height=15,
                                bg=ENTRY_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                                wrap=tk.WORD, relief=tk.FLAT, borderwidth=0)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(0,5))

        scrollbar = tk.Scrollbar(frame, command=self.log_text.yview, bg=BG_COLOR, troughcolor=ENTRY_BG)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(0,5))
        self.log_text.config(yscrollcommand=scrollbar.set)
        self.log_text.config(state=tk.DISABLED) # Start as read-only

        log_button_frame = tk.Frame(frame, bg=BG_COLOR)
        log_button_frame.pack(fill=tk.X)
        tk.Button(log_button_frame, text="Clear Log", command=self._clear_log,
                  bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR, bd=0, padx=10, pady=3).pack(side=tk.LEFT, padx=5)
        # Save log button can be added here similarly

    def _create_controls_panel(self, parent_frame: tk.Frame) -> None:
        """Creates the main server control buttons and status."""
        button_frame = tk.Frame(parent_frame, bg=BG_COLOR)
        button_frame.pack(fill=tk.X, pady=(10,5))

        self.start_button = tk.Button(button_frame, text="Start Server", command=self.start_server,
                                      bg=SUCCESS_COLOR, fg=BUTTON_TEXT_COLOR,
                                      activebackground="#46a37a", activeforeground=BUTTON_TEXT_COLOR,
                                      bd=0, padx=10, pady=5, width=15, font=("Helvetica", 10, "bold"))
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(button_frame, text="Stop Server", command=self.stop_server,
                                     bg=WARNING_COLOR, fg=BUTTON_TEXT_COLOR,
                                     activebackground="#c87019", activeforeground=BUTTON_TEXT_COLOR,
                                     bd=0, padx=10, pady=5, width=15, state=tk.DISABLED, font=("Helvetica", 10, "bold"))
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.save_config_button = tk.Button(button_frame, text="Save Settings", command=self._save_config,
                                     bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR,
                                     activebackground="#3a686a", activeforeground=BUTTON_TEXT_COLOR,
                                     bd=0, padx=10, pady=5, width=15, font=("Helvetica", 10, "bold"))
        self.save_config_button.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="Server is stopped.")
        self.status_label = tk.Label(button_frame, textvariable=self.status_var,
                                     bg=BG_COLOR, fg=WARNING_COLOR,
                                     font=("Helvetica", 10, "bold"))
        self.status_label.pack(side=tk.RIGHT, padx=10)

    def _toggle_password(self) -> None:
        """Toggles password visibility in the entry field."""
        if self.show_pass_var.get():
            self.pass_entry.config(show="")
        else:
            self.pass_entry.config(show="*")

    def _copy_to_clipboard(self, text: str) -> None:
        """Copies the given text to the clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log(f"Copied '{text}' to clipboard.")

    def get_local_ip(self) -> str:
        """Attempts to get the local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1) # Add timeout
            s.connect(("8.8.8.8", 80)) # Does not send data
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception: # Catch all exceptions for network issues
            return "127.0.0.1"

    def browse_folder(self, var_to_set: tk.StringVar) -> None:
        """Opens a dialog to browse for a folder."""
        folder_path = filedialog.askdirectory(initialdir=var_to_set.get() or os.getcwd())
        if folder_path:
            var_to_set.set(folder_path)
            self.log(f"Selected folder: {folder_path}")

    def browse_file(self, var_to_set: tk.StringVar, filetypes: list[tuple[str,str]]) -> None:
        """Opens a dialog to browse for a file."""
        file_path = filedialog.askopenfilename(initialdir=os.path.dirname(var_to_set.get() or os.getcwd()),
                                               filetypes=filetypes)
        if file_path:
            var_to_set.set(file_path)
            self.log(f"Selected file: {file_path}")
    
    def _is_port_available(self, ip: str, port: int) -> bool:
        """Checks if a specific IP and port are available to bind."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((ip, port))
            s.close()
            return True
        except socket.error:
            s.close()
            return False

    def validate_inputs(self) -> bool:
        """Validates all necessary inputs before starting the server."""
        ip = self.ip_var.get().strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            messagebox.showerror("Invalid IP", "Please enter a valid IP address (e.g., 192.168.1.100 or 0.0.0.0).")
            return False

        port_str = self.port_var.get().strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a number between 1 and 65535.")
            return False

        if not self._is_port_available(ip, port) and ip != "0.0.0.0": #0.0.0.0 might behave differently with simple bind check
             if not self._is_port_available("0.0.0.0", port): # Check all interfaces if specific IP fails
                messagebox.showwarning("Port Unavailable", f"Port {port} on IP {ip} might be in use. Trying to start anyway.")
        
        if not self.user_var.get().strip():
            messagebox.showerror("Invalid User", "Username cannot be empty.")
            return False
        if not self.pass_var.get(): # Password can be empty, but good to warn for non-anonymous.
            if not self.anon_enabled_var.get(): # Only warn if no anonymous either
                 messagebox.showwarning("Weak Password", "Password is empty. This is insecure if anonymous access is disabled.")

        shared_folder = self.folder_var.get().strip()
        if not shared_folder or not os.path.isdir(shared_folder):
            messagebox.showerror("Invalid Folder", "Please select a valid shared folder for the main user.")
            return False

        user_perms = self._get_permissions_string(self.user_perm_vars)
        if not user_perms:
            messagebox.showwarning("No Permissions", "The main user has no permissions assigned.")


        if self.anon_enabled_var.get():
            anon_folder = self.anon_folder_var.get().strip()
            if not anon_folder or not os.path.isdir(anon_folder):
                messagebox.showerror("Invalid Anonymous Folder", "Please select a valid folder for anonymous access or disable it.")
                return False
            anon_perms = self._get_permissions_string(self.anon_perm_vars)
            if not anon_perms:
                messagebox.showwarning("No Anon Permissions", "Anonymous access is enabled but has no permissions assigned.")

        if self.ftps_enabled_var.get():
            cert = self.cert_file_var.get().strip()
            key = self.key_file_var.get().strip()
            if not cert or not os.path.isfile(cert):
                messagebox.showerror("Invalid Certificate", "FTPS enabled: Certificate file not found or invalid.")
                return False
            if not key or not os.path.isfile(key):
                messagebox.showerror("Invalid Key", "FTPS enabled: Private key file not found or invalid.")
                return False
        return True

    def log(self, message: str, level: str = "INFO") -> None:
        """Logs a message to the text widget with a timestamp and level."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted_message)
        
        # Basic color coding for levels (can be expanded)
        tag_name = f"level_{level.lower()}"
        self.log_text.tag_configure(tag_name, foreground=TEXT_COLOR) # Default
        if level == "ERROR":
            self.log_text.tag_configure(tag_name, foreground=ERROR_COLOR)
        elif level == "WARNING":
            self.log_text.tag_configure(tag_name, foreground=WARNING_COLOR)
        elif level == "SUCCESS":
            self.log_text.tag_configure(tag_name, foreground=SUCCESS_COLOR)

        self.log_text.tag_add(tag_name, f"end-{len(formatted_message)+1}c", "end-1c")
        
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log("Log cleared.")

    def start_server(self) -> None:
        """Validates inputs and starts the FTP server in a new thread."""
        if not self.validate_inputs():
            return

        if self.is_server_running:
            self.log("Server is already running.", "WARNING")
            return

        ip = self.ip_var.get().strip()
        port = int(self.port_var.get().strip())
        username = self.user_var.get().strip()
        password = self.pass_var.get() # Get raw password
        user_permissions = self._get_permissions_string(self.user_perm_vars)
        shared_folder = self.folder_var.get().strip()
        banner = self.banner_var.get().strip()

        anon_enabled = self.anon_enabled_var.get()
        anon_folder = self.anon_folder_var.get().strip() if anon_enabled else None
        anon_permissions = self._get_permissions_string(self.anon_perm_vars) if anon_enabled else None
        
        ftps_enabled = self.ftps_enabled_var.get()
        cert_file = self.cert_file_var.get().strip() if ftps_enabled else None
        key_file = self.key_file_var.get().strip() if ftps_enabled else None

        self.server_thread = threading.Thread(target=self._run_server,
                                              args=(ip, port, username, password, user_permissions, shared_folder, banner,
                                                    anon_enabled, anon_folder, anon_permissions,
                                                    ftps_enabled, cert_file, key_file), daemon=True)
        self.server_thread.start()

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.save_config_button.config(state=tk.DISABLED) # Disable saving while server is running
        self.status_var.set("Server is starting...")
        self.status_label.config(fg=WARNING_COLOR)
        self.root.update_idletasks()


    def _run_server(self, ip: str, port: int, username: str, password: str, user_perms: str, shared_folder: str, banner: str,
                    anon_enabled: bool, anon_folder: str | None, anon_perms: str | None,
                    ftps_enabled: bool, cert_file: str | None, key_file: str | None) -> None:
        """The actual server execution logic (runs in a thread)."""
        try:
            authorizer = DummyAuthorizer()
            if username: # Only add user if username is provided
                authorizer.add_user(username, password, shared_folder, perm=user_perms)
            else: # If main user is blank, maybe we only want anonymous
                if not anon_enabled:
                    self.root.after(0, self.log, "No authenticated user and anonymous access is disabled. Server won't accept logins.", "ERROR")
                    self.root.after(0, self._server_start_failed)
                    return


            if anon_enabled and anon_folder and anon_perms:
                try:
                    authorizer.add_anonymous(anon_folder, perm=anon_perms)
                except Exception as e: # Catch issues with anonymous setup specifically
                    self.root.after(0, self.log, f"Failed to setup anonymous user: {e}", "ERROR")
                    # Optionally, decide if server should still start without anonymous
            
            handler_class = FTPHandler
            if ftps_enabled and cert_file and key_file:
                handler_class = TLS_FTPHandler
                handler_class.certfile = cert_file
                handler_class.keyfile = key_file
                # For FTPS (explicit FTPS using PROT P)
                handler_class.tls_control_required = True
                handler_class.tls_data_required = True
                # Or for FTPES (AUTH TLS) - more common
                # handler.tls_control_required = False 
                # handler.tls_data_required = False # Client can choose to encrypt data channel

            handler_class.authorizer = authorizer
            if banner:
                handler_class.banner = banner
            
            # Add a custom on_login to log successful logins
            def custom_on_login(username_logged_in):
                self.root.after(0, self.log, f"User '{username_logged_in}' logged in from {handler_class.remote_ip}", "SUCCESS")
            handler_class.on_login = custom_on_login

            # Add a custom on_login_failed to log failed attempts
            def custom_on_login_failed(username_failed, password_failed, error_reason):
                 self.root.after(0, self.log, f"Login failed for '{username_failed}'. Reason: {error_reason}. IP: {handler_class.remote_ip}", "WARNING")
            handler_class.on_login_failed = custom_on_login_failed


            self.server = FTPServer((ip, port), handler_class)
            self.server.max_cons = 256
            self.server.max_cons_per_ip = 5

            self.is_server_running = True
            self.root.after(0, self._server_started_successfully, ip, port, ftps_enabled)
            self.server.serve_forever()

        except socket.error as e:
            if e.errno == socket.errno.EADDRINUSE: # type: ignore
                self.root.after(0, self.log, f"Error: Port {port} on IP {ip} is already in use.", "ERROR")
            else:
                self.root.after(0, self.log, f"Network Error starting server: {e}", "ERROR")
            self.root.after(0, self._server_start_failed)
        except AuthenticationFailed as e: # Should be caught by authorizer, but just in case
             self.root.after(0, self.log, f"Authentication setup error: {e}", "ERROR")
             self.root.after(0, self._server_start_failed)
        except Exception as e:
            self.root.after(0, self.log, f"Critical error starting server: {e}", "ERROR")
            import traceback
            self.root.after(0, self.log, traceback.format_exc(), "ERROR")
            self.root.after(0, self._server_start_failed)
        finally:
            # This block executes when serve_forever() returns (i.e., server stops)
            if self.is_server_running: # If it was running and stopped gracefully
                self.root.after(0, self._server_stopped_ui_update)


    def _server_started_successfully(self, ip: str, port: int, ftps: bool) -> None:
        """UI updates when server starts successfully."""
        protocol = "FTPS" if ftps else "FTP"
        self.log(f"{protocol} Server started on {ip}:{port}", "SUCCESS")
        self.log(f"Main shared folder: {self.folder_var.get().strip()}")
        if self.user_var.get().strip():
             self.log(f"User '{self.user_var.get().strip()}' configured with permissions: {self._get_permissions_string(self.user_perm_vars)}")
        if self.anon_enabled_var.get():
            self.log(f"Anonymous access enabled. Folder: {self.anon_folder_var.get().strip()}, Perms: {self._get_permissions_string(self.anon_perm_vars)}")
        self.status_var.set(f"{protocol} Server is running")
        self.status_label.config(fg=SUCCESS_COLOR)


    def _server_start_failed(self) -> None:
        """UI updates when server fails to start."""
        self.is_server_running = False
        self.server = None
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.save_config_button.config(state=tk.NORMAL)
        self.status_var.set("Server start failed.")
        self.status_label.config(fg=ERROR_COLOR)

    def stop_server(self) -> None:
        """Stops the FTP server if it's running."""
        if self.server and self.is_server_running:
            self.log("Stopping server...", "INFO")
            try:
                self.server.close_all() # This makes serve_forever() return
                # The actual UI update to "stopped" state happens in _run_server's finally block
                # or _server_stopped_ui_update if close_all is called from here.
            except Exception as e:
                self.log(f"Error during server shutdown: {e}", "ERROR")
            # Force UI update if thread doesn't exit quickly
            self._server_stopped_ui_update()
        else:
            self.log("Server is not running or already stopping.", "WARNING")
            self._server_stopped_ui_update() # Ensure UI is correct


    def _server_stopped_ui_update(self) -> None:
        """Updates UI elements when the server is confirmed stopped."""
        self.is_server_running = False
        self.server = None # Clear server instance
        if self.server_thread and self.server_thread.is_alive():
             # It's good practice to join, but daemon=True means it won't block exit
             # self.server_thread.join(timeout=1.0) # Give it a moment
             pass # Daemon thread will exit
        self.server_thread = None

        self.log("Server stopped.", "INFO")
        self.status_var.set("Server is stopped.")
        self.status_label.config(fg=WARNING_COLOR)
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.save_config_button.config(state=tk.NORMAL) # Re-enable saving
        self.root.update_idletasks()

    def _on_closing(self) -> None:
        """Handles window close event."""
        if self.is_server_running:
            if messagebox.askyesno("Server Running", "The FTP server is still running. Do you want to stop it and exit?"):
                self.stop_server()
                # Wait a bit for server to stop if stop_server is async
                self.root.after(500, self._save_and_destroy)
            else:
                return # Don't close
        else:
            self._save_and_destroy()

    def _save_and_destroy(self) -> None:
        """Saves config and destroys the root window."""
        self._save_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    # Attempt to set an icon (provide your own ftp_icon.ico or remove this)
    try:
        # For Windows:
        if sys.platform == "win32":
            # Try loading from script directory or a common location
            icon_path = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'ftp_icon.ico')
            if os.path.exists(icon_path):
                 root.iconbitmap(icon_path)
            else: # Fallback for bundled app
                pass # No icon if not found
        # For Linux (requires Tk 8.6+ for .png, or use .xbm for older)
        # elif sys.platform.startswith("linux"):
        #     icon_path = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'ftp_icon.png')
        #     if os.path.exists(icon_path):
        #         img = tk.PhotoImage(file=icon_path)
        #         root.tk.call('wm', 'iconphoto', root._w, img)
    except Exception as e:
        print(f"Could not set window icon: {e}") # Non-critical

    app = FTPServerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()