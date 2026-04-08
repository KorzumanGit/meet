#!/usr/bin/env bash
# meet.humbull.co の DNS が 34.84.113.149 を返した後に実行する。
# 事前: gcloud auth login（トークン有効）
set -euo pipefail
gcloud compute ssh meet-vm --zone=asia-northeast1-a --project=secretary-492601 --command='
sudo certbot --nginx -d meet.humbull.co --non-interactive --agree-tos -m daisuke.k@humbull.co --redirect
sudo nginx -t && sudo systemctl reload nginx
curl -sS -o /dev/null -w "https /health -> %{http_code}\n" https://meet.humbull.co/health
'
