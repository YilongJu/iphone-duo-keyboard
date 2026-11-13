#!/usr/bin/env bash
# Job: the attribution table of the domain training text (WSL). It reads the Stack Exchange dumps again.
set -euo pipefail
nice -n 10 python3 scripts/lm-domain/attribute_training.py --cases build/lm-domain/data/domain \
  --licences build/lm-domain/corpus/licences.json --work build/lm-domain/attribution
