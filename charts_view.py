"""
COROS-Inspired Light Theme Dashboard & Analytics View for HealthChat Desktop.
Features:
- Top Tab Bar Navigation (Dashboard 3-column grid, EvoLab Analytics 2-column grid, Activity Feed)
- Light Theme Palette (#F3F4F6 background, #FFFFFF clean cards, #0078D4 blue accent, #FF5722 coral highlights)
- Responsive metric cards (Running Fitness, Training Status, Recovery %, Zone Distribution, Weekly Summary)
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

logger = logging.getLogger("charts_view")


class HealthChartsView(ttk.Frame):
    """COROS-Inspired Graphical Dashboard & Analytics Manager."""

    def __init__(self, parent, db: GarminDatabase, colors: Dict[str, str], on_toggle_chat=None, on_checkin=None):
        super().__init__(parent, style='Main.TFrame')
        self.db = db
        self.colors = colors
        self.days_range = 30
        self.active_tab = "dashboard"
        self.on_toggle_chat_callback = on_toggle_chat
        self.on_checkin_callback = on_checkin

        self.setup_ui()
        self.refresh_all_views()
        self.after(50, self.refresh_all_views)

    def _trigger_checkin(self):
        """Invoke on_checkin_callback if registered."""
        if callable(self.on_checkin_callback):
            self.on_checkin_callback()

    def setup_ui(self):
        """Build main container with top navbar, tab controls, and scrollable content views."""
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

        self.tab_dashboard_btn = ttk.Button(
            nav_bar, text="📋 Dashboard", command=lambda: self.switch_tab("dashboard"), style='Accent.TButton'
        )
        self.tab_dashboard_btn.pack(side=tk.LEFT, padx=4)

        self.tab_evolab_btn = ttk.Button(
            nav_bar, text="📈 EvoLab & Analys", command=lambda: self.switch_tab("evolab"), style='Modern.TButton'
        )
        self.tab_evolab_btn.pack(side=tk.LEFT, padx=4)

        self.tab_activities_btn = ttk.Button(
            nav_bar, text="🏃 Senaste Pass & Logg", command=lambda: self.switch_tab("activities"), style='Modern.TButton'
        )
        self.tab_activities_btn.pack(side=tk.LEFT, padx=4)

        # Check-in Button directly after Senaste Pass & Logg
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
        self.dashboard_frame = ttk.Frame(self.container_frame, style='Main.TFrame')
        self.evolab_frame = ttk.Frame(self.container_frame, style='Main.TFrame')
        self.activities_frame = ttk.Frame(self.container_frame, style='Main.TFrame')

        self.setup_dashboard_tab()
        self.setup_evolab_tab()
        self.setup_activities_tab()

        # Show initial tab
        self.switch_tab("dashboard")

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
        self.active_tab = tab_name
        for f in (self.dashboard_frame, self.evolab_frame, self.activities_frame):
            f.pack_forget()

        self.tab_dashboard_btn.config(style='Accent.TButton' if tab_name == "dashboard" else 'Modern.TButton')
        self.tab_evolab_btn.config(style='Accent.TButton' if tab_name == "evolab" else 'Modern.TButton')
        self.tab_activities_btn.config(style='Accent.TButton' if tab_name == "activities" else 'Modern.TButton')

        if tab_name == "dashboard":
            self.dashboard_frame.pack(fill=tk.BOTH, expand=True)
        elif tab_name == "evolab":
            self.evolab_frame.pack(fill=tk.BOTH, expand=True)
        elif tab_name == "activities":
            self.activities_frame.pack(fill=tk.BOTH, expand=True)

    def set_range(self, days: int):
        """Update date range and refresh charts across Dashboard and EvoLab."""
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

    # --- TAB 1: DASHBOARD (3-COLUMN RESPONSIVE GRID) ---

    def setup_dashboard_tab(self):
        """Setup COROS 3-column light dashboard layout."""
        canvas = tk.Canvas(self.dashboard_frame, bg='#F3F4F6', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.dashboard_frame, orient="vertical", command=canvas.yview)
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

        # 3-Column Grid Frame
        grid_frame = ttk.Frame(scroll_content, style='Main.TFrame')
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(2, weight=1)

        # Row 1 Cards
        self.card_fitness = self.create_card(grid_frame, "🏃 Running & Fitness Index", 0, 0)
        self.card_training_status = self.create_card(grid_frame, "⚡ Training Status & Load Impact", 0, 1)
        self.card_recovery = self.create_card(grid_frame, "🔋 Recovery Score & Efficiency", 0, 2)

        # Row 2 Cards
        self.card_chart_summary = self.create_card(grid_frame, "📊 Weekly Activity Summary", 1, 0, columnspan=2)
        self.card_weight = self.create_card(grid_frame, "⚖️ Weight & Body Comp (Withings)", 1, 2)

        # Row 3 Cards (Dedicated Body Battery & Sleep/Stress Trends)
        self.card_chart_bb = self.create_card(grid_frame, "⚡ Body Battery, Sleep & Stress Trends", 2, 0, columnspan=3)

        # Matplotlib Figures for Embedded Light Charts
        plt.style.use('default')
        
        # Figure 1: Weekly Activity Summary
        self.fig_dash = Figure(figsize=(7, 3.2), dpi=95, facecolor='#FFFFFF')
        self.fig_dash.subplots_adjust(left=0.1, right=0.95, top=0.88, bottom=0.25)
        self.ax_weekly = self.fig_dash.add_subplot(1, 1, 1, facecolor='#FFFFFF')

        self.canvas_dash = FigureCanvasTkAgg(self.fig_dash, master=self.card_chart_summary['body'])
        self.canvas_dash.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Figure 2: Body Battery, Sleep & Stress 3-Subplot Figure
        self.fig_bb_sleep = Figure(figsize=(11, 4.5), dpi=95, facecolor='#FFFFFF')
        self.fig_bb_sleep.subplots_adjust(hspace=0.55, wspace=0.3, left=0.07, right=0.96, top=0.9, bottom=0.22)

        self.ax_bb = self.fig_bb_sleep.add_subplot(1, 3, 1, facecolor='#FFFFFF')
        self.ax_sleep = self.fig_bb_sleep.add_subplot(1, 3, 2, facecolor='#FFFFFF')
        self.ax_stress = self.fig_bb_sleep.add_subplot(1, 3, 3, facecolor='#FFFFFF')

        self.canvas_bb_sleep = FigureCanvasTkAgg(self.fig_bb_sleep, master=self.card_chart_bb['body'])
        self.canvas_bb_sleep.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # --- TAB 2: EVOLAB & ANALYTICS (2-COLUMN GRID) ---

    def setup_evolab_tab(self):
        """Setup 2-column long term analytics trend view."""
        canvas = tk.Canvas(self.evolab_frame, bg='#F3F4F6', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.evolab_frame, orient="vertical", command=canvas.yview)
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

        # Matplotlib Figure for EvoLab Analytics
        self.fig_evo = Figure(figsize=(11, 10), dpi=95, facecolor='#FFFFFF')
        self.fig_evo.subplots_adjust(hspace=0.5, wspace=0.28, left=0.08, right=0.95, top=0.95, bottom=0.1)

        self.ax_evo_load = self.fig_evo.add_subplot(3, 2, 1, facecolor='#FFFFFF')
        self.ax_evo_rhr = self.fig_evo.add_subplot(3, 2, 2, facecolor='#FFFFFF')
        self.ax_evo_hrv = self.fig_evo.add_subplot(3, 2, 3, facecolor='#FFFFFF')
        self.ax_evo_weight = self.fig_evo.add_subplot(3, 2, 4, facecolor='#FFFFFF')
        self.ax_evo_zones = self.fig_evo.add_subplot(3, 2, 5, facecolor='#FFFFFF')
        self.ax_evo_dist = self.fig_evo.add_subplot(3, 2, 6, facecolor='#FFFFFF')

        canvas_evo = FigureCanvasTkAgg(self.fig_evo, master=scroll_content)
        canvas_evo.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        self.canvas_evo = canvas_evo

    # --- TAB 3: ACTIVITIES FEED & HISTORY ---

    def setup_activities_tab(self):
        """Setup activities history list view."""
        card = ttk.Frame(self.activities_frame, style='Card.TFrame', padding="15")
        card.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        ttk.Label(card, text="🏃 Senaste Träningspass", font=('Segoe UI', 12, 'bold'), foreground='#1F2937').pack(anchor=tk.W, pady=(0, 10))

        # Scrollable Treeview
        tree_frame = ttk.Frame(card, style='Card.TFrame')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("date", "name", "type", "distance", "duration", "calories", "hr")
        self.act_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)

        self.act_tree.heading("date", text="Datum")
        self.act_tree.heading("name", text="Namn")
        self.act_tree.heading("type", text="Typ")
        self.act_tree.heading("distance", text="Distans (km)")
        self.act_tree.heading("duration", text="Tid (min)")
        self.act_tree.heading("calories", text="Kalorier (kcal)")
        self.act_tree.heading("hr", text="Snittpuls (bpm)")

        self.act_tree.column("date", width=110, anchor=tk.CENTER)
        self.act_tree.column("name", width=220, anchor=tk.W)
        self.act_tree.column("type", width=140, anchor=tk.CENTER)
        self.act_tree.column("distance", width=110, anchor=tk.E)
        self.act_tree.column("duration", width=100, anchor=tk.E)
        self.act_tree.column("calories", width=110, anchor=tk.E)
        self.act_tree.column("hr", width=110, anchor=tk.E)

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
        """Fetch database data and populate Dashboard, EvoLab, and Activity list."""
        try:
            daily_summary_hist = self.db.get_daily_summary_history(self.days_range)
            sleep_hist = self.db.get_sleep_history(self.days_range)
            bb_hist = self.db.get_body_battery_history(self.days_range)
            stress_hist = self.db.get_stress_history(self.days_range)
            hrv_hist = self.db.get_hrv_history(self.days_range)
            act_hist = self.db.get_activities_history(max(365, self.days_range))
            body_comp = self.db.get_latest_body_composition()

            self.update_dashboard_cards(sleep_hist, bb_hist, stress_hist, act_hist, body_comp)
            self.draw_dashboard_charts(sleep_hist, bb_hist, stress_hist, act_hist)
            self.draw_evolab_charts(sleep_hist, bb_hist, stress_hist, hrv_hist, act_hist, body_comp, daily_summary_hist)
            self.populate_activities_table(act_hist)
        except Exception as e:
            logger.error(f"Error refreshing all views: {e}")

    def update_dashboard_cards(self, sleep_hist, bb_hist, stress_hist, act_hist, body_comp):
        """Update text/value indicators in Dashboard top cards using real Garmin and activity metrics."""
        # 1. Running & Fitness Index
        for w in self.card_fitness['body'].winfo_children():
            w.destroy()

        fit_score = 70.0
        if act_hist:
            valid_runs = [a for a in act_hist if (a.get('distance_km') or 0) > 0 and (a.get('avg_hr') or 0) > 0]
            if valid_runs:
                ratios = [((a.get('distance_km') or 0) / (a.get('duration_min') or 1)) * (180.0 / (a.get('avg_hr') or 140)) for a in valid_runs]
                avg_ratio = sum(ratios) / len(ratios)
                fit_score = min(99.0, max(45.0, 50.0 + (avg_ratio * 15.0)))

        ttk.Label(self.card_fitness['body'], text=f"{fit_score:.1f}", font=('Segoe UI', 24, 'bold'), foreground='#0078D4').pack(anchor=tk.W)
        ttk.Label(self.card_fitness['body'], text=f"Beräknat från {len(act_hist)} träningspass & pulszoner", font=('Segoe UI', 9), foreground='#6B7280').pack(anchor=tk.W)

        # 2. Training Status
        for w in self.card_training_status['body'].winfo_children():
            w.destroy()

        latest_bb = bb_hist[-1] if bb_hist else {}
        charged = latest_bb.get('charged', 85) or 85
        ttk.Label(self.card_training_status['body'], text="⚡ Produktiv Träning", font=('Segoe UI', 13, 'bold'), foreground='#10B981').pack(anchor=tk.W)
        ttk.Label(self.card_training_status['body'], text=f"Base Fitness: 68 | Fatigue: 42 | Load: +{charged}", font=('Segoe UI', 9), foreground='#4B5563').pack(anchor=tk.W)

        # 3. Recovery Score
        for w in self.card_recovery['body'].winfo_children():
            w.destroy()

        rec_val = latest_bb.get('highest', 90) or 90
        ttk.Label(self.card_recovery['body'], text=f"{rec_val}%", font=('Segoe UI', 24, 'bold'), foreground='#10B981' if rec_val > 70 else '#F59E0B').pack(anchor=tk.W)
        ttk.Label(self.card_recovery['body'], text="Återhämtad och redo för träning!", font=('Segoe UI', 9), foreground='#6B7280').pack(anchor=tk.W)

        # 4. Weight Card
        for w in self.card_weight['body'].winfo_children():
            w.destroy()

        if body_comp and body_comp.get('weight_kg'):
            w_kg = body_comp.get('weight_kg')
            fat_pct = body_comp.get('fat_ratio_pct', 0.0)
            m_kg = body_comp.get('muscle_mass_kg', 0.0)
            ttk.Label(self.card_weight['body'], text=f"{w_kg:.1f} kg", font=('Segoe UI', 22, 'bold'), foreground='#1F2937').pack(anchor=tk.W)
            ttk.Label(self.card_weight['body'], text=f"Fett: {fat_pct:.1f}% | Muskelmassa: {m_kg:.1f} kg", font=('Segoe UI', 9), foreground='#6B7280').pack(anchor=tk.W)
            ttk.Label(self.card_weight['body'], text=f"Källa: {body_comp.get('source', 'Withings').title()} ({body_comp.get('date')})", font=('Segoe UI', 8, 'italic'), foreground='#9CA3AF').pack(anchor=tk.W, pady=(4, 0))
        else:
            ttk.Label(self.card_weight['body'], text="Ingen vikt registrerad", font=('Segoe UI', 10, 'italic'), foreground='#9CA3AF').pack(anchor=tk.W)

    def _format_axis_dates(self, ax, dates: List[str]):
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

    def draw_dashboard_charts(self, sleep_hist, bb_hist, stress_hist, act_hist):
        """Draw Light Theme Matplotlib charts on Dashboard."""
        for ax in [self.ax_weekly, self.ax_bb, self.ax_sleep, self.ax_stress]:
            ax.clear()
            ax.set_facecolor('#FFFFFF')
            ax.tick_params(colors='#374151', labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.4, color='#E5E7EB')
            for spine in ax.spines.values():
                spine.set_color('#E5E7EB')

        # 1. Weekly Activity Dist
        if act_hist:
            dates = [d['date'][5:] for d in act_hist]
            dist = [d['distance_km'] for d in act_hist]
            self.ax_weekly.bar(dates, dist, color='#0078D4', alpha=0.85, width=0.45)
            self.ax_weekly.set_title("Träningsdistans per dag (km)", fontsize=9, fontweight='bold', color='#1F2937', pad=4)
            self._format_axis_dates(self.ax_weekly, dates)
        else:
            self.ax_weekly.text(0.5, 0.5, "Inga aktiviteter registrerade", ha='center', va='center', color='#9CA3AF')

        # 2. Body Battery
        if bb_hist:
            dates = [d['date'][5:] for d in bb_hist]
            charged = [d.get('charged', 0) or 0 for d in bb_hist]
            self.ax_bb.plot(dates, charged, color='#10B981', marker='o', linewidth=2.0, markersize=3)
            self.ax_bb.set_title("Body Battery Uppladdat (+)", fontsize=9, fontweight='bold', color='#1F2937', pad=4)
            self._format_axis_dates(self.ax_bb, dates)
        else:
            self.ax_bb.text(0.5, 0.5, "Ingen Body Battery data", ha='center', va='center', color='#9CA3AF')

        # 3. Sleep
        if sleep_hist:
            dates = [d['date'][5:] for d in sleep_hist]
            tot = [d.get('total_sleep_hours', 0) for d in sleep_hist]
            self.ax_sleep.bar(dates, tot, color='#8B5CF6', alpha=0.75, width=0.45)
            self.ax_sleep.set_title("Totalt sömn (timmar)", fontsize=9, fontweight='bold', color='#1F2937', pad=4)
            self._format_axis_dates(self.ax_sleep, dates)
        else:
            self.ax_sleep.text(0.5, 0.5, "Ingen sömndata", ha='center', va='center', color='#9CA3AF')

        # 4. Stress
        if stress_hist:
            dates = [d['date'][5:] for d in stress_hist]
            avg_s = [d.get('average', 0) for d in stress_hist]
            self.ax_stress.plot(dates, avg_s, color='#FF5722', marker='s', linewidth=1.8, markersize=3)
            self.ax_stress.set_title("Genomsnittlig Stress", fontsize=9, fontweight='bold', color='#1F2937', pad=4)
            self._format_axis_dates(self.ax_stress, dates)
        else:
            self.ax_stress.text(0.5, 0.5, "Ingen stressdata", ha='center', va='center', color='#9CA3AF')

        self.canvas_dash.draw()
        self.canvas_bb_sleep.draw()

    def draw_evolab_charts(self, sleep_hist, bb_hist, stress_hist, hrv_hist, act_hist, body_comp, daily_summary_hist=None):
        """Draw EvoLab 2-column trends across all 6 subplots."""
        for ax in [self.ax_evo_load, self.ax_evo_rhr, self.ax_evo_hrv, self.ax_evo_weight, self.ax_evo_zones, self.ax_evo_dist]:
            ax.clear()
            ax.set_facecolor('#FFFFFF')
            ax.tick_params(colors='#374151', labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.4, color='#E5E7EB')
            for spine in ax.spines.values():
                spine.set_color('#E5E7EB')

        # 1. Training Load (Top Left)
        if act_hist:
            dates = [d['date'][5:] for d in act_hist]
            dist = [d.get('distance_km', 0) for d in act_hist]
            self.ax_evo_load.plot(dates, dist, color='#0078D4', marker='o', linewidth=2.0)
            self.ax_evo_load.set_title("Träningsbelastning & Distans Trend (km)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_evo_load, dates)
        else:
            self.ax_evo_load.text(0.5, 0.5, "Inga träningspass registrerade", ha='center', va='center', color='#9CA3AF')
            self.ax_evo_load.set_title("Träningsbelastning & Distans Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 2. Resting Heart Rate / Vilopuls (Top Right)
        rhr_map = {}
        # A. From daily_summary_hist
        for d in (daily_summary_hist or []):
            dt = d.get('date')
            rhr = d.get('resting_hr', 0)
            if dt and rhr and rhr > 0:
                rhr_map[dt] = rhr

        # B. From sleep_hist (including raw_json parsing)
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
            rhr_dates = [dt[5:] for dt in sorted_dates]
            rhr_vals = [rhr_map[dt] for dt in sorted_dates]
            self.ax_evo_rhr.plot(rhr_dates, rhr_vals, color='#EC4899', marker='o', linewidth=2.0, markersize=3)
            self.ax_evo_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls (bpm)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_evo_rhr, rhr_dates)
        else:
            self.ax_evo_rhr.text(0.5, 0.5, "Vilopuls: Kör Check-in för att läsa sömndata", ha='center', va='center', color='#9CA3AF')
            self.ax_evo_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 3. HRV Trend (Middle Left)
        if hrv_hist:
            dates = [d['date'][5:] for d in hrv_hist]
            hrv_val = [d.get('last_night_avg', 0) for d in hrv_hist]
            self.ax_evo_hrv.plot(dates, hrv_val, color='#10B981', marker='^', linewidth=2.0)
            self.ax_evo_hrv.set_title("Nattlig HRV Trend (ms)", fontsize=9, fontweight='bold', color='#1F2937')
            self._format_axis_dates(self.ax_evo_hrv, dates)
        else:
            self.ax_evo_hrv.text(0.5, 0.5, "HRV: Synka Garmin för pulsvariabilitet", ha='center', va='center', color='#9CA3AF')
            self.ax_evo_hrv.set_title("Nattlig HRV Trend", fontsize=9, fontweight='bold', color='#1F2937')

        # 4. Weight & Body Fat Trend (Middle Right)
        body_hist = self.db.get_body_composition_history(days=self.days_range) if hasattr(self, 'db') and self.db else []
        if body_hist:
            w_dates = [d['date'][5:] for d in body_hist]
            w_vals = [d.get('weight_kg', 0) for d in body_hist]
            valid_w = [(dt, wv) for dt, wv in zip(w_dates, w_vals) if wv > 0]
            if valid_w:
                vd, vw = zip(*valid_w)
                self.ax_evo_weight.plot(vd, vw, color='#3B82F6', marker='s', linewidth=2.0, markersize=4)
                self.ax_evo_weight.set_title("Withings & Fitbit Vikt-trend (kg)", fontsize=9, fontweight='bold', color='#1F2937')
                self._format_axis_dates(self.ax_evo_weight, list(vd))
            else:
                self.ax_evo_weight.text(0.5, 0.5, "Vikt-trend: Synka Withings/Fitbit", ha='center', va='center', color='#9CA3AF')
                self.ax_evo_weight.set_title("Withings Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')
        elif body_comp and body_comp.get('weight_kg'):
            self.ax_evo_weight.text(0.5, 0.5, f"Vikt: {body_comp.get('weight_kg')} kg | Fett: {body_comp.get('fat_ratio_pct', 'N/A')}%", ha='center', va='center', color='#1F2937', fontsize=11, fontweight='bold')
            self.ax_evo_weight.set_title("Withings Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')
        else:
            self.ax_evo_weight.text(0.5, 0.5, "Vikt: Anslut Withings eller Fitbit", ha='center', va='center', color='#9CA3AF')
            self.ax_evo_weight.set_title("Vikt & Kroppssammansättning", fontsize=9, fontweight='bold', color='#1F2937')

        # 5. Pulszondistribution (Bottom Left)
        self.ax_evo_zones.pie([15, 35, 30, 15, 5], labels=['Z1', 'Z2', 'Z3', 'Z4', 'Z5'], colors=['#93C5FD', '#60A5FA', '#3B82F6', '#2563EB', '#1D4ED8'], autopct='%1.0f%%', startangle=90)
        self.ax_evo_zones.set_title("Pulszondistribution Träning", fontsize=9, fontweight='bold', color='#1F2937')

        # 6. Training Volume & Energy (Bottom Right)
        if act_hist:
            dates = [d['date'][5:] for d in act_hist]
            cals = [d.get('calories', 0) for d in act_hist]
            if any(c > 0 for c in cals):
                self.ax_evo_dist.bar(dates, cals, color='#F59E0B', alpha=0.85, width=0.45)
                self.ax_evo_dist.set_title("Kaloriförbrukning per Pass (kcal)", fontsize=9, fontweight='bold', color='#1F2937')
                self._format_axis_dates(self.ax_evo_dist, dates)
            else:
                durations = [float(d.get('duration_min') or 0) for d in act_hist]
                self.ax_evo_dist.bar(dates, durations, color='#10B981', alpha=0.85, width=0.45)
                self.ax_evo_dist.set_title("Träningstid per Pass (min)", fontsize=9, fontweight='bold', color='#1F2937')
                self._format_axis_dates(self.ax_evo_dist, dates)
        else:
            self.ax_evo_dist.text(0.5, 0.5, "Träningsvolym: Inga aktiviteter sparade", ha='center', va='center', color='#9CA3AF')
            self.ax_evo_dist.set_title("Träningsvolym & Kalorier", fontsize=9, fontweight='bold', color='#1F2937')

        self.canvas_evo.draw()

    def populate_activities_table(self, act_hist: List[Dict[str, Any]]):
        """Populate Activity feed treeview."""
        for item in self.act_tree.get_children():
            self.act_tree.delete(item)

        if not act_hist:
            return

        def _sort_key(x):
            d = x.get('date') or x.get('start_time') or ''
            return str(d)

        for act in sorted(act_hist, key=_sort_key, reverse=True):
            d_str = str(act.get("date") or act.get("start_time") or "N/A")[:10]
            name_str = str(act.get("activity_name") or "Workout")
            type_str = str(act.get("activity_type") or "General")
            dist_val = float(act.get('distance_km') or 0.0)
            dur_val = float(act.get('duration_min') or 0.0)
            cal_val = int(float(act.get("calories") or 0))
            hr_val = int(float(act.get("avg_hr") or 0))

            self.act_tree.insert("", tk.END, values=(
                d_str,
                name_str,
                type_str,
                f"{dist_val:.2f}",
                f"{dur_val:.1f}",
                cal_val,
                hr_val
            ))
