# Knowledge Protocol

## Structure
The knowledge vault is structured as follows within `knowledge/`:
- `knowledge/index.md`: Central registry of all knowledge entries (Decisions, Successes, Failures, Constraints, Insights).
- `knowledge/timeline.md`: Chronological log of sessions and their outcomes.
- `knowledge/entries/K-NNN-slug.md`: Individual knowledge entries, named with a unique ID and descriptive slug.

## Entry Frontmatter
Every entry in `knowledge/entries/` MUST contain the following YAML frontmatter:
```yaml
---
id: K-NNN
title: "Brief description"
type: decision | success | failure | constraint | insight
status: active | superseded | retired
created: YYYY-MM-DD
tags: [tag1, tag2]
---
```
