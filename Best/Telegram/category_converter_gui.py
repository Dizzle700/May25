import tkinter as tk
from tkinter import filedialog, messagebox
import json
import re

# --- Conversion Logic (from previous scripts) ---
def slugify(text):
    text = text.lower()
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya',
    }
    for char, replacement in translit_map.items():
        text = text.replace(char, replacement)
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return text

def convert_to_nested_json(file_content):
    parsed_data = {}
    current_major_category_slug = None
    major_id_counter = 1
    sub_id_counter = 1

    for line in file_content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            major_cat_raw = line[1:].strip().replace(':', '')
            major_cat_display_name = major_cat_raw # Use raw name
            current_major_category_slug = slugify(major_cat_display_name)

            if current_major_category_slug not in parsed_data:
                parsed_data[current_major_category_slug] = {
                    "id": f"cat_maj_{major_id_counter:02d}", # New ID format
                    "major_category": major_cat_display_name,
                    "slug": current_major_category_slug,
                    "sub_categories": {}
                }
                major_id_counter += 1
        elif line.startswith('-') and current_major_category_slug:
            sub_cat_raw = line[1:].strip()
            sub_cat_display_name = sub_cat_raw # Use raw name
            sub_cat_slug = slugify(sub_cat_display_name)

            if sub_cat_slug not in parsed_data[current_major_category_slug]["sub_categories"]:
                parsed_data[current_major_category_slug]["sub_categories"][sub_cat_slug] = {
                    "id": f"cat_sub_{sub_id_counter:02d}", # New ID format
                    "name": sub_cat_display_name,
                    "slug": sub_cat_slug
                }
                sub_id_counter += 1

    final_json_output = []
    for major_cat_slug in sorted(parsed_data.keys()):
        major_cat_data = parsed_data[major_cat_slug]
        sub_categories_list = []
        for sub_cat_slug in sorted(major_cat_data["sub_categories"].keys()):
            sub_categories_list.append(major_cat_data["sub_categories"][sub_cat_slug])
        final_json_output.append({
            "id": major_cat_data["id"],
            "major_category": major_cat_data["major_category"],
            "slug": major_cat_data["slug"],
            "sub_categories": sub_categories_list
        })
    return final_json_output

def convert_to_flat_json(file_content):
    flat_output = []
    major_id_counter = 1
    sub_id_counter = 1
    major_category_slug_to_id = {} # To map slugs to IDs for parent_id

    for line in file_content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            major_cat_raw = line[1:].strip().replace(':', '')
            major_cat_display_name = major_cat_raw # Use raw name
            major_cat_slug = slugify(major_cat_display_name)

            if major_cat_slug not in major_category_slug_to_id:
                major_category_id = f"cat_maj_{major_id_counter:02d}" # New ID format
                major_category_slug_to_id[major_cat_slug] = major_category_id
                flat_output.append({
                    "id": major_category_id,
                    "name": major_cat_display_name,
                    "slug": major_cat_slug,
                    "parent_id": None,
                    "type": "major"
                })
                major_id_counter += 1

    current_major_category_slug = None
    for line in file_content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            major_cat_raw = line[1:].strip().replace(':', '')
            major_cat_display_name = major_cat_raw # Use raw name
            current_major_category_slug = slugify(major_cat_display_name)

        elif line.startswith('-') and current_major_category_slug:
            sub_cat_raw = line[1:].strip()
            sub_cat_display_name = sub_cat_raw # Use raw name
            sub_cat_slug = slugify(sub_cat_display_name)
            target_parent_id = major_category_slug_to_id.get(current_major_category_slug)

            exists = False
            for item in flat_output:
                if item.get("slug") == sub_cat_slug and item.get("parent_id") == target_parent_id:
                    exists = True
                    break
            
            if not exists:
                flat_output.append({
                    "id": f"cat_sub_{sub_id_counter:02d}", # New ID format
                    "name": sub_cat_display_name,
                    "slug": sub_cat_slug,
                    "parent_id": target_parent_id,
                    "type": "sub"
                })
                sub_id_counter += 1

    final_sorted_output = sorted(flat_output, key=lambda x: x["id"])
    return final_sorted_output

# --- GUI Application ---
class CategoryConverterApp:
    def __init__(self, master):
        self.master = master
        master.title("Category Converter")

        # Input File
        self.input_frame = tk.Frame(master)
        self.input_frame.pack(pady=10)
        tk.Label(self.input_frame, text="Input File:").pack(side=tk.LEFT)
        self.input_path_var = tk.StringVar()
        self.input_entry = tk.Entry(self.input_frame, textvariable=self.input_path_var, width=50)
        self.input_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(self.input_frame, text="Browse", command=self.browse_input_file).pack(side=tk.LEFT)

        # Output File
        self.output_frame = tk.Frame(master)
        self.output_frame.pack(pady=10)
        tk.Label(self.output_frame, text="Output File:").pack(side=tk.LEFT)
        self.output_path_var = tk.StringVar()
        self.output_entry = tk.Entry(self.output_frame, textvariable=self.output_path_var, width=50)
        self.output_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(self.output_frame, text="Browse", command=self.browse_output_file).pack(side=tk.LEFT)

        # Structure Type
        self.structure_frame = tk.Frame(master)
        self.structure_frame.pack(pady=10)
        tk.Label(self.structure_frame, text="Output Structure:").pack(side=tk.LEFT)
        self.structure_type = tk.StringVar(value="nested")
        tk.Radiobutton(self.structure_frame, text="Nested JSON", variable=self.structure_type, value="nested").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(self.structure_frame, text="Flat JSON", variable=self.structure_type, value="flat").pack(side=tk.LEFT, padx=5)

        # Convert Button
        self.convert_button = tk.Button(master, text="Convert", command=self.convert_categories)
        self.convert_button.pack(pady=20)

        # Status Label
        self.status_label = tk.Label(master, text="", fg="blue")
        self.status_label.pack(pady=5)

    def browse_input_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Input Text File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            self.input_path_var.set(file_path)

    def browse_output_file(self):
        file_path = filedialog.asksaveasfilename(
            title="Save Output JSON File",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            self.output_path_var.set(file_path)

    def convert_categories(self):
        input_file = self.input_path_var.get()
        output_file = self.output_path_var.get()
        selected_structure = self.structure_type.get()

        if not input_file or not output_file:
            messagebox.showerror("Error", "Please select both input and output files.")
            return

        try:
            print(f"Attempting to read input file: {input_file}")
            with open(input_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
            print(f"Successfully read input file. Content length: {len(file_content)} characters.")

            if selected_structure == "nested":
                print("Converting to nested JSON...")
                converted_data = convert_to_nested_json(file_content)
            else: # flat
                print("Converting to flat JSON...")
                converted_data = convert_to_flat_json(file_content)
            print(f"Conversion complete. Data size: {len(converted_data)} items.")

            print(f"Attempting to write output file: {output_file}")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(converted_data, f, ensure_ascii=False, indent=2)
            print("Successfully wrote output file.")

            self.status_label.config(text=f"Conversion successful! Output saved to {output_file}", fg="green")
        except Exception as e:
            print(f"An error occurred during conversion: {e}") # Print to console for debugging
            self.status_label.config(text=f"Error during conversion: {e}", fg="red")
            messagebox.showerror("Conversion Error", f"An error occurred: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = CategoryConverterApp(root)
    root.mainloop()
