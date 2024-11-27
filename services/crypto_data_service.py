import requests
from typing import List, Dict

class CryptoDataService:
    @staticmethod
    def get_crypto_data() -> List[Dict]:
        url = "https://cryptobubbles.net/backend/data/bubbles1000.usd.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            return []