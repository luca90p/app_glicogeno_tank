import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
from data_models import SportType

def check_password():
    """Gestisce l'autenticazione semplice tramite session state."""
    def password_entered():
        if st.session_state["password"] == "glicogeno2025": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]  
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Inserisci Password di Accesso", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Inserisci Password di Accesso", type="password", on_change=password_entered, key="password")
        st.error("Password errata.")
        return False
    else:
        return True

# --- PARSING FILE METABOLICO (TEST LAB) ---
def parse_metabolic_report(uploaded_file):
    """
    Legge file CSV/Excel da metabolimetro e estrae la curva metabolica.
    Cerca colonne chiave come 'CHO', 'FAT', 'Watt'/'WR', 'FC'/'HR'.
    """
    try:
        # 1. Lettura File (Gestione header variabile)
        if uploaded_file.name.endswith('.csv'):
            # Tentativo di lettura intelligente per CSV
            # Leggiamo le prime righe per trovare l'header
            content = uploaded_file.getvalue().decode('utf-8', errors='replace')
            lines = content.split('\n')
            header_row = 0
            
            # Cerca la riga che contiene sia "CHO" che "FAT"
            for i, line in enumerate(lines[:200]): 
                if "CHO" in line and "FAT" in line:
                    header_row = i
                    break
            
            uploaded_file.seek(0)
            
            # Proviamo a leggere con diversi separatori/decimali
            try:
                # Tenta separatore automatico
                df = pd.read_csv(uploaded_file, header=header_row, sep=None, engine='python', decimal=',')
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=header_row, sep=None, engine='python', decimal='.')
        else:
            # Excel
            df = pd.read_excel(uploaded_file)
            
        # 2. Mappatura Colonne (Normalizzazione)
        # Convertiamo tutto in maiuscolo per la ricerca
        cols = df.columns.tolist()
        col_map = {}
        
        # Funzione helper per cercare colonne
        def find_col(keywords):
            for c in cols:
                c_str = str(c).upper()
                for k in keywords:
                    if k in c_str:
                        return c
            return None

        # Cerca CHO (preferenza g/h, poi g/min, poi solo CHO)
        cho_c = find_col(['CHO (G/H)', 'CHO G/H']) 
        if not cho_c: cho_c = find_col(['CHO'])
        if cho_c: col_map['CHO'] = cho_c
        
        # Cerca FAT
        fat_c = find_col(['FAT (G/H)', 'FAT G/H'])
        if not fat_c: fat_c = find_col(['FAT'])
        if fat_c: col_map['FAT'] = fat_c
        
        # Cerca Intensità
        # Priorità: Watt > Velocità > FC
        watt_c = find_col(['WR', 'WATT', 'POWER'])
        speed_c = find_col(['SPEED', 'VEL', 'KM/H', ' V ']) # ' V ' con spazi per evitare match parziali errati
        fc_c = find_col(['FC', 'HR', 'HEART', 'BPM'])
        
        intensity_type = None
        if watt_c:
            col_map['Intensity'] = watt_c
            intensity_type = 'watt'
        elif speed_c:
            col_map['Intensity'] = speed_c
            intensity_type = 'speed'
        elif fc_c:
            col_map['Intensity'] = fc_c
            intensity_type = 'hr'
        else:
            return None, None, "Colonna Intensità (Watt, Speed o FC) non trovata nel file."

        if 'CHO' not in col_map or 'FAT' not in col_map:
            return None, None, "Colonne CHO o FAT non trovate. Assicurati che il file contenga i dati di ossidazione."

        # 3. Pulizia Dati
        clean_df = df[list(col_map.values())].rename(columns={v: k for k, v in col_map.items()})
        
        # Conversione in numerico e drop errori
        for c in clean_df.columns:
            clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        
        clean_df.dropna(inplace=True)
        # Rimuovi righe con intensità zero o negativa
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        # 4. Verifica unità di misura
        # Se i valori max di CHO sono < 10, probabilmente sono g/min -> convertire a g/h
        if clean_df['CHO'].max() < 10: 
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None

    except Exception as e:
        return None, None, f"Errore durante la lettura del file: {str(e)}"

def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    """Esegue il parsing di file XML formato ZWO (Zwift Workout)."""
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
    except Exception as e:
        st.error(f"Errore critico nel parsing XML: {e}")
        return [], 0, 0, 0

    # Verifica congruenza sport
    zwo_sport_tag = root.findtext('sportType')
    if zwo_sport_tag:
        is_bike_file = zwo_sport_tag.lower() == 'bike'
        is_run_file = zwo_sport_tag.lower() == 'run'
        
        if is_bike_file and sport_type != SportType.CYCLING:
            st.warning(f"Attenzione: File strutturato per BICI caricato su profilo {sport_type.label}.")
        elif is_run_file and sport_type != SportType.RUNNING:
            st.warning(f"Attenzione: File strutturato per CORSA caricato su profilo {sport_type.label}.")

    intensity_series = [] 
    total_duration_sec = 0
    total_weighted_if = 0
    
    # Estrazione segmenti SteadyState
    for steady_state in root.findall('.//SteadyState'):
        try:
            duration_sec = int(steady_state.get('Duration'))
            power_ratio = float(steady_state.get('Power'))
            
            # Approssimazione al minuto per la simulazione metabolica
            duration_min_segment = math.ceil(duration_sec / 60)
            intensity_factor = power_ratio 
            
            for _ in range(duration_min_segment):
                intensity_series.append(intensity_factor)
            
            total_duration_sec += duration_sec
            total_weighted_if += intensity_factor * (duration_sec / 60) 

        except ValueError:
            continue

    total_duration_min = math.ceil(total_duration_sec / 60)
    avg_power = 0
    avg_hr = 0

    if total_duration_min > 0:
        avg_if = total_weighted_if / total_duration_min
        
        if sport_type == SportType.CYCLING:
            avg_power = avg_if * ftp_watts
        elif sport_type == SportType.RUNNING:
            avg_hr = avg_if * thr_hr
        else: 
            max_hr_ref = st.session_state.get('max_hr_input', 185)
            avg_hr = avg_if * max_hr_ref * 0.85 
            
        return intensity_series, total_duration_min, avg_power, avg_hr
    
    return [], 0, 0, 0

def calculate_zones_cycling(ftp):
    return [
        {"Zona": "Z1 - Recupero Attivo", "Range %": "< 55%", "Valore": f"< {int(ftp*0.55)} W"},
        {"Zona": "Z2 - Endurance", "Range %": "56 - 75%", "Valore": f"{int(ftp*0.56)} - {int(ftp*0.75)} W"},
        {"Zona": "Z3 - Tempo", "Range %": "76 - 90%", "Valore": f"{int(ftp*0.76)} - {int(ftp*0.90)} W"},
        {"Zona": "Z4 - Soglia (FTP)", "Range %": "91 - 105%", "Valore": f"{int(ftp*0.91)} - {int(ftp*1.05)} W"},
        {"Zona": "Z5 - VO2max", "Range %": "106 - 120%", "Valore": f"{int(ftp*1.06)} - {int(ftp*1.20)} W"},
        {"Zona": "Z6 - Capacità Anaerobica", "Range %": "121 - 150%", "Valore": f"{int(ftp*1.21)} - {int(ftp*1.50)} W"},
    ]

def calculate_zones_running_hr(thr):
    return [
        {"Zona": "Z1 - Recupero", "Range %": "< 85% LTHR", "Valore": f"< {int(thr*0.85)} bpm"},
        {"Zona": "Z2 - Aerobico", "Range %": "85 - 89% LTHR", "Valore": f"{int(thr*0.85)} - {int(thr*0.89)} bpm"},
        {"Zona": "Z3 - Tempo", "Range %": "90 - 94% LTHR", "Valore": f"{int(thr*0.90)} - {int(thr*0.94)} bpm"},
        {"Zona": "Z4 - Sub-Soglia", "Range %": "95 - 99% LTHR", "Valore": f"{int(thr*0.95)} - {int(thr*0.99)} bpm"},
        {"Zona": "Z5 - Soglia / VO2max", "Range %": "> 100% LTHR", "Valore": f"> {int(thr*1.00)} bpm"},
    ]

