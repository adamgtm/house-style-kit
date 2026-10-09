# Lines for CLAUDE.md or AGENTS.md

Add these to your agent instructions (`CLAUDE.md` for Claude Code, `AGENTS.md` for Codex) so every session knows what "in the house style" means.

```markdown
## House style

- When I ask for anything "in the house style" (graphics, charts, slides, pages, emails), read `house-style/README.md` first, then look at the role models for that kind of work in `house-style/role-models/`.
- When I edit something you made, save the reusable lesson to `house-style/lessons.md`: the date, what we were making, my exact words, and the rule in one sentence. If the lesson changes a rule, update `house-style/README.md` too.
- When I say "make this a role model", copy the final version into `house-style/role-models/`, add it to `manifest.json` with my words, and rebuild the gallery: `python3 house-style/build_gallery.py`.
- Look at anything visual at phone width before showing it to me.
```
