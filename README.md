# 🧭 Newport Navigator

An offline-friendly, installable map for our family stay at **Lime Kiln House**, Newport, Co. Mayo (Aug 22–29).
It shows a curated, illustrated map of the Clew Bay area — food & drink, essentials, beaches & nature,
activities, and golf — with the **hosts' own recommendations** highlighted (⭐) and our **planning notes**
baked in. Each place hands off to a real maps app for turn-by-turn **walking / cycling / driving** directions.

It's a **PWA**: open the hosted link once, "Add to Home Screen", and it launches like an app and works
with **no internet**. Anyone can tap **Add pin** to drop a GPS pin with a name and description; pins
are saved on that phone (sharing across phones will be a small Fly.io API later).

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
family-sync.js            # family pins in localStorage (this phone only)
manifest.webmanifest      # PWA metadata (name, icons, theme)
sw.js                     # service worker — caches the app shell for offline use
data/places.json          # curated place data — edit this to add/change host pins
icons/                    # app icons (scalable SVG: icon.svg + icon-maskable.svg)
docs/family-setup.md      # "get your phone ready before Ireland" sheet
fly.toml                  # Fly.io app config
Dockerfile                # static file server (gostatic on port 8080)
```

> Icons are SVG so they stay crisp at any size. High-res PNG icons (192/512/maskable/apple-touch)
> are also available in the delivered zip if you want to add them for extra iOS home-screen polish.

## Run it locally
Because the app fetches `data/places.json`, it must be served over http (not opened as a `file://`).
Uses port **8787** so it stays out of the way of other local services (including anything on 51xx).
```bash
# from the project folder
python3 -m http.server 8787
# then visit http://localhost:8787
```
(or use any static server / the Live Server extension in Cursor/VS Code — point it at 8787).

## Family pins (GPS drops)
Curated places stay in `data/places.json`. Pins the family adds are **not** written there — they live in
`localStorage` on that phone. They work offline. Sharing between phones is not wired up yet (planned as a
small Fly.io API).

**Getting an update onto a phone:** open the home-screen icon **on Wi-Fi** and tap **Get latest** in the header. That unregisters the service worker, clears the cache, and reloads from the network. You do not need to delete website data. (The app also refreshes its cache in the background when online; **Get latest** is the immediate / stuck-stale button.)

## Add or edit places
Curated content lives in **`data/places.json`** — no code changes needed. Each place looks like:
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

## Deploy
Live at **[https://newport-navigator.fly.dev/](https://newport-navigator.fly.dev/)**. Open that link on each phone → **Add to Home Screen**.

```bash
fly deploy
```

Then tap **Get latest** on any phone that already has the icon. This is a static PWA (no pin-sharing API yet).

## Roadmap
- Fill in the expandable pin fields (hours, photos, longer write-ups) — content task.
- Optional: de-cluster the Westport town pins into an expandable group.
- Optional: a day-by-day itinerary view.
- Optional: directions between two selected pins.
- Shared family pins via a Fly.io API.

Built for the Lime Kiln House trip. Map data © OpenStreetMap contributors (positions); illustration is original.
