import os
import google.generativeai as genai
from PIL import Image

def append_category_to_file(category, categories_file_path):
    """Appends a new category to the specified categories file."""
    if not category or not categories_file_path:
        return
    try:
        with open(categories_file_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{category}")
        print(f"INFO: New category '{category}' appended to {os.path.basename(categories_file_path)}.")
    except Exception as e:
        print(f"Error: Could not append category to {categories_file_path}: {e}")

def generate_new_category(image_path, text_to_categorize, api_key):
    """
    Uses Gemini AI to generate a new product category based on the image and text.

    Args:
        image_path (str): Path to the image file.
        text_to_categorize (str): The text (e.g., product caption) to use for context.
        api_key (str): The Gemini API key.

    Returns:
        str: The newly generated category name, or 'не удалось создать' on failure.
    """
    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        return "не настроен API ключ"

    if not image_path or not os.path.exists(image_path):
        print(f"Warning: Image path invalid for new category generation: {image_path}.")
        return "файл изображения не найден"

    try:
        genai.configure(api_key=api_key)
        
        img = Image.open(image_path)

        model_name_to_use = "gemini-1.5-pro-latest" 
        
        generation_config = {
            "temperature": 0.4, # Slightly more creative for generation
            "top_p": 1,
            "top_k": 32,
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

        prompt_text = (
            f"Проанализируй это изображение и текст: \"{text_to_categorize if text_to_categorize else 'Нет текста.'}\". "
            "Придумай краткое и точное название для новой категории товаров, к которой относится этот предмет. "
            "Название должно быть на русском языке. Ответь только названием категории. "
            "Например: 'Беспроводные наушники', 'Чехлы для телефонов', 'Умные часы'."
        )
        
        response = model.generate_content([prompt_text, img])
        
        if response.parts:
            new_category = response.text.strip()
            if new_category and 0 < len(new_category) <= 100:
                print(f"INFO: Gemini generated new category: '{new_category}'")
                # Simple cleaning: remove potential quotes
                new_category = new_category.replace('"', '').replace("'", "")
                return new_category
            else:
                print(f"Warning: Gemini returned an empty or unusual string for a new category: '{new_category}'.")
                return "не удалось создать"
        else:
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                 return f"заблокировано ({response.prompt_feedback.block_reason.name})"
            return "нет ответа от AI"

    except Exception as e:
        print(f"An error occurred while generating a new category with Gemini API: {e}")
        if "API key not valid" in str(e):
            return "неверный API ключ"
        return "ошибка AI"

if __name__ == '__main__':
    print("New Category Generator Module")
    # This part is for testing and requires manual setup of API key and image path.
    # print("To test, set api_key and provide a valid image_path and text.")
    # api_key = "YOUR_GEMINI_API_KEY_HERE" 
    # image_path = "path/to/your/image.jpg"
    # text = "Some descriptive text"
    # if api_key != "YOUR_GEMINI_API_KEY_HERE" and os.path.exists(image_path):
    #     new_cat = generate_new_category(image_path, text, api_key)
    #     print(f"Generated Category: {new_cat}")
    #
    #     # Test appending to file
    #     test_cat_file = "test_categories_append.txt"
    #     append_category_to_file(new_cat, test_cat_file)
    #     if os.path.exists(test_cat_file):
    #         print(f"Check content of {test_cat_file}")
