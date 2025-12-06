import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import altair as alt
from data_models import SportType

# --- SISTEMA DI PROTEZIONE ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "glicogeno2025": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]  
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Inserisci Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Inserisci Password", type="password", on_change=password_entered, key="password")
        st.error("Password errata.")
        return False
    else:
        return True

# ==============================================================================
# MODULO CALCOLO POTENZA NORMALIZZATA (NP)
# ==============================================================================
def calculate_normalized_power(df):
    if 'power' not in df.columns: return 0
    rolling_pwr = df['power'].rolling(window=30, min_periods=1).mean()
    return (rolling_pwr ** 4).mean() ** 0.25

# ==============================================================================
# MODULO FIT PARSER & PLOTTING
# ==============================================================================

def process_fit_data(fit_file_object):
    """
    Legge file .FIT, normalizza, pulisce pause e restituisce DataFrame.
    """
    try:
        fit_file_object.seek(0)
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore file FIT: {e}"

    data_list = []
    for record in fitfile.get_messages("record"):
        r_data = {}
        for field in record: r_data[field.name] = field.value
        if 'timestamp' in r_data: data_list.append(r_data)

    if not data_list: return None, "Nessun dato record."

    df_raw = pd.DataFrame(data_list)
    df_raw = df_raw.set_index('timestamp').sort_index()
    
    # Normalizzazione Temporale (1s)
    if not df_raw.empty:
        full_idx = pd.date_range(start=df_raw.index.min(), end=df_raw.index.max(), freq='1s')
        # Forward fill limitato (max 5 sec) per evitare di inventare dati in pause lunghe
        df_raw = df_raw.reindex(full_idx).ffill(limit=5).fillna(0)

    col_map = {
        'power': ['power', 'accumulated_power'],
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence'],
        'distance': ['distance']
    }

    df_clean = pd.DataFrame(index=df_raw.index)
    for std, alts in col_map.items():
        for alt in alts:
            if alt in df_raw.columns:
                df_clean[std] = df_raw[alt]
                break 
    
    # Conversione Speed m/s -> km/h
    if 'speed' in df_clean.columns:
        if df_clean['speed'].max() < 100: 
            df_clean['speed_kmh'] = df_clean['speed'] * 3.6
        else:
            df_clean['speed_kmh'] = df_clean['speed']
    else:
        df_clean['speed_kmh'] = 0

    # --- ALGORITMO FILTRO PAUSE MIGLIORATO ---
    # 1. Soglia velocità: < 2.5 km/h è pausa (camminata lenta/fermo)
    # 2. Potenza zero: Se power=0 E speed < 5 km/h per più di 10s -> Pausa
    # 3. Cadenza zero: Se cadenza=0 E speed < 5 km/h -> Pausa (Ciclismo)
    
    is_stopped = df_clean['speed_kmh'] < 2.5
    
    # Maschera finale
    df_final = df_clean[~is_stopped].copy()
    
    # Ricalcolo asse temporale continuo (Moving Time)
    df_final['moving_time_min'] = np.arange(len(df_final)) / 60.0
    
    return df_final, None

def create_fit_plot(df):
    """Genera grafico ALTAIR a 4 pannelli: Power, HR, Cadence, Altitude."""
    # Resampling per performance grafica
    plot_df = df.reset_index()
    if len(plot_df) > 5000: plot_df = plot_df.iloc[::10, :] # Downsample più aggressivo per velocità
    
    base = alt.Chart(plot_df).encode(x=alt.X('moving_time_min', title='Tempo in Movimento (min)'))
    charts = []
    
    # 1. POTENZA
    if 'power' in df.columns and df['power'].max() > 0:
        c_pwr = base.mark_area(color='#FF4B4B', opacity=0.6, line=True).encode(
            y=alt.Y('power', title='Watt'),
            tooltip=['moving_time_min', 'power']
        ).properties(height=150, title="Potenza")
        charts.append(c_pwr)
    
    # 2. CARDIO
    if 'heart_rate' in df.columns and df['heart_rate'].max() > 0:
        c_hr = base.mark_line(color='#A020F0').encode(
            y=alt.Y('heart_rate', title='BPM', scale=alt.Scale(zero=False)),
            tooltip=['moving_time_min', 'heart_rate']
        ).properties(height=150, title="Frequenza Cardiaca")
        charts.append(c_hr)
        
    # 3. ALTIMETRIA (Nuovo!)
    if 'altitude' in df.columns:
        # Area grigia stile Strava
        min_alt = df['altitude'].min()
        c_alt = base.mark_area(color='#90A4AE', opacity=0.4, line={'color':'#546E7A'}).encode(
            y=alt.Y('altitude', title='Metri', scale=alt.Scale(domain=[min_alt, df['altitude'].max()])),
            tooltip=['moving_time_min', 'altitude']
        ).properties(height=150, title="Profilo Altimetrico")
        charts.append(c_alt)

    # 4. CADENZA
    if 'cadence' in df.columns and df['cadence'].max() > 0:
        c_cad = base.transform_filter(alt.datum.cadence > 0).mark_circle(color='#00FF00', size=5, opacity=0.2).encode(
            y=alt.Y('cadence', title='RPM'),
            tooltip=['moving_time_min', 'cadence']
        ).properties(height=100, title="Cadenza")
        charts.append(c_cad)

    if charts:
        return alt.vconcat(*charts).resolve_scale(x='shared')
    else:
        return alt.Chart(pd.DataFrame({'T':['Nessun dato valido']})).mark_text().encode(text='T')

def parse_fit_file_wrapper(uploaded_file, sport_type):
    """Wrapper che estrae dati e calcola statistiche avanzate."""
    df, error = process_fit_data(uploaded_file)
    if error or df is None or df.empty: return [], 0, 0, 0, 0, 0, 0, None

    # Medie su tempo in movimento
    avg_power = df['power'].mean() if 'power' in df.columns else 0
    avg_hr = df['heart_rate'].mean() if 'heart_rate' in df.columns else 0
    norm_power = calculate_normalized_power(df) if 'power' in df.columns else 0
    
    # Statistiche extra per Dashboard
    total_duration_min = math.ceil(len(df) / 60)
    
    dist = 0
    if 'distance' in df.columns:
        dist = (df['distance'].max() - df['distance'].min()) / 1000.0 # km
    elif 'speed_kmh' in df.columns:
        # Stima distanza se manca colonna
        dist = (df['speed_kmh'].mean() * (total_duration_min/60))
        
    elev_gain = 0
    if 'altitude' in df.columns:
        # Calcolo guadagno positivo
        deltas = df['altitude'].diff()
        elev_gain = deltas[deltas > 0].sum()
    
    work_kj = 0
    if 'power' in df.columns:
        work_kj = (avg_power * (total_duration_min * 60)) / 1000
    
    # Resampling per logica simulatore (1 min)
    df_res = df.resample('1T').mean()
    series = []
    target = 'power' if sport_type == SportType.CYCLING and 'power' in df.columns else 'heart_rate'
    if target in df_res.columns:
        series = [float(x) for x in df_res[target].fillna(0).tolist()]
    
    return series, total_duration_min, avg_power, avg_hr, norm_power, dist, elev_gain, work_kj, df

# ==============================================================================
# PARSING METABOLICO (ESTRAZIONE MULTIPLA SMART)
# ==============================================================================
def parse_metabolic_report(uploaded_file):
    try:
        df_raw = None
        uploaded_file.seek(0)
        
        # 1. LEGGI TUTTO IL FILE (Scan & Slice)
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            try:
                df_raw = pd.read_csv(uploaded_file, header=None, sep=None, engine='python', encoding='latin-1', dtype=str)
            except:
                uploaded_file.seek(0)
                df_raw = pd.read_csv(uploaded_file, header=None, sep=',', engine='python', encoding='latin-1', dtype=str)
        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df_raw = pd.read_excel(uploaded_file, header=None, dtype=str)
        else:
            return None, None, "Formato non supportato."

        if df_raw is None or df_raw.empty: return None, None, "File vuoto."

        # 2. CERCA HEADER
        header_idx = None
        targets = ["CHO", "FAT"]
        intensities = ["WR", "WATT", "POW", "FC", "HR", "BPM", "SPEED", "VEL", "KM/H", "V"]

        for i, row in df_raw.head(300).iterrows():
            row_text = " ".join([str(x).upper() for x in row.values if pd.notna(x)])
            if all(t in row_text for t in targets) and any(t in row_text for t in intensities):
                header_idx = i; break
        
        if header_idx is None: return None, None, "Intestazione non trovata."

        # 3. TAGLIA E MAPPA
        df_raw.columns = df_raw.iloc[header_idx] 
        df = df_raw.iloc[header_idx + 1:].reset_index(drop=True)
        df.columns = [str(c).strip().upper() for c in df.columns]
        cols = df.columns.tolist()

        def find_col(keys):
            for col in cols:
                for k in keys:
                    if k == col or (k in col and len(col) < len(k)+5): return col
            return None

        # Mappa Metabolica
        c_cho = find_col(['CHO', 'CARBOHYDRATES'])
        c_fat = find_col(['FAT', 'LIPIDS'])
        
        # Mappa Intensità (Tutte quelle trovate)
        c_watt = find_col(['WR', 'WATT', 'POWER', 'POW'])
        c_hr = find_col(['FC', 'HR', 'HEART', 'BPM'])
        c_speed = find_col(['SPEED', 'VEL', 'KM/H', 'V'])

        if not (c_cho and c_fat): return None, None, "Mancano colonne CHO/FAT."

        # 4. ESTRAZIONE E CONVERSIONE
        def to_float(series):
            s = series.astype(str).str.replace(',', '.', regex=False).str.extract(r'(\d+\.?\d*)')[0]
            return pd.to_numeric(s, errors='coerce')

        clean_df = pd.DataFrame()
        clean_df['CHO'] = to_float(df[c_cho])
        clean_df['FAT'] = to_float(df[c_fat])
        
        available_metrics = []
        if c_watt: 
            clean_df['Watt'] = to_float(df[c_watt])
            available_metrics.append('Watt')
        if c_hr: 
            clean_df['HR'] = to_float(df[c_hr])
            available_metrics.append('HR')
        if c_speed: 
            clean_df['Speed'] = to_float(df[c_speed])
            available_metrics.append('Speed')

        if not available_metrics: return None, None, "Nessuna colonna intensità trovata."

        clean_df.dropna(subset=['CHO', 'FAT'], inplace=True)
        
        # Check Unità (g/min -> g/h)
        if not clean_df.empty and clean_df['CHO'].max() < 8.0:
            clean_df['CHO'] *= 60; clean_df['FAT'] *= 60

        return clean_df, available_metrics, None

    except Exception as e: return None, None, str(e)
# --- ZWO ---
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




