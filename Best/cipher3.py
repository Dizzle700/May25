import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import secrets
import threading
import time
import hashlib
import json
import datetime

# --- Constants ---
BG_COLOR = "#2c3e50"
ACCENT_COLOR = "#3498db"
TEXT_COLOR = "#ecf0f1"
BUTTON_COLOR = "#2980b9"
ENTRY_BG_COLOR = "#34495e"
SUCCESS_COLOR = "#27ae60"
ERROR_COLOR = "#e74c3c"
WARN_COLOR = "#f39c12" # Orange
GOOD_COLOR = "#f1c40f" # Yellow
STRONG_COLOR = "#2ecc71" # Light Green

SALT_SIZE = 16
KEY_LENGTH = 32
PBKDF2_ITERATIONS = 310000 # Increased iterations (OWASP recommendation ~2023)
HASH_ALGORITHM = hashlib.sha256 # Algorithm for integrity check
CHUNK_SIZE = 1024 * 1024 # 1MB for progress updates
METADATA_SEPARATOR = b'::META_SEP::' # Separator between metadata and content

STATUS_READY = "Ready"
STATUS_SELECT_FILE = "Please select a file."
STATUS_ENTER_PASS = "Please enter and confirm password."
STATUS_PASS_MISMATCH = "Passwords do not match."
STATUS_ENCRYPTING = "Encrypting..."
STATUS_DECRYPTING = "Decrypting..."
STATUS_GENERATING_KEY = "Generating key..."
STATUS_READING = "Reading file..."
STATUS_WRITING = "Writing file..."
STATUS_CALCULATING_HASH = "Calculating hash..."
STATUS_VERIFYING = "Verifying integrity..."
STATUS_CREATING_BACKUP = "Creating backup..."
STATUS_DELETING = "Deleting original..."
STATUS_ENCRYPT_SUCCESS = "✓ File encrypted successfully!"
STATUS_DECRYPT_SUCCESS = "✓ File decrypted successfully!"
STATUS_DECRYPT_HASH_MATCH = "✓ File decrypted successfully! Integrity check passed."
STATUS_DECRYPT_HASH_MISMATCH = "✗ WARNING: File decrypted, but integrity check FAILED! File may be corrupt or tampered with."
STATUS_ERROR_PREFIX = "✗ Error: "


class ModernCryptoApp:
    """
    A Tkinter application for securely encrypting and decrypting files
    using Fernet symmetric encryption with PBKDF2 key derivation and
    file integrity checking.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("Secure File Encryptor/Decryptor")
        self.root.geometry("550x750") # Increased height for confirm password
        self.root.resizable(False, False)
        self.root.configure(bg=BG_COLOR)

        self.selected_file = None
        self.is_processing = False

        self._setup_ui()
        self._update_button_states() # Initial state check

    def _setup_ui(self):
        """Creates and arranges all UI elements."""
        self.main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        self.main_frame.pack(fill="both", expand=True)

        # --- Title ---
        title_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        title_frame.pack(fill="x", pady=10)
        lock_icon = "🔒"
        self.title_label = tk.Label(
            title_frame,
            text=f"{lock_icon} Secure File Processor {lock_icon}",
            font=("Helvetica", 18, "bold"), bg=BG_COLOR, fg=TEXT_COLOR
        )
        self.title_label.pack()

        # --- File Selection ---
        file_frame = tk.LabelFrame(
            self.main_frame, text="File Selection", font=("Helvetica", 12),
            bg=BG_COLOR, fg=TEXT_COLOR, padx=10, pady=10
        )
        file_frame.pack(fill="x", pady=10)

        self.file_path_var = tk.StringVar(value="No file selected")
        self.file_entry = tk.Entry(
            file_frame, textvariable=self.file_path_var, width=45,
            bg=ENTRY_BG_COLOR, fg=TEXT_COLOR, readonlybackground=ENTRY_BG_COLOR,
            state="readonly"
        )
        self.file_entry.pack(side=tk.LEFT, padx=5, pady=10, fill="x", expand=True)

        self.select_button = tk.Button(
            file_frame, text="Browse", bg=BUTTON_COLOR, fg=TEXT_COLOR,
            activebackground=ACCENT_COLOR, activeforeground="white",
            padx=10, command=self._select_file
        )
        self.select_button.pack(side=tk.RIGHT, padx=5, pady=10)

        # --- Password Section ---
        password_frame = tk.LabelFrame(
            self.main_frame, text="Password", font=("Helvetica", 12),
            bg=BG_COLOR, fg=TEXT_COLOR, padx=10, pady=10
        )
        password_frame.pack(fill="x", pady=10)

        # Password Entry
        tk.Label(password_frame, text="Enter Password:", bg=BG_COLOR, fg=TEXT_COLOR).pack(anchor="w")
        self.password_entry = tk.Entry(
            password_frame, show="•", width=30, bg=ENTRY_BG_COLOR, fg=TEXT_COLOR
        )
        self.password_entry.pack(fill="x", pady=(0, 5))
        self.password_entry.bind("<KeyRelease>", self._check_password_strength)

        # Confirm Password Entry (for encryption)
        tk.Label(password_frame, text="Confirm Password (for encryption):", bg=BG_COLOR, fg=TEXT_COLOR).pack(anchor="w")
        self.confirm_password_entry = tk.Entry(
             password_frame, show="•", width=30, bg=ENTRY_BG_COLOR, fg=TEXT_COLOR
        )
        self.confirm_password_entry.pack(fill="x", pady=(0, 5))
        self.confirm_password_entry.bind("<KeyRelease>", self._update_button_states)


        # Show Password Checkbox
        self.show_password_var = tk.BooleanVar()
        self.show_password_checkbox = tk.Checkbutton(
            password_frame, text="Show password(s)", variable=self.show_password_var,
            command=self._toggle_password_visibility, bg=BG_COLOR, fg=TEXT_COLOR,
            selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
            anchor="w"
        )
        self.show_password_checkbox.pack(fill="x", pady=5)

        # Password Strength Indicator
        self.strength_label = tk.Label(
            password_frame, text="Password Strength: Not Rated", bg=BG_COLOR, fg=TEXT_COLOR
        )
        self.strength_label.pack(anchor="w", pady=5)

        # --- Options Section ---
        options_frame = tk.LabelFrame(
            self.main_frame, text="Options", font=("Helvetica", 12),
            bg=BG_COLOR, fg=TEXT_COLOR, padx=10, pady=10
        )
        options_frame.pack(fill="x", pady=10)

        self.delete_var = tk.BooleanVar()
        self.delete_checkbox = tk.Checkbutton(
            options_frame, text="Delete original file after successful operation",
            variable=self.delete_var, bg=BG_COLOR, fg=TEXT_COLOR,
            selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=TEXT_COLOR, anchor="w"
        )
        self.delete_checkbox.pack(fill="x", pady=2)

        self.backup_var = tk.BooleanVar(value=True) # Default to creating backup
        self.backup_checkbox = tk.Checkbutton(
            options_frame, text="Create backup (.bak) before operation",
            variable=self.backup_var, bg=BG_COLOR, fg=TEXT_COLOR,
            selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=TEXT_COLOR, anchor="w"
        )
        self.backup_checkbox.pack(fill="x", pady=2)

        # --- Action Buttons ---
        buttons_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        buttons_frame.pack(fill="x", pady=10)

        self.encrypt_button = tk.Button(
            buttons_frame, text="🔒 Encrypt File", bg=BUTTON_COLOR, fg=TEXT_COLOR,
            activebackground=ACCENT_COLOR, activeforeground="white",
            padx=20, pady=10, state="disabled", command=self._start_encrypt_thread
        )
        self.encrypt_button.pack(side=tk.LEFT, padx=10, pady=10, expand=True, fill="x")

        self.decrypt_button = tk.Button(
            buttons_frame, text="🔓 Decrypt File", bg=BUTTON_COLOR, fg=TEXT_COLOR,
            activebackground=ACCENT_COLOR, activeforeground="white",
            padx=20, pady=10, state="disabled", command=self._start_decrypt_thread
        )
        self.decrypt_button.pack(side=tk.RIGHT, padx=10, pady=10, expand=True, fill="x")

        # --- Progress Bar ---
        self.progress_var = tk.DoubleVar()
        self.style = ttk.Style()
        # Ensure theme is available, fallback if needed
        try:
            self.style.theme_use('clam') # Or 'alt', 'default', etc.
        except tk.TclError:
            print("Warning: 'clam' theme not found, using default.")
        self.style.configure("TProgressbar", thickness=20, troughcolor=ENTRY_BG_COLOR, background=ACCENT_COLOR)
        self.progress_bar = ttk.Progressbar(
            self.main_frame, variable=self.progress_var, maximum=100,
            mode="determinate", length=460, style="TProgressbar"
        )
        self.progress_bar.pack(fill="x", padx=10, pady=5)

        # --- Status Label ---
        self.status_label = tk.Label(
            self.main_frame, text=STATUS_READY, font=("Helvetica", 10),
            bg=BG_COLOR, fg=TEXT_COLOR, wraplength=500, justify=tk.LEFT
        )
        self.status_label.pack(pady=(5, 10), anchor="w", fill="x", padx=10)

    def _update_ui(self, progress=None, status=None, status_color=None):
        """Safely updates UI elements from any thread."""
        def task():
            if progress is not None:
                self.progress_var.set(progress)
            if status is not None:
                self.status_label.config(text=status, fg=status_color or TEXT_COLOR)
            self.root.update_idletasks()
        # Schedule the UI update on the main Tkinter thread
        self.root.after(0, task)

    def _set_ui_state(self, enabled: bool):
        """Enables or disables interactive UI elements."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.select_button.config(state=state)
        self.password_entry.config(state=state)
        self.confirm_password_entry.config(state=state)
        self.show_password_checkbox.config(state=state)
        self.delete_checkbox.config(state=state)
        self.backup_checkbox.config(state=state)
        # Buttons are handled separately based on other conditions
        if enabled:
            self._update_button_states() # Re-evaluate button states when enabling
        else:
            self.encrypt_button.config(state=tk.DISABLED)
            self.decrypt_button.config(state=tk.DISABLED)
        self.is_processing = not enabled

    def _toggle_password_visibility(self):
        """Toggles visibility of both password fields."""
        show_char = "" if self.show_password_var.get() else "•"
        self.password_entry.config(show=show_char)
        self.confirm_password_entry.config(show=show_char)

    def _check_password_strength(self, event=None):
        """Checks password strength and updates indicator."""
        password = self.password_entry.get()
        strength = 0
        length_ok = len(password) >= 12 # Increased recommended length
        has_digit = any(c.isdigit() for c in password)
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_symbol = any(not c.isalnum() for c in password)

        if length_ok: strength += 1
        if has_digit: strength += 1
        if has_upper and has_lower: strength += 1 # Combined check
        if has_symbol: strength += 1
        if len(password) >= 16: strength += 1 # Bonus for very long

        color = TEXT_COLOR
        if not password:
            text = "Password Strength: Not Rated"
        elif strength == 0:
            text = "Password Strength: Very Weak"
            color = ERROR_COLOR
        elif strength == 1:
            text = "Password Strength: Weak"
            color = ERROR_COLOR
        elif strength == 2:
            text = "Password Strength: Moderate"
            color = WARN_COLOR
        elif strength == 3:
            text = "Password Strength: Good"
            color = GOOD_COLOR
        elif strength == 4:
            text = "Password Strength: Strong"
            color = STRONG_COLOR
        else: # strength == 5
            text = "Password Strength: Very Strong"
            color = SUCCESS_COLOR

        self.strength_label.config(text=text, fg=color)
        self._update_button_states() # Also update buttons on key release

    def _generate_key(self, password: str, salt: bytes) -> bytes:
        """Derives a Fernet key from password and salt using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def _calculate_hash(self, file_path: str) -> str | None:
        """Calculates the SHA-256 hash of a file."""
        try:
            hasher = HASH_ALGORITHM()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            self._update_ui(status=f"{STATUS_ERROR_PREFIX}Failed to calculate hash: {e}", status_color=ERROR_COLOR)
            return None

    def _select_file(self):
        """Opens file dialog and updates selected file path."""
        if self.is_processing: return
        selected = filedialog.askopenfilename()
        if selected:
            self.selected_file = selected
            self.file_path_var.set(os.path.basename(selected))
            self._update_ui(status=f"Selected: {os.path.basename(selected)}")
        else:
            self.selected_file = None
            self.file_path_var.set("No file selected")
            self._update_ui(status=STATUS_READY)
        self._update_button_states()

    def _update_button_states(self, event=None):
        """Enables/disables Encrypt/Decrypt buttons based on inputs."""
        if self.is_processing: return # Don't change state during processing

        file_selected = bool(self.selected_file)
        password = self.password_entry.get()
        confirm_password = self.confirm_password_entry.get()
        password_entered = bool(password)
        passwords_match = (password == confirm_password)

        can_encrypt = file_selected and password_entered and passwords_match
        can_decrypt = file_selected and password_entered

        self.encrypt_button.config(state=tk.NORMAL if can_encrypt else tk.DISABLED)
        self.decrypt_button.config(state=tk.NORMAL if can_decrypt else tk.DISABLED)

        # Update status if passwords don't match for encryption
        if file_selected and password_entered and not passwords_match and self.confirm_password_entry.get():
             self._update_ui(status=STATUS_PASS_MISMATCH, status_color=WARN_COLOR)
        elif not file_selected:
             self._update_ui(status=STATUS_SELECT_FILE, status_color=TEXT_COLOR)
        elif not password_entered:
             self._update_ui(status=STATUS_ENTER_PASS, status_color=TEXT_COLOR)
        # Keep strength indicator updated, but don't override password mismatch warning
        elif self.strength_label['text'].startswith("Password Strength"):
             pass # Don't reset status if strength is already shown
        else:
             # If everything seems okay for potential action, show Ready or selection
             status = f"Selected: {os.path.basename(self.selected_file)}" if file_selected else STATUS_READY
             self._update_ui(status=status, status_color=TEXT_COLOR)


    def _start_encrypt_thread(self):
        """Starts the encryption process in a separate thread."""
        if self._validate_inputs(is_encrypt=True):
            thread = threading.Thread(target=self._process_file, args=(True,), daemon=True)
            thread.start()

    def _start_decrypt_thread(self):
        """Starts the decryption process in a separate thread."""
        if self._validate_inputs(is_encrypt=False):
            thread = threading.Thread(target=self._process_file, args=(False,), daemon=True)
            thread.start()

    def _validate_inputs(self, is_encrypt: bool) -> bool:
        """Checks if file and password inputs are valid before processing."""
        if self.is_processing: return False
        if not self.selected_file:
            messagebox.showerror("Input Error", "Please select a file first.")
            return False
        password = self.password_entry.get()
        if not password:
            messagebox.showerror("Input Error", "Please enter a password.")
            return False
        if is_encrypt:
            confirm_password = self.confirm_password_entry.get()
            if password != confirm_password:
                messagebox.showerror("Input Error", "Passwords do not match.")
                return False
        return True

    def _create_backup(self, file_path: str) -> str | None:
        """Creates a backup of the file with a .bak extension."""
        backup_path = file_path + ".bak"
        try:
            self._update_ui(status=STATUS_CREATING_BACKUP, status_color=ACCENT_COLOR)
            with open(file_path, 'rb') as src, open(backup_path, 'wb') as dst:
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk: break
                    dst.write(chunk)
            return backup_path
        except Exception as e:
            messagebox.showerror("Backup Error", f"Failed to create backup: {e}")
            self._update_ui(status=f"{STATUS_ERROR_PREFIX}Backup failed", status_color=ERROR_COLOR)
            return None

    def _process_file(self, is_encrypt: bool):
        """Handles the core file processing (encryption or decryption)."""
        self._set_ui_state(enabled=False)
        start_time = time.time()
        operation_name = "Encryption" if is_encrypt else "Decryption"
        status_color = ACCENT_COLOR

        input_path = self.selected_file
        output_path = None # Determined during processing
        password = self.password_entry.get()

        try:
            # 1. Backup (Optional)
            if self.backup_var.get():
                if not self._create_backup(input_path):
                    raise Exception("Backup creation failed.") # Stop processing
                self._update_ui(progress=5)

            # --- Encryption ---
            if is_encrypt:
                self._update_ui(progress=10, status=STATUS_ENCRYPTING, status_color=status_color)

                # Calculate hash of original file
                self._update_ui(progress=15, status=STATUS_CALCULATING_HASH, status_color=status_color)
                original_hash = self._calculate_hash(input_path)
                if not original_hash: raise Exception("Failed to calculate original file hash.")

                # Prepare metadata
                metadata = {
                    "filename": os.path.basename(input_path),
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "hash": original_hash,
                    "hash_alg": "sha256"
                }
                metadata_bytes = json.dumps(metadata).encode('utf-8')

                # Generate salt and key
                self._update_ui(progress=20, status=STATUS_GENERATING_KEY, status_color=status_color)
                salt = os.urandom(SALT_SIZE)
                key = self._generate_key(password, salt)
                fernet = Fernet(key)

                # Read original data (update progress)
                self._update_ui(progress=25, status=STATUS_READING, status_color=status_color)
                original_data = bytearray()
                file_size = os.path.getsize(input_path)
                bytes_read = 0
                with open(input_path, 'rb') as f_in:
                    while True:
                        chunk = f_in.read(CHUNK_SIZE)
                        if not chunk: break
                        original_data.extend(chunk)
                        bytes_read += len(chunk)
                        # Reading progress: 25% to 50%
                        self._update_ui(progress=25 + (bytes_read / file_size) * 25)

                # Combine metadata and data
                data_to_encrypt = metadata_bytes + METADATA_SEPARATOR + original_data

                # Encrypt (this is the intensive step for Fernet)
                self._update_ui(progress=50, status=STATUS_ENCRYPTING, status_color=status_color)
                encrypted_data = fernet.encrypt(bytes(data_to_encrypt)) # Pass bytes
                self._update_ui(progress=65) # Assume encryption takes some time

                # Determine output path
                output_dir = os.path.dirname(input_path)
                random_name = secrets.token_hex(16) + ".enc" # Use .enc extension
                output_path = os.path.join(output_dir, random_name)

                # Write encrypted file (salt + data) with progress
                self._update_ui(progress=70, status=STATUS_WRITING, status_color=status_color)
                total_to_write = len(salt) + len(encrypted_data)
                bytes_written = 0
                with open(output_path, 'wb') as f_out:
                    f_out.write(salt)
                    bytes_written += len(salt)
                    # Write encrypted data in chunks for progress update
                    for i in range(0, len(encrypted_data), CHUNK_SIZE):
                        chunk = encrypted_data[i:i+CHUNK_SIZE]
                        f_out.write(chunk)
                        bytes_written += len(chunk)
                        # Writing progress: 70% to 95%
                        self._update_ui(progress=70 + (bytes_written / total_to_write) * 25)

                final_status = STATUS_ENCRYPT_SUCCESS
                final_color = SUCCESS_COLOR
                message = f"File encrypted successfully!\nSaved as: {random_name}"

            # --- Decryption ---
            else:
                self._update_ui(progress=10, status=STATUS_DECRYPTING, status_color=status_color)

                # Read salt and encrypted data (update progress)
                self._update_ui(progress=15, status=STATUS_READING, status_color=status_color)
                salt = b''
                encrypted_data = bytearray()
                file_size = os.path.getsize(input_path)
                bytes_read = 0
                try:
                    with open(input_path, 'rb') as f_in:
                        salt = f_in.read(SALT_SIZE)
                        if len(salt) != SALT_SIZE:
                            raise ValueError("File is too small to contain salt.")
                        bytes_read += SALT_SIZE
                        while True:
                            chunk = f_in.read(CHUNK_SIZE)
                            if not chunk: break
                            encrypted_data.extend(chunk)
                            bytes_read += len(chunk)
                            # Reading progress: 15% to 45%
                            self._update_ui(progress=15 + (bytes_read / file_size) * 30)
                except FileNotFoundError:
                    raise Exception(f"Encrypted file not found: {os.path.basename(input_path)}")
                except Exception as e:
                     raise Exception(f"Error reading encrypted file: {e}")

                # Generate key
                self._update_ui(progress=45, status=STATUS_GENERATING_KEY, status_color=status_color)
                key = self._generate_key(password, salt)
                fernet = Fernet(key)

                # Decrypt (intensive step)
                self._update_ui(progress=50, status=STATUS_DECRYPTING, status_color=status_color)
                try:
                    decrypted_payload = fernet.decrypt(bytes(encrypted_data)) # Pass bytes
                except InvalidToken:
                    raise Exception("Invalid password or corrupted data.") # More specific
                self._update_ui(progress=65) # Assume decryption takes time

                # Split metadata and content
                try:
                    metadata_bytes, original_data = decrypted_payload.split(METADATA_SEPARATOR, 1)
                    metadata = json.loads(metadata_bytes.decode('utf-8'))
                    original_filename = metadata.get("filename", "decrypted_file") # Fallback name
                    stored_hash = metadata.get("hash")
                    # hash_alg = metadata.get("hash_alg", "sha256") # Could use this later if supporting multiple algs
                except (ValueError, json.JSONDecodeError, KeyError) as e:
                    raise Exception(f"Invalid file format or missing metadata: {e}")

                # Determine output path
                output_dir = os.path.dirname(input_path)
                output_path = os.path.join(output_dir, original_filename)

                 # Check for file existence before writing
                if os.path.exists(output_path):
                    if not messagebox.askyesno("File Exists", f"The file '{original_filename}' already exists. Overwrite?"):
                        raise Exception("Decryption cancelled by user (file exists).")

                # Write decrypted file (update progress)
                self._update_ui(progress=70, status=STATUS_WRITING, status_color=status_color)
                total_to_write = len(original_data)
                bytes_written = 0
                with open(output_path, 'wb') as f_out:
                    # Write data in chunks for progress update
                    for i in range(0, len(original_data), CHUNK_SIZE):
                        chunk = original_data[i:i+CHUNK_SIZE]
                        f_out.write(chunk)
                        bytes_written += len(chunk)
                        # Writing progress: 70% to 90%
                        self._update_ui(progress=70 + (bytes_written / total_to_write) * 20)

                # Verify hash (integrity check)
                if stored_hash:
                    self._update_ui(progress=90, status=STATUS_VERIFYING, status_color=status_color)
                    current_hash = self._calculate_hash(output_path)
                    if current_hash == stored_hash:
                        final_status = STATUS_DECRYPT_HASH_MATCH
                        final_color = SUCCESS_COLOR
                        message = f"File decrypted successfully!\nSaved as: {original_filename}\nIntegrity check passed."
                    else:
                        final_status = STATUS_DECRYPT_HASH_MISMATCH
                        final_color = WARN_COLOR # Use warning color for mismatch
                        message = f"WARNING: File decrypted but integrity check FAILED!\nSaved as: {original_filename}\nExpected hash: {stored_hash[:10]}...\nCalculated hash: {current_hash[:10]}..."
                        messagebox.showwarning("Integrity Check Failed", message) # Show warning popup too
                else:
                    # No hash stored (maybe older version encrypted file?)
                    final_status = STATUS_DECRYPT_SUCCESS + " (No hash found for verification)"
                    final_color = SUCCESS_COLOR
                    message = f"File decrypted successfully!\nSaved as: {original_filename}\n(Hash verification skipped - not found in metadata)"
                self._update_ui(progress=95)


            # 9. Delete Original (Optional) - AFTER successful operation
            delete_msg = ""
            if self.delete_var.get() and output_path: # Ensure operation seemed successful
                self._update_ui(progress=98, status=STATUS_DELETING, status_color=status_color)
                try:
                    # Note: os.remove is not cryptographically secure deletion
                    os.remove(input_path)
                    delete_msg = f"\nOriginal file '{os.path.basename(input_path)}' deleted."
                except Exception as e:
                    delete_msg = f"\nWarning: Failed to delete original file: {e}"
                    messagebox.showwarning("Delete Error", delete_msg.strip())

            # Final Update
            self._update_ui(progress=100, status=final_status, status_color=final_color)
            end_time = time.time()
            duration = end_time - start_time
            message += f"{delete_msg}\nOperation took {duration:.2f} seconds."
            if final_color != WARN_COLOR: # Don't show info box if a warning was already shown
                messagebox.showinfo(operation_name + " Complete", message)

        except Exception as e:
            error_message = f"{STATUS_ERROR_PREFIX}{operation_name} failed: {e}"
            self._update_ui(progress=0, status=error_message, status_color=ERROR_COLOR)
            messagebox.showerror(operation_name + " Error", error_message.replace(STATUS_ERROR_PREFIX, "")) # Cleaner popup message

        finally:
            # Re-enable UI and reset progress after a delay
            self._set_ui_state(enabled=True)
             # Reset progress bar after 3 seconds
            self.root.after(3000, lambda: self._update_ui(progress=0))
            # Optionally reset file selection and password after operation?
            # self.selected_file = None
            # self.file_path_var.set("No file selected")
            # self.password_entry.delete(0, tk.END)
            # self.confirm_password_entry.delete(0, tk.END)
            # self._check_password_strength() # Reset strength
            # self._update_button_states()


def main():
    """Initializes and runs the Tkinter application."""
    root = tk.Tk()
    app = ModernCryptoApp(root)

    # Attempt to set an icon (replace 'lock_icon.ico' with your actual icon file if you have one)
    # try:
    #     # Make sure 'lock_icon.ico' is in the same directory or provide a full path
    #     # You might need different formats for Linux/macOS (.png, .gif, .icns)
    #     root.iconbitmap("lock_icon.ico")
    # except tk.TclError:
    #     print("Note: Icon file 'lock_icon.ico' not found or invalid format for this OS.")
    # except Exception as e:
    #      print(f"Note: Could not set icon: {e}")

    root.mainloop()

if __name__ == "__main__":
    main()

