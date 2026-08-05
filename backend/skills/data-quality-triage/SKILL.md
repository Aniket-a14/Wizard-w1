---
name: data-quality-triage
description: What to establish about a table before trusting any aggregate computed from it
tags: [quality, aggregation, joins, nulls]
version: 1.0
---

## When to use this

Before reporting any total, average, rate or ranking. A number computed from a
table nobody has checked is a confident answer to a question that was never
actually asked of the data.

## The four checks, in order

**1. Row grain.** What does one row mean? Not "an order" — one row per order, or
one row per order *line*? Summing a per-order amount over a per-line table
multiplies the total by the average basket size, and the result looks entirely
plausible. Establish this before anything else: every other check depends on it.

```python
print(len(df), df[key_columns].drop_duplicates().shape[0])
```

If those two numbers differ, the table is finer-grained than the key suggests.

**2. Null structure, not null count.** A 3% null rate is meaningless on its own.
What matters is whether the nulls are concentrated — in one time period, one
region, one source system. Nulls clustered in a segment mean an aggregate
computed over the rest silently excludes that segment.

```python
print(df.isna().mean().sort_values(ascending=False).head(10))
print(df[df[column].isna()].groupby(segment).size())
```

**3. Types that are lying.** A numeric column read as `object` usually contains
one bad value — a `"N/A"`, a thousands separator, a currency symbol. Coercing it
with `errors='coerce'` turns those into nulls, which then quietly drop out of the
mean. Count what coercion destroys before accepting it.

```python
coerced = pd.to_numeric(df[column], errors="coerce")
lost = coerced.isna().sum() - df[column].isna().sum()
print(f"{lost} values could not be parsed as numbers")
```

Report that number. Do not silently accept it.

**4. Duplicates that are not errors.** The same entity appearing twice may be a
genuine repeat event or an ingestion artefact. Check whether the duplicates
differ in any column at all: identical rows are usually an artefact, rows
differing only in a timestamp are usually real.

## Before joining

State the expected relationship — one-to-one, one-to-many, many-to-many — and
then verify it, rather than assuming it and discovering the answer is 4x too
large. An inner join silently drops non-matching rows on both sides; check how
many before deciding the join was correct.

```python
merged = left.merge(right, on=key, how="outer", indicator=True)
print(merged["_merge"].value_counts())
```

## What to say in the answer

Any of these that turned out to be true belongs in the answer, not just in the
working:

- rows excluded by a join, and how many
- values lost to numeric coercion
- a segment with a materially higher null rate than the rest
- an aggregate computed at a grain different from the one the question implies
