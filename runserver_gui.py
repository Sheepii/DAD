import subprocess
import sys
import tkinter as tk
from tkinter import ttk
import socket
from pathlib import Path


class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DAD - Server Control")
        self.geometry("620x320")
        self.resizable(False, False)

        self.status_var = tk.StringVar(value="Stopped")
        self.process = None

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Start.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Restart.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"))

        header = ttk.Label(self, text="DAD Server Control", style="Header.TLabel")
        header.pack(pady=(14, 4))
        sub = ttk.Label(self, text="Local web app controller", style="Sub.TLabel", foreground="#666666")
        sub.pack(pady=(0, 12))

        status_row = ttk.Frame(self)
        status_row.pack(pady=6)
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)

        ip_row = ttk.Frame(self)
        ip_row.pack(pady=6)
        self.ip_var = tk.StringVar(value="http://127.0.0.1:8080/")
        ttk.Label(ip_row, text="LAN URL:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(ip_row, textvariable=self.ip_var, style="Sub.TLabel").pack(side=tk.LEFT)
        self.copy_btn = ttk.Button(ip_row, text="Copy", command=self.copy_url)
        self.copy_btn.pack(side=tk.LEFT, padx=(8, 0))

        btn_row = ttk.Frame(self)
        btn_row.pack(pady=16)
        self.start_btn = ttk.Button(btn_row, text="Start", command=self.start_server, style="Start.TButton")
        self.restart_btn = ttk.Button(btn_row, text="Restart", command=self.restart_server, style="Restart.TButton")
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.stop_server, style="Stop.TButton")
        self.start_btn.grid(row=0, column=0, padx=8, ipadx=10, ipady=4)
        self.restart_btn.grid(row=0, column=1, padx=8, ipadx=10, ipady=4)
        self.stop_btn.grid(row=0, column=2, padx=8, ipadx=10, ipady=4)

        info = ttk.Label(
            self,
            text="Runs on http://0.0.0.0:8080 (LAN accessible).",
            foreground="#666666",
        )
        info.pack(pady=(4, 0))
        hint = ttk.Label(
            self,
            text="Open http://127.0.0.1:8080/ on this PC.",
            foreground="#666666",
        )
        hint.pack(pady=(2, 8))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.start_server)
        self.after(200, self.update_ip)

    def _get_lan_ip(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def update_ip(self):
        ip = self._get_lan_ip()
        self.ip_var.set(f"http://{ip}:8080/")

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.ip_var.get())
        self.update()

    def start_server(self):
        if self.process and self.process.poll() is None:
            return
        python = sys.executable
        project_root = Path(__file__).resolve().parent
        self.process = subprocess.Popen([python, "runserver.py"], cwd=str(project_root))
        self.status_var.set("Running")

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process = None
        self.status_var.set("Stopped")

    def restart_server(self):
        self.stop_server()
        self.start_server()

    def on_close(self):
        self.stop_server()
        self.destroy()


if __name__ == "__main__":
    app = ServerGUI()
    app.mainloop()
