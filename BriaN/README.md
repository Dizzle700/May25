# Smart Background Remover & Compositor

A desktop application to automatically remove backgrounds from images using AI and then composite them onto a new background with various layout options.

## Features

*   Batch background removal for multiple images.
*   AI-powered background removal using `briaai/RMBG-2.0`.
*   Selection of output formats (PNG, WebP).
*   CPU/GPU processing support.
*   Image compositing module:
    *   Select a background image.
    *   Drag and drop processed (transparent) images onto the background.
    *   Freeform placement.
    *   Grid-based placement (e.g., 2x2, 2x3).
    *   Save the final composite image.
*   Modern Material Dark theme.

## Setup

1.  **Clone the repository (or create the project files):**
    ```bash
    # If you have a git repo:
    # git clone <repository-url>
    # cd smart_background_compositor_flat
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    # On Windows
    source venv/Scripts/activate
    # On macOS/Linux
    # source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Note: `torch` installation can be tricky. You might need to install it separately according to your system and CUDA version from [pytorch.org](https://pytorch.org/get-started/locally/).*

4.  **Download or create icons:**
    Place your UI icons (e.g., `start_icon.png`, `folder_icon.png`) into the `assets/icons/` directory.

## Running the Application

```bash
python main.py