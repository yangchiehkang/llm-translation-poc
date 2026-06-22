\# Core Term Acceptance Scope for TCR V0.3



Date: 2026-06-22  

Owner: 杨杰康  

Branch: dev/yangjiekang



\---



\## 1. Output Files



\- `termbase/core\_high\_terms\_v0.3\_candidate.csv`

\- `scripts/termbase/build\_core\_high\_terms\_v0.3.py`

\- `notes/2026-06-22\_core-term-acceptance-scope.md`



\---



\## 2. Source Termbase



Core term candidates are selected from:



```text

termbase/auto\_regulation\_terms\_v0.2.csv

```



Base filters:



```text

priority == high

status == active

target\_lang == zh

```



Current source statistics:



```text

V0.2 total rows: 4489

High + active + zh rows: 3175

Core candidate rows: 1888

```



\---



\## 3. Candidate Term Statistics



The generated candidate file contains:



```text

1888 rows

12 columns

```



Fields:



```text

term\_id

source\_lang

target\_lang

source\_term

target\_term

domain

priority

alias

note

status

tcr\_scope

acceptance\_scope

```



Count by `tcr\_scope`:



| tcr\_scope | Count |

|---|---:|

| `strict` | 1647 |

| `relaxed` | 241 |



Count by `acceptance\_scope`:



| acceptance\_scope | Count |

|---|---:|

| `external\_acceptance` | 1647 |

| `internal\_diagnosis` | 241 |



\---



\## 4. Count by Source Language



| source\_lang | Count |

|---|---:|

| `ms` | 252 |

| `pt` | 236 |

| `ar` | 231 |

| `th` | 166 |

| `de` | 153 |

| `vi` | 147 |

| `en` | 143 |

| `id` | 131 |

| `es` | 115 |

| `it` | 79 |

| `fr` | 71 |

| `no` | 62 |

| `nl` | 49 |

| `ru` | 37 |

| `sv` | 16 |



\---



\## 5. RFP Key Language Coverage



RFP key languages:



```text

en, ru, es, de, fr, th, ar

```



Coverage by `source\_lang` and `tcr\_scope`:



| source\_lang | relaxed | strict |

|---|---:|---:|

| `ar` | 27 | 204 |

| `de` | 29 | 124 |

| `en` | 5 | 138 |

| `es` | 14 | 101 |

| `fr` | 18 | 53 |

| `ru` | 14 | 23 |

| `th` | 13 | 153 |



These languages can be separately reported in TCR V0.3.



\---



\## 6. Strict TCR Scope



`strict` terms are used for external acceptance.



A term enters `strict` TCR if it meets one of the following conditions:



\- belongs to core automotive regulation or technical domains;

\- is related to type approval, homologation, conformity assessment, certification, testing, vehicle safety, EV, battery safety, REESS, charging interface, ADAS, emissions, noise, or VIN;

\- contains core technical keywords such as approval, conformity, regulation, test procedure, braking, steering, battery, REESS, charging, high voltage, insulation resistance, AEBS, LDWS, ESC, VIN.



Strict TCR is recommended as the main external acceptance metric.



Recommended filter:



```python

df = df\[

&#x20;   (df\["status"] == "active")

&#x20;   \& (df\["priority"] == "high")

&#x20;   \& (df\["tcr\_scope"] == "strict")

]

```



\---



\## 7. Relaxed TCR Scope



`relaxed` terms are used for internal diagnosis.



A term enters `relaxed` TCR if it is high-priority and active but is broader or more context-dependent than strict terms.



Relaxed TCR should be used to identify potential terminology consistency problems, but should not be the only external acceptance indicator.



Recommended filter:



```python

df = df\[

&#x20;   (df\["status"] == "active")

&#x20;   \& (df\["priority"] == "high")

&#x20;   \& (df\["tcr\_scope"].isin(\["strict", "relaxed"]))

]

```



\---



\## 8. Acceptance vs Diagnosis



| Scope | acceptance\_scope | Purpose | Recommended Usage |

|---|---|---|---|

| `strict` | `external\_acceptance` | External acceptance | Main TCR V0.3 acceptance metric |

| `relaxed` | `internal\_diagnosis` | Internal diagnosis | Supplementary analysis only |



\---



\## 9. Excluded Terms



The following broad or structural terms are excluded from core high term acceptance:



```text

shall

must

may

should

vehicle

vehicles

motor vehicle

system

systems

part

parts

device

devices

component

components

test

tests

standard

standards

requirement

requirements

annex

appendix

paragraph

section

article

chapter

table

figure

scope

general

other

others

```



Chinese-only broad targets are also excluded when they appear as standalone target terms:



```text

应

必须

可

可以

宜

车辆

机动车

系统

部件

零件

装置

组件

试验

测试

标准

要求

附件

附录

段落

条

章节

表

图

范围

其他

```



Validation result for common broad English terms:



```text

Empty DataFrame

Columns: \[term\_id, source\_lang, source\_term, target\_term, domain, tcr\_scope]

Index: \[]

```



This means the following terms were not included as standalone core acceptance terms:



```text

shall

must

may

should

vehicle

vehicles

system

systems

part

parts

device

devices

annex

appendix

paragraph

standard

requirement

```



\---



\## 10. TCR V0.3 Recommended Fields



The candidate file keeps the original V0.2 fields and adds two fields:



```text

tcr\_scope

acceptance\_scope

```



Recommended fields for TCR V0.3:



```text

term\_id

source\_lang

target\_lang

source\_term

target\_term

domain

priority

status

tcr\_scope

acceptance\_scope

```



\---



\## 11. Suggested TCR Filtering Logic



For external acceptance:



```python

strict\_df = df\[

&#x20;   (df\["status"] == "active")

&#x20;   \& (df\["priority"] == "high")

&#x20;   \& (df\["tcr\_scope"] == "strict")

]

```



For internal diagnosis:



```python

diagnosis\_df = df\[

&#x20;   (df\["status"] == "active")

&#x20;   \& (df\["priority"] == "high")

&#x20;   \& (df\["tcr\_scope"].isin(\["strict", "relaxed"]))

]

```



For RFP key language reporting:



```python

rfp\_langs = \["en", "ru", "es", "de", "fr", "th", "ar"]



rfp\_df = df\[df\["source\_lang"].isin(rfp\_langs)]

```



For RFP strict TCR reporting:



```python

rfp\_strict\_df = df\[

&#x20;   (df\["source\_lang"].isin(rfp\_langs))

&#x20;   \& (df\["tcr\_scope"] == "strict")

]

```



\---



\## 12. Coordination Points with TCR V0.3



Need to align with 姚皓天 on:



\- whether TCR V0.3 reads `core\_high\_terms\_v0.3\_candidate.csv` directly;

\- whether `tcr\_scope == strict` is the default external acceptance metric;

\- whether `strict + relaxed` is used for internal diagnosis;

\- whether RFP key languages are reported separately;

\- whether output should include grouped statistics by `source\_lang`, `tcr\_scope`, and `acceptance\_scope`;

\- whether full V0.2 TCR remains as a diagnostic-only metric.



\---



\## 13. Current Completion Status



| Check Item | Result |

|---|---|

| Core high term candidate file generated | Done |

| Candidate file can be read by pandas | Done |

| `tcr\_scope` field added | Done |

| `acceptance\_scope` field added | Done |

| Strict / relaxed distinction completed | Done |

| RFP key language coverage checked | Done |

| Broad standalone terms excluded | Done |

| Documentation drafted | Done |



\---



\## 14. Summary



The core high term acceptance scope for TCR V0.3 has been established.



Generated file:



```text

termbase/core\_high\_terms\_v0.3\_candidate.csv

```



Current statistics:



```text

Core candidate rows: 1888

Strict terms: 1647

Relaxed terms: 241

External acceptance terms: 1647

Internal diagnosis terms: 241

```



Recommended TCR V0.3 usage:



\- use `tcr\_scope == strict` for external acceptance;

\- use `tcr\_scope in \["strict", "relaxed"]` for internal diagnosis;

\- report RFP key languages separately;

\- keep full V0.2 TCR as diagnostic reference only.



