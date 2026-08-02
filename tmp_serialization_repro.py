import json
import traceback
from datetime import datetime, timedelta, timezone


def main():
    data = {
        'subscription': {
            'active': True,
            'expires_at': datetime.now(timezone.utc) + timedelta(days=7),
            'plan': 'premium'
        }
    }
    print(type(data['subscription']['expires_at']).__name__)
    try:
        json.dumps(data)
        print('json ok')
    except Exception:
        traceback.print_exc()

main()
