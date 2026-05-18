import os
import time
import json
from urllib.request import Request, urlopen
from urllib.parse import quote

# Paste your NewsAPI key here
NEWSAPI_KEY = "YOUR_API_KEY_HERE"
QUERY = "Bogotá seguridad"

def test_newsapi():
    if NEWSAPI_KEY == "YOUR_API_KEY_HERE":
        print("Please replace YOUR_API_KEY_HERE with your actual NewsAPI key.")
        return

    print(f"--- Testing NEWSAPI ---")
    start = time.time()
    
    # URL encode the query
    encoded_query = quote(QUERY)
    
    # We use the 'everything' endpoint to search all articles
    url = f"https://newsapi.org/v2/everything?q={encoded_query}&language=es&sortBy=relevancy&pageSize=3&apiKey={NEWSAPI_KEY}"
    
    req = Request(url, headers={"User-Agent": "NiddoAgent/1.0"})
    
    try:
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            end = time.time()
            print(f"Time: {end - start:.2f} seconds")
            
            articles = data.get("articles", [])
            if not articles:
                print("No articles found for this query.")
                return
                
            for i, res in enumerate(articles):
                source = res.get('source', {}).get('name', 'Unknown')
                print(f"{i+1}. [{source}] {res.get('title', 'No Title')}")
                content = res.get('content') or res.get('description') or ''
                print(f"   Snippet ({len(content)} chars): {content[:150]}...\n")
    except Exception as e:
        print(f"NewsAPI Error: {e}")

if __name__ == "__main__":
    print(f"Query: '{QUERY}'\n")
    test_newsapi()