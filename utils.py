import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
from data_models import SportType
import io

# --- SISTEMA DI PROTEZIONE (LOGIN) ---
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
    Legge file CSV/Excel da metabolimetro.
    Versione ROBUSTA: Sniffa il separatore, trova l'header e pulisce i nomi delle colonne.
    """
    try:
        df = None
        
        # 1. Gestione CSV con Header Variabile
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            content = uploaded_file.getvalue().decode('utf-8', errors='replace')
            lines = content.split('\n')
            
            # Cerca la riga di intestazione (quella che contiene "CHO" e "FAT")
            header_row = 0
            header_line = ""
            for i, line in enumerate(lines[:200]): 
                if "CHO" in line.upper() and "FAT" in line.upper():
                    header_row = i
                    header_line = line
                    break
            
            # Sniffing del separatore dalla riga di header trovata
            sep = ',' # Default
            if header_line:
                if ';' in header_line and header_line.count(';') > header_line.count(','):
                    sep = ';'
                elif '\t' in header_line:
                    sep = '\t'
            
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal='.')
            except:
                uploaded_file.seek(0)
                # Fallback: prova decimale con virgola
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal=',')
                
        # 2. Gestione Excel
        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            return None, None, "Formato file non supportato. Usa CSV o Excel."

        if df is None or df.empty:
            return None, None, "Il file sembra vuoto o non leggibile."

        # 3. Normalizzazione Colonne
        # Rimuove spazi e converte in maiuscolo per la ricerca
        df.columns = [str(c).strip().upper() for c in df.columns]
        cols = df.columns.tolist()
        col_map = {}
        
        # Funzione helper di ricerca
        def find_col(keywords):
            for c in cols:
                for k in keywords:
                    # Match esatto o "parola contenuta"
                    if k == c or (k in c and len(c) < len(k)+5): # Evita match spuri su stringhe lunghe
                        return c
            return None

        # Mappatura
        col_map['CHO'] = find_col(['CHO', 'CHO (G/H)', 'CARBOHYDRATES'])
        col_map['FAT'] = find_col(['FAT', 'FAT (G/H)', 'LIPIDS'])
        
        # Intensità (Priorità: Watt -> Speed -> FC)
        watt_c = find_col(['WR', 'WATT', 'WATTS', 'POWER', 'POW'])
        speed_c = find_col(['SPEED', 'VEL', 'KM/H', 'V'])
        fc_c = find_col(['FC', 'HR', 'HEART RATE', 'BPM'])
        
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

        # Verifica Errori Mappatura
        missing = []
        if 'CHO' not in col_map or not col_map['CHO']: missing.append("CHO")
        if 'FAT' not in col_map or not col_map['FAT']: missing.append("FAT")
        if 'Intensity' not in col_map: missing.append("Intensità (Watt/FC/Vel)")
        
        if missing:
            found_cols_str = ", ".join(cols[:10]) + "..."
            return None, None, f"Colonne mancanti: {', '.join(missing)}. Colonne trovate nel file: [{found_cols_str}]"

        # 4. Creazione DataFrame Pulito
        clean_df = df[list(col_map.values())].rename(columns={v: k for k, v in col_map.items()})
        
        # Conversione numerica forzata
        for c in clean_df.columns:
            clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        # 5. Verifica Unità di Misura (g/min -> g/h)
        # Se il consumo max di CHO è < 10, probabilmente sono g/min -> convertire a g/h
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None

    except Exception as e:
        return None, None, f"Errore tecnico lettura file: {str(e)}"

# --- LOGICA DI PARSING ZWO ---
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

# --- FUNZIONI ZONE ---
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
