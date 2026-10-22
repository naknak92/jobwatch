"""Veille d'offres Data Scientist / Data Analyst en Île-de-France.

Collecte les nouvelles offres (LinkedIn, Indeed, Glassdoor, HelloWork, France Travail
en option), les note par rapport au profil, et envoie un e-mail récapitulatif avec
les meilleures sous forme d'issues GitHub (GitHub les envoie par e-mail). Les offres déjà vues sont mémorisées dans seen.json.

Usage :
    python jobwatch.py            # collecte + création des issues
    python jobwatch.py --dry-run  # collecte + aperçu dans preview.md, sans rien créer
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen.json"
PROFILE_FILE = ROOT / "profile.md"

SEARCH_TERMS = [
    "data scientist", "data analyst", "machine learning engineer", "analytics engineer",
    "business intelligence", "ingénieur IA",
]
MIN_SCORE = int(os.environ.get("MIN_SCORE", "6"))
# Fenêtre de recherche : un passage par jour, donc 30 h pour avoir de la marge
HOURS_OLD = int(os.environ.get("HOURS_OLD", "30"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# Offres écartées d'office (titre)
EXCLUDE_TITLE = re.compile(r"\b(stage|stagiaire|intern(ship)?|intership|alternan\w*|apprenti\w*|th[eè]se|doctora\w*|postdoc\w*|post-doc\w*)\b", re.I)
# Le titre doit parler de data
DATA_TITLE = re.compile(r"data|donn[ée]es|machine learning|\bml\b|\bia\b|\bai\b|analyst|analyste|analytics|scientist|\bbi\b|business intelligence|statisti", re.I)
SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|principal|head|manager|director|directeur|chef|staff|expert)\b", re.I)
JUNIOR_TITLE = re.compile(r"\b(junior|jr\.?|confirm[ée]|d[ée]butant|graduate)\b", re.I)

SKILLS = {
    "python": 1.0, "sql": 1.0, "machine learning": 1.0, "scikit": 0.5, "pytorch": 0.5,
    "tensorflow": 0.5, "spark": 0.7, "nlp": 0.7, "llm": 0.7, "rag": 0.7, "genai": 0.5,
    "ia générative": 0.5, "tableau": 0.7, "power bi": 0.7, "powerbi": 0.7, "gcp": 0.5,
    "bigquery": 0.5, "aws": 0.4, "azure": 0.4, "docker": 0.3, "mlops": 0.5, "pandas": 0.4,
    "dashboard": 0.4, "statisti": 0.4, "télécom": 0.5, "telecom": 0.5, "hadoop": 0.3,
}


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def job_id(job):
    # même offre publiée sur plusieurs sites : titre + début du nom de l'entreprise
    words = re.sub(r"[^a-z0-9]+", " ", norm(job["title"])).split()
    title = "".join(w for w in words if w not in {"h", "f", "m", "x", "cdi"})
    company = re.sub(r"[^a-z0-9]", "", norm(job["company"]))[:5]
    key = title + "|" + company
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- sources

def from_jobspy(hours_old):
    from jobspy import scrape_jobs

    jobs = []
    for term in SEARCH_TERMS:
        for site, location in [("linkedin", "Paris, Île-de-France, France"),
                               ("indeed", "Île-de-France"),
                               ("glassdoor", "Paris, France")]:
            try:
                df = scrape_jobs(site_name=[site], search_term=term, location=location,
                                 distance=50, results_wanted=100, hours_old=hours_old,
                                 country_indeed="france", linkedin_fetch_description=False)
            except Exception as e:
                print(f"[{site}] erreur : {e}", file=sys.stderr)
                continue
            for r in df.fillna("").to_dict("records"):
                jobs.append({
                    "source": site.capitalize(), "title": str(r.get("title", "")),
                    "company": str(r.get("company", "")), "location": str(r.get("location", "")),
                    "url": str(r.get("job_url", "")), "description": str(r.get("description", ""))[:6000],
                    "contract": str(r.get("job_type", "")),
                })
            time.sleep(2)
    return jobs


def from_hellowork():
    jobs = []
    url = "https://www.hellowork.com/fr-fr/emploi/recherche.html"
    for term in SEARCH_TERMS:
        for page in range(1, 6):
            # d=h : publiées depuis 24 h ; st=date : les plus récentes d'abord
            try:
                r = requests.get(url, params={"k": term, "l": "Île-de-France", "d": "h", "st": "date", "p": page},
                                 headers={"User-Agent": UA}, timeout=30)
                r.raise_for_status()
            except Exception as e:
                print(f"[hellowork] erreur : {e}", file=sys.stderr)
                break
            links = BeautifulSoup(r.text, "html.parser").select('a[data-cy="offerTitle"]')
            for a in links:
                title_company = a.get("title", "")
                title, _, company = title_company.rpartition(" - ")
                label = a.get("aria-label", "")
                m = re.search(r" à (.+?), chez", label)
                jobs.append({
                    "source": "HelloWork", "title": title or title_company, "company": company,
                    "location": m.group(1) if m else "", "url": "https://www.hellowork.com" + a["href"],
                    "description": label, "contract": "",
                })
            time.sleep(2)
            if len(links) < 20:
                break
    return jobs


def from_france_travail():
    cid, secret = os.environ.get("FT_CLIENT_ID"), os.environ.get("FT_CLIENT_SECRET")
    if not (cid and secret):
        return []
    try:
        tok = requests.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token",
            params={"realm": "/partenaire"},
            data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
                  "scope": "api_offresdemploiv2 o2dsoffre"}, timeout=30).json()["access_token"]
    except Exception as e:
        print(f"[france travail] auth : {e}", file=sys.stderr)
        return []
    jobs = []
    for term in SEARCH_TERMS:
        try:
            r = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
                             headers={"Authorization": f"Bearer {tok}"},
                             params={"motsCles": term, "region": "11", "publieeDepuis": 1, "range": "0-149"},
                             timeout=30)
            if r.status_code == 204:
                continue
            r.raise_for_status()
        except Exception as e:
            print(f"[france travail] {e}", file=sys.stderr)
            continue
        for o in r.json().get("resultats", []):
            jobs.append({
                "source": "France Travail", "title": o.get("intitule", ""),
                "company": (o.get("entreprise") or {}).get("nom", ""),
                "location": (o.get("lieuTravail") or {}).get("libelle", ""),
                "url": (o.get("origineOffre") or {}).get("urlOrigine")
                       or f"https://candidat.francetravail.fr/offres/recherche/detail/{o.get('id')}",
                "description": o.get("description", "")[:6000], "contract": o.get("typeContratLibelle", ""),
            })
    return jobs


def add_linkedin_description(job):
    """Récupère la description d'une offre LinkedIn (seulement pour les nouvelles, pour rester discret)."""
    m = re.search(r"/view/(\d+)", job["url"])
    if job["source"] != "Linkedin" or job["description"] or not m:
        return
    try:
        r = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}",
                         headers={"User-Agent": UA}, timeout=20)
        div = BeautifulSoup(r.text, "html.parser").select_one(".show-more-less-html__markup")
        if div:
            job["description"] = div.get_text(" ", strip=True)[:6000]
    except Exception as e:
        print(f"[linkedin] description : {e}", file=sys.stderr)
    time.sleep(1)


# ---------------------------------------------------------------- notation

def keyword_score(job):
    title, text = norm(job["title"]), norm(job["title"] + " " + job["description"])
    score = 3.0
    if re.search(r"data scien|machine learning|ml engineer|\bia\b|\bai\b", title):
        score += 3
    elif re.search(r"data analy|analyste|analytics|business intelligence|\bbi\b", title):
        score += 3
    elif "data" in title:
        score += 1
    hits = [k for k in SKILLS if re.search(r"\b" + re.escape(norm(k)), text)]
    score += min(3.0, sum(SKILLS[k] for k in hits) / 2)
    if SENIOR_TITLE.search(job["title"]):
        score -= 2.5
    if JUNIOR_TITLE.search(job["title"]):
        score += 0.5
    if re.search(r"\b([5-9]|1[0-9])\s*\+?\s*(ans|years)", text):
        score -= 1.5
    score = max(0, min(10, round(score)))
    plus = ", ".join(hits[:6]) or "peu de compétences citées"
    moins = []
    if SENIOR_TITLE.search(job["title"]):
        moins.append("poste senior/lead")
    if re.search(r"\b([5-9]|1[0-9])\s*\+?\s*(ans|years)", text):
        moins.append("beaucoup d'expérience demandée")
    return score, f"✔ {plus}" + (f" · ✖ {', '.join(moins)}" if moins else "")


def llm_score(jobs):
    """Note les offres avec Claude si ANTHROPIC_API_KEY est défini, sinon par mots-clés."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    # le profil peut venir d'un secret GitHub (PROFILE) pour ne pas le publier dans le dépôt
    profile = os.environ.get("PROFILE") or (PROFILE_FILE.read_text(encoding="utf-8") if PROFILE_FILE.exists() else "")
    if not profile:
        key = None
    for job in jobs:
        job["score"], job["why"] = keyword_score(job)
        if not key:
            continue
        prompt = (
            f"Profil du candidat :\n{profile}\n\nOffre :\nTitre : {job['title']}\nEntreprise : {job['company']}\n"
            f"Lieu : {job['location']}\nContrat : {job['contract']}\n{job['description'][:4000]}\n\n"
            "Note de 0 à 10 l'adéquation de cette offre avec le profil (niveau d'expérience, compétences, "
            "métier). Réponds uniquement en JSON : "
            '{"score": <entier>, "why": "<une phrase courte en français : points forts ✔ et points faibles ✖>"}'
        )
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-5-5", "max_tokens": 200,
                      "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            out = r.json()["content"][0]["text"]
            data = json.loads(out[out.index("{"): out.rindex("}") + 1])
            job["score"], job["why"] = int(data["score"]), str(data["why"])
        except Exception as e:
            print(f"[claude] {job['title']} : {e}", file=sys.stderr)
    return jobs


# ---------------------------------------------------------------- notification (issues GitHub)
# Chaque offre devient une issue du dépôt, assignée au propriétaire : GitHub envoie alors
# automatiquement un e-mail sur l'adresse du compte, sans aucun mot de passe à fournir.

# Jusqu'à ce nombre d'offres, l'e-mail détaille chaque offre ; au-delà, un tableau compact.
MAX_DETAILED = 10


def offer_markdown(j):
    contract = f" · {j['contract']}" if j["contract"] else ""
    return (f"### {j['title']}\n**{j['score']}/10** — {j['company']} · {j['location']}{contract} · _{j['source']}_\n\n"
            f"{j['why']}\n\n👉 **[Voir l'annonce et postuler]({j['url']})**")


def digest_markdown(jobs):
    if len(jobs) <= MAX_DETAILED:
        return "\n\n---\n\n".join(offer_markdown(j) for j in jobs)
    lines = ["| Note | Offre | Entreprise | Lieu | Site |", "|---|---|---|---|---|"]
    for j in jobs:
        t = j["title"].replace("|", "/")
        lines.append(f"| {j['score']}/10 | [{t}]({j['url']}) | {j['company']} | {j['location']} | {j['source']} |")
    return "\n".join(lines)


def create_issue(title, body):
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    owner = repo.split("/")[0]
    r = requests.post(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                      json={"title": title[:250], "body": body, "assignees": [owner]})
    r.raise_for_status()


def notify(jobs, dry_run):
    """Une seule issue (donc un seul e-mail) par passage, avec toutes les nouvelles offres."""
    top = jobs[0]
    if len(jobs) == 1:
        title = f"🔔 {top['score']}/10 · {top['title']} · {top['company']}"
    else:
        title = f"🔔 {len(jobs)} offres · {top['title']} ({top['score']}/10)…"
    body = digest_markdown(jobs)
    if dry_run:
        (ROOT / "preview.md").write_text(f"## {title}\n\n{body}", encoding="utf-8")
        print("Aperçu écrit dans preview.md")
        return
    create_issue(title, body)
    print("1 issue créée")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ne rien créer, écrire preview.md")
    args = ap.parse_args()

    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}

    raw = from_jobspy(HOURS_OLD) + from_hellowork() + from_france_travail()
    new, ids = [], set()
    for job in raw:
        if not job["title"] or EXCLUDE_TITLE.search(job["title"]) or not DATA_TITLE.search(job["title"]):
            continue
        jid = job_id(job)
        if jid in seen or jid in ids:
            continue
        ids.add(jid)
        new.append(job)
    print(f"{len(raw)} offres collectées, {len(new)} nouvelles")
    for job in new:
        add_linkedin_description(job)

    scored = sorted(llm_score(new), key=lambda j: -j["score"])
    good = [j for j in scored if j["score"] >= MIN_SCORE]
    print(f"{len(good)} offres au-dessus de {MIN_SCORE}/10")

    if good:
        notify(good, args.dry_run)

    if not args.dry_run:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for j in new:
            seen[job_id(j)] = now
        # on oublie les offres de plus de 60 jours pour garder le fichier léger
        cutoff = time.time() - 60 * 86400
        seen = {k: v for k, v in seen.items() if datetime.fromisoformat(v).timestamp() > cutoff}
        SEEN_FILE.write_text(json.dumps(seen, indent=0))


if __name__ == "__main__":
    main()
