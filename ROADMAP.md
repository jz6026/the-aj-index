# The AJ Index: Roadmap

**The idea:** when you're mid-trade and someone's waiting on you, you shouldn't have to dig
through the worth wiki. This tells you what the AJ Item Worth Wiki says about both sides in
seconds, and gets smarter over time by learning from real trades.

## Done
- [x] Wiki fetcher + parser: grabs every item's worth (every color too) and keeps the history
- [x] Comments fetcher: pulls listings, sales and trades from item comment sections (usernames stripped out)
- [x] Simple tagger: sorts comments into sale / sold / trade / ISO / question and pulls out dim + gem prices. This is the baseline the ML model has to beat
- [x] 31 tests

## v1: Trade chatbot (ship this first!)
- [x] **Value ladder:** built from the wiki's own counter pages (RIMs → betas → wrists → short collars → long collars), so comparing two values is "exactly what the wiki says"
  - Diamond-priced items and RIM swaps are different kinds of deals, so the chatbot explains instead of comparing when they're mixed
- [x] **Trade check** (`trade.py`): give/get sides, wiki values quoted word for word, short verdict, warnings
- [x] **Item name matching:** nobody types full item names, so it needs to get slang like "blk long", "cb", "rim beard" and figure out the exact item + color
- [ ] **Chatbot:** tell it the trade → it looks up both sides → quotes the wiki values exactly → gives a recommendation
  - Never makes up a value, only uses what the wiki says
  - Short answers since you're mid-trade, and always ends with "double-check before you accept"
  - Sticks to trading talk and doesn't ask for any personal info
- [ ] **Website** with the chat, a shoutout to the wiki, and a note that it's unofficial
- [x] **Cloud setup:** Docker + Postgres, AWS stack (ECS + RDS + S3/CloudFront) with a daily wiki refresh. See [DEPLOY.md](DEPLOY.md)
- [x] API: item search + lookup, and `/api/trade` so the website can use the trade checker
- [ ] **Go live:** first real deploy, limits on how much each person can chat

## v2: Learning real rankings
- [x] Labeling tool + my own classifier (word counts + logistic regression, built with scikit-learn) that gets scored against the rules
- [ ] Label a few hundred comments by hand (can chip away at this anytime)
- [ ] Train on the real labels and see if my model actually beats the rules
- [ ] Pull out *which* items are traded for which (slang dictionary + rules, with the model sorting comment types)
- [ ] Maybe: fine-tune a Hugging Face model too and compare all three
- [ ] Elo-style rankings: every item starts where the wiki puts it, then real trades move it up or down
  - Every item gets its own rank (because not all den betas are equal lol)
  - Shows how confident it is, and newer trades count more
  - Tested against the wiki's own tiers to see if it actually does better
- [ ] Value trend charts (what happens after re-releases, crashes, etc.)
- [ ] Chatbot shows the wiki value AND the learned rank, and explains when they don't match
- [ ] **Talk:** a free discussion board (price checks, "is this fair?" posts with trade cards)
  - Anonymous animal names ("a sleepy otter"), no profiles, no DMs, everything stays public
  - Filter on every post like AJ's chat: blocks phone numbers, emails, links, "add me on ___"
  - Report button, and posts auto-hide after a few reports until I check them
  - Rate limits (like 1 post a minute) + an automatic toxicity check before posting
  - Posts here are fair game for training (with a note telling people that)

## Frontend: terminal style
- [ ] Resizable panels: quote, trade checker, trade book, chart, movers, tape
- [ ] Layout + trade book saved in the browser (no account needed)
- [ ] Phones: same panels as stacked cards
- [ ] Switch to React for this

## Later
- [ ] Let people log their own trades on the site (no accounts or usernames, weird outliers get flagged)
- [ ] Inventory tracking
- [ ] Accounts / login (Amazon Cognito: email or Google). Only for features that need it
  (logged trades, inventory, discussion). 13+ only, and check the kids' privacy rules (COPPA) first

## Ground rules
- **Credit the wiki:** its content is CC BY-SA, so the site credits the AJ Item Worth Wiki and anything built from its text gets shared under the same license
- **Unofficial fan project:** not affiliated with WildWorks, no copied game art or logos (link to images instead)
- **No scraped usernames:** names from the wiki's comments get scrubbed before saving, since lots of players are kids. Display names people pick on my own site are fine
- Reach out to the wiki admins / Discord before launching
