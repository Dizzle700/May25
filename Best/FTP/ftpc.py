import os
import sys
import socket
import ftplib
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import ipaddress

class FTPClient:
    def __init__(self, root):
        self.root = root
        self.root.title("Comfy FTP Client")
        self.root.geometry("800x500")  # Reduced size for compactness
        self.root.configure(bg="#2E3440")
        
        self.colors = {
            "bg": "#2E3440", "fg": "#ECEFF4", "highlight": "#5E81AC",
            "accent": "#88C0D0", "success": "#A3BE8C", "error": "#BF616A",
            "warning": "#EBCB8B"
        }
        
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["fg"])
        self.style.configure("TButton", background=self.colors["highlight"], foreground=self.colors["fg"])
        self.style.map("TButton", background=[("active", self.colors["accent"])])
        self.style.configure("TEntry", fieldbackground=self.colors["bg"], foreground=self.colors["fg"],
                           insertcolor=self.colors["fg"])
        self.style.configure("Treeview", background=self.colors["bg"], foreground=self.colors["fg"],
                           fieldbackground=self.colors["bg"])
        self.style.map("Treeview", background=[("selected", self.colors["highlight"])])
        
        self.ftp = None
        self.current_dir = "/"
        self.upload_progress = None
        self.download_progress = None
        
        self.create_widgets()
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)  # Reduced padding
        
        # Connection frame
        conn_frame = ttk.Frame(main_frame)
        conn_frame.pack(fill=tk.X)
        
        ttk.Label(conn_frame, text="Host:").pack(side=tk.LEFT, padx=2)
        self.host_entry = ttk.Entry(conn_frame, width=15)
        self.host_entry.insert(0, "192.168.1.10")
        self.host_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn_frame, text="Port:").pack(side=tk.LEFT, padx=2)
        self.port_entry = ttk.Entry(conn_frame, width=5)
        self.port_entry.insert(0, "2121")
        self.port_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn_frame, text="User:").pack(side=tk.LEFT, padx=2)
        self.username_entry = ttk.Entry(conn_frame, width=15)
        self.username_entry.insert(0, "pc")
        self.username_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn_frame, text="Pass:").pack(side=tk.LEFT, padx=2)
        self.password_entry = ttk.Entry(conn_frame, width=15, show="•")
        self.password_entry.pack(side=tk.LEFT, padx=2)
        
        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=2)
        
        self.disconnect_btn = ttk.Button(conn_frame, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=2)
        
        self.scan_btn = ttk.Button(conn_frame, text="Scan", command=self.scan_network)
        self.scan_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn_frame, text="Network:").pack(side=tk.LEFT, padx=2)
        self.network_entry = ttk.Entry(conn_frame, width=15)
        self.network_entry.insert(0, "192.168.1.0/24")
        self.network_entry.pack(side=tk.LEFT, padx=2)
        
        # File browser frame
        browser_frame = ttk.Frame(main_frame)
        browser_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Local files
        local_frame = ttk.Frame(browser_frame)
        local_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Label(local_frame, text="Local:").pack(anchor=tk.W)
        local_path_frame = ttk.Frame(local_frame)
        local_path_frame.pack(fill=tk.X)
        
        self.local_path_entry = ttk.Entry(local_path_frame)
        self.local_path_entry.insert(0, os.path.expanduser("~"))
        self.local_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.browse_btn = ttk.Button(local_path_frame, text="Browse", command=self.browse_local)
        self.browse_btn.pack(side=tk.RIGHT, padx=2)
        
        self.local_tree = ttk.Treeview(local_frame, columns=("size", "modified"), height=10)
        self.local_tree.heading("#0", text="Name")
        self.local_tree.heading("size", text="Size")
        self.local_tree.heading("modified", text="Modified")
        self.local_tree.column("#0", width=150)
        self.local_tree.column("size", width=60)
        self.local_tree.column("modified", width=100)
        self.local_tree.pack(fill=tk.BOTH, expand=True)
        self.local_tree.bind("<Double-1>", self.on_local_double_click)
        
        # Remote files
        remote_frame = ttk.Frame(browser_frame)
        remote_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        ttk.Label(remote_frame, text="Remote:").pack(anchor=tk.W)
        remote_path_frame = ttk.Frame(remote_frame)
        remote_path_frame.pack(fill=tk.X)
        
        self.remote_path_entry = ttk.Entry(remote_path_frame)
        self.remote_path_entry.insert(0, "/")
        self.remote_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.refresh_btn = ttk.Button(remote_path_frame, text="Refresh", command=self.refresh_remote)
        self.refresh_btn.pack(side=tk.RIGHT, padx=2)
        
        self.remote_tree = ttk.Treeview(remote_frame, columns=("size", "modified"), height=10)
        self.remote_tree.heading("#0", text="Name")
        self.remote_tree.heading("size", text="Size")
        self.remote_tree.heading("modified", text="Modified")
        self.remote_tree.column("#0", width=150)
        self.remote_tree.column("size", width=60)
        self.remote_tree.column("modified", width=100)
        self.remote_tree.pack(fill=tk.BOTH, expand=True)
        self.remote_tree.bind("<Double-1>", self.on_remote_double_click)
        
        # Transfer frame
        transfer_frame = ttk.Frame(main_frame)
        transfer_frame.pack(fill=tk.X, pady=2)
        
        self.upload_btn = ttk.Button(transfer_frame, text="Upload", command=self.upload, state=tk.DISABLED)
        self.upload_btn.pack(side=tk.LEFT, padx=2)
        
        self.upload_progress = ttk.Progressbar(transfer_frame, mode="determinate", length=100)
        self.upload_progress.pack(side=tk.LEFT, padx=2)
        self.upload_percent = tk.StringVar(value="0%")
        ttk.Label(transfer_frame, textvariable=self.upload_percent).pack(side=tk.LEFT)
        
        self.download_btn = ttk.Button(transfer_frame, text="Download", command=self.download, state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=2)
        
        self.download_progress = ttk.Progressbar(transfer_frame, mode="determinate", length=100)
        self.download_progress.pack(side=tk.LEFT, padx=2)
        self.download_percent = tk.StringVar(value="0%")
        ttk.Label(transfer_frame, textvariable=self.download_percent).pack(side=tk.LEFT)
        
        # Log
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.X)
        
        ttk.Label(log_frame, text="Log:").pack(anchor=tk.W)
        self.log_text = ScrolledText(log_frame, height=4, bg=self.colors["bg"], fg=self.colors["fg"],
                                   insertbackground=self.colors["fg"])
        self.log_text.pack(fill=tk.X)
        self.log_text.config(state=tk.DISABLED)
        
        self.refresh_local()
    
    def log(self, message, level="info"):
        self.log_text.config(state=tk.NORMAL)
        tag = level if level in ["success", "error", "warning"] else None
        if tag:
            self.log_text.tag_configure(tag, foreground=self.colors[tag])
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def connect(self):
        host = self.host_entry.get()
        port = int(self.port_entry.get())
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        if not host:
            messagebox.showerror("Error", "Host cannot be empty")
            return
        
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(host, port)
            self.ftp.login(username, password)
            self.log(f"Connected to {host}:{port}", "success")
            self.current_dir = self.ftp.pwd()
            self.remote_path_entry.delete(0, tk.END)
            self.remote_path_entry.insert(0, self.current_dir)
            
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.upload_btn.config(state=tk.NORMAL)
            self.download_btn.config(state=tk.NORMAL)
            self.refresh_remote()
        except Exception as e:
            self.log(f"Connection error: {str(e)}", "error")
    
    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass
            self.ftp = None
            self.log("Disconnected")
            for item in self.remote_tree.get_children():
                self.remote_tree.delete(item)
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.upload_btn.config(state=tk.DISABLED)
            self.download_btn.config(state=tk.DISABLED)
    
    def browse_local(self):
        directory = filedialog.askdirectory(initialdir=self.local_path_entry.get())
        if directory:
            self.local_path_entry.delete(0, tk.END)
            self.local_path_entry.insert(0, directory)
            self.refresh_local()
    
    def refresh_local(self):
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)
        
        path = self.local_path_entry.get()
        try:
            if os.path.dirname(path) != path:
                self.local_tree.insert("", "end", text="..", values=("", ""), tags=("dir",))
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                stat_info = os.stat(item_path)
                modified = f"{stat_info.st_mtime:.0f}"
                size = f"{stat_info.st_size:,}" if os.path.isfile(item_path) else ""
                tag = "file" if os.path.isfile(item_path) else "dir"
                self.local_tree.insert("", "end", text=item, values=(size, modified), tags=(tag,))
        except Exception as e:
            self.log(f"Error accessing {path}: {str(e)}", "error")
    
    def refresh_remote(self):
        if not self.ftp:
            return
        for item in self.remote_tree.get_children():
            self.remote_tree.delete(item)
        
        try:
            if self.current_dir != "/":
                self.remote_tree.insert("", "end", text="..", values=("", ""), tags=("dir",))
            file_list = []
            self.ftp.dir(file_list.append)
            for line in file_list:
                parts = line.split(maxsplit=8)
                if len(parts) < 9:
                    continue
                name = parts[8]
                size = parts[4] if not parts[0].startswith('d') else ""
                date = ' '.join(parts[5:8])
                tag = "dir" if parts[0].startswith('d') else "file"
                self.remote_tree.insert("", "end", text=name, values=(size, date), tags=(tag,))
            self.log(f"Refreshed {self.current_dir}")
        except Exception as e:
            self.log(f"Error refreshing: {str(e)}", "error")
    
    def on_local_double_click(self, event):
        item = self.local_tree.selection()[0]
        item_text = self.local_tree.item(item, "text")
        if "dir" in self.local_tree.item(item, "tags"):
            new_path = os.path.dirname(self.local_path_entry.get()) if item_text == ".." else \
                      os.path.join(self.local_path_entry.get(), item_text)
            self.local_path_entry.delete(0, tk.END)
            self.local_path_entry.insert(0, new_path)
            self.refresh_local()
    
    def on_remote_double_click(self, event):
        if not self.ftp:
            return
        item = self.remote_tree.selection()[0]
        item_text = self.remote_tree.item(item, "text")
        if "dir" in self.remote_tree.item(item, "tags"):
            try:
                self.ftp.cwd(".." if item_text == ".." else item_text)
                self.current_dir = self.ftp.pwd()
                self.remote_path_entry.delete(0, tk.END)
                self.remote_path_entry.insert(0, self.current_dir)
                self.refresh_remote()
            except Exception as e:
                self.log(f"Error changing dir: {str(e)}", "error")
    
    def upload(self):
        if not self.ftp:
            self.log("Not connected", "warning")
            return
        items = self.local_tree.selection()
        if not items:
            messagebox.showinfo("Info", "Select a file to upload")
            return
        self.upload_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.do_upload, args=(items,), daemon=True).start()
    
    def do_upload(self, items):
        for item in items:
            item_text = self.local_tree.item(item, "text")
            if item_text == ".." or "dir" in self.local_tree.item(item, "tags"):
                continue
            local_path = os.path.join(self.local_path_entry.get(), item_text)
            try:
                file_size = os.path.getsize(local_path)
                self.upload_progress["maximum"] = file_size
                self.upload_progress["value"] = 0
                self.upload_percent.set("0%")
                
                def callback(block):
                    self.upload_progress["value"] += len(block)
                    percent = int((self.upload_progress["value"] / file_size) * 100)
                    self.root.after(0, lambda: self.upload_percent.set(f"{percent}%"))
                
                with open(local_path, 'rb') as file:
                    self.log(f"Uploading {item_text}...")
                    self.ftp.storbinary(f'STOR {item_text}', file, callback=callback)
                    self.log(f"Uploaded {item_text}", "success")
                self.root.after(0, self.refresh_remote)
            except Exception as e:
                self.log(f"Error uploading {item_text}: {str(e)}", "error")
            finally:
                self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.upload_percent.set("0%"))
    
    def download(self):
        if not self.ftp:
            self.log("Not connected", "warning")
            return
        items = self.remote_tree.selection()
        if not items:
            messagebox.showinfo("Info", "Select a file to download")
            return
        self.download_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.do_download, args=(items,), daemon=True).start()
    
    def do_download(self, items):
        for item in items:
            item_text = self.remote_tree.item(item, "text")
            if item_text == ".." or "dir" in self.remote_tree.item(item, "tags"):
                continue
            local_path = os.path.join(self.local_path_entry.get(), item_text)
            try:
                size_str = self.remote_tree.item(item, "values")[0]
                file_size = int(''.join(filter(str.isdigit, size_str))) if size_str else 0
                self.download_progress["maximum"] = file_size or 1000000  # Fallback size
                self.download_progress["value"] = 0
                self.download_percent.set("0%")
                
                def callback(block):
                    self.download_progress["value"] += len(block)
                    percent = int((self.download_progress["value"] / self.download_progress["maximum"]) * 100)
                    self.root.after(0, lambda: self.download_percent.set(f"{percent}%"))
                
                with open(local_path, 'wb') as file:
                    self.log(f"Downloading {item_text}...")
                    self.ftp.retrbinary(f'RETR {item_text}', lambda b: [file.write(b), callback(b)])
                    self.log(f"Downloaded {item_text}", "success")
                self.root.after(0, self.refresh_local)
            except Exception as e:
                self.log(f"Error downloading {item_text}: {str(e)}", "error")
            finally:
                self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.download_percent.set("0%"))
    
    def scan_network(self):
        network_range = self.network_entry.get()
        self.log(f"Scanning {network_range}...")
        threading.Thread(target=self.do_scan, args=(network_range,), daemon=True).start()
    
    def do_scan(self, network_range):
        try:
            network = ipaddress.ip_network(network_range, strict=False)
            scan_dialog = tk.Toplevel(self.root)
            scan_dialog.title("Scan Results")
            scan_dialog.geometry("400x300")
            scan_dialog.configure(bg=self.colors["bg"])
            
            scan_tree = ttk.Treeview(scan_dialog, columns=("port", "banner"), height=10)
            scan_tree.heading("#0", text="Host")
            scan_tree.heading("port", text="Port")
            scan_tree.heading("banner", text="Banner")
            scan_tree.column("#0", width=100)
            scan_tree.column("port", width=50)
            scan_tree.column("banner", width=200)
            scan_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            status_var = tk.StringVar(value="Scanning...")
            ttk.Label(scan_dialog, textvariable=status_var).pack(pady=2)
            
            progress = ttk.Progressbar(scan_dialog, mode="determinate")
            progress.pack(fill=tk.X, padx=5)
            total_hosts = sum(1 for _ in network.hosts())
            progress["maximum"] = total_hosts
            
            def on_select():
                selection = scan_tree.selection()
                if selection:
                    host = scan_tree.item(selection[0], "text")
                    port = scan_tree.item(selection[0], "values")[0]
                    self.host_entry.delete(0, tk.END)
                    self.host_entry.insert(0, host)
                    self.port_entry.delete(0, tk.END)
                    self.port_entry.insert(0, port)
                    scan_dialog.destroy()
            
            ttk.Button(scan_dialog, text="Select", command=on_select).pack(pady=2)
            
            found_count = 0
            for i, host in enumerate(network.hosts(), 1):
                host_str = str(host)
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    if s.connect_ex((host_str, 21)) == 0:
                        banner = "Unknown"
                        try:
                            ftp = ftplib.FTP()
                            ftp.connect(host_str, 21, timeout=2)
                            banner = ftp.getwelcome()
                            ftp.close()
                        except:
                            pass
                        scan_tree.insert("", "end", text=host_str, values=("21", banner))
                        found_count += 1
                        self.log(f"Found FTP at {host_str}:21", "success")
                    s.close()
                except:
                    pass
                progress["value"] = i
                status_var.set(f"Scanned: {i}/{total_hosts} - Found: {found_count}")
                scan_dialog.update()
            
            status_var.set(f"Done. Found {found_count} FTP servers.")
        except Exception as e:
            self.log(f"Scan error: {str(e)}", "error")

if __name__ == "__main__":
    root = tk.Tk()
    app = FTPClient(root)
    root.mainloop()