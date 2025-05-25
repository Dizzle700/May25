# utils.py - Utility functions
import re
import os

# --- Configuration Constants ---
MAX_FILENAME_LENGTH = 200  # Adjusted for better compatibility
SETTINGS_ORGANIZATION = "MyCompany"  # Or your name/org
SETTINGS_APPNAME = "TelegramImageDownloader"
CONFIG_FILENAME = "config.ini"
DATABASE_FILENAME = "telegram_downloads.db"

# --- Helper Functions ---
def sanitize_filename(filename, exclusion_patterns=None):
    """
    Sanitizes a string to be used as a filename.
    If exclusion_patterns is provided, will remove any matching patterns from the filename.
    """
    # Apply exclusions if provided
    if exclusion_patterns:
        for pattern in exclusion_patterns:
            if pattern.startswith("regex:"):
                regex_pattern = pattern[6:]  # Remove "regex:" prefix
                try:
                    filename = re.sub(regex_pattern, '', filename)
                except re.error:
                    pass  # If regex is invalid, just skip it
            else:
                filename = filename.replace(pattern, '')
    
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    sanitized = re.sub(r'[_ ]+', '_', sanitized)
    sanitized = sanitized.strip('_ ')
    
    if len(sanitized) > MAX_FILENAME_LENGTH:
        base, ext = os.path.splitext(sanitized)
        if ext and len(ext) < 10: # Basic check for a reasonable extension
             max_base_len = MAX_FILENAME_LENGTH - len(ext)
             sanitized = base[:max_base_len] + ext
        else:
             sanitized = sanitized[:MAX_FILENAME_LENGTH]
    
    if not sanitized:
        return "downloaded_image"
    return sanitized