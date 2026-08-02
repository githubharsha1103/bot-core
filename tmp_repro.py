import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from utils import storage

async def main():
    payload = {
        'subscription': {
            'active': True,
            'expires_at': datetime.now(timezone.utc) + timedelta(days=7),
            'plan': 'premium'
        }
    }
    try:
        await storage.set_user(12345, payload)
    except Exception:
        traceback.print_exc()

asyncio.run(main())
