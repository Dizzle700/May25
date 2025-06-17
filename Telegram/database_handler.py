import sqlite3
import os
from datetime import datetime

# Removed global DATABASE_NAME and DATABASE_PATH
# DATABASE_NAME = "telegram_images.sqlite"
# DATABASE_PATH = os.path.join(os.path.dirname(__file__), DATABASE_NAME) # Place DB in the same folder as this script

def get_db_connection(db_path):
    """Establishes a connection to the SQLite database."""
    if not db_path:
        raise ValueError("Database path must be provided.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def initialize_database(db_path):
    """Initializes the database and creates the images table if it doesn't exist."""
    conn = get_db_connection(db_path)
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
            major_category_id TEXT, -- ID of the major category
            sub_category_id TEXT, -- ID of the sub category
            sanitized_caption TEXT, -- Caption cleaned of emojis and extra whitespace
            price TEXT -- Extracted prices as JSON string
        )
    """)
    # Attempt to add columns if they don't exist (for existing databases)
    columns_to_add = {
        "major_category_id": "TEXT",
        "sub_category_id": "TEXT",
        "sanitized_caption": "TEXT",
        "price": "TEXT"
    }
    for column_name, column_type in columns_to_add.items():
        try:
            cursor.execute(f"ALTER TABLE images ADD COLUMN {column_name} {column_type}")
            print(f"INFO: Column '{column_name}' added to 'images' table.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass # Column already exists
            else:
                print(f"Warning: Could not add '{column_name}' column (may already exist or other issue): {e}")
    
    conn.commit()
    conn.close()

def insert_image_metadata(metadata, db_path):
    """
    Inserts image metadata into the database.
    'metadata' is a dictionary with keys matching table column names.
    'db_path' is the path to the SQLite database file.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO images (
                message_id, channel, image_number_in_message, caption, 
                filename, full_path, download_date, download_time, 
                original_filename, utc_timestamp, message_group, telegram_message_date, 
                major_category_id, sub_category_id, sanitized_caption, price
            ) VALUES (
                :message_id, :channel, :image_number_in_message, :caption,
                :filename, :full_path, :download_date, :download_time,
                :original_filename, :utc_timestamp, :message_group, :telegram_message_date, 
                :major_category_id, :sub_category_id, :sanitized_caption, :price
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

def get_image_metadata(image_id, db_path):
    """
    Retrieves all metadata for a single image by its ID.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM images WHERE id = ?", (image_id,))
    img_data = cursor.fetchone()
    conn.close()
    return img_data


if __name__ == '__main__':
    # This block is for direct script execution, e.g., for testing.
    # You'll need to define a test_db_path to use these functions directly.
    test_db_name = "test_telegram_images.sqlite"
    test_db_path = os.path.join(os.path.dirname(__file__), test_db_name)
    
    print(f"Initializing test database at: {test_db_path}")
    initialize_database(test_db_path)
    print("Test database initialized.")

    # Example usage (optional, for testing)
    # test_data = {
    #     'message_id': 123,
    #     'channel': '@testchannel',
    #     'image_number_in_message': 1,
    #     'caption': 'Test Caption',
    #     'filename': 'test_image.jpg',
    #     'full_path': os.path.join(os.path.dirname(__file__), 'test_image.jpg'), # Adjusted for local test
    #     'download_date': datetime.now().strftime("%Y-%m-%d"),
    #     'download_time': datetime.now().strftime("%H:%M:%S"),
    #     'original_filename': 'original.jpg',
    #     'utc_timestamp': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #     'message_group': 1,
    #     'telegram_message_date': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #     'ai_category': 'Test Category',
    #     'sanitized_caption': 'Test Caption Sanitized',
    #     'price': 10.99
    # }
    # # Create a dummy file for the test if full_path needs to exist for some logic
    # # with open(test_data['full_path'], 'w') as f: f.write("dummy image data")
    #
    # insert_image_metadata(test_data, test_db_path)
    # print("Test data inserted (if path was unique).")
    #
    # # Clean up the dummy file and test database if created
    # # if os.path.exists(test_data['full_path']):
    # #     os.remove(test_data['full_path'])
    # # if os.path.exists(test_db_path):
    # #     print(f"Test database {test_db_path} can be manually deleted if no longer needed.")
