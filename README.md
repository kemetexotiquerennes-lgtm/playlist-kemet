# Playlist tournante Kemet Exotique

Une playlist YouTube de **150 morceaux (environ 10 h)** qui se renouvelle **chaque matin vers 7 h** :
les 40 morceaux les plus anciens sortent et 40 nouveaux entrent, à des places au hasard.
Les morceaux viennent de `bibliotheque.csv` (1 781 titres classés par zone). Les titres jamais passés sont
prioritaires : avant qu'un morceau revienne, les autres de sa catégorie sont passés.

- **60 % cœur de cible** : Antilles-Guyane-Haïti, Réunion-Maurice-Madagascar, Mayotte-Comores, Cameroun, Sénégal, afro urbain français
- **40 % élargie** : reste de l'Afrique, Cap-Vert et Angola, Caraïbes anglophones
- Jamais plus de 3 morceaux d'un même artiste en même temps

Tout tourne sur GitHub, gratuitement : pas d'ordinateur allumé, pas d'abonnement.

## Ce qui se passe les premiers jours
| Période | Ce qui se passe |
|---|---|
| Jours 1 à 3 | La playlist se remplit (environ 60 morceaux par jour à cause du quota YouTube) |
| À partir du jour 4 | 40 morceaux renouvelés chaque matin |
| Au bout de 40 jours environ | Tous les titres ont été cherchés une fois sur YouTube : le script n'utilise plus que 40 % du quota |

Chaque titre n'est cherché **qu'une fois** : la vidéo trouvée est gardée dans `cache.json`.
Le quota restant chaque jour sert à chercher à l'avance les morceaux des jours suivants.

---

## Installation (environ 20 minutes, une seule fois)

### 1. Google Cloud
Même procédure que pour le premier kit. Si c'est déjà fait, garde ton `client_secret.json`.
1. Projet créé et **YouTube Data API v3** activée.
2. **Google Auth Platform → Accès aux données** : ajoute le niveau d'accès `.../auth/youtube`.
3. **Clients → Créer un client → « Application de bureau »** : télécharge le JSON, renomme-le `client_secret.json`.
4. **Audience → Publier l'application.** Indispensable : en mode Test, Google coupe l'accès au bout de 7 jours
   et la rotation s'arrête. À la connexion, Google affiche « Application non validée » : clique sur *Paramètres avancés*
   puis *Accéder à… (non sécurisé)*. C'est ta propre appli.

### 2. Autoriser l'accès (sur ton ordi)
```bash
pip install -r requirements.txt
python get_refresh_token.py
```
Connecte-toi avec **le compte Google de la chaîne qui doit héberger la playlist**.
Le terminal affiche alors 3 valeurs.

### 3. GitHub
1. Crée un dépôt **privé** (par ex. `playlist-kemet`) et envoie-y tous les fichiers du dossier, **sauf `client_secret.json`**.
2. **Settings → Secrets and variables → Actions → New repository secret** : crée `YT_CLIENT_ID`, `YT_CLIENT_SECRET` et `YT_REFRESH_TOKEN`.
3. **Actions → Playlist tournante Kemet → Run workflow** pour le premier lancement.
   Le journal affiche le lien de la playlist.

Ensuite, tu n'as plus rien à faire.

---

## Réglages (`rotation.yaml`, modifiable sur GitHub avec l'icône crayon)
| Réglage | Par défaut | Effet |
|---|---|---|
| `taille` | 150 | Nombre de morceaux dans la playlist |
| `renouvellement_par_jour` | 40 | Morceaux changés chaque matin. Maximum conseillé : 45 (quota) |
| `melange` | 60 / 40 | Part cœur de cible / élargie |
| `zone_a_l_honneur` | vide | Ex. `"Sénégal"` pour coller au pays de la semaine |
| `part_zone_a_l_honneur` | 20 | % des nouveaux morceaux réservés à cette zone |

**Zone à l'honneur :** les petites zones (Cameroun 56 titres, Réunion 55, Mayotte-Comores 11) sont épuisées en quelques jours.
Le script complète alors avec le cœur de cible, ce n'est pas une panne. Pour mettre une petite zone en avant toute une semaine,
garde une part autour de 10-15 %, ou ajoute des titres de cette zone dans la bibliothèque.

## Ajouter ou retirer des morceaux
Modifie `bibliotheque.csv` (colonnes `Title,Artist,Zone`), sur GitHub ou dans Excel puis renvoie le fichier.
Pour la zone, reprends exactement un des noms déjà utilisés dans la colonne. Les nouveaux titres passent en priorité, puisqu'ils n'ont jamais été joués.

## Bon à savoir
- **Mauvaise version trouvée** (live, reprise…) : dans `cache.json`, remplace l'identifiant de vidéo de ce titre
  par le bon (les 11 caractères après `v=` dans l'adresse YouTube). Mets `null` pour ne plus jamais le passer.
- **Tester sans rien modifier** : `DRY_RUN=1 python rotation_quotidienne.py`
- **Erreur `invalid_grant` dans le journal** : l'autorisation a expiré. Relance `get_refresh_token.py` et remplace le secret `YT_REFRESH_TOKEN`.
- Si un jour la rotation ne tourne plus, regarde l'onglet Actions : GitHub peut mettre une tâche planifiée en pause.
  Clique alors sur *Enable workflow*. Le script ne prend qu'une minute par jour, ce qui reste largement dans les minutes gratuites de GitHub.
- **Musique au magasin** : diffuser de la musique dans un commerce demande une licence SACEM, et les conditions de YouTube
  réservent les playlists à un usage personnel.
