# database_manager.py - Manages SQLite database operations
import sqlite3
from datetime import datetime
from utils import DATABASE_FILENAME

class DatabaseManager:
    def __init__(self, db_name=DATABASE_FILENAME):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self._connect()
        self._create_tables()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                download_timestamp TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                message_date_utc TEXT NOT NULL,
                message_date_local TEXT,
                channel TEXT NOT NULL,
                caption_original TEXT,
                caption_processed TEXT,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                original_telegram_filename TEXT,
                image_number_in_message INTEGER,
                message_group_id INTEGER 
            )
        ''')
        # You might want an index on file_path for faster checks if a file was already downloaded
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_file_path ON images (file_path)
        ''')
        self.conn.commit()

    def save_image_metadata(self, metadata):
        """
        Saves image metadata to the database.
        metadata should be a dictionary with keys matching table columns.
        """
        # Ensure all required fields are present, provide defaults for optional ones
        required_fields = ['message_id', 'message_date_utc', 'channel', 'filename', 'file_path']
        for field in required_fields:
            if field not in metadata or metadata[field] is None:
                # This indicates an issue with data preparation before calling this
                print(f"Error: Missing required field '{field}' in metadata for DB save.")
                return False


        sql = '''
            INSERT INTO images (
                download_timestamp, message_id, message_date_utc, message_date_local,
                channel, caption_original, caption_processed, filename, file_path,
                original_telegram_filename, image_number_in_message, message_group_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        try:
            self.cursor.execute(sql, (
                metadata.get('download_timestamp', datetime.now(datetime.timezone.utc).isoformat()),
                metadata['message_id'],
                metadata['message_date_utc'],
                metadata.get('message_date_local'),
                metadata['channel'],
                metadata.get('caption_original'),
                metadata.get('caption_processed'),
                metadata['filename'],
                metadata['file_path'],
                metadata.get('original_telegram_filename'),
                metadata.get('image_number_in_message'),
                metadata.get('message_group_id')
            ))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Database Integrity Error (likely duplicate file_path): {e} for {metadata.get('file_path')}")
            return False # Or handle as appropriate (e.g., update existing)
        except Exception as e:
            print(f"Error saving image metadata to DB: {e}")
            self.conn.rollback() # Rollback on other errors
            return False

    def close(self):
        if self.conn:
            self.conn.close()