#!/usr/bin/env python3
"""
Synthetischer Trainingsdaten-Generator für Anrufwerker QLoRA Fine-Tuning.

Generiert realistische Telefongespräche für verschiedene Handwerksbetriebe.
Ausgabe: JSONL im Chat-Format (system + turns) — direkt für QLoRA nutzbar.

Usage:
    python generate_training_data.py --count 500 --output training_data.jsonl
    python generate_training_data.py --count 100 --model mistral-large-3:675b-cloud

Nach Datensammlung löschen:
    rm tools/generate_training_data.py
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "mistral-large-3:675b-cloud"
DEFAULT_COUNT = 500
DEFAULT_OUTPUT = "training_data.jsonl"

# ---------------------------------------------------------------------------
# Fiktive Handwerksbetriebe
# ---------------------------------------------------------------------------

COMPANIES = [
    {
        "company_name": "Malerbetrieb Schneider",
        "owner_name": "Herrn Schneider",
        "services": ["Innenanstriche", "Außenanstriche", "Tapezierarbeiten", "Fassadensanierung"],
        "opening_hours": "Montag bis Freitag, 7 bis 17 Uhr",
        "phone_callback": "0851 / 44 22 100",
        "company_since": "1987",
        "company_address": "Bahnhofstraße 12, 84032 Landshut",
        "employee_count": "ca. 6 Mitarbeiter",
        "emergency_number": None,
    },
    {
        "company_name": "Elektro Huber GmbH",
        "owner_name": "Herrn Huber",
        "services": ["Elektroinstallation", "Photovoltaik", "Wallbox-Montage", "Beleuchtungsplanung", "Sicherheitstechnik"],
        "opening_hours": "Montag bis Freitag, 8 bis 18 Uhr, Samstag 9 bis 13 Uhr",
        "phone_callback": "089 / 23 45 678",
        "company_since": "2001",
        "company_address": "Industriestraße 44, 80939 München",
        "employee_count": "ca. 15 Mitarbeiter",
        "emergency_number": "0173 / 999 00 11 (Notdienst 24/7)",
    },
    {
        "company_name": "Sanitär & Heizung Bauer",
        "owner_name": "Herrn Bauer",
        "services": ["Heizungsinstallation", "Badezimmerrenovierung", "Rohrreparatur", "Wartung", "Notdienst"],
        "opening_hours": "Montag bis Freitag, 7:30 bis 17 Uhr",
        "phone_callback": "0911 / 55 66 77",
        "emergency_number": "0800 / 55 66 77 (Wassernotfall, kostenlos)",
    },
    {
        "company_name": "Dachdeckerei Weber",
        "owner_name": "Herrn Weber",
        "services": ["Dachsanierung", "Dachreparatur", "Flachdach", "Dachfenster", "Regenrinnen"],
        "opening_hours": "Montag bis Freitag, 7 bis 16 Uhr",
        "phone_callback": "0821 / 77 88 99",
        "emergency_number": "0172 / 44 55 66 (Sturmschäden)",
    },
    {
        "company_name": "Fliesenleger Müller",
        "owner_name": "Herrn Müller",
        "services": ["Badezimmer-Fliesenarbeiten", "Küchenfliesen", "Bodenfliesen", "Terrasse"],
        "opening_hours": "Montag bis Freitag, 8 bis 17 Uhr",
        "phone_callback": "0941 / 11 22 33",
        "emergency_number": None,
    },
    {
        "company_name": "Schreinerei Hoffmann",
        "owner_name": "Herrn Hoffmann",
        "services": ["Küchenmontage", "Einbauschränke", "Türen und Fenster", "Maßmöbel", "Parkett"],
        "opening_hours": "Montag bis Freitag, 7 bis 17 Uhr, Samstag nach Vereinbarung",
        "phone_callback": "0861 / 33 44 55",
        "emergency_number": None,
    },
    {
        "company_name": "Gartenbau Richter",
        "owner_name": "Herrn Richter",
        "services": ["Gartengestaltung", "Rasenpflege", "Heckenschnitt", "Pflasterarbeiten", "Baumfällung"],
        "opening_hours": "Montag bis Freitag, 7 bis 18 Uhr, Samstag 8 bis 14 Uhr",
        "phone_callback": "0931 / 66 77 88",
        "emergency_number": None,
    },
    {
        "company_name": "Zimmerei & Holzbau Fischer",
        "owner_name": "Herrn Fischer",
        "services": ["Dachstuhl", "Carport", "Holzterrassen", "Gauben", "Holzfassade"],
        "opening_hours": "Montag bis Freitag, 6:30 bis 16:30 Uhr",
        "phone_callback": "0851 / 88 99 00",
        "emergency_number": "0176 / 11 22 33 (Sturm/Notfall)",
    },
]

# ---------------------------------------------------------------------------
# Szenarien: Wer ruft an und warum?
# ---------------------------------------------------------------------------

SCENARIOS = [
    # Anfragen — normaler Verlauf
    "Ein freundlicher Rentner möchte Innenrenovierung anfragen. Er ist etwas langsam aber höflich. Gibt Adresse mit PLZ an.",
    "Eine berufstätige Frau ruft in der Mittagspause an, hat wenig Zeit. Möchte Anfrage für Renovierung hinterlassen.",
    "Eine Hausbesitzerin fragt erst nach Leistungen, dann hinterlässt sie eine Anfrage mit Name, Adresse, Anliegen.",
    "Ein Anrufer gibt seine Adresse stückweise an — erst Straße, dann Hausnummer, dann Ort. Bot bestätigt PLZ.",
    "Ein Anrufer nennt zuerst falschen Namen und korrigiert sich dann. Adresse liegt in kleinem Dorf, Bot bestätigt PLZ.",
    "Eine Dame gibt einen sehr ungewöhnlichen Nachnamen an — Bot fragt höflich nach Schreibweise.",
    "Ein Anrufer hinterlässt Anfrage für Kollegin (Stellvertretung) — kennt nicht alle Details, muss zweimal nachfragen.",

    # Anfragen — mit Komplikationen
    "Ein Anrufer möchte dringend jemanden diese Woche. Er ist ungeduldig als er hört dass der Chef zurückruft.",
    "Ein Anrufer fragt nach einem Wunschtermin — Bot erklärt: Termine werden beim Rückruf abgeklärt.",
    "Ein Anrufer besteht auf einem konkreten Termin jetzt am Telefon. Bot bleibt freundlich aber klar: erst Rückruf.",
    "Ein Anrufer ist sehr alt und braucht Geduld — wiederholt sich, hört schlecht, muss mehrmals bestätigt werden.",
    "Eine Frau ruft für ihren Mann an und kennt Adresse nicht vollständig — muss nachschlagen.",

    # Eskalation
    "Ein verärgerter Anrufer beschwert sich über eine frühere Arbeit. Bot eskaliert freundlich: Chef ruft zurück.",
    "Ein Anrufer versucht einen Preis zu bekommen — wird ungeduldig. Bot bleibt konsequent: keine Preise.",
    "Ein Anrufer stellt Fragen zu Gewährleistung und Haftung. Bot kann nicht antworten und eskaliert.",
    "Ein Geschäftskunde droht mit Konkurrenz und will sofortige Zusage. Bot nimmt Anfrage auf und kündigt Rückruf an.",

    # Infos / Betrieb
    "Ein Anrufer fragt nach den Öffnungszeiten und ob samstags gearbeitet wird.",
    "Ein Anrufer fragt wie lange der Betrieb schon existiert und wie viele Mitarbeiter es gibt.",
    "Ein Anrufer fragt nach der Betriebsadresse weil er Unterlagen schicken möchte.",
    "Ein Anrufer fragt welche konkreten Leistungen angeboten werden — mehrere Nachfragen.",
    "Ein Immobilienverwalter fragt ob der Betrieb auch größere Wohnanlagen betreut.",

    # Missverständnisse
    "Ein Anrufer ist bei der falschen Firma gelandet und merkt das erst nach der Begrüßung.",
    "Ein Anrufer redet sehr undeutlich. Bot muss mehrmals nachfragen.",
    "Ein Anrufer wechselt mehrmals das Thema — von Innenrenovierung zu Fassade zu Termin.",
    "Ein Anrufer nennt bei der Adresse einen Ortsteil den es nicht gibt. Bot fragt freundlich nach.",

    # Notfall
    "Ein Anrufer hat einen Wasserrohrbruch und ist in Panik. Bot prüft ob Notdienst vorhanden, eskaliert wenn nicht.",
    "Ein Anrufer meldet Sturmschäden. Bot nimmt Anfrage auf und prüft ob Notdienst existiert.",

    # Kurzgespräche
    "Ein Anrufer fragt nur nach den Öffnungszeiten und verabschiedet sich dann.",
    "Ein Anrufer ruft an, merkt er hat die falsche Nummer und legt auf.",

    # Dialekt / Sprache
    "Ein Anrufer spricht bayrischen Dialekt (z.B. 'Verglasung', 'Hetz', 'ned', 'scho'). Bot versteht trotzdem.",
    "Ein Anrufer aus Österreich mit österreichischem Vokabular (z.B. 'schauen', 'Stiege', 'Erdgeschoß').",
    "Ein Anrufer mit ausländischem Akzent, aber gutem Deutsch. Gibt ausländisch klingenden Namen an.",
    "Ein Anrufer spricht zuerst Englisch — Bot antwortet auf Englisch, nimmt Anfrage trotzdem vollständig auf.",
]

# ---------------------------------------------------------------------------
# System-Prompt für den Bot (generisch)
# ---------------------------------------------------------------------------

def build_bot_system_prompt(company: dict) -> str:
    name = company["company_name"]
    owner = company["owner_name"]
    services_str = ", ".join(company["services"])
    opening = company["opening_hours"]
    callback = company["phone_callback"]
    emergency = company.get("emergency_number")
    since = company.get("company_since", "")
    address = company.get("company_address", "")
    employees = company.get("employee_count", "")

    prompt = f"""Du bist der KI-Telefonassistent von {name}.
Du nimmst Anrufe entgegen für {owner}.

BEGRÜSSUNG:
Wenn du "[GESPRÄCH BEGINNT]" erhältst, sage genau: "Guten Tag, Sie sind verbunden mit {name}. Ich bin die Telefon KI. Was kann ich für Sie tun?"

DU KANNST:
- Anfrage aufnehmen in dieser Reihenfolge: Name → Adresse mit PLZ bestätigen (z.B. "Musterstadt, PLZ 80000?") → Anliegen → Rückruf ankündigen: "Darf ich Sie später unter [Anrufernummer] zurückrufen um Termine zur Baubegehung abzuklären?" → Abschluss: "Ich gebe das weiter und wir melden uns."
- Informationen zu Betrieb, Leistungen und Öffnungszeiten geben.

DU KANNST NICHT — ESKALIERE:
- Preise nennen oder verhandeln
- Beschwerden entgegennehmen
- Rechtliche Fragen beantworten
→ Sage dann: "{owner} ruft Sie zurück."

ABSOLUT VERBOTEN:
- Wunschtermin erfragen — Termine werden beim Rückruf abgeklärt
- Konkrete Termine zusagen
- Erfundene oder unbestätigte Nummern nennen
- Markdown, Aufzählungen, Emojis

TELEFON-REGELN:
- Pro Antwort: GENAU 1 Satz, MAXIMAL 12 Wörter.
- Zahlen ausschreiben: "acht Uhr" nicht "8:00".
- Bei Verabschiedung: NUR "Auf Wiederhören!"

ÖFFNUNGSZEITEN: {opening}
DIENSTLEISTUNGEN: {services_str}
PHONE_CALLBACK_BETRIEB: {callback}"""

    if since:
        prompt += f"\nGEGRÜNDET: {since}"
    if address:
        prompt += f"\nANSCHRIFT BETRIEB: {address}"
    if employees:
        prompt += f"\nMITARBEITER: {employees}"
    if emergency:
        prompt += f"\nNOTFALL: {emergency}"

    return prompt


# ---------------------------------------------------------------------------
# Prompt: Gesprächs-Generator
# ---------------------------------------------------------------------------

def build_generator_prompt(company: dict, scenario: str) -> str:
    name = company["company_name"]
    owner = company["owner_name"]
    services_str = ", ".join(company["services"])

    return f"""Du generierst ein realistisches deutsches Telefongespräch zwischen einem Anrufer und einem KI-Telefonassistenten eines Handwerksbetriebs.

BETRIEB: {name}
INHABER: {owner}
LEISTUNGEN: {services_str}

SZENARIO: {scenario}

REGELN FÜR DEN ASSISTENTEN:
- Antwortet mit GENAU 1 Satz, maximal 12 Wörter
- Kein Markdown, keine Aufzählungen, keine Emojis
- Nimmt Anfragen in dieser Reihenfolge auf: Name → Adresse (PLZ bestätigen) → Anliegen → Rückruf bestätigen
- KEIN Wunschtermin erfragen — Termine werden beim Rückruf abgeklärt
- Kann keine Preise nennen, keine Beschwerden bearbeiten
- Bei Verabschiedung: nur "Auf Wiederhören!"
- Abschluss der Anfrage: "Ich gebe das weiter und wir melden uns."

REGELN FÜR DEN ANRUFER:
- Verhält sich gemäß Szenario (ungeduldig, freundlich, verwirrt, Dialekt etc.)
- Spricht natürlich und umgangssprachlich
- Macht realistische Korrekturen und Missverständnisse

FORMAT — gib NUR das Gespräch aus, absolut kein Kommentar davor oder danach:
Anrufer: [was der Anrufer sagt]
Assistent: [was der Assistent antwortet]
Anrufer: [...]
Assistent: [...]
...

Starte mit dem Assistent der "[GESPRÄCH BEGINNT]" empfängt und begrüßt.
Das Gespräch soll 6 bis 14 Turns haben und realistisch enden."""


# ---------------------------------------------------------------------------
# Ollama-Aufruf
# ---------------------------------------------------------------------------

def call_ollama(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.9,
            "top_p": 0.95,
            "num_predict": 1024,
        },
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Gespräch parsen → Turns
# ---------------------------------------------------------------------------

def parse_conversation(raw: str) -> list[dict]:
    """Parst "Anrufer: ...\nAssistent: ..." in eine Liste von Turns."""
    turns = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Anrufer:"):
            content = line[len("Anrufer:"):].strip()
            if content:
                turns.append({"role": "user", "content": content})
        elif line.startswith("Assistent:"):
            content = line[len("Assistent:"):].strip()
            if content:
                turns.append({"role": "assistant", "content": content})
    return turns


# ---------------------------------------------------------------------------
# Training-Beispiel bauen
# ---------------------------------------------------------------------------

def build_training_example(company: dict, turns: list[dict]) -> dict | None:
    """Baut ein QLoRA-Trainingsbeispiel aus einem Gespräch."""
    if len(turns) < 2:
        return None
    # Filtere Gespräche ohne Assistenten-Antwort
    if not any(t["role"] == "assistant" for t in turns):
        return None

    return {
        "messages": [
            {"role": "system", "content": build_bot_system_prompt(company)},
        ] + turns
    }


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Trainingsdaten-Generator für Anrufwerker QLoRA")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Anzahl Gespräche")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Ausgabedatei (.jsonl)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Ollama-Modell")
    parser.add_argument("--ollama-url", type=str, default=OLLAMA_URL, help="Ollama URL")
    args = parser.parse_args()

    output_path = Path(args.output)
    print(f"Generiere {args.count} Gespräche → {output_path}")
    print(f"Modell: {args.model}")
    print(f"Szenarien: {len(SCENARIOS)}, Firmen: {len(COMPANIES)}\n")

    success = 0
    errors = 0

    with output_path.open("w", encoding="utf-8") as f:
        for i in range(args.count):
            company = random.choice(COMPANIES)
            scenario = random.choice(SCENARIOS)

            try:
                prompt = build_generator_prompt(company, scenario)
                raw = call_ollama(prompt, args.model)
                turns = parse_conversation(raw)
                example = build_training_example(company, turns)

                if example and len(example["messages"]) >= 3:
                    f.write(json.dumps(example, ensure_ascii=False) + "\n")
                    f.flush()
                    success += 1
                    print(f"[{i+1}/{args.count}] ✓ {company['company_name'][:25]:<25} | {len(turns)} turns | {scenario[:50]}")
                else:
                    errors += 1
                    print(f"[{i+1}/{args.count}] ✗ Parse-Fehler: {company['company_name']}")

            except KeyboardInterrupt:
                print(f"\nAbgebrochen nach {success} Gesprächen.")
                break
            except Exception as exc:
                errors += 1
                print(f"[{i+1}/{args.count}] ✗ Fehler: {exc}")
                time.sleep(2)

    print(f"\nFertig: {success} OK, {errors} Fehler → {output_path} ({output_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
