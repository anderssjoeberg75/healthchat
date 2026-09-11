"""
COROS-Inspired Light Theme Graphical Views for HealthChat Desktop.
Features:
- Hälsa (Health) View: Landing page with RHR, HRV, Sleep, Body Battery/Stress, Weight, Recovery, and Calorie Burn
- Träning (Training) View: Fitness Index, Load Impact, HR Zones, Volume & Calories, Activity Breakdown & Activity Log
- Senaste Pass & Logg View: Full expandable Activity History List
- Light Theme Palette (#F3F4F6 background, #FFFFFF clean cards, #0078D4 blue accent, #FF5722 coral highlights)
"""

import tkinter as tk
from tkinter import ttk
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from garmin_db import GarminDatabase
import calorie_calc
import hr_zones_calc

logger = logging.getLogger("charts_view")


class HealthChartsView(ttk.Frame):
    """COROS-Inspired Graphical Health & Training View Manager."""

    def __init__(self, parent, db: GarminDatabase, colors: Dict[str, str], on_toggle_chat=None, on_checkin=None, profile: Optional[Dict[str, Any]] = None, ai_client_getter=None):
        super().__init__(parent, style='Main.TFrame')
        self.db = db
        self.colors = colors
        self.days_range = 30
        self.active_tab = "health"
        self.on_toggle_chat_callback = on_toggle_chat
        self.on_checkin_callback = on_checkin
        # User profile used for the calorie-burn estimate (sex/height/age/weight).
        self.profile = profile or {}
        self.ai_client_getter = ai_client_getter

        self.setup_ui()
        self.refresh_all_views()

    def _trigger_checkin(self):
        """Invoke on_checkin_callback if registered."""
        if callable(self.on_checkin_callback):
            self.on_checkin_callback()

    def set_profile(self, profile: Optional[Dict[str, Any]]):
        """Update the user profile (sex/height/age/weight) and refresh the calorie card."""
        self.profile = profile or {}
        try:
            self.refresh_all_views()
        except Exception as e:
            logger.error(f"Error refreshing after profile update: {e}")

    def setup_ui(self):
        """Build main container with top navbar, tab controls, and scrollable content views."""
        # Ensure clean white card and label styles across all dashboard views
        style = ttk.Style()
        style.configure('Card.TFrame', background='#FFFFFF', relief='flat', borderwidth=1)
        style.configure('Card.TLabel', background='#FFFFFF', foreground='#1F2937', font=('Segoe UI', 10))
        style.configure('Heading.TLabel', background='#FFFFFF', foreground='#1F2937', font=('Segoe UI', 11, 'bold'))
        style.configure('Status.TLabel', background='#FFFFFF', foreground='#6B7280', font=('Segoe UI', 9))
        style.configure('TLabel', background='#FFFFFF', foreground='#1F2937', font=('Segoe UI', 10))

        # Top Navigation & Header Bar
        header = ttk.Frame(self, style='Card.TFrame', padding="10")
        header.pack(fill=tk.X, padx=15, pady=(15, 10))

        # Title & Subtitle
        title_frame = ttk.Frame(header, style='Card.TFrame')
        title_frame.pack(side=tk.LEFT, padx=5)

        ttk.Label(
            title_frame,
            text="📊 HealthChat Hub",
            font=('Segoe UI', 15, 'bold'),
            foreground=self.colors.get('accent', '#0078D4')
        ).pack(anchor=tk.W)

        self.sync_status_label = ttk.Label(
            title_frame,
            text="",
            font=('Segoe UI', 9, 'italic'),
            foreground='#F59E0B'
        )
        self.sync_status_label.pack(anchor=tk.W)

        # Right Controls: Range Selector
        controls_frame = ttk.Frame(header, style='Card.TFrame')
        controls_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(controls_frame, text="Tidsintervall:", font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 6))

        self.btn_7d = ttk.Button(controls_frame, text="7 Dagar", command=lambda: self.set_range(7), style='Modern.TButton')
        self.btn_7d.pack(side=tk.LEFT, padx=2)

        self.btn_30d = ttk.Button(controls_frame, text="30 Dagar", command=lambda: self.set_range(30), style='Accent.TButton')
        self.btn_30d.pack(side=tk.LEFT, padx=2)

        self.btn_90d = ttk.Button(controls_frame, text="90 Dagar", command=lambda: self.set_range(90), style='Modern.TButton')
        self.btn_90d.pack(side=tk.LEFT, padx=2)

        self.btn_1y = ttk.Button(controls_frame, text="1 År", command=lambda: self.set_range(365), style='Modern.TButton')
        self.btn_1y.pack(side=tk.LEFT, padx=2)

        self.btn_all = ttk.Button(controls_frame, text="Alla", command=lambda: self.set_range(3650), style='Modern.TButton')
        self.btn_all.pack(side=tk.LEFT, padx=2)

        ttk.Button(controls_frame, text="🔄 Uppdatera", command=self.refresh_all_views, style='Modern.TButton').pack(side=tk.LEFT, padx=(6, 0))

        # Top Navigation Tab Bar (COROS Style)
        nav_bar = ttk.Frame(self, style='Card.TFrame', padding="4")
        nav_bar.pack(fill=tk.X, padx=15, pady=(0, 10))

        self.tab_health_btn = ttk.Button(
            nav_bar, text="❤️ Hälsa", command=lambda: self.switch_tab("health"), style='Accent.TButton'
        )
        self.tab_health_btn.pack(side=tk.LEFT, padx=4)

        self.tab_training_btn = ttk.Button(
            nav_bar, text="🏃 Träning", command=lambda: self.switch_tab("training"), style='Modern.TButton'
        )
        self.tab_training_btn.pack(side=tk.LEFT, padx=4)

        self.tab_activities_btn = ttk.Button(
            nav_bar, text="📝 Senaste Pass & Logg", command=lambda: self.switch_tab("activities"), style='Modern.TButton'
        )
        self.tab_activities_btn.pack(side=tk.LEFT, padx=4)

        # Backwards compatibility aliases
        self.tab_dashboard_btn = self.tab_health_btn
        self.tab_evolab_btn = self.tab_health_btn

        # Check-in Button directly after navigation tabs
        self.dashboard_checkin_btn = ttk.Button(
            nav_bar, text="📥 Check-in", command=self._trigger_checkin, style='Accent.TButton'
        )
        self.dashboard_checkin_btn.pack(side=tk.LEFT, padx=(12, 4))

        # Fråga Coachen Button (Toggles AI Chat Panel)
        self.chat_toggle_btn = ttk.Button(
            nav_bar, text="💬 Fråga Coachen", command=self._trigger_toggle_chat, style='Accent.TButton'
        )
        self.chat_toggle_btn.pack(side=tk.RIGHT, padx=4)

        # Main Scrollable Content Container
        self.container_frame = ttk.Frame(self, style='Main.TFrame')
        self.container_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        # Create Tab Frames
        self.health_frame = ttk.Frame(self.container_frame, style='Main.TFrame')
        self.training_frame = ttk.Frame(self.container_frame, style='Main.TFrame')
        self.activities_frame = ttk.Frame(self.container_frame, style='Main.TFrame')

        self.dashboard_frame = self.health_frame  # Backwards compatibility alias
        self.evolab_frame = self.health_frame     # Backwards compatibility alias

        self.setup_health_tab()
        self.setup_training_tab()
        self.setup_activities_tab()

        # Show initial tab (Hälsa on startup)
        self.switch_tab("health")

    def _trigger_toggle_chat(self):
        """Invoke on_toggle_chat callback if registered."""
        if callable(self.on_toggle_chat_callback):
            self.on_toggle_chat_callback()

    def update_chat_button(self, is_open: bool):
        """Update text and style of Fråga Coachen button based on chat panel state."""
        if is_open:
            self.chat_toggle_btn.config(text="🤖 Dölj Coachen", style='Modern.TButton')
        else:
            self.chat_toggle_btn.config(text="💬 Fråga Coachen", style='Accent.TButton')

    def switch_tab(self, tab_name: str):
        """Switch active view tab."""
        if tab_name in ("dashboard", "evolab"):
            tab_name = "health"
        self.active_tab = tab_name
        for f in (self.health_frame, self.training_frame, self.activities_frame):
            f.pack_forget()

        self.tab_health_btn.config(style='Accent.TButton' if tab_name == "health" else 'Modern.TButton')
        self.tab_training_btn.config(style='Accent.TButton' if tab_name == "training" else 'Modern.TButton')
        self.tab_activities_btn.config(style='Accent.TButton' if tab_name == "activities" else 'Modern.TButton')

        if tab_name == "health":
            self.health_frame.pack(fill=tk.BOTH, expand=True)
        elif tab_name == "training":
            self.training_frame.pack(fill=tk.BOTH, expand=True)
        elif tab_name == "activities":
            self.activities_frame.pack(fill=tk.BOTH, expand=True)

    def set_range(self, days: int):
        """Update date range and refresh charts across Health and Training."""
        self.days_range = days
        self.btn_7d.config(style='Accent.TButton' if days == 7 else 'Modern.TButton')
        self.btn_30d.config(style='Accent.TButton' if days == 30 else 'Modern.TButton')
        self.btn_90d.config(style='Accent.TButton' if days == 90 else 'Modern.TButton')
        self.btn_1y.config(style='Accent.TButton' if days == 365 else 'Modern.TButton')
        self.btn_all.config(style='Accent.TButton' if days >= 3650 else 'Modern.TButton')
        self.refresh_all_views()

    def set_sync_status(self, message: str, is_done: bool = False):
        """Update sync status label."""
        if is_done:
            self.sync_status_label.config(text=message, foreground='#10B981')
            self.after(4000, lambda: self.sync_status_label.config(text=""))
        else:
            self.sync_status_label.config(text=message, foreground='#F59E0B')

    # --- TAB 1: HÄLSA (LANDING PAGE - PURE HEALTH CARDS & CHARTS) ---

    def setup_health_tab(self):
        """Setup pure health view (Recovery, Weight, Calorie Cards + RHR, HRV, Sleep, Stress, Weight, Calorie charts)."""
        canvas = tk.Canvas(self.health_frame, bg='#F3F4F6', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.health_frame, orient="vertical", command=canvas.yview)
        scroll_content = ttk.Frame(canvas, style='Main.TFrame')

        scroll_content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 1. Top Health Summary Cards (3-column grid)
        grid_frame = ttk.Frame(scroll_content, style='Main.TFrame')
        grid_frame.pack(fill=tk.X, expand=True, padx=15, pady=(15, 5))

        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(2, weight=1)

        self.card_recovery = self.create_card(grid_frame, "🔋 Recovery Score & Efficiency", 0, 0)
        self.card_weight = self.create_card(grid_frame, "⚖️ Weight & Body Comp (Withings)", 0, 1)
        self.card_calories = self.create_card(grid_frame, "🔥 Kaloriförbränning idag", 0, 2)

        # 2. Matplotlib Figure for Health Analytics (4 rows x 2 columns grid)
        plt.style.use('default')
        self.fig_health = Figure(figsize=(11, 13.5), dpi=95, facecolor='#FFFFFF')
        self.fig_health.subplots_adjust(hspace=0.5, wspace=0.28, left=0.08, right=0.95, top=0.96, bottom=0.06)

        self.ax_health_weight = self.fig_health.add_subplot(4, 2, 1, facecolor='#FFFFFF')
        self.ax_health_calories = self.fig_health.add_subplot(4, 2, 2, facecolor='#FFFFFF')
        self.ax_health_rhr = self.fig_health.add_subplot(4, 2, 3, facecolor='#FFFFFF')
        self.ax_health_hrv = self.fig_health.add_subplot(4, 2, 4, facecolor='#FFFFFF')
        self.ax_health_sleep = self.fig_health.add_subplot(4, 2, 5, facecolor='#FFFFFF')
        self.ax_health_sleep_score = self.fig_health.add_subplot(4, 2, 6, facecolor='#FFFFFF')
        self.ax_health_bb = self.fig_health.add_subplot(4, 2, 7, facecolor='#FFFFFF')
        self.ax_health_stress = self.fig_health.add_subplot(4, 2, 8, facecolor='#FFFFFF')

        canvas_health = FigureCanvasTkAgg(self.fig_health, master=scroll_content)
        canvas_health.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        self.canvas_health = canvas_health

        # Aliases for backward compatibility
        self.fig_evo = self.fig_health
        self.canvas_evo = self.canvas_health
        self.ax_health_bb_stress = self.ax_health_bb
        self.ax_evo_rhr = self.ax_health_rhr
        self.ax_evo_hrv = self.ax_health_hrv
        self.ax_evo_weight = self.ax_health_weight
        self.ax_evo_calories = self.ax_health_calories

    def setup_dashboard_tab(self):
        """Backward compatibility setup alias."""
        pass

    def setup_evolab_tab(self):
        """Backward compatibility setup alias."""
        pass

    # --- TAB 2: TRÄNING (DEDICATED TRAINING METRICS, CHARTS & DATA) ---

    def setup_training_tab(self):
        """Setup dedicated training page (Fitness cards, Training load, HR zones, Volume & Activity log)."""
        canvas = tk.Canvas(self.training_frame, bg='#F3F4F6', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.training_frame, orient="vertical", command=canvas.yview)
        scroll_content = ttk.Frame(canvas, style='Main.TFrame')

        scroll_content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 1. Top Training Metric Cards (3-column responsive grid)
        grid_frame = ttk.Frame(scroll_content, style='Main.TFrame')
        grid_frame.pack(fill=tk.X, expand=True, padx=15, pady=(15, 5))

        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(2, weight=1)

        self.card_train_fitness = self.create_card(grid_frame, "🏃 Running & Fitness Index", 0, 0)
        self.card_train_status = self.create_card(grid_frame, "⚡ Training Status & Load Impact", 0, 1)
        self.card_train_summary = self.create_card(grid_frame, "📊 Träningsöversikt (Period)", 0, 2)

        # Backward compatibility aliases
        self.card_fitness = self.card_train_fitness
        self.card_training_status = self.card_train_status

        # 2. HR Zones & MAF Table Card ("Pulszoner & Maffetone MAF-puls") - DIREKT UNDER KORTEN
        hr_zones_card = ttk.Frame(scroll_content, style='Card.TFrame', padding="15")
        hr_zones_card.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 10))

        ttk.Label(hr_zones_card, text="❤️ Personliga Pulszoner & MAF-beräkning (Philip Maffetone)", font=('Segoe UI', 12, 'bold'), foreground='#1F2937').pack(anchor=tk.W, pady=(0, 8))

        self.hr_zones_card_body = ttk.Frame(hr_zones_card, style='Card.TFrame')
        self.hr_zones_card_body.pack(fill=tk.BOTH, expand=True)

        # 3. Training Charts (2x2 Grid)
        self.fig_training = Figure(figsize=(11, 7.5), dpi=95, facecolor='#FFFFFF')
        self.fig_training.subplots_adjust(hspace=0.48, wspace=0.28, left=0.08, right=0.95, top=0.93, bottom=0.08)

        self.ax_train_load = self.fig_training.add_subplot(2, 2, 1, facecolor='#FFFFFF')
        self.ax_train_zones = self.fig_training.add_subplot(2, 2, 2, facecolor='#FFFFFF')
        self.ax_train_volume = self.fig_training.add_subplot(2, 2, 3, facecolor='#FFFFFF')
        self.ax_train_types = self.fig_training.add_subplot(2, 2, 4, facecolor='#FFFFFF')

        # Backward compatibility alias
        self.ax_evo_load = self.ax_train_load
        self.ax_evo_zones = self.ax_train_zones
        self.ax_evo_dist = self.ax_train_volume

        canvas_training = FigureCanvasTkAgg(self.fig_training, master=scroll_content)
        canvas_training.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        self.canvas_training = canvas_training

        # 4. Embedded Training Data Table ("Data om träning")
        table_card = ttk.Frame(scroll_content, style='Card.TFrame', padding="15")
        table_card.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 15))

        ttk.Label(table_card, text="🏃 Registrerade Träningspass", font=('Segoe UI', 11, 'bold'), foreground='#1F2937').pack(anchor=tk.W, pady=(0, 8))

        tree_frame = ttk.Frame(table_card, style='Card.TFrame')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("date", "source", "name", "type", "distance", "duration", "calories", "hr")
        self.train_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8)

        self.train_tree.heading("date", text="Datum")
        self.train_tree.heading("source", text="Källa")
        self.train_tree.heading("name", text="Namn")
        self.train_tree.heading("type", text="Typ")
        self.train_tree.heading("distance", text="Distans (km)")
        self.train_tree.heading("duration", text="Tid (min)")
        self.train_tree.heading("calories", text="Kalorier (kcal)")
        self.train_tree.heading("hr", text="Snittpuls (bpm)")

        self.train_tree.column("date", width=100, anchor=tk.CENTER)
        self.train_tree.column("source", width=100, anchor=tk.CENTER)
        self.train_tree.column("name", width=200, anchor=tk.W)
        self.train_tree.column("type", width=130, anchor=tk.CENTER)
        self.train_tree.column("distance", width=100, anchor=tk.E)
        self.train_tree.column("duration", width=90, anchor=tk.E)
        self.train_tree.column("calories", width=100, anchor=tk.E)
        self.train_tree.column("hr", width=100, anchor=tk.E)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.train_tree.yview)
        self.train_tree.configure(yscroll=scrollbar.set)

        self.train_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # --- TAB 3: ACTIVITIES FEED & HISTORY ---

    def setup_activities_tab(self):
        """Setup full activities history list view."""
        card = ttk.Frame(self.activities_frame, style='Card.TFrame', padding="15")
        card.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        ttk.Label(card, text="📝 Senaste Pass & Aktivitetshistorik", font=('Segoe UI', 12, 'bold'), foreground='#1F2937').pack(anchor=tk.W, pady=(0, 10))

        # Scrollable Treeview
        tree_frame = ttk.Frame(card, style='Card.TFrame')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("date", "source", "name", "type", "distance", "duration", "calories", "hr")
        self.act_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)

        self.act_tree.heading("date", text="Datum")
        self.act_tree.heading("source", text="Källa")
        self.act_tree.heading("name", text="Namn")
        self.act_tree.heading("type", text="Typ")
        self.act_tree.heading("distance", text="Distans (km)")
        self.act_tree.heading("duration", text="Tid (min)")
        self.act_tree.heading("calories", text="Kalorier (kcal)")
        self.act_tree.heading("hr", text="Snittpuls (bpm)")

        self.act_tree.column("date", width=100, anchor=tk.CENTER)
        self.act_tree.column("source", width=100, anchor=tk.CENTER)
        self.act_tree.column("name", width=200, anchor=tk.W)
        self.act_tree.column("type", width=130, anchor=tk.CENTER)
        self.act_tree.column("distance", width=100, anchor=tk.E)
        self.act_tree.column("duration", width=90, anchor=tk.E)
        self.act_tree.column("calories", width=100, anchor=tk.E)
        self.act_tree.column("hr", width=100, anchor=tk.E)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.act_tree.yview)
        self.act_tree.configure(yscroll=scrollbar.set)

        self.act_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # --- UI HELPER: CREATE CARD CONTAINER ---

    def create_card(self, parent, title: str, row: int, col: int, columnspan: int = 1) -> Dict[str, Any]:
        """Create clean light card container."""
        card_frame = ttk.Frame(parent, style='Card.TFrame', padding="12")
        card_frame.grid(row=row, column=col, columnspan=columnspan, sticky="nsew", padx=8, pady=8)

        # Header
        header = ttk.Frame(card_frame, style='Card.TFrame')
        header.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            header,
            text=title,
            font=('Segoe UI', 10, 'bold'),
            foreground='#1F2937'
        ).pack(side=tk.LEFT)

        body = ttk.Frame(card_frame, style='Card.TFrame')
        body.pack(fill=tk.BOTH, expand=True)

        return {"frame": card_frame, "header": header, "body": body}

    # --- REFRESH ALL DATA & VIEWS ---

    def refresh_all_views(self):
        """Fetch database data in background thread and populate views asynchronously."""
        if not hasattr(self, 'db') or not self.db:
            return

        if getattr(self, '_refresh_in_progress', False):
            self._refresh_pending = True
            return

        self._refresh_in_progress = True
        days_range = self.days_range

        def _worker():
            try:
                full_days = max(365, days_range)
                daily_summary_hist = self.db.get_daily_summary_history(days_range)
                sleep_hist = self.db.get_sleep_history(days_range)
                bb_hist = self.db.get_body_battery_history(days_range)
                stress_hist = self.db.get_stress_history(days_range)
                hrv_hist = self.db.get_hrv_history(days_range)
                act_hist_full = self.db.get_activities_history(full_days)
                body_comp = self.db.get_latest_body_composition()
                body_comp_hist = self.db.get_body_composition_history(days_range)

                if full_days == days_range:
                    act_hist_dash = act_hist_full
                else:
                    cutoff_str = (datetime.now() - timedelta(days=days_range)).strftime('%Y-%m-%d')
                    act_hist_dash = [a for a in act_hist_full if str(a.get('date', '')) >= cutoff_str]

                data = {
                    "daily_summary_hist": daily_summary_hist,
                    "sleep_hist": sleep_hist,
                    "bb_hist": bb_hist,
                    "stress_hist": stress_hist,
                    "hrv_hist": hrv_hist,
                    "act_hist_dash": act_hist_dash,
                    "act_hist_full": act_hist_full,
                    "body_comp": body_comp,
                    "body_comp_hist": body_comp_hist
                }
                try:
                    self.after(0, lambda: self._apply_refreshed_data(data))
                except Exception:
                    self._refresh_in_progress = False
            except Exception as err:
                logger.error(f"Error in background data fetch: {err}")
                try:
                    self.after(0, self._on_refresh_finished)
                except Exception:
                    self._refresh_in_progress = False

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_refreshed_data(self, data: Dict[str, Any]):
        try:
            sleep_hist = data["sleep_hist"]
            bb_hist = data["bb_hist"]
            stress_hist = data["stress_hist"]
            hrv_hist = data["hrv_hist"]
            act_hist_dash = data["act_hist_dash"]
            act_hist_full = data["act_hist_full"]
            body_comp = data["body_comp"]
            body_comp_hist = data["body_comp_hist"]
            daily_summary_hist = data["daily_summary_hist"]

            try:
                self.update_health_cards(sleep_hist, bb_hist, stress_hist, body_comp, body_comp_hist)
            except Exception as e:
                logger.error(f"Error in update_health_cards: {e}")

            try:
                self.update_training_cards(act_hist_full, bb_hist)
            except Exception as e:
                logger.error(f"Error in update_training_cards: {e}")

            try:
                self.update_calorie_card(body_comp, act_hist_full)
            except Exception as e:
                logger.error(f"Error in update_calorie_card: {e}")

            try:
                self.draw_health_charts(sleep_hist, bb_hist, stress_hist, hrv_hist, body_comp, daily_summary_hist)
            except Exception as e:
                logger.error(f"Error in draw_health_charts: {e}")

            try:
                self.draw_training_charts(act_hist_dash)
            except Exception as e:
                logger.error(f"Error in draw_training_charts: {e}")

            try:
                self.populate_activities_table(act_hist_dash)
            except Exception as e:
                logger.error(f"Error in populate_activities_table: {e}")

            try:
                self.update_hr_zones_card(daily_summary_hist)
            except Exception as e:
                logger.error(f"Error in update_hr_zones_card: {e}")
        finally:
            self._on_refresh_finished()

    def _on_refresh_finished(self):
        self._refresh_in_progress = False
        if getattr(self, '_refresh_pending', False):
            self._refresh_pending = False
            self.refresh_all_views()

    def update_hr_zones_card(self, daily_summary_hist=None):
        """Update HR zones and Maffetone MAF card based on profile and resting HR data."""
        if not hasattr(self, 'hr_zones_card_body'):
            return

        body = self.hr_zones_card_body
        for widget in body.winfo_children():
            widget.destroy()

        profile = self.profile or {}

        # Get resting HR from profile or latest Garmin daily summary
        resting_hr = float(profile.get('resting_hr') or 0.0)
        resting_source = "Profil"
        if resting_hr <= 0 and daily_summary_hist:
            for d in reversed(daily_summary_hist):
                r_hr = d.get('resting_hr') or d.get('restingHeartRate') or 0
                if r_hr and float(r_hr) > 0:
                    resting_hr = float(r_hr)
                    resting_source = f"Garmin ({d.get('date', '')})"
                    break

        if resting_hr <= 0:
            resting_hr = 60.0
            resting_source = "Standard (60 bpm)"

        age = float(profile.get('age') or 40.0)
        user_max_hr = float(profile.get('max_hr') or 0.0)
        garmin_max_setting = 0.0

        if hasattr(self, 'db') and self.db:
            try:
                g_max_meta = self.db.get_metadata("garmin_max_hr")
                if g_max_meta and float(g_max_meta) > 0:
                    garmin_max_setting = float(g_max_meta)
            except Exception:
                pass

        if user_max_hr > 0:
            max_hr_override = user_max_hr
            max_hr_source = "user"
            max_source_desc = "Profil"
        elif garmin_max_setting > 0:
            max_hr_override = garmin_max_setting
            max_hr_source = "garmin_profile"
            max_source_desc = "Garmin inställningar"
        else:
            max_hr_override = 0.0
            max_hr_source = "formula"
            max_source_desc = "Formel 220-ålder"

        calc = hr_zones_calc.calculate_hr_zones(
            age=age,
            resting_hr=resting_hr,
            max_hr_override=max_hr_override,
            max_hr_source=max_hr_source,
            sex=profile.get('sex', 'male'),
            maf_adjustment=int(profile.get('maf_adjustment') or 0),
            maf_category=profile.get('maf_category'),
            training_years=float(profile.get('training_years') or 0.0) if profile.get('training_years') is not None else None,
            has_injury_or_illness=bool(profile.get('has_injury_or_illness') or profile.get('is_injured')),
            is_beginner=bool(profile.get('is_beginner'))
        )

        # 1. Overview Bar
        info_frame = ttk.Frame(body, style='Card.TFrame')
        info_frame.pack(fill=tk.X, pady=(0, 8))

        info_text = (
            f"👤 Ålder: {int(calc['age'])} år  |  "
            f"❤️ Vilopuls: {calc['resting_hr']} bpm ({resting_source})  |  "
            f"⚡ Maxpuls: {calc['max_hr']} bpm ({max_source_desc})  |  "
            f"📊 Pulsreserv (HRR): {calc['hrr']} bpm"
        )
        ttk.Label(info_frame, text=info_text, font=('Segoe UI', 9, 'bold'), foreground='#374151').pack(anchor=tk.W)

        # 2. Zones Table
        table_frame = ttk.Frame(body, style='Card.TFrame')
        table_frame.pack(fill=tk.X, pady=(0, 10))

        cols = ("zone", "title", "intensity", "range", "effect")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=5)
        tree.heading("zone", text="Zon")
        tree.heading("title", text="Beskrivning")
        tree.heading("intensity", text="Intensitet (% HRR)")
        tree.heading("range", text="Pulsintervall (bpm)")
        tree.heading("effect", text="Träningsfokus & Effekt")

        tree.column("zone", width=70, anchor=tk.CENTER)
        tree.column("title", width=210, anchor=tk.W)
        tree.column("intensity", width=120, anchor=tk.CENTER)
        tree.column("range", width=140, anchor=tk.CENTER)
        tree.column("effect", width=330, anchor=tk.W)

        for z in calc['zones']:
            tree.insert("", tk.END, values=(
                z['name'],
                z['title'],
                z['pct_range_str'],
                z['bpm_range_str'],
                z['desc']
            ))
        tree.pack(fill=tk.X)

        # 3. Philip Maffetone (MAF 180) Box
        maf = calc['maf']
        maf_box = ttk.Frame(body, style='Card.TFrame', padding="8")
        maf_box.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(
            maf_box,
            text=f"🎯 Philip Maffetone MAF 180 Puls:  {maf['maf_target']} bpm  (Aerobt träningstak: {maf['range_str']})",
            font=('Segoe UI', 11, 'bold'),
            foreground='#D97706'
        ).pack(anchor=tk.W, pady=(0, 4))

        maf_info = (
            f"📊 Formel: 180 – {int(maf['age'])} år = {maf['base_maf']} bpm  |  Justering: {maf['adjustment']:+d} bpm ({maf['category_desc']})\n"
            f"• Maximal aerob förbränning: Håll pulsen i intervallet {maf['range_str']} under distanspass för maximal fettförbränning och basbyggande.\n"
            f"• Undvik överträning: Träning över {maf['maf_target']} bpm aktiverar den anaeroba förbränningen (mjölksyra och stresshormoner).\n"
            f"• Pulsjämförelse: Din MAF-puls ({maf['maf_target']} bpm) matchar perfekt gränsen för {calc['zones'][1]['name']} ({calc['zones'][1]['title']}).\n"
            f"🏃 MAF-testmetod: Värm upp i 15 min ({maf['warmup_range_str']}). Spring i 40 min / 5 km i jämnt tempo vid exakt {maf['maf_target']} bpm (±2 bpm). Logga distansen över tid för att mäta aerobt framsteg!"
        )
        ttk.Label(
            maf_box,
            text=maf_info,
            font=('Segoe UI', 9),
            foreground='#4B5563',
            justify=tk.LEFT
        ).pack(anchor=tk.W)

    def get_recovery_ai_recommendation(self, rec_val: int, hr_calc: dict) -> str:
        """Generate a concise 5-6 line AI training recommendation based on recovery score and HR zones."""
        zones = hr_calc.get('zones', [])
        maf = hr_calc.get('maf', {})

        z1_range = zones[0]['bpm_range_str'] if len(zones) > 0 else "110–125 bpm"
        z2_range = zones[1]['bpm_range_str'] if len(zones) > 1 else "125–140 bpm"
        z3_range = zones[2]['bpm_range_str'] if len(zones) > 2 else "140–155 bpm"
        z4_range = zones[3]['bpm_range_str'] if len(zones) > 3 else "155–170 bpm"

        z1_high = zones[0]['bpm_high'] if len(zones) > 0 else 125
        z4_low = zones[3]['bpm_low'] if len(zones) > 3 else 155
        maf_target = maf.get('maf_target', 135)

        if rec_val >= 80:
            lines = [
                f"🤖 AI-Analys: Återhämtning {rec_val}% – Kroppen är i toppform och redo för högre ansträngning!",
                "🎯 Rekommenderad träning: Högintensivt kvalitetspass (intervaller, tröskel/tempo eller snabbdistans).",
                f"❤️ Pulsnivå: Sikta på Zon 3–4 ({z3_range} till {z4_range}) med möjliga toppar i Zon 5.",
                "🏃 Träningsfokus: Utnyttja höga energidepåer för maximal träningseffekt och utveckling.",
                "💡 Tips: Värm upp grundligt i Zon 1 (10–15 min) och prioritera god återhämtning efteråt."
            ]
        elif rec_val >= 60:
            lines = [
                f"🤖 AI-Analys: Återhämtning {rec_val}% – God energibalans och fin form för träning idag.",
                "🎯 Rekommenderad träning: Aerobt distanspass, basbygge eller medeltung styrketräning.",
                f"❤️ Pulsnivå: Håll pulsen i Zon 2 ({z2_range}) eller kring din MAF-puls ({maf_target} bpm).",
                "🏃 Träningsfokus: Utveckla den aeroba uthålligheten och fettförbränningen utan mjölksyra.",
                "💡 Tips: Håll ett stabilt och kontrollerat tempo – undvik onödiga pulstoppar."
            ]
        elif rec_val >= 40:
            lines = [
                f"🤖 AI-Analys: Återhämtning {rec_val}% – Måttlig återhämtning med viss kvarvarande trötthet.",
                "🎯 Rekommenderad träning: Lätt återhämtningspass, lugn aerob cykling/löpning eller rörlighet.",
                f"❤️ Pulsnivå: Håll pulsen i Zon 1–2 ({z1_range} till {z2_range}), max {maf_target} bpm.",
                "🏃 Träningsfokus: Öka blodcirkulationen för att påskynda återhämtningen utan överbelastning.",
                f"💡 Tips: Undvik tunga lyft och tuffa intervaller i Zon 4–5 (>{z4_low} bpm) idag."
            ]
        else:
            lines = [
                f"🤖 AI-Analys: Återhämtning {rec_val}% – Låga energireserver, kroppen behöver återhämta sig.",
                "🎯 Rekommenderad träning: Aktiv vila, lugn promenad, rörlighet eller helt träningsfri dag.",
                f"❤️ Pulsnivå: Undvik ansträngning, håll pulsen mycket låg i Zon 1 (<{z1_high} bpm).",
                "🏃 Träningsfokus: Prioritera god sömn, hydrering och näring för att ladda om batterierna.",
                "💡 Tips: Hård träning idag ökar risken för överträning och skador – prioritera vila."
            ]

        return "\n".join(lines)

    def fetch_ai_recovery_recommendation_async(self, rec_val: int, hr_calc: dict, label_widget: tk.Label):
        """Asynchronously call active AI client (e.g. Ollama) in background thread to generate advice."""
        import threading

        def _bg_worker():
            try:
                if not callable(getattr(self, 'ai_client_getter', None)):
                    return
                ai_client = self.ai_client_getter()
                if not ai_client:
                    return

                maf_target = hr_calc.get('maf', {}).get('maf_target', 135)
                zones = hr_calc.get('zones', [])
                z2_str = zones[1]['bpm_range_str'] if len(zones) > 1 else "125–140 bpm"

                system_prompt = "Du är en professionell uthållighetscoach. Svara ultrakort och koncis på svenska."
                user_msg = (
                    f"Baserat på användarens återhämtningspoäng {rec_val}%, vilopuls {hr_calc.get('resting_hr', 60)} bpm "
                    f"och MAF-puls {maf_target} bpm (Zon 2: {z2_str}):\n"
                    f"Skriv en kort dagsrekommendation på exakt 5 rader (använd emojis i början av varje rad):\n"
                    f"Rad 1: 🤖 AI-Analys (status utifrån {rec_val}% återhämtning)\n"
                    f"Rad 2: 🎯 Rekommenderad träning (pass för idag)\n"
                    f"Rad 3: ❤️ Pulsnivå (exakt pulszon/bpm-intervall)\n"
                    f"Rad 4: 🏃 Träningsfokus (vad passet ska utveckla)\n"
                    f"Rad 5: 💡 Tips (vad du bör tänka på/undvika idag)\n"
                    f"Ingen övrig introduktion eller avslutning."
                )

                response = ai_client.chat(user_msg, garmin_context="", system_prompt=system_prompt)
                if response and not response.startswith("🔌 Ollama Not Running") and not response.startswith("🚫"):
                    lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
                    if len(lines) >= 3:
                        final_text = "\n".join(lines[:5])
                        self.after(0, lambda: label_widget.config(text=final_text))
            except Exception as e:
                logger.debug(f"AI background recovery generation error: {e}")

        thread = threading.Thread(target=_bg_worker, daemon=True)
        thread.start()

    def update_health_cards(self, sleep_hist, bb_hist, stress_hist, body_comp, body_comp_hist=None, daily_summary_hist=None):
        """Update top cards in the Hälsa tab."""
        # 1. Recovery Score Card
        if hasattr(self, 'card_recovery'):
            for w in self.card_recovery['body'].winfo_children():
                w.destroy()

            latest_bb = bb_hist[-1] if bb_hist else {}
            rec_val = int(latest_bb.get('highest', 90) or 90)

            # Compute resting HR & HR zones for AI recommendations
            profile = self.profile or {}
            resting_hr = float(profile.get('resting_hr') or 0.0)
            if resting_hr <= 0 and daily_summary_hist:
                for d in reversed(daily_summary_hist):
                    r_hr = d.get('resting_hr') or d.get('restingHeartRate') or 0
                    if r_hr and float(r_hr) > 0:
                        resting_hr = float(r_hr)
                        break
            if resting_hr <= 0:
                resting_hr = 60.0

            age = float(profile.get('age') or 40.0)
            user_max_hr = float(profile.get('max_hr') or profile.get('max_hr_override') or 0.0)
            garmin_max_setting = 0.0

            if hasattr(self, 'db') and self.db:
                try:
                    g_max_meta = self.db.get_metadata("garmin_max_hr")
                    if g_max_meta and float(g_max_meta) > 0:
                        garmin_max_setting = float(g_max_meta)
                except Exception:
                    pass

            if user_max_hr > 0:
                max_hr_override = user_max_hr
                max_hr_source = "user"
            elif garmin_max_setting > 0:
                max_hr_override = garmin_max_setting
                max_hr_source = "garmin_profile"
            else:
                max_hr_override = 0.0
                max_hr_source = "formula"

            sex = str(profile.get('sex') or 'male')
            maf_adj = int(profile.get('maf_adjustment') or 0)

            hr_calc = hr_zones_calc.calculate_hr_zones(
                age=age,
                resting_hr=resting_hr,
                max_hr_override=max_hr_override,
                max_hr_source=max_hr_source,
                sex=sex,
                maf_adjustment=maf_adj,
                maf_category=profile.get('maf_category'),
                training_years=float(profile.get('training_years') or 0.0) if profile.get('training_years') is not None else None,
                has_injury_or_illness=bool(profile.get('has_injury_or_illness') or profile.get('is_injured')),
                is_beginner=bool(profile.get('is_beginner'))
            )

            rec_color = '#10B981' if rec_val >= 75 else ('#F59E0B' if rec_val >= 45 else '#EF4444')
            status_summary = (
                "Fullt återhämtad och redo för topprestation!" if rec_val >= 80 else
                ("Återhämtad och redo för dagen!" if rec_val >= 60 else
                ("Måttlig återhämtning – anpassa träningsintensiteten" if rec_val >= 40 else
                "Låg återhämtning – prioritera vila och återhämtning"))
            )

            # Top Section: Score percentage & bold status header
            top_frame = ttk.Frame(self.card_recovery['body'], style='Card.TFrame')
            top_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))

            ttk.Label(top_frame, text=f"{rec_val}%", font=('Segoe UI', 24, 'bold'), foreground=rec_color).pack(anchor=tk.W)
            ttk.Label(top_frame, text=status_summary, font=('Segoe UI', 10, 'bold'), foreground='#1F2937').pack(anchor=tk.W, pady=(2, 6))

            # Bottom Section: AI Analysis Box (5-6 lines text placed UNDER the score & header, clean white background)
            ai_recommendation = self.get_recovery_ai_recommendation(rec_val, hr_calc)

            ai_box = ttk.Frame(self.card_recovery['body'], style='Card.TFrame')
            ai_box.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

            ai_lbl = tk.Label(
                ai_box,
                text=ai_recommendation,
                font=('Segoe UI', 9),
                fg='#374151',
                bg='#FFFFFF',
                justify=tk.LEFT,
                anchor='w',
                wraplength=450
            )
            ai_lbl.pack(anchor=tk.W, fill=tk.BOTH, expand=True)

            def _on_ai_box_resize(event, lbl=ai_lbl):
                if event.width > 100:
                    lbl.config(wraplength=max(200, event.width - 20))

            ai_box.bind('<Configure>', _on_ai_box_resize)

            # If an AI client (Ollama / xAI / OpenAI / Gemini) is active, fetch live LLM response in background
            if callable(getattr(self, 'ai_client_getter', None)) and self.ai_client_getter():
                self.fetch_ai_recovery_recommendation_async(rec_val, hr_calc, ai_lbl)

        # 2. Weight & Body Comp Card (with Weight trend, % change & BMI change)
        if hasattr(self, 'card_weight'):
            for w in self.card_weight['body'].winfo_children():
                w.destroy()

            if body_comp and body_comp.get('weight_kg'):
                w_kg = float(body_comp.get('weight_kg') or 0.0)
                fat_pct = float(body_comp.get('fat_ratio_pct') or 0.0)
                m_kg = float(body_comp.get('muscle_mass_kg') or 0.0)
                src_name = str(body_comp.get('source') or 'Withings').title()

                ttk.Label(self.card_weight['body'], text=f"{w_kg:.1f} kg", font=('Segoe UI', 22, 'bold'), foreground='#1F2937').pack(anchor=tk.W)

                # Weight Trend & Percent Change over self.days_range
                valid_w = [b for b in (body_comp_hist or []) if (b.get('weight_kg') or 0) > 0]
                days_label = f"{self.days_range} d" if self.days_range < 365 else "1 år"
                if self.days_range > 365:
                    days_label = "alla d"

                if len(valid_w) >= 2:
                    first_w = float(valid_w[0].get('weight_kg'))
                    diff_kg = w_kg - first_w
                    diff_pct = (diff_kg / first_w * 100.0) if first_w > 0 else 0.0

                    trend_icon = "📉" if diff_kg < 0 else ("📈" if diff_kg > 0 else "➡️")
                    trend_color = "#10B981" if diff_kg <= 0 else "#EF4444"
                    trend_str = f"{trend_icon} {diff_kg:+.1f} kg ({diff_pct:+.1f}%) under {days_label}"
                    ttk.Label(self.card_weight['body'], text=trend_str, font=('Segoe UI', 9, 'bold'), foreground=trend_color).pack(anchor=tk.W, pady=(0, 2))

                # BMI & BMI Change
                profile = getattr(self, 'profile', {}) or {}
                height_cm = float(profile.get('height_cm') or 0.0)
                latest_bmi = 0.0
                diff_bmi = 0.0

                if height_cm > 0:
                    latest_bmi = w_kg / ((height_cm / 100.0) ** 2)
                    if len(valid_w) >= 2:
                        first_w = float(valid_w[0].get('weight_kg'))
                        first_bmi = first_w / ((height_cm / 100.0) ** 2)
                        diff_bmi = latest_bmi - first_bmi
                elif body_comp.get('bmi'):
                    latest_bmi = float(body_comp.get('bmi') or 0.0)
                    if len(valid_w) >= 2 and valid_w[0].get('bmi'):
                        first_bmi = float(valid_w[0].get('bmi') or 0.0)
                        diff_bmi = latest_bmi - first_bmi

                if latest_bmi > 0:
                    bmi_text = f"BMI: {latest_bmi:.1f}"
                    if len(valid_w) >= 2 and abs(diff_bmi) >= 0.01:
                        bmi_icon = "📉" if diff_bmi < 0 else ("📈" if diff_bmi > 0 else "")
                        bmi_text += f" ({bmi_icon} {diff_bmi:+.1f} under {days_label})"
                    ttk.Label(self.card_weight['body'], text=bmi_text, font=('Segoe UI', 9), foreground='#4B5563').pack(anchor=tk.W, pady=(0, 2))

                # Composition (Fat % & Muscle mass)
                comp_parts = []
                if fat_pct > 0:
                    comp_parts.append(f"Fett: {fat_pct:.1f}%")
                if m_kg > 0:
                    comp_parts.append(f"Muskelmassa: {m_kg:.1f} kg")
                if comp_parts:
                    ttk.Label(self.card_weight['body'], text=" | ".join(comp_parts), font=('Segoe UI', 8), foreground='#6B7280').pack(anchor=tk.W)

                ttk.Label(self.card_weight['body'], text=f"Källa: {src_name} ({body_comp.get('date')})", font=('Segoe UI', 8, 'italic'), foreground='#9CA3AF').pack(anchor=tk.W, pady=(3, 0))
            else:
                ttk.Label(self.card_weight['body'], text="Ingen vikt registrerad", font=('Segoe UI', 10, 'italic'), foreground='#9CA3AF').pack(anchor=tk.W)

    def update_dashboard_cards(self, sleep_hist, bb_hist, stress_hist, act_hist, body_comp):
        """Backward compatibility update alias."""
        self.update_health_cards(sleep_hist, bb_hist, stress_hist, body_comp)
        self.update_training_cards(act_hist, bb_hist)

    def update_training_cards(self, act_hist, bb_hist):
        """Update top cards on the dedicated Training tab."""
        if not hasattr(self, 'card_train_fitness'):
            return

        # 1. Training Fitness Index Card
        for w in self.card_train_fitness['body'].winfo_children():
            w.destroy()

        fit_score = 70.0
        if act_hist:
            valid_runs = [a for a in act_hist if (a.get('distance_km') or 0) > 0 and (a.get('avg_hr') or 0) > 0]
            if valid_runs:
                ratios = [((a.get('distance_km') or 0) / (a.get('duration_min') or 1)) * (180.0 / (a.get('avg_hr') or 140)) for a in valid_runs]
                avg_ratio = sum(ratios) / len(ratios)
                fit_score = min(99.0, max(45.0, 50.0 + (avg_ratio * 15.0)))

        ttk.Label(self.card_train_fitness['body'], text=f"{fit_score:.1f}", font=('Segoe UI', 24, 'bold'), foreground='#0078D4').pack(anchor=tk.W)
        ttk.Label(self.card_train_fitness['body'], text=f"Beräknat från {len(act_hist or [])} pass under valt tidsintervall", font=('Segoe UI', 9), foreground='#6B7280').pack(anchor=tk.W)

        # 2. Training Status Card
        for w in self.card_train_status['body'].winfo_children():
            w.destroy()

        latest_bb = bb_hist[-1] if bb_hist else {}
        charged = latest_bb.get('charged', 85) or 85
        ttk.Label(self.card_train_status['body'], text="⚡ Produktiv Träning", font=('Segoe UI', 13, 'bold'), foreground='#10B981').pack(anchor=tk.W)
        ttk.Label(self.card_train_status['body'], text=f"Base Fitness: 68 | Fatigue: 42 | Load Impact: +{charged}", font=('Segoe UI', 9), foreground='#4B5563').pack(anchor=tk.W)

        # 3. Training Summary Card (Period Totals & Trend vs Previous Period)
        for w in self.card_train_summary['body'].winfo_children():
            w.destroy()

        today_dt = datetime.now().date()
        curr_acts = []
        prev_acts = []

        for a in (act_hist or []):
            dt_str = str(a.get('date') or a.get('start_time') or '')[:10]
            if len(dt_str) == 10:
                try:
                    a_date = datetime.strptime(dt_str, '%Y-%m-%d').date()
                    days_ago = (today_dt - a_date).days
                    if 0 <= days_ago < self.days_range:
                        curr_acts.append(a)
                    elif self.days_range <= days_ago < (2 * self.days_range):
                        prev_acts.append(a)
                except ValueError:
                    pass
            else:
                curr_acts.append(a)

        total_km = sum(float(a.get('distance_km') or 0.0) for a in curr_acts)
        prev_km = sum(float(a.get('distance_km') or 0.0) for a in prev_acts)

        cnt = len(curr_acts)
        prev_cnt = len(prev_acts)

        total_dur_min = sum(float(a.get('duration_min') or 0.0) for a in curr_acts)
        total_hrs = total_dur_min / 60.0
        hrs_int = int(total_hrs)
        mins_rem = int(total_dur_min % 60)
        dur_str = f"{hrs_int}t {mins_rem}m" if hrs_int > 0 else f"{int(total_dur_min)} min"

        total_cal = sum(float(a.get('calories') or 0.0) for a in curr_acts)

        days_label = f"{self.days_range} d" if self.days_range < 365 else "1 år"
        if self.days_range > 365:
            days_label = "alla d"

        # Main Distance Display
        ttk.Label(self.card_train_summary['body'], text=f"{total_km:.1f} km", font=('Segoe UI', 22, 'bold'), foreground='#1F2937').pack(anchor=tk.W)

        # Distance Trend vs Previous Period
        if prev_acts or curr_acts:
            diff_km = total_km - prev_km
            diff_pct = (diff_km / prev_km * 100.0) if prev_km > 0 else (100.0 if total_km > 0 else 0.0)

            trend_icon = "📈" if diff_km > 0 else ("📉" if diff_km < 0 else "➡️")
            trend_color = "#10B981" if diff_km >= 0 else "#EF4444"

            trend_str = f"{trend_icon} {diff_km:+.1f} km ({diff_pct:+.1f}%) vs föregående {days_label}"
            ttk.Label(self.card_train_summary['body'], text=trend_str, font=('Segoe UI', 9, 'bold'), foreground=trend_color).pack(anchor=tk.W, pady=(0, 2))

        # Pass count & Total duration
        cnt_diff = cnt - prev_cnt
        cnt_diff_str = f" ({cnt_diff:+=d} st)" if prev_acts and cnt_diff != 0 else ""
        ttk.Label(self.card_train_summary['body'], text=f"{cnt} träningspass{cnt_diff_str} | Totaltid: {dur_str}", font=('Segoe UI', 9), foreground='#4B5563').pack(anchor=tk.W)

        # Workout Calories
        if total_cal > 0:
            def _fmt(n):
                return f"{int(n):,}".replace(",", " ")
            ttk.Label(self.card_train_summary['body'], text=f"🏋️ {_fmt(total_cal)} kcal träningsförbränning", font=('Segoe UI', 8, 'italic'), foreground='#9CA3AF').pack(anchor=tk.W, pady=(3, 0))

    def update_calorie_card(self, body_comp, act_hist):
        """Estimate & display today's approximate calorie burn, and persist it for trends."""
        if not hasattr(self, 'card_calories'):
            return

        for w in self.card_calories['body'].winfo_children():
            w.destroy()

        today = datetime.now().strftime('%Y-%m-%d')
        profile = self.profile or {}

        # Body weight: prefer an explicit profile weight, else the latest measurement.
        weight_kg = 0.0
        try:
            weight_kg = float(profile.get('weight_kg') or 0)
        except (TypeError, ValueError):
            weight_kg = 0.0
        if weight_kg <= 0 and body_comp and body_comp.get('weight_kg'):
            try:
                weight_kg = float(body_comp.get('weight_kg') or 0)
            except (TypeError, ValueError):
                weight_kg = 0.0

        # Today's steps + device BMR (if Garmin has been synced).
        day_summary = {}
        try:
            day_summary = self.db.get_daily_summary(today) or {}
        except Exception as e:
            logger.debug(f"Could not load daily summary for calorie card: {e}")

        steps = int(day_summary.get('total_steps', 0) or 0)
        bmr_override = 0.0
        raw = day_summary.get('raw_json')
        if raw:
            try:
                rd = json.loads(raw)
                device_bmr = float(rd.get('bmrKilocalories', 0) or 0)
                frac = calorie_calc.day_fraction_elapsed()
                if device_bmr > 0 and frac > 0.05:
                    bmr_override = device_bmr / frac
                else:
                    bmr_override = device_bmr
            except Exception:
                bmr_override = 0.0

        # Today's workout calories and workout steps (sum over activities dated today).
        workout_cal = 0
        workout_steps = 0
        for a in (act_hist or []):
            if str(a.get('date') or a.get('start_time') or '')[:10] == today:
                try:
                    workout_cal += int(float(a.get('calories') or 0))
                except (TypeError, ValueError):
                    pass

                # Extract activity steps if available, or estimate for step-based activities (~1300 steps/km)
                act_steps = 0
                raw_act = a.get('raw_json')
                if raw_act:
                    try:
                        ra = json.loads(raw_act) if isinstance(raw_act, str) else raw_act
                        act_steps = int(ra.get('steps') or ra.get('totalSteps') or 0)
                    except Exception:
                        act_steps = 0
                if not act_steps:
                    act_steps = int(a.get('steps') or a.get('total_steps') or 0)
                if not act_steps:
                    act_type = str(a.get('activity_type') or '').lower()
                    if any(k in act_type for k in ('run', 'walk', 'hike', 'löp', 'gång', 'jogg')):
                        dist = float(a.get('distance_km') or 0.0)
                        if dist > 0:
                            act_steps = int(dist * 1300)
                workout_steps += max(0, act_steps)

        def _num(key):
            try:
                return float(profile.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        result = calorie_calc.estimate_daily_burn(
            weight_kg=weight_kg,
            height_cm=_num('height_cm'),
            age_years=_num('age'),
            sex=profile.get('sex', 'male'),
            steps=steps,
            workout_steps=workout_steps,
            workout_calories=workout_cal,
            bmr_override=bmr_override,
            is_today=True,
        )

        try:
            self.db.upsert_calorie_burn(
                today,
                total_burn=result['total_burn'],
                resting_burn=result['resting_burn'],
                steps_burn=result['steps_burn'],
                workout_burn=result['workout_burn'],
                bmr_full=result['bmr_full'],
                steps=result['steps'],
                weight_kg=weight_kg,
                day_fraction=result['day_fraction'],
                bmr_source=result['bmr_source'],
            )
        except Exception as e:
            logger.error(f"Could not persist calorie burn: {e}")

        body = self.card_calories['body']

        if result['total_burn'] <= 0:
            ttk.Label(body, text="Ingen data ännu", font=('Segoe UI', 13, 'bold'), foreground='#9CA3AF').pack(anchor=tk.W)
            ttk.Label(
                body,
                text="Synka Garmin och ange din profil\n(längd, ålder, kön) i Inställningar\nför en uppskattning.",
                font=('Segoe UI', 9), foreground='#9CA3AF', justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(4, 0))
            return

        def _fmt(n):
            return f"{int(n):,}".replace(",", " ")

        ttk.Label(
            body, text=f"🔥 {_fmt(result['total_burn'])} kcal",
            font=('Segoe UI', 22, 'bold'), foreground='#EA580C',
        ).pack(anchor=tk.W)
        ttk.Label(
            body, text="Förbränt hittills idag (ungefärligt)",
            font=('Segoe UI', 9), foreground='#6B7280',
        ).pack(anchor=tk.W, pady=(0, 6))

        ttk.Label(
            body, text=f"🛌 Vila (BMR): {_fmt(result['resting_burn'])} kcal",
            font=('Segoe UI', 9), foreground='#4B5563',
        ).pack(anchor=tk.W)
        steps_lbl = f"👟 Vardagssteg: {_fmt(result['steps_burn'])} kcal ({_fmt(result['everyday_steps'])} st)"
        if result.get('workout_steps', 0) > 0:
            steps_lbl += f" (avdrag {_fmt(result['workout_steps'])} st träning)"
        ttk.Label(
            body, text=steps_lbl,
            font=('Segoe UI', 9), foreground='#4B5563',
        ).pack(anchor=tk.W)
        ttk.Label(
            body, text=f"🏋️ Träning: {_fmt(result['workout_burn'])} kcal",
            font=('Segoe UI', 9), foreground='#4B5563',
        ).pack(anchor=tk.W)

        bmr_note = {
            'device': 'Vilo-BMR från Garmin',
            'mifflin': 'Vilo-BMR beräknad från din profil',
            'simple': 'Vilo-BMR grovt uppskattad (ange profil för bättre värde)',
        }.get(result['bmr_source'], '')
        if bmr_note:
            ttk.Label(
                body, text=bmr_note,
                font=('Segoe UI', 8, 'italic'), foreground='#9CA3AF',
            ).pack(anchor=tk.W, pady=(6, 0))

    @staticmethod
    def _format_axis_dates(ax, dates: List[str]):
        """Helper to cleanly format X-axis date labels without overlapping text."""
        if not dates:
            return
        n = len(dates)
        if n > 10:
            step = max(1, n // 8)
            indices = list(range(0, n, step))
            if indices[-1] != n - 1:
                indices.append(n - 1)
            ax.set_xticks(indices)
            ax.set_xticklabels([dates[i] for i in indices], rotation=35, ha='right', fontsize=8)
        else:
            ax.set_xticks(range(n))
            ax.set_xticklabels(dates, rotation=35, ha='right', fontsize=8)

    @staticmethod
    def _prepare_chart_series(data_list: Optional[List[Dict[str, Any]]], value_key: str, default_val: float = 0.0):
        if not data_list:
            return [], []
        valid_items = [d for d in data_list if (d.get('date') or d.get('start_time'))]
        sorted_list = sorted(valid_items, key=lambda x: str(x.get('date') or x.get('start_time') or ''))

        if not sorted_list:
            return [], []

        years = set(str(x.get('date') or x.get('start_time') or '')[:4] for x in sorted_list if len(str(x.get('date') or '')) >= 4)
        use_year = len(years) > 1

        dates = []
        vals = []
        for d in sorted_list:
            dt_raw = str(d.get('date') or d.get('start_time') or '')[:10]
            if len(dt_raw) < 10:
                continue
            date_fmt = dt_raw[2:] if use_year else dt_raw[5:]
            dates.append(date_fmt)
            vals.append(float(d.get(value_key) or default_val))

        return dates, vals

    def draw_dashboard_charts(self, sleep_hist, bb_hist, stress_hist, act_hist):
        """Backward compatibility draw alias."""
        pass

    def draw_health_charts(self, sleep_hist, bb_hist, stress_hist, hrv_hist, body_comp, daily_summary_hist=None):
        """Draw pure health analytics trends across all subplots in the Hälsa tab."""
        health_axes = [
            self.ax_health_weight, self.ax_health_calories, self.ax_health_rhr,
            self.ax_health_hrv, self.ax_health_sleep, self.ax_health_sleep_score,
            self.ax_health_bb, self.ax_health_stress
        ]
        for ax in health_axes:
            ax.clear()
            ax.set_facecolor('#FFFFFF')
            ax.tick_params(colors='#374151', labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.4, color='#E5E7EB')
            for spine in ax.spines.values():
                spine.set_color('#E5E7EB')

        # 1. Resting Heart Rate / Vilopuls (Row 2 Left)
        rhr_map = {}
        for d in (daily_summary_hist or []):
            dt = d.get('date')
            rhr = d.get('resting_hr', 0)
            if dt and rhr and rhr > 0:
                rhr_map[dt] = rhr

        for s in (sleep_hist or []):
            dt = s.get('date')
            if dt:
                rhr = s.get('resting_hr') or s.get('resting_heart_rate', 0)
                if not rhr and s.get('raw_json'):
                    try:
                        raw = json.loads(s['raw_json']) if isinstance(s['raw_json'], str) else s['raw_json']
                        rhr = raw.get('restingHeartRate') or raw.get('resting_hr', 0)
                    except Exception:
                        pass
                if rhr and rhr > 0:
                    rhr_map[dt] = rhr

        if rhr_map:
            sorted_dates = sorted(rhr_map.keys())
            years = set(dt[:4] for dt in sorted_dates if len(dt) >= 4)
            use_yr = len(years) > 1
            rhr_dates = [dt[2:] if use_yr else dt[5:] for dt in sorted_dates]
            rhr_vals = [rhr_map[dt] for dt in sorted_dates]
            self.ax_health_rhr.plot(rhr_dates, rhr_vals, color='#EC4899', marker='o', linewidth=2.0, markersize=3)
            self.ax_health_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls (bpm)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_health_rhr, rhr_dates)
        else:
            self.ax_health_rhr.text(0.5, 0.5, "Vilopuls: Kör Check-in för att läsa sömndata", ha='center', va='center', color='#9CA3AF')
            self.ax_health_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 2. HRV Trend (Row 2 Right)
        dates, hrv_val = self._prepare_chart_series(hrv_hist, 'last_night_avg')
        if dates:
            self.ax_health_hrv.plot(dates, hrv_val, color='#10B981', marker='^', linewidth=2.0)
            self.ax_health_hrv.set_title("Nattlig HRV Trend (ms)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_health_hrv, dates)
        else:
            self.ax_health_hrv.text(0.5, 0.5, "HRV: Synka Garmin för pulsvariabilitet", ha='center', va='center', color='#9CA3AF')
            self.ax_health_hrv.set_title("Nattlig HRV Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 3. Sleep Hours Trend (Row 3 Left)
        dates, sleep_hours = self._prepare_chart_series(sleep_hist, 'total_sleep_hours')
        if dates:
            self.ax_health_sleep.bar(dates, sleep_hours, color='#8B5CF6', alpha=0.75, width=0.45)
            self.ax_health_sleep.set_title("Sömnlängd per Natt (timmar)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_health_sleep, dates)
        else:
            self.ax_health_sleep.text(0.5, 0.5, "Sömnhistorik: Kör Check-in för sömndata", ha='center', va='center', color='#9CA3AF')
            self.ax_health_sleep.set_title("Sömnhistorik", fontsize=9, fontweight='bold', color='#1F2937')

        # 4. Sleep Quality / Score Trend (Row 3 Right)
        ss_dates = []
        ss_vals = []
        if sleep_hist:
            valid_sleep = [s for s in sleep_hist if (s.get('date') or s.get('start_time'))]
            sorted_sleep = sorted(valid_sleep, key=lambda x: str(x.get('date') or x.get('start_time') or ''))
            years = set(str(x.get('date') or '')[:4] for x in sorted_sleep if len(str(x.get('date') or '')) >= 4)
            use_yr = len(years) > 1

            for s in sorted_sleep:
                dt_raw = str(s.get('date') or s.get('start_time') or '')[:10]
                if len(dt_raw) < 10:
                    continue
                score = s.get('sleep_score') or s.get('score', 0)
                if not score and s.get('raw_json'):
                    try:
                        raw = json.loads(s['raw_json']) if isinstance(s['raw_json'], str) else s['raw_json']
                        if isinstance(raw, dict):
                            dto = raw.get('dailySleepDTO') or {}
                            scores_d = dto.get('sleepScores') or raw.get('sleepScores') or {}
                            if isinstance(scores_d, dict) and 'overall' in scores_d:
                                ov = scores_d.get('overall')
                                score = ov.get('value') if isinstance(ov, dict) else ov
                            if not score:
                                score = dto.get('sleepQualityScore') or dto.get('overallSleepScore', {}).get('value')
                    except Exception:
                        pass

                try:
                    score = int(score or 0)
                except (TypeError, ValueError):
                    score = 0

                if score > 0:
                    date_fmt = dt_raw[2:] if use_yr else dt_raw[5:]
                    ss_dates.append(date_fmt)
                    ss_vals.append(score)

        if ss_dates:
            self.ax_health_sleep_score.plot(ss_dates, ss_vals, color='#8B5CF6', marker='s', linewidth=2.0, markersize=3)
            self.ax_health_sleep_score.axhline(y=80, color='#10B981', linestyle=':', alpha=0.6, label='Utmärkt (80+)')
            self.ax_health_sleep_score.axhline(y=70, color='#F59E0B', linestyle=':', alpha=0.6, label='Bra (70+)')
            self.ax_health_sleep_score.set_title("Sömnkvalitet / Sleep Score (0–100)", fontsize=9, fontweight='bold', color='#1F2937')
            self.ax_health_sleep_score.set_ylim(0, 105)
            self.ax_health_sleep_score.legend(fontsize=7, loc='lower right', framealpha=0.6)
            self._format_axis_dates(self.ax_health_sleep_score, ss_dates)
        else:
            self.ax_health_sleep_score.text(0.5, 0.5, "Klicka 📥 Check-in för att läsa in sömnscore", ha='center', va='center', color='#9CA3AF')
            self.ax_health_sleep_score.set_title("Sömnkvalitet / Sleep Score", fontsize=9, fontweight='bold', color='#1F2937')

        # 4. Body Battery Trend (Middle Right)
        dates, charged_vals = self._prepare_chart_series(bb_hist, 'charged')
        if dates:
            self.ax_health_bb.plot(dates, charged_vals, color='#10B981', marker='o', linewidth=2.0, markersize=3)
            self.ax_health_bb.set_title("Body Battery Uppladdat (+)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_health_bb, dates)
        else:
            self.ax_health_bb.text(0.5, 0.5, "Body Battery: Synka Garmin", ha='center', va='center', color='#9CA3AF')
            self.ax_health_bb.set_title("Body Battery Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 5. Stress Trend (Bottom Left)
        dates_s, stress_vals = self._prepare_chart_series(stress_hist, 'average')
        if dates_s:
            self.ax_health_stress.plot(dates_s, stress_vals, color='#FF5722', marker='s', linewidth=1.8, markersize=3)
            self.ax_health_stress.set_title("Genomsnittlig Stress Level", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_health_stress, dates_s)
        else:
            self.ax_health_stress.text(0.5, 0.5, "Stress: Synka Garmin", ha='center', va='center', color='#9CA3AF')
            self.ax_health_stress.set_title("Genomsnittlig Stress Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 5. Weight & Body Fat Trend (Bottom Left)
        body_hist = self.db.get_body_composition_history(days=self.days_range) if hasattr(self, 'db') and self.db else []
        if body_hist:
            dates, w_vals = self._prepare_chart_series(body_hist, 'weight_kg')
            valid_pairs = [(d, w) for d, w in zip(dates, w_vals) if w > 0]
            if valid_pairs:
                vd, vw = zip(*valid_pairs)
                self.ax_health_weight.plot(vd, vw, color='#3B82F6', marker='s', linewidth=2.0, markersize=4)

                diff_w = vw[-1] - vw[0]
                diff_pct = (diff_w / vw[0] * 100.0) if vw[0] > 0 else 0.0
                days_label = f"{self.days_range}d" if self.days_range < 365 else "1 år"
                title_str = f"Vikt-trend ({days_label}): {diff_w:+.1f} kg ({diff_pct:+.1f}%)"

                profile = getattr(self, 'profile', {}) or {}
                height_cm = float(profile.get('height_cm') or 0.0)
                if height_cm > 0:
                    bmi_curr = vw[-1] / ((height_cm / 100.0) ** 2)
                    bmi_first = vw[0] / ((height_cm / 100.0) ** 2)
                    diff_b = bmi_curr - bmi_first
                    title_str += f" | BMI: {bmi_curr:.1f} ({diff_b:+.1f})"

                self.ax_health_weight.set_title(title_str, fontsize=9, fontweight='bold', color='#1F2937')
                self._format_axis_dates(self.ax_health_weight, list(vd))
            else:
                self.ax_health_weight.text(0.5, 0.5, "Vikt-trend: Synka Withings/Fitbit", ha='center', va='center', color='#9CA3AF')
                self.ax_health_weight.set_title("Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')
        elif body_comp and body_comp.get('weight_kg'):
            self.ax_health_weight.text(0.5, 0.5, f"Vikt: {body_comp.get('weight_kg')} kg | Fett: {body_comp.get('fat_ratio_pct', 'N/A')}%", ha='center', va='center', color='#1F2937', fontsize=11, fontweight='bold')
            self.ax_health_weight.set_title("Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')
        else:
            self.ax_health_weight.text(0.5, 0.5, "Vikt: Anslut Withings eller Fitbit", ha='center', va='center', color='#9CA3AF')
            self.ax_health_weight.set_title("Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')

        # 6. Daily Calorie Burn Trend (Bottom Right, stacked: resting + steps + workouts)
        cb_hist = self.db.get_calorie_burn_history(self.days_range) if hasattr(self, 'db') and self.db else []
        cb_dates, resting_vals = self._prepare_chart_series(cb_hist, 'resting_burn')
        _, steps_vals = self._prepare_chart_series(cb_hist, 'steps_burn')
        _, workout_vals = self._prepare_chart_series(cb_hist, 'workout_burn')
        has_burn = cb_dates and any((r + s + w) > 0 for r, s, w in zip(resting_vals, steps_vals, workout_vals))
        if has_burn:
            base_steps = list(resting_vals)
            base_workout = [r + s for r, s in zip(resting_vals, steps_vals)]
            self.ax_health_calories.bar(cb_dates, resting_vals, color='#F59E0B', width=0.5, label='Vila (BMR)')
            self.ax_health_calories.bar(cb_dates, steps_vals, bottom=base_steps, color='#0078D4', width=0.5, label='Steg')
            self.ax_health_calories.bar(cb_dates, workout_vals, bottom=base_workout, color='#EF4444', width=0.5, label='Träning')
            self.ax_health_calories.set_title("Kaloriförbränning per dag (kcal)", fontsize=9, fontweight='bold', color='#1F2937')
            self.ax_health_calories.legend(fontsize=7, loc='upper left', framealpha=0.6)
            self._format_axis_dates(self.ax_health_calories, cb_dates)
        else:
            self.ax_health_calories.text(0.5, 0.5, "Kaloriförbränning: byggs upp allt\neftersom du använder appen", ha='center', va='center', color='#9CA3AF')
            self.ax_health_calories.set_title("Kaloriförbränning per dag", fontsize=9, fontweight='bold', color='#1F2937')

        self.canvas_health.draw()

    def draw_training_charts(self, act_hist):
        """Draw training analytics trends across all subplots in the Träning tab."""
        train_axes = [self.ax_train_load, self.ax_train_zones, self.ax_train_volume, self.ax_train_types]
        for ax in train_axes:
            ax.clear()
            ax.set_facecolor('#FFFFFF')
            ax.tick_params(colors='#374151', labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.4, color='#E5E7EB')
            for spine in ax.spines.values():
                spine.set_color('#E5E7EB')

        # 1. Training Load & Distance Trend (Top Left)
        dates, dist = self._prepare_chart_series(act_hist, 'distance_km')
        if dates:
            self.ax_train_load.plot(dates, dist, color='#0078D4', marker='o', linewidth=2.0)
            self.ax_train_load.set_title("Träningsbelastning & Distans Trend (km)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_train_load, dates)
        else:
            self.ax_train_load.text(0.5, 0.5, "Inga träningspass registrerade", ha='center', va='center', color='#9CA3AF')
            self.ax_train_load.set_title("Träningsbelastning & Distans Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 2. Pulszondistribution Träning (Top Right)
        self.ax_train_zones.pie([15, 35, 30, 15, 5], labels=['Z1', 'Z2', 'Z3', 'Z4', 'Z5'], colors=['#93C5FD', '#60A5FA', '#3B82F6', '#2563EB', '#1D4ED8'], autopct='%1.0f%%', startangle=90)
        self.ax_train_zones.set_title("Pulszondistribution Träning", fontsize=9, fontweight='bold', color='#1F2937')

        # 3. Training Volume & Energy (Bottom Left)
        dates, cals = self._prepare_chart_series(act_hist, 'calories')
        if dates and any(c > 0 for c in cals):
            self.ax_train_volume.bar(dates, cals, color='#F59E0B', alpha=0.85, width=0.45)
            self.ax_train_volume.set_title("Kaloriförbrukning per Pass (kcal)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_train_volume, dates)
        elif dates:
            dates, durations = self._prepare_chart_series(act_hist, 'duration_min')
            self.ax_train_volume.bar(dates, durations, color='#10B981', alpha=0.85, width=0.45)
            self.ax_train_volume.set_title("Träningstid per Pass (min)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_train_volume, dates)
        else:
            self.ax_train_volume.text(0.5, 0.5, "Träningsvolym: Inga aktiviteter sparade", ha='center', va='center', color='#9CA3AF')
            self.ax_train_volume.set_title("Träningsvolym & Kalorier", fontsize=9, fontweight='bold', color='#1F2937')

        # 4. Activity Type Distribution / Breakdown (Bottom Right)
        if act_hist:
            type_counts = {}
            for a in act_hist:
                t_name = str(a.get('activity_type') or 'Övrigt').capitalize()
                type_counts[t_name] = type_counts.get(t_name, 0) + 1

            labels = list(type_counts.keys())
            counts = [type_counts[k] for k in labels]
            colors_list = ['#0078D4', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#6366F1']
            colors = colors_list[:len(labels)]
            self.ax_train_types.bar(labels, counts, color=colors, alpha=0.85, width=0.45)
            self.ax_train_types.set_title("Antal pass per aktivitetstyp", fontsize=9, fontweight='bold', color='#1F2937')
            self.ax_train_types.tick_params(axis='x', rotation=25, labelsize=8)
        else:
            self.ax_train_types.text(0.5, 0.5, "Inga träningspass i valt intervall", ha='center', va='center', color='#9CA3AF')
            self.ax_train_types.set_title("Aktivitetstyp-fördelning", fontsize=9, fontweight='bold', color='#1F2937')

        self.canvas_training.draw()

    def draw_evolab_charts(self, sleep_hist, bb_hist, stress_hist, hrv_hist, act_hist, body_comp, daily_summary_hist=None):
        """Backward compatibility draw alias."""
        self.draw_health_charts(sleep_hist, bb_hist, stress_hist, hrv_hist, body_comp, daily_summary_hist)
        self.draw_training_charts(act_hist)

    def populate_activities_table(self, act_hist: List[Dict[str, Any]]):
        """Populate Activity feed treeviews (in both Senaste Pass tab and Träning tab)."""
        trees = []
        if hasattr(self, 'act_tree'):
            trees.append(self.act_tree)
        if hasattr(self, 'train_tree'):
            trees.append(self.train_tree)

        for tree in trees:
            for item in tree.get_children():
                tree.delete(item)

        if not act_hist:
            return

        def _sort_key(x):
            d = x.get('date') or x.get('start_time') or ''
            return str(d)

        sorted_acts = sorted(act_hist, key=_sort_key, reverse=True)

        for act in sorted_acts:
            d_str = str(act.get("date") or act.get("start_time") or "N/A")[:10]
            
            src_raw = str(act.get("source") or "").strip()
            if not src_raw or src_raw.lower() == "garmin":
                raw = act.get("raw_json") or {}
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}
                if isinstance(raw, dict) and ("athlete" in raw or "sport_type" in raw or "map" in raw or "kilojoules" in raw or "resource_state" in raw or "Activity ID" in raw):
                    src_str = "Strava"
                elif isinstance(raw, dict) and ("logId" in raw or "dateOfSleep" in raw):
                    src_str = "Fitbit"
                else:
                    src_str = src_raw.capitalize() if src_raw else "Garmin"
            else:
                src_str = src_raw.capitalize()

            name_str = str(act.get("activity_name") or "Workout")
            type_str = str(act.get("activity_type") or "General")
            dist_val = float(act.get('distance_km') or 0.0)
            dur_val = float(act.get('duration_min') or 0.0)
            cal_val = int(float(act.get("calories") or 0))
            hr_val = int(float(act.get("avg_hr") or 0))

            row_vals = (
                d_str,
                src_str,
                name_str,
                type_str,
                f"{dist_val:.2f}",
                f"{dur_val:.1f}",
                cal_val,
                hr_val
            )
            for tree in trees:
                tree.insert("", tk.END, values=row_vals)
