import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog # 增加 filedialog
import subprocess
import threading
import time
import random
import re
import sys
import hashlib
import os
import pandas as pd

# ============================================================
# ADB 工具函数
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

def run_utf8(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "ignore")
    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)

def rsleep(rng, base=1.0, delta=0.5):
    sec = rng.uniform(base - delta, base + delta)
    time.sleep(max(sec, 0.1))

# ============================================================
# DeviceBot 类
# ============================================================
class DeviceBot:
    def __init__(self, serial, logger=None):
        self.serial = serial
        self.should_stop = False
        self.logger = logger
        seed = int(hashlib.md5(serial.encode()).hexdigest(), 16) % (2**32)
        self.rng = random.Random(seed)
    
    def log(self, msg):
        if self.logger: self.logger(msg)
        else: print(msg)

    def adb(self, args):
        cmd = [ADB_BIN, "-s", self.serial] + args
        return run_utf8(cmd)

    def get_page_xml(self):
        self.adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
        return self.adb(["shell", "cat", "/sdcard/window_dump.xml"]).stdout

    def input_text_direct(self, text, press_enter=True):
        self.adb(["shell", "input", "keyevent", "123"]) 
        self.adb(["shell", "input", "keyevent", "29", "--meta", "113"]) 
        self.adb(["shell", "input", "keyevent", "67"])
        
        for _ in range(5):
            self.adb(["shell", "input", "keyevent", "67"])
        
        esc = str(text).replace(" ", "%s")
        self.adb(["shell", "input", "text", esc])
        
        time.sleep(0.2)
        
        if press_enter:
            self.adb(["shell", "input", "keyevent", "66"])
            time.sleep(0.3)

    def click_edittext_after_label(self, label_text, occurrence=1):
        xml = self.get_page_xml()
        pattern = rf'text="[^"]*{re.escape(label_text)}[^"]*".*?class="android\.widget\.EditText".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        matches = list(re.finditer(pattern, xml, re.S))
        if len(matches) < occurrence: return False
        x1, y1, x2, y2 = map(int, matches[occurrence - 1].groups())
        self.adb(["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)])
        return True

    def wait_until_text(self, text, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.should_stop: return False
            if re.search(rf'text="[^"]*{re.escape(text)}[^"]*"', self.get_page_xml()):
                return True
            time.sleep(0.3)
        return False

    def fill_offshelf_and_destination(self, qty, destination_value):
        if not self.wait_until_text("Off-shelf quanity"):
            return False
        if not self.click_edittext_after_label("Off-shelf quanity"): 
            self.log("❌ 找不到 Off-shelf quanity 输入框")
            return False
        self.input_text_direct(str(qty))
        
        if not (self.click_edittext_after_label("Destination Cell/Container") or 
                self.click_edittext_after_label("Destination Cell")):
            self.log("❌ 找不到 Destination 输入框")
            return False
        self.input_text_direct(destination_value)
        return True

    # ================= 核心循环 (增强版) =================
    def build_large_box(self, limit=400, product="", qty="1", cell_a="", cell_b=""):
        loop_count = 0
        current_source = cell_a
        self.log("🚀 任务启动：手动模式")

        while not self.should_stop and (limit == 0 or loop_count < limit):
            destination = cell_b if current_source == cell_a else cell_a
            self.log(f"--- #{loop_count + 1}: {current_source} -> {destination} ---")

            # 步骤 1: 源库位 (Source Cell)
            self.input_text_direct(current_source)
            time.sleep(0.2)

            # 步骤 2: 产品代码 (Product Code)
            self.input_text_direct(product)
            time.sleep(0.2) 
            
            # 步骤 3: 填写数量和目标库位
            if not self.fill_offshelf_and_destination(qty, destination):
                self.log(f"❌ 循环 #{loop_count + 1} 失败，尝试重置...")
                self.adb(["shell", "input", "keyevent", "4"])
                break

            # 步骤 4: 提交后的复位缓冲
            rsleep(self.rng, 0.8, 0.2) 
            
            loop_count += 1
            current_source = destination 

        self.log(f"🏁 任务结束，共执行 {loop_count} 次")

        self.log(f"🏁 任务结束，共执行 {loop_count} 次")

    # --- 新增 Excel 批量循环逻辑 ---
    def process_excel_loop(self, df, limit=400):
        loop_count = 0
        total_rows = len(df)
        self.log(f"🚀 任务启动：Excel 批量模式 (总行数: {total_rows})")
        
        while not self.should_stop and (limit == 0 or loop_count < limit):
            row_idx = loop_count % total_rows
            row = df.iloc[row_idx]
            
            p_code = str(row['Product'])
            p_qty = str(row['Qty'])
            p_from = str(row['From'])
            p_to = str(row['To'])

            self.log(f"--- 任务 #{loop_count + 1} (Row {row_idx + 1}) ---")
            self.log(f"From: {p_from} -> To: {p_to} | {p_code} (x{p_qty})")

            self.input_text_direct(p_from)
            rsleep(self.rng, 0.8, 0.2)
            self.input_text_direct(p_code)
            rsleep(self.rng, 0.8, 0.2)
            
            if not self.fill_offshelf_and_destination(p_qty, p_to):
                self.log("⚠️ 流程中断，尝试下一条...")
                time.sleep(2)
                continue

            rsleep(self.rng, 1.5, 0.5) 
            loop_count += 1
            self.log(f"✅ 任务 #{loop_count} 完成")

# ============================================================
# GUI 主程序
# ============================================================
class MultiDeviceGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ADB WMS 循环工具 v2.0")
        self.root.geometry("600x850")
        self.running_processes = {}
        self.excel_path = None

        # 设备列表
        frame_top = ttk.LabelFrame(root, text="设备列表")
        frame_top.pack(fill="x", padx=10, pady=5)
        self.device_listbox = tk.Listbox(frame_top, height=4, selectmode=tk.SINGLE)
        self.device_listbox.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ttk.Button(frame_top, text="刷新设备", command=self.refresh_usb).pack(side="right", padx=5)

        # --- 新增：Excel 上传区 ---
        excel_frame = ttk.LabelFrame(root, text="Excel 批量导入 (若使用则覆盖手动参数)", padding=10)
        excel_frame.pack(fill="x", padx=10, pady=5)
        self.excel_label = ttk.Label(excel_frame, text="未选择文件 (需包含列: Product, Qty, From, To)", foreground="gray")
        self.excel_label.pack(side="left", padx=5)
        ttk.Button(excel_frame, text="选择 Excel", command=self.upload_excel).pack(side="right", padx=5)
        ttk.Button(excel_frame, text="清空", command=self.clear_excel).pack(side="right", padx=2)

        # 参数区
        param_frame = ttk.LabelFrame(root, text="手动运行参数配置 (Excel模式下仅循环次数有效)", padding=10)
        param_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(param_frame, text="Product Code:").grid(row=0, column=0, sticky="w")
        self.product_var = tk.StringVar(value="B0108-03001BK")
        ttk.Entry(param_frame, textvariable=self.product_var).grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(param_frame, text="Off-shelf quanity:").grid(row=1, column=0, sticky="w")
        self.qty_var = tk.StringVar(value="1")
        ttk.Entry(param_frame, textvariable=self.qty_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(param_frame, text="Cell A:").grid(row=2, column=0, sticky="w")
        self.cell_a_var = tk.StringVar(value="A1-R1-L1-B1")
        ttk.Entry(param_frame, textvariable=self.cell_a_var).grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(param_frame, text="Cell B:").grid(row=3, column=0, sticky="w")
        self.cell_b_var = tk.StringVar(value="A1-R1-L1-B2")
        ttk.Entry(param_frame, textvariable=self.cell_b_var).grid(row=3, column=1, sticky="ew", pady=2)

        ttk.Label(param_frame, text="循环总次数 (0无限):").grid(row=4, column=0, sticky="w")
        self.limit_var = tk.StringVar(value="400")
        ttk.Entry(param_frame, textvariable=self.limit_var).grid(row=4, column=1, sticky="ew", pady=2)

        param_frame.columnconfigure(1, weight=1)

        # 控制按钮
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", padx=10)
        ttk.Button(btn_frame, text="▶ 开始任务", command=self.start_task).pack(side="left", expand=True, fill="x", padx=5, pady=10)
        ttk.Button(btn_frame, text="⏹ 停止/退出", command=self.stop_all).pack(side="right", expand=True, fill="x", padx=5, pady=10)

        # 日志
        ttk.Label(root, text="运行日志:").pack(anchor="w", padx=10)
        self.log_text = scrolledtext.ScrolledText(root, height=15)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

    def upload_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel Files", "*.xlsx *.xls")])
        if path:
            try:
                # 预读检查列名
                df = pd.read_excel(path)
                required = {'Product', 'Qty', 'From', 'To'}
                if not required.issubset(df.columns):
                    messagebox.showerror("错误", f"Excel必须包含列: {required}")
                    return
                self.excel_path = path
                self.excel_label.config(text=os.path.basename(path), foreground="green")
                self.log(f"成功加载 Excel: {path}")
            except Exception as e:
                messagebox.showerror("错误", f"读取失败: {e}")

    def clear_excel(self):
        self.excel_path = None
        self.excel_label.config(text="未选择文件 (需包含列: Product, Qty, From, To)", foreground="gray")

    def refresh_usb(self):
        self.device_listbox.delete(0, tk.END)
        for d in list_usb_devices():
            self.device_listbox.insert(tk.END, d)

    def start_task(self):
        selection = self.device_listbox.curselection()
        if not selection:
            messagebox.showerror("错误", "请选择设备")
            return
        serial = self.device_listbox.get(selection[0])
        
        if serial in self.running_processes:
            messagebox.showwarning("警告", "该设备任务已在运行")
            return

        t = threading.Thread(target=self.worker, args=(serial,), daemon=True)
        t.start()
        self.running_processes[serial] = t

    def worker(self, serial):
        bot = DeviceBot(serial, logger=lambda m: self.log(f"[{serial}] {m}"))
        try:
            limit = int(self.limit_var.get())
            
            # 判断逻辑：如果有Excel路径，走批量循环；否则走原有的A-B循环
            if self.excel_path:
                df = pd.read_excel(self.excel_path)
                bot.process_excel_loop(df, limit=limit)
            else:
                bot.build_large_box(
                    limit=limit,
                    product=self.product_var.get(),
                    qty=self.qty_var.get(),
                    cell_a=self.cell_a_var.get(),
                    cell_b=self.cell_b_var.get()
                )
        except Exception as e:
            self.log(f"程序异常: {e}")
        finally:
            if serial in self.running_processes:
                del self.running_processes[serial]

    def stop_all(self):
        self.log("⏳ 正在尝试停止当前任务...")
        sys.exit()

    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = MultiDeviceGUI(root)
    root.mainloop()