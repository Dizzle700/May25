import sqlite3
import os
from datetime import datetime

DATABASE_NAME = "telegram_images.sqlite"
DATABASE_PATH = os.path.join(os.path.dirname(__file__), DATABASE_NAME) # Place DB in the same folder as this script

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def initialize_database():
    """Initializes the database and creates the images table if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            channel TEXT,
            image_number_in_message INTEGER,
            caption TEXT,
            filename TEXT,
            full_path TEXT UNIQUE,  -- Assuming full_path should be unique
            download_date TEXT, -- ISO format date YYYY-MM-DD
            download_time TEXT, -- HH:MM:SS
            original_filename TEXT,
            utc_timestamp TEXT, -- ISO format datetime YYYY-MM-DD HH:MM:SS
            message_group INTEGER, -- To group images from the same message if multiple
            telegram_message_date TEXT, -- Store the original message date from Telegram (UTC)
            ai_category TEXT -- Category suggested by AI
        )
    """)
    # Attempt to add the ai_category column if it doesn't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE images ADD COLUMN ai_category TEXT")
        print("INFO: Column 'ai_category' added to 'images' table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            # Column already exists, which is fine
            pass
        else:
            # For other OperationalError, print it, but don't crash initialization
            print(f"Warning: Could not add 'ai_category' column (may already exist or other issue): {e}")
            # Depending on strictness, you might re-raise e here if it's critical
    
    conn.commit()
    conn.close()

def insert_image_metadata(metadata):
    """
    Inserts image metadata into the database.
    'metadata' is a dictionary with keys matching table column names.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO images (
                message_id, channel, image_number_in_message, caption, 
                filename, full_path, download_date, download_time, 
                original_filename, utc_timestamp, message_group, telegram_message_date, ai_category
            ) VALUES (
                :message_id, :channel, :image_number_in_message, :caption,
                :filename, :full_path, :download_date, :download_time,
                :original_filename, :utc_timestamp, :message_group, :telegram_message_date, :ai_category
            )
        """, metadata)
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"Warning: Image with path {metadata.get('full_path')} already exists in DB. Skipping.")
        # Or handle as an update if needed:
        # cursor.execute("""
        #     UPDATE images SET ... WHERE full_path = :full_path
        # """, metadata)
        # conn.commit()
    except Exception as e:
        print(f"Error inserting image metadata into database: {e}")
        # Potentially re-raise or log more formally
    finally:
        conn.close()

if __name__ == '__main__':
    # Initialize DB when script is run directly (for setup or testing)
    print(f"Initializing database at: {DATABASE_PATH}")
    initialize_database()
    print("Database initialized.")

    # Example usage (optional, for testing)
    # test_data = {
    #     'message_id': 123,
    #     'channel': '@testchannel',
    #     'image_number_in_message': 1,
    #     'caption': 'Test Caption',
    #     'filename': 'test_image.jpg',
    #     'full_path': '/path/to/telegram/test_image.jpg',
    #     'download_date': datetime.now().strftime("%Y-%m-%d"),
    #     'download_time': datetime.now().strftime("%H:%M:%S"),
    #     'original_filename': 'original.jpg',
    #     'utc_timestamp': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #     'message_group': 1,
    #     'telegram_message_date': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    # }
    # insert_image_metadata(test_data)
    # print("Test data inserted (if path was unique).")
