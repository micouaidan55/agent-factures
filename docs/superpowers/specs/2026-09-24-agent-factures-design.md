# Agent de traitement de factures et devis — Design

**Date :** 2026-09-24
**Statut :** validé en brainstorming, en attente de relecture

## 1. Objectif

Projet de portfolio destiné à convaincre à la fois :

- **des recruteurs techniques** : qualité du code, architecture modulaire, boucle agentique maîtrisée, tests et évaluations mesurées ;
- **des clients PME** : problème métier concret (traitement des factures fournisseurs et devis), gain de temps démontrable, démo compréhensible en 30 secondes.

Il s'agit du premier projet d'une future suite d'« agents pour PME » (extensions prévues : tri des emails, relances clients).

## 2. Choix techniques

| Sujet | Choix | Raison |
|---|---|---|
| Langage | Python | Standard de l'écosystème IA, bonnes bibliothèques PDF, tableur et tests |
| LLM | Claude (API Anthropic, SDK Python officiel) | Lecture native des PDF, tool use natif, bonne extraction structurée |
| Modèle par défaut | Claude Sonnet ; Haiku en option | Fiabilité par défaut ; comparaison coût/qualité dans les evals |
| Boucle agentique | Écrite à la main avec le tool use (pas de framework) | Mécanisme compréhensible et explicable en entretien |
| Interface | Streamlit | Démo web rapide à construire, lisible par un non-technicien |
| Stockage | SQLite | Zéro configuration, suffisant pour une V1 mono-utilisateur |
| Validation | Pydantic | Schéma strict pour les données extraites |
| Tests | pytest | Standard |
| Gestion de projet | uv (+ Docker Compose optionnel) | Lancement en une commande |

## 3. Périmètre V1

### Inclus

1. Dépôt de factures et devis (PDF, PNG, JPG) via l'interface Streamlit ou le dossier `inbox/`.
2. Extraction des champs : fournisseur, type de document (facture/devis), numéro, date d'émission, date d'échéance, montants HT, TVA et TTC, devise, lignes de détail (libellé, quantité, prix unitaire, total).
3. Vérifications :
   - cohérence HT + TVA = TTC (tolérance d'arrondi : 0,02 €) ;
   - cohérence de la somme des lignes avec le HT ;
   - doublon : même fournisseur **et** même numéro de document déjà en base ;
   - montant inhabituel : TTC supérieur à 3 fois la moyenne des factures précédentes du même fournisseur (seulement s'il existe au moins 3 factures d'historique) ;
   - échéance dépassée à la date du traitement.
4. Verdict par document : `ok`, `anomalie` (avec explication en langage naturel) ou `a_revoir`.
5. Validation humaine : accepter, corriger les champs ou rejeter. **Rien n'est écrit en base avant la validation.**
6. Enregistrement dans SQLite ; export CSV et Excel.
7. Brouillon de relance pour les factures dont l'échéance est dépassée : affiché, copiable, **jamais envoyé**.
8. Tableau de bord : total restant à payer, échéances des 30 prochains jours, alertes en cours, journal des actions de l'agent, coût en tokens par document.

### Exclus (versions suivantes)

Connexion à Gmail ou IMAP, envoi réel d'emails, gestion multi-utilisateurs et authentification, modèle local, API REST.

## 4. Architecture

```
agent-factures/
├── app/            # Interface Streamlit (dépôt, validation, tableau de bord)
├── agent/          # Boucle agentique + déclaration des outils pour Claude
├── tools/          # Implémentation des outils appelés par l'agent
├── extraction/     # Schéma Pydantic Invoice + validation
├── storage/        # Accès SQLite (factures, fournisseurs, journal)
├── evals/          # Jeu de factures fictives, valeurs attendues, script de mesure
├── tests/          # Tests pytest
├── inbox/          # Dossier surveillé (optionnel)
└── docs/
```

Chaque module a une seule responsabilité et une interface explicite :

- **`extraction`** : définit `Invoice`, `InvoiceLine` et `Verdict` (Pydantic). Il ne dépend d'aucun autre module.
- **`storage`** : `InvoiceRepository` (`add`, `get`, `find_by_supplier_and_number`, `list_by_supplier`, `list_overdue`, `list_all`) et `ActionLog` (`record`, `list_for_document`). Il dépend uniquement de `extraction`.
- **`tools`** : des fonctions pures ou en lecture seule qui prennent un repository en paramètre (injection de dépendance, pour faciliter les tests) :
  - `check_amounts(invoice) -> list[Issue]`
  - `find_duplicates(repo, supplier, number) -> list[Invoice]`
  - `get_supplier_history(repo, supplier) -> SupplierStats`
  - `check_due_date(invoice, today) -> Issue | None`
  - `draft_reminder(invoice, today) -> str` (génère le texte de relance ; peut appeler le LLM)
- **`agent`** : `InvoiceAgent.process(document_path) -> AgentResult`. Il orchestre la boucle avec Claude, expose les outils en lecture seule et renvoie l'extraction, le verdict, les problèmes détectés, la trace des appels d'outils et l'usage en tokens. Il n'écrit **pas** en base.
- **`app`** : appelle `InvoiceAgent`, affiche le résultat, et appelle `InvoiceRepository.add` uniquement après validation humaine.

L'écriture en base (`save_invoice`) n'est donc **pas** un outil de l'agent : c'est une action de l'interface déclenchée par l'humain.

## 5. Flux de données

1. L'utilisateur dépose un document.
2. `InvoiceAgent.process` envoie le document à Claude (bloc document PDF natif, ou image), avec le prompt système et la liste des outils.
3. Claude extrait les données sous forme d'un appel à l'outil `submit_extraction`, dont le schéma d'entrée est dérivé du modèle Pydantic `Invoice`.
4. Le code valide l'extraction avec Pydantic. En cas d'échec, l'erreur est renvoyée à Claude pour **une** nouvelle tentative ; si elle échoue aussi, le verdict est `a_revoir` et les champs partiels sont conservés.
5. Claude appelle les outils de vérification qu'il juge pertinents ; le code les exécute et renvoie les résultats.
6. Claude termine par l'appel à l'outil `submit_verdict` (`ok`, `anomalie` ou `a_revoir`, avec une explication).
7. L'interface affiche l'extraction, le verdict, les problèmes et la trace des outils ; l'humain accepte, corrige ou rejette.
8. Si le document est accepté, il est enregistré en base et toutes les actions sont écrites dans le journal.
9. Si l'échéance est dépassée, un brouillon de relance est proposé.

## 6. Garde-fous

- Nombre maximal d'itérations de la boucle : 10 par document ; au-delà, arrêt et verdict `a_revoir`.
- Outils exposés à l'agent **en lecture seule** uniquement.
- Suivi des tokens (entrée et sortie) et du coût estimé par document, affiché dans l'interface.
- Clé d'API lue depuis la variable d'environnement `ANTHROPIC_API_KEY` (fichier `.env` ignoré par git, `.env.example` fourni).

## 7. Gestion des erreurs

| Cas | Comportement |
|---|---|
| Fichier illisible, ou qui n'est ni une facture ni un devis | Verdict `a_revoir` avec la raison ; pas d'exception remontée à l'utilisateur |
| Erreur d'API (réseau, 429, 5xx) | Nouvelles tentatives avec délai croissant (géré par le SDK), puis message clair dans l'interface |
| Extraction invalide | Une nouvelle tentative, puis `a_revoir` avec les champs partiels |
| Limite d'itérations atteinte | Arrêt propre, verdict `a_revoir`, événement consigné dans le journal |
| Format de fichier non supporté | Refus au dépôt avec un message clair |

## 8. Tests

- **Tests unitaires** pour `extraction`, `storage` et chaque outil : aucun appel au LLM, SQLite en mémoire.
- **Tests de la boucle agentique** avec un faux client qui renvoie des réponses scriptées. Ils vérifient l'enchaînement des outils, la nouvelle tentative sur extraction invalide, la limite d'itérations et le fait qu'aucune écriture n'a lieu en base.
- Aucun test ne consomme de crédits d'API. Les appels réels sont réservés aux evals.

## 9. Évaluations

- `evals/generate.py` génère environ 20 documents fictifs (PDF) avec leurs valeurs attendues (`evals/expected.json`) :
  - des mises en page variées ;
  - au moins une version « scannée » (image bruitée et légèrement pivotée) ;
  - 2 doublons ;
  - 2 erreurs de TVA volontaires ;
  - 1 montant anormal ;
  - 2 devis ;
  - 1 document qui n'est pas une facture.
- `evals/run.py --model <modèle>` mesure :
  - la précision par champ (correspondance exacte pour les textes normalisés, tolérance de 0,01 pour les montants) ;
  - le rappel et la précision de la détection d'anomalies ;
  - la justesse du verdict ;
  - le coût moyen et le temps moyen par document.
- Les résultats pour Sonnet et Haiku sont publiés dans le README sous forme de tableau.

## 10. Présentation portfolio

- **README** : d'abord le pitch métier (problème, gain de temps estimé, GIF de la démo), puis la partie technique (schéma d'architecture, choix justifiés, résultats des evals, limites connues, feuille de route).
- Lancement en une commande : `uv run streamlit run app/main.py`, avec les documents d'exemple fournis.
- Dépôt GitHub public avec un historique de commits lisible.

## 11. Critères de réussite

- Traitement de bout en bout d'une facture PDF dans l'interface, en moins de 30 secondes.
- Précision des champs d'au moins 90 % sur le jeu d'évaluation avec Sonnet.
- Toutes les anomalies injectées sont détectées.
- Suite de tests verte, sans clé d'API.
- Un inconnu peut cloner le dépôt et lancer la démo en moins de 5 minutes en suivant le README.
