#!/usr/bin/env python3
"""
Webtoon Translation Studio - Masaüstü Kontrol Paneli & Launcher
Backend, Frontend, AI Model Kuyruğu ve Sistem Bakım Yönetimi
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ─── Sabitler ve Dizinler ───────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent
PYTHON_EXE = REPO_ROOT / ".venv-ai" / "bin" / "python"
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)

BACKEND_PORT = 5000
FRONTEND_PORT = 5173
BACKEND_HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/health"
BACKEND_JOBS_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/jobs"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"

# Renk Paleti (Dark Modern UI)
BG_DARK = "#111317"
BG_CARD = "#181c22"
BG_CARD_BORDER = "#272d35"
BG_INPUT = "#20262e"
TEXT_MAIN = "#edf0f2"
TEXT_MUTED = "#98a3ad"
ACCENT_GOLD = "#e7bd54"
ACCENT_GREEN = "#45d483"
ACCENT_RED = "#ff5c5c"
ACCENT_BLUE = "#38bdf8"
ACCENT_ORANGE = "#fb923c"


class ProcessManager:
    """Arka plan servis süreçlerini (Backend & Frontend) yöneten sınıf."""

    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue
        self.backend_proc: subprocess.Popen | None = None
        self.frontend_proc: subprocess.Popen | None = None

    def start_backend(self) -> bool:
        if self.is_backend_running():
            return True
        try:
            cmd = [str(PYTHON_EXE), "-m", "backend.app"]
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.backend_proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setpgrp,
                env=env,
            )
            threading.Thread(target=self._pipe_reader, args=(self.backend_proc, "backend"), daemon=True).start()
            return True
        except Exception as error:
            self.log_queue.put(("backend", f"[HATA] Backend başlatılamadı: {error}\n"))
            return False

    def stop_backend(self) -> None:
        if self.backend_proc:
            try:
                pgid = os.getpgid(self.backend_proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                self.backend_proc.wait(timeout=2)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.backend_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.backend_proc = None
            self.log_queue.put(("backend", "[BİLGİ] Backend durduruldu.\n"))

    def start_frontend(self) -> bool:
        if self.is_frontend_running():
            return True
        try:
            npm_bin = shutil.which("npm") or "npm"
            cmd = [npm_bin, "run", "dev"]
            self.frontend_proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setpgrp,
            )
            threading.Thread(target=self._pipe_reader, args=(self.frontend_proc, "frontend"), daemon=True).start()
            return True
        except Exception as error:
            self.log_queue.put(("frontend", f"[HATA] Frontend başlatılamadı: {error}\n"))
            return False

    def stop_frontend(self) -> None:
        if self.frontend_proc:
            try:
                pgid = os.getpgid(self.frontend_proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                self.frontend_proc.wait(timeout=2)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.frontend_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.frontend_proc = None
            self.log_queue.put(("frontend", "[BİLGİ] Frontend durduruldu.\n"))

    def is_backend_running(self) -> bool:
        if self.backend_proc and self.backend_proc.poll() is None:
            return True
        return False

    def is_frontend_running(self) -> bool:
        if self.frontend_proc and self.frontend_proc.poll() is None:
            return True
        return False

    def kill_all_ai_tasks(self) -> int:
        """IOPaint veya takılan Python alt modellerini zorla sonlandırır."""
        killed_count = 0
        if not HAS_PSUTIL:
            return killed_count

        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["pid"] == current_pid:
                    continue
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "iopaint" in cmdline or ("python" in cmdline and "backend.app" not in cmdline and "control_panel.py" not in cmdline and "Webtoon Editor" in cmdline):
                    proc.kill()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return killed_count

    def _pipe_reader(self, proc: subprocess.Popen, tag: str) -> None:
        if not proc.stdout:
            return
        for line in iter(proc.stdout.readline, ""):
            if line:
                self.log_queue.put((tag, line))
        proc.stdout.close()


class ControlPanelApp(tk.Tk):
    """Modern Dark Mode Tkinter Kontrol Paneli Arayüzü."""

    def __init__(self):
        super().__init__()
        self.title("Webtoon Translation Studio — Kontrol Paneli")
        self.geometry("980x720")
        self.minsize(860, 600)
        self.configure(bg=BG_DARK)

        self.log_queue: queue.Queue = queue.Queue()
        self.manager = ProcessManager(self.log_queue)

        self.auto_scroll_backend = tk.BooleanVar(value=True)
        self.auto_scroll_frontend = tk.BooleanVar(value=True)

        self._setup_styles()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Periyodik arka plan güncellemeleri
        self.after(100, self._process_log_queue)
        self.after(500, self._refresh_status_loop)

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=BG_DARK, foreground=TEXT_MAIN, font=("Inter", 10))
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_CARD, foreground=TEXT_MUTED, padding=[16, 6], font=("Inter", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", BG_INPUT)], foreground=[("selected", ACCENT_GOLD)])

        style.configure("TProgressbar", background=ACCENT_GOLD, troughcolor=BG_INPUT, borderwidth=0)

    def _build_ui(self) -> None:
        # 1. Header (Üst Bar)
        header = tk.Frame(self, bg=BG_CARD, highlightthickness=1, highlightbackground=BG_CARD_BORDER, padx=16, pady=12)
        header.pack(fill="x", padx=14, pady=(12, 6))

        logo_frame = tk.Frame(header, bg=BG_CARD)
        logo_frame.pack(side="left")

        logo_box = tk.Label(logo_frame, text="⚡", bg=ACCENT_GOLD, fg="#111317", font=("Inter", 14, "bold"), width=3, height=1)
        logo_box.pack(side="left", padx=(0, 10))

        title_frame = tk.Frame(logo_frame, bg=BG_CARD)
        title_frame.pack(side="left")

        tk.Label(title_frame, text="Webtoon Translation Studio", bg=BG_CARD, fg=TEXT_MAIN, font=("Inter", 13, "bold")).pack(anchor="w")
        tk.Label(title_frame, text="Yerel Servis ve Model Yönetim Paneli", bg=BG_CARD, fg=TEXT_MUTED, font=("Inter", 9)).pack(anchor="w")

        self.lbl_global_status = tk.Label(header, text="● Sistem Hazır", bg=BG_CARD, fg=ACCENT_GREEN, font=("Inter", 11, "bold"))
        self.lbl_global_status.pack(side="right")

        # 2. Servis Kartları (3 Kolon)
        cards_frame = tk.Frame(self, bg=BG_DARK)
        cards_frame.pack(fill="x", padx=14, pady=6)
        cards_frame.columnconfigure((0, 1, 2), weight=1, uniform="card")

        # Kart 1: Backend
        c1 = tk.LabelFrame(cards_frame, text=" Backend API (:5000) ", bg=BG_CARD, fg=ACCENT_GOLD, font=("Inter", 10, "bold"), padx=12, pady=10, relief="solid", bd=1)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.lbl_backend_state = tk.Label(c1, text="🔴 Durduruldu", bg=BG_CARD, fg=ACCENT_RED, font=("Inter", 10, "bold"))
        self.lbl_backend_state.pack(anchor="w")
        self.lbl_backend_pid = tk.Label(c1, text="PID: -", bg=BG_CARD, fg=TEXT_MUTED, font=("Inter", 9))
        self.lbl_backend_pid.pack(anchor="w", pady=(2, 8))

        btn_row1 = tk.Frame(c1, bg=BG_CARD)
        btn_row1.pack(fill="x")
        self.btn_start_backend = self._create_btn(btn_row1, "▶ Başlat", self._start_backend, bg="#234e35", fg="#86efac")
        self.btn_start_backend.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop_backend = self._create_btn(btn_row1, "■ Durdur", self._stop_backend, bg="#4e2323", fg="#fca5a5")
        self.btn_stop_backend.pack(side="left", fill="x", expand=True)

        # Kart 2: Frontend
        c2 = tk.LabelFrame(cards_frame, text=" Frontend Arayüz (:5173) ", bg=BG_CARD, fg=ACCENT_GOLD, font=("Inter", 10, "bold"), padx=12, pady=10, relief="solid", bd=1)
        c2.grid(row=0, column=1, sticky="nsew", padx=3)

        self.lbl_frontend_state = tk.Label(c2, text="🔴 Durduruldu", bg=BG_CARD, fg=ACCENT_RED, font=("Inter", 10, "bold"))
        self.lbl_frontend_state.pack(anchor="w")
        self.lbl_frontend_pid = tk.Label(c2, text="PID: -", bg=BG_CARD, fg=TEXT_MUTED, font=("Inter", 9))
        self.lbl_frontend_pid.pack(anchor="w", pady=(2, 8))

        btn_row2 = tk.Frame(c2, bg=BG_CARD)
        btn_row2.pack(fill="x")
        self.btn_start_frontend = self._create_btn(btn_row2, "▶ Başlat", self._start_frontend, bg="#234e35", fg="#86efac")
        self.btn_start_frontend.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop_frontend = self._create_btn(btn_row2, "■ Durdur", self._stop_frontend, bg="#4e2323", fg="#fca5a5")
        self.btn_stop_frontend.pack(side="left", fill="x", expand=True)

        self.btn_open_browser = self._create_btn(c2, "🌐 Tarayıcıda Aç", self._open_browser, bg="#1e293b", fg=ACCENT_BLUE)
        self.btn_open_browser.pack(fill="x", pady=(6, 0))

        # Kart 3: AI Kuyruğu & Sistem
        c3 = tk.LabelFrame(cards_frame, text=" AI Modelleri & Sistem ", bg=BG_CARD, fg=ACCENT_GOLD, font=("Inter", 10, "bold"), padx=12, pady=10, relief="solid", bd=1)
        c3.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        self.lbl_ram_usage = tk.Label(c3, text="RAM: Hesaplanıyor...", bg=BG_CARD, fg=TEXT_MAIN, font=("Inter", 9))
        self.lbl_ram_usage.pack(anchor="w")
        self.lbl_cpu_usage = tk.Label(c3, text="CPU: %0", bg=BG_CARD, fg=TEXT_MUTED, font=("Inter", 9))
        self.lbl_cpu_usage.pack(anchor="w", pady=(0, 4))

        self.lbl_ai_job = tk.Label(c3, text="Aktif AI İşi: Boşta", bg=BG_CARD, fg=ACCENT_GREEN, font=("Inter", 9, "bold"))
        self.lbl_ai_job.pack(anchor="w", pady=(0, 8))

        self.btn_kill_ai = self._create_btn(c3, "🛑 AI İşlemini Durdur", self._kill_ai_tasks, bg="#581c1c", fg="#fca5a5")
        self.btn_kill_ai.pack(fill="x")

        # 3. Ortak Aksiyon Butonları
        quick_actions = tk.Frame(self, bg=BG_DARK)
        quick_actions.pack(fill="x", padx=14, pady=4)

        self._create_btn(quick_actions, "🚀 Tüm Sistemi Başlat", self._start_all, bg="#1e3a29", fg="#86efac", font=("Inter", 10, "bold")).pack(side="left", padx=(0, 6))
        self._create_btn(quick_actions, "🛑 Tümünü Kapat", self._stop_all, bg="#451a1a", fg="#fca5a5", font=("Inter", 10, "bold")).pack(side="left", padx=(0, 6))
        self._create_btn(quick_actions, "🔄 Yeniden Başlat", self._restart_all, bg="#332a18", fg=ACCENT_GOLD).pack(side="left", padx=(0, 6))

        # Sağ Taraf: Bakım Araçları
        self._create_btn(quick_actions, "🧹 Cache Temizle", self._clean_temp_files, bg="#20262e", fg=TEXT_MAIN).pack(side="right")
        self._create_btn(quick_actions, "🔍 Kod Doğrula", self._compile_check, bg="#20262e", fg=TEXT_MAIN).pack(side="right", padx=6)
        self._create_btn(quick_actions, "🔨 Frontend Build", self._build_frontend, bg="#20262e", fg=TEXT_MAIN).pack(side="right")

        # 4. Canlı Terminal / Log Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(6, 12))

        # Sekme 1: Backend Logları
        tab_backend = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_backend, text="  Backend Logları  ")
        self.txt_backend = self._create_log_text(tab_backend)

        # Sekme 2: Frontend Logları
        tab_frontend = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_frontend, text="  Frontend Logları  ")
        self.txt_frontend = self._create_log_text(tab_frontend)

        # Sekme 3: AI İş Kuyruğu
        tab_jobs = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_jobs, text="  AI Kuyruğu Durumu  ")
        self.txt_jobs = self._create_log_text(tab_jobs)

    def _create_btn(self, parent: Any, text: str, command: Any, bg: str, fg: str, font: tuple = ("Inter", 9, "bold")) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground="#333d4b",
            activeforeground=TEXT_MAIN,
            relief="flat",
            font=font,
            padx=10,
            pady=5,
            cursor="hand2",
            bd=0,
        )
        return btn

    def _create_log_text(self, parent: tk.Frame) -> tk.Text:
        control_row = tk.Frame(parent, bg=BG_DARK)
        control_row.pack(fill="x", pady=(4, 2))

        btn_clear = tk.Button(
            control_row,
            text="Temizle",
            bg=BG_INPUT,
            fg=TEXT_MUTED,
            activebackground=BG_CARD,
            activeforeground=TEXT_MAIN,
            font=("Inter", 8),
            relief="flat",
            command=lambda: text_widget.delete("1.0", "end"),
        )
        btn_clear.pack(side="right")

        frame = tk.Frame(parent, bg=BG_INPUT, bd=1, relief="solid")
        frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        text_widget = tk.Text(
            frame,
            bg="#0d1117",
            fg="#c9d1d9",
            insertbackground="#ffffff",
            selectbackground="#264f78",
            font=("Fira Code", 9),
            yscrollcommand=scrollbar.set,
            wrap="word",
            bd=0,
            padx=8,
            pady=8,
        )
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)

        # Renk Etiketleri
        text_widget.tag_config("error", foreground=ACCENT_RED)
        text_widget.tag_config("info", foreground=ACCENT_BLUE)
        text_widget.tag_config("warn", foreground=ACCENT_GOLD)
        text_widget.tag_config("success", foreground=ACCENT_GREEN)

        return text_widget

    # ─── Servis Aksiyonları ───────────────────────────────────────────────────

    def _start_backend(self) -> None:
        if self.manager.start_backend():
            self.lbl_backend_state.config(text="🟢 Başlatılıyor...", fg=ACCENT_GOLD)

    def _stop_backend(self) -> None:
        self.manager.stop_backend()
        self.lbl_backend_state.config(text="🔴 Durduruldu", fg=ACCENT_RED)
        self.lbl_backend_pid.config(text="PID: -")

    def _start_frontend(self) -> None:
        if self.manager.start_frontend():
            self.lbl_frontend_state.config(text="🟢 Başlatılıyor...", fg=ACCENT_GOLD)

    def _stop_frontend(self) -> None:
        self.manager.stop_frontend()
        self.lbl_frontend_state.config(text="🔴 Durduruldu", fg=ACCENT_RED)
        self.lbl_frontend_pid.config(text="PID: -")

    def _start_all(self) -> None:
        self._start_backend()
        self._start_frontend()

    def _stop_all(self) -> None:
        self._stop_frontend()
        self._stop_backend()

    def _restart_all(self) -> None:
        self._stop_all()
        self.after(1200, self._start_all)

    def _open_browser(self) -> None:
        webbrowser.open(FRONTEND_URL)

    def _kill_ai_tasks(self) -> None:
        count = self.manager.kill_all_ai_tasks()
        self.log_queue.put(("backend", f"[BİLGİ] {count} aktif AI alt süreci durduruldu.\n"))
        messagebox.showinfo("AI Durduruldu", f"{count} adet arka plan AI/model süreci sonlandırıldı.")

    # ─── Bakım & Güncelleme ───────────────────────────────────────────────────

    def _clean_temp_files(self) -> None:
        cleaned = 0
        for pattern in (".ocr_*.png", ".tmp_*.png", ".project-cover.*.tmp"):
            for path in REPO_ROOT.rglob(pattern):
                if path.is_file():
                    try:
                        path.unlink()
                        cleaned += 1
                    except Exception:
                        pass
        self.log_queue.put(("backend", f"[BİLGİ] {cleaned} geçici önbellek dosyası temizlendi.\n"))
        messagebox.showinfo("Temizlik Tamam", f"{cleaned} adet geçici OCR ve önbellek dosyası temizlendi.")

    def _compile_check(self) -> None:
        threading.Thread(target=self._run_compileall_worker, daemon=True).start()

    def _run_compileall_worker(self) -> None:
        self.log_queue.put(("backend", "[BİLGİ] Python dosyaları doğrulanıyor...\n"))
        res = subprocess.run([str(PYTHON_EXE), "-m", "compileall", "backend"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        if res.returncode == 0:
            self.log_queue.put(("backend", "[BAŞARILI] Python backend kodunda sözdizimi hatası yok.\n"))
        else:
            self.log_queue.put(("backend", f"[HATA] Python derleme hatası:\n{res.stderr}\n"))

    def _build_frontend(self) -> None:
        threading.Thread(target=self._run_build_worker, daemon=True).start()

    def _run_build_worker(self) -> None:
        self.log_queue.put(("frontend", "[BİLGİ] Frontend production derlemesi başlatıldı (npm run build)...\n"))
        npm_bin = shutil.which("npm") or "npm"
        res = subprocess.run([npm_bin, "run", "build"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        if res.returncode == 0:
            self.log_queue.put(("frontend", f"[BAŞARILI] Frontend build tamamlandı:\n{res.stdout}\n"))
        else:
            self.log_queue.put(("frontend", f"[HATA] Frontend build başarısız:\n{res.stderr or res.stdout}\n"))

    # ─── Log ve Durum Döngüleri ───────────────────────────────────────────────

    def _process_log_queue(self) -> None:
        while not self.log_queue.empty():
            try:
                tag, line = self.log_queue.get_nowait()
                target_text = self.txt_backend if tag == "backend" else self.txt_frontend

                tag_style = "info"
                if "error" in line.lower() or "hata" in line.lower() or "failed" in line.lower():
                    tag_style = "error"
                elif "warn" in line.lower() or "uyari" in line.lower():
                    tag_style = "warn"
                elif "başarılı" in line.lower() or "tamamlandı" in line.lower() or "200" in line:
                    tag_style = "success"

                target_text.insert("end", line, tag_style)
                target_text.see("end")
            except queue.Empty:
                break
        self.after(100, self._process_log_queue)

    def _refresh_status_loop(self) -> None:
        threading.Thread(target=self._query_system_metrics, daemon=True).start()
        self.after(2000, self._refresh_status_loop)

    def _query_system_metrics(self) -> None:
        # 1. Backend Durumu
        backend_alive = False
        if self.manager.is_backend_running():
            try:
                req = urllib.request.Request(BACKEND_HEALTH_URL, headers={"User-Agent": "ControlPanel"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    backend_alive = resp.status == 200
            except Exception:
                backend_alive = False

        pid_b = self.manager.backend_proc.pid if self.manager.backend_proc else "-"

        # 2. Frontend Durumu
        frontend_alive = self.manager.is_frontend_running()
        pid_f = self.manager.frontend_proc.pid if self.manager.frontend_proc else "-"

        # 3. RAM & CPU
        ram_text = "RAM: Bilinmiyor"
        cpu_text = "CPU: %0"
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            ram_text = f"RAM: %{mem.percent} ({mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB)"
            cpu_text = f"CPU: %{psutil.cpu_percent(interval=None)}"

        # 4. AI İş Kuyruğu Durumu
        job_status_text = "Aktif AI İşi: Boşta"
        if backend_alive:
            try:
                req = urllib.request.Request(BACKEND_JOBS_URL, headers={"User-Agent": "ControlPanel"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    jobs_data = json.loads(resp.read().decode("utf-8"))
                    running = next((job for job in jobs_data if job.get("status") in {"running", "queued"}), None)
                    if running:
                        job_status_text = f"AI: {running.get('type', '').upper()} (%{running.get('progress', 0)}) — {running.get('message', '')}"
                    self.after(0, lambda d=jobs_data: self._update_jobs_tab(d))
            except Exception:
                pass

        # GUI Elemanlarını Güncelle
        self.after(0, lambda: self._apply_metric_updates(backend_alive, pid_b, frontend_alive, pid_f, ram_text, cpu_text, job_status_text))

    def _apply_metric_updates(self, b_alive: bool, b_pid: Any, f_alive: bool, f_pid: Any, ram: str, cpu: str, ai_job: str) -> None:
        if b_alive:
            self.lbl_backend_state.config(text="🟢 Çalışıyor (Port 5000)", fg=ACCENT_GREEN)
            self.lbl_backend_pid.config(text=f"PID: {b_pid}")
        else:
            self.lbl_backend_state.config(text="🔴 Durduruldu", fg=ACCENT_RED)
            self.lbl_backend_pid.config(text="PID: -")

        if f_alive:
            self.lbl_frontend_state.config(text="🟢 Çalışıyor (Port 5173)", fg=ACCENT_GREEN)
            self.lbl_frontend_pid.config(text=f"PID: {f_pid}")
        else:
            self.lbl_frontend_state.config(text="🔴 Durduruldu", fg=ACCENT_RED)
            self.lbl_frontend_pid.config(text="PID: -")

        self.lbl_ram_usage.config(text=ram)
        self.lbl_cpu_usage.config(text=cpu)

        if "AI:" in ai_job:
            self.lbl_ai_job.config(text=ai_job, fg=ACCENT_GOLD)
            self.lbl_global_status.config(text="🟡 AI İşlemi Sürüyor", fg=ACCENT_GOLD)
        elif b_alive and f_alive:
            self.lbl_ai_job.config(text="Aktif AI İşi: Boşta", fg=ACCENT_GREEN)
            self.lbl_global_status.config(text="🟢 Sistem Aktif & Hazır", fg=ACCENT_GREEN)
        elif b_alive or f_alive:
            self.lbl_global_status.config(text="🟡 Kısmi Çalışıyor", fg=ACCENT_ORANGE)
        else:
            self.lbl_ai_job.config(text="Aktif AI İşi: Servis Kapalı", fg=TEXT_MUTED)
            self.lbl_global_status.config(text="🔴 Servisler Kapalı", fg=ACCENT_RED)

    def _update_jobs_tab(self, jobs: list[dict[str, Any]]) -> None:
        if not jobs:
            return
        formatted = []
        for job in jobs[:20]:
            status_emoji = {"done": "✅", "running": "⏳", "queued": "🕒", "failed": "❌"}.get(job.get("status"), "•")
            formatted.append(f"{status_emoji} [{job.get('type', '').upper()}] %{job.get('progress', 0):02d} — {job.get('message', '')} ({job.get('createdAt', '')[:19]})")
        content = "\n".join(formatted)

        self.txt_jobs.delete("1.0", "end")
        self.txt_jobs.insert("1.0", content)

    def _on_close(self) -> None:
        if self.manager.is_backend_running() or self.manager.is_frontend_running():
            accepted = messagebox.askyesno("Çıkış", "Açık olan Backend ve Frontend servisleri de kapatılsın mı?")
            if accepted:
                self.manager.stop_all = self._stop_all()
        self.destroy()


def main():
    app = ControlPanelApp()
    app.mainloop()


if __name__ == "__main__":
    main()
