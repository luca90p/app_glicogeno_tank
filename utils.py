import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
from data_models import SportType

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
    Include logica di fallback per formati Metasoft/Cosmed specifici.
    """
    df = None
    parsing_log = []
    
    try:
        # A. TENTATIVO CSV (Standard)
        try:
            uploaded_file.seek(0)
            content = uploaded_file.getvalue().decode('utf-8', errors='replace')
            
            # 1. Cerca Header Row
            lines = content.splitlines()
            header_row = None
            
            # Parole chiave da cercare nella stessa riga
            keywords = ["FC", "CHO", "FAT"]
            
            for i, line in enumerate(lines[:300]): # Scansiona le prime 300 righe
                line_upper = line.upper()
                if all(k in line_upper for k in keywords):
                    header_row = i
                    break
            
            if header_row is None:
                # Fallback: Cerca header specifico Metasoft (t, Fase, Marker...)
                for i, line in enumerate(lines[:300]):
                    if line.strip().startswith("t") and "Fase" in line:
                        header_row = i
                        break
            
            # Se ancora None, proviamo a leggere senza header e vedere dopo
            parse_header = header_row if header_row is not None else 0
            
            # Sniffing Separatore
            sep = ','
            if header_row is not None:
                header_line = lines[header_row]
                if header_line.count(';') > header_line.count(','): sep = ';'
                if header_line.count('\t') > header_line.count(','): sep = '\t'
            
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal='.')
            
            # Check se ha funzionato la lettura decimale, altrimenti riprova con virgola
            # Controllo euristico: se la colonna 0 contiene virgole, rileggi
            if df.shape[1] > 1 and df.dtypes[0] == object and df.iloc[0,0] and ',' in str(df.iloc[0,0]):
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal=',')

        except Exception as e:
            parsing_log.append(f"CSV Error: {e}")
            # B. TENTATIVO EXCEL (Se CSV fallisce)
            try:
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file)
            except Exception as e2:
                parsing_log.append(f"Excel Error: {e2}")

        if df is None or df.empty:
            return None, None, f"Impossibile leggere il file. Log: {parsing_log}"

        # 2. NORMALIZZAZIONE E MAPPATURA
        df.columns = [str(c).strip().upper() for c in df.columns]
        cols = df.columns.tolist()
        col_map = {}
        
        def find_col(keywords):
            for c in cols:
                for k in keywords:
                    if k == c or (k in c and len(c) < len(k)+5): return c
            return None

        # Mappatura Standard per Nomi
        col_map['CHO'] = find_col(['CHO', 'CARBOHYDRATES'])
        col_map['FAT'] = find_col(['FAT', 'LIPIDS'])
        col_map['FC'] = find_col(['FC', 'HR', 'HEART', 'BPM'])
        col_map['Watt'] = find_col(['WR', 'WATT', 'POWER'])
        col_map['Speed'] = find_col(['SPEED', 'VEL', 'KM/H'])

        # FALLBACK POSIZIONALE (Metasoft Specific)
        # Se non trovo i nomi ma ho tante colonne, provo a mappare per indice
        # Metasoft tipico: Col 6=FC (G), Col 7=WR (H), CHO/FAT verso la fine (21/23 o simile)
        if not col_map['CHO'] and len(cols) > 20:
            # Cerchiamo colonne numeriche verso la fine che potrebbero essere CHO/FAT
            # Questa è una euristica rischiosa, usiamola solo se disperati
            pass 

        # Selezione Intensità
        intensity_col = None
        intensity_type = None
        
        if col_map['Watt']:
            intensity_col = col_map['Watt']
            intensity_type = 'watt'
        elif col_map['Speed']:
            intensity_col = col_map['Speed']
            intensity_type = 'speed'
        elif col_map['FC']:
            intensity_col = col_map['FC']
            intensity_type = 'hr'
        
        # Verifica completezza
        missing = []
        if not col_map['CHO']: missing.append("CHO")
        if not col_map['FAT']: missing.append("FAT")
        if not intensity_col: missing.append("Intensità (Watt/FC)")

        if missing:
            return None, None, f"Colonne non identificate: {', '.join(missing)}. Trovate: {cols[:10]}... (Verifica che la riga di intestazione sia corretta)."

        # 3. CREAZIONE DATAFRAME PULITO
        clean_df = pd.DataFrame()
        clean_df['Intensity'] = df[intensity_col]
        clean_df['CHO'] = df[col_map['CHO']]
        clean_df['FAT'] = df[col_map['FAT']]
        
        # Conversione
        for c in clean_df.columns:
            clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        # 4. CHECK UNITÀ DI MISURA
        # Se CHO max < 10, è g/min -> converti a g/h
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None

    except Exception as e:
        return None, None, f"Errore inatteso: {str(e)}"

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
