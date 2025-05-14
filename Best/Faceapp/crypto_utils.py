# crypto_utils.py
import os
from cryptography.fernet import Fernet

KEY_FILE = "key.key"

def generate_key():
    """Generates a new encryption key and saves it to a file."""
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as key_file:
        key_file.write(key)
    print(f"New encryption key generated and saved to {KEY_FILE}")
    return key

def load_key():
    """Loads the encryption key from the key file. Generates a new one if not found."""
    if not os.path.exists(KEY_FILE):
        print(f"Warning: Encryption key file '{KEY_FILE}' not found. Generating a new one.")
        print("         This means previously stored blueprints cannot be decrypted!")
        return generate_key()
    try:
        with open(KEY_FILE, "rb") as key_file:
            key = key_file.read()
        # Basic check if it looks like a Fernet key
        if len(key) == 44 and key.endswith(b'='):
             return key
        else:
             print(f"Error: Invalid key format found in {KEY_FILE}. Please delete the file and restart to generate a new key.")
             raise ValueError("Invalid key format")
    except Exception as e:
        print(f"Error loading key from {KEY_FILE}: {e}")
        raise

def get_fernet_instance():
    """Gets a Fernet instance initialized with the loaded key."""
    key = load_key()
    return Fernet(key)

def encrypt_data(data: bytes) -> bytes:
    """Encrypts bytes using the loaded key."""
    f = get_fernet_instance()
    return f.encrypt(data)

def decrypt_data(encrypted_data: bytes) -> bytes:
    """Decrypts bytes using the loaded key."""
    f = get_fernet_instance()
    try:
        return f.decrypt(encrypted_data)
    except Exception as e: # Includes InvalidToken
        print(f"Decryption failed: {e}")
        # Handle appropriately - maybe return None or raise a specific error
        return b"" # Return empty bytes on failure for this demo