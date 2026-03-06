import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import time
import random
import re
import xml.etree.ElementTree as ET
import sys
import queue

# ============================================================
# ADB 工具函数（与设备无关）
# ============================================================
ADB_BIN = "platform-tools/adb.exe"

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
    return [l.split("\t")[0] for l in out
            if "\tdevice" in l and ":" not in l]


def list_wifi_devices():
    out = adb_raw(["devices"]).stdout.splitlines()
    return [l.split("\t")[0] for l in out
            if "\tdevice" in l and ":" in l]


# ============================================================
# DeviceBot 类（你的 build_large_box 完整保留）
# ============================================================
def run_utf8(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "ignore")
    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def rsleep(base=1.0, delta=0.5):
    sec = random.uniform(base - delta, base + delta)
    time.sleep(max(sec, 0.1))


class DeviceBot:
    def __init__(self, serial, logger=None):
        self.serial = serial
        self.should_stop = False   # ⭐ 用于停止任务
        self.logger = logger
    
    def log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def adb(self, args):
        cmd = [ADB_BIN, "-s", self.serial] + args
        return run_utf8(cmd)

    def wake_and_unlock(self):

        print("💡 Wake device")

        state = self.adb([
            "shell", "dumpsys", "power"
        ]).stdout

        # 如果屏幕关闭才点亮
        if "Display Power: state=OFF" in state:
            print("🔆 Screen off → waking up")
            self.adb(["shell", "input", "keyevent", "26"])
            time.sleep(0.5)

        # 滑动解锁
        self.adb([
            "shell", "input", "swipe",
            "300", "1000", "300", "400", "300"
        ])

        time.sleep(0.5)

    def stop_wms(self):
        self.adb(["shell", "am", "force-stop", "com.jd.mrd.pangu"])

    def run_wms(self):
        # 回到桌面
        self.adb(["shell", "input", "keyevent", "3"])
        rsleep(0.5, 0.2)

        # 启动 iWMS
        r = self.adb([
            "shell", "am", "start", "-n",
            "com.jd.mrd.pangu/.entrance.activity.WelcomeActivity"
        ])

        print("[am start stdout]", r.stdout.strip())
        print("[am start stderr]", r.stderr.strip())

        # 等待加载
        rsleep(2, 1)

        # 验证是否真的到前台
        focus = self.adb(["shell", "dumpsys", "window", "windows"]).stdout
        if "com.jd.mrd.pangu" not in focus:
            print("❌ iWMS not in foreground. Current focus check failed.")

    def handle_update_if_needed(self):

        xml = self.get_page_xml()

        if "Install" not in xml or "Version" not in xml:
            return False

        print("⚠️ New version detected")

        # 第一层 INSTALL
        if self.click_by_text("INSTALL"):
            print("📦 Click first INSTALL")
        else:
            print("❌ INSTALL button not found")
            return False

        time.sleep(1)

        # 第二层 Android INSTALL
        for _ in range(20):

            xml = self.get_page_xml()

            if "Do you want to install" in xml or "existing application" in xml:
                print("📦 Android install confirm detected")

                if self.click_by_text("INSTALL"):
                    print("✅ Click second INSTALL")
                    break

            time.sleep(0.5)

        # 等待安装完成
        print("⏳ Waiting install finish...")

        for _ in range(60):

            xml = self.get_page_xml()

            # 登录页面出现说明安装完成
            if "App installed" in xml:

                print("✅ Install finished")

                # 点击 OPEN
                if self.click_by_text("OPEN"):
                    print("🚀 Click OPEN")

                return True

            time.sleep(1)

        print("⚠️ Install timeout")
        return False
    
    def ensure_adb_keyboard(self):
        """
        Ensure ADBKeyboard is active.
        If not installed -> warn.
        If installed but not active -> switch to it.
        """

        print("🔎 Checking ADBKeyboard...")

        # 1️⃣ 检查是否安装
        pkg_check = self.adb([
            "shell", "pm", "list", "packages", "com.android.adbkeyboard"
        ]).stdout

        if "com.android.adbkeyboard" not in pkg_check:
            print("❌ ADBKeyboard not installed!")
            print("⚠️ Please install ADBKeyboard.apk on the device.")
            return False

        # 2️⃣ 查看当前输入法
        current_ime = self.adb([
            "shell", "settings", "get", "secure", "default_input_method"
        ]).stdout.strip()

        if "com.android.adbkeyboard/.AdbIME" in current_ime:
            print("✅ ADBKeyboard already active")
            return True

        print("⚠️ Switching to ADBKeyboard...")

        # 3️⃣ 启用输入法
        self.adb([
            "shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME"
        ])

        # 4️⃣ 切换输入法
        self.adb([
            "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME"
        ])

        time.sleep(0.5)

        print("✅ ADBKeyboard activated")

        return True
    
    def input_text_adbime(self, text, press_enter=False):
        self.adb([
            "shell", "am", "broadcast",
            "-a", "ADB_INPUT_TEXT",
            "--es", "msg", text
        ])
        time.sleep(0.2)

        if press_enter:
            self.adb(["shell", "input", "keyevent", "66"])

    def get_page_xml(self):
        self.adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
        return self.adb(["shell", "cat", "/sdcard/window_dump.xml"]).stdout

    def detect_container_with_goods(self, cell_a, cell_b):

        print("🔎 Detecting container with goods...")

        qty_a = self.check_current_container(cell_a)
        print(f"{cell_a} qty =", qty_a)

        qty_b = self.check_current_container(cell_b)
        print(f"{cell_b} qty =", qty_b)

        if qty_a and qty_a > 0:
            print(f"📦 Goods in {cell_a}")
            return cell_a

        if qty_b and qty_b > 0:
            print(f"📦 Goods in {cell_b}")
            return cell_b

        print("⚠️ No goods detected, default to A")
        return cell_a

    def click_by_text(self, target_text, max_scroll=5):
        for _ in range(max_scroll):
            if self.should_stop: return False
            xml = self.get_page_xml()
            m = re.search(
                rf'text="{re.escape(target_text)}".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml, re.S
            )
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                cx, cy = (x1 + x2)//2, (y1 + y2)//2
                self.adb(["shell", "input", "tap", str(cx), str(cy)])
                return True

            self.adb(["shell", "input", "swipe",
                      "300", "700", "300", "200", "500"])
        return False
    
    def _get_text_by_rid(self, rid):
        xml = self.get_page_xml()
        try:
            root = ET.fromstring(xml)
        except Exception:
            return None
        for node in root.iter("node"):
            if node.attrib.get("resource-id") == rid:
                return node.attrib.get("text", "")
        return None
    
    def input_text_exact(self, rid, text, press_enter=False, max_fix=6):
        """
        目标：让输入框最终内容 = text
        处理：先清空 -> adb input text(带转义) -> 读取实际值 -> 如果末尾多了就删
        """
        # 先聚焦
        if not self.tap_rid_and_confirm_focus(rid):
            return False

        # 清空
        for _ in range(20):
            self.adb(["shell", "input", "keyevent", "67"])

        # ADB input text 对某些符号要转义（尤其 !）
        esc = text.replace(" ", "%s")
        esc = esc.replace("!", r"\!")  # 关键：避免 ! 被当成奇怪映射
        # 你也可以按需加：esc = esc.replace("@", r"\@")  （一般不需要）

        self.adb(["shell", "input", "text", esc])
        rsleep(0.25, 0.1)

        # 读取实际输入，修正“末尾多字符”
        for _ in range(max_fix):
            cur = self._get_text_by_rid(rid)
            if cur is None:
                break

            if cur == text:
                if press_enter:
                    self.adb(["shell", "input", "keyevent", "66"])
                return True

            # 如果是 “正确前缀 + 多尾巴”，就删掉尾巴
            if cur.startswith(text) and len(cur) > len(text):
                extra = len(cur) - len(text)
                self.adb(["shell", "input", "keyevent", "123"])  # MOVE_END
                for _ in range(extra):
                    self.adb(["shell", "input", "keyevent", "67"])  # DEL
                rsleep(0.15, 0.05)
                continue

            # 其他情况（比如符号被改了）：直接重来一次
            self.clear_current_input(max_del=120)
            self.adb(["shell", "input", "text", esc])
            rsleep(0.2, 0.05)

        return False
    
    def click_input_by_hint(self, hint_text):
        """
        Click <android.widget.EditText> based on its hint attribute.
        Example: hint_text = "Tracking number"
        """
        xml = self.get_page_xml()

        # 匹配 EditText with hint="Tracking number"
        m = re.search(
            rf'class="android\.widget\.EditText".*?hint="{re.escape(hint_text)}".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml,
            re.S
        )

        if not m:
            return False

        x1, y1, x2, y2 = map(int, m.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        self.adb(["shell", "input", "tap", str(cx), str(cy)])
        return True

    
    def click_empty_input(self, max_scroll=5):
        """
        Click an empty EditText (text="").
        """
        for _ in range(max_scroll):
            if self.should_stop:
                return False

            xml = self.get_page_xml()

            m = re.search(
                r'class="android\.widget\.EditText".*?text="".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml, re.S
            )

            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                cx = (x1 + x2)//2
                cy = (y1 + y2)//2

                self.adb(["shell", "input", "tap", str(cx), str(cy)])
                return True

            self.adb(["shell", "input", "swipe", "300", "700", "300", "200", "500"])

        return False

    def click_edittext_by_partial_id(self, keyword):
        xml = self.get_page_xml()

        m = re.search(
            rf'class="android\.widget\.EditText".*?resource-id="[^"]*{re.escape(keyword)}[^"]*".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml,
            re.S
        )

        if not m:
            return False

        x1, y1, x2, y2 = map(int, m.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        self.adb(["shell", "input", "tap", str(cx), str(cy)])
        return True

    def click_edittext_after_label(self, label_text, occurrence=1):

        xml = self.get_page_xml()

    # 先找 label 的位置，然后找其后出现的第一个 EditText
    # 注意：这里用 .*? 非贪婪，尽量锁定“label后面的EditText”
        pattern = (
            rf'text="[^"]*{re.escape(label_text)}[^"]*".*?'
            rf'class="android\.widget\.EditText".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        )

        matches = list(re.finditer(pattern, xml, re.S))
        if len(matches) < occurrence:
            return False

        m = matches[occurrence - 1]
        x1, y1, x2, y2 = map(int, m.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        self.adb(["shell", "input", "tap", str(cx), str(cy)])
        return True
    
    def wait_until_text(self, text, timeout=3.0, interval=0.2):
        end = time.time() + timeout
        while time.time() < end:
            if self.should_stop:
                return False
            xml = self.get_page_xml()
            if re.search(rf'text="[^"]*{re.escape(text)}[^"]*"', xml):
                return True
            time.sleep(interval)
        return False
    
    def fill_offshelf_and_destination(self, destination_value):
    # 等下一页出现 Off-shelf quanity
        if not self.wait_until_text("Off-shelf quanity", timeout=3.0, interval=0.2):
            print("❌ Off-shelf quanity page not detected (timeout).")
            return False

    # 1) Off-shelf quanity -> 1
        if not self.click_edittext_after_label("Off-shelf quanity"):
            print("❌ Off-shelf quanity input not found.")
            return False
        rsleep(0.1, 0)
        self.input_text_direct("1")  # ✅ 固定填 1

    # 2) Destination cell/container -> destination_value
        if not self.click_edittext_after_label("Destination Cell/Container"):
            if not (self.click_edittext_after_label("Destination Cell") or
                    self.click_edittext_after_label("Destination Container")):
                print("❌ Destination input not found.")
                return False

        rsleep(0.1, 0)
        self.input_text_direct(destination_value)  # ✅ 填 destination
        return True

    def input_text_direct(self, text, press_enter=True):
        esc = (
            text.replace(" ", "%s")
        )
        self.adb(["shell", "input", "text", esc])

        if press_enter:
            self.adb(["shell",  "input", "keyevent", "66"])
            
        print(f"Input text: {text}")

    def check_current_container(self, container_number):
        #self.adb(["shell", "input", "keyevent", "4"])
        rsleep(0.4, 0.1)
        self.input_text_direct(container_number)
        rsleep(0.5,0.1)
        xml = self.get_page_xml()
        m = re.search(
            r'Total package quantity.*?text="(\d+)"', xml, re.S
        )
        if m:
            return int(m.group(1))
        return None
    
    def click_by_partial_id(self, keyword):
        xml = self.get_page_xml()

        m = re.search(
            rf'resource-id="[^"]*{re.escape(keyword)}[^"]*".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml,
            re.S
        )

        if not m:
            return False

        x1, y1, x2, y2 = map(int, m.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        self.adb(["shell", "input", "tap", str(cx), str(cy)])
        return True

    def get_current_page(self):
        xml = self.get_page_xml()

        if "signin_email_et" in xml:
            return "login"

        if "JDL iWMS" in xml:
            return "main"

        return "unknown"


    def _parse_bounds(self, b):
        # b like: "[48,503][1032,623]"
        nums = list(map(int, re.findall(r"\d+", b)))
        x1, y1, x2, y2 = nums
        return x1, y1, x2, y2

    def _find_node_by_rid(self, rid):
        xml = self.get_page_xml()
        try:
            root = ET.fromstring(xml)
        except Exception:
            return None, None

        for node in root.iter("node"):
            if node.attrib.get("resource-id") == rid:
                return node, node.attrib.get("bounds")
        return None, None

    def _get_focused_rid(self):
        xml = self.get_page_xml()
        try:
            root = ET.fromstring(xml)
        except Exception:
            return None
        for node in root.iter("node"):
            if node.attrib.get("focused") == "true":
                return node.attrib.get("resource-id")
        return None

    def tap_rid_and_confirm_focus(self, rid, tries=3):
        for _ in range(tries):
            node, b = self._find_node_by_rid(rid)
            if not b:
                rsleep(0.3, 0.1)
                continue

            x1, y1, x2, y2 = self._parse_bounds(b)
            cx, cy = (x1 + x2)//2, (y1 + y2)//2
            self.adb(["shell", "input", "tap", str(cx), str(cy)])
            rsleep(0.25, 0.1)

            if self._get_focused_rid() == rid:
                return True

            # 有些设备 tap 不切焦点，补一个 TAB/DPAD_DOWN 再试
            self.adb(["shell", "input", "keyevent", "61"])  # TAB
            rsleep(0.2, 0.1)

            if self._get_focused_rid() == rid:
                return True

        return False

    def clear_current_input(self, max_del=60):
        # Ctrl + A
        self.adb(["shell", "input", "keyevent", "113"])  # CTRL down
        self.adb(["shell", "input", "keyevent", "29"])   # A
        self.adb(["shell", "input", "keyevent", "114"])  # CTRL up

        time.sleep(0.05)

        # 删除选中内容
        self.adb(["shell", "input", "keyevent", "67"])

    def build_large_box(self,
                    limit=400,
                    cred_list=None):

        if not cred_list:
            print("❌ No credentials list provided")
            return

        # 固定两个库位
        cell_a = "A1-R1-L1-B1"
        cell_b = "A1-R1-L1-B2"
        current_container = None

        cred_idx = 0
        loop_count = 0   # ⭐ 总循环次数

        current_container = "A1-R1-L1-B1"

        while not self.should_stop and (limit == 0 or loop_count < limit):
            if current_container == cell_a:
                destination = cell_b
            else:
                destination = cell_a

            account, password = cred_list[cred_idx]

            self.log("========================================")
            self.log(f"🔁 Loop #{loop_count + 1}")
            self.log(f"👤 Account : {account}")
            self.log(f"🔑 Password: {password}")
            self.log("========================================")

            # 只在第一次循环启动一次
            if loop_count == 0:
                self.wake_and_unlock()
                self.ensure_adb_keyboard()
                self.stop_wms()
                self.run_wms()
                rsleep(1, 0.3)

                self.handle_update_if_needed()

            if not self.login(account, password):
                print("❌ Login failed")
                cred_idx += 1
                continue

            self.handle_update_if_needed()

            rsleep(0.8, 0.2)

            # 进入功能页面
            if not self.click_by_text("In-Warehouse"):
                return
            rsleep(0.6, 0.1)

            if not self.click_by_text("change"):
                return
            rsleep(0.6, 0.1)

            if not self.click_by_text("Transfer"):
                return
            rsleep(0.6, 0.1)

            if not self.click_by_text("Goods Location Trans."):
                return
            rsleep(0.6, 0.1)

            # 输入 Cell Code
            self.input_text_direct(current_container, press_enter=True)

            # 等 UI 自动跳到 product code
            time.sleep(0.7)

            # 输入 Product Code
            fixed_product = "B0108-03001BK"
            self.input_text_direct(fixed_product, press_enter=True)
            
            # ⭐ 填写数量和目标库位
            if not self.fill_offshelf_and_destination(destination):
                print("❌ Fill destination failed")
                return

            # 一直按返回直到主页面出现
            for _ in range(6):
                self.adb(["shell", "input", "keyevent", "4"])
                rsleep(0.25, 0.05)

                xml = self.get_page_xml()
                if "JDL iWMS" in xml:
                    break
            print("✅ Limit reached, signing out...")

            # Sign out
            if not self.click_by_partial_id("iv_setting"):
                return

            rsleep(0.5, 0.1)

            if not self.click_by_text("SIGN OUT"):
                return

            if not self.wait_until_text("CONFIRM", timeout=4):
                return

            if not self.click_by_text("CONFIRM"):
                return
            
            loop_count += 1

            self.log("---------- Loop Finished ----------")
            self.log(f"Total loops: {loop_count}")
            self.log("-----------------------------------")

            cred_idx = (cred_idx + 1) % len(cred_list)
            current_container = destination

        print("🎉 All accounts finished.")

    def login(self, account, password):

        # 只 dump 一次
        xml = self.get_page_xml()

        email_rid = "com.jd.mrd.pangu:id/signin_email_et"
        pwd_rid   = "com.jd.mrd.pangu:id/signin_pwd_et"
        btn_rid   = "com.jd.mrd.pangu:id/login_rl"

        def find_bounds(rid):
            m = re.search(
                rf'resource-id="{re.escape(rid)}".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml,
                re.S
            )
            if not m:
                return None
            return list(map(int, m.groups()))

        email_bounds = find_bounds(email_rid)
        pwd_bounds   = find_bounds(pwd_rid)
        btn_bounds   = find_bounds(btn_rid)

        if not email_bounds or not pwd_bounds or not btn_bounds:
            print("❌ Login elements not found")
            return False

        # ===== 账号 =====
        x1,y1,x2,y2 = email_bounds
        self.adb(["shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)])
        self.clear_current_input()
        self.input_text_adbime(account)

        # ===== 密码 =====
        x1,y1,x2,y2 = pwd_bounds
        self.adb(["shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)])
        self.clear_current_input()
        self.input_text_adbime(password)

        # ===== 登录 =====
        x1,y1,x2,y2 = btn_bounds
        self.adb(["shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)])

        # 等待 Select Warehouse 页面
        if not self.wait_until_text("Select Warehouse", timeout=4):
            print("❌ Warehouse page not detected")
            return False

        # 点击 EWR-LG-5-US
        if not self.click_by_text("EWR-LG-5-US"):
            print("❌ Warehouse option not found")
            return False

        # 等主页面
        return self.wait_until_text("JDL iWMS", timeout=5)
    
    def click_keyboard_next(self):
        xml = self.get_page_xml()

        m = re.search(
            r'content-desc="Next".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml,
            re.S
        )

        if not m:
            return False

        x1,y1,x2,y2 = map(int, m.groups())
        cx = (x1+x2)//2
        cy = (y1+y2)//2

        self.adb(["shell","input","tap",str(cx),str(cy)])
        return True
    
    def click_by_resource_id(self, rid):
        xml = self.get_page_xml()

        m = re.search(
            rf'resource-id="{re.escape(rid)}".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml,
            re.S
        )

        if not m:
            return False

        x1, y1, x2, y2 = map(int, m.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        self.adb(["shell", "input", "tap", str(cx), str(cy)])
        rsleep(0.4, 0.1)   # ⭐ 给UI一点时间

        return True
# ============================================================
# GUI 主程序
# ============================================================
class MultiDeviceGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Walmurt: A Faster,Lighter Billbert")
        self.root.geometry("1100x850")

        self.running_processes = {}   # {serial: Thread}

        # ============================
        # 左侧：设备选择区
        # ============================
        frame_left = ttk.LabelFrame(root, text="设备选择")
        frame_left.pack(side="left", fill="y", padx=10, pady=10)

        self.device_listbox = tk.Listbox(frame_left, height=15, selectmode=tk.MULTIPLE)
        self.device_listbox.pack(padx=10, pady=10)

        ttk.Button(frame_left, text="刷新 USB", command=self.refresh_usb).pack(fill="x", padx=10, pady=5)
        ttk.Button(frame_left, text="刷新 WiFi", command=self.refresh_wifi).pack(fill="x", padx=10, pady=5)
        ttk.Button(frame_left, text="WiFi 配对", command=self.open_wifi_pair_window).pack(fill="x", padx=10, pady=5)
        ttk.Button(frame_left, text="WiFi 连接", command=self.open_wifi_connect_window).pack(fill="x", padx=10, pady=5)

        # ttk.Button(frame_left, text="Kill 选中设备", command=self.kill_selected).pack(fill="x", padx=10, pady=5)
        # ttk.Button(frame_left, text="Kill ALL", command=self.kill_all).pack(fill="x", padx=10, pady=5)

        # ============================
        # 右侧：输入区
        # ============================
        frame_right = ttk.Frame(root)
        frame_right.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frame_right, text="Login Account(one per line):").pack(anchor="w")
        self.accounts_text = scrolledtext.ScrolledText(frame_right, height=4)
        self.accounts_text.pack(fill="x", pady=5)

        ttk.Label(frame_right, text="Login Password(one per line, match accounts):").pack(anchor="w")
        self.passwords_text = scrolledtext.ScrolledText(frame_right, height=4)
        self.passwords_text.pack(fill="x", pady=5)
        
        # ============================
        #  参数区
        # ============================
        param_frame = ttk.LabelFrame(frame_right, text="运行参数设置")
        param_frame.pack(fill="x", pady=10)

        # limit
        ttk.Label(param_frame, text="Limit:").grid(row=0, column=2, sticky="w")
        self.entry_limit = ttk.Entry(param_frame, width=10)
        self.entry_limit.insert(0, "0")
        self.entry_limit.grid(row=0, column=3, padx=5)

        ttk.Button(frame_right, text="▶ 启动任务（选中设备）",
                    command=self.start_for_selected).pack(pady=15)

        # 日志输出
        ttk.Label(frame_right, text="日志输出:").pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(frame_right, height=10)
        self.log_text.pack(fill="both", expand=True)

    # ============================================================
    # 设备刷新
    # ============================================================
    def refresh_usb(self):
        self.device_listbox.delete(0, tk.END)
        for d in list_usb_devices():
            self.device_listbox.insert(tk.END, d)

    def refresh_wifi(self):
        self.device_listbox.delete(0, tk.END)
        for d in list_wifi_devices():
            self.device_listbox.insert(tk.END, d)
            
    def open_wifi_connect_window(self):
        win = tk.Toplevel(self.root)
        win.title("WiFi ADB 连接")
        win.geometry("420x500")

        ttk.Label(win, text="WiFi ADB 连接", font=("Arial", 12, "bold")).pack(pady=10)

        guide = (
            "请输入 Wireless debugging 显示的设备地址：\n\n"
            "示例：192.168.1.95:5555\n\n"
            "必须已完成 Wireless debugging 的配对（Pairing）。"
        )

        txt = tk.Text(win, height=6, width=55, wrap="word")
        txt.insert("1.0", guide)
        txt.config(state="disabled")
        txt.pack(pady=5)

        ttk.Label(win, text="IP:Port").pack(pady=5)

        entry = ttk.Entry(win, width=30)
        entry.insert(0, "192.168.1.95:5555")
        entry.pack(pady=5)

        result_label = ttk.Label(win, text="", foreground="blue")
        result_label.pack(pady=10)

        # ⭐⭐⭐ Connect 按钮的动作
        def do_connect():
            ip_port = entry.get().strip()
            if not ip_port:
                result_label.config(text="⚠️ 请输入 IP:Port")
                return
            
            out = adb_raw(["connect", ip_port]).stdout.strip()
            result_label.config(text=out)

            # 写到主界面日志
            self.log(f"[WiFi Connect] {out}")

            # 成功后自动刷新 WiFi 设备列表
            if "connected" in out.lower():
                time.sleep(0.5)
                self.refresh_wifi()

        # ⭐⭐⭐ 这是你缺失的 Connect 按钮
        ttk.Button(win, text="Connect", command=do_connect).pack(pady=10)


    
    def open_wifi_pair_window(self):
        win = tk.Toplevel(self.root)
        win.title("无线ADB调试配对")
        win.geometry("550x580")

        ttk.Label(win, text="Android Wireless Debugging (Full Guide)",
                font=("Arial", 12, "bold")).pack(pady=10)

        tutorial = (
            "1. Enable Developer Options:\n"
            "   Settings → About phone → Tap 'Build number' 7 times\n\n"
            "2. Enable USB Debugging:\n"
            "   Settings → System → Developer options → USB debugging → ON\n\n"
            "3. Connect USB once and accept the dialog.\n\n"
            "4. Enable Wireless Debugging:\n"
            "   Developer options → Wireless debugging → ON\n\n"
            "5. Tap: 'Pair device with pairing code'\n\n"
            "6. Phone shows:\n"
            "   IP Address: 192.168.1.95:37099\n"
            "   Pairing Code: 482913\n\n"
            "7. Enter both below and click Pair.\n"
        )

        txt = tk.Text(win, height=18, width=70, wrap="word")
        txt.insert("1.0", tutorial)
        txt.config(state="disabled")
        txt.pack(pady=5)

        # Input: IP:Port
        ttk.Label(win, text="IP:Port").pack(pady=2)
        ip_entry = ttk.Entry(win, width=35)
        ip_entry.insert(0, "192.168.1.95:37099")
        ip_entry.pack(pady=2)

        # Input: Pairing Code
        ttk.Label(win, text="Pairing Code").pack(pady=2)
        code_entry = ttk.Entry(win, width=35)
        code_entry.insert(0, "123456")
        code_entry.pack(pady=2)

        # Result label
        result_label = ttk.Label(win, text="", foreground="blue")
        result_label.pack(pady=10)

        # Pair button
        def do_pair():
            ip_port = ip_entry.get().strip()
            code = code_entry.get().strip()

            if not ip_port or not code:
                result_label.config(text="Please enter both IP:Port and code")
                return

            # adb pair <IP:Port> <code>
            result = adb_raw(["pair", ip_port, code]).stdout.strip()
            result_label.config(text=result)

        ttk.Button(win, text="Pair", command=do_pair).pack(pady=10)



    # ============================================================
    # 启动任务
    # ============================================================    
    def start_for_selected(self):
        selections = self.device_listbox.curselection()
        if not selections:
            messagebox.showerror("错误", "请选择至少一个设备")
            return
        
        accounts = [x.strip() for x in self.accounts_text.get("1.0", tk.END).splitlines() if x.strip()]
        passwords = [x.strip() for x in self.passwords_text.get("1.0", tk.END).splitlines() if x.strip()]

        if not accounts or not passwords:
            messagebox.showerror("错误", "Accounts / Passwords 不能为空（每行一个）")
            return

        if len(accounts) != len(passwords):
            messagebox.showerror("错误", f"账号行数({len(accounts)})和密码行数({len(passwords)})不一致")
            return

        cred_list = list(zip(accounts, passwords))

        for idx in selections:
            serial = self.device_listbox.get(idx)

            if serial in self.running_processes:
                messagebox.showerror("错误", f"{serial} 正在运行任务")
                continue

            t = threading.Thread(
                target=self.run_bot_worker,
                args=(serial, cred_list),
                daemon=True
            )
            t.start()
            self.running_processes[serial] = t
            self.log(f"[{serial}] 任务启动")

    def run_bot_worker(self, serial, cred_list):
        bot = DeviceBot(serial, logger=lambda m: self.log(f"[{serial}] {m}"))

        # 从 UI 获取参数
        # checkpoint = int(self.entry_checkpoint.get())
        limit = int(self.entry_limit.get())

        bot.build_large_box(
            limit=limit,
            cred_list=cred_list
        )

        self.log(f"[{serial}] 任务完成")
        del self.running_processes[serial]

    # ============================================================
    # Kill 机制：支持随时杀任务
    # ============================================================
    def kill_selected(self):
        selections = self.device_listbox.curselection()
        for idx in selections:
            serial = self.device_listbox.get(idx)
            if serial in self.running_processes:
                self.running_processes[serial]._stop()
                del self.running_processes[serial]
                self.log(f"[{serial}] ❌ 已强制终止")

    def kill_all(self):
        for serial, thread in list(self.running_processes.items()):
            thread._stop()
            self.log(f"[{serial}] ❌ 已强制终止")
        self.running_processes.clear()

    # ============================================================
    # 日志
    # ============================================================
    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)


# ============================================================
# 程序入口
# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = MultiDeviceGUI(root)
    root.mainloop()
