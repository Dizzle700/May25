import os
import sys
import socket
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
import ipaddress

class FTPServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FTP Server")
        self.root.geometry("500x450")  # Reduced window size
        self.root.resizable(True, True)
        
        # Updated color scheme
        self.bg_color = "#1a1a2e"  # Dark navy blue
        self.text_color = "#ffffff"  # White
        self.entry_bg = "#16213e"  # Slightly lighter navy
        self.accent_color = "#4f8a8b"  # Teal
        self.success_color = "#57cc99"  # Mint green
        self.warning_color = "#fb8b24"  # Orange
        
        self.root.configure(bg=self.bg_color)
        
        self.server = None
        self.server_thread = None
        self.is_server_running = False
        
        self.create_widgets()
        
    def create_widgets(self):
        # Main frame with less padding
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title - more compact
        title_label = tk.Label(main_frame, text="FTP Server Control", 
                              font=("Helvetica", 14, "bold"), 
                              bg=self.bg_color, fg=self.text_color)
        title_label.pack(pady=(0, 10))
        
        # Use a more compact grid layout
        settings_frame = tk.Frame(main_frame, bg=self.bg_color)
        settings_frame.pack(fill=tk.X, pady=5)
        
        # Two-column grid layout for settings
        # Row 0: IP and Port
        tk.Label(settings_frame, text="IP:", bg=self.bg_color, fg=self.text_color, width=8, anchor="e").grid(row=0, column=0, sticky="e", padx=2, pady=2)
        local_ip = self.get_local_ip()
        self.ip_var = tk.StringVar(value=local_ip)
        tk.Entry(settings_frame, textvariable=self.ip_var, bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color, width=15).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        
        tk.Label(settings_frame, text="Port:", bg=self.bg_color, fg=self.text_color, width=5, anchor="e").grid(row=0, column=2, sticky="e", padx=2, pady=2)
        self.port_var = tk.StringVar(value="2121")
        tk.Entry(settings_frame, textvariable=self.port_var, bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color, width=8).grid(row=0, column=3, sticky="ew", padx=2, pady=2)
        
        # Row 1: Username and Password
        tk.Label(settings_frame, text="Username:", bg=self.bg_color, fg=self.text_color, width=8, anchor="e").grid(row=1, column=0, sticky="e", padx=2, pady=2)
        self.user_var = tk.StringVar(value="user")
        tk.Entry(settings_frame, textvariable=self.user_var, bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        
        tk.Label(settings_frame, text="Password:", bg=self.bg_color, fg=self.text_color, width=5, anchor="e").grid(row=1, column=2, sticky="e", padx=2, pady=2)
        self.pass_var = tk.StringVar(value="480")
        tk.Entry(settings_frame, textvariable=self.pass_var, show="*", bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color).grid(row=1, column=3, sticky="ew", padx=2, pady=2)
        
        # Row 2: Permissions
        tk.Label(settings_frame, text="Permissions:", bg=self.bg_color, fg=self.text_color, width=8, anchor="e").grid(row=2, column=0, sticky="e", padx=2, pady=2)
        self.perm_var = tk.StringVar(value="elradfmw")
        tk.Entry(settings_frame, textvariable=self.perm_var, bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color).grid(row=2, column=1, columnspan=3, sticky="ew", padx=2, pady=2)
        
        # Shared folder section - more compact
        folder_frame = tk.Frame(main_frame, bg=self.bg_color)
        folder_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(folder_frame, text="Shared Folder:", bg=self.bg_color, fg=self.text_color).pack(side=tk.LEFT, padx=2)
        self.folder_var = tk.StringVar()
        folder_entry = tk.Entry(folder_frame, textvariable=self.folder_var, bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        browse_button = tk.Button(folder_frame, text="Browse", 
                                command=self.browse_folder, 
                                bg=self.accent_color, fg=self.text_color,
                                activebackground="#3a686a", activeforeground=self.text_color,
                                bd=0, padx=5)
        browse_button.pack(side=tk.RIGHT, padx=2)
        
        # Configure column weights for proper expansion
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)
        
        # Status and log area - made taller
        log_frame = tk.LabelFrame(main_frame, text="Server Log", 
                                font=("Helvetica", 10), 
                                bg=self.bg_color, fg=self.text_color, padx=5, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, 
                              bg=self.entry_bg, fg=self.text_color, insertbackground=self.text_color,
                              wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Control buttons and status - in single row
        button_frame = tk.Frame(main_frame, bg=self.bg_color)
        button_frame.pack(fill=tk.X, pady=5)
        
        self.start_button = tk.Button(button_frame, text="Start Server", 
                                    command=self.start_server, 
                                    bg=self.success_color, fg="#000000",  # Black text on green
                                    activebackground="#46a37a", activeforeground="#000000",
                                    bd=0, padx=10, pady=3, width=12)
        self.start_button.pack(side=tk.LEFT, padx=2)
        
        self.stop_button = tk.Button(button_frame, text="Stop Server", 
                                   command=self.stop_server, 
                                   bg=self.warning_color, fg="#000000",  # Black text on orange
                                   activebackground="#c87019", activeforeground="#000000",
                                   bd=0, padx=10, pady=3, width=12, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=2)
        
        # Status indicator - store reference to the label widget
        self.status_var = tk.StringVar(value="Server is stopped")
        self.status_label = tk.Label(button_frame, textvariable=self.status_var, 
                              bg=self.bg_color, fg=self.warning_color,
                              font=("Helvetica", 9, "bold"))
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # Add initial log message
        self.log("FTP Server ready. Select a folder and configure settings.")
    
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def browse_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.folder_var.set(folder_path)
            self.log(f"Selected folder: {folder_path}")
    
    def validate_inputs(self):
        # Validate IP
        ip = self.ip_var.get().strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            messagebox.showerror("Invalid IP", "Please enter a valid IP address.")
            return False
        
        # Validate port
        port = self.port_var.get().strip()
        try:
            port_num = int(port)
            if port_num < 1 or port_num > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a number between 1-65535.")
            return False
        
        # Validate folder
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Invalid Folder", "Please select a valid folder to share.")
            return False
        
        return True
    
    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def start_server(self):
        if not self.validate_inputs():
            return
        
        if self.is_server_running:
            self.log("Server is already running.")
            return
        
        # Get values from inputs
        ip = self.ip_var.get().strip()
        port = int(self.port_var.get().strip())
        username = self.user_var.get().strip()
        password = self.pass_var.get().strip()
        permissions = self.perm_var.get().strip()
        shared_folder = self.folder_var.get().strip()
        
        # Start server in a separate thread
        self.server_thread = threading.Thread(target=self._run_server, 
                                            args=(ip, port, username, password, permissions, shared_folder))
        self.server_thread.daemon = True
        self.server_thread.start()
        
        # Update UI
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Server is running")
        self.root.update_idletasks()
    
    def _run_server(self, ip, port, username, password, permissions, shared_folder):
        try:
            # Create authorizer
            authorizer = DummyAuthorizer()
            authorizer.add_user(username, password, shared_folder, perm=permissions)
            
            # Create handler
            handler = FTPHandler
            handler.authorizer = authorizer
            
            # Create server
            self.server = FTPServer((ip, port), handler)
            
            # Update UI from the main thread
            self.root.after(0, self.log, f"Server started on {ip}:{port}")
            self.root.after(0, self.log, f"Shared folder: {shared_folder}")
            self.root.after(0, self.log, f"Username: {username}, Password: {password}")
            self.root.after(0, self.log, "FTP server is now running.")
            self.root.after(0, lambda: self.status_label.configure(fg=self.success_color))
            
            # Set flag
            self.is_server_running = True
            
            # Serve forever (until stopped)
            self.server.serve_forever()
            
        except Exception as e:
            # Update UI from the main thread
            self.root.after(0, self.log, f"Error starting server: {str(e)}")
            self.root.after(0, self.stop_server)
    
    def stop_server(self):
        if self.server and self.is_server_running:
            # Stop the server
            self.server.close_all()
            
            # Update UI
            self.log("Server stopped.")
            self.status_var.set("Server is stopped")
            self.status_label.configure(fg=self.warning_color)
            
            # Reset buttons
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            
            # Reset flag
            self.is_server_running = False
        else:
            self.log("No server is running.")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)

def main():
    root = tk.Tk()
    app = FTPServerGUI(root)
    
    # Set icon
    try:
        # Try to use a predefined icon if available
        root.iconbitmap("ftp_icon.ico")
    except:
        pass
    
    root.mainloop()

if __name__ == "__main__":
    main()