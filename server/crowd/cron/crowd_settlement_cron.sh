#!/bin/bash
# 众包结算：每周一 09:00 聚合上周 accepted 证据 → 结算行 → INFO 推送
cd /home/ubuntu/china-travel-food || exit 1
unset HTTPS_PROXY HTTP_PROXY ALL_PROXY
export FOOD_APP_DIR=/home/ubuntu/china-travel-food/app
export FOOD_DATA_DIR=/home/ubuntu/china-travel-food/.pm_dispatch_data
set -a; . /home/ubuntu/food-cloud/deploy.env; set +a
python3 cloud/crowd_settlement.py >> /home/ubuntu/china-travel-food/.pm_dispatch_data/crowd_settlement_cron.log 2>&1
