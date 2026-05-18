import os
import time
import json
from urllib.request import Request, urlopen
from duckduckgo_search import DDGS
from dotenv import load_dotenv

load_dotenv()

QUERY = "Bogota Teusaquillo seguridad"
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

def test_tavily():
    print(f"--- Testing TAVILY API ---")
    start = time.time()
    payload = {
        "api_key": TAVILY_KEY,
        "query": QUERY,
        "topic": "news",
        "search_depth": "basic",
        "time_range": "month",
        "max_results": 3,
        "include_answer": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request("https://api.tavily.com/search", data=body, headers={"Content-Type": "application/json"}, method="POST")
    
    try:
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            end = time.time()
            print(f"Time: {end - start:.2f} seconds")
            for i, res in enumerate(data.get("results", [])):
                source = res.get('url', '').split('/')[2] if 'url' in res else 'Tavily'
                print(f"{i+1}. [{source}] {res.get('title', '')}")
                content = res.get('content', '')
                print(f"   Snippet ({len(content)} chars): {content[:150]}...\n")
    except Exception as e:
        print(f"Tavily Error: {e}")

def test_ddg():
    print(f"--- Testing DUCKDUCKGO NEWS ---")
    start = time.time()
    try:
        ddgs = DDGS()
        # Fallback to text search if news is empty
        results = list(ddgs.news(QUERY, max_results=3))
        if not results:
            print("DDG News was empty, trying DDG Text search...")
            results = list(ddgs.text(QUERY, max_results=3))
            
        end = time.time()
        print(f"Time: {end - start:.2f} seconds")
        for i, res in enumerate(results):
            source = res.get('source', res.get('href', '').split('/')[2] if 'href' in res else 'Unknown')
            print(f"{i+1}. [{source}] {res.get('title', 'No Title')}")
            snippet = res.get('body', '')
            print(f"   Snippet ({len(snippet)} chars): {snippet[:150]}...\n")
    except Exception as e:
        print(f"DDG Error: {e}")

if __name__ == "__main__":
    print(f"Query: '{QUERY}'\n")
    test_tavily()
    test_ddg()