import sqlite3
import os
from datetime import datetime

def get_db_connection(db_path):
    """Establishes a connection to the SQLite database."""
    if not db_path:
        raise ValueError("Database path must be provided.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database(db_path):
    """Initializes the database and creates the necessary tables if they don't exist."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            channel TEXT,
            caption TEXT,
            download_date TEXT,
            download_time TEXT,
            utc_timestamp TEXT,
            message_group INTEGER,
            telegram_message_date TEXT,
            major_category_id TEXT,
            sub_category_id TEXT,
            sanitized_caption TEXT,
            price TEXT,
            brand_tag TEXT
        )
    """)

    # Create product_images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            image_number_in_message INTEGER,
            filename TEXT,
            full_path TEXT UNIQUE,
            original_filename TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)

    # Add new columns to products table if they don't exist
    columns_to_add = {
        "major_category_id": "TEXT",
        "sub_category_id": "TEXT",
        "sanitized_caption": "TEXT",
        "price": "TEXT",
        "brand_tag": "TEXT"
    }
    for column_name, column_type in columns_to_add.items():
        try:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {column_name} {column_type}")
            print(f"INFO: Column '{column_name}' added to 'products' table.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass
            else:
                print(f"Warning: Could not add '{column_name}' column to 'products': {e}")

    conn.commit()
    conn.close()

def insert_product_with_images(product_data, images_data, db_path):
    """
    Inserts product and its associated images into the database in a transaction.
    'product_data' is a dictionary for the products table.
    'images_data' is a list of dictionaries for the product_images table.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN")

        # Insert into products table
        cursor.execute("""
            INSERT INTO products (
                message_id, channel, caption, download_date, download_time,
                utc_timestamp, message_group, telegram_message_date,
                major_category_id, sub_category_id, sanitized_caption, price, brand_tag
            ) VALUES (
                :message_id, :channel, :caption, :download_date, :download_time,
                :utc_timestamp, :message_group, :telegram_message_date,
                :major_category_id, :sub_category_id, :sanitized_caption, :price, :brand_tag
            )
        """, product_data)
        product_id = cursor.lastrowid

        # Insert into product_images table
        for image_data in images_data:
            image_data['product_id'] = product_id
            # Check if the image already exists to prevent IntegrityError
            cursor.execute("SELECT id FROM product_images WHERE full_path = ?", (image_data['full_path'],))
            existing_image = cursor.fetchone()
            if existing_image:
                print(f"Info: Image with path '{image_data['full_path']}' already exists. Skipping insert.")
                continue # Skip to the next image

            cursor.execute("""
                INSERT INTO product_images (
                    product_id, image_number_in_message, filename, full_path, original_filename
                ) VALUES (
                    :product_id, :image_number_in_message, :filename, :full_path, :original_filename
                )
            """, image_data)

        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        # This specific IntegrityError should now be largely prevented by the check above,
        # but keeping the catch for other potential integrity issues.
        print(f"Warning: Integrity error during product/image insert. Details: {e}")
    except Exception as e:
        conn.rollback()
        print(f"Error inserting product with images into database: {e}")
    finally:
        conn.close()

def get_product_details(product_id, db_path):
    """
    Retrieves all details for a single product, including its images.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Get product data
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product_data = cursor.fetchone()

    if not product_data:
        conn.close()
        return None

    # Get associated images
    cursor.execute("SELECT * FROM product_images WHERE product_id = ?", (product_id,))
    images_data = cursor.fetchall()

    conn.close()

    # Combine into a single dictionary
    product_details = dict(product_data)
    product_details['images'] = [dict(row) for row in images_data]

    return product_details

if __name__ == '__main__':
    test_db_name = "test_telegram_products.sqlite"
    test_db_path = os.path.join(os.path.dirname(__file__), test_db_name)
    
    print(f"Initializing test database at: {test_db_path}")
    initialize_database(test_db_path)
    print("Test database initialized.")

    # Example usage
    test_product_data = {
        'message_id': 456,
        'channel': '@testchannel',
        'caption': 'Multi-image Test Caption',
        'download_date': datetime.now().strftime("%Y-%m-%d"),
        'download_time': datetime.now().strftime("%H:%M:%S"),
        'utc_timestamp': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        'message_group': 2,
        'telegram_message_date': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        'major_category_id': 'cat_maj_01',
        'sub_category_id': 'cat_sub_01',
        'sanitized_caption': 'Multi-image Test Caption Sanitized',
        'price': '19.99',
        'brand_tag': 'TestBrand'
    }

    test_images_data = [
        {
            'image_number_in_message': 1,
            'filename': 'test_image_1.jpg',
            'full_path': os.path.join(os.path.dirname(__file__), 'test_image_1.jpg'),
            'original_filename': 'original1.jpg'
        },
        {
            'image_number_in_message': 2,
            'filename': 'test_image_2.jpg',
            'full_path': os.path.join(os.path.dirname(__file__), 'test_image_2.jpg'),
            'original_filename': 'original2.jpg'
        }
    ]

    # Create dummy files for testing
    for img in test_images_data:
        if not os.path.exists(img['full_path']):
            with open(img['full_path'], 'w') as f:
                f.write("dummy image data")

    insert_product_with_images(test_product_data, test_images_data, test_db_path)
    print("Test product with images inserted (if path was unique).")

    # Example of retrieving the data
    # In a real scenario, you'd get the product_id from somewhere else
    # For this test, we'll just assume it's 1
    retrieved_product = get_product_details(1, test_db_path)
    if retrieved_product:
        print("\nRetrieved Product Details:")
        import json
        print(json.dumps(retrieved_product, indent=2))
    else:
        print("\nCould not retrieve product with ID 1.")

    # Clean up dummy files
    for img in test_images_data:
        if os.path.exists(img['full_path']):
            os.remove(img['full_path'])
