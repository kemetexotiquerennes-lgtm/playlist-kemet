"""
Playlist tournante : chaque matin, les morceaux les plus anciens sortent
et de nouveaux morceaux de bibliotheque.csv entrent à des positions au hasard.

- Les morceaux jamais passés sont prioritaires, puis ceux passés il y a le plus longtemps.
- Chaque titre n'est cherché sur YouTube qu'une seule fois (résultat gardé dans cache.json),
  ce qui économise le quota les jours suivants.
- Si le quota du jour est atteint, le script s'arrête proprement et reprend le lendemain.

Variables d'environnement (Secrets GitHub) : YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
DRY_RUN=1 : affiche ce qui serait fait sans rien modifier.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CACHE_FILE = ROOT / "cache.json"        # titre|artiste → id de vidéo (ou null si introuvable)
PLAYS_FILE = ROOT / "passages.json"     # titre|artiste → date du dernier passage
SCOPES = ["https://www.googleapis.com/auth/youtube"]

COEUR = {
    "Antilles, Guyane & Haïti", "Réunion, Maurice & Madagascar", "Mayotte & Comores",
    "Cameroun", "Sénégal", "Afro urbain France",
}
COST = {"read": 1, "search": 100, "insert": 50, "delete": 50}


class QuotaReached(Exception):
    pass


class Budget:
    def __init__(self, limit: int):
        self.limit, self.used = limit, 0

    def can(self, op: str) -> bool:
        return self.used + COST[op] <= self.limit

    def spend(self, op: str):
        if not self.can(op):
            raise QuotaReached()
        self.used += COST[op]


def key(title: str, artist: str) -> str:
    return f"{title}|{artist}"


def stable_rank(k: str) -> str:
    """Ordre « au hasard » mais fixe d'un jour à l'autre, pour que les recherches
    faites à l'avance tombent sur les morceaux qui passeront ensuite."""
    return hashlib.md5(k.encode("utf-8")).hexdigest()


def queue_order(t: dict, plays: dict):
    # jamais passés d'abord, puis du plus ancien passage au plus récent
    return (plays.get(t["key"], ""), stable_rank(t["key"]))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def is_quota_error(err) -> bool:
    return "quotaExceeded" in str(err) or "dailyLimitExceeded" in str(err)


def is_playlist_missing(err) -> bool:
    return "playlistNotFound" in str(err)


def is_gone_error(err) -> bool:
    """La VIDÉO (ou l'élément de playlist) n'existe plus ou est bloquée — pas la playlist."""
    s = str(err)
    if is_playlist_missing(err):
        return False
    return any(x in s for x in ("videoNotFound", "playlistItemNotFound", "videoNotAvailable", "forbidden"))


def with_retry(call, tries: int = 6, wait: int = 5):
    """Une playlist toute neuve met parfois quelques secondes à être visible par l'API."""
    for attempt in range(tries):
        try:
            return call()
        except Exception as err:  # noqa: BLE001
            if is_playlist_missing(err) and attempt < tries - 1:
                time.sleep(wait)
                continue
            raise


def load_library() -> list[dict]:
    with open(ROOT / "bibliotheque.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{"title": r["Title"].strip(), "artist": r["Artist"].strip(), "zone": r.get("Zone", "").strip(),
             "key": key(r["Title"].strip(), r["Artist"].strip())} for r in rows if r.get("Title")]


# ───────────────────────── choix des morceaux ─────────────────────────

def plan_groups(n: int, cfg: dict) -> list[str]:
    """Liste de n étiquettes : 'honneur', 'coeur' ou 'elargie', dans un ordre mélangé."""
    groups = []
    zone = (cfg.get("zone_a_l_honneur") or "").strip()
    if zone:
        groups += ["honneur"] * round(n * cfg.get("part_zone_a_l_honneur", 0) / 100)
    rest = n - len(groups)
    coeur = round(rest * cfg["melange"]["coeur_de_cible"] / 100)
    groups += ["coeur"] * coeur + ["elargie"] * (rest - coeur)
    random.shuffle(groups)
    return groups


def pick_candidates(library, cfg, in_playlist: set[str], artist_count: dict, plays: dict, cache: dict, n: int):
    """Renvoie jusqu'à n morceaux, en respectant le mélange et le max par artiste."""
    zone = (cfg.get("zone_a_l_honneur") or "").strip()

    def group_of(t):
        if zone and t["zone"] == zone:
            return "honneur"
        return "coeur" if t["zone"] in COEUR else "elargie"

    def eligible(t):
        return (t["key"] not in in_playlist
                and cache.get(t["key"], "?") is not None          # pas marqué introuvable
                and artist_count.get(t["artist"], 0) < cfg["max_par_artiste"])

    pool = sorted(library, key=lambda t: queue_order(t, plays))
    chosen = []
    for g in plan_groups(n, cfg):
        for fallback in (g, "coeur", "elargie", "honneur"):
            t = next((t for t in pool if group_of(t) == fallback and eligible(t)), None)
            if t:
                chosen.append(t)
                in_playlist.add(t["key"])
                artist_count[t["artist"]] = artist_count.get(t["artist"], 0) + 1
                break
    return chosen


# ───────────────────────── YouTube ─────────────────────────

def youtube_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"❌ Secrets manquants : {', '.join(missing)}")
    creds = Credentials(
        token=None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def get_or_create_playlist(yt, cfg, budget: Budget) -> str:
    title = cfg["playlist"]["title"]
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req:
        budget.spend("read")
        res = req.execute()
        for p in res.get("items", []):
            if p["snippet"]["title"] == title:
                return p["id"]
        req = yt.playlists().list_next(req, res)
    budget.spend("insert")
    created = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title, "description": cfg["playlist"]["description"]},
        "status": {"privacyStatus": cfg["playlist"]["privacy"]},
    }).execute()
    print(f"🆕 Playlist créée : {title}")
    time.sleep(10)
    return created["id"]


def current_items(yt, playlist_id, budget: Budget) -> list[dict]:
    items = []
    req = yt.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50)
    while req:
        budget.spend("read")
        res = with_retry(req.execute)
        for it in res.get("items", []):
            items.append({"item_id": it["id"], "video_id": it["contentDetails"]["videoId"],
                          "added": it["snippet"].get("publishedAt", "")})
        req = yt.playlistItems().list_next(req, res)
    return items


def search(yt, t: dict, budget: Budget) -> str | None:
    budget.spend("search")
    res = yt.search().list(part="id", q=f"{t['title']} {t['artist']}", type="video",
                           videoCategoryId="10", maxResults=1, regionCode="FR").execute()
    items = res.get("items", [])
    return items[0]["id"]["videoId"] if items else None


# ───────────────────────── programme ─────────────────────────

def main():
    cfg = yaml.safe_load((ROOT / "rotation.yaml").read_text(encoding="utf-8"))
    dry = os.environ.get("DRY_RUN") == "1"
    today = os.environ.get("DATE_DU_JOUR") or datetime.now(timezone.utc).date().isoformat()
    library = load_library()
    by_video = {}
    cache, plays = load_json(CACHE_FILE), load_json(PLAYS_FILE)
    for k, v in cache.items():
        if v:
            by_video[v] = k
    by_key = {t["key"]: t for t in library}

    budget = Budget(cfg["budget_quota"])
    yt = youtube_client()
    stats = {"retirés": 0, "ajoutés": 0, "recherches": 0, "introuvables": 0}

    try:
        playlist_id = get_or_create_playlist(yt, cfg, budget)
        items = current_items(yt, playlist_id, budget)

        # 1) repérer les plus anciens à faire sortir (seulement si la playlist est pleine)
        size, renew = cfg["taille"], cfg["renouvellement_par_jour"]
        oldest = sorted(items, key=lambda i: i["added"])
        overflow = oldest[:max(0, len(items) - size)]
        to_remove = oldest[len(overflow):len(overflow) + (renew if len(items) >= size else 0)]
        n_add = (size - len(items) + len(overflow)) + len(to_remove)

        def delete(it):
            budget.spend("delete")
            try:
                yt.playlistItems().delete(id=it["item_id"]).execute()
            except Exception as err:  # noqa: BLE001
                if is_quota_error(err):
                    raise QuotaReached()
                if not is_gone_error(err):
                    raise
            items.remove(it)
            stats["retirés"] += 1

        if not dry:
            for it in overflow:        # playlist trop longue (taille réduite dans la config)
                delete(it)

        # 2) choisir les nouveaux ; chaque ancien ne sort qu'une fois son remplaçant ajouté,
        #    pour que la playlist ne se vide jamais si le quota est coupé en route
        leaving = {i["video_id"] for i in to_remove}
        in_playlist = {by_video[i["video_id"]] for i in items
                       if i["video_id"] in by_video and i["video_id"] not in leaving}
        artist_count: dict[str, int] = {}
        for k in in_playlist:
            if k in by_key:
                a = by_key[k]["artist"]
                artist_count[a] = artist_count.get(a, 0) + 1
        in_playlist |= {by_video[v] for v in leaving if v in by_video}   # pas de retour immédiat

        candidates = pick_candidates(library, cfg, set(in_playlist), artist_count, plays, cache, n_add * 2)
        added = 0
        failures = 0
        for t in candidates:
            if added >= n_add:
                break
            pending_delete = COST["delete"] if to_remove else 0
            vid = cache.get(t["key"])
            if vid is None and t["key"] not in cache:
                if budget.used + COST["search"] + COST["insert"] + pending_delete > budget.limit:
                    break
                vid = search(yt, t, budget)
                stats["recherches"] += 1
                cache[t["key"]] = vid
                if vid:
                    by_video[vid] = t["key"]
                else:
                    stats["introuvables"] += 1
                    continue
            if not vid:
                continue
            if dry:
                print(f"  + [{t['zone']}] {t['artist']} — {t['title']}")
                added += 1
                stats["retirés"] += 1 if to_remove and added <= len(to_remove) else 0
                continue
            if budget.used + COST["insert"] + pending_delete > budget.limit:
                break
            budget.spend("insert")
            body = {"snippet": {
                "playlistId": playlist_id,
                "position": random.randint(0, len(items)),
                "resourceId": {"kind": "youtube#video", "videoId": vid},
            }}
            try:
                with_retry(lambda: yt.playlistItems().insert(part="snippet", body=body).execute())
                failures = 0
            except Exception as err:  # noqa: BLE001
                if is_quota_error(err):
                    raise QuotaReached()
                if is_gone_error(err):
                    cache[t["key"]] = None   # vidéo supprimée ou bloquée : on ne la reprendra plus
                    failures += 1
                    if failures >= 5:
                        raise RuntimeError("5 ajouts refusés d'affilée : arrêt par sécurité. Dernière erreur : " + str(err))
                    continue
                raise
            items.append({"item_id": "", "video_id": vid, "added": today})
            plays[t["key"]] = today
            added += 1
            stats["ajoutés"] = added
            if to_remove:
                delete(to_remove.pop(0))

        # 3) s'il reste du quota, préparer les recherches des prochains jours
        if not dry:
            upcoming = [t for t in sorted(library, key=lambda t: queue_order(t, plays))
                        if t["key"] not in cache]
            for t in upcoming:
                if not budget.can("search"):
                    break
                vid = search(yt, t, budget)
                stats["recherches"] += 1
                cache[t["key"]] = vid
                if not vid:
                    stats["introuvables"] += 1

    except QuotaReached:
        print("⏸️  Quota du jour atteint : la suite se fera demain.")
    except Exception as err:  # noqa: BLE001
        if not is_quota_error(err):
            if not dry:
                save_json(CACHE_FILE, cache)
                save_json(PLAYS_FILE, plays)
            raise
        print("⏸️  Quota du jour atteint (signalé par YouTube) : la suite se fera demain.")
    finally:
        if not dry:
            save_json(CACHE_FILE, cache)
            save_json(PLAYS_FILE, plays)

    found = sum(1 for v in cache.values() if v)
    never = sum(1 for t in library if t["key"] not in plays and cache.get(t["key"], "?") is not None)
    print(f"🎶 Aujourd'hui : {stats['retirés']} retirés, {stats['ajoutés']} ajoutés, "
          f"{stats['recherches']} recherches ({stats['introuvables']} introuvables). "
          f"Quota utilisé : {budget.used}/{budget.limit}")
    print(f"📚 Bibliothèque : {len(library)} titres, {found} déjà trouvés sur YouTube, "
          f"{never} jamais encore passés.")
    if not dry and 'playlist_id' in locals():
        print(f"🔗 https://www.youtube.com/playlist?list={playlist_id}")


if __name__ == "__main__":
    main()
