\# API Concurrency and Cache Plan



Date: 2026-06-22  

Owner: 杨杰康  

Branch: dev/yangjiekang



\---



\## 1. Output Files



\- `docs/translation\_speed\_optimization\_plan.md`

\- `notes/2026-06-22\_api-concurrency-cache-plan.md`

\- `scripts/mt/translate\_concurrent\_poc.py`



\---



\## 2. POC Test Result



Local mock test completed.



First run:



```text

total\_samples: 10

completed\_samples: 10

failed\_samples: 0

cache\_hits: 0

cache\_misses: 10

workers: 3

mock: true

```



Second run:



```text

total\_samples: 10

completed\_samples: 10

failed\_samples: 0

cache\_hits: 10

cache\_misses: 0

workers: 3

mock: true

```



\---



\## 3. Concurrency Plan



Initial test groups:



| workers | Purpose |

|---:|---|

| 1 | baseline sequential speed |

| 3 | low-risk concurrent test |

| 5 | upper small-scale validation |



Recommended first test:



```bash

python scripts/mt/translate\_concurrent\_poc.py --workers 3 --limit 10 --mock

```



\---



\## 4. Cache Key



Cache key fields:



```text

model

prompt\_version

termbase\_version

source\_lang

target\_lang

source\_text\_hash

injected\_terms\_hash

```



Cache key algorithm:



```text

sha256(json.dumps(cache\_key\_payload, sort\_keys=True))

```



\---



\## 5. Cache Hit Rule



Cache hit requires exact match of:



```text

model

prompt\_version

termbase\_version

source\_lang

target\_lang

source\_text\_hash

injected\_terms\_hash

```



\---



\## 6. Cache Invalidation



Cache misses when any of these changes:



```text

model

prompt\_version

termbase\_version

source\_lang

target\_lang

source\_text

injected\_terms

```



\---



\## 7. Retry Rule



Retry transient errors only:



```text

timeout

connection\_error

rate\_limit

server\_error

empty\_response

invalid\_json

```



Default:



```text

max\_retries = 3

backoff = 2, 4, 8 seconds

```



\---



\## 8. Logs



Request log:



```text

outputs/translation\_concurrent\_poc\_request\_log.csv

```



Result log:



```text

outputs/translation\_concurrent\_poc\_results.csv

```



Cache file:



```text

outputs/translation\_concurrent\_poc\_cache.jsonl

```



Speed summary:



```text

outputs/translation\_concurrent\_poc\_summary.json

```



\---



\## 9. Server Test



Login:



```bash

ssh -p 3222 yinzs@220.154.1.75

```



Run:



```bash

cd /path/to/llm-translation-poc

git checkout dev/yangjiekang

git pull origin dev/yangjiekang

python scripts/mt/translate\_concurrent\_poc.py --workers 1 --limit 10 --mock

python scripts/mt/translate\_concurrent\_poc.py --workers 3 --limit 10 --mock

python scripts/mt/translate\_concurrent\_poc.py --workers 5 --limit 10 --mock

```



\---



\## 10. Completion Status



| Item | Status |

|---|---|

| Concurrent API flow | Done |

| Cache key | Done |

| Cache hit rule | Done |

| Cache invalidation rule | Done |

| Retry mechanism | Done |

| Request log | Done |

| Result log | Done |

| Small-scale POC script | Done |

| Local mock test | Passed |

| Cache hit validation | Passed |

| Server workflow | Documented |



