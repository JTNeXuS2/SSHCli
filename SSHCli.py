#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import threading
import paramiko
import tkinter as tk
import webbrowser
import time

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
# Класс для управления постоянным SSH-соединением
# ----------------------------------------------------------------------
class SSHConnection:
    def __init__(self):
        self.client = None
        self.sftp = None
        self.current_path = None
        self.host = None
        self.port = None
        self.username = None
        self.password = None
        self.lock = threading.Lock()
        self.connecting = False
        self.connected = False
    
    def is_connected(self):
        """Проверяет, активно ли соединение"""
        if self.client and self.client.get_transport() and self.client.get_transport().is_active():
            return True
        return False
    
    def connect(self, host, port, username, password, output_callback, status_callback=None):
        """Устанавливает соединение, если его нет (выполняется в потоке)"""
        with self.lock:
            if self.connecting:
                output_callback("[INFO] Уже выполняется подключение...")
                return False
            
            self.connecting = True
        
        try:
            # Если уже подключены к тому же серверу, ничего не делаем
            if self.is_connected() and self.host == host and self.port == port and self.username == username:
                output_callback("[INFO] Использую существующее соединение")
                with self.lock:
                    self.connecting = False
                if status_callback:
                    status_callback(True)
                return True
            
            # Закрываем старое соединение, если есть
            self.close()
            
            output_callback(f"[INFO] Устанавливаю новое соединение с {host}:{port}")
            
            # Создаём клиент
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Подключаемся
            client.connect(hostname=host, port=port,
                          username=username, password=password, timeout=10)
            
            # Получаем текущую директорию после подключения
            stdin, stdout, stderr = client.exec_command('pwd')
            current_path = stdout.read().decode().strip()
            
            with self.lock:
                self.client = client
                self.current_path = current_path
                self.host = host
                self.port = port
                self.username = username
                self.password = password
                self.connecting = False
                self.connected = True
            
            output_callback(f"[INFO] Соединение установлено. Текущая директория: {current_path}")
            
            if status_callback:
                status_callback(True)
            
            return True
            
        except Exception as e:
            output_callback(f"[ERROR] Не удалось подключиться: {e}")
            with self.lock:
                self.client = None
                self.connecting = False
                self.connected = False
            
            if status_callback:
                status_callback(False)
            
            return False
    
    def execute(self, command, output_callback):
        """Выполняет команду в существующем соединении"""
        with self.lock:
            if not self.is_connected():
                output_callback("[ERROR] Соединение не установлено или разорвано")
                return False
            
            client = self.client
            current_path = self.current_path
        
        try:
            # Для команд cd нужно обрабатывать особым образом
            if command.strip().startswith('cd '):
                return self._change_directory(command, output_callback)
            
            # Выполняем команду в текущей директории
            full_command = f"cd {current_path} && {command}"
            stdin, stdout, stderr = client.exec_command(full_command)
            
            # Читаем stdout
            for line in stdout:
                output_callback(line.rstrip("\n"))
            
            # Читаем stderr
            for line in stderr:
                output_callback("[ERR] " + line.rstrip("\n"))
            
            return True
            
        except Exception as e:
            output_callback(f"[EXCEPTION] {str(e)}")
            return False
    
    def _change_directory(self, command, output_callback):
        """Обрабатывает команду cd и обновляет текущий путь"""
        try:
            with self.lock:
                client = self.client
            
            # Получаем целевую директорию из команды
            parts = command.strip().split(maxsplit=1)
            if len(parts) < 2:
                target_dir = "~"  # cd без аргументов идёт в домашнюю директорию
            else:
                target_dir = parts[1]
            
            # Выполняем cd и сразу проверяем результат
            test_command = f"cd {target_dir} && pwd"
            stdin, stdout, stderr = client.exec_command(test_command)
            
            new_path = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            
            if error:
                output_callback(f"[ERR] {error}")
                return False
            
            if new_path:
                with self.lock:
                    self.current_path = new_path
                output_callback(f"[INFO] Текущая директория: {new_path}")
                return True
            else:
                output_callback("[ERR] Не удалось сменить директорию")
                return False
                
        except Exception as e:
            output_callback(f"[EXCEPTION] Ошибка при смене директории: {e}")
            return False
    
    def _update_current_path(self, output_callback):
        """Обновляет сохранённый текущий путь"""
        try:
            with self.lock:
                client = self.client
            
            stdin, stdout, stderr = client.exec_command('pwd')
            new_path = stdout.read().decode().strip()
            if new_path:
                with self.lock:
                    self.current_path = new_path
        except Exception as e:
            output_callback(f"[WARNING] Не удалось обновить путь: {e}")
    
    def download_file(self, remote_path, local_path, output_callback):
        """Скачивает файл через существующее соединение"""
        with self.lock:
            if not self.is_connected():
                output_callback("[ERROR] Соединение не установлено или разорвано")
                return False
            
            client = self.client
        
        try:
            # Создаём SFTP сессию
            transport = client.get_transport()
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Скачиваем файл
            sftp.get(remote_path, local_path)
            output_callback(f"[INFO] Файл успешно скачан: {remote_path} → {local_path}")
            
            sftp.close()
            return True
            
        except Exception as e:
            output_callback(f"[ERROR] Не удалось скачать файл: {e}")
            return False
    
    def close(self):
        """Закрывает соединение"""
        with self.lock:
            if self.client:
                try:
                    self.client.close()
                except:
                    pass
                self.client = None
            self.current_path = None
            self.connected = False
            self.connecting = False

# ----------------------------------------------------------------------
# Функции шифрования/дешифрования (простое XOR шифрование)
# ----------------------------------------------------------------------
def get_key():
    """Получаем ключ шифрования из переменной окружения или используем фиксированный"""
    env_key = os.environ.get('SSH_CLIENT_KEY')
    if env_key:
        return hashlib.sha256(env_key.encode()).digest()
    else:
        return b'MySuperSecretKey'

def encrypt_password(password):
    """Шифрует пароль с помощью XOR + base64"""
    if not password:
        return ""
    
    key = get_key()
    password_bytes = password.encode('utf-8')
    encrypted_bytes = bytearray()
    key_length = len(key)
    
    for i, byte in enumerate(password_bytes):
        encrypted_bytes.append(byte ^ key[i % key_length])
    return base64.b64encode(encrypted_bytes).decode('ascii')

def decrypt_password(encrypted_data):
    """Дешифрует пароль"""
    if not encrypted_data:
        return ""
    
    try:
        key = get_key()
        encrypted_bytes = base64.b64decode(encrypted_data)
        decrypted_bytes = bytearray()
        key_length = len(key)
        
        for i, byte in enumerate(encrypted_bytes):
            decrypted_bytes.append(byte ^ key[i % key_length])
        
        return decrypted_bytes.decode('utf-8')
    except Exception:
        return encrypted_data

def is_encrypted(password_str):
    """Проверяет, зашифрован ли пароль (эвристика)"""
    if not password_str:
        return False
    
    try:
        if all(ord(c) < 128 for c in password_str):
            base64.b64decode(password_str)
            return True
    except Exception:
        pass
    
    return False

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

        # Создаём глобальное SSH соединение
        self.ssh_connection = SSHConnection()

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
        for i in range(5):
            content_frame.rowconfigure(i, weight=0)
        content_frame.rowconfigure(5, weight=1)
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
        
        # Запускаем периодическое обновление статуса
        self._update_status_periodically()

    def _update_status_periodically(self):
        self._refresh_status()
        # Запускаем снова через 2 секунды
        self.after(5000, self._update_status_periodically)

    def _establish_connection(self):
        """Устанавливает соединение с сервером в отдельном потоке"""
        params = self.get_connection_params()
        if not params:
            return
        
        host, port, user, password = params
        
        # Показываем индикатор загрузки
        self.loading_label.config(text="⏳ Подключение...")
        self.btn_connect.config(state="disabled")
        
        def connect_thread():
            success = self.ssh_connection.connect(
                host, port, user, password, 
                self.append_output,
                self._connection_status_callback
            )
            # Обновляем UI в главном потоке
            self.after(0, self._connection_finished, success)
        
        threading.Thread(target=connect_thread, daemon=True).start()

    def _connection_finished(self, success):
        """Вызывается после завершения попытки подключения"""
        self.loading_label.config(text="")
        self.btn_connect.config(state="normal")
        self._refresh_status()

    def _connection_status_callback(self, connected):
        """Колбэк для обновления статуса из потока"""
        self.after(0, self._update_connection_status, connected)

    def _close_connection(self):
        """Закрывает текущее соединение"""
        self.ssh_connection.close()
        self._update_connection_status(False)
        self.append_output("[INFO] Соединение закрыто")

    def _update_connection_status(self, connected):
        """Обновляет статус соединения в интерфейсе"""
        if connected and self.ssh_connection.current_path:
            self.lbl_connection_status.config(
                text=f"Подключено к {self.ssh_connection.host}:{self.ssh_connection.port}",
                foreground="green"
            )
            self.lbl_connection_path.config(
                text=f"📁 {self.ssh_connection.current_path}",
                foreground="blue"
            )
        else:
            self.lbl_connection_status.config(text="Не подключено", foreground="red")
            self.lbl_connection_path.config(text="")

    def _create_bottom_link(self, parent):
        bottom_frame = ttk.Frame(parent)
        bottom_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        bottom_frame.columnconfigure(0, weight=1)

        link_label = tk.Label(
            bottom_frame,
            text="Source github.com/JTNeXuS2",
            fg="blue",
            cursor="hand2",
            font=("Arial", 8, "underline")
        )
        link_label.grid(row=0, column=0, sticky="e")
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
        
        # Настраиваем колонки для равномерного распределения
        for i in range(8):
            conn_frame.columnconfigure(i, weight=1 if i in (1,3,5) else 0)
        
        # Строка 1: Хост, Порт, Логин, Пароль в одной строке
        ttk.Label(conn_frame, text="Хост:").grid(row=0, column=0, sticky="e", padx=2, pady=1)
        self.entry_host = ttk.Entry(conn_frame)
        self.entry_host.grid(row=0, column=1, sticky="ew", padx=2, pady=1)
        
        ttk.Label(conn_frame, text="Порт:").grid(row=0, column=2, sticky="e", padx=2, pady=1)
        self.entry_port = ttk.Entry(conn_frame, width=8)
        self.entry_port.insert(0, "22")
        self.entry_port.grid(row=0, column=3, sticky="ew", padx=2, pady=1)
        
        ttk.Label(conn_frame, text="Логин:").grid(row=0, column=4, sticky="e", padx=2, pady=1)
        self.entry_user = ttk.Entry(conn_frame)
        self.entry_user.grid(row=0, column=5, sticky="ew", padx=2, pady=1)
        
        ttk.Label(conn_frame, text="Пароль:").grid(row=0, column=6, sticky="e", padx=2, pady=1)
        self.entry_pass = ttk.Entry(conn_frame, show="*")
        self.entry_pass.grid(row=0, column=7, sticky="ew", padx=2, pady=1)
        
        # Строка 2: Сохранённые соединения + кнопки
        ttk.Label(conn_frame, text="Сохранённые:").grid(row=1, column=0, sticky="e", padx=2, pady=1)
        self.combo_var = tk.StringVar()
        self.combo_box = ttk.Combobox(conn_frame, textvariable=self.combo_var, state="readonly")
        self.combo_box.grid(row=1, column=1, columnspan=5, sticky="ew", padx=2, pady=1)
        self.combo_box.bind("<<ComboboxSelected>>", self._on_combo_selected)
        
        # Кнопки Сохранить/Удалить компактно
        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=1, column=6, columnspan=2, sticky="ew", padx=2, pady=1)
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        
        self.btn_save = ttk.Button(btn_frame, text="💾 Сохранить", command=self._save_current_combo)
        self.btn_save.grid(row=0, column=0, sticky="ew", padx=1)
        
        self.btn_delete = ttk.Button(btn_frame, text="🗑️ Удалить", command=self._delete_selected_combo)
        self.btn_delete.grid(row=0, column=1, sticky="ew", padx=1)
        
        # Строка 3: Управление соединением компактно
        control_frame = ttk.Frame(conn_frame)
        control_frame.grid(row=2, column=0, columnspan=8, sticky="ew", pady=2)
        control_frame.columnconfigure(0, weight=1)
        
        # Левая часть с кнопками
        left = ttk.Frame(control_frame)
        left.pack(side="left", fill="x", expand=True)
        
        self.btn_connect = ttk.Button(left, text="Подключить", width=15, command=self._establish_connection)
        self.btn_connect.pack(side="left", padx=1)
        
        self.btn_disconnect = ttk.Button(left, text="Отключить", width=15, command=self._close_connection)
        self.btn_disconnect.pack(side="left", padx=1)
        
        self.loading_label = ttk.Label(left, text="", font=("Arial", 10))
        self.loading_label.pack(side="left", padx=5)
        
        # Правая часть со статусом (компактно)
        right = ttk.Frame(control_frame)
        right.pack(side="right")
        
        # Статус в виде индикатора
        self.lbl_connection_status = ttk.Label(right, text="●", font=("Arial", 12))
        self.lbl_connection_status.pack(side="left", padx=2)
        
        self.lbl_connection_path = ttk.Label(right, text="[нет подключения]", foreground="gray")
        self.lbl_connection_path.pack(side="left", padx=2)
    def _create_btn_frame(self, parent):
        btn_frame = ttk.LabelFrame(parent, text="Быстрые команды")
        btn_frame.grid(row=1, column=0, sticky="ew", pady=5)
        cols = 4
        for i in range(cols):
            btn_frame.columnconfigure(i, weight=1, uniform="btn")
        # Список кнопок: (текст, команда)
        buttons = [
            ("help", "help"),
            ("где я", "pwd"),
            ("список файлов", "ls -la"),
            ("свободное место", "df -h"),
            ("очистить директорию", "rm -f /tmp/*"),
            ("удалить директорию", "rm -rf /tmp/dir"),
            ("создать директорию", "mkdir test"),
            ("touch file", "touch test.txt"),
            ("прочитать файл", "cat /etc/passwd"),
            ("список процессов", "ps aux | head"),
            ("Справка", "info"),
        ]
        # Размещаем кнопки в сетке
        for i, (text, cmd) in enumerate(buttons):
            row = i // cols
            col = i % cols
            
            if cmd == "info":
                btn = ttk.Button(btn_frame, text=text, command=self.infos)
            else:
                btn = ttk.Button(btn_frame, text=text, 
                               command=lambda x=cmd: self._insert_command(x))
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")
    

    def _insert_command(self, command):
        """Вставляет команду в поле произвольной команды"""
        self.entry_custom_var.set(command)
        self.entry_custom.focus_set()
        self.entry_custom.icursor(tk.END)

    # ------------------------------------------------------------------
    # UI – произвольная команда
    # ------------------------------------------------------------------
    def _create_custom_frame(self, parent):
        custom_frame = ttk.LabelFrame(parent, text="Произвольная команда")
        custom_frame.grid(row=2, column=0, sticky="ew", pady=5)

        custom_frame.columnconfigure(0, weight=1)
        custom_frame.columnconfigure(1, weight=0)
        custom_frame.columnconfigure(2, weight=0)

        # Combobox для истории
        self.entry_custom_var = tk.StringVar()
        self.entry_custom = ttk.Combobox(custom_frame,
                                        textvariable=self.entry_custom_var,
                                        state="normal", width=60)
        self.entry_custom.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

        # Run button
        self.btn_custom = ttk.Button(custom_frame, text="Выполнить", command=self.run_custom)
        self.btn_custom.grid(row=0, column=1, sticky="w", padx=5)

        # Delete button
        self.btn_delete_history = ttk.Button(custom_frame, text="Удалить из истории", command=self._delete_history_command)
        self.btn_delete_history.grid(row=0, column=2, sticky="w", padx=5)

    # ------------------------------------------------------------------
    # UI – скачивание файла
    # ------------------------------------------------------------------
    def _create_download_frame(self, parent):
        download_frame = ttk.LabelFrame(parent, text="Скачивание файла")
        download_frame.grid(row=3, column=0, sticky="ew", pady=5)

        download_frame.columnconfigure(1, weight=1)

        ttk.Label(download_frame, text="Remote Path:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.entry_remote = ttk.Entry(download_frame, width=50)
        self.entry_remote.grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(download_frame, text="Local Path:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.entry_local = ttk.Entry(download_frame, width=50, state="readonly")
        self.entry_local.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        self.btn_download = ttk.Button(download_frame, text="Скачать", command=self._download_file)
        self.btn_download.grid(row=2, column=1, sticky="e", padx=5, pady=5)

    # ------------------------------------------------------------------
    # UI – вывод
    # ------------------------------------------------------------------
    def _create_output_frame(self, parent):
        output_frame = ttk.LabelFrame(parent, text="Результат")
        output_frame.grid(row=5, column=0, sticky="nsew", pady=5)

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
            messagebox.showwarning("Ошибка", "Не удалось загрузить сохранённые соединения.")
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
        self.entry_pass.delete(0, tk.END)
        password = combo['password']
        if password and is_encrypted(password):
            decrypted = decrypt_password(password)
            self.entry_pass.insert(0, decrypted)
        else:
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
        messagebox.showinfo("Справка по командам", 
            "📁 Навигация:\n"
            "pwd — показать текущую папку\n"
            "ls — список файлов\n"
            "ls -la — показать все файлы (включая скрытые)\n"
            "cd [путь] — перейти в папку\n"
            "cd .. — на уровень выше\n"
            "cd ~ — в домашнюю папку\n\n"
            
            "📄 Работа с файлами:\n"
            "cat [файл] — показать содержимое файла\n"
            "touch [файл] — создать пустой файл\n"
            "rm [файл] — удалить файл\n"
            "rm -rf [папка] — удалить папку со всем содержимым\n"
            "cp [источник] [цель] — копировать\n"
            "mv [источник] [цель] — переместить/переименовать\n\n"
            
            "📊 Система:\n"
            "df -h — свободное место на дисках\n"
            "ps aux — список процессов\n"
            "grep [текст] [файл] — поиск текста в файле"
        )

    def _load_history(self):
        """Загружаем историю из HISTORY_FILE и заполняем combobox."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = [line.rstrip("\n")
                                    for line in f if line.strip()]
            except Exception as e:
                messagebox.showwarning("История", f"Не удалось загрузить историю: {e}")
                self.history = []
        else:
            self.history = []

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
            messagebox.showwarning("История", f"Не удалось сохранить историю: {e}")

        self.entry_custom['values'] = self.history

    def _delete_history_command(self):
        current_command = self.entry_custom.get().strip()
        if not current_command:
            messagebox.showwarning("Внимание", "Нечего удалять – выберите команду из истории.")
            return
        if current_command not in self.history:
            messagebox.showinfo("Информация", "Команда уже отсутствует в истории.")
            return
        current_index = -1
        try:
            current_index = list(self.entry_custom['values']).index(current_command)
        except (ValueError, AttributeError, KeyError):
            pass
        self.history.remove(current_command)
        self._save_history_to_file()
        self.entry_custom['values'] = self.history
        next_command = ""
        if self.history:
            if current_index >= 0 and current_index < len(self.history):
                next_command = self.history[current_index]
            elif len(self.history) > 0:
                next_command = self.history[0]
        self.entry_custom_var.set(next_command)

    def _save_history_to_file(self):
        """Записывает первые 200 строк истории в HISTORY_FILE."""
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                for c in self.history[:200]:
                    f.write(c + "\n")
        except Exception as e:
            messagebox.showwarning("История", f"Не удалось сохранить историю: {e}")

    def get_connection_params(self):
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        try:
            port = int(port_str) if port_str else 22
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.")
            return None
        user = self.entry_user.get().strip()
        password = self.entry_pass.get()

        if not host:
            messagebox.showerror("Ошибка", "Пожалуйста, укажите хост.")
            return None
        if not user:
            messagebox.showerror("Ошибка", "Пожалуйста, укажите логин.")
            return None
        if not password:
            messagebox.showerror("Ошибка", "Пожалуйста, укажите пароль.")
            return None
            
        return host, port, user, password

    def append_output(self, text):
        self.text_output.configure(state="normal")
        self.text_output.insert("end", text + "\n")
        self.text_output.see("end")
        self.text_output.configure(state="disabled")

    def _refresh_status(self):
        """Обновляет статус соединения"""
        if self.ssh_connection.is_connected():
            self._update_connection_status(True)
        else:
            self._update_connection_status(False)

    def run_custom(self):
        command = self.entry_custom.get().strip()
        if not command:
            messagebox.showwarning("Внимание", "Введите команду.")
            return
        
        self._save_history(command)

        # Проверяем, есть ли активное соединение
        if not self.ssh_connection.client or not self.ssh_connection.client.get_transport() or not self.ssh_connection.client.get_transport().is_active():
            # Если нет соединения, пытаемся установить
            params = self.get_connection_params()
            if not params:
                return
            
            host, port, user, password = params
            if not self.ssh_connection.connect(host, port, user, password, self.append_output):
                return
        
        # Выполняем команду в существующем соединении
        self.append_output(f"=== Выполняется: {command}")
        threading.Thread(target=self._execute_in_connection, 
                        args=(command,), daemon=True).start()

    def _execute_in_connection(self, command):
        """Выполняет команду в существующем соединении в отдельном потоке"""
        self.ssh_connection.execute(command, self.append_output)
        # Обновляем статус в GUI
        self.after(0, self._refresh_status)

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
        
        # Проверяем соединение
        if not self.ssh_connection.client or not self.ssh_connection.client.get_transport() or not self.ssh_connection.client.get_transport().is_active():
            params = self.get_connection_params()
            if not params:
                return
            host, port, user, password = params
            if not self.ssh_connection.connect(host, port, user, password, self.append_output):
                return

        local_path = self._local_path_for_remote(remote_path)
        self.entry_local.config(state="normal")
        self.entry_local.delete(0, tk.END)
        self.entry_local.insert(0, str(local_path))
        self.entry_local.config(state="readonly")

        self.append_output(f"[INFO] Начинается скачивание: {remote_path} → {local_path}")
        threading.Thread(target=self.ssh_connection.download_file,
                         args=(remote_path, str(local_path), self.append_output),
                         daemon=True).start()

# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = SSHGUI()
    app.mainloop()
