# config_manager.py - Handles application configuration
import configparser
import os
from utils import CONFIG_FILENAME

class ConfigManager:
    def __init__(self, filename=CONFIG_FILENAME):
        self.filename = filename
        self.config = configparser.ConfigParser()
        self._load_config()

    def _load_config(self):
        if not os.path.exists(self.filename):
            self._create_default_config()
        self.config.read(self.filename)

    def _create_default_config(self):
        self.config['Telegram'] = {
            'api_id': '',
            'api_hash': '',
            'phone_number': ''
        }
        self.config['UserPreferences'] = {
            'save_folder': '',
            'channel': '',
            'start_date': '', # YYYY-MM-DD
            'export_excel': 'False',
            'preserve_names': 'False',
            'exclusion_patterns': ''
        }
        with open(self.filename, 'w') as configfile:
            self.config.write(configfile)
        print(f"Created default configuration file: {self.filename}. Please edit it with your details.")

    def get_telegram_credentials(self):
        try:
            api_id = self.config.get('Telegram', 'api_id')
            api_hash = self.config.get('Telegram', 'api_hash')
            phone_number = self.config.get('Telegram', 'phone_number')
            if not api_id or not api_hash or not phone_number:
                return None, None, None # Indicate missing credentials
            return api_id, api_hash, phone_number
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._create_default_config() # Recreate if section/option missing
            return None, None, None

    def get_value(self, section, option, fallback=None):
        try:
            return self.config.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def set_value(self, section, option, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, str(value))
        self._save_config()

    def _save_config(self):
        with open(self.filename, 'w') as configfile:
            self.config.write(configfile)

    def ensure_telegram_config_exists(self):
        """Checks if essential Telegram config exists, returns True if okay."""
        api_id, api_hash, phone = self.get_telegram_credentials()
        return bool(api_id and api_hash and phone)