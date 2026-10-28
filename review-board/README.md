# Review board

A review board is one page where you look at a round of options, pick the ones you like, leave a note on each, and click Send. Your notes go back to your agent with no copy and paste.

Use it for any design round with options: graphics, slides, page mockups. One item per thing you're deciding. One version per option.

## The `review.json` contract

Put `review.json` next to the round's images. Paths are relative to the file.

```json
{"id": "round-1", "title": "Round 1 review", "instruction": "Pick the versions you like. Leave a note on each.",
 "sections": [{"name": "Intro", "items": [{"id": "then-now", "title": "Then and Now",
   "versions": [{"id": "then-now-A", "label": "A", "src": "then-now/a.png",
                 "note": "One line: what this version does.", "recommended": true,
                 "info": {"file": "path/to/source", "sources": ["where the facts came from"]}}]}]}]}
```

- Item ids and version ids are unique across the whole board.
- Every item has at least one version, and every `src` exists.
- `label` defaults to A, B, C.
- `note` shows under the stack. Keep it to one line.
- `info` shows behind a small "info" link. `recommended` shows only there, so it doesn't bias you.
- Hold facts and layout steady across versions. Change only what you're deciding.

## Run it

File mode is the default. The board is a plain `board.html` that opens from disk. No server.

```
python3 review-board/scripts/build_review_board.py path/to/review.json --wait --open
```

Agents: run this as a background job. It builds into `review-board-<name>/` beside `review.json`, opens the board, and prints `Review board ready: <path>`. Tell the user the path.

When the user clicks Send, the browser saves a feedback file to their Downloads folder. The waiting job sees it within a second, checks it belongs to this board and build, saves it as `feedback/<time>__<id>.json` and `.md` beside `review.json`, prints the notes, and exits. That wakes the agent.

- A feedback file from an older build is ignored. Reload `board.html` and send again.
- "Copy as Markdown" is the fallback if the download is blocked.
- Only items with a like or a note appear in the Markdown. The last line says how many had neither.
- `--inbox DIR` watches a folder other than Downloads.

The other mode runs a small local server:

```
python3 review-board/scripts/build_review_board.py path/to/review.json --serve --open
```

It listens on 127.0.0.1 only. Add `--wait` to exit after the first send. Use it only if file mode doesn't suit you.

Without `--open`, nothing launches. Different `review.json` files in one folder get different output folders. Rebuilding over another board's folder needs `--force`.

The scripts use the standard library plus Pillow.

## Keys

On the page:

- `L` likes the version shown. The Like button does the same.
- Click a thumbnail, or press up and down on a focused stack, to change version.
- `Enter` opens the full-screen view.
- `Cmd/Ctrl+Enter` in a note jumps to the next item.

In full screen:

- Left and right change graphic.
- Up and down, or `1` to `9`, change version.
- `L` likes. `N` opens the note.
- `Esc` leaves the note, then closes the view.
- `?` lists the keys.

## Act on the notes

1. Apply each note as a targeted edit. Change only what was named.
2. A like is a pick, not a request to change that version. A note with no like means a change is wanted. If a note says "B is best," count it as a like.
3. Build the next round as a new `review.json` with a new board id, and run it again.

## Turn notes into lessons

The notes are the source of your house style. After each round, save every pick and every note to `house-style/lessons.md` in the reviewer's own words, with the date, the board, and a category. When the same note comes up twice, or the reviewer says "always," move it into the standard for that kind of work.
