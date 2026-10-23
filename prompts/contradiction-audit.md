# Monthly contradiction audit

Rules drift. A lesson from last month quietly disagrees with one from today, or a role model still shows an old habit. Paste this into Claude Code or Codex about once a month.

```text
Audit my house style for contradictions. Read house-style/README.md, house-style/lessons.md, every standard in house-style/standards/ (if there are any), house-style/role-models/manifest.json and look at the role-model images. Also read any builders, skills, templates or CSS my agents use to make visual work, and any visual rules in CLAUDE.md or AGENTS.md.

Report, in plain English:
1. Contradictions: two rules that would make an agent produce different results. Quote both, with where each lives and its date.
   - If my newer direction clearly settles it, say which one wins.
   - If it only looks like a conflict because the rules apply to different kinds of work, say so and propose one line that makes the scope clear.
   - If it's a real taste call, give me your recommendation and ask me.
2. Repeats: the same rule written in several places. Suggest the one place it should live.
3. Stale: rules or role models showing something I've since changed (an old footer, a retired color), and file paths that no longer exist.

Don't change anything yet. After I answer, update the file that owns each rule (the README or that kind of work's standard) and record my answers in lessons.md in my words.
```
