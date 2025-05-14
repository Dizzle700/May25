Okay, here is a detailed plan and specification document in Markdown format for the Python PyQt6 looped clicker application with human-like mouse movements.

```markdown
# Design Document: PyQt6 Looped Auto-Clicker

**Version:** 1.0
**Date:** 2025-04-09
**Author:** Gemini AI

## 1. Introduction & Overview

This document outlines the design for a Python-based desktop application using the PyQt6 framework. The application serves as an automated mouse clicker that operates in loops. It features two primary modes: capturing specific screen coordinates and repeatedly clicking on one of the captured coordinates chosen randomly. A key feature is the simulation of human-like mouse movements, incorporating random delays, variable speeds, and path deviations ("shaking") when moving the cursor to the target coordinate before clicking. The application will provide a modern, dark-themed graphical user interface (GUI) with standard controls (Start, Stop, Pause) and allow users to assign keyboard hotkeys for core actions.

## 2. Goals

* Develop a user-friendly GUI application using Python and PyQt6.
* Implement a reliable method for capturing absolute screen coordinates via mouse clicks.
* Store a list of captured coordinates persistently.
* Implement a "Click Mode" that loops indefinitely (until stopped).
* In each loop iteration of Click Mode, randomly select one coordinate from the captured list.
* Simulate human-like mouse movement to the selected coordinate before clicking:
    * Introduce random delays before initiating movement.
    * Vary the speed of mouse movement.
    * Introduce minor random deviations ("shaking" or curved paths) during movement.
    * Introduce random delays between consecutive clicks in the loop.
* Provide GUI buttons for Start, Stop, and Pause functionality for the clicking loop.
* Allow users to assign global keyboard hotkeys for:
    * Starting the click loop.
    * Stopping the click loop.
    * Pausing/Resuming the click loop.
    * Capturing the current mouse cursor position.
* Implement a visually appealing dark theme for the GUI.
* Ensure the GUI remains responsive during background clicking operations.
* Provide clear visual feedback to the user about the application's current state (Idle, Capturing, Running, Paused).

## 3. Non-Goals

* Advanced anti-detection mechanisms beyond basic human simulation (e.g., simulating browser fingerprints, complex behavioral patterns).
* Support for clicking relative to specific application windows (coordinates will be absolute screen positions).
* Complex scripting or sequencing of clicks beyond random selection.
* Support for multiple monitors with significantly different resolutions/scaling (initial version targets primary monitor simplicity).
* Keystroke automation.
* Saving/Loading multiple different lists of coordinates (v1.0 will have one list).

## 4. Target Audience

* Users performing repetitive clicking tasks in games or applications.
* Testers needing simple click automation.
* Users requiring basic automation without complex scripting needs.

## 5. High-Level Architecture

The application will consist of three main components:

1.  **GUI Layer (PyQt6):** Handles user interaction, displays information (coordinates, status), triggers actions, and manages the main event loop.
2.  **Core Logic Layer (Python):** Manages application state (Idle, Capturing, Running, Paused), stores coordinates, controls the clicking loop, and interfaces with the Input Simulation Layer. This layer will run the clicking loop in a separate thread (`QThread`) to prevent GUI freezes.
3.  **Input Simulation & Hooking Layer (Python Libraries):** Handles low-level mouse movement, clicking simulation (e.g., using `pynput` or `pyautogui`), and global keyboard/mouse event listening for coordinate capture and hotkeys (e.g., using `pynput`).

```
+---------------------+      +---------------------+      +--------------------------+
|   GUI Layer         |<---->| Core Logic Layer    |<---->| Input Simulation &       |
|   (PyQt6)           |      | (Python, QThread)   |      | Hooking Layer            |
|   - Main Window     |      | - State Machine     |      | (pynput/pyautogui)       |
|   - Buttons         |      | - Coordinate List   |      | - Mouse Move/Click       |
|   - Coordinate View |      | - Click Loop        |      | - Global Key/Mouse Listen|
|   - Status Display  |      | - Human Simulation  |      |                          |
|   - Hotkey Config   |      | - Persistence       |      |                          |
+---------------------+      +---------------------+      +--------------------------+
        | Signals/Slots                | Calls                        | OS Events
        +------------------------------+------------------------------+
```

## 6. Detailed Design

### 6.1. GUI (PyQt6)

* **Main Window:** `QMainWindow` or `QWidget` as the base.
* **Layout:** Use `QVBoxLayout` and `QHBoxLayout` for structure.
* **Theme:** Implement a dark theme using Qt Style Sheets (QSS). Consider using a library like `qt-material` or `QDarkStylesheet` for a pre-built modern look, or create custom QSS.
* **Widgets:**
    * `QPushButton` ("Start", "Stop", "Pause/Resume"): Control the clicking loop. Pause button toggles between Pause/Resume text.
    * `QPushButton` ("Enter Capture Mode" / "Exit Capture Mode"): Toggles the coordinate capture state.
    * `QListWidget`: Displays the captured (X, Y) coordinates. Allow selection and deletion of coordinates.
    * `QLabel` ("Status Label"): Displays the current application state (e.g., "Idle", "Capturing: Click to add point", "Running", "Paused", "Stopped").
    * `QLabel` / `QLineEdit` (Read-only): Display the currently assigned hotkeys.
    * `QPushButton` ("Configure Hotkeys"): Opens a separate dialog or section to set hotkeys.
* **Hotkey Configuration:**
    * A dedicated `QDialog` or section in the main window.
    * Labels for each action (Start, Stop, Pause, Capture).
    * Input fields or buttons that capture the next key press to assign it as the hotkey for the corresponding action. Display the assigned key (e.g., "Ctrl+Alt+S").
    * Save/Cancel buttons for the configuration.
* **Responsiveness:** The click loop MUST run in a separate `QThread`. Signals and slots will be used for communication between the worker thread and the GUI thread (e.g., updating status, reporting errors).

### 6.2. Core Logic

* **State Machine:** Manage the application's state:
    * `IDLE`: Application is waiting for user input.
    * `CAPTURING`: Waiting for a mouse click anywhere on the screen to record coordinates. The global mouse listener is active.
    * `RUNNING`: The clicking loop is active in the background thread.
    * `PAUSED`: The clicking loop thread is sleeping but can be resumed.
    * `STOPPED`: Explicitly stopped by the user (essentially returns to `IDLE`).
* **Coordinate Storage:** A Python `list` of tuples `[(x1, y1), (x2, y2), ...]`.
* **Clicking Loop (`QThread`):**
    1.  Check state (if not `RUNNING`, exit or pause).
    2.  If `RUNNING`:
        a.  Select a random coordinate `(target_x, target_y)` from the stored list. If the list is empty, stop and report an error/warning.
        b.  Get current mouse position `(start_x, start_y)`.
        c.  Call the Human Simulation module to move the mouse from `(start_x, start_y)` to `(target_x, target_y)`.
        d.  Perform a mouse click at `(target_x, target_y)`.
        e.  Wait for a random delay (within a configurable range).
        f.  Repeat.
* **Pause/Resume Logic:** Use a flag or `threading.Event` within the worker thread. When paused, the loop waits on the event. Resuming sets the event.
* **Stop Logic:** Set a flag that the worker thread checks on each iteration. When set, the thread cleans up and exits its loop.
* **Persistence:**
    * Use JSON or `configparser` to save/load:
        * The list of captured coordinates.
        * Hotkey assignments.
    * Save location: User's standard application data directory (use `QStandardPaths` from PyQt6 to find appropriate locations like `%APPDATA%` or `~/.config`).
    * Load settings/coordinates on application startup.
    * Save settings/coordinates on modification (e.g., adding/deleting coordinate, changing hotkeys) or on application exit.

### 6.3. Input Simulation & Hooking Layer

* **Library Choice:** `pynput` is recommended as it provides robust cross-platform support for both input simulation (mouse move, click) and global input monitoring (keyboard/mouse listeners). `pyautogui` is an alternative, primarily for simulation, potentially simpler for basic movement but less feature-rich for hooks.
* **Global Listeners (`pynput`):**
    * Run listeners in separate, non-daemon threads managed carefully to allow clean shutdown.
    * *Keyboard Listener:* Detects when registered hotkeys are pressed. When detected, emit a PyQt signal or use a thread-safe queue to notify the Core Logic/GUI layer to change state (Start, Stop, Pause).
    * *Mouse Listener:* Active only when in `CAPTURING` state. On mouse click, capture `event.x`, `event.y`, notify the Core Logic to add the coordinate, and potentially switch back to `IDLE` state (or allow multiple captures).
* **Mouse Control (`pynput.mouse.Controller`):**
    * `mouse.position = (x, y)`: Sets the mouse position.
    * `mouse.click(Button.left, 1)`: Performs a left click.

### 6.4. Human Simulation Module

This is crucial for the desired behavior. It will be a function or class called by the Core Logic's clicking loop.

* **Input:** Start coordinates `(sx, sy)`, End coordinates `(ex, ey)`. Optional: Configuration parameters (min/max delay, speed range, "shakiness" factor).
* **Output:** Moves the mouse cursor from start to end, simulating human behavior.
* **Steps:**
    1.  **Initial Delay:** Wait for a random duration (`random.uniform(min_delay, max_delay)`).
    2.  **Path Calculation:**
        * Calculate the vector from start to end.
        * Determine the total distance.
        * Decide on a variable duration for the movement based on distance and a random speed factor (`random.uniform(min_speed_factor, max_speed_factor)`). Ensure minimum/maximum movement times to feel natural.
        * **Path Interpolation:** Instead of moving directly, break the path into multiple smaller steps (e.g., 10-50 steps).
        * **Deviation/Shaking:** For each intermediate point on the path, add a small, random offset perpendicular to the direction of travel. The magnitude of the offset can decrease as the cursor nears the target. Bezier curves can also be used for smoother, more natural curves: define control points randomly offset from the direct line.
        * **Variable Speed:** Don't make the time between steps constant. Use an easing function (e.g., quadratic ease-in-out) so the mouse starts slower, accelerates, and then decelerates as it approaches the target. Calculate the time delay for each small step accordingly.
    3.  **Movement Execution:** Loop through the calculated intermediate points:
        * Move the mouse cursor to the next point (`mouse.position = ...`).
        * Wait for the calculated small delay for that step (`time.sleep(...)`). Using `time.sleep` frequently with small values is acceptable here for simulation fidelity, as it's in a background thread.
    4.  **Final Adjustment:** Ensure the mouse lands *exactly* on `(ex, ey)`.

### 6.5. Configuration Parameters (Optional but Recommended)

Expose these settings in the GUI (perhaps in the Hotkey config dialog or a separate "Settings" dialog):

* Min/Max delay before move (seconds).
* Min/Max delay between clicks (seconds).
* Min/Max movement speed factor (abstract unit, affects duration).
* "Shakiness" factor (magnitude of random path deviation).

## 7. User Interface (UI) Mockup/Description

```
+------------------------------------------------------+
| Looped Auto-Clicker v1.0                             | Window Title
+------------------------------------------------------+
| [ Status: Idle ]                                     | Status Label
+------------------------------------------------------+
| Coordinates:                                         |
| +--------------------------------------------------+ |
| | (123, 456)                                       | | QListWidget
| | (789, 101)                                       | |
| | (345, 678)                                       | |
| | ...                                              | |
| +--------------------------------------------------+ |
| [ Delete Selected Coord ]                            | Button
+------------------------------------------------------+
| Controls:                                            |
| [ Start (Hotkey: None) ] [ Stop (Hotkey: None) ]     | Buttons + Hotkey display
| [ Pause (Hotkey: None) ]                             |
+------------------------------------------------------+
| Capture:                                             |
| [ Enter Capture Mode (Hotkey: None) ]                | Button + Hotkey display
+------------------------------------------------------+
| [ Configure Hotkeys & Settings ]                     | Button
+------------------------------------------------------+
```

* The "Status" label updates dynamically.
* When "Enter Capture Mode" is clicked, the button text might change to "Exit Capture Mode" / "Click to Capture", and the Status label updates. Clicking anywhere adds coords to the list.
* Start/Stop/Pause buttons enable/disable appropriately based on the state.
* Hotkey display next to buttons updates when configured.

## 8. Key Features Breakdown

* **Coordinate Capture:** Global mouse hook active in Capture Mode. Records absolute X, Y on click.
* **Coordinate Management:** List display, ability to delete entries.
* **Clicking Loop:** Runs in `QThread`. Randomly selects coordinate. Calls human simulation module. Performs click. Waits random delay. Repeats.
* **Human Simulation:** Core module implementing delays, variable speed paths with deviations (Bezier curves or interpolated offsets).
* **State Control:** Start/Stop/Pause buttons and corresponding hotkeys manage the `QThread` loop via flags/events.
* **Hotkey System:** Global keyboard listener (`pynput`) maps key combinations to actions (Start/Stop/Pause/Capture). Configuration UI allows user assignment.
* **Dark Theme:** Achieved via PyQt6's QSS styling.
* **Persistence:** Settings (hotkeys) and coordinates saved to a configuration file (JSON).

## 9. Technology Stack

* **Language:** Python 3.x (latest stable recommended)
* **GUI Framework:** PyQt6
* **Input Simulation/Hooking:** pynput (recommended) or alternatives like pyautogui (for simulation)
* **Human Simulation Helpers (Optional):** NumPy (for vector math, Bezier curves), `scipy.interpolate` (potentially)
* **Standard Libraries:** `json`, `random`, `time`, `threading`, `os`, `sys`
* **Packaging (Optional):** PyInstaller or cx_Freeze to create distributable executables.

## 10. Future Enhancements / Suggestions (Post V1.0)

* **Multiple Coordinate Lists:** Allow saving/loading named lists of coordinates for different tasks.
* **Visual Feedback:** Draw a temporary overlay or marker on the screen showing where the next click will target or where captures occurred.
* **Advanced Human Simulation:**
    * More sophisticated Bezier curve generation.
    * Simulate occasional small pauses *during* movement.
    * Introduce slight inaccuracies – sometimes slightly miss the exact target coordinate before clicking.
    * Vary click duration (press/release time).
* **Configuration Profiles:** Save different sets of simulation parameters (delays, speed, shakiness) along with coordinate lists.
* **Click Types:** Allow configuration of right-clicks, double-clicks.
* **Relative Coordinates:** Option to capture coordinates relative to a specific window's position.
* **Error Handling & Logging:** More robust error reporting to the user and potentially a log file.
* **UI Enhancements:** Drag-and-drop reordering of coordinates in the list. Inline editing of coordinates.

## 11. Potential Challenges

* **Permissions:** Global input hooks (`pynput` listeners) often require specific OS permissions (e.g., Accessibility on macOS, potentially admin rights on Windows depending on what windows are being interacted with). Clear instructions for the user might be needed.
* **Cross-Platform Compatibility:** Ensuring `pynput` and mouse/keyboard control works reliably and consistently across Windows, macOS, and Linux. Wayland on Linux can be particularly challenging for global hooks and coordinate systems.
* **GUI Responsiveness:** Ensuring the background thread and input listeners do not block or interfere with the PyQt event loop. Correct use of `QThread`, signals/slots, and potentially thread-safe queues is essential.
* **Human Simulation Realism:** Making the mouse movement *truly* indistinguishable from a human is complex and subjective. The proposed approach provides a good approximation.
* **Resource Usage:** Continuous background listening and processing might consume noticeable CPU, especially the input listeners. Optimize where possible.
* **Detection by Anti-Cheat/Bot Systems:** While simulating human behavior helps, sophisticated detection systems might still flag the application based on driver interactions, process signatures, or statistical analysis of input patterns. This application is *not* guaranteed to be undetectable.

## 12. Disclaimer

This application automates user input. Use it responsibly and ethically. Misuse in online games or other systems may violate their Terms of Service and could lead to account suspension. The developers assume no responsibility for misuse.
```