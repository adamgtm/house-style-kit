# Start here (for the agent)

You are helping someone build a **house style**: a small folder that teaches coding agents what their graphics, charts, slides, pages and emails should look like. It works because it is built from their real work and their own words, not adjectives. Your job is to walk them through it in about 30 minutes, in plain English, one question at a time.

When you finish, their project has:

1. `house-style/README.md`: the index. Principles, the look, where their work is seen, how each kind of work signs off, and the role model to copy for each kind.
2. `house-style/lessons.md`: lessons from their edits, in their exact words, dated.
3. `house-style/role-models/`: the role-model images, `manifest.json` (the one list), and `index.html` (the gallery page).
4. A few lines in their `CLAUDE.md` or `AGENTS.md` so "in the house style" means something to every future session.

## Ground rules

- **Their words, not yours.** Quote what they say about their work. Never invent a quote, a claim, a number or a reason they didn't give. When you infer something, label it as your read and ask.
- **One question at a time.** Short questions. Offer an example answer when it helps.
- **Examples beat descriptions.** When their description of their style and their actual work disagree, show them the difference and ask which is right.
- **Keep it local.** Every file you make stays in their project. Don't upload, publish or post anything anywhere. (Like any coding agent, you send what you read to your model provider; don't promise more privacy than that.)
- **Don't overwrite.** If `house-style/` already exists, read it and offer to extend it. Ask before editing `CLAUDE.md` or `AGENTS.md`.
- **Plain English.** No jargon unless they use it. Short progress updates between steps.

## Step 0: set up

1. Confirm you can read and write files in this folder. If you can't (for example, a chat window without local file access), say so plainly: this needs Claude Code or Codex working locally.
2. Copy `house-style-kit/templates/house-style/` to `./house-style/` (skip any file that already exists), copy `house-style-kit/scripts/build_gallery.py` and `house-style-kit/scripts/check_page.py` into `./house-style/`, and copy `house-style-kit/prompts/` to `./house-style/prompts/` so the prompts survive if they delete the kit.
3. Check `python3 --version` works. The gallery page needs nothing else. Two extras are optional, so offer them and don't require them: a post graphic of the gallery needs Pillow (`pip install pillow`), and the phone check (`check_page.py`) needs Playwright (`pip install playwright`, then `python3 -m playwright install chromium`).
4. Optional: show them the example gallery so they see where this is going: `python3 house-style/build_gallery.py --manifest house-style-kit/examples/role-models/manifest.json --open`. Say plainly that the examples are Adam's, to show the format, not a style to copy.

## Step 1: interview (one question at a time)

Ask these in order, skipping anything they've already answered:

1. **What do you make most?** Social graphics, charts, slides, web pages, emails, product screens, something else. Use the answer to set the surfaces in `manifest.json` (rename or remove the starter ones).
2. **Who sees it, and where?** A phone in a social feed, an email, a sales call on a big screen, a website. This decides sizes and how dense things can be.
3. **Point me at 10 to 20 things you've made and liked.** A folder, files, links or screenshots. Ask for pieces they'd want more of, not only the top performers: one-off hits teach the wrong lesson. If they have engagement numbers, use them to suggest candidates; they decide.
4. **Name 3 to 5 outside pieces you admire, and why.** A publication, a site, a chart maker, a deck. The *why* is the valuable part. Write it down in their words.
5. **Any brand basics already set?** Colors, fonts, a logo, a brand guide. Read anything they share, and check it against their actual work.
6. **What do you never want to see?** Things that make work feel off-brand or generic to them.

**No work of their own yet?** That's fine. Use the outside pieces from question 4 as starting role models, marked `"status": "borrowed"`, and tell them to replace each one as their own work piles up.

## Step 2: study the examples

Open every example. Look for what repeats:

- **Color:** background, text, one or two accents. Give hex values only when you can sample them from the file (Pillow can read pixel colors); otherwise describe them and mark the values as estimates.
- **Type:** serif, sans or mono for headlines, labels and numbers. Name a font only if you can tell; otherwise describe it.
- **Layout habits:** one idea per piece or several, how much text, tables or charts or diagrams, how dense.
- **Sign-off:** how each piece ends (logo, name, URL, call to action, nothing).
- **What's absent:** the things they never do. Often as telling as what they do.

Then show them a short read, five to eight bullets: "Here's what I see in your work." Ask them to confirm, correct or add. **Seed `lessons.md` now, in their exact words and dated:** what they admire and why (question 4), what they never want to see (question 6), anything they said about their role models, and every correction to your read. The log should never start empty.

## Step 3: pick the role models together

Go through the candidates one at a time, or in small batches as thumbnails if there are many. For each, ask: keep or skip, and a few words on why. Then:

- Copy each keeper into `house-style/role-models/` with a short descriptive file name. The gallery shows images (PNG, JPG, WebP or GIF). For a deck, PDF, web page or email, save a preview image (the cover or the strongest slide or screen, as a screenshot) as the `file`, and put the original's path or link in `source`.
- Add it to `manifest.json`: `id`, `surface`, `title`, `file` (relative to the manifest), `date` if known, `where` it was used, `words` (their words about it), `why` (one line on what to copy), and `status`:
  - `approved`: they said yes to it as a role model.
  - `shipped`: it went out, but they haven't said it's a role model.
  - `borrowed`: someone else's work they admire.
- If a dark version exists, add it as `dark`.
- Never mark something `approved` without their yes. Use the posted final, not an earlier draft.
- Keep work made in someone else's voice or brand (a guest post, a sponsor's ad) out of the role models. It deviates on purpose.

## Step 4: write the index

Fill in `house-style/README.md` from the template:

- **Principles:** five to eight short rules drawn from the interview and the patterns they confirmed, each with the reason in their words where you have it.
- **The look:** colors, type and spacing habits. Mark estimates.
- **Where it's seen:** sizes and the screen to design for first.
- **Sign-offs:** how each kind of work ends.
- **Kinds of work:** each surface with its role model and anything specific to it.
- **Open questions:** anything still undecided. Don't decide for them.

Keep it short. The standard says what's true now; the lessons log keeps the history.

## Step 5: build the gallery

First, make the gallery look like theirs. In `house-style/role-models/manifest.json`, set `title`, set `brand` (their name and URL, as they write them), and set `tokens` (`paper`, `ink`, `accent`, and fonts if known) from the look they confirmed. Remove any placeholder they didn't fill rather than leaving "Your name or brand" behind. Then:

```
python3 house-style/build_gallery.py --check
python3 house-style/build_gallery.py --open
```

Fix anything `--check` reports. Show them the page. Ask if anything looks wrong or missing.

## Step 6: connect it to their agents

Show them the lines in `house-style-kit/templates/router.md`. Ask before adding them to their `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex). Create the file if it doesn't exist. If they use both tools, add them to both.

## Step 7: a test drive (offer it)

Offer to make one small thing "in the house style" right now: a quote card, a title slide or a simple chart, as a self-contained HTML file. If Google Chrome is installed, render a PNG with headless Chrome; otherwise open the HTML and let them screenshot it. Look at it yourself at the size people will see it first. If it's a web page and Playwright is installed, run `python3 house-style/check_page.py <file>` and fix what it reports. When they react, save the lesson. This is the loop they'll use from now on.

## Step 8: wrap up

Tell them, briefly:

- Ask for anything "in the house style."
- When they edit what you made, the lesson gets saved in their words. When a lesson keeps coming back, it becomes a rule in the index.
- When they love something, say "make this a role model."
- Once a month, paste `house-style/prompts/contradiction-audit.md` to catch rules that drifted apart.
- Later, when they need them, more prompts wait in `house-style/prompts/`: write a standard when one kind of work keeps showing up in the lessons, make a builder for something they make every week, run a batch when they need many at once, and redesign in rounds.
- `house-style/` is self-contained, prompts and scripts included. They can delete `house-style-kit/` whenever they like.
