# 🧭 Newport Navigator

An offline-friendly, installable map for our family stay at **Lime Kiln House**, Newport, Co. Mayo (Aug 22–29).
It shows a curated, illustrated map of the Clew Bay area — food & drink, essentials, beaches & nature,
activities, and golf — with the **hosts' own recommendations** highlighted (⭐) and our **planning notes**
baked in. Each place can open **Google Maps** for turn-by-turn; **Irish hops** in the app
are the local landmark version and stay on the phone once downloaded.

It's a **PWA**: open the hosted link once, "Add to Home Screen", and it launches like an app and works
with **no internet**. Anyone can tap **Add pin** to drop a GPS pin, paste a Maps link / Eircode, or
press-and-hold the map. Pins save on the phone immediately and sync to the family when there's a signal.

## Why it works offline
Map *imagery* (street tiles) can't legally be bundled offline, so this app uses a lightweight, custom
**illustrated basemap** that needs no tiles at all. Places, Irish hops, and family pins live in the
app (and sync when there's a signal), cached by a service worker, so the map opens with no coverage.

Turn-by-turn is **Google Maps** on the place card — that needs a signal. See
[`docs/family-setup.md`](docs/family-setup.md) for the one-page family setup.

## Project structure
```
index.html                # the app (illustrated basemap + pins + filters + info cards)
family-sync.js            # family pins (localStorage + sync)
server.py                 # static files + /api/resolve + /api/pins
manifest.webmanifest      # PWA metadata (name, icons, theme)
sw.js                     # service worker — caches the app shell for offline use
data/places.json          # curated place data — edit this to add/change host pins
icons/                    # app icons (scalable SVG: icon.svg + icon-maskable.svg)
docs/family-setup.md      # "get your phone ready before Ireland" sheet
fly.toml                  # Fly.io app config
Dockerfile                # Python server on port 8080
```

> Icons are SVG so they stay crisp at any size. High-res PNG icons (192/512/maskable/apple-touch)
> are also available in the delivered zip if you want to add them for extra iOS home-screen polish.

## Run it locally
Because the app fetches `data/places.json` (and the pin APIs), it must be served over http (not opened as a `file://`).
Uses port **8787** so it stays out of the way of other local services (including anything on 51xx).
```bash
# from the project folder
python3 server.py
# then visit http://localhost:8787
```
Paste / Eircode lookup and pin sharing need this server (a plain `python3 -m http.server` will not run the APIs).

## Family pins
Curated places stay in `data/places.json`. Family pins are **not** written there — they live in
`localStorage` on each phone and sync through `POST /api/pins` when online (last `updatedAt` wins;
removes are soft-deletes). Offline, they still save on that phone and push when there's a signal.

**Add pin** offers **I'm here** (GPS), **paste** (Google/Apple Maps share, `geo:`, coordinates, or an
Irish Eircode), or press-and-hold on the map. Short Google links (`maps.app.goo.gl/…`) are followed
on the server. Eircodes are looked up on OpenStreetMap (only if that code is mapped). A pin within ~50 m of an existing one offers to
open that pin instead.

The trip code is `clewbay2026` (header `X-Trip-Code`; override on the server with `NN_TRIP_CODE`).
Anyone with the family URL and that code can add and see pins. No photos or chat.

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

Then tap **Get latest** on any phone that already has the icon.

## Roadmap
- Fill in the expandable pin fields (hours, photos, longer write-ups) — content task.
- Optional: de-cluster the Westport town pins into an expandable group.
- Optional: a day-by-day itinerary view.
- Optional: directions between two selected pins.
- Optional: Android share-target so a Maps share opens Add pin directly.

Built for the Lime Kiln House trip. Map data © OpenStreetMap contributors (positions); illustration is original.
