# Agent factures

**Un agent IA qui lit vos factures, en extrait les données, repère les erreurs et prépare les relances clients, sous votre contrôle.**

Dans une PME, saisir et vérifier les factures prend plusieurs heures par semaine : recopier les montants, repérer les doublons, surveiller ce qu'il reste à payer aux fournisseurs et à encaisser auprès des clients. Cet agent fait le travail préparatoire, et un humain valide chaque pièce en quelques secondes.

<!-- Ajouter ici un GIF de démo : docs/demo.gif -->

## Ce que fait l'agent

1. **Lit** les factures et devis en PDF ou en image (y compris des scans).
2. **Extrait** l'émetteur, le destinataire, le sens (facture reçue d'un fournisseur ou émise vers un client), le numéro, les dates, les montants HT, TVA et TTC, et les lignes de détail.
3. **Vérifie** la cohérence des montants, les doublons, les montants inhabituels pour un fournisseur et les échéances dépassées.
4. **Explique** son verdict en langage clair : ✅ OK, ⚠️ anomalie ou ❓ à revoir.
5. **Attend votre validation** avant d'enregistrer quoi que ce soit.
6. **Prépare un brouillon de relance** pour les clients en retard de paiement, et signale les factures fournisseurs à régler. Rien n'est jamais envoyé automatiquement.

## Résultats mesurés

Évaluation sur 20 documents fictifs (mises en page variées, un scan, des doublons, des erreurs de TVA volontaires, des devis et un courrier hors sujet) :

Voir `evals/results/`. Pour reproduire : `uv run python -m evals.run --model claude-sonnet-5`.

## Démarrage rapide

```bash
git clone <url-du-dépôt> && cd agent-factures
cp .env.example .env        # puis renseigner ANTHROPIC_API_KEY (et COMPANY_NAME, le nom de votre entreprise)
uv sync
uv run streamlit run app/main.py
```

Des documents d'exemple se trouvent dans `evals/dataset/` : déposez-les dans l'interface ou copiez-les dans `inbox/`.

## Architecture

```
PDF / image ──► InvoiceAgent (boucle agentique) ──► verdict + extraction ──► validation humaine ──► SQLite
                     │  ▲
         tool_use    ▼  │  tool_result
                 ToolExecutor ──► check_amounts · check_due_date · find_duplicates · get_supplier_history
                                  (lecture seule)
```

| Module | Rôle |
|---|---|
| `agent_factures.extraction` | Modèles Pydantic (`Invoice`, `Verdict`, `Issue`) |
| `agent_factures.agent` | Boucle agentique écrite à la main sur l'API Messages de Claude, exécuteur d'outils, chargement des documents |
| `agent_factures.tools` | Vérifications déterministes et brouillon de relance |
| `agent_factures.storage` | SQLite, journal d'actions, exports CSV et Excel |
| `app/` | Interface Streamlit |
| `evals/` | Génération du jeu de test et mesure de la précision |

### Choix de conception

- **Boucle agentique manuelle plutôt qu'un framework** : environ 140 lignes lisibles, avec un contrôle total des garde-fous.
- **L'agent ne peut rien écrire** : il ne dispose que d'outils en lecture seule. L'enregistrement est une action humaine.
- **Contrôles déterministes en code, jugement par le LLM** : les calculs (TVA, doublons, seuils) sont faits par du code testé. Claude décide quoi vérifier et explique le résultat. Un verdict « OK » est automatiquement requalifié si un contrôle a détecté un problème. Le code garantit aussi l'exécution des quatre contrôles (montants, échéance, doublons, historique fournisseur) même si le modèle en oublie un : ceux qui manquent sont relancés avant le verdict final.
- **Garde-fous** : 10 itérations maximum par document, une seule nouvelle tentative en cas d'extraction invalide, coût en tokens affiché pour chaque document.
- **Testé sans API** : la suite pytest utilise un client factice et ne consomme aucun crédit.

## Tests

```bash
uv run pytest
```

## Limites connues et feuille de route

- Pas encore de connexion à une boîte mail (Gmail ou IMAP).
- Pas de suivi des paiements : les totaux « à payer » et « à encaisser » portent sur toutes les factures enregistrées.
- Mono-utilisateur, sans authentification.
- Prochaines étapes : tri automatique des emails entrants, relances clients, option de modèle local pour les données sensibles.
