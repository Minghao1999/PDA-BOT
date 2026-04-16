import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import time
import random
import re
import sys
import hashlib
import os

# ============================================================
# ADB 工具
# ============================================================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

ADB_BIN = resource_path("platform-tools/adb.exe")

def adb_raw(args):
    return subprocess.run(
        [ADB_BIN] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def list_usb_devices():
    out = adb_raw(["devices"]).stdout.splitlines()
    return [l.split("\t")[0] for l in out if "\tdevice" in l and ":" not in l]

def run_utf8(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def rsleep(rng, base=1.0, delta=0.5):
    sec = rng.uniform(base - delta, base + delta)
    time.sleep(max(sec, 0.1))

# ============================================================
# DeviceBot
# ============================================================
class DeviceBot:
    def __init__(self, serial, logger=None):
        self.serial = serial
        self.should_stop = False
        self.logger = logger
        seed = int(hashlib.md5(serial.encode()).hexdigest(), 16) % (2**32)
        self.rng = random.Random(seed)

    def log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def adb(self, args):
        return run_utf8([ADB_BIN, "-s", self.serial] + args)

    def get_page_xml(self):
        self.adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
        return self.adb(["shell", "cat", "/sdcard/window_dump.xml"]).stdout

    def input_text_direct(self, text):
        self.adb(["shell", "input", "keyevent", "123"])
        self.adb(["shell", "input", "keyevent", "29", "--meta", "113"])
        for _ in range(5):
            self.adb(["shell", "input", "keyevent", "67"])

        esc = str(text).replace(" ", "%s")
        self.adb(["shell", "input", "text", esc])
        time.sleep(0.2)
        self.adb(["shell", "input", "keyevent", "66"])

    def click_edittext_after_label(self, label_text):
        xml = self.get_page_xml()
        pattern = rf'text="[^"]*{re.escape(label_text)}[^"]*".*?class="android\.widget\.EditText".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        match = re.search(pattern, xml, re.S)
        if not match:
            return False
        x1, y1, x2, y2 = map(int, match.groups())
        self.adb(["shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2)])
        return True

    def wait_until_text(self, text, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            if re.search(rf'text="[^"]*{re.escape(text)}[^"]*"', self.get_page_xml()):
                return True
            time.sleep(0.3)
        return False
    
    def click_button_by_text(self, text):
        xml = self.get_page_xml()
        pattern = rf'text="{text}".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        match = re.search(pattern, xml)

        if not match:
            return False

        x1, y1, x2, y2 = map(int, match.groups())
        x = (x1 + x2) // 2
        y = (y1 + y2) // 2

        self.adb(["shell", "input", "tap", str(x), str(y)])
        return True

    # ============================================================
    # 核心：Relocation 循环
    # ============================================================
    def relocation_loop(self, limit, cell_a, cell_b):
        loop = 0
        current = cell_a
        self.log("🚀 开始 Relocation 循环")

        while not self.should_stop and (limit == 0 or loop < limit):
            target = cell_b if current == cell_a else cell_a

            self.log(f"#{loop+1}: {current} → {target}")

            # 输入 Cell Code
            if not self.wait_until_text("Cell Code"):
                self.log("❌ 找不到 Cell Code 页面")
                break

            if not self.click_edittext_after_label("Cell Code"):
                self.log("❌ 找不到 Cell Code 输入框")
                break

            self.input_text_direct(current)
            time.sleep(0.3)

            # 输入 Destination
            if not (self.click_edittext_after_label("Destination Cell/Container")
                    or self.click_edittext_after_label("Destination Cell")):
                self.log("❌ 找不到 Destination 输入框")
                break

            self.input_text_direct(target)
            time.sleep(0.3)

            # CONFIRM
            # CONFIRM（点击按钮）
            if not self.click_button_by_text("CONFIRM"):
                self.log("❌ 找不到 CONFIRM 按钮")
                break

            self.log("✅ 点击 CONFIRM")

            rsleep(self.rng, 0.8, 0.2)

            loop += 1
            current = target

        self.log(f"🏁 完成 {loop} 次")

# ============================================================
# GUI
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Relocation Bot")
        self.root.geometry("500x600")

        # 设备
        frame = ttk.LabelFrame(root, text="设备")
        frame.pack(fill="x", padx=10, pady=5)

        self.listbox = tk.Listbox(frame, height=4)
        self.listbox.pack(side="left", fill="x", expand=True)

        ttk.Button(frame, text="刷新", command=self.refresh).pack(side="right")

        # 参数
        param = ttk.LabelFrame(root, text="参数")
        param.pack(fill="x", padx=10, pady=5)

        ttk.Label(param, text="Cell A").grid(row=0, column=0)
        self.cell_a = tk.StringVar(value="A1-R1-L1-B1")
        ttk.Entry(param, textvariable=self.cell_a).grid(row=0, column=1)

        ttk.Label(param, text="Cell B").grid(row=1, column=0)
        self.cell_b = tk.StringVar(value="A1-R1-L1-B2")
        ttk.Entry(param, textvariable=self.cell_b).grid(row=1, column=1)

        ttk.Label(param, text="循环次数(0无限)").grid(row=2, column=0)
        self.limit = tk.StringVar(value="400")
        ttk.Entry(param, textvariable=self.limit).grid(row=2, column=1)

        # 按钮
        btn = ttk.Frame(root)
        btn.pack(fill="x", padx=10)

        ttk.Button(btn, text="开始", command=self.start).pack(side="left", expand=True, fill="x")
        ttk.Button(btn, text="停止", command=self.stop).pack(side="right", expand=True, fill="x")

        # 日志
        self.logbox = scrolledtext.ScrolledText(root, height=15)
        self.logbox.pack(fill="both", expand=True, padx=10, pady=5)

        self.thread = None

    def log(self, msg):
        self.logbox.insert(tk.END, msg+"\n")
        self.logbox.see(tk.END)

    def refresh(self):
        self.listbox.delete(0, tk.END)
        for d in list_usb_devices():
            self.listbox.insert(tk.END, d)

    def start(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showerror("错误", "选设备")
            return

        serial = self.listbox.get(sel[0])
        limit = int(self.limit.get())

        def run():
            bot = DeviceBot(serial, logger=self.log)
            bot.relocation_loop(limit, self.cell_a.get(), self.cell_b.get())

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def stop(self):
        os._exit(0)

# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()