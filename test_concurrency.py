"""
Automated Multi-Threaded Concurrency Test for Bank Fraud Portal
Spawns concurrent worker threads sending parallel fraud intake requests to verify multi-worker throughput.
"""

import concurrent.futures
import urllib.request
import json
import time

URL = "http://127.0.0.1:5050/api/fraud-tickets"
NUM_REQUESTS = 30
CONCURRENT_WORKERS = 10

def send_fraud_report(i):
    payload = {
        "full_name": f"Concurrent User {i}",
        "email": f"user_{i}_{int(time.time()*1000)%10000}@concurrent-test.in",
        "phone": f"+91 98000 {10000+i}",
        "account_number": f"ACT-CONCUR-{i:03d}",
        "account_type": "SAVINGS",
        "incident_type": "Automated Multi-Thread Intake",
        "amount_involved": 10000 + (i * 250),
        "severity": "MEDIUM",
        "suspect_entity": f"Test Merchant {i}",
        "description": f"Automated stress test incident #{i}"
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(URL, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            elapsed = time.time() - start
            body = json.loads(res.read().decode('utf-8'))
            return {"status": res.status, "ticket_id": body.get("ticket_id"), "ticket_number": body.get("ticket_number"), "time": elapsed, "success": True}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "success": False, "time": time.time() - start}

def run_stress_test():
    print(f"[*] Starting Multi-Worker Stress Test: {NUM_REQUESTS} requests across {CONCURRENT_WORKERS} concurrent threads...")
    start_total = time.time()
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = [executor.submit(send_fraud_report, i) for i in range(1, NUM_REQUESTS + 1)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            
    total_time = time.time() - start_total
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    avg_latency = sum(r["time"] for r in results) / len(results)
    
    print("\n" + "="*60)
    print("  MULTI-WORKER CONCURRENCY TEST RESULTS")
    print("="*60)
    print(f"  Total Requests Sent:    {NUM_REQUESTS}")
    print(f"  Concurrent Threads:     {CONCURRENT_WORKERS}")
    print(f"  Successful (201):       {len(successful)} ({len(successful)/NUM_REQUESTS*100:.1f}%)")
    print(f"  Failed:                 {len(failed)}")
    print(f"  Total Elapsed Time:     {total_time:.3f} seconds")
    print(f"  Average Request Latency:{avg_latency*1000:.1f} ms")
    print(f"  Throughput:             {NUM_REQUESTS/total_time:.1f} requests/second")
    print("="*60)
    
    assert len(successful) == NUM_REQUESTS, "Some requests failed during concurrency test!"

if __name__ == "__main__":
    run_stress_test()
