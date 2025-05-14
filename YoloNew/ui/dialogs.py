from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTabWidget,
                             QCheckBox, QSlider, QGroupBox,
                             QSpinBox, QDoubleSpinBox, QFormLayout,
                             QComboBox, QDialogButtonBox, QWidget)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal

class AugmentationSettingsDialog(QDialog):
    """Dialog for configuring augmentation settings."""
    
    # Signal to emit when settings change
    settings_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Augmentation Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(500)
        
        # Initialize default settings
        self.settings = {
            "geometric": {
                "enabled": True,
                "probability": 0.5,
                "hflip_prob": 0.5,
                "vflip_prob": 0.5,
                "rotate_prob": 0.3,
                "rotate_limit": 30,
                "shift_scale_rotate_prob": 0.3,
                "elastic_transform_prob": 0.1,
                "grid_distortion_prob": 0.1,
                "optical_distortion_prob": 0.1
            },
            "color": {
                "enabled": True,
                "probability": 0.5,
                "brightness_contrast_prob": 0.5,
                "hue_saturation_prob": 0.3,
                "rgb_shift_prob": 0.3,
                "clahe_prob": 0.3,
                "channel_shuffle_prob": 0.1,
                "gamma_prob": 0.3
            },
            "weather": {
                "enabled": True,
                "probability": 0.3,
                "fog_prob": 0.3,
                "rain_prob": 0.2,
                "sunflare_prob": 0.1,
                "shadow_prob": 0.2
            },
            "noise": {
                "enabled": True,
                "probability": 0.3,
                "gaussian_noise_prob": 0.3,
                "iso_noise_prob": 0.3,
                "jpeg_compression_prob": 0.3,
                "posterize_prob": 0.2,
                "equalize_prob": 0.2
            },
            "blur": {
                "enabled": True,
                "probability": 0.3,
                "blur_prob": 0.3,
                "gaussian_blur_prob": 0.3,
                "motion_blur_prob": 0.2,
                "median_blur_prob": 0.2,
                "glass_blur_prob": 0.1
            }
        }
        
        self._create_ui()
        self._load_settings()
        
    def _create_ui(self):
        """Create the dialog UI."""
        # Main layout
        main_layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Create tabs for different transform categories
        self._create_geometric_tab()
        self._create_color_tab()
        self._create_weather_tab()
        self._create_noise_tab()
        self._create_blur_tab()
        
        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                     QDialogButtonBox.StandardButton.Cancel |
                                     QDialogButtonBox.StandardButton.Apply |
                                     QDialogButtonBox.StandardButton.Reset)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply_settings)
        button_box.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset_settings)
        
        main_layout.addWidget(button_box)
        
    def _create_geometric_tab(self):
        """Create the geometric transforms tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable checkbox
        self.geometric_enabled = QCheckBox("Enable Geometric Transforms")
        layout.addWidget(self.geometric_enabled)
        
        # Probability slider
        prob_layout = QHBoxLayout()
        prob_layout.addWidget(QLabel("Overall Probability:"))
        self.geometric_prob = QDoubleSpinBox()
        self.geometric_prob.setRange(0.0, 1.0)
        self.geometric_prob.setSingleStep(0.1)
        self.geometric_prob.setDecimals(1)
        prob_layout.addWidget(self.geometric_prob)
        layout.addLayout(prob_layout)
        
        # Group box for individual transforms
        group_box = QGroupBox("Individual Transforms")
        form_layout = QFormLayout(group_box)
        
        # Horizontal Flip
        self.hflip_prob = QDoubleSpinBox()
        self.hflip_prob.setRange(0.0, 1.0)
        self.hflip_prob.setSingleStep(0.1)
        self.hflip_prob.setDecimals(1)
        form_layout.addRow("Horizontal Flip Probability:", self.hflip_prob)
        
        # Vertical Flip
        self.vflip_prob = QDoubleSpinBox()
        self.vflip_prob.setRange(0.0, 1.0)
        self.vflip_prob.setSingleStep(0.1)
        self.vflip_prob.setDecimals(1)
        form_layout.addRow("Vertical Flip Probability:", self.vflip_prob)
        
        # Rotate
        self.rotate_prob = QDoubleSpinBox()
        self.rotate_prob.setRange(0.0, 1.0)
        self.rotate_prob.setSingleStep(0.1)
        self.rotate_prob.setDecimals(1)
        form_layout.addRow("Rotation Probability:", self.rotate_prob)
        
        self.rotate_limit = QSpinBox()
        self.rotate_limit.setRange(1, 180)
        self.rotate_limit.setSingleStep(5)
        form_layout.addRow("Rotation Limit (degrees):", self.rotate_limit)
        
        # ShiftScaleRotate
        self.shift_scale_rotate_prob = QDoubleSpinBox()
        self.shift_scale_rotate_prob.setRange(0.0, 1.0)
        self.shift_scale_rotate_prob.setSingleStep(0.1)
        self.shift_scale_rotate_prob.setDecimals(1)
        form_layout.addRow("Shift/Scale/Rotate Probability:", self.shift_scale_rotate_prob)
        
        # Add more transform controls as needed
        layout.addWidget(group_box)
        layout.addStretch(1)
        
        self.tab_widget.addTab(tab, "Geometric")
        
    def _create_color_tab(self):
        """Create the color transforms tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable checkbox
        self.color_enabled = QCheckBox("Enable Color Transforms")
        layout.addWidget(self.color_enabled)
        
        # Probability slider
        prob_layout = QHBoxLayout()
        prob_layout.addWidget(QLabel("Overall Probability:"))
        self.color_prob = QDoubleSpinBox()
        self.color_prob.setRange(0.0, 1.0)
        self.color_prob.setSingleStep(0.1)
        self.color_prob.setDecimals(1)
        prob_layout.addWidget(self.color_prob)
        layout.addLayout(prob_layout)
        
        # Group box for individual transforms
        group_box = QGroupBox("Individual Transforms")
        form_layout = QFormLayout(group_box)
        
        # Brightness & Contrast
        self.brightness_contrast_prob = QDoubleSpinBox()
        self.brightness_contrast_prob.setRange(0.0, 1.0)
        self.brightness_contrast_prob.setSingleStep(0.1)
        self.brightness_contrast_prob.setDecimals(1)
        form_layout.addRow("Brightness/Contrast Probability:", self.brightness_contrast_prob)
        
        # Hue, Saturation, Value
        self.hue_saturation_prob = QDoubleSpinBox()
        self.hue_saturation_prob.setRange(0.0, 1.0)
        self.hue_saturation_prob.setSingleStep(0.1)
        self.hue_saturation_prob.setDecimals(1)
        form_layout.addRow("Hue/Saturation Probability:", self.hue_saturation_prob)
        
        # RGB Shift
        self.rgb_shift_prob = QDoubleSpinBox()
        self.rgb_shift_prob.setRange(0.0, 1.0)
        self.rgb_shift_prob.setSingleStep(0.1)
        self.rgb_shift_prob.setDecimals(1)
        form_layout.addRow("RGB Shift Probability:", self.rgb_shift_prob)
        
        # Add more transform controls as needed
        layout.addWidget(group_box)
        layout.addStretch(1)
        
        self.tab_widget.addTab(tab, "Color")
    
    def _create_weather_tab(self):
        """Create the weather transforms tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable checkbox
        self.weather_enabled = QCheckBox("Enable Weather Transforms")
        layout.addWidget(self.weather_enabled)
        
        # Probability slider
        prob_layout = QHBoxLayout()
        prob_layout.addWidget(QLabel("Overall Probability:"))
        self.weather_prob = QDoubleSpinBox()
        self.weather_prob.setRange(0.0, 1.0)
        self.weather_prob.setSingleStep(0.1)
        self.weather_prob.setDecimals(1)
        prob_layout.addWidget(self.weather_prob)
        layout.addLayout(prob_layout)
        
        # Group box for individual transforms
        group_box = QGroupBox("Individual Transforms")
        form_layout = QFormLayout(group_box)
        
        # Fog
        self.fog_prob = QDoubleSpinBox()
        self.fog_prob.setRange(0.0, 1.0)
        self.fog_prob.setSingleStep(0.1)
        self.fog_prob.setDecimals(1)
        form_layout.addRow("Fog Probability:", self.fog_prob)
        
        # Rain
        self.rain_prob = QDoubleSpinBox()
        self.rain_prob.setRange(0.0, 1.0)
        self.rain_prob.setSingleStep(0.1)
        self.rain_prob.setDecimals(1)
        form_layout.addRow("Rain Probability:", self.rain_prob)
        
        # Add more transform controls as needed
        layout.addWidget(group_box)
        layout.addStretch(1)
        
        self.tab_widget.addTab(tab, "Weather")
    
    def _create_noise_tab(self):
        """Create the noise transforms tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable checkbox
        self.noise_enabled = QCheckBox("Enable Noise Transforms")
        layout.addWidget(self.noise_enabled)
        
        # Probability slider
        prob_layout = QHBoxLayout()
        prob_layout.addWidget(QLabel("Overall Probability:"))
        self.noise_prob = QDoubleSpinBox()
        self.noise_prob.setRange(0.0, 1.0)
        self.noise_prob.setSingleStep(0.1)
        self.noise_prob.setDecimals(1)
        prob_layout.addWidget(self.noise_prob)
        layout.addLayout(prob_layout)
        
        # Group box for individual transforms
        group_box = QGroupBox("Individual Transforms")
        form_layout = QFormLayout(group_box)
        
        # Gaussian Noise
        self.gaussian_noise_prob = QDoubleSpinBox()
        self.gaussian_noise_prob.setRange(0.0, 1.0)
        self.gaussian_noise_prob.setSingleStep(0.1)
        self.gaussian_noise_prob.setDecimals(1)
        form_layout.addRow("Gaussian Noise Probability:", self.gaussian_noise_prob)
        
        # Add more transform controls as needed
        layout.addWidget(group_box)
        layout.addStretch(1)
        
        self.tab_widget.addTab(tab, "Noise")
    
    def _create_blur_tab(self):
        """Create the blur transforms tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable checkbox
        self.blur_enabled = QCheckBox("Enable Blur Transforms")
        layout.addWidget(self.blur_enabled)
        
        # Probability slider
        prob_layout = QHBoxLayout()
        prob_layout.addWidget(QLabel("Overall Probability:"))
        self.blur_prob = QDoubleSpinBox()
        self.blur_prob.setRange(0.0, 1.0)
        self.blur_prob.setSingleStep(0.1)
        self.blur_prob.setDecimals(1)
        prob_layout.addWidget(self.blur_prob)
        layout.addLayout(prob_layout)
        
        # Group box for individual transforms
        group_box = QGroupBox("Individual Transforms")
        form_layout = QFormLayout(group_box)
        
        # Blur
        self.blur_effect_prob = QDoubleSpinBox()
        self.blur_effect_prob.setRange(0.0, 1.0)
        self.blur_effect_prob.setSingleStep(0.1)
        self.blur_effect_prob.setDecimals(1)
        form_layout.addRow("Blur Probability:", self.blur_effect_prob)
        
        # Add more transform controls as needed
        layout.addWidget(group_box)
        layout.addStretch(1)
        
        self.tab_widget.addTab(tab, "Blur")
    
    def _load_settings(self):
        """Load settings into UI controls."""
        # Geometric
        self.geometric_enabled.setChecked(self.settings["geometric"]["enabled"])
        self.geometric_prob.setValue(self.settings["geometric"]["probability"])
        self.hflip_prob.setValue(self.settings["geometric"]["hflip_prob"])
        self.vflip_prob.setValue(self.settings["geometric"]["vflip_prob"])
        self.rotate_prob.setValue(self.settings["geometric"]["rotate_prob"])
        self.rotate_limit.setValue(self.settings["geometric"]["rotate_limit"])
        self.shift_scale_rotate_prob.setValue(self.settings["geometric"]["shift_scale_rotate_prob"])
        
        # Color
        self.color_enabled.setChecked(self.settings["color"]["enabled"])
        self.color_prob.setValue(self.settings["color"]["probability"])
        self.brightness_contrast_prob.setValue(self.settings["color"]["brightness_contrast_prob"])
        self.hue_saturation_prob.setValue(self.settings["color"]["hue_saturation_prob"])
        self.rgb_shift_prob.setValue(self.settings["color"]["rgb_shift_prob"])
        
        # Weather
        self.weather_enabled.setChecked(self.settings["weather"]["enabled"])
        self.weather_prob.setValue(self.settings["weather"]["probability"])
        self.fog_prob.setValue(self.settings["weather"]["fog_prob"])
        self.rain_prob.setValue(self.settings["weather"]["rain_prob"])
        
        # Noise
        self.noise_enabled.setChecked(self.settings["noise"]["enabled"])
        self.noise_prob.setValue(self.settings["noise"]["probability"])
        self.gaussian_noise_prob.setValue(self.settings["noise"]["gaussian_noise_prob"])
        
        # Blur
        self.blur_enabled.setChecked(self.settings["blur"]["enabled"])
        self.blur_prob.setValue(self.settings["blur"]["probability"])
        self.blur_effect_prob.setValue(self.settings["blur"]["blur_prob"])
        
    def _save_settings(self):
        """Save UI control values to settings."""
        # Geometric
        self.settings["geometric"]["enabled"] = self.geometric_enabled.isChecked()
        self.settings["geometric"]["probability"] = self.geometric_prob.value()
        self.settings["geometric"]["hflip_prob"] = self.hflip_prob.value()
        self.settings["geometric"]["vflip_prob"] = self.vflip_prob.value()
        self.settings["geometric"]["rotate_prob"] = self.rotate_prob.value()
        self.settings["geometric"]["rotate_limit"] = self.rotate_limit.value()
        self.settings["geometric"]["shift_scale_rotate_prob"] = self.shift_scale_rotate_prob.value()
        
        # Color
        self.settings["color"]["enabled"] = self.color_enabled.isChecked()
        self.settings["color"]["probability"] = self.color_prob.value()
        self.settings["color"]["brightness_contrast_prob"] = self.brightness_contrast_prob.value()
        self.settings["color"]["hue_saturation_prob"] = self.hue_saturation_prob.value()
        self.settings["color"]["rgb_shift_prob"] = self.rgb_shift_prob.value()
        
        # Weather
        self.settings["weather"]["enabled"] = self.weather_enabled.isChecked()
        self.settings["weather"]["probability"] = self.weather_prob.value()
        self.settings["weather"]["fog_prob"] = self.fog_prob.value()
        self.settings["weather"]["rain_prob"] = self.rain_prob.value()
        
        # Noise
        self.settings["noise"]["enabled"] = self.noise_enabled.isChecked()
        self.settings["noise"]["probability"] = self.noise_prob.value()
        self.settings["noise"]["gaussian_noise_prob"] = self.gaussian_noise_prob.value()
        
        # Blur
        self.settings["blur"]["enabled"] = self.blur_enabled.isChecked()
        self.settings["blur"]["probability"] = self.blur_prob.value()
        self.settings["blur"]["blur_prob"] = self.blur_effect_prob.value()
        
    def _apply_settings(self):
        """Apply the current settings."""
        self._save_settings()
        self.settings_changed.emit(self.settings)
        
    def _reset_settings(self):
        """Reset settings to defaults."""
        # Reset to default values
        self.settings = {
            "geometric": {
                "enabled": True,
                "probability": 0.5,
                "hflip_prob": 0.5,
                "vflip_prob": 0.5,
                "rotate_prob": 0.3,
                "rotate_limit": 30,
                "shift_scale_rotate_prob": 0.3,
                "elastic_transform_prob": 0.1,
                "grid_distortion_prob": 0.1,
                "optical_distortion_prob": 0.1
            },
            "color": {
                "enabled": True,
                "probability": 0.5,
                "brightness_contrast_prob": 0.5,
                "hue_saturation_prob": 0.3,
                "rgb_shift_prob": 0.3,
                "clahe_prob": 0.3,
                "channel_shuffle_prob": 0.1,
                "gamma_prob": 0.3
            },
            "weather": {
                "enabled": True,
                "probability": 0.3,
                "fog_prob": 0.3,
                "rain_prob": 0.2,
                "sunflare_prob": 0.1,
                "shadow_prob": 0.2
            },
            "noise": {
                "enabled": True,
                "probability": 0.3,
                "gaussian_noise_prob": 0.3,
                "iso_noise_prob": 0.3,
                "jpeg_compression_prob": 0.3,
                "posterize_prob": 0.2,
                "equalize_prob": 0.2
            },
            "blur": {
                "enabled": True,
                "probability": 0.3,
                "blur_prob": 0.3,
                "gaussian_blur_prob": 0.3,
                "motion_blur_prob": 0.2,
                "median_blur_prob": 0.2,
                "glass_blur_prob": 0.1
            }
        }
        
        # Load the reset settings into UI
        self._load_settings()
        
    def get_settings(self):
        """Get the current settings."""
        self._save_settings()
        return self.settings
        
    def accept(self):
        """Handle dialog acceptance."""
        self._apply_settings()
        super().accept()
