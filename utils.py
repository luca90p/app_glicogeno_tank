import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import matplotlib.pyplot as plt
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

# ==============================================================================
# MODULO FIT PARSER (Integrato da fit_processor.py)
# ==============================================================================

def process_fit_data(fit_file_object):
    """
    Legge un oggetto file .FIT, normalizza i tempi e restituisce un DataFrame pulito.
    """
    try:
        fit_file_object.seek(0) # Reset pointer
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore lettura file FIT: {e}"

    data_list = []

    # Estrazione messaggi 'record'
    for record in fitfile.get_messages("record"):
        record_data = {}
        for record_field in record:
            record_data[record_field.name] = record_field.value
        
        if 'timestamp' in record_data:
            data_list.append(record_data)

    if not data_list:
        return None, "Nessun dato di registrazione trovato nel file."

    # Creazione DataFrame
    df = pd.DataFrame(data_list)
    df = df.set_index('timestamp').sort_index()
    
    # Normalizzazione a 1 secondo (Smart Recording fix)
    # Gestisce eventuali buchi temporali o pause smart
    if not df.empty:
        full_time_index = pd.date_range(start=df.index.min(), end=df.index.max(), freq='1s')
        # Reindex e forward fill per coprire i buchi (smart recording)
        df = df.reindex(full_time_index).ffill().fillna(0)

    # Standardizzazione Colonne
    column_map = {
        'power': ['power', 'accumulated_power'],
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence']
    }

    final_cols = {}
    for std_name, alternatives in column_map.items():
        for alt in alternatives:
            if alt in df.columns:
                final_cols[alt] = std_name
                break 
    
    df = df.rename(columns=final_cols)
    
    # Calcoli aggiuntivi
    if 'speed' in df.columns:
        # Converti m/s in km/h se necessario
        if df['speed'].max() < 80: 
            df['speed_kmh'] = df['speed'] * 3.6
        else:
            df['speed_kmh'] = df['speed']
    else:
        df['speed_kmh'] = 0

    # Pulizia Pause (Velocità < 1.5 km/h)
    # Utile per avere medie reali (escludendo i semafori)
    df['block_id'] = df['speed_kmh'].ne(df['speed_kmh'].shift()).cumsum()
    df['block_len'] = df.groupby('block_id')['speed_kmh'].transform('count')
    
    # Maschera: Pausa se fermo o dato congelato a lungo (stallo)
    is_pause = (df['speed_kmh'] < 1.5) | ((df['block_len'] > 30) & (df['speed_kmh'] == 0))
    
    df_clean = df[~is_pause].copy()
    
    # Asse Tempo in minuti (per grafici)
    df_clean['moving_time_min'] = np.arange(len(df_clean)) / 60.0
    
    return df_clean, None

def create_fit_plot(df):
    """Genera grafico Matplotlib per il file FIT."""
    # Stile scuro per Streamlit
    plt.style.use('dark_background') 
    
    fig, axes = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
    
    c_pwr = '#FF4B4B' 
    c_hr = '#A020F0'  
    c_cad = '#00FF00' 
    c_spd = '#00BFFF' 

    # 1. POTENZA
    if 'power' in df.columns:
        axes[0].plot(df['moving_time_min'], df['power'], color=c_pwr, lw=0.5, alpha=0.6)
        # Media mobile 30s
        axes[0].plot(df['moving_time_min'], df['power'].rolling(30).mean(), color='white', lw=1.5, label='30s Avg')
        axes[0].set_ylabel('Watt', fontweight='bold', color=c_pwr)
        axes[0].legend(loc='upper right', fontsize='small')
    
    # 2. FREQUENZA CARDIACA
    if 'heart_rate' in df.columns:
        axes[1].plot(df['moving_time_min'], df['heart_rate'], color=c_hr, lw=1)
        axes[1].set_ylabel('BPM', fontweight='bold', color=c_hr)
        axes[1].grid(True, linestyle=':', alpha=0.3)

    # 3. CADENZA
    if 'cadence' in df.columns:
        cad_view = df['cadence'].replace(0, np.nan)
        axes[2].scatter(df['moving_time_min'], cad_view, color=c_cad, s=0.5, alpha=0.6)
        axes[2].set_ylabel('RPM', fontweight='bold', color=c_cad)
        axes[2].set_ylim(0, 130)

    # 4. VELOCITÀ
    if 'speed_kmh' in df.columns:
        axes[3].plot(df['moving_time_min'], df['speed_kmh'], color=c_spd, lw=1)
        axes[3].set_ylabel('Km/h', fontweight='bold', color=c_spd)
        axes[3].fill_between(df['moving_time_min'], df['speed_kmh'], color=c_spd, alpha=0.2)

    axes[3].set_xlabel('Tempo (minuti)')
    plt.tight_layout()
    
    return fig

def parse_fit_file_wrapper(uploaded_file, sport_type):
    """
    Wrapper che collega il parser FIT al motore di simulazione.
    Restituisce la serie temporale (per minuto) e le medie.
    """
    df, error = process_fit_data(uploaded_file)
    
    if error or df is None or df.empty:
        return [], 0, 0, 0, None

    # Calcolo Medie Globali (sul tempo in movimento)
    avg_power = df['power'].mean() if 'power' in df.columns else 0
    avg_hr = df['heart_rate'].mean() if 'heart_rate' in df.columns else 0
    
    # Calcolo Durata Totale (in minuti)
    total_duration_min = math.ceil(len(df) / 60)
    
    # --- RESAMPLING PER SIMULATORE (1 Minuto) ---
    # Il motore di simulazione lavora minuto per minuto. 
    # Dobbiamo fare il downsampling dei dati (media di ogni minuto).
    
    # Rindicizziamo su frequenza 1 Minuto prendendo la media
    df_resampled = df.resample('1T').mean()
    
    # Costruiamo la intensity_series
    intensity_series = []
    
    # Scegliamo la colonna guida in base allo sport
    target_col = 'power' if sport_type == SportType.CYCLING and 'power' in df.columns else 'heart_rate'
    
    if target_col in df_resampled.columns:
        # Sostituisci NaN con 0 (es. pause)
        series_data = df_resampled[target_col].fillna(0).tolist()
        intensity_series = [float(x) for x in series_data]
    
    return intensity_series, total_duration_min, avg_power, avg_hr, df

# ==============================================================================

# --- PARSING FILE METABOLICO (TEST LAB) ---
def parse_metabolic_report(uploaded_file):
    # ... (CODICE INVARIATO DALLA VERSIONE PRECEDENTE ROBUSTA) ...
    # Copiare qui il codice di parse_metabolic_report che ti ho mandato prima
    # Per brevità non lo ripeto tutto, ma è quello che inizia con:
    # "Legge file CSV/Excel da metabolimetro. Versione ROBUSTA 2.0..."
    try:
        df = None
        # 1. Gestione CSV
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            bytes_data = uploaded_file.getvalue()
            try:
                content = bytes_data.decode('utf-8')
            except UnicodeDecodeError:
                content = bytes_data.decode('latin-1', errors='replace')
            lines = content.splitlines()
            header_row = None
            header_line = ""
            search_terms = ["FC", "WR", "CHO", "FAT"]
            for i, line in enumerate(lines[:300]):
                line_upper = line.upper()
                matches = sum(1 for term in search_terms if term in line_upper)
                if matches >= 2:
                    header_row = i
                    header_line = line
                    break
            if header_row is None:
                for i, line in enumerate(lines[:300]):
                    if line.strip().startswith("t") and "Fase" in line:
                        header_row = i
                        header_line = line
                        break
            
            # Se ancora None, proviamo a leggere senza header e vedere dopo
            parse_header = header_row if header_row is not None else 0
            sep = ','
            if header_row is not None:
                if header_line.count(';') > header_line.count(','): sep = ';'
                elif header_line.count('\t') > header_line.count(','): sep = '\t'
            
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal='.')
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal=',')

        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            return None, None, "Formato file non supportato."

        if df is None or df.empty: return None, None, "File vuoto."

        # Normalizzazione
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
        watt_c = find_col(['WR', 'WATT', 'POWER', 'POW'])
        speed_c = find_col(['SPEED', 'VEL', 'KM/H', 'V'])
        fc_c = find_col(['FC', 'HR', 'HEART', 'BPM'])
        
        intensity_type = None
        if watt_c: col_map['Intensity'] = watt_c; intensity_type = 'watt'
        elif speed_c: col_map['Intensity'] = speed_c; intensity_type = 'speed'
        elif fc_c: col_map['Intensity'] = fc_c; intensity_type = 'hr'
        
        if not (col_map.get('CHO') and col_map.get('FAT') and intensity_type):
             return None, None, "Colonne chiave non trovate."

        clean_df = pd.DataFrame()
        clean_df['Intensity'] = df[col_map['Intensity']]
        clean_df['CHO'] = df[col_map['CHO']]
        clean_df['FAT'] = df[col_map['FAT']]
        for c in clean_df.columns: clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None
    except Exception as e:
        return None, None, str(e)

# --- PARSING ZWO (ESISTENTE) ---
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
    except: return [], 0, 0, 0

    intensity_series = [] 
    total_duration_sec = 0
    total_weighted_if = 0
    
    for steady_state in root.findall('.//SteadyState'):
        try:
            dur = int(steady_state.get('Duration'))
            pwr = float(steady_state.get('Power'))
            for _ in range(math.ceil(dur / 60)): intensity_series.append(pwr)
            total_duration_sec += dur
            total_weighted_if += pwr * (dur / 60) 
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
