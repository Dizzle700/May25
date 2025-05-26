import configparser
import os
import google.generativeai as genai
from PIL import Image # For image processing

# --- Configuration ---
CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "config.ini")
DEFAULT_CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), "categories.txt")

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

def load_categories(categories_file_path=DEFAULT_CATEGORIES_FILE):
    """Loads categories from a text file, one category per line."""
    categories = []
    try:
        with open(categories_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and \
                   not (line.startswith("'") or line.startswith('"')):
                    categories.append(line)
    except FileNotFoundError:
        print(f"Warning: Categories file not found at {categories_file_path}. Returning empty list.")
        return []
    except Exception as e:
        print(f"Error loading categories from {categories_file_path}: {e}")
        return []
    if not categories:
        print(f"Warning: No categories loaded from {categories_file_path}. Ensure the file is not empty and has valid entries.")
    return categories

def get_category_from_gemini(image_path, text_to_categorize, categories_list, api_key):
    """
    Uses Gemini AI to categorize the given image and text based on the provided categories list.

    Args:
        image_path (str): Path to the image file.
        text_to_categorize (str): The text (e.g., product caption) to categorize.
        categories_list (list): A list of category strings.
        api_key (str): The Gemini API key.

    Returns:
        str: The suggested category name from the list, or 'не определена' / error message.
    """
    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        return "не настроен API ключ"

    if not categories_list:
        return "нет списка категорий"

    if not image_path or not os.path.exists(image_path):
        print(f"Warning: Image path invalid or file does not exist: {image_path}. Attempting text-only categorization.")
        # Fallback to text-only if image is missing, or return specific error
        # For now, let's make image mandatory for this function version
        return "файл изображения не найден"


    # Text is optional but helpful if present
    # if not text_to_categorize or len(text_to_categorize.strip()) < 3:
    #     text_to_categorize = "Проанализируй только изображение."


    try:
        genai.configure(api_key=api_key)
        
        img = Image.open(image_path)

        # Using gemini-1.5-pro-latest for multimodal capabilities
        # Note: Ensure the user's API key has access to this model.
        # gemini-pro-vision was the older model name for vision.
        # gemini-1.5-flash-latest is text only.
        # gemini-1.5-pro-latest is the current advanced multimodal model.
        model_name_to_use = "gemini-1.5-pro-latest" 
        
        generation_config = {
            "temperature": 0.2, 
            "top_p": 1,
            "top_k": 32, # Allow for a bit more flexibility with multimodal
            "max_output_tokens": 50,
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

        categories_str = ", ".join(categories_list)
        
        prompt_text = (
            f"Проанализируй это изображение и следующий текст (если есть): \"{text_to_categorize if text_to_categorize else 'Нет дополнительного текста.'}\". "
            f"К какой из следующих категорий товар на изображении лучше всего подходит? Категории: [{categories_str}]. "
            "Ответь только названием одной категории из предоставленного списка. "
            "Если ни одна категория точно не подходит или на изображении нет явного товара, ответь 'не определена'."
        )
        
        # print(f"DEBUG: Gemini Prompt Text: {prompt_text}")
        # The SDK expects a list of parts for multimodal input
        response = model.generate_content([prompt_text, img])
        
        if response.parts:
            suggested_category_raw = response.text.strip()
            # print(f"DEBUG: Gemini Raw Response: '{suggested_category_raw}'")

            # 1. Check for case-insensitive exact match with predefined categories
            for predefined_cat in categories_list:
                if suggested_category_raw.lower() == predefined_cat.lower():
                    # print(f"DEBUG: Case-insensitive match found: '{predefined_cat}'")
                    return predefined_cat # Return the version from the user's list for consistency

            # 2. If Gemini explicitly says "не определена" (case-insensitive)
            #    or if the raw response is empty after stripping.
            if not suggested_category_raw or suggested_category_raw.lower() == "не определена":
                # Try to return the canonical "не определена" if it's in categories_list
                for predefined_cat in categories_list:
                    if predefined_cat.lower() == "не определена":
                        return predefined_cat
                return "не определена" # Default if canonical "не определена" isn't in the list

            # 3. If no direct match, and not "не определена", and not empty,
            #    consider it a new category suggestion by Gemini. Store it as is.
            #    (Add a simple length check to avoid overly long/garbage responses)
            if 0 < len(suggested_category_raw) <= 100: # Arbitrary length limit for a category name
                print(f"INFO: Gemini suggested a new or variant category: '{suggested_category_raw}' (not an exact case-insensitive match in predefined list). Using it.")
                return suggested_category_raw
            else:
                print(f"Warning: Gemini returned an unusual category string (empty or too long): '{suggested_category_raw}'. Defaulting to 'не определена'.")
                # Try to return the canonical "не определена" if it's in categories_list
                for predefined_cat in categories_list:
                    if predefined_cat.lower() == "не определена":
                        return predefined_cat
                return "не определена"
        else:
            # print(f"DEBUG: Gemini response has no parts. Blocked? Reason: {response.prompt_feedback}")
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                 return f"заблокировано ({response.prompt_feedback.block_reason.name})" # Use .name for enum
            return "нет ответа от AI"

    except ImportError:
        print("ERROR: The 'google-generativeai' library is not installed. Please install it using: pip install google-generativeai")
        return "ошибка библиотеки AI"
    except Exception as e:
        print(f"An error occurred while interacting with Gemini API: {e}")
        if "API key not valid" in str(e):
            return "неверный API ключ"
        return "ошибка AI"

if __name__ == '__main__':
    print("Gemini Categorizer Module")
    print("Ensure you have 'google-generativeai' installed: pip install google-generativeai")
    
    # Test API Key
    test_api_key = get_gemini_api_key()
    if test_api_key and test_api_key != "YOUR_GEMINI_API_KEY":
        print(f"API Key loaded: {test_api_key[:5]}...{test_api_key[-5:]}")
        
        # Test category loading
        cats = load_categories()
        print(f"Loaded categories: {cats}")

        if cats:
            # Test categorization
            sample_text_headphone = "Беспроводные наушники Awei T29 Pro с шумоподавлением, Bluetooth 5.1, отличное звучание"
            sample_text_charger = "Быстрое зарядное устройство USB-C PD 20W для iPhone и Android"
            sample_text_headphone = "Беспроводные наушники Awei T29 Pro с шумоподавлением, Bluetooth 5.1, отличное звучание"
            # For image-based test, you'd need a sample image path.
            # This test will likely fail without a valid image path.
            # For now, we'll assume a placeholder path for the test structure.
            sample_image_path_placeholder = "path/to/sample_image.jpg" # User needs to replace this for local testing
            print(f"Note: Standalone test requires a valid image at '{sample_image_path_placeholder}'")


            print(f"\nTesting with text: '{sample_text_headphone}' and image (placeholder): '{sample_image_path_placeholder}'")
            if os.path.exists(sample_image_path_placeholder):
                 category = get_category_from_gemini(sample_image_path_placeholder, sample_text_headphone, cats, test_api_key)
                 print(f"Suggested Category: {category}")
            else:
                 print(f"Skipping image test as '{sample_image_path_placeholder}' does not exist.")

        else:
            print("Skipping categorization test as no categories were loaded or API key is placeholder.")
    else:
        print("Gemini API key not configured in telegram/config.ini or is a placeholder. Skipping live tests.")
