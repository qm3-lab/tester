import requests
import sys
import json
import time

BASE_URL = "https://clob.polymarket.com"
LATENCIES = {}

def record_latency(name, start_time):
    latency_ms = (time.time() - start_time) * 1000
    LATENCIES[name] = latency_ms
    return latency_ms

def test_connectivity():
    print("Testing connectivity to Polymarket CLOB API...")
    try:
        start = time.time()
        resp = requests.get(f"{BASE_URL}/time", timeout=10)
        latency = record_latency("Connectivity (GET /time)", start)
        
        if resp.status_code == 200:
            print(f"[PASS] Connected to {BASE_URL}/time. Server time: {resp.json()}")
            print(f"      Latency: {latency:.2f} ms")
            return True
        else:
            print(f"[FAIL] Connected but received status code: {resp.status_code}")
            print(f"Response: {resp.text}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not connect to {BASE_URL}/time")
        print(f"Error: {e}")
        return False

def test_read_order_book():
    print("\nTesting Read Order Book (Public API)...")
    try:
        # Strategy: Use Gamma API to find an active market, then check CLOB for the book.
        # Gamma API is better for filtering.
        gamma_url = "https://gamma-api.polymarket.com/markets"
        params = {
            "closed": "false",
            "active": "true",
            "limit": 10,
            "order": "volume24hr" # Try to get high volume markets
        }
        
        print(f"[INFO] Fetching active markets from Gamma API ({gamma_url})...")
        resp = requests.get(gamma_url, params=params, timeout=10)
        
        markets = []
        if resp.status_code == 200:
            markets = resp.json()
            # Gamma returns a list directly usually, or paginated
            if isinstance(markets, dict) and 'data' in markets: # Handle potential pagination wrapper
                markets = markets['data']
        else:
            print(f"[WARN] Gamma API failed ({resp.status_code}). Falling back to CLOB markets...")
            # Fallback to original method if Gamma fails
            resp = requests.get(f"{BASE_URL}/markets", params={"limit": 50}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                markets = data.get('data', []) if isinstance(data, dict) else data

        if not markets:
            print("[FAIL] No markets found to test.")
            return False

        print(f"[INFO] Found {len(markets)} markets. Checking for order books...")
        
        for market in markets:
            # Extract token_id
            token_id = None
            
            # Gamma structure
            if 'clobTokenIds' in market and market['clobTokenIds']:
                token_ids = market['clobTokenIds']
                if isinstance(token_ids, str):
                    try:
                        token_ids = json.loads(token_ids)
                    except:
                        pass # Keep as string if parsing fails
                
                if isinstance(token_ids, list) and len(token_ids) > 0:
                    token_id = token_ids[0]
                else:
                    token_id = None
            # CLOB structure
            elif 'tokens' in market and market['tokens']:
                token_id = market['tokens'][0].get('token_id')
            
            if not token_id:
                continue
                
            # Fetch book from CLOB
            book_url = f"{BASE_URL}/book"
            start = time.time()
            book_resp = requests.get(book_url, params={"token_id": token_id}, timeout=5)
            latency = record_latency("Read Order Book (GET /book)", start)
            
            if book_resp.status_code == 200:
                print(f"[PASS] Successfully read order book for token {token_id}")
                print(f"      Market: {market.get('question', market.get('slug', 'Unknown'))}")
                print(f"      Latency: {latency:.2f} ms")
                book_data = book_resp.json()
                bids = book_data.get('bids', [])
                asks = book_data.get('asks', [])
                print(f"      Top Bid: {bids[0] if bids else 'None'}")
                print(f"      Top Ask: {asks[0] if asks else 'None'}")
                return True
            elif book_resp.status_code == 404:
                continue # Empty book or not found
            else:
                print(f"[WARN] Failed to read book for {token_id}. Status: {book_resp.status_code}")

        print("[FAIL] Could not find any accessible order book in the fetched markets.")
        return False

    except Exception as e:
        print(f"[FAIL] Error reading order book: {e}")
        return False

def test_place_order_latency():
    print("\nTesting Place Order Latency (POST /order)...")
    # Endpoint: POST /order
    # We expect 401 (Unauthorized) or 400 (Bad Request) if reachable.
    # We expect 403 (Forbidden) if Geo-blocked.
    url = f"{BASE_URL}/order"
    
    # Dummy payload to simulate a real order structure
    payload = {
        "token_id": "0",
        "price": "0.5",
        "size": "10",
        "side": "BUY",
        "expiration": 0,
        "nonce": 0,
        "signature": "0x0"
    }
    
    try:
        start = time.time()
        resp = requests.post(url, json=payload, timeout=10)
        latency = record_latency("Place Order (POST /order)", start)
        
        if resp.status_code in [400, 401, 422]:
            print(f"[PASS] Order endpoint is reachable (Status: {resp.status_code}).")
            print(f"      Latency: {latency:.2f} ms")
            print("      (Auth error expected as we are testing reachability/latency only)")
            return True
        elif resp.status_code == 403:
            print(f"[FAIL] Order endpoint returned 403 Forbidden.")
            print("      This likely indicates the VPS IP is GEO-BLOCKED by Polymarket.")
            return False
        else:
            print(f"[WARN] Unexpected status code from order endpoint: {resp.status_code}")
            print(f"      Latency: {latency:.2f} ms")
            return True 
            
    except Exception as e:
        print(f"[FAIL] Error connecting to order endpoint: {e}")
        return False

if __name__ == "__main__":
    print("--- Polymarket VPS Usability Test ---\n")
    
    c = test_connectivity()
    if c:
        r = test_read_order_book()
        t = test_place_order_latency()
        
        print("\n" + "="*30)
        if c and r and t:
            print("RESULT: SUCCESS")
            print("This VPS appears FULLY COMPATIBLE with Polymarket API.")
            print("\n--- Latency Summary ---")
            for name, ms in LATENCIES.items():
                print(f"{name:<30}: {ms:.2f} ms")
        else:
            print("RESULT: ISSUES DETECTED")
            print("This VPS may have issues connecting to Polymarket.")
        print("="*30)
    else:
        print("\n[SUMMARY] Basic connectivity failed.")
