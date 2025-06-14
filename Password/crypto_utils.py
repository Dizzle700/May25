# crypto_utils.py
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# --- Constants ---
SALT_SIZE = 16
NONCE_SIZE = 12  # Recommended for AES-GCM
KEY_LENGTH = 32  # AES-256
PBKDF2_ITERATIONS = 390000 # Adjust based on performance/security needs
ENCRYPTION_CHECK_CONSTANT = b"PyVaultSecure_Check_OK" # Used to verify master password

backend = default_backend()

def generate_salt():
    """Generates a cryptographically secure random salt."""
    return os.urandom(SALT_SIZE)

def derive_key(password: str, salt: bytes) -> bytes:
    """Derives a secure encryption key from the password and salt using PBKDF2."""
    if not isinstance(password, bytes):
        password = password.encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=backend
    )
    return kdf.derive(password)

def encrypt_data(key: bytes, plaintext: str) -> bytes:
    """Encrypts data using AES-GCM."""
    if not isinstance(plaintext, bytes):
        plaintext = plaintext.encode('utf-8')
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None) # No associated data
    # Prepend nonce to ciphertext for storage
    return nonce + ciphertext

def decrypt_data(key: bytes, encrypted_data: bytes) -> str:
    """Decrypts data using AES-GCM."""
    if not encrypted_data or len(encrypted_data) <= NONCE_SIZE:
        raise ValueError("Invalid encrypted data")
    nonce = encrypted_data[:NONCE_SIZE]
    ciphertext = encrypted_data[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except Exception as e: # Catch potential decryption/authentication errors
        print(f"Decryption failed: {e}") # Log appropriately in real app
        raise ValueError("Decryption failed - likely incorrect key or tampered data")

def generate_encryption_check(key: bytes) -> bytes:
    """Generates an encrypted check value to verify the master password later."""
    return encrypt_data(key, ENCRYPTION_CHECK_CONSTANT.decode('utf-8')) # Encrypt the constant string

def verify_encryption_check(key: bytes, stored_check: bytes) -> bool:
    """Verifies the master password by decrypting the stored check value."""
    try:
        decrypted_check = decrypt_data(key, stored_check)
        return decrypted_check.encode('utf-8') == ENCRYPTION_CHECK_CONSTANT
    except ValueError:
        return False # Decryption failed, likely wrong password