---
name: cohort-analysis
description: Defining cohorts correctly and computing retention, churn or lifetime value across them
tags: [cohorts, retention, churn, ltv, time-series]
version: 1.0
---

## When to use this

Any question about retention, churn, activation or how one group of users behaves
differently over time from another. "Which cohorts are driving churn", "does the
January signup group behave differently", "is retention improving".

The snippets below name their columns `"entity_id"`, `"event_date"` and
`"activity_date"`. Those are placeholders — substitute the real column names from
the data in front of you.

## Define the cohort before computing anything

A cohort is fixed by an event that happens **once** per entity — first purchase,
signup, activation. Two mistakes account for most wrong cohort analyses:

- **Assigning on a recurring event.** If cohort membership is derived from any
  transaction date, an entity lands in several cohorts and every rate is
  computed over an inflated denominator.
- **Reassigning over time.** Once assigned, an entity's cohort never changes. It
  is a property of the entity, not of the row being looked at.

```python
cohort = df.groupby("entity_id")["event_date"].min().dt.to_period("M").rename("cohort")
df = df.merge(cohort, left_on="entity_id", right_index=True)
```

Deriving it with `transform("min")` is the same thing in one step and avoids a
merge that can change the row count.

## Period index, not calendar date

Retention compares cohorts at the *same age*, not on the same date. A cohort
formed in January is six months old in July; one formed in June is one month old.
Plotting both against the calendar compares a mature cohort to a new one and
concludes retention collapsed.

```python
df["period"] = (df["activity_date"].dt.to_period("M") - df["cohort"]).apply(lambda x: x.n)
```

## The denominator is the cohort's own size

Retention at period *n* is *active entities in period n* over *the cohort's size
at period 0* — never over the previous period, and never over the whole
population. Dividing by the previous period gives period-over-period survival,
which is a different and usually smaller-looking number.

```python
sizes = df[df["period"] == 0].groupby("cohort")["entity_id"].nunique()
active = df.groupby(["cohort", "period"])["entity_id"].nunique()
retention = (active / sizes).unstack("period")
```

## The right-hand triangle is not data

A cohort table is triangular: recent cohorts have no period-6 row yet because
period 6 has not happened. Those cells are **absent, not zero**. Averaging down a
column mixes a real value from an old cohort with a missing one from a new
cohort, and every long-horizon metric drifts downward as a result. Exclude any
cohort that has not had time to reach the period being compared, and say which
ones were excluded.

## Churn is the mirror, and its definition is a choice

Churn needs an explicit inactivity window — 30 days, 90 days, a missed renewal.
State the window in the answer. Without it "20% churn" is not a measurement, and
two people using different windows will disagree about the same data forever.

## What to report

- the cohort definition and the event it is anchored on
- the churn or activity window, in days
- which cohorts were excluded for immaturity, and how many
- cohort sizes alongside the rates — a 40% retention on 12 entities is noise, and
  a rate without its denominator invites it to be read as a finding
