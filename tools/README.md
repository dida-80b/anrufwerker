# Training Data Generator

Generiert synthetische Telefongespräche für QLoRA Fine-Tuning.
8 Handwerksbetriebe × 31 Szenarien, zufällig kombiniert.

## Starten

```bash

python3 tools/generate_training_data.py --count 1000 --output tools/training_data.jsonl
```

Strg+C bricht sauber ab — bereits generierte Daten bleiben erhalten.

## Aufräumen (nach 2-3 Tagen)

```bash
rm tools/generate_training_data.py tools/training_data.jsonl tools/README.md
```

## Output-Format

JSONL, ein Gespräch pro Zeile, direkt für QLoRA nutzbar:
```json
{"messages": [{"role": "system", ...}, {"role": "assistant", ...}, {"role": "user", ...}, ...]}
```
