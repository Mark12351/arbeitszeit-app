import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Arbeitszeiterfassung", layout="wide")

# ---- Google Sheets Setup ----
SHEET_NAME = "Arbeitszeit"
SHEET_TAB = "Tabelle1"
URLAUB_STAGE = 26
SOLLTAG_MINUTEN = 7 * 60 + 42  # 7 Std 42 Min

@st.cache_resource(ttl=3600, show_spinner=False)
def get_sheet():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).worksheet(SHEET_TAB)
    return sheet

def parse_ueberstunden(s):
    s = str(s).replace(" ", "")
    if s.startswith("+"):
        sign = 1
        s = s[1:]
    elif s.startswith("-"):
        sign = -1
        s = s[1:]
    else:
        sign = 1
    if ":" in s:
        h, m = map(int, s.split(":"))
        return sign * (h * 60 + m)
    return 0

def minuten_to_zeit(minuten):
    vorzeichen = ""
    if minuten < 0:
        vorzeichen = "-"
        minuten = abs(minuten)
    return f"{vorzeichen}{minuten // 60}:{str(minuten % 60).zfill(2)}"

def zeit_to_minuten(zeit):
    try:
        h, m = map(int, str(zeit).split(":"))
        return h * 60 + m
    except:
        return 0

def is_wochenende(datum):
    try:
        jahr, monat, tag = map(int, datum.split("-"))
        wtag = datetime(jahr, monat, tag).weekday()
        return wtag >= 5
    except:
        return False

def recalc_balances(df):
    df_user = df.copy()
    balance = 0
    urlaub = 0
    freizeit = 0
    for i, row in df_user.iterrows():
        u = str(row["Urlaub"])
        f = str(row["Freizeitausgleich"]) if "Freizeitausgleich" in row else "Nein"
        if u == "Seminar":
            continue
        if u in ["Ja", "1"]:
            urlaub += 1
        elif u == "Halb":
            urlaub += 0.5
        elif f in ["Ja", "1"]:
            balance -= SOLLTAG_MINUTEN
            freizeit += 1
        else:
            ueber = row["Ueberstunden"]
            balance += parse_ueberstunden(ueber)
    return urlaub, freizeit, balance

def user_rows(df, user):
    return df[df["Login"].str.strip() == user].copy()

# ---- Streamlit Interface ----
st.title("🕒 Arbeitszeiterfassung")

with st.form("login_form"):
    login = st.text_input("Login eingeben:", max_chars=30, placeholder="z.B. Mark")
    submitted = st.form_submit_button("Anmelden")

if 'user' not in st.session_state:
    st.session_state['user'] = None

if submitted:
    if login.strip() == "":
        st.warning("Bitte Login eingeben!")
    else:
        st.session_state['user'] = login.strip()

if st.session_state['user']:
    sheet = get_sheet()
    df = pd.DataFrame(sheet.get_all_records())
    df_user = user_rows(df, st.session_state['user'])
    df_user = df_user.sort_values(by="Datum", ascending=False).reset_index(drop=True)

    urlaub, freizeit, balance = recalc_balances(df_user)
    url_left = URLAUB_STAGE - urlaub
    vorzeichen = "+" if balance >= 0 else "-"
    st.success(
        f"**Verbleibende Urlaubstage:** {url_left} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"**Überstunden-Bilanz:** {vorzeichen}{minuten_to_zeit(abs(balance))} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"**Freizeitausgleich-Tage:** {freizeit}"
    )

    st.markdown("### Deine Einträge:")

    def pretty_urlaub(u):
        if u == "Seminar":
            return "Seminar"
        elif u in ["Ja", "1"]:
            return "Ja"
        elif u == "Halb":
            return "Halb"
        else:
            return "Nein"

    # Таблица пользователя
    show_df = df_user.copy()
    if not show_df.empty:
        show_df["Urlaub"] = show_df["Urlaub"].apply(pretty_urlaub)
        show_df["Freizeitausgleich"] = show_df.get("Freizeitausgleich", "Nein")
        st.dataframe(
            show_df[["Datum", "Start", "Ende", "Pause", "Gearbeitet", "Ueberstunden", "Urlaub", "Freizeitausgleich"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Noch keine Einträge vorhanden.")

    st.markdown("---")
    st.header("Neuer / Bearbeiten Eintrag")

    edit_mode = False
    selected_row = None

    if not df_user.empty:
        edit_datum = st.selectbox(
            "Vorhandenen Tag bearbeiten/löschen:",
            ["Neuer Tag"] + df_user["Datum"].tolist()
        )
        if edit_datum != "Neuer Tag":
            edit_mode = True
            selected_row = df_user[df_user["Datum"] == edit_datum].iloc[0]
    else:
        edit_datum = "Neuer Tag"

    # --- Form ---
    with st.form("add_edit"):
        datum = st.text_input("Datum (JJJJ-MM-TT)", value=selected_row["Datum"] if edit_mode else datetime.now().strftime("%Y-%m-%d"))
        col1, col2 = st.columns(2)
        with col1:
            start = st.text_input("Start (hh:mm)", value=selected_row["Start"] if edit_mode else "")
        with col2:
            ende = st.text_input("Ende (hh:mm)", value=selected_row["Ende"] if edit_mode else "")

        pause = st.text_input("Pause (Minuten)", value=str(selected_row["Pause"]) if edit_mode else "0")
        col3, col4 = st.columns(2)
        urlaub = st.checkbox("Urlaubstag", value=(selected_row["Urlaub"]=="Ja") if edit_mode else False)
        halburlaub = st.checkbox("Halber Urlaubstag", value=(selected_row["Urlaub"]=="Halb") if edit_mode else False)
        seminar = st.checkbox("Seminartag", value=(selected_row["Urlaub"]=="Seminar") if edit_mode else False)
        freizeit = st.checkbox("Freizeitausgleich", value=(selected_row.get("Freizeitausgleich","Nein")=="Ja") if edit_mode else False)

        submit = st.form_submit_button("Speichern")
        delete = st.form_submit_button("Löschen") if edit_mode else False

    # --- Обработка формы ---
    if submit:
        if urlaub and halburlaub:
            st.error("Nicht beides: voller und halber Urlaubstag!")
        elif seminar and (urlaub or halburlaub or freizeit):
            st.error("Seminartag kann nicht mit Urlaub/Freizeitausgleich kombiniert werden!")
        else:
            try:
                pause_min = int(pause)
            except:
                pause_min = 0

            if seminar:
                gearbeitet = minuten_to_zeit(SOLLTAG_MINUTEN)
                ueberstunden = "0:00"
                urlaub_speicher = "Seminar"
            elif urlaub:
                gearbeitet = "0:00"
                ueberstunden = "0:00"
                urlaub_speicher = "Ja"
            elif halburlaub:
                gearbeitet = "0:00"
                ueberstunden = "0:00"
                urlaub_speicher = "Halb"
            elif freizeit:
                gearbeitet = "0:00"
                ueberstunden = "0:00"
                urlaub_speicher = "Nein"
            else:
                try:
                    start_min = zeit_to_minuten(start)
                    ende_min = zeit_to_minuten(ende)
                except:
                    st.error("Falsches Format bei Start/Ende!")
                    st.stop()
                gearb_min = max(0, ende_min - start_min - pause_min)
                gearbeitet = minuten_to_zeit(gearb_min)
                if is_wochenende(datum):
                    ueber_min = gearb_min
                else:
                    ueber_min = gearb_min - SOLLTAG_MINUTEN
                ueberstunden = f"+{minuten_to_zeit(ueber_min)}" if ueber_min > 0 else minuten_to_zeit(ueber_min)
                urlaub_speicher = "Nein"

            # Проверка отпускных дней (суммирует Ja и Halb)
            if urlaub or halburlaub:
                urlaub_sum = 0
                for _, row in user_rows(df, st.session_state['user']).iterrows():
                    uv = str(row.get("Urlaub", "Nein"))
                    if uv in ["1", "Ja"]:
                        urlaub_sum += 1
                    elif uv == "Halb":
                        urlaub_sum += 0.5
                add_uv = 1 if urlaub else 0.5
                if edit_mode:
                    prev_uv = selected_row["Urlaub"]
                    if prev_uv == "Ja" and not urlaub:
                        urlaub_sum -= 1
                    if prev_uv == "Halb" and not halburlaub:
                        urlaub_sum -= 0.5
                if urlaub_sum + add_uv > URLAUB_STAGE:
                    st.error("Urlaubstage-Limit überschritten!")
                    st.stop()

            new_row = [datum, st.session_state['user'], start, ende, pause, gearbeitet, ueberstunden, urlaub_speicher, "Ja" if freizeit else "Nein"]

            # Обновление или добавление строки
            all_rows = sheet.get_all_records()
            updated = False
            for idx, row in enumerate(all_rows):
                if str(row["Login"]).strip() == st.session_state['user'] and row["Datum"] == datum:
                    sheet.update(f"B{idx+2}:J{idx+2}", [new_row[1:]])  # обновить существующую строку
                    updated = True
                    break
            if not updated:
                sheet.append_row(new_row)
            st.success("Gespeichert!")
            st.rerun()

    if edit_mode and delete:
        all_rows = sheet.get_all_records()
        for idx, row in enumerate(all_rows):
            if str(row["Login"]).strip() == st.session_state['user'] and row["Datum"] == edit_datum:
                sheet.delete_rows(idx + 2)
                break
        st.success("Gelöscht!")
        st.rerun()

    st.button("Abmelden", on_click=lambda: st.session_state.clear())
