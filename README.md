# 🧭 Newport Navigator

An offline-friendly, installable map for our family stay at **Lime Kiln House**, Newport, Co. Mayo (Aug 22–29).
It shows a curated, illustrated map of the Clew Bay area — food & drink, essentials, beaches & nature,
activities, and golf — with the **hosts' own recommendations** highlighted (⭐) and our **planning notes**
baked in. Each place hands off to a real maps app for turn-by-turn **walking / cycling / driving** directions.

It's a **PWA**: open the hosted link once, "Add to Home Screen", and it launches like an app and works
with **no internet**.

## Why it works offline (and where directions come from)
Map *imagery* (street tiles) can't legally be bundled offline, so this app uses a lightweight, custom
**illustrated basemap** that needs no tiles at all. The place data, filters, and info all live in the app
and are cached by a service worker, so the whole thing opens with no signal.

For actual **roads + directions offline**, each pin's **"Directions (offline)"** button opens the phone's
maps app via a `geo:` link. Install **[Organic Maps](https://organicmaps.app)** (free, open-source) and
download the West Mayo region once — it routes **walking, cycling, and driving** fully offline (including the
Great Western Greenway). There's also a **Google Maps** button (driving-only offline; needs signal for
walk/bike). See [`docs/family-setup.md`](docs/family-setup.md) for the one-page family setup.

## Project structure
```
index.html                # the app (illustrated basemap + pins + filters + info cards)
manifest.webmanifest      # PWA metadata (name, icons, theme)
sw.js                     # service worker — caches the app shell for offline use
data/places.json          # ALL place data — edit this to add/change pins (see below)
icons/                    # app icons (scalable SVG: icon.svg + icon-maskable.svg)
docs/family-setup.md      # "get your phone ready before Ireland" sheet
.nojekyll                 # tells GitHub Pages to serve files as-is
```

> Icons are SVG so they stay crisp at any size. High-res PNG icons (192/512/maskable/apple-touch)
> are also available in the delivered zip if you want to add them for extra iOS home-screen polish.

## Run it locally
Because the app fetches `data/places.json`, it must be served over http (not opened as a `file://`).
```bash
# from the project folder
python3 -m http.server 8080
# then visit http://localhost:8080
```
(or use any static server / the Live Server extension in Cursor/VS Code).

## Add or edit places
All content lives in **`data/places.json`** — no code changes needed. Each place looks like:
```json
{
  "id": "the-tavern-bar-murrisk",
  "cat": "food",              // home | food | shop | beach | do | golf
  "host": true,               // true = ⭐ host pick
  "emoji": "🦀",
  "name": "The Tavern Bar, Murrisk",
  "lat": 53.777, "lng": -9.636,
  "desc": "Short one-liner shown on the card.",
  "plan": "Optional orange callout — our planning note.",
  "info": "Optional small print (e.g. 'Book ahead').",
  "tel": "+3539864060",       // optional — enables the Call button
  "hours": "", "website": "", "kidFriendly": null,
  "bookingNeeded": null, "photo": "", "long": ""   // expandable fields (fill in later)
}
```
`long` (a longer write-up) is shown on the card in place of `desc` when present. `pin` positions use the
same simple projection as the basemap; anything outside the core Newport–Achill area shows up in the
"Off this map" strip instead of on the map.

## Deploy (GitHub Pages)
1. Push this repo to GitHub.
2. Repo **Settings → Pages → Build and deployment → Source: Deploy from a branch**, branch `main`, folder `/ (root)`.
3. Wait ~1 min; your app is live at `https://<user>.github.io/newport-navigator/`.
4. Open that link on each phone → share sheet → **Add to Home Screen**.

## Roadmap
- Fill in the expandable pin fields (hours, photos, longer write-ups) — content task.
- Optional: de-cluster the Westport town pins into an expandable group.
- Optional: a day-by-day itinerary view.

Built for the Lime Kiln House trip. Map data © OpenStreetMap contributors (positions); illustration is original.
