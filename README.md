# ADB WMS Controller

ADB WMS Controller is a desktop automation tool built with **Python** and **Tkinter** that uses **ADB (Android Debug Bridge)** to control Android devices and automate repetitive operations in warehouse systems.

---

## Features

- Detect USB connected Android devices
- Execute ADB commands automatically
- Simulate text input and screen tap actions
- Tkinter graphical user interface
- Task log monitoring

---

## Requirements

Before running the program, install:

- Python 3.9+
- Android **ADB platform-tools**
- **ADB Keyboard (required for text input)**

Download ADB platform tools:

https://developer.android.com/tools/releases/platform-tools

Download ADB Keyboard:

https://github.com/senzhk/ADBKeyBoard

---

## Enable USB Debugging

On your Android device:

1. Open **Settings**
2. Go to **Developer Options**
3. Enable **USB Debugging**
4. Connect device to computer
5. Allow debugging authorization

## How to Run

1. Open **walmurt.py** in VS Code.
2. Click the **Run** button (the triangle icon) in the upper-right corner.
3. The program UI will appear.
4. Enter your **account** and **password**.
5. Select the **device number** from the left.
5. Set the **loop limit** if needed.
6. Click **Start** to run the automation.

(Version 1 can only be accessed from the login screen. If you are already logged into an account, please log out first.)