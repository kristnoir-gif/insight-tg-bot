#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/bot_tg')
from db import get_stats

stats = get_stats()
print('Total requests:', stats['total_requests'])
print('Type:', type(stats['total_requests']))
print('Full stats:', stats)
