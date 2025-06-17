import json
import re

def slugify(text):
    text = text.lower()
    # Simplified transliteration for common Cyrillic characters
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya',
    }
    for char, replacement in translit_map.items():
        text = text.replace(char, replacement)

    text = re.sub(r'[^\w\s-]', '', text) # Remove all non-word chars (except space and hyphen)
    text = re.sub(r'[\s_-]+', '-', text) # Replace multiple spaces/underscores/hyphens with a single hyphen
    text = text.strip('-') # Remove leading/trailing hyphens
    return text

file_content = """
# Аудио и наушники:
  - наушники earphones
  - наушники headphones
  - наушники tws (airpods like)
  - наушники neckband
  - гарнитура handsfree
  - портативные колонки
  - Портативные Bluetooth-колонки
  - смарт колонки
  - радио

# Переходники:
  - Аудиоадаптеры (USB-C/Lightning на Jack 3.5)
  - USB-адаптеры (USB-C → USB-A, USB-A → USB-C)
  - Видеоадаптеры (USB-C → HDMI, USB-C → VGA, USB-C → DisplayPort)
  - OTG-переходники (USB-C/Micro-USB для подключения периферии)
  - Универсальные переходники для розеток (международные адаптеры)
  - Адаптеры для SSD и HDD (SATA → USB, M.2 → USB)
  - Аудиоадаптеры для стриминга (например, для петличных микрофонов)
  - Переходники для сетевых кабелей (Ethernet → USB)
  - Адаптеры для карт памяти (SD → USB-C, MicroSD → USB)
  - Мультипортовые адаптеры (USB-C хабы с HDMI/Ethernet/USB)

# Кабели:
  - Кабели зарядки (typec, micro, iphone)
  - Кабели видео (hdmi, displayport, vga)
  - Кабели аудио (Aux, Rca, coaxial)
  - Сетевые кабели
  - Кабели Питания
  - Кабели для принтеров
  - Кабели для внешних жестких дисков (SATA → USB)

# Зарядные устройства и питание:
  - зарядные устройства
  - Зарядные устройства (комлект)
  - Зарядный адаптер (блок)
  - Power Bank (внешние аккумуляторы)
  - Беспроводные зарядки
  - Bluetooth-адаптеры
  - Батарейки и аккумуляторы
  - Зарядные устройства для аккумуляторов
  - Bluetooth-адаптеры
  - Универсальные переходники для розеток
  - Ночник с зарядкой/динамиком
  - Адаптеры USB-C → HDMI/VGA
  - Адаптеры для SSD и HDD
  - Солнечные лампы
  - Эко-батарейки/аккумуляторы

# Аксессуары для авто:
  - автомобильные зарядные блоки
  - автомобильные зарядные устройства
  - автомобильные аксессуары
  - FM-трансмиттеры
  - Видеорегистраторы
  - Парктроники
  - Автомобильные пылесосы
  - Ручные пылесосы

# Аксессуары для телефонов:
  - чехлы для телефонов
  - влагозащитные чехлы и сумки
  - сумги для ноутбуков
  - Внешние микрофоны для смартфонов
  - Защитные стекла и пленки
  - Держатели для телефона
  - Попсокеты и кольца
  - Стилусы
  - Подставки под телефон
  - Аккумуляторные чехлы
  - Органайзеры для проводов
  - Сумки и чехлы для гаджетов
  - Подставки и охлаждающие подставки для ноутбуков


# Умные устройства:
  - Умные часы (Smart Watch)
  - Фитнес-браслеты
  - Ремешки для смарт-часов
  - GPS-трекеры
  - Смарт-розетки
  - Умные камеры наблюдения
  - Датчики движения / дыма
  - Умные термометры / гигрометры
  - Смарт-термокружки/термосы
  - GPS-маячки
  - Детские смарт-часы с GPS

# Компьютерные аксессуары:
  - компьютерные мыши
  - клавиатуры
  - Коврики для мыши
  - Мыши
  - Клавиатуры
  - USB-хабы
  - Wifi адаптеры
  - Bluetooth-адаптеры
  - Веб-камеры
  - USB-концентраторы с Ethernet/HDMI

# Хранение данных:
  - Карты памяти и кардридеры
  - Флешки (USB-накопители)
  - Карты памяти Microsd
  - Внешние SSD и HDD
  - Кардридеры
  - USB OTG накопители

# Фото и видео:
  - Штативы и моноподы
  - Селфи-палки
  - Кольцевые лампы и вспышки
  - Крепления для экшн-камер
  - USB-лампы

# Сетевое оборудование:
  - Wi-Fi роутеры
  - Повторители сигнала (репитеры)
  - USB-модемы

# Разное для дома:
  - Светильники
  - Электронные весы
  - Увлажнители воздуха
  - Портативные вентиляторы
  - Светодиодные ленты
  - Электронные кухонные весы
  - Увлажнители и очистители воздуха

# Игры и развлечения:
  - Игровые геймпады
  - VR-очки
  - Мини-дроны
  - Лазерные указки
  - Обучающие планшеты/игрушки


# Личная гигиена и уход:
  - Электрические зубные щетки
  - Машинки для стрижки волос / триммеры
  - Электробритвы

# Одежда и уход за ней:
  - Пароочистители
  - Отпариватели для одежды
  - Сушилки для обуви
  - Машинки для удаления катышков
  - Мини-утюги дорожные

Прочее:
  - USB-разветвители для прикуривателя
  - OTG-кабели и переходники
  - HDMI кабели и переходники
  - Android TV box (приставки Smart TV)
  - Защитные пленки/накладки на клавиатуру
  - Ультразвуковые очистители (например, для украшений или очков)
  - Электронные записные книжки/планшеты для заметок
  - Электронные ручки/перья
  - Массажёры (для лица, шеи, тела)
  - Линзы для камер смартфона

Детское:
  - GPS часы для детей
  - Детские планшеты



Праздничные открытки
Наборы для ухода за собой
"""

# Define the specific mappings based on the example and common sense
# Major category renames
major_category_renames = {
    "Аудио и наушники": "Аудио",
    # Add other major category renames here if needed, otherwise they use their raw name
}

# Sub-category aggregations and renames, keyed by original lowercased name
# Value can be a string (new name) or a dict (new name + target major category slug for re-categorization)
sub_category_mappings = {
    "наушники earphones": "Наушники (вкладыши, накладные, TWS, Neckband)",
    "наушники headphones": "Наушники (вкладыши, накладные, TWS, Neckband)",
    "наушники tws (airpods like)": "Наушники (вкладыши, накладные, TWS, Neckband)",
    "наушники neckband": "Наушники (вкладыши, накладные, TWS, Neckband)",
    "гарнитура handsfree": "Гарнитуры (Handsfree)",
    "портативные колонки": "Портативные и Bluetooth-колонки",
    "портативные bluetooth-kolonki": "Портативные и Bluetooth-колонки",
    "смарт колонки": "Смарт-колонки",
    "радио": "Радио",
    "внешние микрофоны для смартфонов": {
        "name": "Внешние микрофоны (для смартфонов и стриминга)",
        "target_major_category_slug": "audio"
    },
    "gps часы для детей": {
        "name": "Детские смарт-часы с GPS",
        "target_major_category_slug": "umnye-ustroystva" # Assuming this slug for "Умные устройства"
    }
}

# Initialize data structures for flat output
flat_output = []
id_counter = 1
major_category_slug_to_id = {} # To map slugs to IDs for parent_id

# First pass: Process major categories
for line in file_content.strip().split('\n'):
    line = line.strip()
    if not line:
        continue

    if line.startswith('#'):
        major_cat_raw = line[1:].strip().replace(':', '')
        major_cat_display_name = major_category_renames.get(major_cat_raw, major_cat_raw)
        major_cat_slug = slugify(major_cat_display_name)

        if major_cat_slug not in major_category_slug_to_id:
            major_category_id = id_counter
            major_category_slug_to_id[major_cat_slug] = major_category_id
            flat_output.append({
                "id": major_category_id,
                "name": major_cat_display_name,
                "slug": major_cat_slug,
                "parent_id": None
            })
            id_counter += 1

# Second pass: Process sub-categories and link them to their parents
# We need to iterate through the file content again to correctly associate sub-categories with their original major categories
current_major_category_slug = None
for line in file_content.strip().split('\n'):
    line = line.strip()
    if not line:
        continue

    if line.startswith('#'):
        major_cat_raw = line[1:].strip().replace(':', '')
        major_cat_display_name = major_category_renames.get(major_cat_raw, major_cat_raw)
        current_major_category_slug = slugify(major_cat_display_name)

    elif line.startswith('-') and current_major_category_slug:
        sub_cat_raw = line[1:].strip()
        sub_cat_lower = sub_cat_raw.lower()

        sub_cat_display_name = sub_cat_raw
        sub_cat_slug = slugify(sub_cat_raw)
        target_parent_id = major_category_slug_to_id.get(current_major_category_slug)

        # Check for re-categorization or aggregation
        if sub_cat_lower in sub_category_mappings:
            mapping_info = sub_category_mappings[sub_cat_lower]
            if isinstance(mapping_info, dict): # This is a re-categorized item
                sub_cat_display_name = mapping_info["name"]
                sub_cat_slug = slugify(sub_cat_display_name)
                target_major_slug = mapping_info["target_major_category_slug"]
                target_parent_id = major_category_slug_to_id.get(target_major_slug)
                # Ensure the target major category exists in flat_output, create if not (should be created in first pass)
                if target_parent_id is None:
                    # This case should ideally not happen if major categories are parsed first
                    # But as a fallback, create it
                    new_major_cat_id = id_counter
                    id_counter += 1
                    major_category_slug_to_id[target_major_slug] = new_major_cat_id
                    flat_output.append({
                        "id": new_major_cat_id,
                        "name": target_major_slug.replace('-', ' ').title(),
                        "slug": target_major_slug,
                        "parent_id": None
                    })
                    target_parent_id = new_major_cat_id
            else: # This is a renamed/aggregated item for the current category
                sub_cat_display_name = mapping_info
                sub_cat_slug = slugify(sub_cat_display_name)

        # Add sub-category if not already added (to handle aggregation)
        # Check if an item with this slug and parent_id already exists
        exists = False
        for item in flat_output:
            if item.get("slug") == sub_cat_slug and item.get("parent_id") == target_parent_id:
                exists = True
                break
        
        if not exists:
            flat_output.append({
                "id": id_counter,
                "name": sub_cat_display_name,
                "slug": sub_cat_slug,
                "parent_id": target_parent_id
            })
            id_counter += 1

# Sort the final output by ID for consistent order
final_sorted_output = sorted(flat_output, key=lambda x: x["id"])

print(json.dumps(final_sorted_output, ensure_ascii=False, indent=2))
