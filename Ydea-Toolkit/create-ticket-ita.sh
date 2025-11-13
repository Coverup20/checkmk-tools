#!/bin/bash
source .env

TITLE="$1"
DESCRIPTION="$2"
PRIORITY_ITA="$3"

# Converti priorità italiana in inglese
case "${PRIORITY_ITA,,}" in
  bassa)    PRIORITY="low" ;;
  media)    PRIORITY="normal" ;;
  alta)     PRIORITY="high" ;;
  critica)  PRIORITY="critical" ;;
  *)        PRIORITY="normal" ;;
esac

echo "🎫 Creazione ticket con priorità: $PRIORITY_ITA → $PRIORITY"
echo ""

./ydea-toolkit.sh create "$TITLE" "$DESCRIPTION" "$PRIORITY"
