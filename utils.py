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
    Include logica di fallback POSIZIONALE per file Metasoft.
    """
    df = None
    parsing_log = []
    
    try:
        # A. LETTURA RAW DEL CONTENUTO
        # Leggiamo tutto come testo per analizzare la struttura
        uploaded_file.seek(0)
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            content = uploaded_file.getvalue().decode('latin-1', errors='replace') # Latin-1 è più sicuro per file legacy
            lines = content.splitlines()
        else:
            # Excel non supportato in questa modalità raw text, ma pandas lo gestisce
            pass

        # B. TENTATIVO 1: RILEVAMENTO HEADER INTELLIGENTE
        # Cerchiamo la riga che contiene le label
        header_row = None
        sep = ','
        
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            for i, line in enumerate(lines[:200]):
                if "CHO" in line.upper() and "FAT" in line.upper():
                    header_row = i
                    if line.count(';') > line.count(','): sep = ';'
                    elif line.count('\t') > line.count(','): sep = '\t'
                    break
            
            if header_row is not None:
                uploaded_file.seek(0)
                try:
                    df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal=',')
                    # Se fallisce la conversione numerica, riprova con punto
                    if df.shape[1] > 1:
                         # Test rapido su una colonna dati
                         try: pd.to_numeric(df.iloc[0, 6])
                         except: 
                             uploaded_file.seek(0)
                             df = pd.read_csv(uploaded_file, header=header_row, sep=sep, engine='python', decimal='.')
                except:
                    pass

        # C. TENTATIVO 2 (FALLBACK): MAPPATURA POSIZIONALE FISSA (A, G, V, X)
        # Se il df è vuoto o mancano colonne chiave, usiamo la mappa forzata che hai fornito
        # A (0) = Tempo, G (6) = FC, H (7) = Watt/WR (spesso accanto a FC), V (21) = CHO, X (23) = FAT
        
        forced_map_used = False
        
        if df is None or 'CHO' not in [str(c).upper() for c in df.columns]:
            parsing_log.append("Header automatico fallito. Tento mappatura posizionale (A, G, V, X).")
            
            if uploaded_file.name.lower().endswith(('.csv', '.txt')):
                # Cerchiamo l'inizio dei dati. Di solito dopo la riga delle unità.
                # Se header era 116 (trovato dal tool), dati iniziano a 118 (Excel 119).
                data_start_row = 0
                for i, line in enumerate(lines[:200]):
                    # Cerchiamo una riga che inizia con un timestamp o numero
                    parts = line.split(sep)
                    if len(parts) > 20 and parts[0].strip() and parts[6].strip().replace(',','').replace('.','').isdigit():
                        data_start_row = i
                        break
                
                if data_start_row > 0:
                    uploaded_file.seek(0)
                    # Leggiamo senza header, saltando le righe iniziali
                    df = pd.read_csv(uploaded_file, header=None, skiprows=data_start_row, sep=sep, engine='python', decimal=',')
                    forced_map_used = True
            
            elif uploaded_file.name.lower().endswith('.xlsx'):
                 df = pd.read_excel(uploaded_file, header=None)
                 # Trova inizio dati excel (es. riga 119)
                 # Semplifichiamo: cerchiamo la prima riga con numeri validi in col G (6) e V (21)
                 start_idx = 0
                 for i in range(min(200, len(df))):
                     val_g = str(df.iloc[i, 6])
                     if val_g.replace('.','').isdigit() and float(val_g) > 40: # FC > 40
                         start_idx = i
                         break
                 df = df.iloc[start_idx:].reset_index(drop=True)
                 forced_map_used = True

        if df is None or df.empty:
            return None, None, "Impossibile leggere il file. Verifica il formato."

        # 3. ESTRAZIONE COLONNE (Dinamica o Posizionale)
        clean_df = pd.DataFrame()
        
        if forced_map_used:
            # Mappatura fissa basata sulla tua richiesta
            # A=0, G=6 (FC), H=7 (WR/Watt - probabile), V=21 (CHO), X=23 (FAT)
            try:
                # Verifica che il df abbia abbastanza colonne
                if df.shape[1] < 24:
                    return None, None, f"Il file ha solo {df.shape[1]} colonne, ne servono almeno 24 (fino alla colonna X)."
                
                clean_df['FC'] = pd.to_numeric(df.iloc[:, 6], errors='coerce') # Col G
                clean_df['CHO'] = pd.to_numeric(df.iloc[:, 21], errors='coerce') # Col V
                clean_df['FAT'] = pd.to_numeric(df.iloc[:, 23], errors='coerce') # Col X
                
                # Per l'intensità usiamo WR (Col H - indice 7) se esiste, altrimenti FC
                clean_df['Watt'] = pd.to_numeric(df.iloc[:, 7], errors='coerce') # Col H
                
                if clean_df['Watt'].sum() > 0:
                    clean_df['Intensity'] = clean_df['Watt']
                    intensity_type = 'watt'
                else:
                    clean_df['Intensity'] = clean_df['FC']
                    intensity_type = 'hr'
                    
            except Exception as e:
                return None, None, f"Errore mappatura posizionale: {e}"

        else:
            # Mappatura per Nomi (Standard)
            df.columns = [str(c).strip().upper() for c in df.columns]
            cols = df.columns.tolist()
            col_map = {}
            
            def find_col(keywords):
                for c in cols:
                    for k in keywords:
                        if k == c or (k in c and len(c) < len(k)+5): return c
                return None

            col_map['CHO'] = find_col(['CHO', 'CARBOHYDRATES'])
            col_map['FAT'] = find_col(['FAT', 'LIPIDS'])
            
            # Intensità
            watt_c = find_col(['WR', 'WATT', 'POWER'])
            speed_c = find_col(['SPEED', 'VEL', 'KM/H'])
            fc_c = find_col(['FC', 'HR', 'BPM'])
            
            intensity_type = None
            intensity_col = None
            
            if watt_c: 
                intensity_col = watt_c; intensity_type = 'watt'
            elif speed_c: 
                intensity_col = speed_c; intensity_type = 'speed'
            elif fc_c: 
                intensity_col = fc_c; intensity_type = 'hr'
            
            if not (col_map['CHO'] and col_map['FAT'] and intensity_col):
                return None, None, f"Colonne non trovate per nome. Trovate: {cols[:5]}..."

            clean_df['Intensity'] = pd.to_numeric(df[intensity_col], errors='coerce')
            clean_df['CHO'] = pd.to_numeric(df[col_map['CHO']], errors='coerce')
            clean_df['FAT'] = pd.to_numeric(df[col_map['FAT']], errors='coerce')

        # 4. PULIZIA FINALE
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        # Verifica unità (g/min -> g/h)
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None

    except Exception as e:
        return None, None, f"Errore critico parsing: {str(e)}"

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

