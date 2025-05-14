# database.py
import sqlite3
import numpy as np
from crypto_utils import encrypt_data, decrypt_data

DATABASE_FILE = "database.db"

def init_db():
    """Initializes the SQLite database and creates the table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_blueprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                encrypted_blueprint BLOB NOT NULL UNIQUE, -- Store embedding encrypted, ensure uniqueness
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Consider adding an index on 'name' if you search by name often
        # cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON face_blueprints (name);")
        conn.commit()
        print(f"Database '{DATABASE_FILE}' initialized successfully.")
        return conn
    except sqlite3.Error as e:
        print(f"Database Error: {e}")
        raise # Re-raise the exception after logging

def save_blueprint(conn: sqlite3.Connection, name: str, blueprint: np.ndarray):
    """
    Encrypts the face blueprint (numpy array) and saves it to the database.
    Returns True on success, False on failure (e.g., duplicate).
    """
    if not name or blueprint is None:
        print("Error: Name or blueprint is empty.")
        return False

    try:
        blueprint_bytes = blueprint.tobytes()
        encrypted_blob = encrypt_data(blueprint_bytes)

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO face_blueprints (name, encrypted_blueprint) VALUES (?, ?)",
            (name, encrypted_blob)
        )
        conn.commit()
        print(f"Blueprint for '{name}' saved successfully.")
        return True
    except sqlite3.IntegrityError:
        print(f"Error: A blueprint identical to this one already exists in the database.")
        return False
    except sqlite3.Error as e:
        print(f"Database Error during save: {e}")
        return False
    except Exception as e:
        print(f"Error during encryption or saving: {e}")
        return False

def load_all_blueprints(conn: sqlite3.Connection) -> dict[str, np.ndarray]:
    """Loads all blueprints, decrypts them, and returns a dictionary {name: blueprint}."""
    blueprints = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, encrypted_blueprint FROM face_blueprints")
        rows = cursor.fetchall()
        for name, encrypted_blob in rows:
            try:
                decrypted_bytes = decrypt_data(encrypted_blob)
                # IMPORTANT: Assuming 128-d float64 embeddings from face_recognition
                blueprint = np.frombuffer(decrypted_bytes, dtype=np.float64)
                if blueprint.shape == (128,): # Basic shape validation
                    blueprints[name] = blueprint
                else:
                    print(f"Warning: Decrypted data for '{name}' has unexpected shape {blueprint.shape}. Skipping.")
            except Exception as e:
                print(f"Error decrypting or processing blueprint for '{name}': {e}")
        return blueprints
    except sqlite3.Error as e:
        print(f"Database Error during load: {e}")
        return {} # Return empty dict on error

# Example usage (optional, for testing)
# if __name__ == "__main__":
#     db_conn = init_db()
#     # Example: Create a dummy blueprint
#     dummy_bp = np.random.rand(128)
#     save_blueprint(db_conn, "Test User", dummy_bp)
#     loaded = load_all_blueprints(db_conn)
#     print(f"Loaded {len(loaded)} blueprints.")
#     if "Test User" in loaded:
#         print("Test User blueprint loaded successfully.")
#         # Optional: Compare dummy_bp with loaded["Test User"]
#         # print(np.allclose(dummy_bp, loaded["Test User"]))
#     db_conn.close()