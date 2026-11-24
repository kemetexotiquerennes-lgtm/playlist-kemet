"""
À lancer UNE SEULE FOIS sur ton ordinateur.

Ouvre une fenêtre Google pour autoriser l'accès à ta chaîne YouTube,
puis affiche les 3 valeurs à copier dans les « Secrets » GitHub.

Prérequis : le fichier client_secret.json (client OAuth de type
« Application de bureau ») téléchargé depuis Google Cloud, placé
dans ce dossier.
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube"]
SECRET_FILE = Path(__file__).parent / "client_secret.json"

if not SECRET_FILE.exists():
    sys.exit("❌ client_secret.json introuvable : télécharge-le depuis Google Cloud "
             "(Google Auth Platform → Clients) et place-le dans ce dossier.")

flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

if not creds.refresh_token:
    sys.exit("❌ Aucun refresh token reçu. Retire l'accès de l'appli sur "
             "myaccount.google.com/permissions puis relance le script.")

client = json.loads(SECRET_FILE.read_text())
client = client.get("installed") or client.get("web")

print("\n✅ Autorisation réussie. Crée ces 3 secrets dans GitHub :\n")
print(f"YT_CLIENT_ID      = {client['client_id']}")
print(f"YT_CLIENT_SECRET  = {client['client_secret']}")
print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
print("\n⚠️  Ne partage jamais ces valeurs et ne les mets pas dans un fichier du dépôt.")
