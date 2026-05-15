import asyncio
import logging
import sys
import os

# Configure logging to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Add project root to path
sys.path.insert(0, os.getcwd())

from gateway import seeder

async def main():
    print("Starting debug sync for Artist ID 66 (ABBA)...")
    try:
        result = await seeder.sync_artist(66)
        print("\nResult:")
        print(result)
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    asyncio.run(main())
