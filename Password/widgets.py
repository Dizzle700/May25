# widgets.py
import random
import string
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QMessageBox, QCheckBox, QSpinBox, QFormLayout, QTextEdit,
    QComboBox
)
from PyQt6.QtCore import Qt
import secrets # Use secrets for password generation

class BaseDialog(QDialog):
    """ Base class for common dialog setup. """
    def __init__(self, parent=None, title="Dialog"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True) # Block interaction with main window
        self.layout = QVBoxLayout(self)

class LoginDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Enter Master Password")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.layout.addWidget(QLabel("Master Password:"))
        self.layout.addWidget(self.password_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_password(self):
        return self.password_input.text()

class SetupDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Setup Master Password")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.layout.addWidget(QLabel("Choose a strong Master Password:"))
        self.layout.addWidget(self.password_input)
        self.layout.addWidget(QLabel("Confirm Master Password:"))
        self.layout.addWidget(self.confirm_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def validate_and_accept(self):
        pwd = self.password_input.text()
        confirm = self.confirm_input.text()
        if not pwd:
             QMessageBox.warning(self, "Input Error", "Password cannot be empty.")
             return
        if pwd != confirm:
            QMessageBox.warning(self, "Input Error", "Passwords do not match.")
            return
        self.accept() # Only accept if valid

    def get_password(self):
        return self.password_input.text()


class AddEditEntryDialog(BaseDialog):
    def __init__(self, parent=None, entry_data=None):
        title = "Edit Entry" if entry_data else "Add New Entry"
        super().__init__(parent, title)
        self.entry_data = entry_data or {} # Store existing data if editing

        self.form_layout = QFormLayout()
        self.title_input = QLineEdit(self.entry_data.get('title', ''))
        self.username_input = QLineEdit(self.entry_data.get('username', ''))
        self.password_input = QLineEdit(self.entry_data.get('password', ''))
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.url_input = QLineEdit(self.entry_data.get('url', ''))
        self.notes_input = QTextEdit(self.entry_data.get('notes', ''))
        self.notes_input.setAcceptRichText(False) # Plain text notes

        # Password visibility toggle
        self.show_pass_button = QPushButton("Show")
        self.show_pass_button.setCheckable(True)
        self.show_pass_button.setFixedWidth(60)
        self.show_pass_button.toggled.connect(self.toggle_password_visibility)

        # Password Generator Button
        self.gen_pass_button = QPushButton("Generate")
        self.gen_pass_button.setFixedWidth(80)
        self.gen_pass_button.clicked.connect(self.open_password_generator) # Connect later

        password_layout = QHBoxLayout()
        password_layout.addWidget(self.password_input)
        password_layout.addWidget(self.show_pass_button)
        password_layout.addWidget(self.gen_pass_button)

        self.form_layout.addRow("Title:", self.title_input)
        self.form_layout.addRow("Username:", self.username_input)
        self.form_layout.addRow("Password:", password_layout)
        self.form_layout.addRow("URL:", self.url_input)
        self.form_layout.addRow("Notes:", self.notes_input)

        self.layout.addLayout(self.form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def toggle_password_visibility(self, checked):
        if checked:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_pass_button.setText("Hide")
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_pass_button.setText("Show")

    def validate_and_accept(self):
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Input Error", "Title cannot be empty.")
            return
        if not self.password_input.text():
             QMessageBox.warning(self, "Input Error", "Password cannot be empty.")
             return
        self.accept()

    def get_data(self) -> dict:
        """Returns the entered data."""
        return {
            "id": self.entry_data.get('id'), # Include ID if editing
            "title": self.title_input.text().strip(),
            "username": self.username_input.text().strip(),
            "password": self.password_input.text(), # Don't strip password
            "url": self.url_input.text().strip(),
            "notes": self.notes_input.toPlainText().strip()
        }

    def open_password_generator(self):
        """Opens the password generator dialog."""
        dialog = PasswordGeneratorDialog(self)
        if dialog.exec():
            generated_password = dialog.get_password()
            if generated_password:
                self.password_input.setText(generated_password)
                # Ensure password visibility is off after generating
                if self.show_pass_button.isChecked():
                    self.show_pass_button.setChecked(False)
                else: # If it was already off, just update echo mode
                    self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

class PasswordGeneratorDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Generate Password")
        self.generated_password = ""

        options_layout = QFormLayout()
        self.length_spinbox = QSpinBox()
        self.length_spinbox.setRange(8, 128)
        self.length_spinbox.setValue(16) # Default length

        self.upper_check = QCheckBox("Include Uppercase (A-Z)")
        self.upper_check.setChecked(True)
        self.lower_check = QCheckBox("Include Lowercase (a-z)")
        self.lower_check.setChecked(True)
        self.digits_check = QCheckBox("Include Digits (0-9)")
        self.digits_check.setChecked(True)
        self.symbols_check = QCheckBox("Include Symbols (!@#$...?)")
        self.symbols_check.setChecked(True)

        self.result_display = QLineEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setMinimumWidth(300)

        generate_button = QPushButton("Generate")
        generate_button.clicked.connect(self.generate)

        options_layout.addRow("Length:", self.length_spinbox)
        options_layout.addRow(self.upper_check)
        options_layout.addRow(self.lower_check)
        options_layout.addRow(self.digits_check)
        options_layout.addRow(self.symbols_check)

        self.layout.addLayout(options_layout)
        self.layout.addWidget(generate_button)
        self.layout.addWidget(QLabel("Generated Password:"))
        self.layout.addWidget(self.result_display)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use Password")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def generate(self):
        length = self.length_spinbox.value()
        chars = ""
        if self.lower_check.isChecked():
            chars += string.ascii_lowercase
        if self.upper_check.isChecked():
            chars += string.ascii_uppercase
        if self.digits_check.isChecked():
            chars += string.digits
        if self.symbols_check.isChecked():
            chars += string.punctuation # Consider defining a specific symbol set

        if not chars:
            QMessageBox.warning(self, "Options Error", "Please select at least one character set.")
            self.generated_password = ""
            self.result_display.clear()
            return

        # Ensure the password contains at least one of each selected type (optional but good practice)
        password_list = []
        if self.lower_check.isChecked(): password_list.append(secrets.choice(string.ascii_lowercase))
        if self.upper_check.isChecked(): password_list.append(secrets.choice(string.ascii_uppercase))
        if self.digits_check.isChecked(): password_list.append(secrets.choice(string.digits))
        if self.symbols_check.isChecked(): password_list.append(secrets.choice(string.punctuation))

        remaining_length = length - len(password_list)
        if remaining_length > 0:
             password_list.extend(secrets.choice(chars) for _ in range(remaining_length))

        random.shuffle(password_list) # Shuffle to mix required chars randomly
        self.generated_password = "".join(password_list)
        self.result_display.setText(self.generated_password)

    def get_password(self):
        # Return only if generated, otherwise return empty
        return self.generated_password if hasattr(self, 'generated_password') else ""

class AddEditCreditCardDialog(BaseDialog):
    def __init__(self, parent=None, card_data=None):
        title = "Edit Credit Card" if card_data else "Add New Credit Card"
        super().__init__(parent, title)
        self.card_data = card_data or {} # Store existing data if editing

        self.form_layout = QFormLayout()
        
        # Card nickname/identifier
        self.card_name_input = QLineEdit(self.card_data.get('card_name', ''))
        self.form_layout.addRow("Card Name:", self.card_name_input)
        
        # Card number with visibility toggle and formatting
        self.card_number_input = QLineEdit(self.card_data.get('card_number', '').replace(' ', ''))
        self.card_number_input.setEchoMode(QLineEdit.EchoMode.Normal)  # Show by default
        self.card_number_input.setInputMask("9999 9999 9999 9999;_")  # Format as blocks of 4 digits
        
        # Card number visibility toggle
        self.show_number_button = QPushButton("Hide")  # Initially "Hide" since shown by default
        self.show_number_button.setCheckable(True)
        self.show_number_button.setChecked(True)  # Set to checked by default (shown)
        self.show_number_button.setFixedWidth(60)
        self.show_number_button.toggled.connect(self.toggle_card_number_visibility)
        
        card_number_layout = QHBoxLayout()
        card_number_layout.addWidget(self.card_number_input)
        card_number_layout.addWidget(self.show_number_button)
        
        self.form_layout.addRow("Card Number:", card_number_layout)
        
        # Cardholder name
        self.cardholder_name_input = QLineEdit(self.card_data.get('cardholder_name', ''))
        self.form_layout.addRow("Cardholder Name:", self.cardholder_name_input)
        
        # Expiry date (MM/YY) with formatting
        self.expiry_date_input = QLineEdit(self.card_data.get('expiry_date', ''))
        self.expiry_date_input.setInputMask("99/99;_")  # Format as MM/YY
        self.expiry_date_input.setPlaceholderText("MM/YY")
        self.form_layout.addRow("Expiry Date:", self.expiry_date_input)
        
        # CVV with visibility toggle and formatting
        self.cvv_input = QLineEdit(self.card_data.get('cvv', ''))
        self.cvv_input.setEchoMode(QLineEdit.EchoMode.Normal)  # Show by default
        self.cvv_input.setInputMask("999;_")  # Accept exactly 3 digits
        self.cvv_input.setMaxLength(3)  # CVV is 3 digits for most cards
        
        # CVV visibility toggle
        self.show_cvv_button = QPushButton("Hide")  # Initially "Hide" since shown by default
        self.show_cvv_button.setCheckable(True)
        self.show_cvv_button.setChecked(True)  # Set to checked by default (shown)
        self.show_cvv_button.setFixedWidth(60)
        self.show_cvv_button.toggled.connect(self.toggle_cvv_visibility)
        
        cvv_layout = QHBoxLayout()
        cvv_layout.addWidget(self.cvv_input)
        cvv_layout.addWidget(self.show_cvv_button)
        
        self.form_layout.addRow("CVV:", cvv_layout)
        
        # Card type dropdown
        self.card_type_input = QComboBox()
        self.card_type_input.addItems(["", "Visa", "Mastercard", "American Express", "Discover", "Other"])
        if 'card_type' in self.card_data:
            self.card_type_input.setCurrentText(self.card_data.get('card_type'))
        self.form_layout.addRow("Card Type:", self.card_type_input)
        
        # Notes
        self.notes_input = QTextEdit(self.card_data.get('notes', ''))
        self.notes_input.setAcceptRichText(False)
        self.form_layout.addRow("Notes:", self.notes_input)
        
        self.layout.addLayout(self.form_layout)
        
        # Save/Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
    
    def toggle_card_number_visibility(self, checked):
        """Shows or hides the card number."""
        if checked:
            self.card_number_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_number_button.setText("Hide")
        else:
            self.card_number_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_number_button.setText("Show")
    
    def toggle_cvv_visibility(self, checked):
        """Shows or hides the CVV."""
        if checked:
            self.cvv_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_cvv_button.setText("Hide")
        else:
            self.cvv_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_cvv_button.setText("Show")
    
    def validate_and_accept(self):
        """Validates the input fields before accepting."""
        # Check for required fields
        if not self.card_name_input.text().strip():
            QMessageBox.warning(self, "Input Error", "Card name cannot be empty.")
            return
        
        # Get clean card number (no spaces)
        card_number = self.card_number_input.text().replace(' ', '')
        if not card_number.strip():
            QMessageBox.warning(self, "Input Error", "Card number cannot be empty.")
            return
        
        # Check if card number has the right number of digits (usually 13-19)
        if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
            QMessageBox.warning(self, "Input Error", "Card number must be 13-19 digits.")
            return
        
        if not self.cardholder_name_input.text().strip():
            QMessageBox.warning(self, "Input Error", "Cardholder name cannot be empty.")
            return
        
        # Basic validation for expiry date format (MM/YY)
        expiry = self.expiry_date_input.text().strip()
        if not expiry or '_' in expiry:  # Check for incomplete input mask
            QMessageBox.warning(self, "Input Error", "Expiry date must be complete in MM/YY format.")
            return
        
        # Validate month is 01-12
        try:
            month, year = expiry.split('/')
            if not (1 <= int(month) <= 12):
                QMessageBox.warning(self, "Input Error", "Month must be between 01 and 12.")
                return
        except (ValueError, IndexError):
            QMessageBox.warning(self, "Input Error", "Expiry date must be in MM/YY format.")
            return
        
        # Validate CVV (3 digits)
        cvv = self.cvv_input.text().strip()
        if not cvv or '_' in cvv:  # Check for incomplete input mask
            QMessageBox.warning(self, "Input Error", "CVV must be complete (3 digits).")
            return
        
        if len(cvv) != 3:
            QMessageBox.warning(self, "Input Error", "CVV must be exactly 3 digits.")
            return
        
        # If all validations pass, accept the dialog
        self.accept()
    
    def get_data(self) -> dict:
        """Returns the entered data."""
        # Remove spaces from card number before storing
        card_number = self.card_number_input.text().replace(' ', '')
        
        return {
            "id": self.card_data.get('id'),  # Include ID if editing
            "card_name": self.card_name_input.text().strip(),
            "card_number": card_number,  # Store without spaces
            "cardholder_name": self.cardholder_name_input.text().strip(),
            "expiry_date": self.expiry_date_input.text().strip(),
            "cvv": self.cvv_input.text().strip(),
            "card_type": self.card_type_input.currentText(),
            "notes": self.notes_input.toPlainText().strip()
        }