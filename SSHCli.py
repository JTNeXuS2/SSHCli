#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import threading
import paramiko
import tkinter as tk
import webbrowser

import hashlib
import base64

from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path

# ----------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------
SAVED_FILE   = "save.json"           # сохранённые соединения
HISTORY_FILE = "history.txt"         # история команд

# ----------------------------------------------------------------------
# Функции шифрования/дешифрования (простое XOR шифрование)
# ----------------------------------------------------------------------
def get_key():
    """Получаем ключ шифрования из переменной окружения или используем фиксированный"""
    # ВНИМАНИЕ: Для реального использования лучше установить переменную окружения
    # export SSH_CLIENT_KEY="ваш_секретный_ключ"
    env_key = os.environ.get('SSH_CLIENT_KEY')
    if env_key:
        # Используем SHA-256 от переменной окружения как ключ
        return hashlib.sha256(env_key.encode()).digest()
    else:
        # Фиксированный ключ для демонстрации (небезопасно для продакшена!)
        return b'MySuperSecretKey'

def encrypt_password(password):
    """Шифрует пароль с помощью XOR + base64"""
    if not password:
        return ""
    
    key = get_key()
    # Преобразуем пароль в байты
    password_bytes = password.encode('utf-8')
    
    # XOR шифрование с циклическим повторением ключа
    encrypted_bytes = bytearray()
    key_length = len(key)
    
    for i, byte in enumerate(password_bytes):
        encrypted_bytes.append(byte ^ key[i % key_length])
    
    # Кодируем в base64 для безопасного хранения
    return base64.b64encode(encrypted_bytes).decode('ascii')

def decrypt_password(encrypted_data):
    """Дешифрует пароль"""
    if not encrypted_data:
        return ""
    
    try:
        key = get_key()
        # Декодируем из base64
        encrypted_bytes = base64.b64decode(encrypted_data)
        
        # XOR дешифрование
        decrypted_bytes = bytearray()
        key_length = len(key)
        
        for i, byte in enumerate(encrypted_bytes):
            decrypted_bytes.append(byte ^ key[i % key_length])
        
        return decrypted_bytes.decode('utf-8')
    except Exception:
        # Если не удалось расшифровать, возвращаем как есть (для обратной совместимости)
        return encrypted_data

def is_encrypted(password_str):
    """Проверяет, зашифрован ли пароль (эвристика)"""
    if not password_str:
        return False
    
    # Проверяем, что строка выглядит как base64 (только ASCII символы)
    try:
        # Если это валидный base64 и не содержит русских букв
        if all(ord(c) < 128 for c in password_str):
            # Пробуем декодировать как base64
            decoded = base64.b64decode(password_str)
            # Если декодировалось успешно, вероятно это зашифрованный пароль
            return True
    except Exception:
        pass
    
    return False

# ----------------------------------------------------------------------
# SSH helper (оставьте как есть)
# ----------------------------------------------------------------------
def ssh_execute(host, port, username, password, command, output_callback):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=host, port=port,
                       username=username, password=password, timeout=10)

        stdin, stdout, stderr = client.exec_command(command)
        for line in stdout:
            output_callback(line.rstrip("\n"))
        for line in stderr:
            output_callback("[ERR] " + line.rstrip("\n"))

        client.close()
    except Exception as e:
        output_callback("[EXCEPTION] " + str(e))

def download_file(host, port, username, password,
                  remote_path, local_path, output_callback):
    try:
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        sftp.get(remote_path, local_path)
        output_callback(f"[INFO] Файл успешно скачан: {remote_path} → {local_path}")

        sftp.close()
        transport.close()
    except Exception as e:
        output_callback(f"[ERROR] Не удалось скачать файл: {e}")

# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class SSHGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSH Client by ⎛⎝illidan⎠⎞")
        self.geometry("850x750")
        self.minsize(600, 400)
        self.resizable(True, True)

        # Основной контейнер
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # row/column weights для основного контейнера
        main_container.rowconfigure(0, weight=1)
        main_container.columnconfigure(0, weight=1)

        # Фрейм для всего содержимого (кроме нижней ссылки)
        content_frame = ttk.Frame(main_container)
        content_frame.grid(row=0, column=0, sticky="nsew")

        # row/column weights для content_frame
        for i in range(4):
            content_frame.rowconfigure(i, weight=0)
        content_frame.rowconfigure(4, weight=1)          # output expands
        content_frame.columnconfigure(0, weight=1)

        # UI sections
        self._create_conn_frame(content_frame)
        self._create_btn_frame(content_frame)
        self._create_custom_frame(content_frame)
        self._create_download_frame(content_frame)
        self._create_output_frame(content_frame)

        # Нижняя панель со ссылкой
        self._create_bottom_link(main_container)

        # Load saved connections and history
        self._load_saved_combos()
        self._load_history()

    # ------------------------------------------------------------------
    # Новая функция для создания ссылки внизу
    # ------------------------------------------------------------------
    def _create_bottom_link(self, parent):
        bottom_frame = ttk.Frame(parent)
        bottom_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        bottom_frame.columnconfigure(0, weight=1)

        # Создаем метку с ссылкой
        link_label = tk.Label(
            bottom_frame,
            text="Source github.com/JTNeXuS2",
            fg="blue",
            cursor="hand2",
            font=("Arial", 8, "underline")
        )
        link_label.grid(row=0, column=0, sticky="e")

        # Привязываем события
        link_label.bind("<Button-1>", lambda e: self._open_browser())
        link_label.bind("<Enter>", lambda e: link_label.configure(fg="red"))
        link_label.bind("<Leave>", lambda e: link_label.configure(fg="blue"))

    def _open_browser(self):
        """Открывает ссылку в браузере"""
        webbrowser.open("https://github.com/JTNeXuS2/SSHCli")

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_conn_frame(self, parent):
        conn_frame = ttk.LabelFrame(parent, text="Параметры подключения")
        conn_frame.grid(row=0, column=0, sticky="ew", pady=5)

        # column weights
        conn_frame.columnconfigure(0, weight=0)
        conn_frame.columnconfigure(1, weight=1)
        conn_frame.columnconfigure(2, weight=0)
        conn_frame.columnconfigure(3, weight=1)
        conn_frame.columnconfigure(4, weight=0, minsize=80)
        conn_frame.columnconfigure(5, weight=0, minsize=80)

        # IP / hostname
        ttk.Label(conn_frame, text="IP / hostname:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.entry_host = ttk.Entry(conn_frame, width=30)
        self.entry_host.grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        # Port
        ttk.Label(conn_frame, text="Порт (по умолчанию 22):").grid(row=0, column=2, sticky="e", padx=5, pady=2)
        self.entry_port = ttk.Entry(conn_frame, width=10)
        self.entry_port.insert(0, "22")
        self.entry_port.grid(row=0, column=3, sticky="w", padx=5, pady=2)

        # Login
        ttk.Label(conn_frame, text="Логин (по умолчанию root):").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.entry_user = ttk.Entry(conn_frame, width=30)
        self.entry_user.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        # Password
        ttk.Label(conn_frame, text="Пароль:").grid(row=1, column=2, sticky="e", padx=5, pady=2)
        self.entry_pass = ttk.Entry(conn_frame, width=30, show="*")
        self.entry_pass.grid(row=1, column=3, sticky="ew", padx=5, pady=2)

        # Saved connections combobox
        ttk.Label(conn_frame, text="Сохранённые:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        self.combo_var = tk.StringVar()
        self.combo_box = ttk.Combobox(conn_frame, textvariable=self.combo_var, state="readonly")
        self.combo_box.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=2)
        self.combo_box.bind("<<ComboboxSelected>>", self._on_combo_selected)

        # Save / Delete buttons
        button_frame = ttk.Frame(conn_frame)
        button_frame.grid(row=2, column=4, columnspan=2, sticky="e", padx=5, pady=2)

        self.btn_delete = ttk.Button(button_frame, text="Удалить", command=self._delete_selected_combo)
        self.btn_delete.pack(side="right")
        self.btn_save = ttk.Button(button_frame, text="Сохранить", command=self._save_current_combo)
        self.btn_save.pack(side="right", padx=(0, 5))

    def _create_btn_frame(self, parent):
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=5)

        btn_frame.columnconfigure(0, weight=0)
        btn_frame.columnconfigure(1, weight=0)

        self.btn_1 = ttk.Button(btn_frame, text="Run Help", command=lambda: self._insert_command("help"))
        self.btn_1.grid(row=0, column=0, sticky="w", padx=5)

        self.btn_2 = ttk.Button(btn_frame, text="Show path", command=lambda: self._insert_command("pwd"))
        self.btn_2.grid(row=0, column=1, sticky="w", padx=5)

        self.btn_3 = ttk.Button(btn_frame, text="Удалить файлы", command=lambda: self._insert_command("rm -f /var/log/test_logs/*"))
        self.btn_3.grid(row=0, column=2, sticky="w", padx=5)

        self.btn_4 = ttk.Button(btn_frame, text="Удалить полностью каталог ", command=lambda: self._insert_command("rm -rf /var/log/test_logs"))
        self.btn_4.grid(row=0, column=3, sticky="w", padx=5)

        self.btn_99 = ttk.Button(btn_frame, text="Справка", command=self.infos)
        self.btn_99.grid(row=1, column=0, sticky="w", padx=5)


    def _insert_command(self, command):
        """Вставляет команду в поле произвольной команды"""
        self.entry_custom_var.set(command)
        # Опционально: устанавливаем фокус на поле ввода
        self.entry_custom.focus_set()
        self.entry_custom.icursor(tk.END)

    # ------------------------------------------------------------------
    # UI – произвольная команда (добавлена кнопка «Удалить»)
    # ------------------------------------------------------------------
    def _create_custom_frame(self, parent):
        custom_frame = ttk.LabelFrame(parent, text="Произвольная команда")
        custom_frame.grid(row=2, column=0, sticky="ew", pady=5)

        custom_frame.columnconfigure(0, weight=1)
        custom_frame.columnconfigure(1, weight=0)
        custom_frame.columnconfigure(2, weight=0)   # новая колонка для кнопки Delete

        # Combobox для истории
        self.entry_custom_var = tk.StringVar()
        self.entry_custom = ttk.Combobox(custom_frame,
                                        textvariable=self.entry_custom_var,
                                        state="normal", width=60)
        self.entry_custom.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

        # Bind selection to just place the selected command in the combobox
        self.entry_custom.bind("<<ComboboxSelected>>",
                               lambda e: self._on_history_selected())

        # Run button
        self.btn_custom = ttk.Button(custom_frame,
                                     text="Выполнить", command=self.run_custom)
        self.btn_custom.grid(row=0, column=1, sticky="w", padx=5)

        # Delete button – новая кнопка
        self.btn_delete_history = ttk.Button(custom_frame,
                                            text="Удалить",
                                            command=self._delete_history_command)
        self.btn_delete_history.grid(row=0, column=2, sticky="w", padx=5)

    def _on_history_selected(self):
        # The combobox already contains the selected command
        pass

    # ------------------------------------------------------------------
    # UI – скачивание файла
    # ------------------------------------------------------------------
    def _create_download_frame(self, parent):
        download_frame = ttk.LabelFrame(parent, text="Скачивание файла")
        download_frame.grid(row=3, column=0, sticky="nsew", pady=5)

        download_frame.rowconfigure(0, weight=0)
        download_frame.rowconfigure(1, weight=0)
        download_frame.rowconfigure(2, weight=0)
        download_frame.columnconfigure(0, weight=0)
        download_frame.columnconfigure(1, weight=1)
        download_frame.columnconfigure(2, weight=0)

        # Remote Path
        ttk.Label(download_frame, text="Remote Path:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.entry_remote = ttk.Entry(download_frame, width=30)
        self.entry_remote.grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        # Local Path (read‑only)
        ttk.Label(download_frame, text="Local Path:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.entry_local = ttk.Entry(download_frame, width=30, state="readonly")
        self.entry_local.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        # Download button
        self.btn_download = ttk.Button(download_frame, text="Download", command=self._download_file)
        self.btn_download.grid(row=2, column=1, sticky="e", padx=5, pady=5)

    # ------------------------------------------------------------------
    # UI – вывод
    # ------------------------------------------------------------------
    def _create_output_frame(self, parent):
        output_frame = ttk.LabelFrame(parent, text="Результат")
        output_frame.grid(row=4, column=0, sticky="nsew", pady=5)

        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)

        self.text_output = scrolledtext.ScrolledText(output_frame, wrap="word", state="disabled")
        self.text_output.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    # ------------------------------------------------------------------
    # Combo handling (сохраняем/удаляем соединения)
    # ------------------------------------------------------------------
    def _load_saved_combos(self):
        if not os.path.exists(SAVED_FILE):
            self.saved_combos = {}
            return
        try:
            with open(SAVED_FILE, "r", encoding="utf-8") as f:
                self.saved_combos = json.load(f)
        except Exception:
            self.saved_combos = {}
            messagebox.showwarning("Ошибка",
                                   "Не удалось загрузить сохранённые соединения.")
        self._refresh_combo_box()

    def _refresh_combo_box(self):
        names = [f"{c['host']}:{c['port']} ({c['user']})"
                 for c in self.saved_combos.values()]
        self.combo_box['values'] = names
        self.combo_var.set('')

    def _on_combo_selected(self, event):
        index = self.combo_box.current()
        if index == -1:
            return
        key = list(self.saved_combos.keys())[index]
        combo = self.saved_combos[key]
        self.entry_host.delete(0, tk.END)
        self.entry_host.insert(0, combo['host'])
        self.entry_port.delete(0, tk.END)
        self.entry_port.insert(0, str(combo['port']))
        self.entry_user.delete(0, tk.END)
        self.entry_user.insert(0, combo['user'])
        
        # Очищаем поле пароля
        self.entry_pass.delete(0, tk.END)
        
        # Определяем, зашифрован пароль или нет
        password = combo['password']
        
        # Проверяем, не зашифрован ли уже пароль
        if password and is_encrypted(password):
            # Пароль зашифрован - расшифровываем
            decrypted = decrypt_password(password)
            self.entry_pass.insert(0, decrypted)
        else:
            # Пароль не зашифрован (обычный текст) - используем как есть
            self.entry_pass.insert(0, password)

    def _save_current_combo(self):
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        user = self.entry_user.get().strip()
        password = self.entry_pass.get()

        if not host or not user or not password:
            messagebox.showerror("Ошибка", "Пожалуйста, заполните все поля подключения.")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.")
            return

        key = f"{host}:{port}:{user}"
        
        # Шифруем пароль перед сохранением
        encrypted_password = encrypt_password(password)
        
        self.saved_combos[key] = {
            "host": host,
            "port": port,
            "user": user,
            "password": encrypted_password
        }

        try:
            with open(SAVED_FILE, "w", encoding="utf-8") as f:
                json.dump(self.saved_combos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить соединение: {e}")
            return

        messagebox.showinfo("Успех", "Соединение сохранено (пароль зашифрован).")
        self._refresh_combo_box()

    def _delete_selected_combo(self):
        index = self.combo_box.current()
        if index == -1:
            messagebox.showwarning("Предупреждение", "Ничего не выбрано.")
            return

        key = list(self.saved_combos.keys())[index]
        del self.saved_combos[key]

        try:
            with open(SAVED_FILE, "w", encoding="utf-8") as f:
                json.dump(self.saved_combos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить соединение: {e}")
            return

        messagebox.showinfo("Успех", "Соединение удалено.")
        self._refresh_combo_box()

    def infos(self):
        messagebox.showinfo("Информация", 
            "pwd — показать текущую папку (путь)\n"
            "ls — список файлов в текущей папке (ls -la — показать все, включая скрытые)\n"
            "cd [путь] — перейти в папку (cd .. — на уровень выше, cd ~ — в домашнюю папку)\n"
            "mkdir [имя] — создать новую папку\n"
            "touch [файл] — создать пустой файл\n"
            "rm [файл] — удалить файл (rm -rf [папка] — удалить папку со всем содержимым)\n"
            "cp [источник] [цель] — копировать файл\n"
            "mv [источник] [цель] — переместить или переименовать файл\n"
            "df -h — свободное место на дисках.\n"
            "cat [файл] — вывести содержимое файла на экран\n"
            "nano [файл] или vi [файл] — популярные текстовые редакторы\n"
            "grep [текст] [файл] — поиск строки в файле"
        )

    # ------------------------------------------------------------------
    # NEW: History load/save
    # ------------------------------------------------------------------
    def _load_history(self):
        """Загружаем историю из HISTORY_FILE и заполняем combobox."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = [line.rstrip("\n")
                                    for line in f if line.strip()]
            except Exception as e:
                messagebox.showwarning("История",
                                       f"Не удалось загрузить историю: {e}")
        else:
            self.history = []

        # обновляем выпадающий список
        self.entry_custom['values'] = self.history

    def _save_history(self, command):
        """Добавляем команду в начало списка и сохраняем до 200 строк."""
        cmd = command.strip()
        if not cmd:
            return
        if cmd in self.history:
            self.history.remove(cmd)
        self.history.insert(0, cmd)

        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                for c in self.history[:200]:
                    f.write(c + "\n")
        except Exception as e:
            messagebox.showwarning("История",
                                   f"Не удалось сохранить историю: {e}")

        # **Важно** – обновляем значения combobox, чтобы новое
        #        отображалось в выпадающем списке
        self.entry_custom['values'] = self.history
    # ----------------------------------------------------------------------
    # Метод удаления выбранной команды из истории
    # ----------------------------------------------------------------------
    def _delete_history_command(self):
        """Удаляет команду, выбранную в Combobox, из истории."""
        command = self.entry_custom.get().strip()
        if not command:
            messagebox.showwarning("Внимание", "Нечего удалять – выберите команду из истории.")
            return

        if command not in self.history:
            messagebox.showinfo("Информация", "Команда уже отсутствует в истории.")
            return

        # Удаляем из списка и сохраняем
        self.history.remove(command)
        self._save_history_to_file()
        # Обновляем значения combobox
        self.entry_custom['values'] = self.history
        # Очищаем поле ввода
        self.entry_custom_var.set('')

    # ----------------------------------------------------------------------
    # Вспомогательный метод, сохраняющий историю в файл (используется и при удалении)
    # ----------------------------------------------------------------------
    def _save_history_to_file(self):
        """Записывает первые 200 строк истории в HISTORY_FILE."""
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                for c in self.history[:200]:
                    f.write(c + "\n")
        except Exception as e:
            messagebox.showwarning("История",
                                   f"Не удалось сохранить историю: {e}")

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def get_connection_params(self):
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        port = int(port_str) if port_str.isdigit() else 22
        user = self.entry_user.get().strip()
        password = self.entry_pass.get()

        if not host or not user or not password:
            messagebox.showerror("Ошибка", "Пожалуйста, заполните поля подключения.")
            return None
        return host, port, user, password

    def append_output(self, text):
        self.text_output.configure(state="normal")
        self.text_output.insert("end", text + "\n")
        self.text_output.see("end")
        self.text_output.configure(state="disabled")

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------
    # УДАЛЕНЫ старые методы run_help и run_pwd, так как они больше не используются
    
    def run_custom(self):
        command = self.entry_custom.get().strip()
        if not command:
            messagebox.showwarning("Внимание", "Введите команду.")
            return
        # Сохраняем в историю
        self._save_history(command)

        params = self.get_connection_params()
        if not params:
            return

        self.append_output(f"=== Выполняется: {command}")
        threading.Thread(target=ssh_execute,
                         args=(*params, command, self.append_output),
                         daemon=True).start()

    # ------------------------------------------------------------------
    # Download functionality
    # ------------------------------------------------------------------
    def _local_path_for_remote(self, remote_path):
        rel_path = remote_path.lstrip('/')
        downloads_dir = Path.cwd() / "Downloads"
        local_path = downloads_dir / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        return local_path

    def _download_file(self):
        remote_path = self.entry_remote.get().strip()
        if not remote_path:
            messagebox.showerror("Ошибка", "Пожалуйста, укажите путь к файлу на сервере.")
            return
        params = self.get_connection_params()
        if not params:
            return

        local_path = self._local_path_for_remote(remote_path)
        self.entry_local.config(state="normal")
        self.entry_local.delete(0, tk.END)
        self.entry_local.insert(0, str(local_path))
        self.entry_local.config(state="readonly")

        self.append_output(f"[INFO] Начинается скачивание: {remote_path} → {local_path}")
        threading.Thread(target=download_file,
                         args=(*params, remote_path, str(local_path), self.append_output),
                         daemon=True).start()

# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = SSHGUI()
    app.mainloop()
