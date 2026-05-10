import flet as ft
import json
import os
import sys
import ctypes
from ctypes import wintypes
import threading
import winreg
import webbrowser
from functools import lru_cache

# Single instance check
def check_single_instance():
    mutex_name = "DayPlanner_SingleInstance_Mutex"
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = ctypes.windll.user32.FindWindowW(None, "DayPlanner")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    return mutex

mutex = check_single_instance()

try:
    import pystray
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()
TASKS_FILE = os.path.join(BASE_PATH, "tasks.json")
SETTINGS_FILE = os.path.join(BASE_PATH, "settings.json")
ICON_FILE = "icon.ico"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
VK_L = 0x4C
HOTKEY_ID = 1

user32 = ctypes.windll.user32

tray_icon = [None]
page_ref = [None]
app_visible = [True]

@lru_cache(maxsize=32)
def get_bg_color(opacity):
    alpha = hex(int(opacity * 255))[2:].zfill(2).upper()
    return f"#{alpha}181818"

@lru_cache(maxsize=32)
def get_card_color(opacity):
    alpha = hex(int(opacity * 255))[2:].zfill(2).upper()
    return f"#{alpha}252525"

def set_click_through(hwnd, enable):
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enable:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

def get_window_handle(title):
    return user32.FindWindowW(None, title)

def load_tasks():
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {"tabs": [{"name": "Главная", "tasks": data}], "active_tab": 0}
                return data
        except Exception:
            pass
    return {"tabs": [{"name": "Главная", "tasks": []}], "active_tab": 0}

def save_tasks(data):
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass

def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "DayPlanner")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def set_autostart(enable):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
            winreg.SetValueEx(key, "DayPlanner", 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, "DayPlanner")
            except Exception:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass

class DeferredSaver:
    def __init__(self, delay=1.0):
        self.delay = delay
        self.timer = None
        self.pending_tasks = None
        self.pending_settings = None

    def save_tasks_deferred(self, tasks):
        self.pending_tasks = tasks
        self._schedule()

    def save_settings_deferred(self, settings):
        self.pending_settings = settings
        self._schedule()

    def _schedule(self):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(self.delay, self._do_save)
        self.timer.daemon = True
        self.timer.start()

    def _do_save(self):
        if self.pending_tasks is not None:
            save_tasks(self.pending_tasks)
            self.pending_tasks = None
        if self.pending_settings is not None:
            save_settings(self.pending_settings)
            self.pending_settings = None

    def flush(self):
        if self.timer:
            self.timer.cancel()
        self._do_save()

saver = DeferredSaver(delay=0.5)

def get_icon_path():
    return os.path.join(BASE_PATH, ICON_FILE)

def create_tray_icon():
    if not TRAY_AVAILABLE:
        return None

    icon_path = get_icon_path()
    try:
        image = Image.open(icon_path) if os.path.exists(icon_path) else Image.new('RGB', (64, 64), color=(127, 90, 240))
    except Exception:
        image = Image.new('RGB', (64, 64), color=(127, 90, 240))

    def show_window(icon, item):
        app_visible[0] = True
        hwnd = get_window_handle("DayPlanner")
        if hwnd:
            user32.ShowWindow(hwnd, 5)
            user32.SetForegroundWindow(hwnd)

    def hide_window(icon, item):
        app_visible[0] = False
        hwnd = get_window_handle("DayPlanner")
        if hwnd:
            user32.ShowWindow(hwnd, 0)

    def toggle_autostart_tray(icon, item):
        set_autostart(not is_autostart_enabled())

    def quit_app(icon, item):
        icon.stop()
        saver.flush()
        hwnd = get_window_handle("DayPlanner")
        if hwnd:
            user32.ShowWindow(hwnd, 5)
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        threading.Thread(
            target=lambda: ((__import__('time').sleep(0.2)), os._exit(0)),
            daemon=True
        ).start()

    menu = pystray.Menu(
        pystray.MenuItem("Показать", show_window, default=True),
        pystray.MenuItem("Скрыть", hide_window),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Автозапуск с Windows",
            toggle_autostart_tray,
            checked=lambda item: is_autostart_enabled()
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app)
    )

    return pystray.Icon("DayPlanner", image, "DayPlanner", menu)


def main(page: ft.Page):
    page.title = "DayPlanner"
    page.bgcolor = ft.Colors.TRANSPARENT
    page.window.bgcolor = ft.Colors.TRANSPARENT
    page.window.frameless = True
    page.window.shadow = False

    page_ref[0] = page

    if TRAY_AVAILABLE:
        tray_icon[0] = create_tray_icon()
        if tray_icon[0]:
            threading.Thread(target=tray_icon[0].run, daemon=True).start()

    def hide_from_taskbar():
        __import__('time').sleep(0.3)
        hwnd = get_window_handle("DayPlanner")
        if hwnd:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.ShowWindow(hwnd, 0)
            user32.ShowWindow(hwnd, 5)

    threading.Thread(target=hide_from_taskbar, daemon=True).start()

    settings = load_settings()
    tasks_data = load_tasks()

    page.window.width = 380
    page.window.height = 650

    if "window_x" in settings and "window_y" in settings:
        page.window.left = settings["window_x"]
        page.window.top = settings["window_y"]
    else:
        page.window.center()

    ACCENT_COLOR = "#7F5AF0"
    TEXT_COLOR = "#FFFFFF"
    DISABLED_COLOR = "#444444"
    LOCKED_OPACITY = 0.5

    opacity_value = settings.get("opacity", 0.9)
    is_locked = [False]
    hwnd = [None]
    hotkey_thread_running = [True]
    dragging_task_id = [None]

    tabs_list = tasks_data.get("tabs", [{"name": "Главная", "tasks": []}])
    active_tab_raw = tasks_data.get("active_tab", 0)
    current_tab = [min(active_tab_raw, max(0, len(tabs_list) - 1))]

    tasks_data_list = []
    task_id_counter = [0]
    task_id_map = {}

    main_container = ft.Ref[ft.Container]()
    lock_button = ft.Ref[ft.IconButton]()
    close_button = ft.Ref[ft.IconButton]()
    add_button = ft.Ref[ft.IconButton]()
    opacity_slider = ft.Ref[ft.Slider]()
    input_field = ft.Ref[ft.TextField]()
    tabs_row_ref = [None]
    tasks_column_ref = [None]

    # File picker for attachments — added to overlay once
    pending_task_info = [None]

    def on_file_picked(e: ft.FilePickerResultEvent):
        if not e.files or not pending_task_info[0]:
            return
        task_info = pending_task_info[0]
        pending_task_info[0] = None
        for f in e.files:
            task_info["attachments"].append({"type": "file", "name": f.name, "path": f.path})
        _rebuild_attachment_chips(task_info)
        save_all_tasks()
        page.update()

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.append(file_picker)

    # ── helpers ──────────────────────────────────────────────────────────────

    def find_task_by_id(task_id):
        return task_id_map.get(task_id)

    def _close_dialog(dlg):
        dlg.open = False
        try:
            page.overlay.remove(dlg)
        except ValueError:
            pass
        page.update()

    def _show_snack(text, color=None):
        snack = ft.SnackBar(
            content=ft.Text(text, color=TEXT_COLOR),
            bgcolor="#333333",
            duration=1500,
        )
        if color:
            snack.content.color = color
        page.overlay.append(snack)
        snack.open = True
        page.update()

    def save_all_tasks():
        tasks = [
            {
                "text": t["text"].value,
                "done": t["checkbox"].value,
                "attachments": t.get("attachments", []),
            }
            for t in tasks_data_list
        ]
        tabs_list[current_tab[0]]["tasks"] = tasks
        saver.save_tasks_deferred({"tabs": tabs_list, "active_tab": current_tab[0]})

    # ── attachment helpers ────────────────────────────────────────────────────

    def open_attachment(attachment):
        try:
            if attachment["type"] == "url":
                webbrowser.open(attachment["url"])
            elif attachment["type"] == "file":
                path = attachment.get("path", "")
                if os.path.exists(path):
                    os.startfile(path)
                else:
                    _show_snack(f"Файл не найден: {attachment.get('name', '')}", "#FF6B6B")
        except Exception:
            pass

    def remove_attachment(task_info, attachment):
        task_info["attachments"].remove(attachment)
        _rebuild_attachment_chips(task_info)
        save_all_tasks()
        page.update()

    def _rebuild_attachment_chips(task_info):
        attachments = task_info.get("attachments", [])
        row = task_info.get("attachments_row")
        container = task_info.get("attachments_container")
        if row is None:
            return

        row.controls.clear()
        for att in attachments:
            is_file = att["type"] == "file"
            icon = ft.Icons.ATTACH_FILE_ROUNDED if is_file else ft.Icons.LINK_ROUNDED
            name = att.get("name") or att.get("url", "Ссылка")
            display = name[:22] + ("…" if len(name) > 22 else "")

            chip = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=11, color="#9B7FF0"),
                        ft.Text(display, size=10, color="#9B7FF0"),
                        ft.GestureDetector(
                            content=ft.Icon(ft.Icons.CLOSE, size=10, color="#666666"),
                            on_tap=lambda e, a=att, ti=task_info: remove_attachment(ti, a),
                        ),
                    ],
                    spacing=3,
                    tight=True,
                ),
                padding=ft.Padding(6, 3, 6, 3),
                margin=ft.Margin(0, 0, 4, 0),
                border_radius=12,
                bgcolor="#2A2040",
                on_click=lambda e, a=att: open_attachment(a),
            )
            row.controls.append(chip)

        if container is not None:
            container.visible = len(attachments) > 0

    def show_attach_dialog(task_info):
        if is_locked[0]:
            return

        url_field = ft.TextField(
            hint_text="https://...",
            hint_style=ft.TextStyle(color="#555555"),
            text_style=ft.TextStyle(color=TEXT_COLOR),
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color="#333333",
            border_radius=8,
            content_padding=10,
        )
        name_field = ft.TextField(
            hint_text="Название (необязательно)",
            hint_style=ft.TextStyle(color="#555555"),
            text_style=ft.TextStyle(color=TEXT_COLOR),
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color="#333333",
            border_radius=8,
            content_padding=10,
        )

        def add_url(e):
            url = url_field.value.strip()
            if not url:
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            label = name_field.value.strip() or url
            task_info["attachments"].append({"type": "url", "name": label, "url": url})
            _rebuild_attachment_chips(task_info)
            save_all_tasks()
            _close_dialog(dlg)

        def pick_file(e):
            _close_dialog(dlg)
            pending_task_info[0] = task_info
            file_picker.pick_files(allow_multiple=True)

        def cancel(e):
            _close_dialog(dlg)

        url_field.on_submit = add_url

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Добавить вложение", color=TEXT_COLOR),
            bgcolor="#252525",
            content=ft.Container(
                width=300,
                content=ft.Column(
                    controls=[
                        ft.ElevatedButton(
                            "Выбрать файл / изображение",
                            icon=ft.Icons.ATTACH_FILE_ROUNDED,
                            on_click=pick_file,
                            style=ft.ButtonStyle(bgcolor="#333333", color=TEXT_COLOR),
                            expand=True,
                        ),
                        ft.Divider(color="#3A3A3A", height=20),
                        ft.Text("Или добавить ссылку:", color="#999999", size=12),
                        url_field,
                        name_field,
                    ],
                    spacing=8,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
                ft.TextButton("Добавить ссылку", on_click=add_url),
            ],
        )

        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # ── opacity / lock ────────────────────────────────────────────────────────

    def apply_locked_style():
        current_opacity = LOCKED_OPACITY if is_locked[0] else opacity_value
        bg = get_bg_color(current_opacity)
        card = get_card_color(current_opacity)
        main_container.current.bgcolor = bg
        input_field.current.fill_color = card
        for task_info in tasks_data_list:
            task_info["container"].bgcolor = card

    last_opacity_update = [0]

    def on_opacity_change(e):
        nonlocal opacity_value
        if is_locked[0]:
            return
        import time
        now = time.time()
        if now - last_opacity_update[0] < 0.1:
            return
        last_opacity_update[0] = now

        opacity_value = round(e.control.value, 1)
        bg = get_bg_color(opacity_value)
        card = get_card_color(opacity_value)
        main_container.current.bgcolor = bg
        input_field.current.fill_color = card
        for task_info in tasks_data_list:
            task_info["container"].bgcolor = card

        settings["opacity"] = opacity_value
        saver.save_settings_deferred(settings.copy())
        page.update()

    def close_app(e):
        if is_locked[0]:
            return
        settings["window_x"] = page.window.left
        settings["window_y"] = page.window.top
        settings["window_width"] = page.window.width
        settings["window_height"] = page.window.height
        saver.flush()

        if TRAY_AVAILABLE and tray_icon[0]:
            app_visible[0] = False
            hwnd_win = get_window_handle("DayPlanner")
            if hwnd_win:
                user32.ShowWindow(hwnd_win, 0)
        else:
            hotkey_thread_running[0] = False
            hwnd_close = get_window_handle("DayPlanner")
            if hwnd_close:
                user32.PostMessageW(hwnd_close, 0x0010, 0, 0)
            os._exit(0)

    def update_ui_state():
        locked = is_locked[0]
        close_button.current.disabled = locked
        close_button.current.icon_color = DISABLED_COLOR if locked else "#666666"
        add_button.current.disabled = locked
        add_button.current.icon_color = DISABLED_COLOR if locked else ACCENT_COLOR
        opacity_slider.current.disabled = locked
        opacity_slider.current.active_color = DISABLED_COLOR if locked else ACCENT_COLOR
        input_field.current.disabled = locked
        input_field.current.hint_style = ft.TextStyle(color=DISABLED_COLOR if locked else "#555555")

        for task_info in tasks_data_list:
            for btn_key in ("checkbox", "delete_btn", "edit_btn", "copy_btn", "attach_btn"):
                ctrl = task_info.get(btn_key)
                if ctrl:
                    ctrl.disabled = locked
            for btn_key in ("delete_btn", "edit_btn", "copy_btn", "attach_btn"):
                ctrl = task_info.get(btn_key)
                if ctrl:
                    ctrl.icon_color = DISABLED_COLOR if locked else "#555555"

    def toggle_lock(e=None):
        is_locked[0] = not is_locked[0]

        if hwnd[0] is None:
            hwnd[0] = get_window_handle("DayPlanner")

        page.window.always_on_top = is_locked[0]
        if hwnd[0]:
            set_click_through(hwnd[0], is_locked[0])

        if is_locked[0]:
            lock_button.current.icon = ft.Icons.LOCK_ROUNDED
            lock_button.current.icon_color = ACCENT_COLOR
            lock_button.current.tooltip = "Ctrl+Shift+L для разблокировки"
        else:
            lock_button.current.icon = ft.Icons.LOCK_OPEN_ROUNDED
            lock_button.current.icon_color = "#666666"
            lock_button.current.tooltip = "Зафиксировать"

        settings["is_locked"] = is_locked[0]
        settings["window_x"] = page.window.left
        settings["window_y"] = page.window.top
        saver.save_settings_deferred(settings.copy())

        update_ui_state()
        apply_locked_style()
        update_header()
        page.update()

    def hotkey_listener():
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_CTRL | MOD_SHIFT, VK_L)
        msg = wintypes.MSG()
        while hotkey_thread_running[0]:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                    page.run_thread(toggle_lock)
            ctypes.windll.kernel32.Sleep(100)
        user32.UnregisterHotKey(None, HOTKEY_ID)

    threading.Thread(target=hotkey_listener, daemon=True).start()

    # ── task CRUD ─────────────────────────────────────────────────────────────

    def on_checkbox_change(e, task_info):
        if is_locked[0]:
            return
        if task_info["checkbox"].value:
            task_info["text"].color = "#666666"
            task_info["text"].style = ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH)
        else:
            task_info["text"].color = TEXT_COLOR
            task_info["text"].style = None
        save_all_tasks()
        page.update()

    def delete_task(task_info):
        if is_locked[0]:
            return
        index = tasks_data_list.index(task_info)
        tasks_column_ref[0].controls.pop(index)
        tasks_data_list.remove(task_info)
        del task_id_map[task_info["id"]]
        save_all_tasks()
        page.update()

    def edit_task(task_info):
        if is_locked[0]:
            return

        edit_field = ft.TextField(
            value=task_info["text"].value,
            text_style=ft.TextStyle(color=TEXT_COLOR),
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color="#333333",
            border_radius=8,
            content_padding=10,
            expand=True,
            autofocus=True,
            multiline=True,
            min_lines=2,
            max_lines=6,
        )

        def save_edit(e):
            new_text = edit_field.value.strip()
            if new_text:
                task_info["text"].value = new_text
                save_all_tasks()
            _close_dialog(dlg)

        def cancel_edit(e):
            _close_dialog(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Редактировать задачу", color=TEXT_COLOR),
            bgcolor="#252525",
            content=ft.Container(width=300, content=edit_field),
            actions=[
                ft.TextButton("Отмена", on_click=cancel_edit),
                ft.TextButton("Сохранить", on_click=save_edit),
            ],
        )

        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def copy_task(task_info):
        if is_locked[0]:
            return
        import subprocess
        process = subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True)
        process.communicate(task_info["text"].value.encode('utf-16-le'))
        _show_snack("Скопировано!")

    # ── drag & drop ───────────────────────────────────────────────────────────

    def reset_all_styles():
        for task_info in tasks_data_list:
            task_info["container"].opacity = 1.0
            task_info["container"].margin = ft.Margin(0, 0, 0, 8)

    def drag_start(task_id):
        if is_locked[0]:
            return
        dragging_task_id[0] = task_id
        task_info = find_task_by_id(task_id)
        if task_info:
            task_info["container"].opacity = 0.3
        page.update()

    def drag_will_accept(e, target_task_id):
        if is_locked[0] or dragging_task_id[0] is None:
            return
        src_task = find_task_by_id(dragging_task_id[0])
        target_task = find_task_by_id(target_task_id)
        if not src_task or not target_task or src_task == target_task:
            return
        try:
            src_index = tasks_data_list.index(src_task)
            target_index = tasks_data_list.index(target_task)
        except ValueError:
            return
        for t in tasks_data_list:
            if t != src_task:
                t["container"].margin = ft.Margin(0, 0, 0, 8)
        if src_index < target_index:
            target_task["container"].margin = ft.Margin(0, 0, 0, 30)
        else:
            target_task["container"].margin = ft.Margin(0, 22, 0, 8)
        page.update()

    def drag_leave(e, target_task_id):
        if is_locked[0] or dragging_task_id[0] is None:
            return
        target_task = find_task_by_id(target_task_id)
        src_task = find_task_by_id(dragging_task_id[0])
        if target_task and target_task != src_task:
            target_task["container"].margin = ft.Margin(0, 0, 0, 8)
        page.update()

    def drag_accept_task(e, target_task_id):
        if is_locked[0] or dragging_task_id[0] is None:
            return
        src_task = find_task_by_id(dragging_task_id[0])
        target_task = find_task_by_id(target_task_id)
        if not src_task or not target_task or src_task == target_task:
            reset_all_styles()
            dragging_task_id[0] = None
            page.update()
            return
        try:
            src_index = tasks_data_list.index(src_task)
            target_index = tasks_data_list.index(target_task)
        except ValueError:
            reset_all_styles()
            dragging_task_id[0] = None
            page.update()
            return
        tasks_data_list.pop(src_index)
        src_ui = tasks_column_ref[0].controls.pop(src_index)
        new_target_index = tasks_data_list.index(target_task)
        insert_index = new_target_index + 1 if src_index < target_index else new_target_index
        tasks_data_list.insert(insert_index, src_task)
        tasks_column_ref[0].controls.insert(insert_index, src_ui)
        save_all_tasks()
        reset_all_styles()
        dragging_task_id[0] = None
        page.update()

    def drag_end(e):
        reset_all_styles()
        dragging_task_id[0] = None
        page.update()

    def move_to_top(e):
        if is_locked[0]:
            return
        try:
            src_id = int(e.data)
        except Exception:
            return
        src_task = find_task_by_id(src_id)
        if not src_task:
            return
        try:
            src_index = tasks_data_list.index(src_task)
        except ValueError:
            return
        if src_index > 0:
            tasks_data_list.pop(src_index)
            src_ui = tasks_column_ref[0].controls.pop(src_index)
            tasks_data_list.insert(0, src_task)
            tasks_column_ref[0].controls.insert(0, src_ui)
            save_all_tasks()
        reset_all_styles()
        dragging_task_id[0] = None
        page.update()

    def move_to_bottom(e):
        if is_locked[0]:
            return
        try:
            src_id = int(e.data)
        except Exception:
            return
        src_task = find_task_by_id(src_id)
        if not src_task:
            return
        try:
            src_index = tasks_data_list.index(src_task)
        except ValueError:
            return
        if src_index < len(tasks_data_list) - 1:
            tasks_data_list.pop(src_index)
            src_ui = tasks_column_ref[0].controls.pop(src_index)
            tasks_data_list.append(src_task)
            tasks_column_ref[0].controls.append(src_ui)
            save_all_tasks()
        reset_all_styles()
        dragging_task_id[0] = None
        page.update()

    # ── task item builder ─────────────────────────────────────────────────────

    def create_task_item(text, is_done=False, attachments=None):
        if attachments is None:
            attachments = []
        current_opacity = LOCKED_OPACITY if is_locked[0] else opacity_value
        text_style = ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if is_done else None
        text_color = "#666666" if is_done else TEXT_COLOR

        task_id = task_id_counter[0]
        task_id_counter[0] += 1

        task_info = {"id": task_id, "attachments": list(attachments)}

        checkbox = ft.Checkbox(
            value=is_done,
            active_color=ACCENT_COLOR,
            check_color=TEXT_COLOR,
            disabled=is_locked[0],
        )
        checkbox.on_change = lambda e: on_checkbox_change(e, task_info)

        text_control = ft.Text(
            text, color=text_color, size=13,
            weight=ft.FontWeight.W_500, style=text_style,
            expand=True,
        )

        edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT_OUTLINED, icon_size=15,
            icon_color=DISABLED_COLOR if is_locked[0] else "#555555",
            tooltip="Редактировать", disabled=is_locked[0],
            on_click=lambda e, ti=task_info: edit_task(ti),
            style=ft.ButtonStyle(padding=2),
        )
        copy_btn = ft.IconButton(
            icon=ft.Icons.COPY_OUTLINED, icon_size=15,
            icon_color=DISABLED_COLOR if is_locked[0] else "#555555",
            tooltip="Копировать", disabled=is_locked[0],
            on_click=lambda e, ti=task_info: copy_task(ti),
            style=ft.ButtonStyle(padding=2),
        )
        attach_btn = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE_ROUNDED, icon_size=15,
            icon_color=DISABLED_COLOR if is_locked[0] else "#555555",
            tooltip="Вложение", disabled=is_locked[0],
            on_click=lambda e, ti=task_info: show_attach_dialog(ti),
            style=ft.ButtonStyle(padding=2),
        )
        delete_btn = ft.IconButton(
            icon=ft.Icons.CLOSE_ROUNDED, icon_size=15,
            icon_color=DISABLED_COLOR if is_locked[0] else "#555555",
            tooltip="Удалить", disabled=is_locked[0],
            on_click=lambda e, ti=task_info: delete_task(ti),
            style=ft.ButtonStyle(padding=2),
        )

        buttons = ft.Column(
            controls=[edit_btn, copy_btn, attach_btn, delete_btn],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        main_row = ft.Row(
            controls=[
                ft.Icon(ft.Icons.DRAG_INDICATOR_ROUNDED, color="#3A3A3A", size=16),
                checkbox,
                text_control,
                buttons,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Attachment chips row
        attachments_row = ft.Row(controls=[], spacing=0, scroll=ft.ScrollMode.AUTO, wrap=False)
        task_info["attachments_row"] = attachments_row

        attachments_container = ft.Container(
            content=attachments_row,
            padding=ft.Padding(36, 0, 4, 4),
            visible=len(attachments) > 0,
        )
        task_info["attachments_container"] = attachments_container

        # Build initial chips
        _rebuild_attachment_chips(task_info)

        card_content = ft.Column(
            controls=[main_row, attachments_container],
            spacing=0,
            tight=True,
        )

        card = ft.Container(
            margin=ft.Margin(0, 0, 0, 6),
            padding=ft.Padding(8, 8, 4, 8),
            border_radius=12,
            bgcolor=get_card_color(current_opacity),
            border=ft.Border(
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
            ),
            opacity=1.0,
            content=card_content,
        )

        task_info.update({
            "checkbox": checkbox,
            "text": text_control,
            "edit_btn": edit_btn,
            "copy_btn": copy_btn,
            "attach_btn": attach_btn,
            "delete_btn": delete_btn,
            "container": card,
        })

        tasks_data_list.append(task_info)
        task_id_map[task_id] = task_info

        feedback = ft.Container(
            width=280,
            padding=ft.Padding(8, 8, 8, 8),
            border_radius=12,
            bgcolor=get_card_color(current_opacity),
            border=ft.Border(
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
                ft.BorderSide(1, "#2A2A2A"),
            ),
            scale=1.02,
            shadow=ft.BoxShadow(blur_radius=8, color="#22000000"),
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.DRAG_INDICATOR_ROUNDED, color="#3A3A3A", size=16),
                    ft.Checkbox(value=is_done, active_color=ACCENT_COLOR, check_color=TEXT_COLOR, disabled=True),
                    ft.Text(
                        text[:40] + ("…" if len(text) > 40 else ""),
                        color=text_color, size=13,
                        weight=ft.FontWeight.W_500, style=text_style,
                    ),
                ],
                spacing=0,
            )
        )

        draggable = ft.Draggable(
            group="tasks",
            content=card,
            content_feedback=feedback,
            data=str(task_id),
            on_drag_start=lambda e: drag_start(task_id),
            on_drag_complete=drag_end,
        )

        return ft.DragTarget(
            group="tasks",
            content=draggable,
            on_will_accept=lambda e: drag_will_accept(e, task_id),
            on_leave=lambda e: drag_leave(e, task_id),
            on_accept=lambda e: drag_accept_task(e, task_id),
        )

    def add_task(e):
        if is_locked[0]:
            return
        task_text = input_field.current.value.strip()
        if not task_text:
            return
        new_task = create_task_item(task_text, False)
        tasks_column_ref[0].controls.append(new_task)
        input_field.current.value = ""
        save_all_tasks()
        page.update()

    # ── tabs ──────────────────────────────────────────────────────────────────

    def _load_tab_tasks(index):
        tasks_data_list.clear()
        task_id_map.clear()
        tasks_column_ref[0].controls.clear()
        for task in tabs_list[index].get("tasks", []):
            task_item = create_task_item(
                task.get("text", ""),
                task.get("done", False),
                task.get("attachments", []),
            )
            tasks_column_ref[0].controls.append(task_item)

    def _save_current_tab_tasks():
        tabs_list[current_tab[0]]["tasks"] = [
            {
                "text": t["text"].value,
                "done": t["checkbox"].value,
                "attachments": t.get("attachments", []),
            }
            for t in tasks_data_list
        ]

    def switch_tab(index):
        if is_locked[0]:
            return
        _save_current_tab_tasks()
        current_tab[0] = index
        _load_tab_tasks(index)
        save_all_tasks()
        rebuild_tabs()
        page.update()

    def add_tab(e):
        if is_locked[0]:
            return

        name_field = ft.TextField(
            hint_text="Название вкладки...",
            text_style=ft.TextStyle(color=TEXT_COLOR),
            border=ft.InputBorder.NONE,
            filled=True,
            fill_color="#333333",
            border_radius=8,
            content_padding=10,
            autofocus=True,
        )

        def create_tab(e):
            name = name_field.value.strip()
            if name:
                tabs_list.append({"name": name, "tasks": []})
                save_all_tasks()
                rebuild_tabs()
            _close_dialog(dlg)

        def cancel(e):
            _close_dialog(dlg)

        name_field.on_submit = create_tab

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Новая вкладка", color=TEXT_COLOR),
            bgcolor="#252525",
            content=ft.Container(width=250, content=name_field),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
                ft.TextButton("Создать", on_click=create_tab),
            ],
        )

        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def delete_tab(index):
        if is_locked[0] or len(tabs_list) <= 1:
            return

        def confirm_delete(e):
            if current_tab[0] != index:
                _save_current_tab_tasks()

            tabs_list.pop(index)

            if current_tab[0] == index:
                new_index = min(index, len(tabs_list) - 1)
                current_tab[0] = new_index
                _load_tab_tasks(new_index)
            elif current_tab[0] > index:
                current_tab[0] -= 1

            saver.save_tasks_deferred({"tabs": tabs_list, "active_tab": current_tab[0]})
            rebuild_tabs()
            _close_dialog(dlg)

        def cancel(e):
            _close_dialog(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Удалить вкладку?", color=TEXT_COLOR),
            bgcolor="#252525",
            content=ft.Text(
                f'Удалить "{tabs_list[index]["name"]}" и все её задачи?',
                color="#999999",
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
                ft.TextButton("Удалить", on_click=confirm_delete),
            ],
        )

        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def rebuild_tabs():
        tabs_row_ref[0].controls.clear()

        for i, tab in enumerate(tabs_list):
            is_active = i == current_tab[0]
            tab_btn = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Text(
                            tab["name"][:10] + ("…" if len(tab["name"]) > 10 else ""),
                            size=11,
                            color=TEXT_COLOR if is_active else "#666666",
                            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_400,
                        ),
                        ft.GestureDetector(
                            content=ft.Icon(
                                ft.Icons.CLOSE, size=12,
                                color="#666666" if not is_locked[0] and len(tabs_list) > 1 else "#333333",
                            ),
                            on_tap=lambda e, idx=i: delete_tab(idx) if len(tabs_list) > 1 else None,
                        ) if not is_locked[0] else ft.Container(),
                    ],
                    spacing=4,
                ),
                padding=ft.Padding(10, 6, 6, 6),
                border_radius=8,
                bgcolor=ACCENT_COLOR if is_active else "#2A2A2A",
                on_click=lambda e, idx=i: switch_tab(idx),
            )
            tabs_row_ref[0].controls.append(tab_btn)

        if not is_locked[0]:
            tabs_row_ref[0].controls.append(ft.Container(
                content=ft.Icon(ft.Icons.ADD, size=16, color="#666666"),
                padding=ft.Padding(8, 6, 8, 6),
                border_radius=8,
                bgcolor="#2A2A2A",
                on_click=add_tab,
            ))

    # ── header ────────────────────────────────────────────────────────────────

    def create_header_content():
        return ft.Container(
            padding=ft.Padding(25, 15, 25, 10),
            content=ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(width=8, height=8, border_radius=4, bgcolor=ACCENT_COLOR),
                            ft.Text("DayPlanner", size=18, weight=ft.FontWeight.BOLD, color=TEXT_COLOR),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                ref=lock_button,
                                icon=ft.Icons.LOCK_ROUNDED if is_locked[0] else ft.Icons.LOCK_OPEN_ROUNDED,
                                icon_size=18,
                                icon_color=ACCENT_COLOR if is_locked[0] else "#666666",
                                on_click=toggle_lock,
                                tooltip="Ctrl+Shift+L",
                            ),
                            ft.IconButton(
                                ref=close_button,
                                icon=ft.Icons.CLOSE_ROUNDED,
                                icon_size=18,
                                icon_color=DISABLED_COLOR if is_locked[0] else "#666666",
                                disabled=is_locked[0],
                                on_click=close_app,
                                tooltip="Свернуть в трей",
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
        )

    def update_header():
        header_content = create_header_content()
        header_drop.content = (
            ft.Container(content=header_content) if is_locked[0]
            else ft.WindowDragArea(content=header_content)
        )
        rebuild_tabs()

    # ── layout assembly ───────────────────────────────────────────────────────

    header_content = create_header_content()
    header_drop = ft.DragTarget(
        group="tasks",
        content=ft.WindowDragArea(content=header_content),
        on_accept=move_to_top,
    )

    current_opacity_val = opacity_value

    tabs_row = ft.Row(controls=[], spacing=6, scroll=ft.ScrollMode.AUTO)
    tabs_row_ref[0] = tabs_row
    rebuild_tabs()

    tabs_container = ft.Container(
        padding=ft.Padding(25, 0, 25, 10),
        content=tabs_row,
    )

    slider_drop = ft.DragTarget(
        group="tasks",
        content=ft.Container(
            padding=ft.Padding(25, 5, 25, 5),
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.BLUR_ON, color="#666666", size=16),
                    ft.Slider(
                        ref=opacity_slider,
                        min=0.3, max=1.0, value=opacity_value,
                        active_color=ACCENT_COLOR,
                        inactive_color="#333333",
                        on_change=on_opacity_change,
                        expand=True,
                    ),
                ],
                spacing=10,
            )
        ),
        on_accept=move_to_top,
    )

    input_field_control = ft.TextField(
        ref=input_field,
        hint_text="Новая задача...",
        hint_style=ft.TextStyle(color="#555555"),
        text_style=ft.TextStyle(color=TEXT_COLOR),
        border=ft.InputBorder.NONE,
        filled=True,
        fill_color=get_card_color(current_opacity_val),
        border_radius=16,
        content_padding=15,
        on_submit=add_task,
    )

    input_drop = ft.DragTarget(
        group="tasks",
        content=ft.Container(
            padding=ft.Padding(25, 10, 15, 10),
            content=ft.Row(
                controls=[
                    ft.Container(content=input_field_control, expand=True),
                    ft.IconButton(
                        ref=add_button,
                        icon=ft.Icons.ADD_ROUNDED,
                        icon_size=22,
                        icon_color=ACCENT_COLOR,
                        tooltip="Добавить",
                        on_click=add_task,
                    ),
                ],
                spacing=5,
            )
        ),
        on_accept=move_to_bottom,
    )

    hint_drop = ft.DragTarget(
        group="tasks",
        content=ft.Container(
            padding=ft.Padding(0, 0, 0, 15),
            content=ft.Row(
                controls=[
                    ft.Text("Ctrl+Shift+L", size=10, color="#555555", weight=ft.FontWeight.W_500),
                    ft.Text(" — режим замка", size=10, color="#444444"),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=0,
            )
        ),
        on_accept=move_to_bottom,
    )

    tasks_column = ft.Column(spacing=0, controls=[])
    tasks_column_ref[0] = tasks_column

    _load_tab_tasks(current_tab[0])

    bottom_space_drop = ft.DragTarget(
        group="tasks",
        content=ft.Container(height=300, bgcolor=ft.Colors.TRANSPARENT),
        on_accept=move_to_bottom,
    )

    tasks_list = ft.Container(
        expand=True,
        padding=ft.Padding(25, 0, 25, 0),
        content=ft.Column(
            controls=[tasks_column, bottom_space_drop],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
    )

    ui_column = ft.Column(
        spacing=0, expand=True,
        controls=[header_drop, tabs_container, slider_drop, tasks_list, input_drop, hint_drop],
    )

    main_layout = ft.Container(
        ref=main_container,
        expand=True,
        bgcolor=get_bg_color(current_opacity_val),
        border_radius=24,
        border=ft.Border(
            ft.BorderSide(1, "#3A3A3A"),
            ft.BorderSide(1, "#3A3A3A"),
            ft.BorderSide(1, "#3A3A3A"),
            ft.BorderSide(1, "#3A3A3A"),
        ),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ui_column,
    )

    page.add(main_layout)


if __name__ == "__main__":
    ft.run(main)
