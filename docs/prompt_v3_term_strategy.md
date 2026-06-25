\# Prompt V3 Term Strategy



Date: 2026-06-22  

Owner: 杨杰康  

For: Prompt V3 implementation



\---



\## 1. Goal



Prompt V3 should avoid forcing all termbase entries into translation.



Terms should be routed into different usage modes:



\- lightweight mode

\- soft term mode

\- strict term mode

\- excluded mode



\---



\## 2. Term Injection Modes



| Prompt Mode | Term Selection | Usage Rule |

|---|---|---|

| Lightweight Mode | no terms or very few terms | Prioritize natural translation |

| Soft Term Mode | `active + high/medium` | Use terms as reference, no mechanical replacement |

| Strict Term Mode | `active + core high terms` | Force specified translation when source term clearly appears |

| Excluded Mode | `low`, `review`, `deprecated`, broad terms | Do not force inject |



\---



\## 3. Lightweight Mode



Use this mode when:



\- source text is short;

\- sentence structure is simple;

\- no core technical term appears;

\- injected terms would make the output rigid;

\- the segment is mostly structural text.



Rules:



```text

max\_terms\_per\_segment = 0 to 3

strict\_terms = 0

soft\_terms = 0 to 3

```



Priority strategy:



| priority | Usage |

|---|---|

| `high` | Use only if clearly relevant |

| `medium` | Usually skip |

| `low` | Skip |



Status strategy:



| status | Usage |

|---|---|

| `active` | Allowed |

| `review` | Skip |

| `deprecated` | Skip |



\---



\## 4. Soft Term Mode



Use this mode when:



\- terms are relevant but not acceptance-critical;

\- source segment contains medium-priority technical terms;

\- term injection may help consistency but should not harm fluency.



Rules:



```text

max\_terms\_per\_segment = 5

strict\_terms = 0

soft\_terms = up to 5

```



Allowed terms:



```text

status == active

priority in \["high", "medium"]

tcr\_scope != strict

```



Prompt instruction:



```text

Use the following terminology as reference. Apply it when natural and contextually appropriate. Do not force mechanical replacement if it makes the translation unnatural.

```



\---



\## 5. Strict Term Mode



Use this mode when:



\- source segment contains core high terms;

\- term belongs to external acceptance scope;

\- source term clearly appears in the original text;

\- the term is regulatory, technical, safety-related, EV-related, REESS-related, testing-related, approval-related, or certification-related.



Rules:



```text

max\_terms\_per\_segment = 8

strict\_terms = up to 5

soft\_terms = up to 3

```



Allowed strict terms:



```text

status == active

priority == high

tcr\_scope == strict

acceptance\_scope == external\_acceptance

```



Prompt instruction:



```text

The following core terminology must be used when the corresponding source term clearly appears in the text. Do not invent alternative translations for these core terms.

```



\---



\## 6. Excluded Terms



Do not force inject terms when:



```text

priority == low

status == review

status == deprecated

problem\_type == broad term

acceptance\_scope == internal\_diagnosis only

```



Broad or structural terms should be excluded from strict injection, including:



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



\---



\## 7. Priority Strategy



| priority | Prompt V3 Usage |

|---|---|

| `high` | Eligible for strict or soft use |

| `medium` | Soft reference only |

| `low` | Excluded from injection |



Detailed rules:



```text

high + active + strict core term -> strict injection

high + active + non-core term -> soft reference

medium + active -> soft reference

low -> no injection

```



\---



\## 8. Status Strategy



| status | Prompt V3 Usage |

|---|---|

| `active` | Allowed |

| `review` | Not used for strict injection |

| `deprecated` | Excluded |



Detailed rules:



```text

active -> can be used according to priority and scope

review -> diagnosis only; do not force inject

deprecated -> never inject

```



\---



\## 9. Term Count Control



Prompt V3 should control terminology volume per segment.



Recommended limits:



| Mode | Max Terms | Strict Terms | Soft Terms |

|---|---:|---:|---:|

| Lightweight | 0-3 | 0 | 0-3 |

| Soft Term | 5 | 0 | 5 |

| Strict Term | 8 | 5 | 3 |



If more terms are matched:



1\. keep `strict` terms first;

2\. keep longer technical terms before shorter broad terms;

3\. keep domain-critical terms before general terms;

4\. drop low-priority and broad terms;

5\. drop review/deprecated terms.



\---



\## 10. Recommended Term Selection Logic



```python

def select\_prompt\_v3\_terms(matched\_terms, mode):

&#x20;   active\_terms = \[

&#x20;       t for t in matched\_terms

&#x20;       if t\["status"] == "active"

&#x20;   ]



&#x20;   strict\_terms = \[

&#x20;       t for t in active\_terms

&#x20;       if t.get("priority") == "high"

&#x20;       and t.get("tcr\_scope") == "strict"

&#x20;       and t.get("acceptance\_scope") == "external\_acceptance"

&#x20;   ]



&#x20;   soft\_terms = \[

&#x20;       t for t in active\_terms

&#x20;       if t.get("priority") in \["high", "medium"]

&#x20;       and t not in strict\_terms

&#x20;   ]



&#x20;   excluded\_terms = \[

&#x20;       t for t in matched\_terms

&#x20;       if t.get("priority") == "low"

&#x20;       or t.get("status") in \["review", "deprecated"]

&#x20;       or t.get("problem\_type") == "broad term"

&#x20;   ]



&#x20;   if mode == "lightweight":

&#x20;       return {

&#x20;           "strict\_terms": \[],

&#x20;           "soft\_terms": soft\_terms\[:3],

&#x20;           "excluded\_terms": excluded\_terms,

&#x20;       }



&#x20;   if mode == "soft":

&#x20;       return {

&#x20;           "strict\_terms": \[],

&#x20;           "soft\_terms": soft\_terms\[:5],

&#x20;           "excluded\_terms": excluded\_terms,

&#x20;       }



&#x20;   if mode == "strict":

&#x20;       return {

&#x20;           "strict\_terms": strict\_terms\[:5],

&#x20;           "soft\_terms": soft\_terms\[:3],

&#x20;           "excluded\_terms": excluded\_terms,

&#x20;       }



&#x20;   return {

&#x20;       "strict\_terms": \[],

&#x20;       "soft\_terms": \[],

&#x20;       "excluded\_terms": matched\_terms,

&#x20;   }

```



\---



\## 11. Prompt Text Templates



\### 11.1 Lightweight Mode



```text

Translate the text naturally and accurately. Do not force terminology replacement unless a core technical term clearly appears.

```



\### 11.2 Soft Term Mode



```text

Use the following terminology as reference. Apply it when natural and contextually appropriate. Do not force mechanical replacement if it makes the translation unnatural.

```



\### 11.3 Strict Term Mode



```text

The following core terminology must be used when the corresponding source term clearly appears in the text. Do not invent alternative translations for these core terms.

```



\---



\## 12. Coordination with Prompt V3 Implementation



Need to align with 李宛真 on:



\- Prompt V3 mode names;

\- max term count per segment;

\- whether strict terms and soft terms are passed separately;

\- how to display excluded terms in debug logs;

\- how to handle review terms during testing;

\- how low-score samples are mapped back to termbase candidates.



\---



\## 13. Recommended Input Fields



Prompt V3 term selector should read:



```text

term\_id

source\_lang

target\_lang

source\_term

target\_term

alias

domain

priority

status

tcr\_scope

acceptance\_scope

```



Optional fields:



```text

problem\_type

suggested\_action

decision\_status

```



\---



\## 14. Completion Criteria



| Check Item | Status |

|---|---|

| Lightweight term rule defined | Done |

| Soft term rule defined | Done |

| Strict term rule defined | Done |

| Priority strategy defined | Done |

| Status strategy defined | Done |

| Broad term exclusion defined | Done |

| Term count control defined | Done |

| Prompt V3 alignment points listed | Done |



