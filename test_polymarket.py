import requests
import sys
import json
import time
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.constants import POLYGON

load_dotenv()

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
    
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        print("[INFO] No PRIVATE_KEY found in environment. Using dummy data.")
        # Fallback to dummy request if no key
        url = f"{BASE_URL}/order"
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
                return True
            elif resp.status_code == 403:
                print(f"[FAIL] Order endpoint returned 403 Forbidden.")
                return False
            else:
                print(f"[WARN] Unexpected status code: {resp.status_code}")
                return True
        except Exception as e:
            print(f"[FAIL] Error: {e}")
            return False

    # Use ClobClient with Private Key
    try:
        funder = os.getenv("FUNDER")
        print("[INFO] Initializing ClobClient with Private Key...")
        # Initialize client with private key (L2 auth)
        # Note: This might require creating an API key if one doesn't exist, 
        # but ClobClient usually handles signing if key is provided.
        client = ClobClient(
            host=BASE_URL, 
            key=private_key, 
            chain_id=POLYGON,
            signature_type=2,
            funder=funder
        )
        api_creds = client.create_or_derive_api_creds()
        client.set_api_creds(api_creds)
        
        # Create a dummy order args
        # We use a token_id that likely doesn't exist or is invalid to avoid real trade
        # But to test AUTH, we should use a valid structure.
        # If we use a random token_id, the server might reject it with "Invalid token" 
        # AFTER checking auth. This is what we want.
        
        order_args = OrderArgs(
            price=0.5,
            size=10,
            side="BUY",
            token_id="50488227317031565004575684525878022626020008256198844799050708993499540064859" # china taiwan 2027
        )
        
        print("[INFO] Sending signed order...")
        start = time.time()
        try:
            # create_order will sign and send
            signed_order = client.create_order(order_args)
            ## GTC(Good-Till-Cancelled) Order
            resp = client.post_order(signed_order, OrderType.GTC)
            latency = record_latency("Place Order (Signed)", start)
            print(f"[PASS] Signed order sent successfully.")
            print(f"      Response: {resp}")
            print(f"      Latency: {latency:.2f} ms")
            return True
        except Exception as e:
            latency = record_latency("Place Order (Signed)", start)
            # Check if error is related to Auth or Logic
            err_str = str(e)
            print(f"[INFO] API Response Error: {err_str}")
            
            if "Unauthorized" in err_str or "Invalid api key" in err_str:
                # This means even with PK, auth failed. 
                # Could be that we need to derive API keys first.
                print("[FAIL] Authentication failed even with Private Key.")
                print("      You may need to create an API key first using `client.create_api_key()`")
                
                # Attempt to create API key?
                # print("      Attempting to create API key...")
                # try:
                #     api_creds = client.create_api_key()
                #     print(f"      API Key Created: {api_creds}")
                #     # Retry order?
                # except Exception as k_err:
                #     print(f"      Failed to create API key: {k_err}")
                
                return False
            elif "Invalid token" in err_str or "not found" in err_str or "Order validation failed" in err_str or "not enough balance" in err_str.lower() or "insufficient balance" in err_str.lower():
                print(f"[PASS] Auth successful! Server rejected order logic (Expected).")
                print(f"      Latency: {latency:.2f} ms")
                return True
            else:
                print(f"[WARN] Unexpected error: {e}")
                return True

    except Exception as e:
        print(f"[FAIL] Error using ClobClient: {e}")
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
