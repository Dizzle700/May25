# YOLO Dataset Creator

A PyQt6-based application for creating, visualizing, and managing datasets for YOLO object detection models.

## Features

- Load and visualize images
- Create and edit bounding box annotations manually
- Use YOLO models to automatically detect objects
- Manage object classes
- Convert between different annotation formats (YOLO, COCO, Pascal VOC)
- Augment datasets to improve model training
- Export datasets in various formats

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Create and activate a virtual environment (recommended):
   ```
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

   Note: For PyTorch with CUDA support, you might need to install a specific version from [pytorch.org](https://pytorch.org/).

## Usage

Run the application with:

```
python main.py
```

### Basic Workflow

1. Add images to the application
2. Define classes for your objects
3. Create bounding boxes manually or use a YOLO model for automatic detection
4. Edit and refine annotations as needed
5. Export the dataset in your desired format

## License

[Specify your license here]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
