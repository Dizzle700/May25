import os
import pathspec
import zipfile
import tarfile
import py7zr # For 7-Zip

def get_gitignore_patterns(source_folder):
    """
    Reads .gitignore from the source_folder and returns a list of patterns.
    Returns an empty list if .gitignore is not found.
    """
    gitignore_path = os.path.join(source_folder, ".gitignore")
    patterns = []
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                patterns = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except Exception as e:
            print(f"Error reading .gitignore: {e}") # Or use a log_callback
    return patterns

def list_files_to_archive(source_folder, log_callback=None):
    """
    Lists all files in source_folder, respecting .gitignore rules.
    Returns a list of tuples: (absolute_path, relative_path_for_archive).
    """
    if log_callback:
        log_callback(f"Scanning files in '{source_folder}'...")

    patterns = get_gitignore_patterns(source_folder)
    spec = pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    
    files_to_archive = []
    
    # Normalize source_folder path to ensure consistent relative paths
    normalized_source_folder = os.path.normpath(source_folder)

    for root, dirs, files in os.walk(normalized_source_folder, topdown=True):
        # Filter directories based on .gitignore (pathspec handles this with directory patterns)
        # pathspec matches paths relative to the directory containing the .gitignore file.
        # For subdirectories, we need their path relative to normalized_source_folder.
        
        # Exclude directories based on .gitignore
        # Note: pathspec works on paths, so for directories, they usually end with /
        # We need to be careful here. A simpler way is to let pathspec check files,
        # and if a directory is ignored (e.g., "build/"), os.walk won't even go into
        # the files of an explicitly excluded directory if we modify `dirs` list.
        # However, pathspec handles file paths directly well.

        # For files:
        for file_name in files:
            absolute_path = os.path.join(root, file_name)
            # Get path relative to the source_folder (where .gitignore is)
            relative_path = os.path.relpath(absolute_path, normalized_source_folder)
            # pathspec needs paths with OS-specific separators for matching,
            # but for archive paths, forward slashes are standard.
            # Let's use OS-specific for matching, and then normalize for archive name.
            
            # Normalize to forward slashes for pathspec, as gitignore patterns typically use them
            match_path = relative_path.replace(os.sep, '/')

            if not spec.match_file(match_path):
                # For arcname, it's good practice to use forward slashes
                arcname = relative_path.replace(os.sep, '/')
                files_to_archive.append((absolute_path, arcname))
            #else:
            #    if log_callback: log_callback(f"Ignoring: {relative_path}", level="DEBUG")

    if log_callback:
        log_callback(f"Scan complete. Found {len(files_to_archive)} file(s) to archive.")
    return files_to_archive


def create_archive(archive_full_path, archive_type, files_to_archive_with_rel_paths, progress_callback=None, log_callback=None):
    """
    Creates an archive of the specified type.
    files_to_archive_with_rel_paths: list of (absolute_path, relative_path_in_archive)
    progress_callback(current_file_index, total_files)
    log_callback(message, level)
    """
    total_files = len(files_to_archive_with_rel_paths)
    if total_files == 0:
        if log_callback:
            log_callback("No files to archive.", level="WARNING")
        return True # Or False, depending on how you want to treat "empty" success

    if log_callback:
        log_callback(f"Creating {archive_type} archive: {archive_full_path}", level="INFO")
        log_callback(f"Archiving {total_files} file(s)...", level="INFO")

    try:
        if archive_type == "ZIP":
            with zipfile.ZipFile(archive_full_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, (abs_path, arcname) in enumerate(files_to_archive_with_rel_paths):
                    zf.write(abs_path, arcname)
                    if progress_callback:
                        progress_callback(i + 1, total_files)
        
        elif archive_type == "TAR.GZ":
            with tarfile.open(archive_full_path, "w:gz") as tf:
                for i, (abs_path, arcname) in enumerate(files_to_archive_with_rel_paths):
                    tf.add(abs_path, arcname=arcname)
                    if progress_callback:
                        progress_callback(i + 1, total_files)
        
        elif archive_type == "7Z":
            # py7zr needs the destination directory to exist
            os.makedirs(os.path.dirname(archive_full_path), exist_ok=True)
            with py7zr.SevenZipFile(archive_full_path, 'w') as szf:
                for i, (abs_path, arcname) in enumerate(files_to_archive_with_rel_paths):
                    szf.write(abs_path, arcname)
                    if progress_callback:
                        progress_callback(i + 1, total_files)
        else:
            if log_callback:
                log_callback(f"Unsupported archive type: {archive_type}", level="ERROR")
            return False
            
        if log_callback:
            log_callback(f"Archive created successfully: {archive_full_path}", level="SUCCESS")
        return True

    except Exception as e:
        if log_callback:
            log_callback(f"Error creating archive: {e}", level="ERROR")
        return False