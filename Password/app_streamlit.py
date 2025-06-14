# app_streamlit.py
import streamlit as st
import os
import tempfile
import string
import secrets
import random

# Import your existing, well-structured modules
import db_manager
import crypto_utils

# --- Page Configuration ---
st.set_page_config(
    page_title="PyVaultSecure",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Helper Functions ---

def lock_vault():
    """Clears all sensitive session state to lock the vault."""
    for key in list(st.session_state.keys()):
        # Don't clear keys that control the file path itself, just the session data
        if key not in ['db_path', 'db_name', 'db_created_new']:
            del st.session_state[key]
    st.rerun()

def generate_password(length=16, upper=True, lower=True, digits=True, symbols=True):
    """Generates a secure password based on specified criteria."""
    chars = ""
    if lower: chars += string.ascii_lowercase
    if upper: chars += string.ascii_uppercase
    if digits: chars += string.digits
    if symbols: chars += string.punctuation
    
    if not chars:
        return "" # Return empty if no character set is selected

    # Ensure at least one of each selected type
    password_list = []
    if lower: password_list.append(secrets.choice(string.ascii_lowercase))
    if upper: password_list.append(secrets.choice(string.ascii_uppercase))
    if digits: password_list.append(secrets.choice(string.digits))
    if symbols: password_list.append(secrets.choice(string.punctuation))

    remaining_length = length - len(password_list)
    if remaining_length > 0:
        password_list.extend(secrets.choice(chars) for _ in range(remaining_length))

    random.shuffle(password_list)
    return "".join(password_list)


# --- Initialize Session State ---
# This is crucial for controlling the app's flow
if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'db_path' not in st.session_state:
    st.session_state.db_path = None
if 'derived_key' not in st.session_state:
    st.session_state.derived_key = None
if 'selected_entry_id' not in st.session_state:
    st.session_state.selected_entry_id = None
if 'selected_entry_type' not in st.session_state:
    st.session_state.selected_entry_type = None

# ==============================================================================
# VIEW: LOCKED / AUTHENTICATION
# ==============================================================================
if st.session_state.derived_key is None:
    st.title("🔐 PyVaultSecure - Vault is Locked")
    st.markdown("---")

    # --- Step 1: Select or Create Database ---
    if st.session_state.db_path is None:
        st.header("Step 1: Open or Create a Vault")
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Open Existing Vault")
            uploaded_file = st.file_uploader("Select a .db or .sqlite file", type=['db', 'sqlite'])
            if uploaded_file is not None:
                # To use the uploaded file, we must save it to a temporary location
                with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                    tmp.write(uploaded_file.getvalue())
                    st.session_state.db_path = tmp.name
                st.session_state.db_name = uploaded_file.name
                st.rerun()
        
        with col2:
            st.subheader("Create New Vault")
            with st.form("create_db_form"):
                new_db_name = st.text_input("New vault filename", placeholder="e.g., my_secure_vault")
                submitted = st.form_submit_button("Create")
                if submitted and new_db_name:
                    # Create in a temporary directory for this session
                    temp_dir = tempfile.mkdtemp()
                    db_path = os.path.join(temp_dir, f"{new_db_name}.db")
                    db_manager.create_new_database_file(db_path)
                    st.session_state.db_path = db_path
                    st.session_state.db_name = f"{new_db_name}.db"
                    st.session_state.db_created_new = True # Flag to show download button
                    st.rerun()

    # --- Step 2: Login or Setup ---
    else:
        st.header(f"Step 2: Unlock Vault '{st.session_state.db_name}'")
        db_manager.set_database_path(st.session_state.db_path)
        salt = db_manager.get_metadata('salt')

        if not salt:
            # --- SETUP FORM ---
            st.warning("This new vault needs a Master Password.")
            with st.form("setup_form"):
                password = st.text_input("Choose Master Password", type="password")
                confirm_password = st.text_input("Confirm Master Password", type="password")
                submitted = st.form_submit_button("Set Password and Unlock")
                if submitted:
                    if not password or password != confirm_password:
                        st.error("Passwords do not match or are empty.")
                    else:
                        new_salt = crypto_utils.generate_salt()
                        key = crypto_utils.derive_key(password, new_salt)
                        check = crypto_utils.generate_encryption_check(key)
                        db_manager.store_metadata('salt', new_salt)
                        db_manager.store_metadata('encryption_check', check)
                        st.session_state.derived_key = key
                        st.success("Vault created and unlocked!")
                        st.rerun()
        else:
            # --- LOGIN FORM ---
            with st.form("login_form"):
                password = st.text_input("Master Password", type="password")
                submitted = st.form_submit_button("Unlock")
                if submitted:
                    stored_check = db_manager.get_metadata('encryption_check')
                    key = crypto_utils.derive_key(password, salt)
                    if crypto_utils.verify_encryption_check(key, stored_check):
                        st.session_state.derived_key = key
                        st.success("Vault Unlocked!")
                        st.rerun()
                    else:
                        st.error("Incorrect Master Password.")
        
        if st.button("‹ Back to Vault Selection"):
            st.session_state.db_path = None
            st.rerun()

# ==============================================================================
# VIEW: UNLOCKED / MAIN APPLICATION
# ==============================================================================
else:
    key = st.session_state.derived_key
    db_manager.set_database_path(st.session_state.db_path)

    # --- Sidebar for Navigation and Actions ---
    with st.sidebar:
        st.header(f"✅ Vault: {st.session_state.db_name}")
        if st.button("Lock Vault", use_container_width=True, type="primary"):
            lock_vault()

        if st.session_state.get('db_created_new', False):
             with open(st.session_state.db_path, "rb") as fp:
                st.download_button(
                    label="Download Your New Vault File",
                    data=fp,
                    file_name=st.session_state.db_name,
                    mime="application/octet-stream",
                    use_container_width=True
                )
             st.warning("Save this file! It will be lost when you close this browser tab.")

        st.markdown("---")
        st.subheader("Add New")
        if st.button("✚ Password", use_container_width=True):
            st.session_state.page = 'add_password'
            st.rerun()
        if st.button("✚ Credit Card", use_container_width=True):
            st.session_state.page = 'add_credit_card'
            st.rerun()
        st.markdown("---")

        st.subheader("All Entries")
        # Load entries and display in sidebar
        password_entries = db_manager.get_all_entry_ids_titles(key)
        cc_entries = db_manager.get_all_credit_card_ids_names(key)

        for entry_id, title in password_entries:
            if st.button(f"🔑 {title}", key=f"pwd_{entry_id}", use_container_width=True):
                st.session_state.page = 'view'
                st.session_state.selected_entry_id = entry_id
                st.session_state.selected_entry_type = "password"
                st.rerun()
        
        for card_id, name in cc_entries:
            if st.button(f"💳 {name}", key=f"cc_{card_id}", use_container_width=True):
                st.session_state.page = 'view'
                st.session_state.selected_entry_id = card_id
                st.session_state.selected_entry_type = "credit_card"
                st.rerun()
    
    # --- Main Content Area ---
    if st.session_state.page == 'main':
        st.title("Welcome to PyVaultSecure")
        st.info("Select an item from the sidebar to view its details, or add a new one.")

    # --- VIEW/EDIT/DELETE ---
    elif st.session_state.page == 'view':
        entry_id = st.session_state.selected_entry_id
        entry_type = st.session_state.selected_entry_type
        
        details = None
        if entry_type == "password":
            details = db_manager.get_entry_details(key, entry_id)
            st.header(f"🔑 Details for: {details.get('title')}")
        elif entry_type == "credit_card":
            details = db_manager.get_credit_card_details(key, entry_id)
            st.header(f"💳 Details for: {details.get('card_name')}")

        if not details:
            st.error("Could not load entry details.")
            st.session_state.page = 'main'
            st.rerun()
        
        # Display fields
        for field, value in details.items():
            if field in ['id', 'error']: continue
            st.text_input(f"**{field.replace('_', ' ').title()}**", value=value, disabled=True, key=f"view_{field}")
        
        # Actions: Edit and Delete
        col1, col2, _ = st.columns([1, 1, 4])
        with col1:
            if st.button("Edit", use_container_width=True):
                st.session_state.page = f'edit_{entry_type}'
                st.rerun()
        with col2:
            if st.button("Delete", use_container_width=True):
                st.session_state.page = f'delete_{entry_type}'
                st.rerun()

    # --- DYNAMIC FORMS ---
    # ADD PASSWORD
    elif st.session_state.page == 'add_password':
        st.header("Add New Password Entry")
        with st.form("add_password_form", clear_on_submit=True):
            title = st.text_input("Title*")
            username = st.text_input("Username")
            
            # Password Generator
            col1, col2 = st.columns([3, 1])
            with col1:
                password = st.text_input("Password*", type="password")
            with col2:
                if st.form_submit_button("Generate"):
                    st.session_state.generated_pass = generate_password()

            if 'generated_pass' in st.session_state and st.session_state.generated_pass:
                st.info(f"Generated Password: `{st.session_state.generated_pass}` (it will be used if password field is empty)")
            
            url = st.text_input("URL")
            notes = st.text_area("Notes")

            submitted = st.form_submit_button("Save Entry")
            if submitted:
                final_password = password or st.session_state.get('generated_pass', '')
                if not title or not final_password:
                    st.error("Title and Password are required fields.")
                else:
                    db_manager.add_entry(key, title, username, final_password, url, notes)
                    st.success(f"Entry '{title}' saved successfully!")
                    st.session_state.page = 'main'
                    if 'generated_pass' in st.session_state: del st.session_state.generated_pass
                    st.rerun()

    # EDIT PASSWORD
    elif st.session_state.page == 'edit_password':
        st.header("Edit Password Entry")
        details = db_manager.get_entry_details(key, st.session_state.selected_entry_id)
        with st.form("edit_password_form"):
            title = st.text_input("Title*", value=details.get('title'))
            username = st.text_input("Username", value=details.get('username'))
            password = st.text_input("Password*", type="password", placeholder="Enter new password or leave blank to keep old")
            url = st.text_input("URL", value=details.get('url'))
            notes = st.text_area("Notes", value=details.get('notes'))
            
            submitted = st.form_submit_button("Update Entry")
            if submitted:
                final_password = password if password else details.get('password')
                if not title:
                    st.error("Title is a required field.")
                else:
                    db_manager.update_entry(key, details['id'], title, username, final_password, url, notes)
                    st.success(f"Entry '{title}' updated successfully!")
                    st.session_state.page = 'view' # Go back to viewing this entry
                    st.rerun()

    # ADD/EDIT CREDIT CARD (Simplified for brevity - can be expanded like password)
    elif st.session_state.page in ['add_credit_card', 'edit_credit_card']:
        is_edit = st.session_state.page == 'edit_credit_card'
        details = db_manager.get_credit_card_details(key, st.session_state.selected_entry_id) if is_edit else {}
        
        st.header("Edit Credit Card" if is_edit else "Add New Credit Card")
        with st.form("cc_form"):
            card_name = st.text_input("Card Name*", value=details.get('card_name', ''))
            card_number = st.text_input("Card Number*", value=details.get('card_number', ''))
            cardholder_name = st.text_input("Cardholder Name*", value=details.get('cardholder_name', ''))
            
            col1, col2 = st.columns(2)
            with col1:
                expiry_date = st.text_input("Expiry (MM/YY)*", value=details.get('expiry_date', ''))
            with col2:
                cvv = st.text_input("CVV*", value=details.get('cvv', ''), type="password")
            
            card_type = st.selectbox("Card Type", ["", "Visa", "Mastercard", "American Express", "Discover", "Other"], index=0)
            notes = st.text_area("Notes", value=details.get('notes', ''))
            
            submitted = st.form_submit_button("Save Card" if not is_edit else "Update Card")
            if submitted:
                if not all([card_name, card_number, cardholder_name, expiry_date, cvv]):
                    st.error("All fields marked with * are required.")
                else:
                    if is_edit:
                        db_manager.update_credit_card(key, details['id'], card_name, card_number, cardholder_name, expiry_date, cvv, card_type, notes)
                        st.success(f"Card '{card_name}' updated!")
                        st.session_state.page = 'view'
                    else:
                        db_manager.add_credit_card(key, card_name, card_number, cardholder_name, expiry_date, cvv, card_type, notes)
                        st.success(f"Card '{card_name}' saved!")
                        st.session_state.page = 'main'
                    st.rerun()

    # DELETE CONFIRMATION
    elif 'delete_' in st.session_state.page:
        entry_type = st.session_state.page.split('_')[1]
        entry_id = st.session_state.selected_entry_id
        
        details = None
        name = "[Unknown]"
        if entry_type == "password":
            details = db_manager.get_entry_details(key, entry_id)
            name = details.get('title')
        elif entry_type == "credit_card":
            details = db_manager.get_credit_card_details(key, entry_id)
            name = details.get('card_name')

        st.header(f"Confirm Deletion")
        st.error(f"Are you sure you want to permanently delete the {entry_type} entry for **'{name}'**? This action cannot be undone.")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("YES, DELETE IT", use_container_width=True, type="primary"):
                if entry_type == "password":
                    db_manager.delete_entry(entry_id)
                elif entry_type == "credit_card":
                    db_manager.delete_credit_card(entry_id)
                st.success(f"Entry '{name}' has been deleted.")
                st.session_state.page = 'main'
                st.session_state.selected_entry_id = None
                st.session_state.selected_entry_type = None
                st.rerun()
        with col2:
            if st.button("NO, CANCEL", use_container_width=True):
                st.session_state.page = 'view' # Go back to viewing
                st.rerun()