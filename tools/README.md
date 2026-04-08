# Training Data Generator

Generates synthetic phone conversations for QLoRA fine-tuning.
8 trade businesses × 31 scenarios, combined at random.

## Run

```bash

python3 tools/generate_training_data.py --count 1000 --output tools/training_data.jsonl
```

Press `Ctrl+C` to stop gracefully. Already generated data is kept.

## Cleanup (after 2-3 days)

```bash
rm tools/generate_training_data.py tools/training_data.jsonl tools/README.md
```

## Output-Format

JSONL, one conversation per line, ready for QLoRA:
```json
{"messages": [{"role": "system", ...}, {"role": "assistant", ...}, {"role": "user", ...}, ...]}
```
