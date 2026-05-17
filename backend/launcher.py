"""
Knowledge Base Desktop App Launcher
Starts FastAPI server in background, opens browser, shows control window.
"""
import sys
import os
import threading
import time
import webbrowser
import tkinter as tk
import uvicorn
import socket


def setup_paths():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        data_dir = os.path.join(exe_dir, "data")
        os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
        os.chdir(exe_dir)


def find_free_port(start=8765):
    port = start
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            port += 1


def start_server(port):
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    setup_paths()
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()
    time.sleep(2)

    webbrowser.open(url)

    root = tk.Tk()
    root.title("Knowledge Base")
    root.geometry("320x160")
    root.resizable(False, False)

    tk.Label(root, text="Knowledge Base", font=("Arial", 14, "bold")).pack(pady=(12, 2))
    tk.Label(root, text=f"Running on port {port}", fg="gray").pack()

    def open_browser():
        webbrowser.open(url)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="Open Window", command=open_browser, width=14).pack(side="left", padx=4)

    tk.Label(root, text="Close this window to stop", fg="gray", font=("Arial", 9)).pack()

    root.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
