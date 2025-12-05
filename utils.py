import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import altair as alt
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
# MODULO FIT PARSER & PLOTTING
# ==============================================================================

def process_fit_data(fit_file_object):
    """Legge un oggetto file .FIT, normalizza i tempi e restituisce un DataFrame pulito."""
    try:
        fit_file_object.seek(0)
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore lettura file FIT: {e}"

    data_list = []
    for record in fitfile.get_messages("record"):
        record_data = {}
        for record_field in record:
            record_data[record_field.name] = record_field.value
        if 'timestamp' in record_data:
            data_list.append(record_data)

    if not data_list:
        return None, "Nessun dato di registrazione trovato nel file."

    df = pd.DataFrame(data_list)
    df = df.set_index('timestamp').sort_index()
    
    if not df.empty:
        full_time_index = pd.date_range(start=df.index.min(), end=df.index.max(), freq='1s')
        df = df.reindex(full_time_index).ffill().fillna(0)

    column_map = {
        'power': ['power', 'accumulated_power'],
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence']
    }

    final_cols = {}
    for std_name, alternatives in column_map.items():
        for alt_col in alternatives:
            if alt_col in df.columns:
                final_cols[alt_col] = std_name
                break 
    
    df = df.rename(columns=final_cols)
    
    if 'speed' in df.columns:
        if df['speed'].max() < 80: df['speed_kmh'] = df['speed'] * 3.6
        else: df['speed_kmh'] = df['speed']
    else:
        df['speed_kmh'] = 0

    df['block_id'] = df['speed_kmh'].ne(df['speed_kmh'].shift()).cumsum()
    df['block_len'] = df.groupby('block_id')['speed_kmh'].transform('count')
    is_pause = (df['speed_kmh'] < 1.5) | ((df['block_len'] > 30) & (df['speed_kmh'] == 0))
    
    df_clean = df[~is_pause].copy()
    df_clean['moving_time_min'] = np.arange(len(df_clean)) / 60.0
    
    return df_clean, None

def create_fit_plot(df):
    """Genera grafico ALTAIR interattivo per il file FIT."""
    plot_df = df.reset_index()
    if len(plot_df) > 5000: plot_df = plot_df.iloc[::5, :]
    
    base = alt.Chart(plot_df).encode(x=alt.X('moving_time_min', title='Tempo (min)'))
    charts = []
    
    if 'power' in df.columns:
        charts.append(base.mark_area(color='#FF4B4B', opacity=0.5, line=True).encode(y=alt.Y('power', title='Watt')).properties(height=150, title="Potenza"))
    if 'heart_rate' in df.columns:
        charts.append(base.mark_line(color='#A020F0').encode(y=alt.Y('heart_rate', title='BPM', scale=alt.Scale(zero=False))).properties(height=150, title="Frequenza Cardiaca"))
    if 'cadence' in df.columns:
        charts.append(base.transform_filter(alt.datum.cadence > 0).mark_circle(color='#00FF00', size=10, opacity=0.3).encode(y=alt.Y('cadence', title='RPM')).properties(height=100, title="Cadenza"))

    return alt.vconcat(*charts).resolve_scale(x='shared') if charts else alt.Chart(pd.DataFrame({'Text': ['Nessun dato']})).mark_text().encode(text='Text')

def parse_fit_file_wrapper(uploaded_file, sport_type):
    df, error = process_fit_data(uploaded_file)
    if error or df is None or df.empty: return [], 0, 0, 0, None

    avg_power = df['power'].mean() if 'power' in df.columns else 0
    avg_hr = df['heart_rate'].mean() if 'heart_rate' in df.columns else 0
    total_duration_min = math.ceil(len(df) / 60)
    
    df_resampled = df.resample('1T').mean()
    intensity_series = []
    target_col = 'power' if sport_type == SportType.CYCLING and 'power' in df.columns else 'heart_rate'
    
    if target_col in df_resampled.columns:
        series_data = df_resampled[target_col].fillna(0).tolist()
        intensity_series = [float(x) for x in series_data]
    
    return intensity_series, total_duration_min, avg_power, avg_hr, df

# ==============================================================================

# --- PARSING FILE METABOLICO (TEST LAB) ---
def parse_metabolic_report(uploaded_file):
    """Legge file CSV/Excel da metabolimetro (Versione Robusta)."""
    try:
        df = None
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            content = uploaded_file.getvalue().decode('latin-1', errors='replace')
            lines = content.splitlines()
            header_row = None
            
            # Cerca la riga di intestazione
            for i, line in enumerate(lines[:300]):
                if "CHO" in line.upper() and "FAT" in line.upper():
                    header_row = i
                    break
            
            if header_row is None: # Fallback
                for i, line in enumerate(lines[:300]):
                    if line.strip().startswith("t") and "Fase" in line:
                        header_row = i; break
            
            parse_header = header_row if header_row is not None else 0
            
            # Sniffing Separatore
            sep = ','
            if header_row is not None:
                h_line = lines[header_row]
                if h_line.count(';') > h_line.count(','): sep = ';'
                elif h_line.count('\t') > h_line.count(','): sep = '\t'
            
            uploaded_file.seek(0)
            try: df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal='.')
            except: 
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=parse_header, sep=sep, engine='python', decimal=',')

        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else: return None, None, "Formato non supportato."

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
        watt_c = find_col(['WR', 'WATT', 'POWER'])
        speed_c = find_col(['SPEED', 'VEL', 'KM/H'])
        fc_c = find_col(['FC', 'HR', 'BPM'])
        
        intensity_type = None
        if watt_c: col_map['Intensity'] = watt_c; intensity_type = 'watt'
        elif speed_c: col_map['Intensity'] = speed_c; intensity_type = 'speed'
        elif fc_c: col_map['Intensity'] = fc_c; intensity_type = 'hr'

        if not (col_map.get('CHO') and col_map.get('FAT') and intensity_type):
             return None, None, "Colonne chiave mancanti (CHO/FAT/Intensity)."

        clean_df = pd.DataFrame()
        clean_df['Intensity'] = df[col_map['Intensity']]
        clean_df['CHO'] = df[col_map['CHO']]
        clean_df['FAT'] = df[col_map['FAT']]
        for c in clean_df.columns: clean_df[c] = pd.to_numeric(clean_df[c], errors='coerce')
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0].sort_values('Intensity')
        
        if not clean_df.empty and clean_df['CHO'].max() < 10:
            clean_df['CHO'] *= 60; clean_df['FAT'] *= 60
            
        return clean_df, intensity_type, None
    except Exception as e: return None, None, str(e)

# --- PARSING ZWO ---
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
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
    except: return [], 0, 0, 0

# --- ZONE ---
def calculate_zones_cycling(ftp):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(ftp*p)} W"} for i, p in enumerate([0.55, 0.75, 0.90, 1.05, 1.20])]
def calculate_zones_running_hr(thr):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(thr*p)} bpm"} for i, p in enumerate([0.85, 0.89, 0.94, 0.99, 1.02])]
