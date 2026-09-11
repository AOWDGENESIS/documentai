"""Unterschriften-Pad: mit Maus, Touchpad oder Zeichentablet/Stift.

Mehrere Striche (wie eine echte Unterschrift: Punkte, Unterstreichungen).
Die Eingabe wird geglättet und die Strichstärke an die Zeichengeschwin-
digkeit angepasst (langsam = kräftig wie mit Druck, schnell = fein) –
das ergibt mit einem Zeichenstift ein natürliches Schriftbild.

Der Export erfolgt deterministisch aus den Strichpunkten als PNG mit
transparentem Hintergrund (kein Canvas-Screenshot, keine Abhängigkeit
von der Bildschirmauflösung).
"""
from __future__ import annotations

import io
import time

import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except Exception:                                  # pragma: no cover
    PIL_OK = False

FARBE = (13, 27, 62)          # dunkles Tintenblau
MIN_BREITE = 2.2              # px im Export (Standardzoom)
MAX_BREITE = 5.6
GLAETTUNG = 0.35              # Anteil des neuen Punktes (0..1)
EXPORT_SKALA = 2.0            # Auflösungs-Vergrößerung des PNG


class SignaturPad(tk.Toplevel):
    """Dialog zum Zeichnen einer Unterschrift.

    on_uebernehmen(png_bytes) wird mit dem PNG aufgerufen, wenn der
    Nutzer „Übernehmen“ wählt. Der Dialog schließt sich danach selbst.
    """

    def __init__(self, master, on_uebernehmen=None, on_speichern=None):
        super().__init__(master)
        self.title("Unterschrift zeichnen")
        self.configure(background="#ffffff")
        self.resizable(False, False)
        self.on_uebernehmen = on_uebernehmen
        self.on_speichern = on_speichern
        self.streiche: list[list[tuple[float, float, float]]] = []
        self._aktuell: list[tuple[float, float, float]] = []
        self._letzte = None
        self._id_counter = 0

        ttk.Label(self, text="Unterschrift zeichnen",
                  font=("Segoe UI", 12, "bold")).pack(pady=(10, 2))
        ttk.Label(self, text="Maus, Touchpad oder Zeichenstift – Striche "
                  "werden geglättet, mehrere Striche möglich.",
                  foreground="#5a6472").pack()

        rahmen = tk.Frame(self, background="#d8dce4", bd=1, relief=tk.FLAT)
        rahmen.pack(padx=14, pady=8)
        self.canvas = tk.Canvas(rahmen, width=520, height=200,
                                background="#ffffff", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(padx=1, pady=1)
        # Anhaltelinie wie auf echten Formularen
        self.canvas.create_line(30, 158, 490, 158, fill="#c9cedb",
                                dash=(4, 3))
        self.canvas.create_text(18, 158, text="X", anchor=tk.W,
                                fill="#9aa2b4", font=("Segoe UI", 11, "bold"))

        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._up)

        leiste = ttk.Frame(self)
        leiste.pack(fill=tk.X, padx=12)
        ttk.Button(leiste, text="↩ Strich zurück",
                   command=self.strich_zurueck).pack(side=tk.LEFT, padx=2)
        ttk.Button(leiste, text="🗑 Alles löschen",
                   command=self.alles_loeschen).pack(side=tk.LEFT, padx=2)

        speicher_zeile = ttk.Frame(self)
        speicher_zeile.pack(fill=tk.X, padx=12, pady=(6, 0))
        ttk.Label(speicher_zeile, text="Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(speicher_zeile, textvariable=self.name_var, width=22
                  ).pack(side=tk.LEFT, padx=4)
        ttk.Button(speicher_zeile, text="💾 Für Wiederverwendung speichern",
                   command=self._nur_speichern).pack(side=tk.LEFT, padx=2)

        bottom = ttk.Frame(self)
        bottom.pack(pady=8)
        ttk.Button(bottom, text="✍ Übernehmen",
                   style="Akzent.TButton",
                   command=self._uebernehmen).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Abbrechen",
                   command=self.destroy).pack(side=tk.LEFT, padx=4)
        self.status = ttk.Label(self, text="", foreground="#5a6472")
        self.status.pack(pady=(0, 6))
        self.bind("<Escape>", lambda _e: self.destroy())

    # -------------------------------------------------- Eingaben
    def _down(self, event) -> None:
        self._aktuell = [(event.x, event.y, time.time())]
        self._letzte = (event.x, event.y)

    def _motion(self, event) -> None:
        if not self._aktuell:
            return
        x, y = event.x, event.y
        letzter = self._aktuell[-1]
        # Glättung: Punkt liegt zu GLAETTUNG am neuen Messwert
        gx = letzter[0] + (x - letzter[0]) * 0.65 + \
            (x - letzter[0]) * GLAETTUNG * 0.35
        gy = letzter[1] + (y - letzter[1]) * 0.65 + \
            (y - letzter[1]) * GLAETTUNG * 0.35
        self._aktuell.append((gx, gy, time.time()))
        breite = self._breite(self._aktuell[-2], self._aktuell[-1])
        self._id_counter += 1
        self.canvas.create_line(self._letzte[0], self._letzte[1], gx, gy,
                                width=breite, capstyle=tk.ROUND,
                                smooth=True, fill="#0d1b3e", tags="ink")
        self._letzte = (gx, gy)

    def _up(self, _event) -> None:
        if len(self._aktuell) > 1:
            self.streiche.append(self._aktuell)
        self._aktuell = []
        self._letzte = None

    # -------------------------------------------------- Strichbreite
    @staticmethod
    def _breite(p1: tuple, p2: tuple) -> float:
        """Schnelles Ziehen = feine Linie, langsames = kräftige Linie
        (nachempfunden dem Druck eines Zeichenstifts)."""
        import math
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        dt = max(0.004, p2[2] - p1[2])
        geschwindigkeit = dist / dt               # px/s
        if geschwindigkeit >= 1400:
            return MIN_BREITE
        if geschwindigkeit <= 160:
            return MAX_BREITE
        anteil = (geschwindigkeit - 160) / (1400 - 160)
        return MAX_BREITE - anteil * (MAX_BREITE - MIN_BREITE)

    # -------------------------------------------------- Aktionen
    def strich_zurueck(self) -> None:
        if self.streiche:
            self.streiche.pop()
            self.canvas.delete("ink")
            for strich in self.streiche:
                self._zeichne(strich)
            self.status.configure(text="Letzter Strich entfernt.")

    def _zeichne(self, strich: list) -> None:
        for i in range(1, len(strich)):
            breite = self._breite(strich[i - 1], strich[i])
            self.canvas.create_line(strich[i - 1][0], strich[i - 1][1],
                                    strich[i][0], strich[i][1], width=breite,
                                    capstyle=tk.ROUND, smooth=True,
                                    fill="#0d1b3e", tags="ink")

    def alles_loeschen(self) -> None:
        self.streiche = []
        self.canvas.delete("ink")
        self.status.configure(text="Geleert – neu zeichnen.")

    # -------------------------------------------------- Export
    def ist_leer(self) -> bool:
        return not any(len(s) > 1 for s in self.streiche)

    def png_bytes(self) -> bytes | None:
        """Rendert die Striche in ein PNG mit transparentem Hintergrund
        (2-fache Auflösung). Liefert None bei leerer Fläche."""
        if not PIL_OK or self.ist_leer():
            return None
        punkte = [(x, y) for strich in self.streiche for x, y, _t in strich]
        x0 = max(0, min(x for x, _y in punkte) - 6)
        y0 = max(0, min(y for _x, y in punkte) - 6)
        x1 = min(520, max(x for x, _y in punkte) + 6)
        y1 = min(200, max(y for _x, y in punkte) + 6)
        breite = max(2, int((x1 - x0) * EXPORT_SKALA))
        hoehe = max(2, int((y1 - y0) * EXPORT_SKALA))
        img = Image.new("RGBA", (breite, hoehe), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for strich in self.streiche:
            for i in range(1, len(strich)):
                p1 = ((strich[i - 1][0] - x0) * EXPORT_SKALA,
                      (strich[i - 1][1] - y0) * EXPORT_SKALA)
                p2 = ((strich[i][0] - x0) * EXPORT_SKALA,
                      (strich[i][1] - y0) * EXPORT_SKALA)
                breite_strich = self._breite(strich[i - 1], strich[i]) \
                    * EXPORT_SKALA
                draw.line([p1, p2], fill=FARBE + (255,),
                          width=max(1, int(round(breite_strich))))
        puffer = io.BytesIO()
        img.save(puffer, format="PNG")
        return puffer.getvalue()

    # -------------------------------------------------- Buttons
    def _nur_speichern(self) -> None:
        if self.ist_leer():
            self.status.configure(text="Noch nichts gezeichnet.")
            return
        if self.on_speichern is not None:
            ergebnis = self.on_speichern(self.name_var.get().strip()
                                         or "Unterschrift",
                                         self.png_bytes())
            self.status.configure(text=f"Gespeichert: {ergebnis}")

    def _uebernehmen(self) -> None:
        png = self.png_bytes()
        if png is None:
            self.status.configure(text="Bitte zuerst eine Unterschrift "
                                       "zeichnen.")
            return
        name = self.name_var.get().strip()
        if name and self.on_speichern is not None:
            self.on_speichern(name, png)          # gleichzeitig sichern
        if self.on_uebernehmen is not None:
            self.on_uebernehmen(png)
        self.destroy()
