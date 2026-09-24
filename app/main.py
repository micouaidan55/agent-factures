"""Point d'entrée Streamlit : navigation en haut de page, avec le journal en menu déroulant."""

import streamlit as st

from agent_factures import web

st.set_page_config(page_title="Agent factures", page_icon="🧾", layout="wide")
web.render_model_selector()

page = st.navigation(
    {
        "": [
            st.Page("app_pages/traiter.py", title="Traiter", icon=":material/upload_file:", default=True),
            st.Page("app_pages/tableau_de_bord.py", title="Tableau de bord", icon=":material/dashboard:"),
        ],
        "Journal": [
            st.Page("app_pages/journal_a_payer.py", title="À payer", icon=":material/schedule:"),
            st.Page("app_pages/journal_retard.py", title="Échéance dépassée", icon=":material/warning:"),
            st.Page("app_pages/journal_clients.py", title="Clients impayés", icon=":material/group:"),
            st.Page("app_pages/journal_payees.py", title="Payées", icon=":material/check_circle:"),
            st.Page("app_pages/journal_historique.py", title="Historique", icon=":material/history:"),
        ],
    },
    position="top",
)

st.title("Agent factures")
st.caption("Extraction, contrôle et suivi de vos factures. Rien n'est enregistré sans votre validation.")
st.header(page.title)
page.run()
