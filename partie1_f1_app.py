"""
Projet Python Avancé – Partie 1
Application desktop F1 avec Tkinter + OpenF1 API + SQLite
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, font as tkfont
import sqlite3
import requests
import threading
import time
import json
import os
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ─── CONFIG ──────────────────────────────────────────────────────────────────

DB_PATH = "f1_data.db"
API_BASE = "https://api.openf1.org/v1"

TEAM_COLORS = {
    "Red Bull Racing": "#3671C6",
    "Ferrari": "#E8002D",
    "Mercedes": "#27F4D2",
    "McLaren": "#FF8000",
    "Aston Martin": "#229971",
    "Alpine": "#FF87BC",
    "Williams": "#64C4FF",
    "RB": "#6692FF",
    "Haas F1 Team": "#B6BABD",
    "Kick Sauber": "#52E252",
}

DEFAULT_COLOR = "#CCCCCC"


# ─── DATABASE ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            driver_number INTEGER PRIMARY KEY,
            full_name     TEXT,
            team_name     TEXT,
            country_code  TEXT,
            session_key   INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lap_times (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_number INTEGER,
            lap_number    INTEGER,
            lap_duration  REAL,
            session_key   INTEGER
        )
    """)
    conn.commit()
    conn.close()


def clear_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM drivers")
    cur.execute("DELETE FROM lap_times")
    conn.commit()
    conn.close()


def save_drivers(drivers: list, session_key: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for d in drivers:
        cur.execute("""
            INSERT OR REPLACE INTO drivers
                (driver_number, full_name, team_name, country_code, session_key)
            VALUES (?, ?, ?, ?, ?)
        """, (
            d.get("driver_number"),
            d.get("full_name", "Unknown"),
            d.get("team_name", "Unknown"),
            d.get("country_code", "?"),
            session_key,
        ))
    conn.commit()
    conn.close()


def save_laps(laps: list, session_key: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for lap in laps:
        dur = lap.get("lap_duration")
        if dur is None:
            continue
        cur.execute("""
            INSERT INTO lap_times (driver_number, lap_number, lap_duration, session_key)
            VALUES (?, ?, ?, ?)
        """, (
            lap.get("driver_number"),
            lap.get("lap_number"),
            dur,
            session_key,
        ))
    conn.commit()
    conn.close()


def count_drivers() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM drivers")
    n = cur.fetchone()[0]
    conn.close()
    return n


def fetch_avg_lap_times() -> list[tuple]:
    """Retourne [(full_name, team_name, avg_duration)] triés par avg."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT d.full_name, d.team_name, AVG(l.lap_duration) as avg_lap
        FROM lap_times l
        JOIN drivers d ON d.driver_number = l.driver_number
        GROUP BY l.driver_number
        ORDER BY avg_lap ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_best_laps() -> list[tuple]:
    """Retourne [(full_name, team_name, min_duration)] triés."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT d.full_name, d.team_name, MIN(l.lap_duration) as best_lap
        FROM lap_times l
        JOIN drivers d ON d.driver_number = l.driver_number
        GROUP BY l.driver_number
        ORDER BY best_lap ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


# ─── API ─────────────────────────────────────────────────────────────────────

def get_latest_session() -> dict | None:
    """
    Cible directement la saison 2024 (données garanties sur OpenF1).
    Evite les sessions 2025/2026 dont les tours ne sont pas encore indexés.
    """
    resp = requests.get(
        f"{API_BASE}/sessions",
        params={"session_type": "Race", "year": 2024},
        timeout=10,
    )
    resp.raise_for_status()
    sessions = resp.json()
    if sessions:
        return sessions[-1]  # Abu Dhabi 2024 – données complètes garanties
    # Fallback absolu
    return {"session_key": 9673, "meeting_name": "Abu Dhabi", "session_name": "Race", "year": 2024}


def get_drivers(session_key: int) -> list:
    resp = requests.get(f"{API_BASE}/drivers", params={"session_key": session_key}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_laps(session_key: int, driver_number: int) -> list:
    resp = requests.get(
        f"{API_BASE}/laps",
        params={"session_key": session_key, "driver_number": driver_number},
        timeout=15,
    )
    # 404 = pas de données pour ce pilote dans cette session → on renvoie liste vide
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return resp.json()


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}:{secs:06.3f}"


# ─── APPLICATION ─────────────────────────────────────────────────────────────

class F1App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🏎️  F1 Data Explorer – OpenF1")
        self.geometry("1100x750")
        self.resizable(True, True)

        self._bg = "#1a1a2e"
        self._fg = "#e0e0e0"
        self._accent = "#e8002d"
        self._btn_bg = "#16213e"

        self.configure(bg=self._bg)
        self._canvas_widget = None
        self._current_session = None

        init_db()
        self._build_menu()
        self._build_ui()
        self.set_status("Prêt — aucune donnée chargée.")

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self, bg=self._btn_bg, fg=self._fg, tearoff=False)

        data_menu = tk.Menu(menubar, tearoff=False, bg=self._btn_bg, fg=self._fg)
        data_menu.add_command(label="📥  Télécharger données F1", command=self._download_threaded)
        data_menu.add_separator()
        data_menu.add_command(label="🗑️  Effacer la base", command=self._confirm_clear)
        menubar.add_cascade(label="Données", menu=data_menu)

        view_menu = tk.Menu(menubar, tearoff=False, bg=self._btn_bg, fg=self._fg)
        view_menu.add_command(label="📊  Graphique temps de tour", command=self._show_chart)
        view_menu.add_command(label="🏆  Meilleurs tours", command=self._show_best_laps)
        menubar.add_cascade(label="Affichage", menu=view_menu)

        options_menu = tk.Menu(menubar, tearoff=False, bg=self._btn_bg, fg=self._fg)
        options_menu.add_command(label="🎨  Couleur de fond…", command=self._pick_bg_color)
        options_menu.add_command(label="🔤  Changer police…", command=self._pick_font)
        menubar.add_cascade(label="Options", menu=options_menu)

        self.config(menu=menubar)

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=self._accent, height=50)
        header.pack(fill="x")
        tk.Label(
            header, text="🏎️  F1 Data Explorer",
            font=("Arial", 20, "bold"), bg=self._accent, fg="white"
        ).pack(side="left", padx=20, pady=8)

        # Toolbar
        toolbar = tk.Frame(self, bg=self._btn_bg, pady=6)
        toolbar.pack(fill="x")

        for label, cmd in [
            ("📥 Télécharger", self._download_threaded),
            ("🗑️ Effacer DB", self._confirm_clear),
            ("📊 Graphique", self._show_chart),
            ("🏆 Meilleurs tours", self._show_best_laps),
            ("📈 Agrégation SQL", self._show_aggregation),
        ]:
            tk.Button(
                toolbar, text=label, command=cmd,
                bg=self._accent, fg="white",
                font=("Arial", 10, "bold"),
                relief="flat", padx=12, pady=4, cursor="hand2",
                activebackground="#c0001e", activeforeground="white",
            ).pack(side="left", padx=6)

        # Session info
        self.session_frame = tk.Frame(self, bg=self._bg)
        self.session_frame.pack(fill="x", padx=15, pady=(10, 0))
        self.session_label = tk.Label(
            self.session_frame, text="Session : —",
            font=("Arial", 11), bg=self._bg, fg="#aaaaaa"
        )
        self.session_label.pack(side="left")

        # Main content paned
        self.pane = tk.PanedWindow(self, orient="horizontal", bg=self._bg, sashwidth=6)
        self.pane.pack(fill="both", expand=True, padx=10, pady=10)

        # Left: table
        left_frame = tk.Frame(self.pane, bg=self._bg)
        self.pane.add(left_frame, minsize=380)

        tk.Label(
            left_frame, text="Classement (temps moyen au tour)",
            font=("Arial", 12, "bold"), bg=self._bg, fg=self._fg
        ).pack(anchor="w", pady=(0, 5))

        cols = ("Pos", "Pilote", "Équipe", "Moy. tour")
        self.tree = ttk.Treeview(left_frame, columns=cols, show="headings", height=22)
        for col, w in zip(cols, [50, 150, 160, 100]):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#16213e", foreground=self._fg,
                        fieldbackground="#16213e", rowheight=24)
        style.configure("Treeview.Heading", background=self._accent, foreground="white",
                        font=("Arial", 10, "bold"))

        sb = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Right: chart area
        self.chart_frame = tk.Frame(self.pane, bg=self._bg)
        self.pane.add(self.chart_frame, minsize=400)

        self.chart_placeholder = tk.Label(
            self.chart_frame,
            text="📊\n\nTéléchargez des données\npuis cliquez sur 'Graphique'",
            font=("Arial", 13), bg=self._bg, fg="#555577",
            justify="center",
        )
        self.chart_placeholder.pack(expand=True)

        # Status bar
        self.status_var = tk.StringVar(value="")
        self.status_bar = tk.Label(
            self, textvariable=self.status_var,
            bg="#0d0d1a", fg="#888888",
            font=("Arial", 9), anchor="w", padx=10, pady=4,
            relief="sunken",
        )
        self.status_bar.pack(fill="x", side="bottom")

    # ── Download ──────────────────────────────────────────────────────────────

    def _download_threaded(self):
        if count_drivers() > 0:
            if not messagebox.askyesno(
                "Base non vide",
                "Des données existent déjà.\nVoulez-vous les remplacer ?"
            ):
                return
            clear_db()
        self.set_status("⏳ Connexion à OpenF1…")
        t = threading.Thread(target=self._download_data, daemon=True)
        t.start()

    def _download_data(self):
        try:
            self.set_status("⏳ Récupération de la session Abu Dhabi 2024…")
            session = get_latest_session()
            if not session:
                self.set_status("❌ Aucune session trouvée.")
                return
            self._current_session = session
            session_key = session["session_key"]
            session_name = f"{session.get('meeting_name', '?')} – {session.get('session_name', '?')} ({session.get('year', '?')})"
            self.after(0, lambda: self.session_label.config(text=f"Session : {session_name}"))

            self.set_status("⏳ Récupération des pilotes…")
            time.sleep(1)  # pause anti-rate-limit
            drivers = get_drivers(session_key)
            save_drivers(drivers, session_key)

            # 20 pilotes avec 2s de pause entre chaque pour éviter le 429
            drivers_limited = drivers[:20]
            total = len(drivers_limited)
            for i, driver in enumerate(drivers_limited):
                dn = driver.get("driver_number")
                self.set_status(f"⏳ Tours pilote {driver.get('full_name', dn)} ({i+1}/{total})…")
                time.sleep(2)
                laps = get_laps(session_key, dn)
                save_laps(laps, session_key)

            self.set_status(f"✅ Données chargées : {count_drivers()} pilotes, session {session_name}")
            self.after(0, self._refresh_table)
        except requests.RequestException as e:
            self.set_status(f"❌ Erreur réseau : {e}")
        except Exception as e:
            self.set_status(f"❌ Erreur inattendue : {e}")

    # ── Table refresh ─────────────────────────────────────────────────────────

    def _refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        rows = fetch_avg_lap_times()
        for i, (name, team, avg) in enumerate(rows, start=1):
            color = TEAM_COLORS.get(team, DEFAULT_COLOR)
            tag = f"team_{i}"
            self.tree.tag_configure(tag, foreground=color)
            self.tree.insert("", "end", values=(i, name, team, format_time(avg)), tags=(tag,))

    # ── Aggregation ───────────────────────────────────────────────────────────

    def _show_aggregation(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT driver_number) FROM lap_times")
        nb_drivers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM lap_times")
        nb_laps = cur.fetchone()[0]
        cur.execute("SELECT AVG(lap_duration) FROM lap_times")
        avg_global = cur.fetchone()[0]
        cur.execute("SELECT MIN(lap_duration) FROM lap_times")
        best = cur.fetchone()[0]
        cur.execute("""
            SELECT d.full_name FROM lap_times l
            JOIN drivers d ON d.driver_number = l.driver_number
            ORDER BY l.lap_duration ASC LIMIT 1
        """)
        best_driver = (cur.fetchone() or ["—"])[0]
        conn.close()

        msg = (
            f"📊 Agrégation SQL – Résultats\n\n"
            f"Pilotes analysés  : {nb_drivers}\n"
            f"Total tours       : {nb_laps}\n"
            f"Moy. globale      : {format_time(avg_global)}\n"
            f"Meilleur tour     : {format_time(best)}\n"
            f"  → par : {best_driver}"
        )
        messagebox.showinfo("Agrégation SQL", msg)

    # ── Chart ─────────────────────────────────────────────────────────────────

    def _show_chart(self):
        rows = fetch_avg_lap_times()
        if not rows:
            messagebox.showwarning("Pas de données", "Téléchargez d'abord les données.")
            return
        self._render_chart(rows, kind="avg")

    def _show_best_laps(self):
        rows = fetch_best_laps()
        if not rows:
            messagebox.showwarning("Pas de données", "Téléchargez d'abord les données.")
            return
        self._render_chart(rows, kind="best")

    def _render_chart(self, rows: list, kind: str = "avg"):
        # Clear previous chart
        if self._canvas_widget:
            self._canvas_widget.get_tk_widget().destroy()
        self.chart_placeholder.pack_forget()

        names = [r[0].split()[-1] for r in rows]  # last name
        teams = [r[1] for r in rows]
        times = [r[2] for r in rows]
        colors = [TEAM_COLORS.get(t, DEFAULT_COLOR) for t in teams]

        fig, ax = plt.subplots(figsize=(6, 5.5))
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#16213e")

        bars = ax.barh(names[::-1], times[::-1], color=colors[::-1], edgecolor="#333355")
        ax.set_xlabel(
            "Temps moyen (s)" if kind == "avg" else "Meilleur tour (s)",
            color=self._fg, fontsize=10
        )
        title = "Temps moyen par pilote" if kind == "avg" else "Meilleur tour par pilote"
        ax.set_title(title, color="white", fontsize=13, fontweight="bold")
        ax.tick_params(colors=self._fg, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333355")

        # Format x-axis as M:SS.mmm
        def fmt_seconds(x, _):
            m = int(x // 60)
            s = x % 60
            return f"{m}:{s:05.2f}"
        import matplotlib.ticker as ticker
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(fmt_seconds))

        # Value labels
        for bar, val in zip(bars, times[::-1]):
            ax.text(
                bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                format_time(val), va="center", color=self._fg, fontsize=7
            )

        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_widget = canvas
        plt.close(fig)

    # ── Options ───────────────────────────────────────────────────────────────

    def _pick_bg_color(self):
        color = colorchooser.askcolor(title="Couleur de fond", color=self._bg)
        if color and color[1]:
            self._bg = color[1]
            self.configure(bg=self._bg)
            for widget in (self.session_frame, self.chart_frame):
                widget.configure(bg=self._bg)

    def _pick_font(self):
        win = tk.Toplevel(self, bg=self._bg)
        win.title("Choisir une police")
        win.geometry("300x180")
        families = ["Arial", "Helvetica", "Courier New", "Georgia", "Verdana", "Tahoma"]
        tk.Label(win, text="Famille :", bg=self._bg, fg=self._fg).pack(pady=(15, 0))
        var = tk.StringVar(value="Arial")
        combo = ttk.Combobox(win, values=families, textvariable=var, state="readonly")
        combo.pack(pady=5)
        sizes = [9, 10, 11, 12, 14]
        tk.Label(win, text="Taille :", bg=self._bg, fg=self._fg).pack()
        size_var = tk.IntVar(value=11)
        ttk.Combobox(win, values=sizes, textvariable=size_var, state="readonly", width=6).pack(pady=5)

        def apply():
            new_font = (var.get(), size_var.get())
            self.session_label.config(font=new_font)
            win.destroy()
            self.set_status(f"Police appliquée : {var.get()} {size_var.get()}pt")

        tk.Button(win, text="Appliquer", command=apply,
                  bg=self._accent, fg="white", relief="flat", padx=10).pack(pady=10)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _confirm_clear(self):
        if messagebox.askyesno("Confirmation", "Effacer toutes les données de la base ?"):
            clear_db()
            for row in self.tree.get_children():
                self.tree.delete(row)
            self.session_label.config(text="Session : —")
            self.set_status("🗑️ Base de données vidée.")

    def set_status(self, msg: str):
        self.status_var.set(f"  {datetime.now().strftime('%H:%M:%S')}  |  {msg}")


# ─── TESTS UNITAIRES ─────────────────────────────────────────────────────────

def _run_unit_tests():
    """Lance les tests unitaires de base (sans interface graphique)."""
    import unittest

    class TestHelpers(unittest.TestCase):
        def test_format_time_zero(self):
            self.assertEqual(format_time(0), "0:00.000")

        def test_format_time_normal(self):
            self.assertEqual(format_time(90.123), "1:30.123")

        def test_format_time_none(self):
            self.assertEqual(format_time(None), "—")

        def test_format_time_sub_minute(self):
            result = format_time(75.5)
            self.assertTrue(result.startswith("1:"))

    class TestDB(unittest.TestCase):
        TEST_DB = "test_f1.db"

        def setUp(self):
            global DB_PATH
            self._orig = DB_PATH
            DB_PATH = self.TEST_DB
            init_db()

        def tearDown(self):
            global DB_PATH
            DB_PATH = self._orig
            if os.path.exists(self.TEST_DB):
                os.remove(self.TEST_DB)

        def test_save_and_count(self):
            save_drivers([{"driver_number": 1, "full_name": "Max Verstappen",
                           "team_name": "Red Bull Racing", "country_code": "NL"}], 9999)
            self.assertEqual(count_drivers(), 1)

        def test_clear_db(self):
            save_drivers([{"driver_number": 1, "full_name": "Test Driver",
                           "team_name": "Ferrari", "country_code": "IT"}], 9999)
            clear_db()
            self.assertEqual(count_drivers(), 0)

        def test_save_laps(self):
            save_drivers([{"driver_number": 44, "full_name": "Lewis Hamilton",
                           "team_name": "Mercedes", "country_code": "GB"}], 9999)
            save_laps([
                {"driver_number": 44, "lap_number": 1, "lap_duration": 91.2},
                {"driver_number": 44, "lap_number": 2, "lap_duration": 90.5},
            ], 9999)
            rows = fetch_avg_lap_times()
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(rows[0][2], 90.85, places=2)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestDB))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if "--tests" in sys.argv:
        _run_unit_tests()
    else:
        app = F1App()
        app.mainloop()