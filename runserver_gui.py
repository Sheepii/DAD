import subprocess
import sys
import tkinter as tk
from tkinter import ttk


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
            text="Runs on https://0.0.0.0:8443 (LAN accessible).",
            foreground="#666666",
        )
        info.pack(pady=(4, 0))
        hint = ttk.Label(
            self,
            text="Open http://127.0.0.1:8000/ (auto-redirects to HTTPS).",
            foreground="#666666",
        )
        hint.pack(pady=(2, 8))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.start_server)

    def start_server(self):
        if self.process and self.process.poll() is None:
            return
        python = sys.executable
        self.process = subprocess.Popen([python, "runserver_https.py"])
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
