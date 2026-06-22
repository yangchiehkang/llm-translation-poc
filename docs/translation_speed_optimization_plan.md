\# Translation Speed Optimization Plan



Date: 2026-06-22  

Owner: 杨杰康  

Task: API concurrency and cache design



\---



\## 1. Goal



Improve translation experiment speed by adding:



\- concurrent API calls;

\- deterministic cache keys;

\- retry mechanism;

\- request and result logs;

\- small-scale speed test workflow.



\---



\## 2. Current Flow



Current translation flow is mainly sequential:



```text

load samples

load prompt

load termbase

build injected terms

build request

call translation API one by one

save translation result

run evaluation / TCR

```



Main bottleneck:



```text

one API call per sample, executed sequentially

```



\---



\## 3. Target Flow



Proposed optimized flow:



```text

load samples

load prompt config

load termbase config

build injected terms

generate cache key

check cache

if cache hit:

&#x20;   return cached translation

else:

&#x20;   submit request to concurrent executor

&#x20;   call API

&#x20;   retry on failure

&#x20;   save result to cache

write request log

write result log

write speed summary

```



\---



\## 4. Concurrency Strategy



Use thread-based concurrency for API calls.



Recommended initial settings:



| Setting | Value |

|---|---:|

| small test samples | 20-50 |

| initial concurrency | 3 |

| upper test concurrency | 5 |

| timeout seconds | 60 |

| max retries | 3 |

| retry backoff | 2s, 4s, 8s |



Concurrency test groups:



```text

workers = 1

workers = 3

workers = 5

```



Do not start with high concurrency.



\---



\## 5. Retry Strategy



Retry when:



```text

timeout

connection error

rate limit

temporary server error

empty response

invalid JSON response

```



Do not retry when:



```text

invalid request format

missing API key

unsupported model

prompt construction error

source data error

```



Retry backoff:



```text

attempt 1: wait 2 seconds

attempt 2: wait 4 seconds

attempt 3: wait 8 seconds

```



\---



\## 6. Cache Key Design



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



Recommended cache key format:



```text

sha256(

&#x20;   model

&#x20;   + prompt\_version

&#x20;   + termbase\_version

&#x20;   + source\_lang

&#x20;   + target\_lang

&#x20;   + source\_text\_hash

&#x20;   + injected\_terms\_hash

)

```



\---



\## 7. Cache Hit Rule



Cache hit only when all fields match:



```text

same model

same prompt\_version

same termbase\_version

same source\_lang

same target\_lang

same source\_text\_hash

same injected\_terms\_hash

```



If any field changes, cache should miss.



\---



\## 8. Cache Invalidation Rule



Cache should be invalidated when:



```text

model changes

prompt\_version changes

termbase\_version changes

source text changes

injected terms change

source\_lang changes

target\_lang changes

translation API parameters change materially

```



Recommended extra fields for traceability:



```text

temperature

top\_p

max\_tokens

api\_provider

created\_at

```



\---



\## 9. Request Log Fields



Request log should include:



```text

request\_id

sample\_id

cache\_key

cache\_hit

model

prompt\_version

termbase\_version

source\_lang

target\_lang

source\_text\_hash

injected\_terms\_hash

worker\_id

attempt

request\_start\_time

request\_end\_time

latency\_ms

status

error\_type

error\_message

```



\---



\## 10. Result Log Fields



Result log should include:



```text

request\_id

sample\_id

cache\_key

model

prompt\_version

termbase\_version

source\_lang

target\_lang

source\_text

translation

injected\_terms

cache\_hit

latency\_ms

attempt\_count

status

created\_at

```



\---



\## 11. Small-Scale Speed Test



Recommended test command:



```bash

python scripts/mt/translate\_concurrent\_poc.py --input data/sample\_translation\_inputs.csv --output outputs/translation\_concurrent\_poc\_results.csv --workers 3 --limit 30 --mock

```



For server test:



```bash

python scripts/mt/translate\_concurrent\_poc.py --input data/sample\_translation\_inputs.csv --output outputs/translation\_concurrent\_poc\_results.csv --workers 3 --limit 30

```



\---



\## 12. Server Execution Environment



Server account:



```text

user: yinzs

host: 220.154.1.75

port: 3222

```



Login command:



```bash

ssh -p 3222 yinzs@220.154.1.75

```



Recommended server-side workflow:



```bash

cd /path/to/llm-translation-poc

git checkout dev/yangjiekang

git pull origin dev/yangjiekang

python scripts/mt/translate\_concurrent\_poc.py --workers 3 --limit 30 --mock

```



\---



\## 13. Speed Evaluation Metrics



Report the following metrics:



```text

total\_samples

completed\_samples

failed\_samples

cache\_hits

cache\_misses

total\_time\_sec

avg\_latency\_ms

throughput\_samples\_per\_min

workers

retry\_count

```



\---



\## 14. Risk Control



Rules:



```text

start from workers=1

then test workers=3

then test workers=5

compare failure rate and latency

do not use high concurrency for formal experiments before validation

keep logs for traceability

never overwrite main experiment outputs

```



\---



\## 15. Completion Criteria



| Check Item | Status |

|---|---|

| Concurrent flow defined | Done |

| Cache key defined | Done |

| Cache hit rule defined | Done |

| Cache invalidation rule defined | Done |

| Retry strategy defined | Done |

| Request log fields defined | Done |

| Result log fields defined | Done |

| Small-scale POC script prepared | Done |

| Server execution workflow documented | Done |



