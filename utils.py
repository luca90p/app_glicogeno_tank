import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
from data_models import SportType

# --- SISTEMA DI PROTEZIONE (LOGIN) ---
def check_password():
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
    Versione ROBUSTA 2.0: Gestione encoding, newlines e ricerca flessibile.
    """
    try:
        df = None
        
        # 1. Gestione CSV
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            bytes_data = uploaded_file.getvalue()
            
            # Tentativo decoding (utf-8 poi latin-1)
            try:
                content = bytes_data.decode('utf-8')
            except UnicodeDecodeError:
                content = bytes_data.decode('latin-1', errors='replace')
            
            # Splitlines gestisce \n, \r, \r\n automaticamente
            lines = content.splitlines()
            
            # Cerca la riga di intestazione
            header_row = None
            header_line = ""
            
            # Parole chiave per identificare l'header (maiuscolo)
            # Cerchiamo una riga che abbia senso (es. FC e Watt, oppure CHO e FAT)
            # Il tuo file ha: t, Fase, Marker... FC, WR... CHO, FAT
            search_terms = ["FC", "WR", "CHO", "FAT"]
            
            for i, line in enumerate(lines[:300]): # Cerca più a fondo
                line_upper = line.upper()
                # Criterio: deve contenere almeno 3 delle parole chiave
                matches = sum(1 for term in search_terms if term in line_upper)
                if matches >= 2: # Abbastanza sicuro
                    header_row = i
                    header_line = line
                    break
            
            if header_row is None:
                # Fallback: Cerca solo "t" e "Fase" (specifico per il tuo file)
                for i, line in enumerate(lines[:300]):
                    if line.strip().startswith("t") and "Fase" in line:
                        header_row = i
                        header_line = line
                        break

            if header_row is None:
                return None, None, "Impossibile trovare la riga di intestazione (Cercato: FC, WR, CHO, FAT)."

            # Sniffing del separatore
            sep = ',' 
            if header_line:
                semi_count = header_line.count(';')
                comm_count = header_line.count(',')
                tab_count = header_line.count('\t')
                
                if semi_count > comm_count and semi_count > tab_count: sep = ';'
                elif tab_count > comm_count: sep = '\t'
            
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal='.')
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal=',')
                
        # 2. Gestione Excel
        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            return None, None, "Formato file non supportato. Usa CSV o Excel."

        if df is None or df.empty:
            return None, None, "Il file letto è vuoto."

        # 3. Normalizzazione Colonne
        df.columns = [str(c).strip().upper() for c in df.columns]
        cols = df.columns.tolist()
        col_map = {}
        
        def find_col(keywords):
            for c in cols:
                for k in keywords:
                    if k == c or k in c: return c
            return None

        # Mappatura
        col_map['CHO'] = find_col(['CHO', 'CARBOHYDRATES'])
        col_map['FAT'] = find_col(['FAT', 'LIPIDS'])
        
        watt_c = find_col(['WR', 'WATT', 'POWER']) # WR è nel tuo file
        speed_c = find_col(['SPEED', 'VEL', 'KM/H'])
        fc_c = find_col(['FC', 'HR', 'BPM'])
        
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

        missing = []
        if 'CHO' not in col_map: missing.append("CHO")
        if 'FAT' not in col_map: missing.append("FAT")
        if 'Intensity' not in col_map: missing.append("Intensità")
        
        if missing:
            return None, None, f"Colonne mancanti: {', '.join(missing)}. Trovate: {cols[:5]}..."

        # 4. Pulizia
        clean_df = df[list(col_map.values())].rename(columns={v: k for k, v in col_map.items()})
        for c in clean_df.columns:
            clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        # 5. Verifica Unità (g/min -> g/h)
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None

    except Exception as e:
        return None, None, f"Errore tecnico: {str(e)}"

# --- PARSING ZWO (ESISTENTE) ---
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
    except:
        return [], 0, 0, 0

    intensity_series = [] 
    total_duration_sec = 0
    total_weighted_if = 0
    
    for steady_state in root.findall('.//SteadyState'):
        try:
            dur = int(steady_state.get('Duration'))
            power = float(steady_state.get('Power'))
            for _ in range(math.ceil(dur / 60)): intensity_series.append(power)
            total_duration_sec += dur
            total_weighted_if += power * (dur / 60) 
        except: continue

    total_min = math.ceil(total_duration_sec / 60)
    avg_val = 0
    if total_min > 0:
        avg_if = total_weighted_if / total_min
        if sport_type == SportType.CYCLING: avg_val = avg_if * ftp_watts
        elif sport_type == SportType.RUNNING: avg_val = avg_if * thr_hr
        else: avg_val = avg_if * 180 
        return intensity_series, total_min, avg_val, avg_val
    return [], 0, 0, 0

# --- FUNZIONI ZONE ---
def calculate_zones_cycling(ftp):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(ftp*p)} W"} for i, p in enumerate([0.55, 0.75, 0.90, 1.05, 1.20])]

def calculate_zones_running_hr(thr):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(thr*p)} bpm"} for i, p in enumerate([0.85, 0.89, 0.94, 0.99, 1.02])]
