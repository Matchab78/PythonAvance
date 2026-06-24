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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key   INTEGER,
            race_label    TEXT,
            date_start    TEXT,
            position      INTEGER,
            driver_number INTEGER,
            full_name     TEXT,
            team_name     TEXT,
            status        TEXT,
            duration      REAL,
            gap           TEXT
        )
    """)
    # Migration douce : ajoute les colonnes si la table existait déjà sans elles
    for col, typ in (("duration", "REAL"), ("gap", "TEXT")):
        try:
            cur.execute(f"ALTER TABLE race_results ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()


def clear_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM drivers")
    cur.execute("DELETE FROM lap_times")
    cur.execute("DELETE FROM race_results")
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


def fetch_avg_lap_times() -> list:
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


def fetch_best_laps() -> list:
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


def save_race_results(session: dict, results: list, drivers: list):
    """Stocke le classement d'une course (dénormalisé : nom/équipe/temps inclus)."""
    dmap = {
        d.get("driver_number"): (d.get("full_name", "Unknown"), d.get("team_name", "Unknown"))
        for d in drivers
    }
    sk = session.get("session_key")
    label = race_label(session)
    date_start = session.get("date_start", "")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM race_results WHERE session_key = ?", (sk,))  # anti-doublon
    for r in results:
        dn = r.get("driver_number")
        name, team = dmap.get(dn, (f"#{dn}", "Unknown"))
        status = (
            "DNF" if r.get("dnf") else
            "DNS" if r.get("dns") else
            "DSQ" if r.get("dsq") else ""
        )
        duration = _num_or_none(r.get("duration"))
        gap_raw = r.get("gap_to_leader")
        gap = str(gap_raw) if gap_raw is not None else None
        cur.execute("""
            INSERT INTO race_results
                (session_key, race_label, date_start, position,
                 driver_number, full_name, team_name, status, duration, gap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sk, label, date_start, r.get("position"), dn, name, team, status, duration, gap))
    conn.commit()
    conn.close()


def fetch_races_list() -> list:
    """[(session_key, race_label, date_start)] triés par date."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT session_key, race_label, MIN(date_start)
        FROM race_results
        GROUP BY session_key, race_label
        ORDER BY MIN(date_start) ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_race_result(session_key: int) -> list:
    """[(position, full_name, team_name, status, duration, gap)] triés."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT position, full_name, team_name, status, duration, gap
        FROM race_results
        WHERE session_key = ?
        ORDER BY CASE WHEN position IS NULL THEN 9999 ELSE position END ASC
    """, (session_key,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ─── API ─────────────────────────────────────────────────────────────────────

def _api_get(endpoint: str, params: dict, timeout: int = 15, retries: int = 4) -> list:
    """GET vers OpenF1 avec gestion du rate-limit (429) : back-off progressif."""
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(retries):
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(5 * (attempt + 1))   # 5s, 10s, 15s, 20s
            continue
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()
    raise requests.RequestException(f"429 persistant sur /{endpoint} apres {retries} essais")


def get_all_races(year: int = 2024) -> list:
    """Toutes les sessions de type Race pour une saison."""
    return _api_get("sessions", {"session_type": "Race", "year": year})


def get_session_result(session_key: int) -> list:
    """Classement final d'une session via /session_result."""
    return _api_get("session_result", {"session_key": session_key})


def get_drivers(session_key: int) -> list:
    return _api_get("drivers", {"session_key": session_key})


def get_laps(session_key: int, driver_number: int) -> list:
    return _api_get("laps", {"session_key": session_key, "driver_number": driver_number})


def race_label(session: dict) -> str:
    """Nom lisible d'un GP (meeting_name absent de /sessions -> fallbacks)."""
    for key in ("country_name", "location", "circuit_short_name", "meeting_name"):
        v = session.get(key)
        if v:
            return str(v)
    return f"Session {session.get('session_key', '?')}"


def _num_or_none(v):
    """Normalise un champ API qui peut être nombre, liste ou None."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        for x in v:
            if isinstance(x, (int, float)):
                return float(x)
    return None


def format_time(seconds) -> str:
    """Temps de tour M:SS.mmm."""
    if seconds is None:
        return "—"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}:{secs:06.3f}"


def format_total(seconds) -> str:
    """Temps total de course en H:MM:SS.mmm (ou M:SS.mmm si < 1h)."""
    if seconds is None:
        return "—"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:06.3f}" if h else f"{m}:{s:06.3f}"


def format_gap(gap_text) -> str:
    """Écart au leader : nombre -> +12.345, ou texte brut (ex: '+1 LAP')."""
    if gap_text in (None, ""):
        return ""
    try:
        return f"+{float(gap_text):.3f}"
    except (ValueError, TypeError):
        return str(gap_text)


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
        self._refresh_races_combo()  # réaffiche les courses déjà en base

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self, bg=self._btn_bg, fg=self._fg, tearoff=False)

        data_menu = tk.Menu(menubar, tearoff=False, bg=self._btn_bg, fg=self._fg)
        data_menu.add_command(label="📥  Télécharger les données F1", command=self._download_threaded)
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

        # Session info + agrégation
        self.session_frame = tk.Frame(self, bg=self._bg)
        self.session_frame.pack(fill="x", padx=15, pady=(10, 0))
        self.session_label = tk.Label(
            self.session_frame, text="Session : —",
            font=("Arial", 11), bg=self._bg, fg="#aaaaaa"
        )
        self.session_label.pack(side="left")
        self.agg_var = tk.StringVar(value="")
        self.agg_label = tk.Label(
            self.session_frame, textvariable=self.agg_var,
            font=("Consolas", 10), bg=self._bg, fg="#7fd1ff",
            justify="right", anchor="e"
        )
        self.agg_label.pack(side="right", padx=10)

        # Styles communs (Treeview + Notebook)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#16213e", foreground=self._fg,
                        fieldbackground="#16213e", rowheight=24)
        style.configure("Treeview.Heading", background=self._accent, foreground="white",
                        font=("Arial", 10, "bold"))
        style.configure("TNotebook", background=self._bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=self._btn_bg, foreground=self._fg,
                        padding=(16, 6), font=("Arial", 10, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", self._accent)],
                  foreground=[("selected", "white")])

        # Notebook (onglets)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # ===== Onglet 1 : Dernière course =====
        tab_last = tk.Frame(self.notebook, bg=self._bg)
        self.notebook.add(tab_last, text="  Dernière course  ")

        self.pane = tk.PanedWindow(tab_last, orient="horizontal", bg=self._bg, sashwidth=6)
        self.pane.pack(fill="both", expand=True)

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

        # ===== Onglet 2 : Courses (saison) =====
        tab_season = tk.Frame(self.notebook, bg=self._bg)
        self.notebook.add(tab_season, text="  🏁 Courses (saison)  ")

        top = tk.Frame(tab_season, bg=self._bg)
        top.pack(fill="x", pady=(8, 6))
        tk.Label(top, text="Grand Prix :", font=("Arial", 11, "bold"),
                 bg=self._bg, fg=self._fg).pack(side="left", padx=(0, 8))
        self.race_var = tk.StringVar()
        self.race_combo = ttk.Combobox(top, textvariable=self.race_var,
                                       state="readonly", width=45)
        self.race_combo.pack(side="left")
        self.race_combo.bind("<<ComboboxSelected>>", self._on_race_selected)

        race_body = tk.Frame(tab_season, bg=self._bg)
        race_body.pack(fill="both", expand=True)
        rcols = ("Pos", "Pilote", "Équipe", "Temps / Écart", "Statut")
        self.race_tree = ttk.Treeview(race_body, columns=rcols, show="headings", height=24)
        for col, w in zip(rcols, [60, 200, 190, 140, 80]):
            self.race_tree.heading(col, text=col)
            self.race_tree.column(col, width=w, anchor="center")
        rsb = ttk.Scrollbar(race_body, orient="vertical", command=self.race_tree.yview)
        self.race_tree.configure(yscrollcommand=rsb.set)
        self.race_tree.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")

        self._races_index = {}  # display label -> session_key

        # Status bar
        self.status_var = tk.StringVar(value="")
        self.status_bar = tk.Label(
            self, textvariable=self.status_var,
            bg="#0d0d1a", fg="#888888",
            font=("Arial", 9), anchor="w", padx=10, pady=4,
            relief="sunken",
        )
        self.status_bar.pack(fill="x", side="bottom")

    # ── Download UNIQUE (saison + dernière course) ──────────────────────────

    def _download_threaded(self):
        if count_drivers() > 0:
            if not messagebox.askyesno(
                "Base non vide",
                "Des données existent déjà.\nVoulez-vous les remplacer ?"
            ):
                return
            clear_db()
        self.set_status("⏳ Connexion à OpenF1…")
        threading.Thread(target=self._download_all, daemon=True).start()

    def _download_all(self):
        """
        Un seul téléchargement qui remplit TOUT :
          - race_results        -> onglet 'Courses (saison)'
          - drivers + lap_times -> onglet 'Dernière course' + graphiques
        """
        try:
            self.set_status("⏳ Récupération du calendrier 2024…")
            races = get_all_races(2024)
            if not races:
                self.set_status("❌ Aucune course trouvée pour 2024.")
                return

            total = len(races)
            last_session = races[-1]
            last_key = last_session.get("session_key")
            last_drivers = []

            # ── 1) Classements de TOUTES les courses ──
            for i, session in enumerate(races, start=1):
                sk = session.get("session_key")
                label = race_label(session)
                self.set_status(f"⏳ [{i}/{total}] {label} — classement…")
                time.sleep(2.5)  # anti rate-limit (retry géré par _api_get)
                drivers = get_drivers(sk)
                results = get_session_result(sk)
                if results:
                    save_race_results(session, results, drivers)
                if sk == last_key:
                    last_drivers = drivers  # réutilisés pour les tours

            self.after(0, self._refresh_races_combo)

            # ── 2) Tours détaillés de la dernière course ──
            session_name = f"{race_label(last_session)} – Race ({last_session.get('year', '?')})"
            self._current_session = last_session
            self.after(0, lambda: self.session_label.config(text=f"Session : {session_name}"))

            if not last_drivers:
                last_drivers = get_drivers(last_key)
            save_drivers(last_drivers, last_key)

            drivers_limited = last_drivers[:20]
            nlast = len(drivers_limited)
            for j, driver in enumerate(drivers_limited, start=1):
                dn = driver.get("driver_number")
                self.set_status(f"⏳ Tours {driver.get('full_name', dn)} ({j}/{nlast})…")
                time.sleep(2.5)
                laps = get_laps(last_key, dn)
                save_laps(laps, last_key)

            self.after(0, self._refresh_table)
            self.set_status(
                f"✅ Terminé : {total} GP chargés + tours de {race_label(last_session)} "
                f"({count_drivers()} pilotes)."
            )
        except requests.RequestException as e:
            self.set_status(f"❌ Erreur réseau : {e}")
        except Exception as e:
            self.set_status(f"❌ Erreur inattendue : {e}")

    def _refresh_races_combo(self):
        rows = fetch_races_list()
        self._races_index = {}
        labels = []
        for sk, label, date_start in rows:
            display = label + (f"  ({date_start[:10]})" if date_start else "")
            self._races_index[display] = sk
            labels.append(display)
        self.race_combo["values"] = labels
        if labels:
            self.race_combo.current(len(labels) - 1)  # dernière course par défaut
            self._on_race_selected()

    def _on_race_selected(self, event=None):
        sk = self._races_index.get(self.race_var.get())
        if sk is None:
            return
        for row in self.race_tree.get_children():
            self.race_tree.delete(row)
        for pos, name, team, status, duration, gap in fetch_race_result(sk):
            color = TEAM_COLORS.get(team, DEFAULT_COLOR)
            tag = f"rteam_{name}"
            self.race_tree.tag_configure(tag, foreground=color)
            pos_txt = str(pos) if pos is not None else (status or "—")
            if status:
                time_txt = "—"
            elif pos == 1:
                time_txt = format_total(duration)      # vainqueur : temps total
            else:
                time_txt = format_gap(gap) or "—"       # autres : écart au leader
            self.race_tree.insert("", "end",
                                  values=(pos_txt, name, team, time_txt, status or "—"),
                                  tags=(tag,))
        self.set_status(f"🏁 Classement affiché : {self.race_var.get()}")

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

        if nb_laps == 0:
            self.agg_var.set("Aucune donnée — téléchargez d'abord.")
            self.set_status("⚠️ Agrégation : base vide.")
            return

        self.agg_var.set(
            f"📊 {nb_drivers} pilotes  |  {nb_laps} tours  |  "
            f"Moy. {format_time(avg_global)}  |  "
            f"Meilleur {format_time(best)} ({best_driver})"
        )
        self.set_status("📈 Agrégation SQL calculée et affichée.")

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
            # Onglet courses
            self.race_combo.set("")
            self.race_combo["values"] = []
            self._races_index = {}
            for row in self.race_tree.get_children():
                self.race_tree.delete(row)
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

        def test_race_label_fallback(self):
            self.assertEqual(race_label({"country_name": "Italy"}), "Italy")
            self.assertEqual(race_label({"location": "Monza"}), "Monza")
            self.assertEqual(race_label({"session_key": 42}), "Session 42")

        def test_format_total(self):
            self.assertEqual(format_total(None), "—")
            self.assertEqual(format_total(95.5), "1:35.500")          # < 1h
            self.assertEqual(format_total(5504.742), "1:31:44.742")   # > 1h

        def test_format_gap(self):
            self.assertEqual(format_gap(None), "")
            self.assertEqual(format_gap(7.313), "+7.313")
            self.assertEqual(format_gap("+1 LAP"), "+1 LAP")

        def test_num_or_none(self):
            self.assertEqual(_num_or_none(12.5), 12.5)
            self.assertEqual(_num_or_none([3.0, 4.0]), 3.0)
            self.assertIsNone(_num_or_none(None))
            self.assertIsNone(_num_or_none("abc"))

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

        def test_null_lap_ignored(self):
            save_drivers([{"driver_number": 16, "full_name": "Charles Leclerc",
                           "team_name": "Ferrari", "country_code": "MC"}], 9999)
            save_laps([
                {"driver_number": 16, "lap_number": 1, "lap_duration": None},
                {"driver_number": 16, "lap_number": 2, "lap_duration": 92.0},
            ], 9999)
            rows = fetch_avg_lap_times()
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(rows[0][2], 92.0, places=2)

        def test_save_and_fetch_race_results(self):
            session = {"session_key": 1234, "country_name": "Bahrain",
                       "date_start": "2024-03-02T15:00:00"}
            drivers = [
                {"driver_number": 1, "full_name": "Max Verstappen", "team_name": "Red Bull Racing"},
                {"driver_number": 16, "full_name": "Charles Leclerc", "team_name": "Ferrari"},
            ]
            results = [
                {"driver_number": 1, "position": 1, "duration": 5504.742},
                {"driver_number": 16, "position": 2, "dnf": True, "gap_to_leader": 22.5},
            ]
            save_race_results(session, results, drivers)
            races = fetch_races_list()
            self.assertEqual(len(races), 1)
            self.assertEqual(races[0][1], "Bahrain")
            classement = fetch_race_result(1234)
            # (position, full_name, team_name, status, duration, gap)
            self.assertEqual(classement[0][1], "Max Verstappen")     # P1
            self.assertAlmostEqual(classement[0][4], 5504.742, 2)    # duration vainqueur
            self.assertEqual(classement[1][3], "DNF")                # statut Leclerc

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