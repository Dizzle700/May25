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

def get_category_from_gemini(image_path, text_to_categorize, categories_data, api_key):
    """
    Uses Gemini AI to categorize the given image and text based on the provided categories list.

    Args:
        image_path (str): Path to the image file.
        text_to_categorize (str): The text (e.g., product caption) to categorize.
        categories_data (tuple): Structured category data from load_categories.
        api_key (str): The Gemini API key.

    Returns:
        tuple: (major_category_id, sub_category_id) or (None, None) on failure/not found.
    """
    raw_categories_list, id_to_category_map, name_to_id_map, slug_to_id_map = categories_data

    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        return None, None # "не настроен API ключ"

    if not raw_categories_list:
        return None, None # "нет списка категорий"

    if not image_path or not os.path.exists(image_path):
        print(f"Warning: Image path invalid or file does not exist: {image_path}. Skipping AI categorization.")
        return None, None # "файл изображения не найден"

    try:
        genai.configure(api_key=api_key)
        
        img = Image.open(image_path)

        model_name_to_use = "gemini-1.5-pro-latest" 
        
        generation_config = {
            "temperature": 0.2, 
            "top_p": 1,
            "top_k": 32,
            "max_output_tokens": 100, # Increased token limit for two categories
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
        
        prompt_text = (
            f"Проанализируй это изображение и следующий текст (если есть): \"{text_to_categorize if text_to_categorize else 'Нет дополнительного текста.'}\". "
            f"К какой из следующих категорий товар на изображении лучше всего подходит? Категории: [{categories_str}]. "
            "Ответь только названием одной основной категории и, если применимо, одной подкатегории, разделенных символом '>'. "
            "Например: 'Аудио и наушники > наушники tws (airpods like)'. "
            "Если подкатегория не найдена, ответь только основной категорией. "
            "Если ни одна категория точно не подходит или на изображении нет явного товара, ответь 'не определена'."
        )
        
        # print(f"DEBUG: Gemini Prompt Text: {prompt_text}")
        response = model.generate_content([prompt_text, img])
        
        if response.parts:
            suggested_category_raw = response.text.strip()
            # print(f"DEBUG: Gemini Raw Response: '{suggested_category_raw}'")

            if not suggested_category_raw or suggested_category_raw.lower() == "не определена":
                return None, None

            # Parse the response: "Major > Sub" or "Major"
            parts = [p.strip() for p in suggested_category_raw.split('>') if p.strip()]
            
            major_name = parts[0] if parts else None
            sub_name = parts[1] if len(parts) > 1 else None

            major_id = None
            sub_id = None

            # Find major category ID
            if major_name:
                for item in raw_categories_list:
                    if item['type'] == 'major' and item['name'].lower() == major_name.lower():
                        major_id = item['id']
                        break
            
            # Find sub category ID, ensuring it belongs to the found major category
            if sub_name and major_id:
                for item in raw_categories_list:
                    if item['type'] == 'sub' and item['name'].lower() == sub_name.lower() and item['parent_id'] == major_id:
                        sub_id = item['id']
                        break
            
            if major_id:
                return major_id, sub_id
            else:
                # If major category not found, then neither can sub-category be valid
                print(f"Warning: Gemini suggested category '{suggested_category_raw}' but major category '{major_name}' not found in loaded categories. Returning (None, None).")
                return None, None
        else:
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                 print(f"Gemini response blocked: {response.prompt_feedback.block_reason.name}")
                 return None, None # f"заблокировано ({response.prompt_feedback.block_reason.name})"
            return None, None # "нет ответа от AI"

    except ImportError:
        print("ERROR: The 'google-generativeai' library is not installed. Please install it using: pip install google-generativeai")
        return None, None # "ошибка библиотеки AI"
    except Exception as e:
        print(f"An error occurred while interacting with Gemini API: {e}")
        if "API key not valid" in str(e):
            return None, None # "неверный API ключ"
        return None, None # "ошибка AI"

if __name__ == '__main__':
    print("Gemini Categorizer Module")
    print("Ensure you have 'google-generativeai' installed: pip install google-generativeai")
    
    # Test API Key
    test_api_key = get_gemini_api_key()
    if test_api_key and test_api_key != "YOUR_GEMINI_API_KEY":
        print(f"API Key loaded: {test_api_key[:5]}...{test_api_key[-5:]}")
        
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
            print(f"Note: Standalone test requires a valid image at '{sample_image_path_placeholder}'")


            print(f"\nTesting with text: '{sample_text_headphone}' and image (placeholder): '{sample_image_path_placeholder}'")
            if os.path.exists(sample_image_path_placeholder):
                 # Pass the full categories_data tuple
                 major_id, sub_id = get_category_from_gemini(sample_image_path_placeholder, sample_text_headphone, (raw_cats, id_map, name_map, slug_map), test_api_key)
                 print(f"Suggested Major ID: {major_id}, Sub ID: {sub_id}")
            else:
                 print(f"Skipping image test as '{sample_image_path_placeholder}' does not exist.")

        else:
            print("Skipping categorization test as no categories were loaded or API key is placeholder.")
    else:
        print("Gemini API key not configured in telegram/config.ini or is a placeholder. Skipping live tests.")
