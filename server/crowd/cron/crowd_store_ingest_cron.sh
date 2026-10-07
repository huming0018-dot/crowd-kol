#!/bin/bash
# 众包证据入库：每日 06:30 聚合 accepted 证据 → 证据表 + 主库 score_diner + 候选
cd /home/ubuntu/china-travel-food || exit 1
unset HTTPS_PROXY HTTP_PROXY ALL_PROXY
export FOOD_APP_DIR=/home/ubuntu/china-travel-food/app
export FOOD_DATA_DIR=/home/ubuntu/china-travel-food/.pm_dispatch_data
set -a; . /home/ubuntu/food-cloud/deploy.env; set +a
python3 cloud/crowd_store_ingest.py >> /home/ubuntu/china-travel-food/.pm_dispatch_data/crowd_store_ingest_cron.log 2>&1
