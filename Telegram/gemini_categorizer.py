import configparser
import os
import google.generativeai as genai
from PIL import Image # For image processing
import json # Added for JSON parsing

# --- Configuration ---
CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "config.ini")
# Changed to categories.json
DEFAULT_CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), "categories.json")

def get_gemini_api_key():
    """Reads the Gemini API key from the config file."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"Error: Configuration file not found at {CONFIG_FILE_PATH}")
        return None
    config.read(CONFIG_FILE_PATH)
    try:
        return config.get("Gemini", "api_key")
    except (configparser.NoSectionError, configparser.NoOptionError):
        print("Error: GEMINI_API_KEY not found in config.ini under [Gemini] section.")
        return None

def get_gemini_model_name():
    """Reads the Gemini model name from the config file."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"Error: Configuration file not found at {CONFIG_FILE_PATH}")
        return None
    config.read(CONFIG_FILE_PATH)
    try:
        return config.get("Gemini", "model_name")
    except (configparser.NoSectionError, configparser.NoOptionError):
        print("Error: 'model_name' not found in config.ini under [Gemini] section. Using default.")
        return "gemini-1.5-pro-latest" # Default if not found

def _build_category_maps(categories_data):
    """
    Builds lookup maps from the flat categories JSON data.
    Returns:
        tuple: (id_to_category_map, name_to_id_map, slug_to_id_map)
    """
    id_to_category_map = {item['id']: item for item in categories_data}
    name_to_id_map = {item['name'].lower(): item['id'] for item in categories_data}
    slug_to_id_map = {item['slug'].lower(): item['id'] for item in categories_data}
    return id_to_category_map, name_to_id_map, slug_to_id_map

def load_categories(categories_file_path=DEFAULT_CATEGORIES_FILE):
    """
    Loads categories from a JSON file and returns structured data and lookup maps.
    Returns:
        tuple: (raw_categories_list, id_to_category_map, name_to_id_map, slug_to_id_map)
    """
    categories_data = []
    try:
        with open(categories_file_path, 'r', encoding='utf-8') as f:
            categories_data = json.load(f)
    except FileNotFoundError:
        print(f"Warning: Categories JSON file not found at {categories_file_path}. Returning empty data.")
        return [], {}, {}, {}
    except json.JSONDecodeError as e:
        print(f"Error decoding categories JSON from {categories_file_path}: {e}. Returning empty data.")
        return [], {}, {}, {}
    except Exception as e:
        print(f"Error loading categories from {categories_file_path}: {e}. Returning empty data.")
        return [], {}, {}, {}
    
    if not categories_data:
        print(f"Warning: No categories loaded from {categories_file_path}. Ensure the file is not empty and has valid JSON entries.")
        return [], {}, {}, {}
    
    id_to_category_map, name_to_id_map, slug_to_id_map = _build_category_maps(categories_data)
    return categories_data, id_to_category_map, name_to_id_map, slug_to_id_map

DEFAULT_CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), "categories.json")
DEFAULT_BRANDS_FILE = os.path.join(os.path.dirname(__file__), "brands.txt") # New constant for brands file

def get_category_from_gemini(image_path, text_to_categorize, categories_data, api_key):
    """
    Uses Gemini AI to categorize the given image and text based on the provided categories list,
    and also extract a brand tag.

    Args:
        image_path (str): Path to the image file.
        text_to_categorize (str): The text (e.g., product caption) to categorize.
        categories_data (tuple): Structured category data from load_categories.
        api_key (str): The Gemini API key.

    Returns:
        tuple: (major_category_id, sub_category_id, brand_tag) or (None, None, None) on failure/not found.
    """
    raw_categories_list, id_to_category_map, name_to_id_map, slug_to_id_map = categories_data

    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        return None, None, None # "не настроен API ключ"

    if not raw_categories_list:
        return None, None, None # "нет списка категорий"

    # Initialize img to None
    img = None 
    # Determine content for Gemini based on image_path and text_to_categorize
    contents = []
    if image_path and os.path.exists(image_path):
        try:
            img = Image.open(image_path)
            contents.append(img)
        except Exception as e:
            print(f"Warning: Could not load image from {image_path}: {e}. Proceeding with text only if available.")
            # Do not return here, try to proceed with text if image fails to load
    elif image_path is not None: # image_path was provided but file doesn't exist
        print(f"Warning: Image file does not exist at {image_path}. Proceeding with text only if available.")
    # If image_path is None (text-only mode), no warning is printed here.

    if text_to_categorize:
        contents.append(text_to_categorize)
    
    if not contents:
        print("Warning: No image or text content provided for AI categorization. Skipping.")
        return None, None, None # "нет контента для AI"

    try:
        genai.configure(api_key=api_key)
        
        model_name_to_use = get_gemini_model_name()
        
        generation_config = {
            "temperature": 0.2, 
            "top_p": 1,
            "top_k": 32,
            "max_output_tokens": 200, # Increased token limit for category and brand
        }
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        model = genai.GenerativeModel(model_name=model_name_to_use,
                                      generation_config=generation_config,
                                      safety_settings=safety_settings)

        # Prepare categories for the prompt
        major_categories = sorted(list(set([item['name'] for item in raw_categories_list if item['type'] == 'major'])))
        sub_categories_by_major = {}
        for item in raw_categories_list:
            if item['type'] == 'sub' and item['parent_id']:
                parent_cat = id_to_category_map.get(item['parent_id'])
                if parent_cat:
                    major_name = parent_cat['name']
                    if major_name not in sub_categories_by_major:
                        sub_categories_by_major[major_name] = []
                    sub_categories_by_major[major_name].append(item['name'])
        
        categories_prompt_parts = []
        for major_cat in major_categories:
            sub_cats = sub_categories_by_major.get(major_cat, [])
            if sub_cats:
                categories_prompt_parts.append(f"{major_cat}: {', '.join(sorted(sub_cats))}")
            else:
                categories_prompt_parts.append(major_cat) # Major category with no sub-categories

        categories_str = "; ".join(categories_prompt_parts)
        
        # Adjust prompt based on whether image content is included
        if img: # If image was successfully loaded and added to contents
            prompt_text = (
                f"ОСНОВНАЯ ЗАДАЧА - АНАЛИЗ ИЗОБРАЖЕНИЯ. Проанализируй В ПЕРВУЮ ОЧЕРЕДЬ ИЗОБРАЖЕНИЕ. Текст используй как дополнительный контекст. Текст: \"{text_to_categorize if text_to_categorize else 'Нет дополнительного текста.'}\". "
                f"1. К какой из следующих ПОДКАТЕГОРИЙ товар НА ИЗОБРАЖЕНИИ лучше всего подходит? Подкатегории: [{categories_str}]. "
                "Ответь только названием одной подкатегории. "
                "Например: 'наушники tws (airpods like)'. "
                "Если ни одна подкатегория точно не подходит или на изображении нет явного товара, ответь 'не определена'.\n"
                f"2. Определи бренд товара, ПРЕДПОЧТИТЕЛЬНО ИЗ ТЕКСТА НА ИЗОБРАЖЕНИИ, или из предоставленного текста. "
                "Ответь 'Brand: [Название бренда]' или 'Brand: не определен', если бренд не найден на изображении/в тексте."
                "Пример ответа: 'наушники tws (airpods like)\nBrand: Awei'"
            )
        else: # Only text is available
            prompt_text = (
                f"Проанализируй следующий текст: \"{text_to_categorize}\". "
                f"1. К какой из следующих ПОДКАТЕГОРИЙ товар, описанный в тексте, лучше всего подходит? Подкатегории: [{categories_str}]. "
                "Ответь только названием одной подкатегории. "
                "Например: 'наушники tws (airpods like)'. "
                "Если ни одна подкатегория точно не подходит или в тексте нет явного товара, ответь 'не определена'.\n"
                f"2. Определи бренд товара из предоставленного текста. "
                "Ответь 'Brand: [Название бренда]' или 'Brand: не определен', если бренд не найден в тексте."
                "Пример ответа: 'наушники tws (airpods like)\nBrand: Awei'"
            )
        
        # print(f"DEBUG: Gemini Prompt Text: {prompt_text}")
        contents.insert(0, prompt_text) # Add prompt text as the first element
        response = model.generate_content(contents)
        
        if response.parts:
            suggested_response_raw = response.text.strip()
            # print(f"DEBUG: Gemini Raw Response: '{suggested_response_raw}'")

            # Split response into category and brand parts
            response_lines = suggested_response_raw.split('\n')
            sub_category_line = response_lines[0].strip() if response_lines else ""
            brand_line = ""
            for line in response_lines[1:]:
                if line.strip().lower().startswith("brand:"):
                    brand_line = line.strip()
                    break

            major_id = None
            sub_id = None
            brand_tag = None

            # Parse Sub-Category and derive Major Category
            if sub_category_line and sub_category_line.lower() != "не определена":
                sub_name = sub_category_line
                
                # Find sub category ID and its parent major category ID
                for item in raw_categories_list:
                    if item['type'] == 'sub' and item['name'].lower() == sub_name.lower():
                        sub_id = item['id']
                        major_id = item['parent_id'] # Get parent ID from the sub-category
                        break
                
                if not sub_id:
                    print(f"Warning: Gemini suggested sub-category '{sub_name}' not found in loaded categories. Returning (None, None, {brand_tag}).")
                    
            # Parse Brand Tag
            if brand_line.lower().startswith("brand:"):
                brand_value = brand_line[len("brand:"):].strip()
                if brand_value.lower() != "не определен":
                    brand_tag = brand_value # Accept the brand directly from Gemini

            return major_id, sub_id, brand_tag
        else:
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                 print(f"Gemini response blocked: {response.prompt_feedback.block_reason.name}")
                 return None, None, None # f"заблокировано ({response.prompt_feedback.block_reason.name})"
            return None, None, None # "нет ответа от AI"

    except ImportError:
        print("ERROR: The 'google-generativeai' library is not installed. Please install it using: pip install google-generativeai")
        return None, None, None # "ошибка библиотеки AI"
    except Exception as e:
        print(f"An error occurred while interacting with Gemini API: {e}")
        if "API key not valid" in str(e):
            return None, None, None # "неверный API ключ"
        return None, None, None # "ошибка AI"

if __name__ == '__main__':
        print("Gemini Categorizer Module")
        print("Ensure you have 'google-generativeai' installed: pip install google-generativeai")
        
        # Test API Key
        test_api_key = get_gemini_api_key()
        test_model_name = get_gemini_model_name()

        if test_api_key and test_api_key != "YOUR_GEMINI_API_KEY":
            print(f"API Key loaded: {test_api_key[:5]}...{test_api_key[-5:]}")
            print(f"Gemini Model Name loaded: {test_model_name}")
            
            # Test category loading
            # load_categories now returns a tuple
            raw_cats, id_map, name_map, slug_map = load_categories()
            print(f"Loaded categories count: {len(raw_cats)}")
            # print(f"ID Map sample: {list(id_map.items())[:5]}")
            # print(f"Name Map sample: {list(name_map.items())[:5]}")

            if raw_cats:
                # Test categorization
                sample_text_headphone = "Беспроводные наушники Awei T29 Pro с шумоподавлением, Bluetooth 5.1, отличное звучание"
                sample_text_charger = "Быстрое зарядное устройство USB-C PD 20W для iPhone и Android"
                
                # For image-based test, you'd need a sample image path.
                # This test will likely fail without a valid image path.
                # For now, we'll assume a placeholder path for the test structure.
                sample_image_path_placeholder = "path/to/sample_image.jpg" # User needs to replace this for local testing
                print(f"\nTesting with text: '{sample_text_headphone}' and image (placeholder): '{sample_image_path_placeholder}'")
                if os.path.exists(sample_image_path_placeholder):
                     # Pass the full categories_data tuple
                     major_id, sub_id, brand_tag = get_category_from_gemini(sample_image_path_placeholder, sample_text_headphone, (raw_cats, id_map, name_map, slug_map), test_api_key)
                     print(f"Suggested Major ID: {major_id}, Sub ID: {sub_id}, Brand Tag: {brand_tag}")
                else:
                     print(f"Skipping image test as '{sample_image_path_placeholder}' does not exist.")

            else:
                print("Skipping categorization test as no categories were loaded or API key is placeholder.")
        else:
            print("Gemini API key not configured in telegram/config.ini or is a placeholder. Skipping live tests.")
