# Veille offres Data Scientist / Data Analyst

Chaque jour à **19 h** (lancé par cron-job.org), le script :
1. cherche les offres des 30 dernières heures sur **LinkedIn, Indeed, Glassdoor et HelloWork** (et **France Travail** si tu ajoutes les clés, voir plus bas) pour : data scientist, data analyst, machine learning engineer, analytics engineer, business intelligence, ingénieur IA, en Île-de-France ;
2. supprime les doublons (une même offre publiée sur plusieurs sites) et les offres déjà envoyées ;
3. écarte les stages, alternances, thèses et post-docs ;
4. donne à chaque offre une note sur 10 ;
5. regroupe toutes les nouvelles offres notées 6/10 ou plus dans **une seule issue GitHub par jour**, et te l'assigne. **GitHub t'envoie alors un seul e-mail** avec toutes les offres, sur l'adresse de ton compte, sans aucun mot de passe à configurer.

Jusqu'à 10 offres, l'e-mail détaille chacune ; au-delà, il les présente dans un tableau compact.

Tu reçois donc **un seul e-mail par jour**, à 19 h, avec toutes les offres de la journée. S'il n'y a rien de nouveau, tu ne reçois rien.

Une fois que tu as traité toutes les offres d'un e-mail, **ferme l'issue** : la liste des issues ouvertes devient ta liste d'offres à traiter.

Welcome to the Jungle et l'APEC bloquent les robots, donc ils ne sont pas couverts directement.

## Ce qui est public
Le dépôt est public (GitHub Actions y est gratuit et illimité). Seuls le code, les mots-clés de recherche et les offres trouvées (les issues) y sont visibles. Rien de personnel : pas de CV, pas d'adresse, pas de mot de passe.

## Recevoir les e-mails
Sur https://github.com/settings/notifications, vérifie que :
- **Default notifications email** est bien l'adresse où tu veux recevoir les offres ;
- dans **Participating, @mentions and custom**, la case **Email** est cochée.

## Réglages
- **Seuil de note** : change `MIN_SCORE` (6 par défaut) dans `jobwatch.py`.
- **Mots-clés** : modifie `SEARCH_TERMS` dans `jobwatch.py`.
- **Heure ou fréquence** : modifie la planification du cron « jobwatch » sur cron-job.org. Le script récupère les 30 dernières heures, donc toute fréquence d'au moins une fois par jour fonctionne.
- **Note par l'IA** (facultatif, plus précise) : ajoute les secrets `ANTHROPIC_API_KEY` et `PROFILE` (ton profil en texte).
- **France Travail** (facultatif) : ajoute les secrets `FT_CLIENT_ID` et `FT_CLIENT_SECRET` (clés gratuites sur francetravail.io).

## Tester sur le Mac
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python jobwatch.py --dry-run   # écrit preview.md sans rien créer
```
