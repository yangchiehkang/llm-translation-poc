\# Prompt V3 Term Rules



Date: 2026-06-22  

Owner: 杨杰康  

Branch: dev/yangjiekang



\---



\## 1. Output Files



\- `docs/prompt\_v3\_term\_strategy.md`

\- `notes/2026-06-22\_prompt-v3-term-rules.md`



\---



\## 2. Prompt V3 Term Usage Principle



Prompt V3 should not force all termbase entries into translation.



Terms should be divided into:



```text

strict terms

soft terms

excluded terms

```



\---



\## 3. Mode Summary



| Mode | Term Usage |

|---|---|

| Lightweight Mode | no terms or very few reference terms |

| Soft Term Mode | active high/medium terms as reference |

| Strict Term Mode | active core high terms as mandatory terms |



\---



\## 4. Priority Rules



| priority | Rule |

|---|---|

| `high` | strict if core term, otherwise soft |

| `medium` | soft only |

| `low` | excluded |



\---



\## 5. Status Rules



| status | Rule |

|---|---|

| `active` | allowed |

| `review` | not used for strict injection |

| `deprecated` | excluded |



\---



\## 6. Strict Term Rule



A term can enter strict injection only if:



```text

status == active

priority == high

tcr\_scope == strict

acceptance\_scope == external\_acceptance

```



Strict terms are used only when the source term clearly appears in the input text.



\---



\## 7. Soft Term Rule



A term can enter soft reference if:



```text

status == active

priority in \["high", "medium"]

```



Soft terms are reference terms only.



They should not be mechanically forced into the translation.



\---



\## 8. Exclusion Rule



Terms should be excluded from forced injection if:



```text

priority == low

status == review

status == deprecated

problem\_type == broad term

```



Broad terms excluded from strict injection:



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



\## 9. Term Count Limits



| Mode | Max Terms | Strict Terms | Soft Terms |

|---|---:|---:|---:|

| Lightweight | 0-3 | 0 | 0-3 |

| Soft Term | 5 | 0 | 5 |

| Strict Term | 8 | 5 | 3 |



\---



\## 10. Recommended Prompt Instructions



Lightweight:



```text

Translate naturally and accurately. Do not force terminology replacement unless a core technical term clearly appears.

```



Soft Term:



```text

Use the following terminology as reference. Apply it when natural and contextually appropriate. Do not force mechanical replacement if it makes the translation unnatural.

```



Strict Term:



```text

The following core terminology must be used when the corresponding source term clearly appears in the text. Do not invent alternative translations for these core terms.

```



\---



\## 11. Alignment with 李宛真



Need to confirm:



\- Prompt V3 mode names;

\- whether strict terms and soft terms are separated in prompt input;

\- max term count per segment;

\- how excluded terms are logged;

\- how low-score samples are mapped to termbase candidate updates.





