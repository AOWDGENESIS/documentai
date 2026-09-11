#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DocumentAI – Portable Dokumentenintelligenz (GUI oder CLI).

Aufruf ohne Argumente      → grafische Oberfläche (Windows)
DocumentAI.py --cli ...     → Kommandozeilenmodus
DocumentAI.py --selbsttest  → Selbstdiagnose
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Windows-Konsollen stehen oft auf cp850/cp1252 (auch bei Datei-Umleitung):
# UTF-8 mit Fallback erzwingen, damit deutsche Texte und ✓/✗-Symbole
# niemals einen UnicodeEncodeError auslösen (getestet unter Wine/Windows).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                  # noqa: BLE001
        pass

# Sicherstellen, dass das Projektverzeichnis im Pfad liegt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _cli_analyse(service, args) -> int:
    model, session, engine = service.open_document(args.datei,
                                                   args.passwort or None)
    service.analyze(model, session, engine)
    print("Dokumentanalyse")
    print("───────────────")
    for line in model.summary_lines():
        print(line)
    d = model.diagnosis
    print(f"  Bearbeitung erlaubt: {'ja' if d.get('bearbeitung_erlaubt') else 'nein'}"
          f" | Drucken: {'ja' if d.get('drucken_erlaubt') else 'nein'}"
          f" | Kopieren: {'ja' if d.get('kopieren_erlaubt') else 'nein'}")
    print(f"  PDF/A-Status: {d.get('pdfa_status', '-')}")
    print(f"  Metadaten: {len(d.get('metadaten', {}))} Einträge, "
          f"eingebettete Dateien: {len(d.get('eingebettete_dateien', []))}")
    if model.signature_info.get("vorhanden"):
        print("\n⚠ Digitale Signatur erkannt – Änderungen erzeugen eine "
              "NEUE Version; das Original bleibt erhalten.")
    counts = model.issue_counts()
    print(f"\nPrüfung abgeschlossen: {counts['fehler']} Fehler, "
          f"{counts['warnung']} Warnungen, {counts['hinweis']} Hinweise")
    for issue in model.issues[:20]:
        icon = {"fehler": "✗", "warnung": "⚠", "hinweis": "ℹ"}[issue.severity]
        print(f"  {icon} {issue.message}")
    return 0


def _cli_felder(service, args) -> int:
    model, session, engine = service.open_document(args.datei,
                                                   args.passwort or None)
    service.analyze(model, session, engine)
    print(f"{len(model.fields)} Felder erkannt:\n")
    for f in model.fields:
        wert = "" if f.value is None else f" = {f.value}"
        stern = "*" if f.required else ""
        print(f"  S{f.page + 1} [{f.field_type}] {f.label or f.name}{stern}"
              f"{wert}  ({f.source}, {round(f.confidence * 100, 1)} %"
              + (f", →{f.canonical}" if f.canonical else "") + ")")
    return 0


def _cli_befuellen(service, args) -> int:
    model, session, engine = service.open_document(args.datei,
                                                   args.passwort or None)
    service.analyze(model, session, engine)
    profile = {}
    if args.profil:
        if os.path.splitext(args.profil)[1].lower() == ".json":
            with open(args.profil, "r", encoding="utf-8") as fh:
                profile = json.load(fh)
        else:
            from documentai.services import profile as prof
            profile = prof.import_file(args.profil)
    elif args.freitext:
        lines = args.freitext.split("\\n")
        from documentai.engines.semantic import RuleSemanticAnalyzer
        profile = RuleSemanticAnalyzer().parse_freeform_lines(lines)
    if not profile:
        print("Keine Profildaten vorhanden (data/profil.json, --profil oder "
              "--freitext angeben).")
        return 2
    assignments = service.prepare_fill(model, profile)
    if not assignments:
        print("Keine passenden Felder für die Profildaten gefunden.")
        return 2
    print("Vorgeschlagene Zuordnung (bitte prüfen):\n")
    for i, a in enumerate(assignments, 1):
        flag = " [PRÜFEN]" if a["pruefen"] else ""
        print(f"  {i:2}. {a['feld']:<28} → {a['wert']:<28} "
              f"({round(a['konfidenz'] * 100)} %{flag})")
    if not args.ja:
        antwort = input("\nZuordnung übernehmen? [J/n] ").strip().lower()
        if antwort not in ("", "j", "ja", "y", "yes"):
            print("Abgebrochen – es wurde nichts geändert.")
            return 1
    service.apply_fill(model, session, engine, assignments)
    result = service.save_new_version(model, session, engine,
                                      reason="Formularbefüllung")
    pruefung = result["pruefung"]
    print(f"\n✓ Neue Version erzeugt: {result['pfad']}")
    print(f"  Verifikation: {'OK' if pruefung['ok'] else 'PROBLEM'} "
          f"({pruefung['seiten']} Seiten geprüft)")
    if not pruefung["ok"]:
        for problem in pruefung["probleme"]:
            print(f"  ⚠ {problem}")
        return 3
    return 0


def _cli_validieren(service, args) -> int:
    model, session, engine = service.open_document(args.datei,
                                                   args.passwort or None)
    service.analyze(model, session, engine)
    counts = model.issue_counts()
    if not any(counts.values()):
        print("✓ Prüfung abgeschlossen – keine Probleme gefunden.")
        return 0
    print(f"⚠ Prüfung abgeschlossen – {counts['fehler'] + counts['warnung']} "
          f"Probleme gefunden:\n")
    for issue in model.issues:
        icon = {"fehler": "✗", "warnung": "⚠", "hinweis": "ℹ"}[issue.severity]
        print(f"  {icon} {issue.message}")
        if issue.suggestion:
            print(f"      Vorschlag: {issue.suggestion}")
    return 1 if counts["fehler"] else 0


def _cli_export(service, args) -> int:
    model, session, engine = service.open_document(args.datei,
                                                   args.passwort or None)
    service.analyze(model, session, engine)
    from documentai.engines.exporter import ExportEngine
    dest = args.ziel
    if not dest:
        base = os.path.splitext(args.datei)[0]
        ext = {"pdf": ".pdf", "txt": "_export.txt", "json": "_export.json",
               "csv": "_felder.csv", "docx": "_export.docx",
               "png": "_seiten", "pdfa": "_pdfa.pdf"}[args.format]
        dest = base + ext
    result = ExportEngine().export(model, session, engine, args.format, dest)
    if result.get("ok"):
        print(f"✓ Export erstellt: {result.get('pfad', dest)}")
        if result.get("pruefung"):
            print(f"  Verifikation: {result['pruefung']}")
        return 0
    print(f"✗ Export fehlgeschlagen: {result.get('fehler', result)}")
    return 3


def _cli_datenbank(service, args) -> int:
    """Verschlüsselte Personen-Datenbank verwalten."""
    import getpass

    from documentai.services import vault as vault_mod
    from documentai.services.extraction import (collect_from_document,
                                                proposals_to_text)
    from documentai.services.vault import SecureVault, VaultError

    pfad = args.db or vault_mod.default_path()
    pw = args.passwort or getpass.getpass("Master-Passwort: ")
    aktion = args.aktion

    def _resolve_person(vault, angabe: str) -> int:
        if angabe.isdigit():
            return int(angabe)
        for p in vault.list_persons():
            if p["name"].lower() == (angabe or "").lower():
                return p["id"]
        raise VaultError("Person nicht gefunden: %r (vorhanden: %s)"
                         % (angabe, ", ".join(p["name"] for p in
                                              vault.list_persons())))

    if aktion == "erstellen":
        if not args.neues_passwort:
            pw2 = getpass.getpass("Master-Passwort wiederholen: ")
            if pw != pw2:
                print("✗ Passwörter stimmen nicht überein.")
                return 2
        vault = SecureVault.create(pw, pfad)
        vault.close()
        print(f"✓ Verschlüsselter Tresor erstellt: {pfad}")
        return 0

    vault = SecureVault.open(pw, pfad)
    try:
        if aktion == "personen":
            for p in vault.list_persons():
                print(f"  [{p['id']}] {p['name']}"
                      + (f" – {p['rolle']}" if p["rolle"] else "")
                      + f" ({p['datenfelder']} Datenfelder)")
        elif aktion == "person-anlegen":
            if not args.name:
                print("✗ --name angeben")
                return 2
            pid = vault.add_person(args.name, args.rolle or "")
            vault.save()
            print(f"✓ Person angelegt: [{pid}] {args.name}")
        elif aktion == "daten-setzen":
            if not (args.person and args.key and args.wert):
                print("✗ --person, --key und --wert angeben")
                return 2
            pid = _resolve_person(vault, args.person)
            vault.set_datum(pid, args.key, args.wert)
            vault.save()
            print(f"✓ Gespeichert: {args.key} = {args.wert}")
        elif aktion == "daten-anzeigen":
            if not args.person:
                print("✗ --person angeben (Name oder ID)")
                return 2
            pid = _resolve_person(vault, args.person)
            person = vault.get_person(pid)
            print(f"Stammdaten: {person['name']}"
                  + (f" ({person['rolle']})" if person["rolle"] else ""))
            daten = vault.get_data(pid)
            if not daten:
                print("  (noch keine Daten)")
            for key, info in daten.items():
                print(f"  {key:<18} = {info['wert']:<34}"
                      f"[{info['quelle']}, "
                      f"{round(info['konfidenz'] * 100)} %]")
        elif aktion == "import":
            if not args.datei:
                print("✗ --datei angeben")
                return 2
            proposals, model, _session = collect_from_document(
                service, args.datei, args.passwort_dokument or "")
            print("Erkannte Daten:\n")
            print(proposals_to_text(proposals))
            if not proposals:
                return 1
            # Automatische Personen-Zuordnung (Spec §4)
            pid_vorschlag, score = vault.match_person(proposals)
            ziel = None
            if args.person:
                ziel = _resolve_person(vault, args.person)
            elif pid_vorschlag:
                person = vault.get_person(pid_vorschlag)
                print(f"\nAutomatische Zuordnung: {person['name']} "
                      f"({int(score * 100)} % Übereinstimmung)")
                if args.freigabe or input("Übernehmen? [J/n] ").strip() \
                        .lower() in ("", "j", "ja"):
                    ziel = pid_vorschlag
            if ziel is None:
                print("Keine Zuordnung – Daten werden nur als unverknüpfte "
                      "Extraktion gespeichert.")
                doc_id = vault.add_document(args.datei, model.sha256,
                                            len(model.pages),
                                            model.source_format)
                for p in proposals:
                    vault.add_extraction(doc_id, p["key"], p["wert"],
                                         p["konfidenz"])
                vault.save()
                print("✓ Extraktionen (ungeprüft) gespeichert.")
                return 0
            doc_id = vault.add_document(args.datei, model.sha256,
                                        len(model.pages),
                                        model.source_format, ziel)
            n = vault.adopt_extractions(ziel, proposals, doc_id)
            vault.save()
            person = vault.get_person(ziel)
            print(f"\n✓ {n} Einträge in die verschlüsselte Datenbank "
                  f"übernommen (Person: {person['name']}).")
        elif aktion == "statistik":
            for key, value in vault.statistics().items():
                print(f"  {key:<14}: {value}")
        elif aktion == "passwort-aendern":
            neu = args.neues_passwort or getpass.getpass(
                "Neues Master-Passwort: ")
            vault.change_master_password(pw, neu)
            vault.close()
            print("✓ Master-Passwort geändert.")
            return 0
        return 0
    finally:
        vault.close()


def _cli_vergleich(service, args) -> int:
    result = service.compare_paths(args.datei_a, args.datei_b)
    from documentai.engines.compare import format_text_diff
    print(format_text_diff(result))
    vis = result.get("visuell", {})
    if vis.get("bilder"):
        print(f"\nVisueller Vergleich: {len(vis['bilder'])} Vergleichsbilder")
        for bild in vis["bilder"][:10]:
            print(f"  {bild}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="DocumentAI",
        description="Portable Dokumentenintelligenz & "
                    "PDF-Formularautomatisierung")
    parser.add_argument("--cli", action="store_true",
                        help="Kommandozeilenmodus statt GUI")
    parser.add_argument("--selbsttest", action="store_true",
                        help="Selbstdiagnose ausführen")
    sub = parser.add_subparsers(dest="befehl")

    p_an = sub.add_parser("analyse", help="Dokument vollständig analysieren")
    p_fe = sub.add_parser("felder", help="erkannte Felder anzeigen")
    p_be = sub.add_parser("befuellen", help="Formular aus Profil befüllen")
    p_va = sub.add_parser("validieren", help="Validierung ausführen")
    p_ex = sub.add_parser("export", help="Export erzeugen")
    p_gl = sub.add_parser("vergleich", help="zwei Versionen vergleichen")
    p_db = sub.add_parser("datenbank",
                          help="verschlüsselte Personen-Datenbank")

    p_db.add_argument("aktion",
                      choices=["erstellen", "personen", "person-anlegen",
                               "daten-setzen", "daten-anzeigen", "import",
                               "statistik", "passwort-aendern"])
    p_db.add_argument("--db", default="", help="Pfad zur Tresor-Datei")
    p_db.add_argument("--passwort", default="",
                      help="Master-Passwort (sonst sichere Eingabe)")
    p_db.add_argument("--neues-passwort", default="")
    p_db.add_argument("--name", default="")
    p_db.add_argument("--rolle", default="")
    p_db.add_argument("--key", default="")
    p_db.add_argument("--wert", default="")
    p_db.add_argument("--person", default="",
                      help="Name oder ID einer Person")
    p_db.add_argument("--datei", default="",
                      help="Dokument für Datenimport")
    p_db.add_argument("--passwort-dokument", default="",
                      help="Passwort für ein geschütztes Importdokument")
    p_db.add_argument("--freigabe", action="store_true",
                      help="Import ohne Rückfrage übernehmen")

    for p in (p_an, p_fe, p_be, p_va, p_ex):
        p.add_argument("datei")
        p.add_argument("--passwort", default="")
    p_be.add_argument("--profil", default="",
                      help="JSON/CSV-Datei mit Profildaten")
    p_be.add_argument("--freitext", default="",
                      help='Freitextdaten, Zeilen mit \\n getrennt')
    p_be.add_argument("--ja", action="store_true",
                      help="Zuordnung ohne Rückfrage übernehmen")
    p_ex.add_argument("--format", default="json",
                      choices=["pdf", "txt", "json", "csv", "docx", "png",
                               "pdfa"])
    p_ex.add_argument("--ziel", default="")
    p_gl.add_argument("datei_a")
    p_gl.add_argument("datei_b")

    args = parser.parse_args()

    from documentai.paths import ensure_dirs
    ensure_dirs()

    if args.selbsttest or args.befehl == "selbsttest":
        from documentai.selftest import format_checks, run_selftest
        print("SELBSTDIAGNOSE – DocumentAI")
        print("════════════════════════════")
        print(format_checks(run_selftest()))
        return 0

    if not args.cli and not args.befehl:
        return _start_gui()

    from documentai.core import registry
    registry.bootstrap()
    from documentai.services.analysis import AnalysisService
    service = AnalysisService()

    handlers = {"analyse": _cli_analyse, "felder": _cli_felder,
                "befuellen": _cli_befuellen, "validieren": _cli_validieren,
                "export": _cli_export, "vergleich": _cli_vergleich,
                "datenbank": _cli_datenbank}
    if not args.befehl:
        parser.print_help()
        return 0
    try:
        return handlers[args.befehl](service, args)
    except Exception as exc:
        from documentai.core.errors import DocumentAIError
        from documentai.util import write_error_report
        path = write_error_report(exc, action=args.befehl,
                                  component="cli")
        print(f"✗ {exc if isinstance(exc, DocumentAIError) else exc}")
        print(f"  Fehlerbericht: {path}")
        return 4


def _start_gui() -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter ist nicht verfügbar. Bitte Python mit tk-Unterstützung "
              "installieren (python.org-Installer) oder --cli verwenden.")
        return 4
    try:
        from documentai.gui.app import DocumentAIApp
        app = DocumentAIApp()
        app.run()
        return 0
    except Exception as exc:
        from documentai.util import write_error_report
        path = write_error_report(exc, action="GUI-Start", component="gui")
        print(f"✗ GUI-Fehler: {exc}")
        print(f"  Fehlerbericht: {path}")
        return 4


if __name__ == "__main__":
    sys.exit(main())
