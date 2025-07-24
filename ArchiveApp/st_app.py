# streamlit_app.py
import streamlit as st
import os
import shutil
import zipfile
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# --- Helper Functions (from original code) ---

def format_size(size_bytes):
    """Formats a size in bytes to a human-readable string."""
    if size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels):
        size_bytes /= power
        n += 1
    return f"{size_bytes:.1f} {power_labels[n]}B"

# --- Archiving Logic (adapted from worker.py) ---

def create_zip_archive(files_to_archive, archive_path, source_folder, progress_callback, password=""):
    """
    Creates a .zip archive and reports progress.
    Note: Python's built-in zipfile module does not support password protection.
    If a password is provided, it will be ignored for ZIP archives.
    """
    if password:
        st.warning("ZIP archiving with password is not supported by the built-in Python zipfile module. Password will be ignored.")

    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        total_files = len(files_to_archive)
        for i, file_path in enumerate(files_to_archive):
            arcname = os.path.relpath(file_path, source_folder)
            
            if os.path.isdir(file_path):
                 # Add the directory entry itself
                zipf.write(file_path, arcname)
                # Walk through the directory and add all files
                for root, _, files in os.walk(file_path):
                    for file in files:
                        full_sub_path = os.path.join(root, file)
                        sub_arcname = os.path.relpath(full_sub_path, source_folder)
                        zipf.write(full_sub_path, sub_arcname)
            else:
                 zipf.write(file_path, arcname)

            progress_percent = int(((i + 1) / total_files) * 100)
            progress_callback(progress_percent, f"Archiving: {os.path.basename(arcname)}")
    return f"Successfully created: {os.path.basename(archive_path)}"

def create_rar_archive(files_to_archive, archive_path, source_folder, progress_callback, password=""):
    """Creates a .rar archive and reports progress."""
    command = ['rar', 'a', '-r']
    if password:
        command.append(f'-p{password}')
    command.append(str(archive_path))
    command.extend([os.path.relpath(f, source_folder) for f in files_to_archive])
    
    # We need to run the command from the source folder for relative paths to work correctly
    process = subprocess.Popen(command, cwd=source_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Simulate progress as RAR CLI doesn't provide easy real-time feedback
    total_files = len(files_to_archive)
    for i in range(total_files):
        progress_callback(int(((i + 1) / total_files) * 99), f"Processing file {i+1}/{total_files}")
    
    stdout, stderr = process.communicate()
    
    if process.returncode == 0:
        progress_callback(100, "Finalizing archive...")
        return f"Successfully created: {os.path.basename(archive_path)}"
    else:
        raise Exception(f"RAR Error: {stderr.strip()}")

# --- Streamlit UI ---

st.set_page_config(layout="wide", page_title="Modern Archiver")

st.title("📦 Modern Archiver")
st.markdown("Upload a ZIP file, select the contents you want to keep, and re-download it as a new, clean archive.")

# --- Session State Initialization ---
# This is crucial for keeping track of data across reruns
if 'source_dir' not in st.session_state:
    st.session_state.source_dir = None
if 'file_data' not in st.session_state:
    st.session_state.file_data = []
if 'rar_available' not in st.session_state:
    st.session_state.rar_available = shutil.which("rar") is not None

# --- Step 1: File Upload ---
uploaded_file = st.file_uploader(
    "Upload a ZIP file containing the folder you want to archive",
    type="zip"
)

# --- Main Application Logic ---
if uploaded_file is not None:
    # Create a temporary directory for this session if it doesn't exist
    if st.session_state.source_dir is None:
        temp_dir = tempfile.mkdtemp()
        st.session_state.source_dir = Path(temp_dir) / uploaded_file.name.replace('.zip', '')
        
        # Unzip the file
        with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
            zip_ref.extractall(st.session_state.source_dir)
        
        # Gather file data (like in the original app)
        try:
            for item_name in os.listdir(st.session_state.source_dir):
                full_path = os.path.join(st.session_state.source_dir, item_name)
                stat = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                st.session_state.file_data.append({
                    "path": full_path,
                    "name": item_name,
                    "size": stat.st_size,
                    "m_time": datetime.fromtimestamp(stat.st_mtime),
                    "is_dir": is_dir,
                    "included": True # Default to included
                })
        except OSError as e:
            st.error(f"Could not read folder contents. Error: {e}")
            st.stop()

    # --- UI Layout (Two Columns) ---
    col1, col2 = st.columns([2, 1])

    with col2:
        st.subheader("⚙️ Archive Controls")
        
        user_message = st.text_input("User Message (for filename)", placeholder="e.g., ProjectBackup, Photos, etc.")
        password = st.text_input("Archive Password (optional)", type="password", placeholder="Enter password for archive")
        
        rar_disabled = not st.session_state.rar_available
        format_options = ["ZIP", "RAR"]
        archive_format = st.radio(
            "Archive Format", 
            options=format_options, 
            index=0, 
            horizontal=True,
            help="RAR option is disabled if the 'rar' command is not found in the system's PATH."
        )

        if archive_format == "RAR" and rar_disabled:
            st.warning("RAR is not available on this server. Please choose ZIP.")
            st.stop()

        if st.button("🔄 Reload / Clear Session"):
            # Clean up the temp directory
            if st.session_state.source_dir and os.path.exists(Path(st.session_state.source_dir).parent):
                shutil.rmtree(Path(st.session_state.source_dir).parent)
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        start_button = st.button("🚀 Start Archiving", type="primary", use_container_width=True)


    with col1:
        st.subheader("📁 Files to Include")

        # --- Sorting and Selection Controls ---
        sort_col1, sort_col2, sort_col3 = st.columns([2, 1, 1])
        with sort_col1:
            sort_key = st.selectbox(
                "Sort by:",
                ["Name (A-Z)", "Name (Z-A)", "Size (Largest)", "Size (Smallest)", "Date (Newest)", "Date (Oldest)"],
                label_visibility="collapsed"
            )
        with sort_col2:
            if st.button("Select All", use_container_width=True):
                for item in st.session_state.file_data:
                    item["included"] = True
        with sort_col3:
            if st.button("Deselect All", use_container_width=True):
                for item in st.session_state.file_data:
                    item["included"] = False
        
        # --- Sorting Logic ---
        reverse_sort = "Z-A" in sort_key or "Largest" in sort_key or "Newest" in sort_key
        if "Name" in sort_key:
            st.session_state.file_data.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=reverse_sort)
        elif "Size" in sort_key:
            st.session_state.file_data.sort(key=lambda x: (not x["is_dir"], x["size"]), reverse=reverse_sort)
        elif "Date" in sort_key:
            st.session_state.file_data.sort(key=lambda x: (not x["is_dir"], x["m_time"]), reverse=reverse_sort)

        # --- File List Display ---
        st.markdown("---")
        for i, item_data in enumerate(st.session_state.file_data):
            # Create a unique key for each checkbox
            checkbox_key = f"cb_{item_data['path']}"
            
            row = st.container()
            row_cols = row.columns([0.5, 0.5, 3, 1, 2])
            
            with row_cols[0]:
                item_data["included"] = st.checkbox("", value=item_data["included"], key=checkbox_key, label_visibility="collapsed")
            
            with row_cols[1]:
                st.write("📁" if item_data["is_dir"] else "📄")
            
            with row_cols[2]:
                st.markdown(f"**{item_data['name']}**")
            
            with row_cols[3]:
                size_str = format_size(item_data['size']) if not item_data['is_dir'] else "---"
                st.text(size_str)
                
            with row_cols[4]:
                st.text(item_data['m_time'].strftime('%Y-%m-%d %H:%M'))

    # --- Archiving Process ---
    if start_button:
        included_files = [item['path'] for item in st.session_state.file_data if item['included']]
        
        if not included_files:
            st.error("No files selected. Please select at least one file to archive.")
        else:
            with st.spinner("Archiving in progress..."):
                # Prepare paths and names
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                fmt = "rar" if archive_format == "RAR" else "zip"
                clean_user_msg = user_message.strip().replace(" ", "_")
                filename = f"{timestamp}_{clean_user_msg}.{fmt}" if clean_user_msg else f"{timestamp}.{fmt}"
                
                output_dir = Path(tempfile.mkdtemp())
                archive_path = output_dir / filename
                
                status_text = st.empty()
                progress_bar = st.progress(0)
                
                def update_progress(percent, message):
                    progress_bar.progress(percent)
                    status_text.text(message)

                try:
                    if fmt == "zip":
                        result_msg = create_zip_archive(included_files, archive_path, st.session_state.source_dir, update_progress, password)
                    else: # rar
                        result_msg = create_rar_archive(included_files, archive_path, st.session_state.source_dir, update_progress, password)

                    st.success(result_msg)
                    
                    # Provide download button
                    with open(archive_path, "rb") as fp:
                        st.download_button(
                            label="📥 Download Archive",
                            data=fp,
                            file_name=filename,
                            mime=f"application/{'x-rar-compressed' if fmt == 'rar' else 'zip'}",
                            use_container_width=True
                        )
                    
                    # Clean up the output temp dir
                    shutil.rmtree(output_dir)

                except Exception as e:
                    st.error(f"An error occurred: {e}")
