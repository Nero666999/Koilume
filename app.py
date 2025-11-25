import os
import pandas as pd
from datetime import datetime
from functools import wraps
import locale 
import time
from supabase import create_client, Client
from dateutil.relativedelta import relativedelta
import traceback

# Impor library Flask
from flask import (
    Flask, 
    render_template_string,
    request, 
    redirect, 
    url_for, 
    session, 
    flash,
    jsonify
)

# --- KONEKSI KE SUPABASE ---
SUPABASE_URL = "https://asweqitjjbepoxwpscsz.supabase.co" 
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFzd2VxaXRqamJlcG94d3BzY3N6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjIzMzg3NzMsImV4cCI6MjA3NzkxNDc3M30.oihrg9Pz0qa0LS5DIJzM2itIbtG0oh__PlOqx4nd2To" 

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("--- BERHASIL KONEK KE SUPABASE ---") 
except Exception as e:
    print(f"--- GAGAL KONEK KE SUPABASE: {e} ---")
# --- Akhir Koneksi ---

app = Flask(__name__)
app.secret_key = 'kunci-rahasia-lokal-saya-bebas-diisi-apa-saja'

# --- Fungsi Format Rupiah ---
def format_rupiah(value):
    """Format angka menjadi string Rupiah 'Rp 1.000.000'."""
    try:
        try:
            locale.setlocale(locale.LC_ALL, 'id_ID.UTF-8')
        except locale.Error:
            locale.setlocale(locale.LC_ALL, 'Indonesian_Indonesia.1252')
            
        value = float(value)
        formatted_value = locale.format_string("%d", value, grouping=True)
        return f"Rp {formatted_value}"
    except (ValueError, TypeError, locale.Error):
        try:
            return f"Rp {int(value):,}".replace(",", ".")
        except:
            return "Rp 0"

app.jinja_env.filters['rupiah'] = format_rupiah
# --- Akhir Fungsi Rupiah ---

# ---------------- Data Kategori ----------------
# ==========================================
# 1. KONFIGURASI KATEGORI (DATA FIX)
# ==========================================

# --- Kategori Aset Tetap (Revisi: Cuma Kendaraan & Bangunan) ---
kategori_aset = {
    "Kendaraan": {
        "akun_aset": "Aset - Kendaraan",
        "akun_akumulasi": "Akumulasi Penyusutan - Kendaraan",
        "akun_beban": "Beban Penyusutan - Kendaraan"
    },
    "Bangunan": {
        "akun_aset": "Aset - Bangunan",
        "akun_akumulasi": "Akumulasi Penyusutan - Bangunan",
        "akun_beban": "Beban Penyusutan - Bangunan"
    }
}

# Pengeluaran
kategori_pengeluaran = {
    # Trigger Tambah Stok
    "Pembelian Stok Ikan": ["Kohaku", "Shusui", "Tancho", "Kumpay"],
    
    # Trigger Beban Biasa (Non-Stok)
    "Beban Operasional": ["Beban Listrik", "Beban Air", "Beban Internet", "Beban Gaji", "Beban Bensin"],
    "Beban Perlengkapan": ["Beban Pakan", "Beban Obat-obatan", "Beban Garam", "Beban Vitamin"],
    "Beban Pemeliharaan": ["Beban Filter/Media", "Beban Perawatan Kolam"],
    "Lainnya": ["Beban Lain-lain"]
}

# Pemasukan
kategori_pemasukan = {
    # Trigger Kurang Stok
    "Penjualan": ["Penjualan - Kohaku", "Penjualan - Shusui", "Penjualan - Tancho", "Penjualan - Kumpay"]
}

# Persediaan (Hanya Ikan)
kategori_persediaan = {
    "Ikan Koi": ["Kohaku", "Shusui", "Tancho", "Kumpay"]
}

# List Dropdown
list_kategori_stok = ["Ikan Koi"]
jenis_ikan = ["Kohaku", "Shusui", "Tancho", "Kumpay"] # Helper list

# Mapping Akun Jurnal
akun_persediaan = {
    "Kohaku": "Persediaan - Kohaku",
    "Shusui": "Persediaan - Shusui",
    "Tancho": "Persediaan - Tancho",
    "Kumpay": "Persediaan - Kumpay"
}

# --- PETA SALDO NORMAL (BARU) ---
SALDO_NORMAL_MAP = {
    "Kas": "Debit", "Bank": "Debit", 
    "Perlengkapan": "Debit", 
    "Piutang Dagang": "Debit",
    "Aset - Kendaraan": "Debit", "Aset - Bangunan": "Debit",
    
    # Persediaan Ikan
    "Persediaan - Kohaku": "Debit",
    "Persediaan - Shusui": "Debit",
    "Persediaan - Tancho": "Debit",
    "Persediaan - Kumpay": "Debit",

    # Pasiva & Kontra
    "Akumulasi Penyusutan - Kendaraan": "Kredit",
    "Akumulasi Penyusutan - Bangunan": "Kredit",
    "Utang Dagang": "Kredit",
    "Modal Owner": "Kredit",
    "Laba Ditahan": "Kredit",
    "Historical Balancing": "Kredit"
}

# --- Data Persediaan ---
jenis_ikan = ["Kohaku", "Shusui", "Tancho", "Kumpay"]

# ---------------- Helper Functions ----------------
def clean_data_and_format_df(df):
    """Membersihkan kolom numerik dan format tanggal untuk laporan."""
    if df is None or df.empty:
        return pd.DataFrame()
    
    try:
        # 1. Pastikan kolom angka adalah NUMERIK
        for col in ['Debit', 'Kredit', 'Jumlah', 'harga_perolehan', 'nilai_residu']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        # 2. Konversi Tanggal dan Hapus Timezone (FIX TypeError: datetime64)
        if 'Tanggal' in df.columns:
            df['Tanggal'] = pd.to_datetime(df['Tanggal'], errors='coerce', utc=True).dt.tz_localize(None)
            df = df.dropna(subset=['Tanggal'])
            
            df['Tanggal_str'] = df['Tanggal'].dt.strftime('%Y-%m-%d %H:%M:%S')
            df['YearMonth'] = df['Tanggal'].dt.to_period('M') 
    except Exception as e:
        print(f"Error in clean_data_and_format_df: {e}")
        return pd.DataFrame()
        
    return df

def load_data_from_db(tabel, user_id):
    """Mengambil data dari tabel Supabase dan mengembalikan DataFrame."""
    try:
        response = supabase.from_(tabel).select("*").eq("user_id", user_id).execute()
        df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        
        if df.empty:
            if tabel == "jurnal":
                # WAJIB ADA: Debit, Kredit, Akun, Tanggal, Keterangan, Kontak
                return pd.DataFrame(columns=['id', 'Tanggal', 'Debit', 'Kredit', 'Akun', 'Keterangan', 'Kontak'])
            elif tabel == "pemasukan":
                return pd.DataFrame(columns=['id', 'Tanggal', 'Jumlah', 'Sumber', 'Sub_Sumber', 'Metode', 'Kontak', 'Keterangan'])
            elif tabel == "pengeluaran":
                return pd.DataFrame(columns=['id', 'Tanggal', 'Jumlah', 'Kategori', 'Sub_Kategori', 'Metode', 'Kontak', 'Keterangan'])
        
        return df
        
    except Exception as e:
        print(f"Error load_data_from_db ({tabel}): {e}")
        # Return empty DataFrame dengan kolom yang sesuai
        if tabel == "jurnal":
            return pd.DataFrame(columns=['id', 'Tanggal', 'Debit', 'Kredit', 'Akun', 'Keterangan', 'Kontak'])
        elif tabel == "pemasukan":
            return pd.DataFrame(columns=['id', 'Tanggal', 'Jumlah', 'Sumber', 'Sub_Sumber', 'Metode', 'Kontak', 'Keterangan'])
        elif tabel == "pengeluaran":
            return pd.DataFrame(columns=['id', 'Tanggal', 'Jumlah', 'Kategori', 'Sub_Kategori', 'Metode', 'Kontak', 'Keterangan'])
        return pd.DataFrame()
        
def append_data_to_db(tabel, data, user_id):
    """Menyimpan data (dictionary) ke tabel Supabase dan mengembalikan ID."""
    try:
        data['user_id'] = user_id 
        # Perubahan: return response.data[0]['id'] untuk mendapatkan ID data yang baru disimpan
        response = supabase.from_(tabel).insert(data).execute()
        if response.data:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error append_data_to_db ({tabel}): {e}")
        flash(f"Gagal menyimpan data ke DB: {e}", "danger")
        raise e
    
def buat_jurnal_batch(jurnal_entries, user_id):
    """Menyimpan beberapa entri jurnal sekaligus ke Supabase."""
    try:
        for entry in jurnal_entries:
            entry['user_id'] = user_id
        response = supabase.from_("jurnal").insert(jurnal_entries).execute()
    except Exception as e:
        print(f"Error buat_jurnal_batch: {e}")
        flash(f"Gagal menyimpan jurnal ke DB: {e}", "danger")
        raise e

def hapus_transaksi_db(tabel, db_id, user_id):
    """Menghapus transaksi dari Supabase dan membuat jurnal pembalikan, termasuk pembalikan stok."""
    try:
        # 1. Ambil data transaksi yang akan dihapus
        response = supabase.from_(tabel).select("*").eq("id", db_id).eq("user_id", user_id).single().execute()
        transaksi = response.data
        
        # JURNAL PEMBALIKAN: Membatalkan dampak keuangan di Jurnal Umum
        waktu_hapus = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jumlah_transaksi = float(transaksi['Jumlah'])
        metode_transaksi = transaksi['Metode']
        kontak = transaksi.get('Kontak', '')
        jurnal_pembalikan_entries = []
        
        # STOK: Ambil data stok terkait (jika ada)
        ref_id = db_id
        # Kita cari jurnal stok yang punya deskripsi Penjualan atau Pembelian
        stok_terkait_res = supabase.from_("persediaan").select("*").eq("ref_id", ref_id).eq("user_id", user_id).execute()
        stok_terkait = stok_terkait_res.data if stok_terkait_res.data else []
        
        if tabel == "pemasukan":
            # --- PEMBALIKAN PEMASUKAN ---
            sub_sumber = transaksi.get('Sub_Sumber', 'Lain-lain') 
            keterangan_batal = f"Pembatalan: {transaksi.get('Sumber', '')} - {sub_sumber}"
            
            # Pembalikan Jurnal Uang (Debit Penjualan, Kredit Kas/Piutang)
            akun_debit_pembalikan = {"Tunai": "Kas", "Transfer": "Bank", "Piutang": "Piutang Dagang"}.get(metode_transaksi, "Kas")
            akun_kredit_asli = sub_sumber 
            jurnal_pembalikan_entries = [
                {"Tanggal": waktu_hapus, "Akun": akun_kredit_asli, "Debit": jumlah_transaksi, "Kredit": 0, "Keterangan": keterangan_batal, "Kontak": ""},
                {"Tanggal": waktu_hapus, "Akun": akun_debit_pembalikan, "Debit": 0, "Kredit": jumlah_transaksi, "Keterangan": keterangan_batal, "Kontak": kontak if akun_debit_pembalikan == "Piutang Dagang" else ""}
            ]
            
            # Pembalikan Stok dan Jurnal HPP (Jika itu Penjualan Stok)
            if stok_terkait:
                # Kita asumsikan hanya ada 1 entry stok per transaksi
                stok_data = stok_terkait[0]
                qty_keluar = int(stok_data.get('keluar', 0)) # Qty yang keluar saat penjualan
                hpp_per_unit = stok_data.get('harga_satuan', 0)
                hpp_total = qty_keluar * hpp_per_unit
                
                # 1. Balik Stok: Stok MASUK kembali ke gudang
                supabase.from_("persediaan").insert({
                    "tanggal": waktu_hapus, "deskripsi": "Pembalikan Penjualan",
                    "barang": stok_data['barang'], "masuk": qty_keluar, "keluar": 0,
                    "harga_satuan": hpp_per_unit, "keterangan": f"Pembalikan HPP Ref ID {ref_id}", "user_id": user_id
                }).execute()

                # 2. Balik Jurnal HPP (Debit Persediaan, Kredit HPP)
                jurnal_pembalikan_entries.extend([
                    {"Tanggal": waktu_hapus, "Akun": "Persediaan - Ikan Koi", "Debit": hpp_total, "Kredit": 0, "Keterangan": f"Pembalikan HPP", "Kontak": ""},
                    {"Tanggal": waktu_hapus, "Akun": "Harga Pokok Penjualan", "Debit": 0, "Kredit": hpp_total, "Keterangan": f"Pembalikan HPP", "Kontak": ""}
                ])

        elif tabel == "pengeluaran":
            # --- PEMBALIKAN PENGELUARAN ---
            sub_kategori = transaksi.get('Sub_Kategori', 'Beban Lain') 
            keterangan_batal = f"Pembatalan: {transaksi.get('Kategori', '')} - {sub_kategori}"

            # Pembalikan Jurnal Uang (Debit Kas/Utang, Kredit Beban/Persediaan)
            akun_kredit_pembalikan = {"Tunai": "Kas", "Transfer": "Bank", "Utang": "Utang Dagang"}.get(metode_transaksi, "Kas")
            akun_debit_asli = sub_kategori
            jurnal_pembalikan_entries = [
                {"Tanggal": waktu_hapus, "Akun": akun_kredit_pembalikan, "Debit": jumlah_transaksi, "Kredit": 0, "Keterangan": keterangan_batal, "Kontak": kontak if akun_kredit_pembalikan == "Utang Dagang" else ""},
                {"Tanggal": waktu_hapus, "Akun": akun_debit_asli, "Debit": 0, "Kredit": jumlah_transaksi, "Keterangan": keterangan_batal, "Kontak": ""}
            ]
            
            # Pembalikan Stok (Jika itu Pembelian Stok Ikan)
            if stok_terkait:
                stok_data = stok_terkait[0]
                qty_masuk = int(stok_data.get('masuk', 0))
                hpp_per_unit = stok_data.get('harga_satuan', 0)
                
                # 1. Balik Stok: Stok KELUAR dari gudang
                supabase.from_("persediaan").insert({
                    "tanggal": waktu_hapus, "deskripsi": "Pembalikan Pembelian",
                    "barang": stok_data['barang'], "masuk": 0, "keluar": qty_masuk,
                    "harga_satuan": hpp_per_unit, "keterangan": f"Pembalikan Pembelian Ref ID {ref_id}", "user_id": user_id
                }).execute()

        else:
            return False
        
        # 2. Hapus Transaksi Asli (Tabel Pemasukan/Pengeluaran)
        supabase.from_(tabel).delete().eq("id", db_id).execute()

        # 3. Simpan Jurnal Pembalikan ke DB
        buat_jurnal_batch(jurnal_pembalikan_entries, user_id)
        return True
        
    except Exception as e:
        print(f"Error hapus_transaksi_db: {e}")
        flash(f"Gagal menghapus data: {e}", "danger")
        return False 

def hitung_stok_akhir(user_id):
    """Hitung sisa stok dan HPP Rata-rata dari tabel tunggal 'persediaan'"""
    try:
        # Ambil semua data
        response = supabase.from_("persediaan").select("*").eq("user_id", user_id).execute()
        df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        
        stok_list = []
        if not df.empty:
            # Pastikan angka aman
            for col in ['masuk', 'keluar', 'harga_satuan']:
                if col in df.columns: df[col] = pd.to_numeric(df[col]).fillna(0)

            # Group by 'barang' (Nama Ikan)
            # [FIX] Pakai 'barang' karena itu nama kolom di Supabase
            for nama_ikan, group in df.groupby('barang'):
                total_masuk = group['masuk'].sum()
                total_keluar = group['keluar'].sum()
                sisa = total_masuk - total_keluar
                
                # Hitung HPP Rata-rata
                transaksi_beli = group[group['masuk'] > 0]
                if not transaksi_beli.empty:
                    nilai_beli = (transaksi_beli['masuk'] * transaksi_beli['harga_satuan']).sum()
                    avg_price = nilai_beli / transaksi_beli['masuk'].sum()
                else:
                    avg_price = 0
                
                # Ambil ID terakhir (sembarang aja buat referensi)
                last_id = group['id'].iloc[-1]
                
                stok_list.append({
                    'id': int(last_id), 
                    'item': nama_ikan,      # [PENTING] Kita rename jadi 'item' biar HTML kebaca
                    'kategori': 'Ikan Koi', # Default kategori
                    'stok_akhir': int(sisa), 
                    'harga_rata_rata': int(avg_price)
                })
        return stok_list
    except Exception as e: 
        print(f"Error hitung stok: {e}")
        return []
    
def get_kartu_stok(user_id):
    """Ambil riwayat kartu stok langsung dari tabel persediaan"""
    try:
        # 1. Ambil Stok Terkini dulu (Dictionary: Nama Ikan -> Sisa Stok)
        # Gunanya biar kita bisa nampilin sisa stok di setiap baris
        data_stok = hitung_stok_akhir(user_id)
        dict_sisa = {x['item']: x['stok_akhir'] for x in data_stok}

        # 2. Ambil History Transaksi
        res = supabase.from_("persediaan").select("*").eq("user_id", user_id).order("tanggal", desc=True).execute()
        data_history = res.data if res.data else []

        # 3. [FIX] Mapping Data biar HTML paham
        processed_data = []
        for row in data_history:
            # KUNCI 1: HTML minta 'item', DB punya 'barang'. Kita samain.
            nama_barang = row.get('barang', '-')
            row['item'] = nama_barang 
            
            # KUNCI 2: HTML minta 'sisa'. Kita ambil dari kamus yg kita hitung di atas.
            row['sisa'] = dict_sisa.get(nama_barang, 0)
            
            # Rapikan tampilan None jadi strip
            if not row.get('deskripsi'): row['deskripsi'] = '-'
            if not row.get('keterangan'): row['keterangan'] = '-'
            
            processed_data.append(row)

        return processed_data

    except Exception as e:
        print(f"Error get kartu stok: {e}")
        return []
            
def update_persediaan(tanggal, deskripsi, barang, jenis, kuantitas, keterangan, user_id, ref_tipe=None, ref_id=None):
    """Update stok persediaan dan return sisa stok"""
    try:
        # Hitung stok sisa terakhir
        last_stock = supabase.from_("persediaan")\
            .select("sisa")\
            .eq("user_id", user_id)\
            .eq("barang", barang)\
            .order("tanggal", desc=True)\
            .limit(1)\
            .execute()
        
        stok_sisa = last_stock.data[0]['sisa'] if last_stock.data else 0
        
        # Hitung sisa baru
        if jenis == 'masuk':
            stok_baru = stok_sisa + kuantitas
            masuk = kuantitas
            keluar = 0
        else:  # keluar
            if stok_sisa < kuantitas:
                raise ValueError(f"Stok {barang} tidak mencukupi. Stok tersedia: {stok_sisa}")
            stok_baru = stok_sisa - kuantitas
            masuk = 0
            keluar = kuantitas
        
        # Simpan ke persediaan
        data = {
            "tanggal": tanggal,
            "deskripsi": deskripsi,
            "barang": barang,
            "masuk": masuk,
            "keluar": keluar,
            "sisa": stok_baru,
            "keterangan": keterangan,
            "user_id": user_id,
            # Tambahkan referensi ke transaksi asal (pemasukan/pengeluaran)
            "ref_tipe": ref_tipe, 
            "ref_id": ref_id
        }
        
        supabase.from_("persediaan").insert(data).execute()
        return stok_baru
        
    except Exception as e:
        print(f"Error update_persediaan: {e}")
        raise e

def get_stok_terkini(user_id, barang=None):
    """
    Dapatkan stok terkini dengan menghitung ulang (Total Masuk - Total Keluar).
    Dijamin selaras dengan halaman Persediaan.
    """
    try:
        # Ambil semua data persediaan
        query = supabase.from_("persediaan").select("barang, masuk, keluar").eq("user_id", user_id)
        if barang:
            query = query.eq("barang", barang)
        
        response = query.execute()
        
        stok_data = {}
        if response.data:
            df = pd.DataFrame(response.data)
            
            # Pastikan angka aman
            df['masuk'] = pd.to_numeric(df['masuk']).fillna(0)
            df['keluar'] = pd.to_numeric(df['keluar']).fillna(0)
            
            # Hitung total per barang
            for nama_ikan, group in df.groupby('barang'):
                total_stok = int(group['masuk'].sum() - group['keluar'].sum())
                stok_data[nama_ikan] = total_stok
                
        return stok_data
    except Exception as e:
        print(f"Error get_stok: {e}")
        return {}
            
def hitung_hpp_rata_rata(user_id, barang):
    """Hitung HPP rata-rata untuk barang tertentu"""
    try:
        # Ambil semua transaksi masuk untuk barang
        response = supabase.from_("persediaan")\
            .select("masuk, harga_satuan")\
            .eq("user_id", user_id)\
            .eq("barang", barang)\
            .gt("masuk", 0)\
            .execute()
        
        if not response.data:
            return 0
            
        total_kuantitas = sum(item['masuk'] for item in response.data)
        total_nilai = sum(item['masuk'] * item.get('harga_satuan', 0) for item in response.data)
        
        return total_nilai / total_kuantitas if total_kuantitas > 0 else 0
        
    except Exception as e:
        print(f"Error hitung_hpp_rata_rata: {e}")
        return 0

def get_riwayat_persediaan(user_id, limit=50):
    """Get riwayat persediaan terbaru"""
    try:
        response = supabase.from_("persediaan")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("tanggal", desc=True)\
            .limit(limit)\
            .execute()
        
        if response.data:
            # Format tanggal untuk display
            for item in response.data:
                if 'tanggal' in item:
                    # Convert to string format for template
                    item['tanggal'] = item['tanggal'][:19]  # ambil YYYY-MM-DD HH:MM:SS
            return response.data
        else:
            return []
            
    except Exception as e:
        print(f"Error get_riwayat_persediaan: {e}")
        return []
    
def get_integrated_financial_data(user_id, start_date, end_date):
    """Mengintegrasikan semua data keuangan untuk laporan yang komprehensif"""
    try:
        # Load semua data yang diperlukan
        jurnal_df = load_data_from_db("jurnal", user_id)
        pemasukan_df = load_data_from_db("pemasukan", user_id)
        pengeluaran_df = load_data_from_db("pengeluaran", user_id)
        persediaan_df = load_data_from_db("persediaan", user_id)
        aset_df = load_data_from_db("aset_tetap", user_id)
        
        # Filter berdasarkan tanggal
        def filter_by_date(df, start, end, date_col='Tanggal'):
            if df.empty:
                return pd.DataFrame()
            mask = (df[date_col] >= start) & (df[date_col] <= end)
            return df.loc[mask]
        
        # Data terfilter
        jurnal_filtered = filter_by_date(jurnal_df, start_date, end_date)
        pemasukan_filtered = filter_by_date(pemasukan_df, start_date, end_date)
        pengeluaran_filtered = filter_by_date(pengeluaran_df, start_date, end_date)
        persediaan_filtered = filter_by_date(persediaan_df, start_date, end_date)
        
        # Hitung metrics terintegrasi
        integrated_data = {
            # Ringkasan
            'total_pemasukan': pemasukan_filtered['Jumlah'].sum() if not pemasukan_filtered.empty else 0,
            'total_pengeluaran': pengeluaran_filtered['Jumlah'].sum() if not pengeluaran_filtered.empty else 0,
            'laba_rugi_bersih': 0,
            
            # Buku Besar
            'buku_besar': {},
            'buku_besar_piutang': [],
            'buku_besar_hutang': [],
            
            # Persediaan
            'nilai_persediaan': 0,
            'perputaran_stok': 0,
            
            # Aset
            'nilai_aset_tetap': aset_df['harga_perolehan'].sum() if not aset_df.empty else 0,
            'akumulasi_penyusutan': 0,
            
            # Rasio Keuangan
            'rasio_likuiditas': 0,
            'rasio_profitabilitas': 0
        }
        
        # Hitung laba rugi dari jurnal
        if not jurnal_filtered.empty:
            pendapatan = jurnal_filtered[
                jurnal_filtered['Akun'].str.contains('Penjualan|Pendapatan', na=False)
            ]['Kredit'].sum()
            
            beban = jurnal_filtered[
                jurnal_filtered['Akun'].str.contains('Beban', na=False)
            ]['Debit'].sum()
            
            hpp = jurnal_filtered[
                jurnal_filtered['Akun'] == 'Harga Pokok Penjualan'
            ]['Debit'].sum()
            
            integrated_data['laba_rugi_bersih'] = pendapatan - beban - hpp
        
        return integrated_data
        
    except Exception as e:
        print(f"Error in financial data integration: {e}")
        return {}    
    
# --- GANTI TOTAL FUNGSI INI DI app.py (Helper Functions) ---

def aggregate_subsidiary_ledger(jurnal_total):
    """Menghitung saldo akhir Piutang/Utang per kontak dari semua jurnal."""
    
    # Pastikan data jurnal sudah bersih dan numerik
    jurnal_total['Debit'] = pd.to_numeric(jurnal_total['Debit'], errors='coerce').fillna(0)
    jurnal_total['Kredit'] = pd.to_numeric(jurnal_total['Kredit'], errors='coerce').fillna(0)
    
    piutang_grouped = {}
    utang_grouped = {}

    # Filter hanya Piutang dan Utang
    df_kontak = jurnal_total[jurnal_total['Akun'].isin(['Piutang Dagang', 'Utang Dagang'])].copy()
    
    if df_kontak.empty:
        return {'piutang': [], 'utang': []}

    # Grouping dan Perhitungan Saldo
    for kontak, group in df_kontak.groupby('Kontak'):
        if not kontak or kontak == 'Saldo Awal': 
            continue
            
        group = group.sort_values('Tanggal')
        
        saldo_berjalan_piutang = 0
        saldo_berjalan_utang = 0
        
        for index, row in group.iterrows():
            nilai_bersih = row['Debit'] - row['Kredit']
            tanggal_str = row['Tanggal'].strftime('%d-%m-%Y')
            
            if row['Akun'] == 'Piutang Dagang':
                saldo_berjalan_piutang += nilai_bersih
                # Update saldo Piutang (hanya simpan saldo terakhir)
                piutang_grouped[kontak] = {'saldo': float(saldo_berjalan_piutang), 'last_date': tanggal_str}

            elif row['Akun'] == 'Utang Dagang':
                # Utang saldo normalnya Kredit, kita balik nilainya
                saldo_berjalan_utang += -nilai_bersih
                # Update saldo Utang (hanya simpan saldo terakhir)
                utang_grouped[kontak] = {'saldo': float(saldo_berjalan_utang), 'last_date': tanggal_str}

    # --- PERBAIKAN KRITIS: FILTER SALDO NOL ---
    # Konversi ke format list dan HANYA SERTAKAN JIKA SALDO AKHIR TIDAK NOL
    
    final_piutang = []
    for k, v in piutang_grouped.items():
        if abs(v['saldo']) > 1.0: # Gunakan toleransi kecil (1.0) untuk menghindari error float
            final_piutang.append({'kontak': k, 'saldo': v['saldo'], 'last_date': v['last_date']})

    final_utang = []
    for k, v in utang_grouped.items():
        if abs(v['saldo']) > 1.0:
            # Utang selalu tampil positif di Neraca, jadi gunakan abs() atau konversi
            final_utang.append({'kontak': k, 'saldo': abs(v['saldo']), 'last_date': v['last_date']})
                   
    return {'piutang': final_piutang, 'utang': final_utang}

def hapus_penyusutan_db(aset_id, periode_str, user_id):
    """Menghapus jurnal penyusutan untuk aset dan periode tertentu, lalu mereset status aset."""
    try:
        periode_dt = datetime.strptime(periode_str, "%Y-%m")
        akhir_bulan_str = (periode_dt + relativedelta(months=1) - relativedelta(days=1)).strftime("%Y-%m-%d")
        
        # 1. Ambil data aset untuk akun yang benar
        aset_res = supabase.from_("aset_tetap").select("akun_beban, akun_akumulasi, id").eq("id", aset_id).single().execute()
        aset = aset_res.data
        
        if not aset:
            raise ValueError("Aset tidak ditemukan.")

        akun_beban = aset['akun_beban']
        akun_akumulasi = aset['akun_akumulasi']
        
        # 2. Hapus Jurnal Penyusutan dari tabel 'jurnal'
        keterangan_target = f"Penyusutan {aset.get('nama_aset', 'Aset')} {periode_str}"
        
        delete_response = supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Tanggal": akhir_bulan_str,
            "Akun": akun_beban, # Targetkan Jurnal Beban Penyusutan
            "Keterangan": keterangan_target
        }).execute()

        # (Asumsi: Jika jurnal beban terhapus, jurnal akumulasi pasangannya juga harus dihapus, 
        # kita coba hapus yang akumulasi secara eksplisit juga)
        
        delete_response_akumulasi = supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Tanggal": akhir_bulan_str,
            "Akun": akun_akumulasi, # Targetkan Jurnal Akumulasi Penyusutan
            "Keterangan": keterangan_target
        }).execute()
        
        # 3. Reset Status Aset di tabel 'aset_tetap'
        
        # Hitung bulan sebelumnya
        prev_month_dt = periode_dt - relativedelta(months=1)
        
        # Kita set bulan terakhir disusutkan ke bulan sebelumnya (atau None jika belum pernah disusutkan)
        # Ambil tanggal terakhir bulan sebelumnya
        prev_akhir_bulan = (prev_month_dt + relativedelta(months=1) - relativedelta(days=1)).strftime("%Y-%m-%d")

        supabase.from_("aset_tetap").update({
            "bulan_terakhir_disusutkan": prev_akhir_bulan
        }).eq("id", aset_id).execute()
        
        return True
        
    except Exception as e:
        print(f"Error hapus_penyusutan_db: {e}")
        raise e  
    
def hapus_aset_db(aset_id, user_id):
    """Menghapus aset, semua jurnal penyusutan terkait, dan jurnal pembelian aset."""
    try:
        # 1. Ambil data aset yang akan dihapus
        aset_res = supabase.from_("aset_tetap").select("*").eq("id", aset_id).single().execute()
        aset = aset_res.data
        
        if not aset:
            raise ValueError("Aset tidak ditemukan.")

        akun_aset = aset['akun_aset']
        akun_beban = aset['akun_beban']
        akun_akumulasi = aset['akun_akumulasi']
        nama_aset = aset['nama_aset']

        # 2. Hapus Jurnal Penyusutan (Beban dan Akumulasi)
        keterangan_susut_search = f"Penyusutan {nama_aset}"
        
        # Hapus Jurnal Beban Penyusutan
        supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Akun": akun_beban,
            "Keterangan": keterangan_susut_search
        }).ilike("Keterangan", f"%{keterangan_susut_search}%").execute()

        # Hapus Jurnal Akumulasi Penyusutan
        supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Akun": akun_akumulasi,
            "Keterangan": keterangan_susut_search
        }).ilike("Keterangan", f"%{keterangan_susut_search}%").execute()
        
        # 3. Hapus Jurnal Pembelian Aset
        keterangan_beli_search = f"Beli Aset {nama_aset}"
        
        # Hapus Jurnal Debit (Akun Aset)
        supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Akun": akun_aset,
            "Keterangan": keterangan_beli_search
        }).execute()
        
        # Hapus Jurnal Kredit (Akun Kas/Bank/Utang) - Hanya Hapus jika Keterangan cocok
        supabase.from_("jurnal").delete().match({
            "user_id": user_id,
            "Keterangan": keterangan_beli_search
        }).execute()
        
        # 4. Hapus Aset dari tabel 'aset_tetap'
        supabase.from_("aset_tetap").delete().eq("id", aset_id).execute()
        
        return True
        
    except Exception as e:
        print(f"Error hapus_aset_db: {e}")
        raise e    
    
# --- Akhir Helper Functions ---

# Tambahkan di sebelum dekorator routes
@app.before_request
def log_request_info():
    print(f"📨 Request: {request.method} {request.path}")

# ---------------- Decorator (GANTI TOTAL) ----------------  
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Cek dasar: jika tidak ada access_token, langsung redirect
        if 'access_token' not in session:
            session.clear()
            flash("Sesi tidak valid. Harap login ulang.", "danger")
            return redirect(url_for('login_page'))
        
        # Jika sudah ada user_id di session, skip validasi Supabase untuk performa
        # Hanya validasi jika diperlukan (misalnya setiap 5 menit sekali)
        if 'user_id' in session and 'last_validated' in session:
            # Validasi ulang setiap 5 menit (300 detik)
            if time.time() - session.get('last_validated', 0) < 300:
                return f(*args, **kwargs)
        
        try:
            # 1. Set Session Supabase
            supabase.auth.set_session(
                session['access_token'], 
                session.get('refresh_token')
            )
            response = supabase.auth.get_user()
            
            if not response or not response.user:
                raise Exception("Token tidak valid atau sudah kedaluwarsa.")
                
            # Update session
            session['user_id'] = response.user.id
            session['last_validated'] = time.time() if 'time' in dir() else 0
            
            # 2. PERBAIKAN: Mengunci Username (Mengatasi sapaan email)
            if 'username' not in session or '@' in session.get('username', ''):
                try:
                    user_id = response.user.id
                    user_email = response.user.email
                    profile_res = supabase.from_("profiles").select("username").eq("id", user_id).single().execute()
                    
                    if profile_res.data and profile_res.data.get('username'):
                        session['username'] = profile_res.data['username']
                    else:
                        session['username'] = user_email 
                except Exception as e:
                    print(f"⚠️ Gagal ambil username dari 'profiles' (fallback): {e}")
                    session['username'] = response.user.email

            if 'logged_in' not in session:
                session['logged_in'] = True

        except Exception as e:
            print(f"⚠️ Error validasi session di decorator: {e}")
            # PERBAIKAN: Jangan langsung redirect jika user_id masih ada di session
            # Mungkin hanya masalah koneksi sementara ke Supabase
            if 'user_id' in session:
                print("⚠️ Menggunakan session yang ada karena error validasi mungkin sementara")
                # Biarkan request lanjut dengan session yang ada
                return f(*args, **kwargs)
            else:
                # Baru redirect jika benar-benar tidak ada session
                session.clear()
                flash("Sesi Anda telah berakhir. Harap login ulang.", "danger")
                return redirect(url_for('login_page'))
        
        return f(*args, **kwargs)
    return decorated_function

# ---------------- KUMPULAN TEMPLATE HTML ----------------

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - Koilume</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * {
            box-sizing: border-box;
        }
        
        body { 
            font-family: 'Inter', sans-serif; 
            background: #f8fafc;
            min-height: 100vh;
            margin: 0;
            padding: 0;
        }
        
        /* Elegant Red Navigation */
        .nav-red-elegant { 
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            box-shadow: 0 4px 20px rgba(220, 38, 38, 0.15);
        }
        
        /* White Content Cards */
        .card-white {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
            transition: all 0.3s ease;
        }
        
        .card-white:hover {
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
            transform: translateY(-2px);
        }
        
        /* PERBAIKAN: Tombol yang konsisten */
        .btn-consistent {
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            min-height: 44px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            color: white;
        }
        
        .btn-primary:hover {
            background: linear-gradient(135deg, #b91c1c 0%, #991b1b 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);
        }
        
        .btn-secondary {
            background: #6b7280;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #4b5563;
            transform: translateY(-2px);
        }
        
        .nav-btn-elegant { 
            padding: 12px 16px; 
            border-radius: 8px; 
            font-weight: 500; 
            font-size: 14px;
            transition: all 0.3s ease; 
            display: flex; 
            align-items: center; 
            gap: 10px;
            color: white;
            position: relative;
            overflow: hidden;
            min-height: 44px;
        }
        
        .nav-btn-elegant::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
            transition: left 0.5s;
        }
        
        .nav-btn-elegant:hover::before {
            left: 100%;
        }
        
        .nav-btn-elegant:hover { 
            background: rgba(255,255,255,0.12); 
            transform: translateY(-1px);
        }
        
        .dropdown-elegant {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            z-index: 1000;
        }
        
        .dropdown-item-elegant { 
            display: flex;
            align-items: center;
            padding: 14px 16px; 
            color: #374151; 
            font-size: 14px; 
            transition: all 0.2s ease;
            border-bottom: 1px solid #f3f4f6;
            min-height: 50px;
        }
        
        .dropdown-item-elegant:last-child {
            border-bottom: none;
        }
        
        .dropdown-item-elegant:hover { 
            background: #fef2f2;
            color: #dc2626;
            padding-left: 20px;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .animate-fade-in {
            animation: fadeIn 0.4s ease-out;
        }
        
        /* Custom Scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: #f1f5f9;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 3px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }
        
        /* Active State untuk Nav */
        .nav-active {
            background: rgba(255,255,255,0.15);
            font-weight: 600;
        }
        
        /* Stat Cards */
        .stat-card {
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            border: 1px solid #e5e7eb;
            text-align: center;
            transition: transform 0.3s ease;
            height: 100%;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        /* Chart Styles */
        .chart-container {
            position: relative;
            height: 400px;
            background: white;
            border-radius: 12px;
            padding: 20px;
        }
        
        /* Loading Animation */
        .loading-spinner {
            border: 3px solid #f3f4f6;
            border-top: 3px solid #dc2626;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        /* Table Improvements */
        .table-hover tbody tr:hover {
            background-color: #f8fafc;
        }
        
        /* Print Styles */
        @media print {
            nav, .no-print { 
                display: none !important; 
            }
        }
        
        /* Responsive Design */
        @media (max-width: 768px) {
            .nav-btn-elegant span {
                display: none;
            }
            
            .btn-consistent {
                padding: 10px 16px;
                font-size: 13px;
            }
        }
    </style>
</head>
<body class="min-h-screen flex flex-col">
    <nav class="nav-red-elegant sticky top-0 z-50 no-print">
        <div class="max-w-7xl mx-auto px-4">
            <div class="flex justify-between h-20 items-center">
                <a href="/" class="flex items-center space-x-3 group">
                    <div class="w-12 h-12 bg-white rounded-2xl flex items-center justify-center group-hover:scale-105 transition-transform shadow-lg">
                        <i class="fas fa-fish text-red-600 text-xl font-bold"></i>
                    </div>
                    <div class="text-white">
                        <span class="text-xl font-bold tracking-tight">Koilume</span>
                        <p class="text-red-100 text-xs">Sistem Akuntansi Profesional</p>
                    </div>
                </a>
                
                <div class="flex items-center space-x-1">
                    {% if session.logged_in %}
                        <a href="/" class="nav-btn-elegant {% if request.path == '/' %}nav-active{% endif %}">
                            <i class="fas fa-home text-lg"></i>
                            <span class="hidden sm:inline">Dashboard</span>
                        </a>
                        
                        <div class="relative group">
                            <button class="nav-btn-elegant {% if 'pemasukan' in request.path or 'pengeluaran' in request.path or 'kelola' in request.path %}nav-active{% endif %}">
                                <i class="fas fa-exchange-alt text-lg"></i>
                                <span class="hidden sm:inline">Transaksi</span>
                                <i class="fas fa-chevron-down text-xs ml-1"></i>
                            </button>
                            <div class="dropdown-elegant absolute top-full left-0 w-64 hidden group-hover:block"> 
                                <a href="{{ url_for('pemasukan_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-arrow-down text-green-500 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Pemasukan</div>
                                        <div class="text-xs text-gray-500">Penjualan & Pendapatan</div>
                                    </div>
                                </a>
                                <a href="{{ url_for('pengeluaran_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-arrow-up text-red-500 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Pengeluaran</div>
                                        <div class="text-xs text-gray-500">Beban & Pembelian</div>
                                    </div>
                                </a>
                                
                                <div class="border-t border-gray-100 my-1"></div>
                                <a href="{{ url_for('pelunasan_piutang_page') }}" class="dropdown-item-elegant bg-blue-50 hover:bg-blue-100">
                                    <i class="fas fa-handshake text-blue-600 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Pelunasan Piutang</div>
                                        <div class="text-xs text-gray-500">Klien Bayar Hutang ke Kita</div>
                                    </div>
                                </a>
                                <a href="{{ url_for('pelunasan_utang_page') }}" class="dropdown-item-elegant bg-orange-50 hover:bg-orange-100">
                                    <i class="fas fa-money-check-alt text-orange-600 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Pelunasan Utang</div>
                                        <div class="text-xs text-gray-500">Kita Bayar Hutang ke Supplier</div>
                                    </div>
                                </a>
                                <div class="border-t border-gray-100 my-1"></div>
                                
                                <a href="{{ url_for('kelola_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-history text-blue-500 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Riwayat</div>
                                        <div class="text-xs text-gray-500">Kelola Data Transaksi</div>
                                    </div>
                                </a>
                            </div>
                        </div>

                        <a href="{{ url_for('persediaan_page') }}" class="nav-btn-elegant {% if 'persediaan' in request.path %}nav-active{% endif %}">
                            <i class="fas fa-boxes text-lg"></i>
                            <span class="hidden sm:inline">Persediaan</span>
                        </a>

                        <div class="relative group">
                            <button class="nav-btn-elegant {% if 'aset' in request.path %}nav-active{% endif %}">
                                <i class="fas fa-building text-lg"></i>
                                <span class="hidden sm:inline">Aset</span>
                                <i class="fas fa-chevron-down text-xs ml-1"></i>
                            </button>
                            <div class="dropdown-elegant absolute top-full left-0 w-56 hidden group-hover:block">
                                <a href="{{ url_for('aset_tetap_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-plus text-purple-500 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Aset Tetap</div>
                                        <div class="text-xs text-gray-500">Tambah & Kelola Aset</div>
                                    </div>
                                </a>
                                <a href="{{ url_for('proses_penyusutan_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-calculator text-yellow-500 text-lg w-6 mr-3"></i>
                                    <div>
                                        <div class="font-semibold">Penyusutan</div>
                                        <div class="text-xs text-gray-500">Proses Depresiasi</div>
                                    </div>
                                </a>
                            </div>
                        </div>
                        
                        <a href="{{ url_for('laporan_page') }}" class="nav-btn-elegant {% if 'laporan' in request.path %}nav-active{% endif %}">
                            <i class="fas fa-chart-bar text-lg"></i>
                            <span class="hidden sm:inline">Laporan</span>
                        </a>

                        <div class="relative group">
                            <button class="nav-btn-elegant">
                                <i class="fas fa-user-circle text-lg"></i>
                                <span class="hidden sm:inline">{{ session.username[:12] }}{% if session.username|length > 12 %}...{% endif %}</span>
                                <i class="fas fa-chevron-down text-xs ml-1 hidden sm:inline"></i>
                            </button>
                            <div class="dropdown-elegant absolute top-full right-0 w-48 hidden group-hover:block">
                                <div class="px-4 py-3 border-b border-gray-100">
                                    <p class="font-semibold text-gray-900">{{ session.username }}</p>
                                    <p class="text-xs text-gray-500">User aktif</p>
                                </div>
                                <a href="{{ url_for('setup_saldo_page') }}" class="dropdown-item-elegant">
                                    <i class="fas fa-cog text-gray-500 text-lg w-6 mr-3"></i>
                                    Setup Saldo
                                </a>
                                <a href="{{ url_for('logout_page') }}" class="dropdown-item-elegant text-red-600">
                                    <i class="fas fa-sign-out-alt text-lg w-6 mr-3"></i>
                                    Logout
                                </a>
                            </div>
                        </div>

                    {% else %}
                        <a href="{{ url_for('login_page') }}" class="btn-consistent btn-primary">
                            <i class="fas fa-sign-in-alt mr-2"></i>
                            <span>Login</span>
                        </a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>

    <main class="flex-1 bg-gray-50">
        <div class="max-w-7xl mx-auto px-4 py-8">
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="mb-6 p-4 rounded-xl border-l-4 flex items-center gap-4 animate-fade-in {% if category == 'success' %}bg-green-50 border-green-500 text-green-800{% else %}bg-red-50 border-red-500 text-red-800{% endif %}">
                    <i class="fas {% if category == 'success' %}fa-check-circle text-green-500{% else %}fa-exclamation-triangle text-red-500{% endif %} text-xl"></i>
                    <div class="flex-1">
                      <span class="font-semibold">{{ message }}</span>
                    </div>
                    <button onclick="this.parentElement.remove()" class="text-gray-500 hover:text-gray-700">
                      <i class="fas fa-times"></i>
                    </button>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            {% block content %}{% endblock %}
        </div>
    </main>

    <footer class="bg-white border-t border-gray-200 py-8 no-print">
        <div class="max-w-7xl mx-auto px-4">
            <div class="flex flex-col md:flex-row justify-between items-center">
                <div class="flex items-center space-x-3 mb-4 md:mb-0">
                    <div class="w-10 h-10 bg-red-100 rounded-xl flex items-center justify-center">
                        <i class="fas fa-fish text-red-600"></i>
                    </div>
                    <div>
                        <span class="text-gray-900 font-bold">Koilume</span>
                        <p class="text-gray-500 text-sm">Sistem Akuntansi Ikan Koi</p>
                    </div>
                </div>
                
                <div class="flex space-x-6 text-gray-400">
                    <a href="#" class="hover:text-red-600 transition-colors" title="GitHub">
                        <i class="fab fa-github text-lg"></i>
                    </a>
                    <a href="#" class="hover:text-red-600 transition-colors" title="Documentation">
                        <i class="fas fa-book text-lg"></i>
                    </a>
                    <a href="#" class="hover:text-red-600 transition-colors" title="Support">
                        <i class="fas fa-life-ring text-lg"></i>
                    </a>
                </div>
            </div>
            
            <div class="border-t border-gray-100 mt-6 pt-6 text-center">
                <p class="text-gray-400 text-sm">
                    &copy; 2025 Koilume System. All rights reserved. 
                    <span class="text-red-500">❤</span> Built with Passion for Koi Business
                </p>
            </div>
        </div>
    </footer>

    <script>
        // Fungsi untuk format Rupiah saat input
        function formatRupiah(e){
            let v = e.value.replace(/[^,\d]/g,'').toString(),
                s = v.split(','),
                r = s[0].substr(0, s[0].length % 3),
                rib = s[0].substr(s[0].length % 3).match(/\d{3}/gi);
                
            if(rib){
                let sep = s[0].length % 3 ? '.' : '';
                r += sep + rib.join('.');
            }
            r = s[1] != undefined ? r + ',' + s[1] : r;
            e.value = r;
        }

        // FUNGSI KRITIS: Mengatur visibilitas field kontak untuk Piutang/Utang
        function toggleKontakInput(name, id){
            const el = document.getElementById(id);
            if(!el) return;

            // KUNCI PERBAIKAN: Mengambil nilai dari elemen <select> (dropdown), bukan radio buttons.
            const selectElement = document.getElementsByName(name)[0];
            let selectedValue = selectElement ? selectElement.value : '';
            
            // Tampilkan jika nilai yang dipilih adalah 'Piutang' atau 'Utang'
            el.style.display = (selectedValue === 'Piutang' || selectedValue === 'Utang') ? 'block' : 'none';
        }

        // Auto-hide flash messages after 5 seconds
        document.addEventListener('DOMContentLoaded', function() {
            // KITA GANTI SELECTORNYA JADI LEBIH SPESIFIK:
            const flashMessages = document.querySelectorAll('.flash-message'); 
            flashMessages.forEach(message => {
                setTimeout(() => {
                    message.style.opacity = '0';
                    message.style.transform = 'translateY(-10px)';
                    setTimeout(() => message.remove(), 300);
                }, 5000);
            });
        });

        // Print functionality
        function printReport() {
            window.print();
        }

        // Show loading spinner
        function showLoading() {
            const loading = document.createElement('div');
            loading.id = 'global-loading';
            loading.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
            loading.innerHTML = `
                <div class="bg-white p-6 rounded-lg flex items-center space-x-3">
                    <div class="loading-spinner"></div>
                    <span>Memproses...</span>
                </div>
            `;
            document.body.appendChild(loading);
        }

        // Hide loading spinner
        function hideLoading() {
            const loading = document.getElementById('global-loading');
            if (loading) {
                loading.remove();
            }
        }
    </script>
</body>
</html>
"""

HTML_INDEX = """
<div class="space-y-8 animate-fade-in">
    <div class="card-white p-8 text-center relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-red-50 to-white opacity-50"></div>
        <div class="relative">
            <h1 class="text-3xl font-bold text-gray-900 mb-2">
                Selamat Datang, <span class="text-red-600">{{ username }}!</span>
            </h1>
            <p class="text-gray-600 text-lg">Dashboard siap membantu kelola bisnis Koi Anda.</p>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        <a href="{{ url_for('pemasukan_page') }}" class="stat-card p-6 bg-green-50 border-green-300 hover:bg-green-100 group">
            <div class="w-16 h-16 bg-green-200 rounded-full flex items-center justify-center mx-auto mb-4 group-hover:scale-110 transition-transform">
                <i class="fas fa-arrow-down text-green-700 text-3xl"></i>
            </div>
            <h3 class="text-xl font-bold text-green-800 mb-1">INPUT PEMASUKAN</h3>
            <p class="text-sm text-gray-600">Jual ikan atau pendapatan lain</p>
        </a>
        
        <a href="{{ url_for('pengeluaran_page') }}" class="stat-card p-6 bg-red-50 border-red-300 hover:bg-red-100 group">
            <div class="w-16 h-16 bg-red-200 rounded-full flex items-center justify-center mx-auto mb-4 group-hover:scale-110 transition-transform">
                <i class="fas fa-arrow-up text-red-700 text-3xl"></i>
            </div>
            <h3 class="text-xl font-bold text-red-800 mb-1">INPUT PENGELUARAN</h3>
            <p class="text-sm text-gray-600">Beban, beli stok, atau bayar utang</p>
        </a>
        
        <a href="{{ url_for('laporan_page') }}" class="stat-card p-6 bg-blue-50 border-blue-300 hover:bg-blue-100 group">
            <div class="w-16 h-16 bg-blue-200 rounded-full flex items-center justify-center mx-auto mb-4 group-hover:scale-110 transition-transform">
                <i class="fas fa-chart-bar text-blue-700 text-3xl"></i>
            </div>
            <h3 class="text-xl font-bold text-blue-800 mb-1">CEK LAPORAN</h3>
            <p class="text-sm text-gray-600">Lihat Laba/Rugi & Neraca</p>
        </a>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        <div class="card-white p-6 lg:col-span-2">
            <div class="flex items-center justify-between mb-6 border-b pb-3">
                <h2 class="text-xl font-bold text-gray-900 flex items-center gap-3">
                    <i class="fas fa-boxes text-red-600"></i>
                    Stok Ikan Kritis
                </h2>
                <a href="{{ url_for('persediaan_page') }}" class="text-sm text-red-600 font-medium hover:underline">
                    Kelola Stok <i class="fas fa-chevron-right ml-1"></i>
                </a>
            </div>
            
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                {% for barang, stok in stok_terkini.items() %}
                <div class="text-center p-4 rounded-xl border-2 transition-all hover:scale-105 {% if stok <= 5 %}border-red-300 bg-red-50{% else %}border-green-300 bg-green-50{% endif %}">
                    <div class="text-xl font-bold {% if stok <= 5 %}text-red-700{% else %}text-green-700{% endif %}">{{ stok }}</div>
                    <div class="text-sm text-gray-600 mt-1">{{ barang }}</div>
                    {% if stok <= 5 %}
                    <div class="text-xs text-red-600 font-medium mt-2 flex items-center justify-center gap-1">
                        <i class="fas fa-exclamation-triangle"></i>
                        RESTOCK
                    </div>
                    {% endif %}
                </div>
                {% else %}
                <div class="col-span-4 text-center py-8 text-gray-400">
                    <i class="fas fa-box-open text-4xl mb-3"></i>
                    <p class="text-lg">Belum ada data stok</p>
                    <p class="text-sm mt-1">Input pembelian pertama di Pengeluaran</p>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="card-white p-6 lg:col-span-1">
            <h2 class="text-xl font-bold text-gray-900 mb-6 flex items-center gap-3 border-b pb-3">
                <i class="fas fa-cog text-blue-600"></i>
                Pengaturan & Aset
            </h2>
            
            <div class="space-y-4">
                <a href="{{ url_for('setup_saldo_page') }}" class="flex items-center p-3 rounded-lg border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 transition-all group">
                    <div class="w-10 h-10 bg-indigo-100 rounded-md flex items-center justify-center mr-3">
                        <i class="fas fa-plus text-indigo-600"></i>
                    </div>
                    <div class="flex-1">
                        <h3 class="font-semibold text-gray-900">Setup Saldo Awal</h3>
                    </div>
                    <i class="fas fa-chevron-right text-gray-400 group-hover:text-indigo-600"></i>
                </a>
                
                <a href="{{ url_for('aset_tetap_page') }}" class="flex items-center p-3 rounded-lg border border-gray-200 hover:border-purple-300 hover:bg-purple-50 transition-all group">
                    <div class="w-10 h-10 bg-purple-100 rounded-md flex items-center justify-center mr-3">
                        <i class="fas fa-building text-purple-600"></i>
                    </div>
                    <div class="flex-1">
                        <h3 class="font-semibold text-gray-900">Aset Tetap & Susut</h3>
                    </div>
                    <i class="fas fa-chevron-right text-gray-400 group-hover:text-purple-600"></i>
                </a>
            </div>
        </div>
    </div>
</div>

<script>
// Load dashboard data (Script yang minimalis)
document.addEventListener('DOMContentLoaded', function() {
    // Fungsi showLoading dan hideLoading tetap berjalan
    // Kita tidak perlu memanggil AJAX loadDashboardData lagi
});
</script>
"""

HTML_PEMASUKAN = """
<div class="max-w-4xl mx-auto bg-white p-8 rounded-xl shadow-lg border border-green-100">
    <h2 class="text-2xl font-bold text-green-800 mb-6 flex items-center gap-2"><span>💰</span> Input Pemasukan</h2>
    
    <form method="POST" enctype="multipart/form-data" class="space-y-6">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Tanggal</label>
                <input type="date" name="tanggal" value="{{ today }}" required class="w-full border rounded p-2 focus:ring-2 focus:ring-green-500">
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Kategori Utama</label>
                <select name="sumber" id="sumber" required class="w-full border rounded p-2 focus:ring-2 focus:ring-green-500" onchange="cekIntegrasiStok()">
                    {% for k in kategori_pemasukan %}
                    <option value="{{ k }}" {% if k == 'Penjualan' %}selected{% endif %}>{{ k }}</option>
                    {% endfor %}
                </select>
            </div>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Detail Akun</label>
                <select name="sub_sumber" id="sub_sumber" required class="w-full border rounded p-2 focus:ring-2 focus:ring-green-500"></select>
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Total Uang (Rp)</label>
                <input type="text" id="total_uang" name="jumlah" onkeyup="formatRupiah(this)" required class="w-full border rounded p-2 font-bold text-green-700 bg-gray-50" placeholder="Rp 0">
            </div>
        </div>

        <div id="box_stok_keluar" class="bg-green-50 p-5 rounded-lg border border-green-200 hidden animate-[fadeIn_0.3s_ease-out]">
            <div class="flex items-center gap-2 mb-3 text-green-800 font-bold border-b border-green-200 pb-2">
                <span>📦</span> Data Penjualan (Potong Stok)
            </div>
            <div class="grid grid-cols-3 gap-3">
                <div class="col-span-3">
                    <label class="block text-xs font-medium mb-1">Pilih Ikan (Stok Tersedia)</label>
                    <select name="stok_item_id" id="barang" class="w-full border rounded p-2 bg-white focus:ring-2 focus:ring-green-500">
                        <option value="">-- Pilih Ikan --</option>
                        {% for item in stok_list %}
                            {% if item.stok_akhir > 0 %}
                            <option value="{{ item.id }}">{{ item.item }} (Sisa: {{ "%.1f"|format(item.stok_akhir) }})</option>
                            {% endif %}
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label class="block text-xs font-medium mb-1">Qty Jual (Ekor)</label>
                    <input type="number" id="qty_jual" name="stok_qty" min="0" step="1" class="w-full border rounded p-2 focus:ring-2 focus:ring-green-500" placeholder="0" oninput="hitungJual()">
                </div>
                <div class="col-span-2">
                    <label class="block text-xs font-medium mb-1">Harga Jual per Ekor (Rp)</label>
                    <input type="text" id="hrg_jual" class="w-full border rounded p-2 focus:ring-2 focus:ring-green-500" placeholder="Rp 0" onkeyup="formatRupiah(this); hitungJual()">
                </div>
            </div>
            <p class="text-xs text-green-600 mt-2 italic">*Total Uang akan terisi otomatis (Qty x Harga).</p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Metode</label>
                <select name="metode_pemasukan" id="metode_pemasukan" class="w-full border rounded p-2" onchange="toggleKontakInput('metode_pemasukan', 'k_pem')">
                    <option value="Tunai">Tunai</option>
                    <option value="Transfer">Transfer</option>
                    <option value="Piutang">Piutang</option>
                </select>
            </div>
            <div id="k_pem" style="display:none">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Nama Pelanggan (Pengutang)</label>
                <input type="text" name="kontak" class="w-full border rounded p-2" placeholder="Nama Pelanggan">
            </div>
        </div>
        
        <textarea name="deskripsi" rows="2" class="w-full border rounded p-2" placeholder="Keterangan..."></textarea>

        <div class="bg-gray-50 p-3 rounded border border-dashed border-gray-300">
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Upload Bukti Transaksi</label>
            <input type="file" name="bukti" accept="image/*,application/pdf" class="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-full file:border-0
              file:text-xs file:font-semibold
              file:bg-green-50 file:text-green-700
              hover:file:bg-green-100
            "/>
        </div>

        <button type="submit" class="w-full bg-green-600 text-white font-bold py-3 rounded hover:bg-green-700 shadow transition transform hover:scale-105">SIMPAN PEMASUKAN</button>
    </form>
</div>

<script>
const katData={{ kategori_pemasukan|tojson }};
const sumberSel=document.getElementById('sumber');
const subSel=document.getElementById('sub_sumber');
const boxStok=document.getElementById('box_stok_keluar');

function cekIntegrasiStok(){ 
    const val=sumberSel.value; 
    subSel.innerHTML=''; 
    (katData[val]||[]).forEach(s=>{
        let o=document.createElement('option');
        o.text=s; o.value=s; subSel.add(o)
    }); 
    if(val === 'Penjualan') {
        boxStok.classList.remove('hidden');
    } else {
        boxStok.classList.add('hidden');
    }
}

function hitungJual(){ 
    const q=parseFloat(document.getElementById('qty_jual').value)||0;
    const h=parseFloat(document.getElementById('hrg_jual').value.replace(/[^0-9]/g,''))||0;
    const tot=q*h; 
    let rev=tot.toString().split('').reverse().join('').match(/\d{1,3}/g);
    rev = rev ? rev.join('.').split('').reverse().join('') : '0';
    document.getElementById('total_uang').value = tot > 0 ? 'Rp '+rev : ''; 
}

document.addEventListener('DOMContentLoaded', function() {
    cekIntegrasiStok();
    // Panggil fungsi toggle saat halaman dimuat untuk memastikan field Piutang/Utang disembunyikan/ditampilkan
    toggleKontakInput('metode_pemasukan', 'k_pem'); 
});

sumberSel.addEventListener('change', cekIntegrasiStok);
</script>
"""

HTML_PENGELUARAN = """
<div class="max-w-4xl mx-auto bg-white p-8 rounded-xl shadow-lg border border-red-100">
    <h2 class="text-2xl font-bold text-red-800 mb-6 flex items-center gap-2"><span>💸</span> Input Pengeluaran</h2>
    
    <form method="POST" enctype="multipart/form-data" class="space-y-6">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Tanggal</label>
                <input type="date" name="tanggal" value="{{ today }}" required class="w-full border rounded p-2">
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Kategori Utama</label>
                <select name="kategori" id="kategori" required class="w-full border rounded p-2" onchange="cekIntegrasiBeli()">
                    <option value="">-- Pilih Kategori --</option>
                    {% for k in kategori_pengeluaran %}
                    <option value="{{ k }}">{{ k }}</option>
                    {% endfor %}
                </select>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Detail Akun / Jenis</label>
                <select name="sub_kategori" id="sub_kategori" required class="w-full border rounded p-2" onchange="autoFillBarang()"></select>
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Total Uang Keluar (Rp)</label>
                <input type="text" id="total_biaya" name="jumlah" onkeyup="formatRupiah(this)" required class="w-full border rounded p-2 font-bold text-red-700" placeholder="Rp 0">
            </div>
        </div>

        <div id="box_stok_masuk" class="bg-red-50 p-5 rounded-lg border border-red-200 hidden animate-[fadeIn_0.3s_ease-out]">
            <div class="flex items-center gap-2 mb-3 text-red-800 font-bold border-b border-red-200 pb-2">
                <span>🐟</span> Data Stok Ikan Masuk
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                    <label class="block text-xs font-medium mb-1">Kategori Stok</label>
                    <input type="text" name="stok_kat" value="Ikan Koi" readonly class="w-full border rounded p-2 bg-gray-100 text-gray-500 cursor-not-allowed">
                </div>
                <div>
                    <label class="block text-xs font-medium mb-1">Jenis Ikan</label>
                    <input type="text" name="stok_nama" id="stok_nama" class="w-full border rounded p-2 bg-white font-bold" placeholder="Jenis Ikan">
                </div>
                <div>
                    <label class="block text-xs font-medium mb-1">Jumlah (Ekor)</label>
                    <input type="number" id="qty_beli" name="stok_qty" min="0" step="1" class="w-full border rounded p-2 bg-white" placeholder="0" oninput="hitungBeli()">
                </div>
            </div>
            <div class="mt-3">
                <label class="block text-xs font-medium mb-1">Harga Beli per Ekor (Otomatis)</label>
                <input type="text" id="hrg_beli" class="w-full border rounded p-2 bg-gray-100 text-gray-600" readonly placeholder="Rp 0">
                <p class="text-xs text-red-500 mt-1 italic">*Harga satuan dihitung dari (Total Uang / Jumlah Ekor)</p>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Metode Bayar</label>
                <select name="metode_pengeluaran" class="w-full border rounded p-2" onchange="toggleKontakInput('metode_pengeluaran', 'k_peng')">
                    <option value="Tunai">Tunai (Kas)</option>
                    <option value="Transfer">Transfer (Bank)</option>
                    <option value="Utang">Utang (Belum Bayar)</option>
                </select>
            </div>
            <div id="k_peng" style="display:none">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Supplier/Toko</label>
                <input type="text" name="kontak" class="w-full border rounded p-2">
            </div>
        </div>
        
        <textarea name="deskripsi" rows="2" class="w-full border rounded p-2" placeholder="Keterangan tambahan..."></textarea>

        <div class="bg-gray-50 p-3 rounded border border-dashed border-gray-300">
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Upload Bukti Transaksi</label>
            <input type="file" name="bukti" accept="image/*,application/pdf" class="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-full file:border-0
              file:text-xs file:font-semibold
              file:bg-red-50 file:text-red-700
              hover:file:bg-red-100
            "/>
        </div>

        <button class="w-full bg-red-600 text-white font-bold py-3 rounded hover:bg-red-700 transition">SIMPAN PENGELUARAN</button>
    </form>
</div>

<script>
const katDataPeng={{ kategori_pengeluaran|tojson }}, katSel=document.getElementById('kategori'), subSelPeng=document.getElementById('sub_kategori'), boxStokBeli=document.getElementById('box_stok_masuk'), inputNamaIkan=document.getElementById('stok_nama');

function cekIntegrasiBeli(){ 
    const val=katSel.value; 
    subSelPeng.innerHTML=''; 
    (katDataPeng[val]||[]).forEach(s=>{let o=document.createElement('option');o.text=s;o.value=s;subSelPeng.add(o)}); 
    if(val === 'Pembelian Stok Ikan') {
        boxStokBeli.classList.remove('hidden');
        autoFillBarang();
    } else {
        boxStokBeli.classList.add('hidden');
    }
}

function autoFillBarang() {
    if(!boxStokBeli.classList.contains('hidden')){
        inputNamaIkan.value = subSelPeng.value;
    }
}

function hitungBeli(){ 
    const total = parseFloat(document.getElementById('total_biaya').value.replace(/[^0-9]/g,''))||0;
    const qty = parseFloat(document.getElementById('qty_beli').value)||0;
    if(qty > 0){
        const satuan = total / qty;
        let rev=Math.round(satuan).toString().split('').reverse().join('').match(/\d{1,3}/g);
        rev = rev ? rev.join('.').split('').reverse().join('') : '0';
        document.getElementById('hrg_beli').value = 'Rp ' + rev;
    }
}

subSelPeng.addEventListener('change', autoFillBarang);
katSel.addEventListener('change', cekIntegrasiBeli);
document.getElementById('total_biaya').addEventListener('input', hitungBeli);
</script>
"""

HTML_LOGIN = """
<div class="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8 bg-white p-10 rounded-2xl shadow-2xl border border-gray-100">
        <div class="text-center">
            <div class="mx-auto w-20 h-20 bg-red-100 rounded-full flex items-center justify-center mb-4">
                <i class="fas fa-fish text-red-600 text-2xl"></i>
            </div>
            <h2 class="text-3xl font-extrabold text-gray-900">
                Koilume
            </h2>
            <p class="mt-2 text-sm text-gray-600">
                Sistem Akuntansi Ikan Koi
            </p>
        </div>
        
        <form class="mt-8 space-y-6" action="{{ url_for('login_page') }}" method="POST">
            <div class="rounded-md shadow-sm -space-y-px">
                <div id="username-container" style="display: none;">
                    <label for="username" class="sr-only">Username</label>
                    <input id="username" name="username" type="text" autocomplete="username"
                           class="appearance-none rounded-t-md relative block w-full px-4 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500 focus:z-10 sm:text-sm" 
                           placeholder="Username">
                </div>

                <div>
                    <label for="email" class="sr-only">Email</label>
                    <input id="email" name="email" type="email" autocomplete="email" required 
                           class="appearance-none relative block w-full px-4 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500 focus:z-10 sm:text-sm" 
                           placeholder="Alamat Email">
                </div>
                <div>
                    <label for="password" class="sr-only">Kata Sandi</label>
                    <input id="password" name="password" type="password" autocomplete="current-password" required 
                           class="appearance-none rounded-b-md relative block w-full px-4 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500 focus:z-10 sm:text-sm" 
                           placeholder="Kata Sandi">
                </div>
            </div>

            <div class="flex items-center justify-center space-x-6">
                <div class="flex items-center">
                    <input id="mode-login" name="mode" type="radio" value="Login" checked 
                           class="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300">
                    <label for="mode-login" class="ml-2 block text-sm font-medium text-gray-700"> 
                        <i class="fas fa-sign-in-alt mr-1"></i>Login
                    </label>
                </div>
                <div class="flex items-center">
                    <input id="mode-daftar" name="mode" type="radio" value="Daftar" 
                           class="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300">
                    <label for="mode-daftar" class="ml-2 block text-sm font-medium text-gray-700">
                        <i class="fas fa-user-plus mr-1"></i>Daftar
                    </label>
                </div>
            </div>

            <div>
                <button type="submit" class="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-white btn-primary focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">
                    <i class="fas fa-paper-plane mr-2"></i>
                    <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                        <i class="fas fa-lock text-red-300"></i>
                    </span>
                    Lanjutkan
                </button>
            </div>
        </form>
    </div>
</div>

<script>
    const modeLogin = document.getElementById('mode-login');
    const modeDaftar = document.getElementById('mode-daftar');
    const usernameContainer = document.getElementById('username-container');
    const emailInput = document.getElementById('email');

    function toggleUsernameField() {
        if (modeDaftar.checked) {
            usernameContainer.style.display = 'block';
            emailInput.classList.remove('rounded-t-md'); 
        } else {
            usernameContainer.style.display = 'none';
            emailInput.classList.add('rounded-t-md'); 
        }
    }
    
    modeLogin.addEventListener('change', toggleUsernameField);
    modeDaftar.addEventListener('change', toggleUsernameField);
    
    document.addEventListener('DOMContentLoaded', toggleUsernameField);
</script>
"""

HTML_PERSEDIAAN = """
<div class="max-w-6xl mx-auto space-y-6">
    
    <div class="flex justify-between items-end border-b pb-4">
        <div>
            <h2 class="text-2xl font-bold text-gray-800">📦 Kartu Stok</h2>
            <p class="text-sm text-gray-500">Laporan keluar-masuk barang.</p>
        </div>
        <div class="flex gap-3">
            <button onclick="document.getElementById('form_stok_awal').classList.toggle('hidden')" 
                    class="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition shadow-sm flex items-center gap-2">
                <span>➕</span> Stok Awal (Tanpa Kurangi Kas)
            </button>
            <button onclick="document.getElementById('form_mati').classList.toggle('hidden')" 
                    class="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition shadow-sm flex items-center gap-2">
                <span>⚙️</span> Penyesuaian (Mati/Rusak)
            </button>
        </div>
    </div>
    
    <div id="form_stok_awal" class="hidden bg-green-100 p-4 rounded-lg border border-green-300 mb-6">
        <h3 class="text-lg font-bold text-green-800 mb-3">Input Stok Awal Bisnis (Dicatat sebagai Kontribusi Modal)</h3>
        <form action="{{ url_for('persediaan_page') }}" method="POST" class="flex flex-wrap gap-4 items-end">
            <input type="hidden" name="action" value="stok_awal">
            
            <div class="w-48">
                <label class="block text-xs font-bold text-gray-600 uppercase mb-1">Jenis Ikan</label>
                <select name="barang_ikan" class="w-full p-2 border rounded text-sm">
                    {% for ikan in jenis_ikan %}
                    <option value="{{ ikan }}">{{ ikan }}</option>
                    {% endfor %}
                </select>
            </div>

            <div class="w-48">
                 <label class="block text-xs font-bold text-gray-600 uppercase mb-1">Tanggal Saldo Awal</label>
                 <input type="date" name="tanggal_saldo_awal" value="{{ today }}" required class="w-full p-2 border rounded text-sm">
            </div>

            <div class="w-24">
                <label class="block text-xs font-bold text-gray-600 uppercase mb-1">Qty</label>
                <input type="number" name="qty" min="1" required class="w-full p-2 border rounded text-sm" placeholder="0">
            </div>
            <div class="flex-1 min-w-[200px]">
                <label class="block text-xs font-bold text-gray-600 uppercase mb-1">Harga Beli Rata-Rata (Rp/Ekor)</label>
                <input type="text" name="harga_satuan" onkeyup="formatRupiah(this)" required class="w-full p-2 border rounded text-sm" placeholder="Rp 0">
                <p class="text-xs text-green-700 mt-1 italic">Nilai total akan masuk ke Modal Owner/Historical Balancing.</p>
            </div>
            <button class="bg-green-800 text-white px-4 py-2 rounded text-sm font-bold hover:bg-green-900">Simpan Stok Awal</button>
        </form>
    </div>
    <div id="form_mati" class="hidden bg-gray-100 p-4 rounded-lg border border-gray-300 mb-6">
        <h3 class="text-lg font-bold text-red-800 mb-3">Input Penyesuaian Stok (Mati/Rusak)</h3>
        <form action="{{ url_for('persediaan_page') }}" method="POST" class="flex flex-wrap gap-4 items-end">
            <input type="hidden" name="action" value="adjustment">
            <div class="flex-1 min-w-[200px]">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Barang</label>
                <select name="item_id" class="w-full p-2 border rounded text-sm">
                    {% for item in stok_akhir %}{% if item.stok_akhir > 0 %}
                    <option value="{{ item.id }}">{{ item.item }} (Sisa: {{ "%.1f"|format(item.stok_akhir) }})</option>
                    {% endif %}{% endfor %}
                </select>
            </div>
            <div class="w-24">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Qty</label>
                <input type="number" name="qty" step="0.1" class="w-full p-2 border rounded text-sm" placeholder="0">
            </div>
            <div class="w-40">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Alasan</label>
                <select name="alasan" class="w-full p-2 border rounded text-sm">
                    <option value="Kematian">Mati</option>
                    <option value="Pemakaian">Lainnya</option>
                </select>
            </div>
            <button class="bg-red-600 text-white px-4 py-2 rounded text-sm font-bold hover:bg-red-700">Simpan Penyesuaian</button>
        </form>
    </div>

    <div class="bg-white rounded-lg shadow border border-gray-200 overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-100">
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-bold text-gray-600 uppercase border-r">Tanggal</th>
                    <th class="px-4 py-3 text-left text-xs font-bold text-gray-600 uppercase border-r">Deskripsi</th>
                    <th class="px-4 py-3 text-left text-xs font-bold text-gray-600 uppercase border-r">Barang & Sisa</th>
                    <th class="px-4 py-3 text-center text-xs font-bold text-green-600 uppercase border-r bg-green-50">Masuk</th>
                    <th class="px-4 py-3 text-center text-xs font-bold text-red-600 uppercase border-r bg-red-50">Keluar</th>
                    <th class="px-4 py-3 text-left text-xs font-bold text-gray-600 uppercase">Keterangan</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-200 bg-white">
                {% for row in kartu_stok %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-2 text-sm text-gray-500 whitespace-nowrap border-r">
                        {{ row.tanggal[:10] }}
                    </td>
                    <td class="px-4 py-2 text-sm text-gray-900 font-medium border-r">
                        {{ row.deskripsi }}
                    </td>
                    <td class="px-4 py-2 text-sm text-gray-900 border-r">
                        <div class="font-bold">{{ row.item }}</div>
                        <div class="text-xs text-gray-500">Sisa Saat Ini: {{ row.sisa }}</div>
                    </td>
                    <td class="px-4 py-2 text-sm text-center font-bold text-green-700 bg-green-50/30 border-r">
                        {{ row.masuk if row.masuk > 0 else '-' }}
                    </td>
                    <td class="px-4 py-2 text-sm text-center font-bold text-red-700 bg-red-50/30 border-r">
                        {{ row.keluar if row.keluar > 0 else '-' }}
                    </td>
                    <td class="px-4 py-2 text-sm text-gray-500 italic truncate max-w-xs">
                        {{ row.keterangan }}
                    </td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="6" class="px-4 py-8 text-center text-gray-400 italic">
                        Belum ada data transaksi stok.
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

HTML_ASET = """
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-1 bg-white p-6 rounded-xl shadow-lg border-t-4 border-red-600 h-fit">
        <h2 class="text-xl font-bold text-gray-900 mb-4 flex items-center gap-2">
            <span>🏢</span> Tambah Aset Tetap
        </h2>
        <form action="{{ url_for('aset_tetap_page') }}" method="POST" class="space-y-4">
            <div>
                <label class="text-xs font-bold text-gray-500 uppercase">Nama Aset</label>
                <input type="text" name="nama_aset" required class="w-full p-2 border rounded text-sm" placeholder="Cth: Mobil Pickup">
            </div>
            <div>
                <label class="text-xs font-bold text-gray-500 uppercase">Tanggal Beli</label>
                <input type="date" name="tanggal_perolehan" value="{{ today }}" required class="w-full p-2 border rounded text-sm">
            </div>
            <div>
                <label class="text-xs font-bold text-gray-500 uppercase">Harga Perolehan (Rp)</label>
                <input type="text" name="harga_perolehan" onkeyup="formatRupiah(this)" required class="w-full p-2 border rounded text-sm font-bold" placeholder="Rp">
            </div>
            <div class="grid grid-cols-2 gap-2">
                <div>
                    <label class="text-xs font-bold text-gray-500 uppercase">Umur (Bulan)</label>
                    <input type="number" name="masa_manfaat" required class="w-full p-2 border rounded text-sm" placeholder="Cth: 60">
                </div>
                <div>
                    <label class="text-xs font-bold text-gray-500 uppercase">Nilai Sisa (Residu)</label>
                    <input type="text" name="nilai_residu" onkeyup="formatRupiah(this)" value="0" class="w-full p-2 border rounded text-sm">
                </div>
            </div>
            <div>
                <label class="text-xs font-bold text-gray-500 uppercase">Kategori</label>
                <select name="kategori_aset" class="w-full p-2 border rounded text-sm">
                    {% for k in kategori_aset.keys() %}<option value="{{ k }}">{{ k }}</option>{% endfor %}
                </select>
            </div>
            <div>
                <label class="text-xs font-bold text-gray-500 uppercase">Bayar Pakai</label>
                <select name="metode_bayar" class="w-full p-2 border rounded text-sm">
                    <option value="Kas">Kas Tunai</option>
                    <option value="Bank">Transfer Bank</option>
                    <option value="Utang Dagang">Utang (Kredit)</option>
                </select>
            </div>
            <button class="w-full bg-red-600 text-white font-bold py-2 rounded hover:bg-red-700 transition">Simpan Aset</button>
        </form>
    </div>

    <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow-lg border border-gray-100">
        <h2 class="text-xl font-bold text-gray-900 mb-4">Daftar Aset Tetap</h2>
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-4 py-2 text-left text-xs font-bold text-gray-500 uppercase">Aset</th>
                        <th class="px-4 py-2 text-right text-xs font-bold text-gray-500 uppercase">Harga Beli</th>
                        <th class="px-4 py-2 text-right text-xs font-bold text-gray-500 uppercase">Susut/Bln</th>
                        <th class="px-4 py-2 text-center text-xs font-bold text-gray-500 uppercase">Akhir Susut</th>
                        <th class="px-4 py-2 text-center text-xs font-bold text-gray-500 uppercase">Aksi</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-200">
                    {% for aset in daftar_aset %}
                    <tr>
                        <td class="px-4 py-3 text-sm">
                            <span class="font-bold text-gray-800">{{ aset.nama_aset }}</span><br>
                            <span class="text-xs text-gray-500">{{ aset.tanggal_perolehan }}</span>
                        </td>
                        <td class="px-4 py-3 text-sm text-right">{{ aset.harga_perolehan | rupiah }}</td>
                        <td class="px-4 py-3 text-sm text-right font-medium text-red-600">
                            {{ ((aset.harga_perolehan - aset.nilai_residu) / aset.masa_manfaat) | rupiah }}
                        </td>
                        <td class="px-4 py-3 text-sm text-center text-gray-500">
                            {{ aset.bulan_terakhir_disusutkan or '-' }}
                        </td>
                        <td class="px-4 py-3 text-sm text-center">
                            <form method="POST" onsubmit="return confirm('Yakin ingin MENGHAPUS aset {{ aset.nama_aset }}? Semua jurnal pembelian dan penyusutan terkait akan dihapus permanen.')" style="display:inline;">
                                <input type="hidden" name="action" value="hapus_aset">
                                <input type="hidden" name="aset_id" value="{{ aset.id }}">
                                <button type="submit" class="text-red-600 hover:text-red-800 text-xs font-bold">
                                    <i class="fas fa-trash"></i> Hapus
                                </button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">Belum ada aset.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
"""

HTML_SETUP = """
<div class="max-w-2xl mx-auto bg-white p-8 rounded-xl shadow-lg border-t-4 border-gray-600">
    <h2 class="text-2xl font-bold text-gray-800 mb-2 flex items-center gap-2">
        <span>⚙️</span> Setup Saldo Awal
    </h2>
    <p class="text-gray-500 text-sm mb-6">
        Input nilai pembukuan terakhir. <br>
        <span class="text-red-500">*Pastikan input Akumulasi Penyusutan agar Nilai Aset di Neraca valid.</span>
    </p>

    <form method="POST" class="space-y-5">
        <div class="grid grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Tanggal Saldo</label>
                <input type="date" name="tanggal" value="{{ today }}" required class="w-full border rounded p-2">
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Pilih Akun</label>
                <select name="akun" id="akun_selector" class="w-full border rounded p-2" required>
                    <optgroup label="KAS & BANK">
                        <option value="Kas" data-normal="Debit">Kas Tunai</option>
                        <option value="Bank" data-normal="Debit">Bank / Rekening</option>
                    </optgroup>
                    
                    <optgroup label="PERLENGKAPAN & PERSEDIAAN">
                        <option value="Perlengkapan" data-normal="Debit">Perlengkapan (Pakan, Obat, dll)</option>
                        {% for ikan in jenis_ikan %}
                        <option value="Persediaan - {{ ikan }}" data-normal="Debit">Persediaan - {{ ikan }}</option>
                        {% endfor %}
                    </optgroup>

                    <optgroup label="PIUTANG">
                        <option value="Piutang Dagang" data-normal="Debit">Piutang (Orang Utang Kita)</option>
                    </optgroup>

                    <optgroup label="ASET TETAP (HARGA BELI)">
                        <option value="Aset - Kendaraan" data-normal="Debit">Kendaraan (Harga Perolehan)</option>
                        <option value="Aset - Bangunan" data-normal="Debit">Bangunan (Harga Perolehan)</option>
                    </optgroup>
                    
                    <optgroup label="AKUMULASI PENYUSUTAN (PENGURANG ASET)">
                        <option value="Akumulasi Penyusutan - Kendaraan" data-normal="Kredit">Akum. Susut Kendaraan</option>
                        <option value="Akumulasi Penyusutan - Bangunan" data-normal="Kredit">Akum. Susut Bangunan</option>
                    </optgroup>

                    <optgroup label="KEWAJIBAN">
                        <option value="Utang Dagang" data-normal="Kredit">Utang Dagang (Kita Utang Orang)</option>
                    </optgroup>

                    <optgroup label="MODAL">
                        <option value="Modal Owner" data-normal="Kredit">Modal Pemilik</option>
                        <option value="Laba Ditahan" data-normal="Kredit">Laba Ditahan</option>
                    </optgroup>
                </select>
            </div>
        </div>

        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Posisi Saldo Normal</label>
            <select name="posisi" id="posisi_selector" class="w-full border rounded p-2 bg-gray-50">
                <option value="Debit">Debit (Harta, Aset, Kas)</option>
                <option value="Kredit">Kredit (Utang, Modal, AKUMULASI PENYUSUTAN)</option>
            </select>
            <p class="text-xs text-gray-400 mt-1" id="info_posisi">
                ⚠️ Saldo normal akun ini adalah **Debit**.
            </p>
        </div>

        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Nilai Saldo (Rp)</label>
            <input type="text" name="jumlah" onkeyup="formatRupiah(this)" required class="w-full border rounded p-2 font-bold text-lg" placeholder="Rp 0">
        </div>

        <button type="submit" class="w-full bg-gray-800 text-white font-bold py-3 rounded hover:bg-gray-900 transition">
            Simpan Saldo
        </button>
    </form>
</div>

<script>
    document.addEventListener('DOMContentLoaded', function() {
        const akunSelector = document.getElementById('akun_selector');
        const posisiSelector = document.getElementById('posisi_selector');
        const infoPosisi = document.getElementById('info_posisi');

        function updatePosisi() {
            const selectedOption = akunSelector.options[akunSelector.selectedIndex];
            const normalBalance = selectedOption.getAttribute('data-normal');
            
            // Atur nilai dropdown posisi ke Saldo Normal yang benar
            posisiSelector.value = normalBalance;

            // Update pesan peringatan
            if (normalBalance === 'Debit') {
                infoPosisi.innerHTML = '✅ Saldo normal akun ini adalah **Debit** (Harta, Aset, Kas).';
                infoPosisi.classList.remove('text-red-500');
                infoPosisi.classList.add('text-green-500');
            } else {
                infoPosisi.innerHTML = '⚠️ Saldo normal akun ini adalah **Kredit** (Utang, Modal, Akumulasi).';
                infoPosisi.classList.remove('text-green-500');
                infoPosisi.classList.add('text-red-500');
            }
        }

        // Panggil saat load dan saat perubahan
        akunSelector.addEventListener('change', updatePosisi);
        updatePosisi(); // Panggil pertama kali untuk Kas Tunai
    });
</script>
"""

HTML_PENYUSUTAN = """
<div class="max-w-3xl mx-auto bg-white p-8 rounded-xl shadow-lg border-t-4 border-red-500">
    <div class="text-center mb-8">
        <h2 class="text-2xl font-bold text-gray-900">⏳ Proses Penyusutan Aset</h2>
        <p class="text-gray-500">Hitung penurunan nilai aset secara otomatis setiap bulan.</p>
    </div>

    <form method="POST" class="flex gap-4 items-end justify-center mb-8 bg-gray-50 p-4 rounded-lg border border-gray-200">
        <div class="w-48">
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Pilih Bulan</label>
            <input type="month" name="periode" value="{{ periode_pilihan }}" required class="w-full border rounded p-2 text-sm font-bold">
        </div>
        <button type="submit" name="action" value="preview" class="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded hover:bg-gray-50 font-medium transition">
            🔍 Preview
        </button>
    </form>

    {% if preview_aset %}
    <div class="border rounded-lg overflow-hidden mb-6">
        <div class="bg-yellow-50 px-4 py-2 border-b border-yellow-100 text-yellow-800 font-bold text-sm">
            Akan Diproses ({{ preview_aset|length }} Item)
        </div>
        <table class="min-w-full divide-y">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-2 text-left text-xs uppercase">Nama Aset</th>
                    <th class="px-4 py-2 text-right text-xs uppercase">Nilai Susut</th>
                </tr>
            </thead>
            <tbody class="divide-y">
                {% for a in preview_aset %}
                <tr>
                    <td class="px-4 py-2 text-sm">{{ a.nama_aset }}</td>
                    <td class="px-4 py-2 text-sm text-right font-bold">{{ a.beban_bulanan | rupiah }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <form method="POST" class="text-center">
        <input type="hidden" name="periode" value="{{ periode_pilihan }}">
        <button type="submit" name="action" value="eksekusi" onclick="return confirm('Yakin proses penyusutan bulan ini?')"
                class="bg-yellow-500 hover:bg-yellow-600 text-white font-bold py-3 px-8 rounded-lg shadow-lg transition transform hover:scale-105">
            🚀 Jalankan Penyusutan & Buat Jurnal
        </button>
    </form>
    {% elif request.method == 'POST' and not preview_aset %}
    <div class="text-center p-8 bg-gray-50 rounded-lg border border-dashed border-gray-300 text-gray-500">
        <p>Semua aset sudah disusutkan untuk periode {{ periode_pilihan }}, atau belum waktunya.</p>
    </div>
    {% endif %}
    
    <div class="bg-white p-6 rounded-xl shadow-lg border border-gray-100 mt-8">
        <h2 class="text-xl font-bold text-gray-900 mb-4">Riwayat Penyusutan Aset</h2>
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-4 py-2 text-left text-xs uppercase">Nama Aset</th>
                        <th class="px-4 py-2 text-center text-xs uppercase">Bulan Terakhir Disusutkan</th>
                        <th class="px-4 py-2 text-center text-xs uppercase">Aksi</th>
                    </tr>
                </thead>
                <tbody class="divide-y">
                    {% for aset in daftar_aset %}
                    <tr>
                        <td class="px-4 py-3 text-sm">{{ aset.nama_aset }}</td>
                        <td class="px-4 py-3 text-sm text-center text-gray-500">
                            {{ aset.bulan_terakhir_disusutkan or 'Belum Disusutkan' }}
                        </td>
                        <td class="px-4 py-3 text-sm text-center">
                            {% if aset.bulan_terakhir_disusutkan %}
                                <form method="POST" onsubmit="return confirm('Yakin ingin membatalkan penyusutan bulan terakhir ({{ aset.bulan_terakhir_disusutkan[:7] }}) untuk {{ aset.nama_aset }}? Jurnal akan dihapus.')" style="display:inline;">
                                    <input type="hidden" name="action" value="hapus_susut">
                                    <input type="hidden" name="aset_id" value="{{ aset.id }}">
                                    <input type="hidden" name="periode_susut" value="{{ aset.bulan_terakhir_disusutkan[:7] }}">
                                    <button type="submit" class="text-red-600 hover:text-red-800 text-xs font-bold">
                                        <i class="fas fa-trash"></i> Batalkan Jurnal
                                    </button>
                                </form>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
</div>
"""

HTML_LAPORAN_PERSEDIAAN = """
<div class="space-y-8">
    <!-- Header -->
    <div class="bg-white rounded-2xl shadow-xl p-8">
        <div class="flex items-center justify-between">
            <div>
                <h1 class="text-3xl font-bold text-gray-900">
                    <i class="fas fa-boxes text-red-500 mr-3"></i>Laporan Persediaan Ikan
                </h1>
                <p class="text-gray-600 mt-2">Kelola dan pantau stok ikan koi Anda</p>
            </div>
            <div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center">
                <i class="fas fa-chart-line text-red-600 text-2xl"></i>
            </div>
        </div>
    </div>

    <!-- Stok Terkini -->
    <div class="bg-white rounded-2xl shadow-xl p-8">
        <h2 class="text-2xl font-bold text-gray-900 mb-6">
            <i class="fas fa-box text-red-500 mr-3"></i>Stok Terkini
        </h2>
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {% for barang, stok in stok_terkini.items() %}
            <div class="text-center p-4 rounded-xl border-2 {% if stok <= 5 %}border-red-300 bg-red-50{% else %}border-green-300 bg-green-50{% endif %} card-hover">
                <div class="text-2xl font-bold {% if stok <= 5 %}text-red-700{% else %}text-green-700{% endif %}">{{ stok }}</div>
                <div class="text-sm text-gray-600 mt-1">{{ barang }}</div>
                {% if stok <= 5 %}
                <div class="text-xs text-red-600 font-medium mt-2">
                    <i class="fas fa-exclamation-triangle mr-1"></i> Stok rendah
                </div>
                {% endif %}
            </div>
            {% else %}
            <div class="col-span-6 text-center py-12">
                <i class="fas fa-box-open text-gray-400 text-5xl mb-4"></i>
                <p class="text-gray-500 text-lg font-medium">Belum ada data stok</p>
                <p class="text-gray-400 mt-2">Mulai dengan input pemasukan/pengeluaran</p>
            </div>
            {% endfor %}
        </div>
    </div>

    <!-- Riwayat Persediaan -->
    <div class="bg-white rounded-2xl shadow-xl overflow-hidden">
        <div class="px-8 py-6 bg-gradient-to-r from-red-500 to-red-600">
            <h2 class="text-2xl font-bold text-white">
                <i class="fas fa-history mr-3"></i>Riwayat Persediaan
            </h2>
        </div>
        
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-calendar mr-2"></i>Tanggal
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-file-alt mr-2"></i>Deskripsi
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-fish mr-2"></i>Barang
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-arrow-down text-green-600 mr-2"></i>Masuk
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-arrow-up text-red-600 mr-2"></i>Keluar
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-boxes mr-2"></i>Sisa
                        </th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider bg-white">
                            <i class="fas fa-sticky-note mr-2"></i>Keterangan
                        </th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {% for item in riwayat_persediaan %}
                    <tr class="hover:bg-gray-50 transition duration-300">
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-medium">
                            {{ item.tanggal[:10] }}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {{ item.deskripsi }}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-semibold">
                            {{ item.barang }}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-green-600 font-bold">
                            {% if item.masuk > 0 %}+{{ item.masuk }}{% endif %}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-red-600 font-bold">
                            {% if item.keluar > 0 %}-{{ item.keluar }}{% endif %}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-bold text-gray-900">
                            {{ item.sisa }}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {{ item.keterangan }}
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="7" class="px-6 py-12 text-center">
                            <i class="fas fa-inbox text-gray-400 text-4xl mb-3"></i>
                            <p class="text-gray-500 text-lg font-medium">Tidak ada data persediaan</p>
                            <p class="text-gray-400 mt-1">Data akan muncul setelah input transaksi</p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
"""

HTML_KELOLA_DATA = """
<div class="space-y-8">
    <div class="bg-white rounded-2xl shadow-xl p-8">
        <div class="flex items-center justify-between">
            <div>
                <h1 class="text-3xl font-bold text-gray-900">
                    <i class="fas fa-cog text-red-500 mr-3"></i>Kelola Data Transaksi
                </h1>
                <p class="text-gray-600 mt-2">Kelola dan pantau semua transaksi keuangan</p>
            </div>
            <div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center">
                <i class="fas fa-database text-red-600 text-2xl"></i>
            </div>
        </div>
    </div>

    <div class="bg-white rounded-2xl shadow-xl overflow-hidden">
        <div class="px-8 py-6 bg-gradient-to-r from-green-500 to-green-600">
            <h2 class="text-2xl font-bold text-white">
                <i class="fas fa-plus-circle mr-3"></i>Data Pemasukan
            </h2>
        </div>
        
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">ID</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Tanggal</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Sumber</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Sub Sumber</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Jumlah</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Metode</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Pelanggan</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Aksi</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {% for row in pemasukan_df %}
                    <tr class="hover:bg-gray-50 transition duration-300">
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row['id'] }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row['Tanggal'] | string | truncate(10, True, '') }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-medium">{{ row['Sumber'] }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ row.get('Sub_Sumber', '') }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-green-600 font-bold">{{ row['Jumlah'] | rupiah }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <span class="px-2 py-1 bg-gray-100 rounded-full text-xs">{{ row['Metode'] }}</span>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row.get('Kontak', '') }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm">
                            <a href="{{ url_for('hapus_page', tipe='pemasukan', db_id=row['id']) }}" 
                               onclick="return confirm('Yakin ingin menghapus data ini? Aksi ini akan membuat jurnal pembalikan dan memengaruhi stok/HPP.')"
                               class="text-red-600 hover:text-red-900 font-medium transition duration-300">
                                <i class="fas fa-trash mr-1"></i>Hapus
                            </a>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="8" class="px-6 py-12 text-center">
                            <i class="fas fa-receipt text-gray-400 text-4xl mb-3"></i>
                            <p class="text-gray-500 text-lg font-medium">Tidak ada data pemasukan</p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <div class="bg-white rounded-2xl shadow-xl overflow-hidden">
        <div class="px-8 py-6 bg-gradient-to-r from-red-500 to-red-600">
            <h2 class="text-2xl font-bold text-white">
                <i class="fas fa-minus-circle mr-3"></i>Data Pengeluaran
            </h2>
        </div>
        
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">ID</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Tanggal</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Kategori</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Jumlah</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Metode</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Vendor</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Aksi</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {% for row in pengeluaran_df %}
                    <tr class="hover:bg-gray-50 transition duration-300">
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row['id'] }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row['Tanggal'] | string | truncate(10, True, '') }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-medium">{{ row['Kategori'] }} - {{ row['Sub_Kategori'] }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-red-600 font-bold">{{ row['Jumlah'] | rupiah }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <span class="px-2 py-1 bg-gray-100 rounded-full text-xs">{{ row['Metode'] }}</span>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ row.get('Kontak', '') }}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm">
                            <a href="{{ url_for('hapus_page', tipe='pengeluaran', db_id=row['id']) }}" 
                               onclick="return confirm('Yakin ingin menghapus data ini? Aksi ini akan membuat jurnal pembalikan dan memengaruhi stok/HPP.')"
                               class="text-red-600 hover:text-red-900 font-medium transition duration-300">
                                <i class="fas fa-trash mr-1"></i>Hapus
                            </a>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="7" class="px-6 py-12 text-center">
                            <i class="fas fa-shopping-cart text-gray-400 text-4xl mb-3"></i>
                            <p class="text-gray-500 text-lg font-medium">Tidak ada data pengeluaran</p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <div class="bg-white rounded-2xl shadow-xl overflow-hidden mt-8 p-6">
        <h2 class="text-2xl font-bold text-gray-900 mb-6">
            <i class="fas fa-file-invoice-dollar mr-2"></i> Riwayat Piutang & Utang Detail
        </h2>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            <div>
                <h3 class="text-lg font-bold text-blue-600 mb-3 border-b pb-2">Detail Piutang (Klien)</h3>
                <div class="space-y-4">
                    {% for kontak_piutang in buku_besar_pembantu.piutang %}
                        <div class="border p-3 rounded-lg bg-blue-50">
                            <div class="font-bold text-gray-800 flex justify-between">
                                {{ kontak_piutang.kontak }}
                                <span class="text-sm font-semibold {% if kontak_piutang.saldo > 0 %}text-red-600{% else %}text-green-600{% endif %}">
                                    Saldo: {{ kontak_piutang.saldo | rupiah }}
                                </span>
                            </div>
                            <p class="text-xs text-gray-500 mt-1">Terakhir: {{ kontak_piutang.last_date }}</p>
                            
                            <div class="mt-2 text-xs border-t pt-2 space-y-1 max-h-40 overflow-y-auto">
                                <span class="font-semibold underline">Riwayat Jurnal Piutang:</span>
                                {% set is_piutang_active = false %}
                                {% for jurnal_entry in jurnal_total %}
                                    {# Filter Piutang Dagang DAN Kontak harus sama #}
                                    {% if jurnal_entry.Kontak == kontak_piutang.kontak and jurnal_entry.Akun == 'Piutang Dagang' %}
                                        {% set is_piutang_active = true %}
                                        <div class="flex justify-between">
                                            <span class="text-gray-600">{{ jurnal_entry.Tanggal | string | truncate(10, true, '') }}</span> 
                                            <span class="font-medium {% if jurnal_entry.Debit > 0 %}text-green-700{% else %}text-red-700{% endif %}" title="{{ jurnal_entry.Keterangan }}">
                                                {% if jurnal_entry.Debit > 0 %}{{ jurnal_entry.Debit | rupiah }} (Jual Kredit){% else %}({{ jurnal_entry.Kredit | rupiah }}) (Lunas){% endif %}
                                            </span>
                                        </div>
                                    {% endif %}
                                {% endfor %}
                                {% if not is_piutang_active %}<p class="text-gray-400">Tidak ada riwayat Jurnal Piutang.</p>{% endif %}
                            </div>
                        </div>
                    {% else %}
                        <p class="text-sm text-gray-400">Tidak ada saldo Piutang aktif.</p>
                    {% endfor %}
                </div>
            </div>

            <div>
                <h3 class="text-lg font-bold text-orange-600 mb-3 border-b pb-2">Detail Utang (Supplier)</h3>
                 <div class="space-y-4">
                    {% for kontak_utang in buku_besar_pembantu.utang %}
                        <div class="border p-3 rounded-lg bg-orange-50">
                            <div class="font-bold text-gray-800 flex justify-between">
                                {{ kontak_utang.kontak }}
                                <span class="text-sm font-semibold text-red-600">
                                    Saldo: {{ kontak_utang.saldo | rupiah }}
                                </span>
                            </div>
                            <p class="text-xs text-gray-500 mt-1">Terakhir: {{ kontak_utang.last_date }}</p>

                            <div class="mt-2 text-xs border-t pt-2 space-y-1 max-h-40 overflow-y-auto">
                                <span class="font-semibold underline">Riwayat Jurnal Utang:</span>
                                {% set is_utang_active = false %}
                                {% for jurnal_entry in jurnal_total %}
                                    {# Filter Utang Dagang DAN Kontak harus sama #}
                                    {% if jurnal_entry.Kontak == kontak_utang.kontak and jurnal_entry.Akun == 'Utang Dagang' %}
                                        {% set is_utang_active = true %}
                                        <div class="flex justify-between">
                                            <span class="text-gray-600">{{ jurnal_entry.Tanggal | string | truncate(10, true, '') }}</span> 
                                            <span class="font-medium {% if jurnal_entry.Kredit > 0 %}text-red-700{% else %}text-green-700{% endif %}" title="{{ jurnal_entry.Keterangan }}">
                                                {% if jurnal_entry.Kredit > 0 %}{{ jurnal_entry.Kredit | rupiah }} (Beli Kredit){% else %}({{ jurnal_entry.Debit | rupiah }}) (Bayar){% endif %}
                                            </span>
                                        </div>
                                    {% endif %}
                                {% endfor %}
                                {% if not is_utang_active %}<p class="text-gray-400">Tidak ada riwayat Jurnal Utang.</p>{% endif %}
                            </div>
                        </div>
                    {% else %}
                        <p class="text-sm text-gray-400">Tidak ada saldo Utang aktif.</p>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>
"""

HTML_LAPORAN = """
<div class="space-y-8">
    <style>
        @media print {
            nav, .no-print-area { display: none !important; }
        }
        
        .chart-container {
            position: relative;
            height: 400px;
        }
        
        .fade-in {
            animation: fadeIn 0.5s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* PERBAIKAN: Tombol yang konsisten */
        .btn-consistent {
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            color: white;
        }
        
        .btn-primary:hover {
            background: linear-gradient(135deg, #b91c1c 0%, #991b1b 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);
        }
        
        .btn-secondary {
            background: #6b7280;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #4b5563;
            transform: translateY(-2px);
        }
        
        /* PERBAIKAN: Layout buku besar pembantu yang sejajar */
        .buku-besar-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }
        
        @media (max-width: 1024px) {
            .buku-besar-grid {
                grid-template-columns: 1fr;
            }
        }
        
        .buku-besar-card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            border: 1px solid #e5e7eb;
            overflow: hidden;
        }
        
        .buku-besar-header {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            padding: 16px 20px;
            color: white;
        }
        
        /* PERBAIKAN: Grafik yang lebih menarik */
        .chart-wrapper {
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            border: 1px solid #e5e7eb;
        }
    </style>

    <div class="card-white rounded-2xl p-6 no-print-area">
        <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
            <div>
                <h1 class="text-2xl font-bold text-gray-900 mb-2 flex items-center gap-3">
                    <i class="fas fa-chart-bar text-red-600"></i>
                    Laporan Keuangan Lengkap
                </h1>
                <p class="text-gray-600">
                    Periode: <span class="font-semibold text-red-600">{{ filter.mulai }}</span> hingga 
                    <span class="font-semibold text-red-600">{{ filter.akhir }}</span>
                </p>
            </div>
            
            <div class="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
                <form method="POST" class="flex flex-col sm:flex-row gap-3 bg-gray-50 p-4 rounded-xl">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Tanggal Mulai</label>
                        <input type="date" name="mulai" value="{{ filter.mulai }}" 
                               class="w-full sm:w-40 p-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-red-500">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Tanggal Akhir</label>
                        <input type="date" name="akhir" value="{{ filter.akhir }}"
                               class="w-full sm:w-40 p-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-red-500">
                    </div>
                    <button type="submit" class="btn-consistent btn-primary mt-2 sm:mt-0">
                        <i class="fas fa-sync-alt mr-2"></i>Refresh
                    </button>
                </form>

                <button onclick="window.print()" class="btn-consistent btn-secondary flex items-center gap-2">
                    <i class="fas fa-print"></i>Cetak Laporan
                </button>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div class="card-white rounded-xl p-6 text-center hover:scale-105 transition-transform">
            <div class="w-16 h-16 bg-green-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <i class="fas fa-arrow-down text-green-600 text-2xl"></i>
            </div>
            <h3 class="text-2xl font-bold text-green-600 mb-2">{{ ringkasan.total_pemasukan | rupiah }}</h3>
            <p class="text-gray-600 font-medium">Total Pemasukan</p>
        </div>
        
        <div class="card-white rounded-xl p-6 text-center hover:scale-105 transition-transform">
            <div class="w-16 h-16 bg-red-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <i class="fas fa-arrow-up text-red-600 text-2xl"></i>
            </div>
            <h3 class="text-2xl font-bold text-red-600 mb-2">{{ ringkasan.total_pengeluaran | rupiah }}</h3>
            <p class="text-gray-600 font-medium">Total Pengeluaran</p>
        </div>
        
        <div class="card-white rounded-xl p-6 text-center hover:scale-105 transition-transform">
            <div class="w-16 h-16 bg-blue-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <i class="fas fa-balance-scale text-blue-600 text-2xl"></i>
            </div>
            <h3 class="text-2xl font-bold text-blue-600 mb-2">{{ laba_rugi.laba_bersih | rupiah }}</h3>
            <p class="text-gray-600 font-medium">Laba/Rugi Bersih</p>
        </div>
    </div>

    <div class="chart-wrapper fade-in">
        <div class="flex items-center justify-between mb-6">
            <h2 class="text-xl font-bold text-gray-900 flex items-center gap-3">
                <i class="fas fa-chart-line text-red-600"></i>
                Grafik Tren Laba/Rugi Bulanan
            </h2>
            <span class="bg-red-100 text-red-600 px-3 py-1 rounded-full text-sm font-medium">
                6 Bulan Terakhir
            </span>
        </div>
        
        <div class="chart-container">
            <canvas id="profitChart"></canvas>
        </div>
        
        {% if not chart_data or chart_data|length < 2 %}
        <div class="text-center py-12 text-gray-400">
            <i class="fas fa-chart-bar text-5xl mb-4"></i>
            <p class="text-lg font-medium">Data grafik belum tersedia</p>
            <p class="text-sm mt-1">Membutuhkan minimal 2 bulan data transaksi</p>
        </div>
        {% endif %}
    </div>

    <div class="fade-in">
        <h2 class="text-xl font-bold text-gray-900 mb-4 flex items-center gap-3">
            <i class="fas fa-book text-red-600"></i>
            Buku Besar Pembantu (Ringkasan Saldo Kontak)
        </h2 >
        
        <div class="buku-besar-grid">
            <div class="buku-besar-card">
                <div class="buku-besar-header">
                    <h3 class="font-bold text-lg flex items-center gap-2">
                        <i class="fas fa-hand-holding-usd"></i>
                        Piutang Dagang
                    </h3>
                </div>
                <div class="p-4 max-h-80 overflow-y-auto">
                    {% if buku_besar_pembantu.piutang %}
                        {% for item in buku_besar_pembantu.piutang %}
                        <div class="flex justify-between items-center py-3 border-b border-gray-200 last:border-b-0">
                            <div>
                                <p class="font-medium text-gray-900">{{ item.kontak }}</p>
                                <p class="text-sm text-gray-500">Update: {{ item.last_date }}</p>
                            </div>
                            <div class="text-right">
                                <p class="font-bold {% if item.saldo >= 0 %}text-green-600{% else %}text-red-600{% endif %}">
                                    {{ item.saldo | rupiah }}
                                </p>
                                <p class="text-sm text-gray-500">Saldo Akhir</p>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="text-center py-8 text-gray-400">
                            <i class="fas fa-receipt text-3xl mb-2"></i>
                            <p>Tidak ada saldo piutang aktif</p>
                        </div>
                    {% endif %}
                </div>
            </div>

            <div class="buku-besar-card">
                <div class="buku-besar-header">
                    <h3 class="font-bold text-lg flex items-center gap-2">
                        <i class="fas fa-credit-card"></i>
                        Utang Dagang
                    </h3>
                </div>
                <div class="p-4 max-h-80 overflow-y-auto">
                    {% if buku_besar_pembantu.utang %}
                        {% for item in buku_besar_pembantu.utang %}
                        <div class="flex justify-between items-center py-3 border-b border-gray-200 last:border-b-0">
                            <div>
                                <p class="font-medium text-gray-900">{{ item.kontak }}</p>
                                <p class="text-sm text-gray-500">Update: {{ item.last_date }}</p>
                            </div>
                            <div class="text-right">
                                <p class="font-bold text-red-600">
                                    {{ item.saldo | rupiah }}
                                </p>
                                <p class="text-sm text-gray-500">Saldo Akhir</p>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="text-center py-8 text-gray-400">
                            <i class="fas fa-file-invoice-dollar text-3xl mb-2"></i>
                            <p>Tidak ada saldo utang aktif</p>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>

    <div class="card-white rounded-2xl overflow-hidden fade-in">
        <div class="bg-gradient-to-r from-red-600 to-red-700 px-6 py-4">
            <h2 class="text-xl font-bold text-white flex items-center gap-3">
                <i class="fas fa-file-invoice-dollar"></i>
                LAPORAN LABA RUGI
            </h2>
        </div>
        
        <div class="p-6">
            <table class="w-full text-sm">
                <tr class="bg-green-50">
                    <td colspan="2" class="font-bold text-green-800 py-4 px-6 text-lg border-b border-green-200">
                        <i class="fas fa-arrow-down mr-2"></i>PENDAPATAN
                    </td>
                </tr>
                {% for item in laba_rugi.rincian_pendapatan %}
                <tr class="border-b border-green-100 hover:bg-green-50 transition-colors">
                    <td class="pl-8 py-3 text-gray-700 font-medium">{{ item.Akun }}</td>
                    <td class="text-right font-bold text-green-700 py-3 pr-6">{{ item.Jumlah | rupiah }}</td>
                </tr>
                {% endfor %}
                <tr class="bg-green-100 border-t-2 border-green-300">
                    <td class="font-bold py-4 px-6 text-green-900 text-lg">TOTAL PENDAPATAN</td>
                    <td class="text-right font-bold text-green-900 text-lg pr-6">{{ laba_rugi.pendapatan_total | rupiah }}</td>
                </tr>
                
                <tr><td colspan="2" class="py-4"></td></tr>
                
                <tr class="bg-yellow-50">
                    <td colspan="2" class="font-bold text-yellow-800 py-4 px-6 text-lg border-b border-yellow-200">
                        <i class="fas fa-calculator mr-2"></i>HARGA POKOK PENJUALAN
                    </td>
                </tr>
                <tr class="border-b border-yellow-100 hover:bg-yellow-50 transition-colors">
                    <td class="pl-8 py-3 text-gray-700 font-medium">HPP Ikan Koi</td>
                    <td class="text-right font-bold text-red-700 py-3 pr-6">({{ laba_rugi.hpp_total | rupiah }})</td>
                </tr>
                <tr class="bg-gray-100 border-t-2 border-gray-300">
                    <td class="font-bold py-4 px-6 text-gray-900 text-lg">LABA KOTOR</td>
                    <td class="text-right font-bold text-blue-700 text-lg pr-6">{{ laba_rugi.laba_kotor | rupiah }}</td>
                </tr>

                <tr><td colspan="2" class="py-4"></td></tr>
                
                <tr class="bg-gray-50"> 
                    <td colspan="2" class="font-bold text-red-800 py-4 px-6 text-lg border-b border-gray-200">
                        <i class="fas fa-arrow-up mr-2"></i>BEBAN OPERASIONAL
                    </td>
                </tr>
                {% for item in laba_rugi.rincian_beban %}
                <tr class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td class="pl-8 py-3 text-gray-700 font-medium">{{ item.Akun }}</td>
                    <td class="text-right font-bold text-red-700 py-3 pr-6">({{ item.Jumlah | rupiah }})</td>
                </tr>
                {% endfor %}
                <tr class="bg-red-100 border-t-2 border-red-300">
                    <td class="font-bold py-4 px-6 text-red-900 text-lg">TOTAL BEBAN</td>
                    <td class="text-right font-bold text-red-800 text-lg pr-6">({{ laba_rugi.beban_total | rupiah }})</td>
                </tr>
                
                <tr class="border-t-4 border-gray-400 bg-gradient-to-r from-blue-50 to-blue-100">
                    <td class="font-bold py-6 px-6 text-gray-900 text-2xl">LABA/RUGI BERSIH</td>
                    <td class="text-right font-bold text-2xl pr-6 {% if laba_rugi.laba_bersih >= 0 %}text-green-600{% else %}text-red-600{% endif %}">
                        {{ laba_rugi.laba_bersih | rupiah }}
                    </td>
                </tr>
            </table>
        </div>
    </div>
    
    <div class="card-white rounded-2xl overflow-hidden fade-in">
        <div class="bg-gradient-to-r from-red-600 to-red-700 px-6 py-4">
            <h2 class="text-xl font-bold text-white flex items-center gap-3">
                <i class="fas fa-balance-scale"></i>
                LAPORAN NERACA (POSISI KEUANGAN)
            </h2>
        </div>
        
        <div class="p-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div>
                    <h3 class="font-bold text-gray-900 text-lg mb-4 border-b pb-2">AKTIVA (ASET)</h3>
                    <table class="w-full text-sm">
                        <tr class="bg-blue-50"><td colspan="2" class="font-bold py-2 px-3 text-blue-800">Aset Lancar</td></tr>
                        {% for item in neraca.aset_lancar %}
                        <tr class="border-b hover:bg-gray-50">
                            <td class="pl-5 py-2 text-gray-700">{{ item.Akun }}</td>
                            <td class="text-right font-medium pr-3">{{ item.Nilai | rupiah }}</td>
                        </tr>
                        {% endfor %}
                        
                        <tr class="bg-blue-50 border-t"><td colspan="2" class="font-bold py-2 px-3 text-blue-800">Aset Tetap</td></tr>
                        {% for item in neraca.aset_tetap %}
                        <tr class="border-b hover:bg-gray-50">
                            <td class="pl-5 py-2 text-gray-700">
                                {% if item.Akun == 'Akumulasi Penyusutan' %}
                                    <span class="ml-4 italic text-red-600">{{ item.Akun }}</span>
                                {% else %}
                                    {{ item.Akun }}
                                {% endif %}
                            </td>
                            <td class="text-right font-medium pr-3">
                                {% if item.Akun == 'Akumulasi Penyusutan' %}
                                    ({{ (item.Nilai * -1) | rupiah }}) 
                                {% else %}
                                    {{ item.Nilai | rupiah }}
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}

                        <tr class="border-t-4 border-gray-400 bg-blue-100">
                            <td class="font-bold py-3 px-3 text-gray-900 text-lg">TOTAL AKTIVA</td>
                            <td class="text-right font-bold text-gray-900 text-lg pr-3">{{ neraca.aktiva | rupiah }}</td>
                        </tr>
                    </table>
                </div>

                <div>
                    <h3 class="font-bold text-gray-900 text-lg mb-4 border-b pb-2">PASIVA (KEWAJIBAN & EKUITAS)</h3>
                    <table class="w-full text-sm">
                        <tr class="bg-red-50"><td colspan="2" class="font-bold py-2 px-3 text-red-800">Kewajiban</td></tr>
                        {% for item in neraca.kewajiban %}
                        <tr class="border-b hover:bg-gray-50">
                            <td class="pl-5 py-2 text-gray-700">{{ item.Akun }}</td>
                            <td class="text-right font-medium pr-3">{{ item.Nilai | rupiah }}</td>
                        </tr>
                        {% endfor %}

                        <tr class="bg-yellow-50 border-t"><td colspan="2" class="font-bold py-2 px-3 text-yellow-800">Ekuitas</td></tr>
                        <tr class="border-b hover:bg-gray-50">
                            <td class="pl-5 py-2 text-gray-700">Modal Awal/Laba Ditahan</td>
                            <td class="text-right font-medium pr-3">{{ neraca.ekuitas | rupiah }}</td>
                        </tr>
                        
                        {% set penyesuaian = neraca.total_ekuitas_laba - neraca.ekuitas - laba_rugi.laba_bersih %}
                        {% if penyesuaian != 0 %}
                            <tr class="border-b hover:bg-gray-50 bg-gray-50">
                                <td class="pl-5 py-2 text-gray-700 italic">Penyesuaian Saldo Awal (Historical)</td>
                                <td class="text-right font-medium pr-3">{{ penyesuaian | rupiah }}</td>
                            </tr>
                        {% endif %}
                        
                        <tr class="border-b hover:bg-gray-50">
                            <td class="pl-5 py-2 text-gray-700 font-bold text-blue-600">Laba Bersih Periode Ini</td>
                            <td class="text-right font-bold text-blue-600 pr-3">{{ laba_rugi.laba_bersih | rupiah }}</td>
                        </tr>
                        
                        <tr class="border-t-4 border-gray-400 bg-red-100">
                            <td class="font-bold py-3 px-3 text-gray-900 text-lg">TOTAL PASIVA</td>
                            <td class="text-right font-bold text-gray-900 text-lg pr-3">{{ neraca.pasiva | rupiah }}</td>
                        </tr>
                    </table>
                    
                    {% if not neraca.is_balance %}
                    {% set selisih = neraca.aktiva - neraca.pasiva %}
                    <p class="mt-4 text-red-600 text-sm font-bold">⚠️ Neraca Tidak Balance. Selisih: {{ selisih if selisih > 0 else -selisih | rupiah }}</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    
    <div class="card-white rounded-2xl overflow-hidden fade-in">
        <div class="bg-gradient-to-r from-red-600 to-red-700 px-6 py-4">
            <h2 class="text-xl font-bold text-white flex items-center gap-3">
                <i class="fas fa-book-open"></i>
                BUKU BESAR UTAMA (SEMUA AKUN)
            </h2>
        </div>
        
        <div class="p-6 space-y-8">
            {% for akun, entries in buku_besar.items() %}
            <div class="border border-indigo-200 rounded-lg overflow-hidden">
                <div class="bg-indigo-50 px-4 py-3 border-b border-indigo-200">
                    <h3 class="font-bold text-indigo-800">{{ akun }}</h3>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50 sticky top-0">
                            <tr>
                                <th class="px-3 py-2 text-left text-xs font-semibold text-gray-700 uppercase">Tanggal</th>
                                <th class="px-3 py-2 text-left text-xs font-semibold text-gray-700 uppercase">Keterangan</th>
                                <th class="px-3 py-2 text-left text-xs font-semibold text-gray-700 uppercase">Kontak</th>
                                <th class="px-3 py-2 text-right text-xs font-semibold text-green-700 uppercase">Debit</th>
                                <th class="px-3 py-2 text-right text-xs font-semibold text-red-700 uppercase">Kredit</th>
                                <th class="px-3 py-2 text-right text-xs font-semibold text-gray-700 uppercase">Saldo</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-200">
                            {% for entry in entries %}
                            <tr class="hover:bg-gray-50 {% if 'Saldo Awal' in entry.Keterangan %}bg-yellow-50 font-semibold{% endif %}">
                                <td class="px-3 py-2 text-sm text-gray-600 whitespace-nowrap">{{ entry.Tanggal }}</td>
                                <td class="px-3 py-2 text-sm text-gray-900">{{ entry.Keterangan }}</td>
                                <td class="px-3 py-2 text-sm text-gray-500">{{ entry.Kontak or '-' }}</td> 
                                <td class="px-3 py-2 text-sm text-right text-green-600 font-mono">{{ entry.Debit | rupiah if entry.Debit > 0 else '-' }}</td>
                                <td class="px-3 py-2 text-sm text-right text-red-600 font-mono">{{ entry.Kredit | rupiah if entry.Kredit > 0 else '-' }}</td>
                                <td class="px-3 py-2 text-sm text-right font-bold text-gray-800 font-mono">{{ entry.Saldo | rupiah }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="bg-indigo-100 px-4 py-2 text-right font-bold text-indigo-900">
                    Saldo Akhir: {{ entries[-1].Saldo | rupiah }}
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    
    <div class="card-white rounded-2xl overflow-hidden fade-in">
        <div class="bg-gradient-to-r from-red-600 to-red-700 px-6 py-4">
            <h2 class="text-xl font-bold text-white flex items-center gap-3">
                <i class="fas fa-book"></i>
                JURNAL UMUM
            </h2>
        </div>
        
        <div class="max-h-[600px] overflow-y-auto">
            <table class="min-w-full divide-y divide-gray-300">
                <thead class="bg-gray-100 sticky top-0">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase">Tanggal</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase">Akun</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase">Keterangan</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-700 uppercase">Kontak</th> 
                        <th class="px-6 py-4 text-right text-xs font-semibold text-gray-700 uppercase">Debit</th>
                        <th class="px-6 py-4 text-right text-xs font-semibold text-gray-700 uppercase">Kredit</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {% for row in jurnal_df %}
                    <tr class="hover:bg-gray-50 transition-colors group">
                        <td class="px-6 py-4 text-sm text-gray-600 whitespace-nowrap">
                            {{ row.Tanggal.strftime('%d-%m-%Y') if row.Tanggal is string else row.Tanggal.strftime('%d-%m-%Y') }}
                        </td>
                        <td class="px-6 py-4">
                            <div class="font-semibold text-gray-900 group-hover:text-blue-700">{{ row.Akun }}</div>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-600 italic">
                            {{ row.Keterangan }}
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-500"> {{ row.Kontak or '-' }}
                        </td>
                        <td class="px-6 py-4 text-sm text-right font-mono">
                            {% if row.Debit > 0 %}
                                <span class="text-green-600 font-bold">{{ row.Debit | rupiah }}</span>
                            {% else %}
                                <span class="text-gray-400">-</span>
                            {% endif %}
                        </td>
                        <td class="px-6 py-4 text-sm text-right font-mono">
                            {% if row.Kredit > 0 %}
                                <span class="text-red-600 font-bold">{{ row.Kredit | rupiah }}</span>
                            {% else %}
                                <span class="text-gray-400">-</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="6" class="px-6 py-12 text-center text-gray-400"> 
                            <i class="fas fa-inbox text-4xl mb-3"></i>
                            <p class="text-lg font-medium">Belum ada transaksi jurnal</p>
                            <p class="text-sm mt-1">Data akan muncul setelah input transaksi</p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {
    // KUNCI PERBAIKAN: Gunakan | tojson | safe untuk memastikan JSON valid
    const chartData = {{ chart_data | tojson | safe }}; 
    
    if (chartData && chartData.length > 1) {
        const ctx = document.getElementById('profitChart').getContext('2d');
        
        const labels = chartData.map(item => {
            const [year, month] = item.month.split('-');
            const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 
                               'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
            return `${monthNames[parseInt(month)-1]} ${year}`;
        });
        
        const data = chartData.map(item => item.profit);
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Laba/Rugi Bersih',
                    data: data,
                    backgroundColor: 'rgba(220, 38, 38, 0.1)',
                    borderColor: 'rgb(220, 38, 38)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: data.map(profit => 
                        profit >= 0 ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)'
                    ),
                    pointBorderColor: 'white',
                    pointBorderWidth: 2,
                    pointRadius: 6,
                    pointHoverRadius: 8,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                const value = context.parsed.y;
                                const formatted = new Intl.NumberFormat('id-ID', {
                                    style: 'currency',
                                    currency: 'IDR',
                                    minimumFractionDigits: 0
                                }).format(value);
                                return label + formatted;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)',
                        },
                        ticks: {
                            callback: function(value) {
                                if (value >= 1000000) {
                                    return 'Rp ' + (value / 1000000).toFixed(1) + 'Jt';
                                } else if (value >= 1000) {
                                    return 'Rp ' + (value / 1000).toFixed(0) + 'Rb';
                                }
                                return 'Rp ' + value;
                            }
                        }
                    },
                    x: {
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)',
                        }
                    }
                }
            }
        });
    }
});
</script>
"""

HTML_PELUNASAN_PIUTANG = """
<div class="max-w-xl mx-auto bg-white p-8 rounded-xl shadow-lg border-t-4 border-blue-600">
    <h2 class="text-2xl font-bold text-blue-700 mb-6 flex items-center gap-2">
        <i class="fas fa-handshake"></i> Pelunasan Piutang
    </h2>
    <p class="text-gray-500 mb-4">Mencatat pembayaran yang diterima dari pelanggan.</p>
    
    <form method="POST" class="space-y-4">
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Tanggal Bayar</label>
            <input type="date" name="tanggal" value="{{ today }}" required class="w-full p-2 border rounded">
        </div>
        
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Nama Pelanggan (Pengutang)</label>
            <input type="text" name="kontak" required class="w-full p-2 border rounded" placeholder="Contoh: Budi, Toko Koi Jaya">
        </div>
        
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Jumlah Diterima (Rp)</label>
            <input type="text" name="jumlah" onkeyup="formatRupiah(this)" required class="w-full p-2 border rounded text-lg font-bold text-green-700" placeholder="Rp 0">
        </div>

        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Masuk ke Kas/Bank</label>
            <select name="metode_kas" class="w-full p-2 border rounded">
                <option value="Kas">Kas Tunai</option>
                <option value="Transfer">Bank Transfer</option>
            </select>
        </div>

        <button type="submit" class="w-full bg-blue-600 text-white font-bold py-3 rounded hover:bg-blue-700 transition">
            CATAT PELUNASAN
        </button>
    </form>
</div>
"""

# --- Template HTML Pelunasan Utang ---
HTML_PELUNASAN_UTANG = """
<div class="max-w-xl mx-auto bg-white p-8 rounded-xl shadow-lg border-t-4 border-orange-600">
    <h2 class="text-2xl font-bold text-orange-700 mb-6 flex items-center gap-2">
        <i class="fas fa-money-check-alt"></i> Pelunasan Utang
    </h2>
    <p class="text-gray-500 mb-4">Mencatat pembayaran yang Anda lakukan kepada supplier.</p>
    
    <form method="POST" class="space-y-4">
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Tanggal Bayar</label>
            <input type="date" name="tanggal" value="{{ today }}" required class="w-full p-2 border rounded">
        </div>
        
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Nama Supplier (Pemberi Utang)</label>
            <input type="text" name="kontak" required class="w-full p-2 border rounded" placeholder="Contoh: Toko Pakan Sejahtera">
        </div>
        
        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Jumlah Dibayarkan (Rp)</label>
            <input type="text" name="jumlah" onkeyup="formatRupiah(this)" required class="w-full p-2 border rounded text-lg font-bold text-red-700" placeholder="Rp 0">
        </div>

        <div>
            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Dibayarkan dari Kas/Bank</label>
            <select name="metode_kas" class="w-full p-2 border rounded">
                <option value="Kas">Kas Tunai</option>
                <option value="Transfer">Bank Transfer</option>
            </select>
        </div>

        <button type="submit" class="w-full bg-orange-600 text-white font-bold py-3 rounded hover:bg-orange-700 transition">
            CATAT PELUNASAN
        </button>
    </form>
</div>
"""

# ---------------- RUTE FLASK ----------------

@app.route("/")
@login_required
def index_page():
    try:
        user_id = session['user_id']
        username = session.get('username', 'Pengguna') # Mengambil username untuk sapaan
        
        # Get data untuk dashboard dengan error handling yang lebih baik
        try:
            stok_terkini = get_stok_terkini(user_id)
        except Exception as stok_error:
            print(f"⚠️ Error saat mengambil stok: {stok_error}")
            stok_terkini = {}  # Fallback ke dict kosong jika error
        
        # Data placeholder (sudah aman)
        total_pemasukan = 0 
        total_pengeluaran = 0 
        laba_rugi = 0 
        
        full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_INDEX)
        return render_template_string(
            full_html, 
            title="Beranda", 
            username=username, # Mengirim username ke HTML
            stok_terkini=stok_terkini,
            total_pemasukan=total_pemasukan,
            total_pengeluaran=total_pengeluaran,
            laba_rugi=laba_rugi
        )
        
    except Exception as e:
        print(f"❌ Error di beranda: {e}")
        print(traceback.format_exc())
        # Fallback ke halaman sederhana jika ada error
        # JANGAN redirect ke login, biarkan user tetap di dashboard dengan pesan error
        error_html = """
        <div class="text-center py-12">
            <div class="bg-white rounded-2xl p-8 max-w-2xl mx-auto">
                <i class="fas fa-exclamation-triangle text-yellow-500 text-5xl mb-4"></i>
                <h2 class="text-2xl font-bold text-gray-900 mb-2">Dashboard Sementara Tidak Tersedia</h2>
                <p class="text-gray-600 mb-6">Terjadi kesalahan saat memuat data dashboard. Silakan coba refresh halaman atau navigasi ke menu lain.</p>
                <div class="flex flex-wrap gap-4 justify-center">
                    <button onclick="window.location.reload()" class="btn-consistent btn-primary">
                        <i class="fas fa-redo mr-2"></i>Refresh Halaman
                    </button>
                    <a href="{{ url_for('pemasukan_page') }}" class="btn-consistent btn-secondary">
                        <i class="fas fa-arrow-down mr-2"></i>Pemasukan
                    </a>
                    <a href="{{ url_for('pengeluaran_page') }}" class="btn-consistent btn-secondary">
                        <i class="fas fa-arrow-up mr-2"></i>Pengeluaran
                    </a>
                    <a href="{{ url_for('laporan_page') }}" class="btn-consistent btn-secondary">
                        <i class="fas fa-chart-bar mr-2"></i>Laporan
                    </a>
                </div>
            </div>
        </div>
        """
        full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', error_html)
        return render_template_string(full_html, title="Beranda")
                              
@app.route("/login", methods=["GET", "POST"])
def login_page():
    # Jika sudah login, lempar ke dashboard
    if session.get('logged_in'):
        return redirect(url_for('index_page'))
        
    if request.method == "POST":
        email = request.form.get("email", "").strip() 
        password = request.form.get("password", "").strip()
        username = request.form.get("username", "").strip()
        mode = request.form.get("mode")
        
        if not email or not password:
            flash("Email dan password tidak boleh kosong.", "danger")
            return redirect(url_for('login_page'))

        # --- LOGIKA DAFTAR ---
        elif mode == "Daftar":
            if not username:
                flash("Username wajib diisi saat mendaftar.", "danger")
                return redirect(url_for('login_page'))
            try:
                # [PERBAIKAN UTAMA]
                # Kirim data ke metadata agar muncul di "Display Name" Supabase Auth
                # Kunci standar: 'full_name', 'name', atau 'display_name'
                response = supabase.auth.sign_up({
                    "email": email,
                    "password": password,
                    "options": {
                        "data": {
                            "username": username,     # Untuk aplikasi kita
                            "full_name": username,    # Agar terbaca di beberapa UI standar
                            "display_name": username, # Target utama dashboard Supabase
                            "name": username          # Cadangan
                        }
                    }
                })
                
                # Cek apakah user berhasil dibuat
                if response.user and response.user.id:
                    user_id = response.user.id
                    
                    # [OPSIONAL] Simpan ke tabel profiles (Hanya jika tabelnya ada)
                    # Kita pakai try-except kosong agar kalau tabel 'profiles' hilang,
                    # pendaftaran TETAP BERHASIL (tidak error).
                    try:
                        supabase.table("profiles").insert({
                            "id": user_id,
                            "username": username
                        }).execute()
                    except Exception:
                        # Abaikan error jika tabel profiles tidak ada.
                        # Data nama sudah aman di Auth Metadata.
                        pass

                    flash("Pendaftaran berhasil! Silakan login.", "success")
                else:
                    flash("Pendaftaran gagal. Cek kembali data Anda.", "danger")
                    
                return redirect(url_for('login_page'))
            
            except Exception as e:
                # Tangkap error spesifik Supabase
                err_msg = str(e)
                if "User already registered" in err_msg:
                    flash("Email sudah terdaftar. Silakan login.", "warning")
                else:
                    flash(f"Gagal mendaftar: {err_msg}", "danger")
            return redirect(url_for('login_page'))     
           
        # --- LOGIKA LOGIN ---
        elif mode == "Login":
            try:
                # 1. Login ke Supabase Auth
                response = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })
                
                user = response.user
                
                # 2. [PERBAIKAN] Ambil Username dari Metadata Auth (Lebih Cepat & Aman)
                # Prioritas: Metadata > Email
                meta = user.user_metadata or {}
                # Cari kunci mana yang tersedia
                login_username = meta.get('username') or meta.get('display_name') or meta.get('full_name') or meta.get('name') or user.email

                # 3. Simpan Session Flask
                session['logged_in'] = True
                session['username'] = login_username # Username fix dari Auth
                session['user_id'] = user.id
                session['access_token'] = response.session.access_token
                session['refresh_token'] = response.session.refresh_token
                
                flash(f"Selamat datang, {login_username}.", "success")
                return redirect(url_for('index_page'))
            
            except Exception as e:
                flash("Login gagal. Periksa email atau password.", "danger")
                print(f"Login Error: {e}") # Debug di terminal
            return redirect(url_for('login_page'))

    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_LOGIN)
    return render_template_string(full_html, title="Login")

@app.route("/logout")
def logout_page():
    try:
        # Matikan sesi di Supabase (optional, tapi bagus buat keamanan)
        supabase.auth.sign_out() 
    except Exception as e:
        print(f"Error saat logout Supabase: {e}")
        
    session.clear() # Hapus semua data sesi di Flask
    flash("Anda telah berhasil logout.", "success")
    return redirect(url_for('login_page'))

@app.route("/laporan", methods=["GET", "POST"])
@login_required
def laporan_page():
    user_id = session['user_id']
    
    # Default values untuk mencegah error
    filter_tanggal = {"mulai": datetime.now().replace(day=1).strftime("%Y-%m-%d"), "akhir": datetime.now().strftime("%Y-%m-%d")}
    ringkasan = {"total_pemasukan": 0, "total_pengeluaran": 0, "laba_rugi": 0} 
    laba_rugi_data = {
        "rincian_pendapatan": [], 
        "rincian_beban": [], 
        "pendapatan_total": 0.0, 
        "beban_total": 0.0, 
        "hpp_total": 0.0, 
        "laba_kotor": 0.0, 
        "laba_bersih": 0.0
    }
    neraca = {
        "kas_bank": 0.0, 
        "piutang": 0.0, 
        "persediaan": 0.0,
        "aset_tetap_net": 0.0,
        "aktiva": 0.0, 
        "pasiva": 0.0, 
        "kewajiban": [], 
        "ekuitas": 0.0, 
        "aset_lancar": [], 
        "aset_tetap": [], 
        "is_balance": True,
        "total_ekuitas_laba": 0.0 
    }
    buku_besar = {}
    buku_besar_pembantu = {'piutang': [], 'utang': []} 
    chart_data = [] # Pastikan ini kosong jika tidak ada data
    now_formatted = datetime.now().strftime('%d %B %Y, %H:%M:%S')
    
    # --- Helper Lokal untuk Filtering ---
    def filter_by_date(df, start_date, end_date, date_column='Tanggal'):
        if df.empty or date_column not in df.columns: 
            return pd.DataFrame()
        try:
            if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                df[date_column] = pd.to_datetime(df[date_column], errors='coerce', utc=True).dt.tz_localize(None)
            
            mask = (df[date_column] >= start_date) & (df[date_column] <= end_date)
            return df.loc[mask].copy() 
        except Exception as e:
            return pd.DataFrame()
    # --- Akhir Helper Lokal ---

    try:
        # Handle date filter
        if request.method == "POST":
            mulai_str = request.form.get("mulai")
            akhir_str = request.form.get("akhir")
        else:
            mulai_str = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            akhir_str = datetime.now().strftime("%Y-%m-%d")
        
        filter_tanggal = {"mulai": mulai_str, "akhir": akhir_str}
        
        # Parse dates dengan error handling
        try:
            mulai_dt = datetime.strptime(mulai_str, "%Y-%m-%d")
            akhir_dt = datetime.strptime(akhir_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59) 
        except ValueError:
            mulai_dt = datetime.now().replace(day=1)
            akhir_dt = datetime.now().replace(hour=23, minute=59, second=59)
            filter_tanggal = {"mulai": mulai_dt.strftime("%Y-%m-%d"), "akhir": akhir_dt.strftime("%Y-%m-%d")}

        # ==================== LOAD DATA TERINTEGRASI ====================
        
        jurnal_df = load_data_from_db("jurnal", user_id)
        pemasukan_df = load_data_from_db("pemasukan", user_id)
        pengeluaran_df = load_data_from_db("pengeluaran", user_id)
        aset_df = load_data_from_db("aset_tetap", user_id)
        
        jurnal_df = clean_data_and_format_df(jurnal_df)
        pemasukan_df = clean_data_and_format_df(pemasukan_df)
        pengeluaran_df = clean_data_and_format_df(pengeluaran_df)

        jurnal_df_f = filter_by_date(jurnal_df, mulai_dt, akhir_dt)
        jurnal_total = filter_by_date(jurnal_df, datetime(2000,1,1), akhir_dt) 
        pemasukan_periode = filter_by_date(pemasukan_df, mulai_dt, akhir_dt)
        pengeluaran_periode = filter_by_date(pengeluaran_df, mulai_dt, akhir_dt)

        # --- VALIDASI KRITIS SAK: CEK BALANCE JURNAL TOTAL ---
        if not jurnal_total.empty:
            jurnal_total['Debit'] = pd.to_numeric(jurnal_total['Debit'], errors='coerce').fillna(0)
            jurnal_total['Kredit'] = pd.to_numeric(jurnal_total['Kredit'], errors='coerce').fillna(0)
            
            total_debit_all = jurnal_total['Debit'].sum()
            total_kredit_all = jurnal_total['Kredit'].sum()
            
            if abs(total_debit_all - total_kredit_all) > 1.0: 
                pass 
        # --------------------------------------------------------

        # ==================== 1. RINGKASAN CEPAT ====================
        ringkasan["total_pemasukan"] = float(pemasukan_periode['Jumlah'].sum()) if not pemasukan_periode.empty else 0.0
        ringkasan["total_pengeluaran"] = float(pengeluaran_periode['Jumlah'].sum()) if not pengeluaran_periode.empty else 0.0
        ringkasan["laba_rugi"] = ringkasan["total_pemasukan"] - ringkasan["total_pengeluaran"]

        # ==================== 2. LAPORAN LABA RUGI TERINTEGRASI ====================
        if not jurnal_df_f.empty:
            jurnal_df_f['Debit'] = pd.to_numeric(jurnal_df_f['Debit'], errors='coerce').fillna(0)
            jurnal_df_f['Kredit'] = pd.to_numeric(jurnal_df_f['Kredit'], errors='coerce').fillna(0)
            
            pendapatan_akun = jurnal_df_f[jurnal_df_f['Akun'].str.contains('Penjualan|Pendapatan', na=False, case=False)]
            if not pendapatan_akun.empty:
                rincian_pendapatan = pendapatan_akun.groupby('Akun')['Kredit'].sum().reset_index()
                rincian_pendapatan = rincian_pendapatan.rename(columns={'Kredit': 'Jumlah'})
                rincian_pendapatan = rincian_pendapatan[rincian_pendapatan['Jumlah'] > 0]
                laba_rugi_data["rincian_pendapatan"] = rincian_pendapatan.to_dict('records')
                laba_rugi_data["pendapatan_total"] = float(rincian_pendapatan['Jumlah'].sum())
            
            beban_akun = jurnal_df_f[
                jurnal_df_f['Akun'].str.contains('Beban', na=False, case=False) & 
                ~jurnal_df_f['Akun'].str.contains('Harga Pokok', na=False)
            ]
            if not beban_akun.empty:
                rincian_beban = beban_akun.groupby('Akun')['Debit'].sum().reset_index()
                rincian_beban = rincian_beban.rename(columns={'Debit': 'Jumlah'})
                rincian_beban = rincian_beban[rincian_beban['Jumlah'] > 0]
                laba_rugi_data["rincian_beban"] = rincian_beban.to_dict('records')
                laba_rugi_data["beban_total"] = float(rincian_beban['Jumlah'].sum())
            
            hpp_akun = jurnal_df_f[jurnal_df_f['Akun'] == 'Harga Pokok Penjualan']
            laba_rugi_data["hpp_total"] = float(hpp_akun['Debit'].sum()) if not hpp_akun.empty else 0.0
            
            laba_rugi_data["laba_kotor"] = laba_rugi_data["pendapatan_total"] - laba_rugi_data["hpp_total"]
            laba_rugi_data["laba_bersih"] = float(laba_rugi_data["laba_kotor"] - laba_rugi_data["beban_total"])

        # ==================== 3. NERACA TERINTEGRASI ====================
        if not jurnal_total.empty:
            
            # --- Perhitungan Saldo Akun ---
            def hitung_saldo_akun(akun_list, df):
                """Hitung saldo Debit - Kredit (Normal Balance Debit)"""
                df_akun = df[df['Akun'].isin(akun_list)]
                saldo = df_akun['Debit'].sum() - df_akun['Kredit'].sum()
                return float(saldo)
                
            # Saldo Akun Pasiva (Normal Kredit), dihitung sebagai Kredit - Debit
            def hitung_saldo_pasiva(akun_list, df):
                """Hitung saldo Kredit - Debit (Normal Balance Kredit)"""
                df_akun = df[df['Akun'].isin(akun_list)]
                saldo = df_akun['Kredit'].sum() - df_akun['Debit'].sum()
                return float(saldo)

            # ASET LANCAR
            neraca["kas_bank"] = hitung_saldo_akun(['Kas', 'Bank'], jurnal_total)
            neraca["perlengkapan"] = hitung_saldo_akun(['Perlengkapan'], jurnal_total)
            neraca["piutang"] = hitung_saldo_akun(['Piutang Dagang'], jurnal_total)
            
            # PERSEDIAAN
            persediaan_akun_list = [v for k, v in akun_persediaan.items()] 
            neraca["persediaan"] = hitung_saldo_akun(persediaan_akun_list, jurnal_total)
            
            # ASET TETAP (NET)
            aset_tetap_bruto_list = ['Aset - Kendaraan', 'Aset - Bangunan']
            akumulasi_susut_list = ['Akumulasi Penyusutan - Kendaraan', 'Akumulasi Penyusutan - Bangunan']
            
            nilai_aset_tetap = hitung_saldo_akun(aset_tetap_bruto_list, jurnal_total)
            saldo_akumulasi_bersih = hitung_saldo_akun(akumulasi_susut_list, jurnal_total) 
            
            neraca["aset_tetap_net"] = nilai_aset_tetap + saldo_akumulasi_bersih 

            # KEWAJIBAN
            neraca["utang_dagang"] = hitung_saldo_pasiva(['Utang Dagang'], jurnal_total)
            
            # EKUITAS (Modal, Laba Ditahan, dan Historical Balancing)
            neraca_modal_murni = hitung_saldo_pasiva(['Modal Owner', 'Laba Ditahan'], jurnal_total)
            saldo_historical_balancing = hitung_saldo_pasiva(['Historical Balancing'], jurnal_total)
            neraca_ekuitas_bersih_total = neraca_modal_murni + saldo_historical_balancing

            # Susun Neraca
            neraca["aset_lancar"] = [
                {"Akun": "Kas & Bank", "Nilai": neraca["kas_bank"]}, 
                {"Akun": "Perlengkapan", "Nilai": neraca["perlengkapan"]},
                {"Akun": "Piutang Dagang", "Nilai": neraca["piutang"]},
                {"Akun": "Persediaan Ikan", "Nilai": neraca["persediaan"]}
            ]
            
            neraca["aset_tetap"] = [
                {"Akun": "Aset Tetap (Harga Perolehan)", "Nilai": nilai_aset_tetap},
                {"Akun": "Akumulasi Penyusutan", "Nilai": saldo_akumulasi_bersih} 
            ]
            
            neraca["kewajiban"] = [
                {"Akun": "Utang Dagang", "Nilai": neraca["utang_dagang"]}
            ]
            
            # Hitung total
            total_aset_lancar = sum(item["Nilai"] for item in neraca["aset_lancar"])
            
            # TOTAL AKTIVA
            neraca["aktiva"] = total_aset_lancar + neraca["aset_tetap_net"]
            
            total_kewajiban = sum(item["Nilai"] for item in neraca["kewajiban"])
            
            # TOTAL EKUITAS (Modal Murni)
            neraca["ekuitas"] = neraca_modal_murni 
            
            # TOTAL PASIVA = Kewajiban + Ekuitas Awal + Laba Bersih Periode
            neraca["total_ekuitas_laba"] = neraca_ekuitas_bersih_total + laba_rugi_data["laba_bersih"]
            neraca["pasiva"] = total_kewajiban + neraca["total_ekuitas_laba"]
            
            # Cek balance (Logika Aman tanpa abs())
            selisih = float(neraca["aktiva"] - neraca["pasiva"])
            if selisih < 0:
                selisih = -selisih
                
            neraca["is_balance"] = selisih < 1.0

        # ==================== 4. BUKU BESAR TERINTEGRASI (SUDAH DIPERBAIKI) ====================
        # LOGIKA BARU: Mengisi variabel buku_besar agar data muncul di tabel
        if not jurnal_df_f.empty:
            # Pastikan kolom Tanggal ada dan aman
            if 'Tanggal' in jurnal_df_f.columns:
                # Grouping data berdasarkan Nama Akun
                for akun_nama, group_data in jurnal_df_f.groupby('Akun'):
                    # Sortir berdasarkan tanggal agar urut
                    group_data = group_data.sort_values('Tanggal')
                    
                    entries_list = []
                    saldo_berjalan = 0
                    
                    for idx, row in group_data.iterrows():
                        debit = float(row['Debit'])
                        kredit = float(row['Kredit'])
                        
                        # Rumus Saldo Sederhana: Debit nambah (+), Kredit kurang (-)
                        # (Untuk keperluan display Buku Besar Umum)
                        saldo_berjalan += (debit - kredit)
                        
                        # Format Tanggal ke string
                        tgl_str = row['Tanggal'].strftime('%Y-%m-%d') if hasattr(row['Tanggal'], 'strftime') else str(row['Tanggal'])[:10]
                        
                        entries_list.append({
                            "Tanggal": tgl_str,
                            "Keterangan": row['Keterangan'],
                            "Kontak": row.get('Kontak', '-'),
                            "Debit": debit,
                            "Kredit": kredit,
                            "Saldo": saldo_berjalan
                        })
                    
                    # Simpan ke dictionary buku_besar
                    buku_besar[akun_nama] = entries_list

        # ==================== 5. DATA GRAFIK TERINTEGRASI ====================
        # Hanya hitung jika ada data jurnal secara keseluruhan
        if not jurnal_df.empty:
            
            # 1. Pastikan kolom YearMonth ada (dibuat di clean_data_and_format_df)
            if 'YearMonth' not in jurnal_df.columns:
                 jurnal_df = clean_data_and_format_df(jurnal_df)
                 if 'YearMonth' not in jurnal_df.columns:
                     # Gagal membuat kolom YearMonth, hentikan proses chart
                     pass # Lanjut ke return tanpa chart
            
            # Hanya jalankan jika YearMonth berhasil dibuat
            if 'YearMonth' in jurnal_df.columns:
                try:
                    current_month = datetime.now().replace(day=1)
                    months_to_show = []
                    
                    # Kumpulkan 6 bulan terakhir
                    for i in range(6):
                        month = (current_month - relativedelta(months=i)).strftime('%Y-%m')
                        months_to_show.append(month)
                    
                    months_to_show.reverse()
                    
                    for month_str in months_to_show:
                        year, month = map(int, month_str.split('-'))
                        month_start = datetime(year, month, 1)
                        
                        # Tentukan akhir bulan
                        if month == 12:
                            month_end = datetime(year+1, 1, 1) - relativedelta(microseconds=1)
                        else:
                            month_end = datetime(year, month+1, 1) - relativedelta(microseconds=1)
                        
                        # Filter jurnal untuk bulan ini
                        monthly_df = filter_by_date(jurnal_df, month_start, month_end)
                        
                        # Hitung Laba Bersih Bulanan
                        pendapatan_bulanan = monthly_df[monthly_df['Akun'].str.contains('Penjualan|Pendapatan', na=False)]['Kredit'].sum() if not monthly_df.empty else 0
                        beban_bulanan = monthly_df[monthly_df['Akun'].str.contains('Beban', na=False) & ~monthly_df['Akun'].str.contains('Harga Pokok', na=False)]['Debit'].sum() if not monthly_df.empty else 0
                        hpp_bulanan = monthly_df[monthly_df['Akun'] == 'Harga Pokok Penjualan']['Debit'].sum() if not monthly_df.empty else 0
                        laba_bersih_bulanan = pendapatan_bulanan - hpp_bulanan - beban_bulanan
                        
                        # Tambahkan data ke list chart
                        chart_data.append({
                            'month': month_str,
                            'profit': float(laba_bersih_bulanan), 
                        })
                    
                except Exception as chart_error:
                    print(f"Error generating chart data: {chart_error}")
                    chart_data = [] 
        
        # Hitung Buku Besar Pembantu (Piutang/Utang Detail)
        buku_besar_pembantu = aggregate_subsidiary_ledger(jurnal_total)


    except Exception as e:
        print(f"❌ [FATAL ERROR IN LAPORAN PAGE]: {e}")
        print(traceback.format_exc())
        flash(f"Terjadi error saat memproses laporan: {str(e)}", "danger")

    # ==================== RENDER TEMPLATE DENGAN SEMUA DATA ====================
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_LAPORAN)
    return render_template_string(
        full_html, 
        title="Laporan Keuangan Terintegrasi",
        filter=filter_tanggal,
        ringkasan=ringkasan,
        laba_rugi=laba_rugi_data,
        neraca=neraca,
        buku_besar=buku_besar,
        buku_besar_pembantu=buku_besar_pembantu, 
        jurnal_df=jurnal_df_f.to_dict('records') if not jurnal_df_f.empty else [],
        chart_data=chart_data,
        now=now_formatted
    )
    
@app.route("/pemasukan", methods=["GET", "POST"])
@login_required
def pemasukan_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            # --- Logika Simpan Data ---
            tanggal = request.form.get("tanggal")
            waktu = datetime.combine(datetime.strptime(tanggal, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            sumber = request.form.get("sumber")
            sub_sumber = request.form.get("sub_sumber")
            jumlah = int(float(request.form.get("jumlah", "0").replace(".", "").replace("Rp", "").strip()))
            metode = request.form.get("metode_pemasukan")
            kontak = request.form.get("kontak", "").strip()
            deskripsi = request.form.get("deskripsi", "")

            # Upload Bukti (Logika yang sama)
            url_bukti = None
            if 'bukti' in request.files:
                file = request.files['bukti']
                if file.filename != '':
                    try:
                        filename = f"{user_id}/{int(datetime.now().timestamp())}_{file.filename}"
                        file_content = file.read()
                        supabase.storage.from_("bukti_transaksi").upload(path=filename, file=file_content, file_options={"content-type": file.content_type})
                        url_bukti = supabase.storage.from_("bukti_transaksi").get_public_url(filename)
                    except: pass

            # Simpan Pemasukan
            data_pemasukan = {
                "Tanggal": waktu, "Sumber": sumber, "Sub_Sumber": sub_sumber,
                "Jumlah": jumlah, "Metode": metode, "Kontak": kontak, "Keterangan": deskripsi,
                "url_bukti": url_bukti
            }
            trx_id = append_data_to_db("pemasukan", data_pemasukan, user_id)

            # Jurnal Dasar Penjualan
            akun_debit = "Piutang Dagang" if metode == "Piutang" else "Kas"
            jurnal_entries = [
                {"Tanggal": waktu, "Akun": akun_debit, "Debit": jumlah, "Kredit": 0, "Keterangan": f"{sumber} - {deskripsi}", "Kontak": kontak},
                {"Tanggal": waktu, "Akun": sub_sumber, "Debit": 0, "Kredit": jumlah, "Keterangan": f"{sumber} - {deskripsi}", "Kontak": kontak}
            ]

            # Update Stok & Jurnal HPP (Jika Penjualan)
            stok_item_id = request.form.get("stok_item_id")
            stok_qty_str = request.form.get("stok_qty")
            
            if stok_item_id and stok_qty_str:
                stok_qty = int(float(stok_qty_str))
                stok_list = hitung_stok_akhir(user_id)
                item_data = next((x for x in stok_list if str(x['id']) == str(stok_item_id)), None)
                
                if item_data and stok_qty > 0:
                    hpp_total = int(stok_qty * item_data['harga_rata_rata'])
                    
                    # 1. Update Kartu Stok (Pengurangan)
                    supabase.from_("persediaan").insert({
                        "tanggal": waktu, "deskripsi": f"Penjualan - {sub_sumber}",
                        "barang": item_data['item'], "masuk": 0, "keluar": stok_qty,
                        "harga_satuan": int(item_data['harga_rata_rata']),
                        "keterangan": f"Ref: {kontak}", "user_id": user_id
                    }).execute()
                    
                    # 2. Jurnal HPP (Debit HPP, Kredit Persediaan SPESIFIK)
                    akun_persediaan_spesifik = akun_persediaan.get(item_data['item'], "Persediaan - Ikan Koi")
                    
                    jurnal_entries.extend([
                        {"Tanggal": waktu, "Akun": "Harga Pokok Penjualan", "Debit": hpp_total, "Kredit": 0, "Keterangan": f"HPP {item_data['item']}", "Kontak": ""},
                        {"Tanggal": waktu, "Akun": akun_persediaan_spesifik, "Debit": 0, "Kredit": hpp_total, "Keterangan": f"HPP {item_data['item']}", "Kontak": ""}
                    ])

            buat_jurnal_batch(jurnal_entries, user_id)
            flash("Pemasukan berhasil disimpan.", "success")
            return redirect(url_for('pemasukan_page'))
            
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('pemasukan_page'))

    stok_list = hitung_stok_akhir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PEMASUKAN)    
    return render_template_string(full_html, title="Pemasukan", today=today, kategori_pemasukan=kategori_pemasukan, stok_list=stok_list)

@app.route("/pengeluaran", methods=["GET", "POST"])
@login_required
def pengeluaran_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            # --- Logika Simpan Data ---
            tanggal = request.form.get("tanggal")
            waktu = datetime.combine(datetime.strptime(tanggal, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            kategori = request.form.get("kategori")
            sub_kategori = request.form.get("sub_kategori")
            jumlah = int(float(request.form.get("jumlah", "0").replace(".", "").replace("Rp", "").strip()))
            metode = request.form.get("metode_pengeluaran")
            deskripsi = request.form.get("deskripsi", "")
            kontak = request.form.get("kontak", "").strip()
            
            # Upload Bukti (Logika yang sama)
            url_bukti = None
            if 'bukti' in request.files:
                file = request.files['bukti']
                if file.filename != '':
                    try:
                        filename = f"{user_id}/{int(datetime.now().timestamp())}_{file.filename}"
                        file_content = file.read()
                        supabase.storage.from_("bukti_transaksi").upload(path=filename, file=file_content, file_options={"content-type": file.content_type})
                        url_bukti = supabase.storage.from_("bukti_transaksi").get_public_url(filename)
                    except: pass

            data_pengeluaran = {
                "Tanggal": waktu, "Kategori": kategori, "Sub_Kategori": sub_kategori,
                "Jumlah": jumlah, "Keterangan": deskripsi, "Metode": metode, "Kontak": kontak,
                "url_bukti": url_bukti
            }
            trx_id = append_data_to_db("pengeluaran", data_pengeluaran, user_id)
            
            # Integrasi Stok Masuk
            stok_nama = request.form.get("stok_nama") # Nama ikan (Kohaku, Shusui, dst.)
            stok_qty_str = request.form.get("stok_qty")
            jurnal_entries = []
            akun_kredit = "Utang Dagang" if metode == "Utang" else "Kas"

            if stok_nama and stok_qty_str:
                # Transaksi Pembelian Stok
                stok_qty = int(float(stok_qty_str))
                stok_kat = request.form.get("stok_kat")
                
                if stok_qty > 0:
                    harga_satuan = int(jumlah / stok_qty)
                    
                    # 1. Update Kartu Stok (Penambahan)
                    supabase.from_("persediaan").insert({
                        "tanggal": waktu, "deskripsi": f"Pembelian - {kontak}",
                        "barang": stok_nama, "masuk": stok_qty, "keluar": 0,
                        "harga_satuan": harga_satuan, "keterangan": deskripsi, "user_id": user_id
                    }).execute()
                    
                    # 2. Jurnal Pembelian (Debit Persediaan SPESIFIK, Kredit Kas/Utang)
                    akun_debit_persediaan = akun_persediaan.get(stok_nama, "Persediaan - Ikan Koi")
                    
                    jurnal_entries = [
                        {"Tanggal": waktu, "Akun": akun_debit_persediaan, "Debit": jumlah, "Kredit": 0, "Keterangan": f"Beli Stok {stok_nama}", "Kontak": kontak},
                        {"Tanggal": waktu, "Akun": akun_kredit, "Debit": 0, "Kredit": jumlah, "Keterangan": f"Beli Stok {stok_nama}", "Kontak": kontak}
                    ]
            else:
                # Transaksi Pengeluaran Beban Biasa
                jurnal_entries = [
                    {"Tanggal": waktu, "Akun": sub_kategori, "Debit": jumlah, "Kredit": 0, "Keterangan": f"{kategori} - {deskripsi}", "Kontak": kontak},
                    {"Tanggal": waktu, "Akun": akun_kredit, "Debit": 0, "Kredit": jumlah, "Keterangan": f"{kategori} - {deskripsi}", "Kontak": kontak}
                ]
            
            buat_jurnal_batch(jurnal_entries, user_id)
            flash("Pengeluaran berhasil disimpan.", "success")
            return redirect(url_for('pengeluaran_page'))
            
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('pengeluaran_page'))

    stok_list = hitung_stok_akhir(user_id)
    unique_items = list(set([x['item'] for x in stok_list]))
    today = datetime.now().strftime("%Y-%m-%d")
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PENGELUARAN)    
    return render_template_string(full_html, title="Pengeluaran", today=today, kategori_pengeluaran=kategori_pengeluaran, list_stok=list_kategori_stok, unique_items=unique_items)

@app.route("/pelunasan_piutang", methods=["GET", "POST"])
@login_required
def pelunasan_piutang_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            tanggal = request.form.get("tanggal")
            waktu = datetime.combine(datetime.strptime(tanggal, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            jumlah = int(float(request.form.get("jumlah", "0").replace(".", "").replace("Rp", "").strip()))
            kontak = request.form.get("kontak", "").strip()
            metode_kas = request.form.get("metode_kas")

            if jumlah <= 0 or not kontak:
                flash("Jumlah dan Nama Pelanggan wajib diisi.", "danger")
                return redirect(url_for('pelunasan_piutang_page'))

            # Jurnal: Debit Kas/Bank, Kredit Piutang Dagang
            akun_debit_kas = "Bank" if metode_kas == "Transfer" else "Kas"
            
            jurnal = [
                # Debit Kas/Bank (Meningkatkan Aset Kas/Bank)
                {"Tanggal": waktu, "Akun": akun_debit_kas, "Debit": jumlah, "Kredit": 0, "Keterangan": f"Pelunasan Piutang dari {kontak}", "Kontak": ""},
                # Kredit Piutang Dagang (Mengurangi Aset Piutang)
                {"Tanggal": waktu, "Akun": "Piutang Dagang", "Debit": 0, "Kredit": jumlah, "Keterangan": f"Pelunasan Piutang dari {kontak}", "Kontak": kontak}
            ]
            buat_jurnal_batch(jurnal, user_id)
            
            flash(f"Pelunasan Piutang sebesar {format_rupiah(jumlah)} dari {kontak} berhasil dicatat.", "success")
            return redirect(url_for('pelunasan_piutang_page'))
            
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('pelunasan_piutang_page'))

    today = datetime.now().strftime("%Y-%m-%d")
    
    # Render template Pelunasan Piutang
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PELUNASAN_PIUTANG)    
    return render_template_string(full_html, title="Pelunasan Piutang", today=today)

@app.route("/pelunasan_utang", methods=["GET", "POST"])
@login_required
def pelunasan_utang_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            tanggal = request.form.get("tanggal")
            waktu = datetime.combine(datetime.strptime(tanggal, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            jumlah = int(float(request.form.get("jumlah", "0").replace(".", "").replace("Rp", "").strip()))
            kontak = request.form.get("kontak", "").strip()
            metode_kas = request.form.get("metode_kas")

            if jumlah <= 0 or not kontak:
                flash("Jumlah dan Nama Supplier wajib diisi.", "danger")
                return redirect(url_for('pelunasan_utang_page'))

            # Jurnal: Debit Utang Dagang, Kredit Kas/Bank
            akun_kredit_kas = "Bank" if metode_kas == "Transfer" else "Kas"
            
            jurnal = [
                # Debit Utang Dagang (Mengurangi Kewajiban)
                {"Tanggal": waktu, "Akun": "Utang Dagang", "Debit": jumlah, "Kredit": 0, "Keterangan": f"Pelunasan Utang kepada {kontak}", "Kontak": kontak},
                # Kredit Kas/Bank (Mengurangi Aset Kas/Bank)
                {"Tanggal": waktu, "Akun": akun_kredit_kas, "Debit": 0, "Kredit": jumlah, "Keterangan": f"Pelunasan Utang kepada {kontak}", "Kontak": ""}
            ]
            buat_jurnal_batch(jurnal, user_id)
            
            flash(f"Pelunasan Utang sebesar {format_rupiah(jumlah)} kepada {kontak} berhasil dicatat.", "success")
            return redirect(url_for('pelunasan_utang_page'))
            
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('pelunasan_utang_page'))

    today = datetime.now().strftime("%Y-%m-%d")
    
    # Render template Pelunasan Utang
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PELUNASAN_UTANG)    
    return render_template_string(full_html, title="Pelunasan Utang", today=today)

@app.route("/api/stok/<string:barang>")
@login_required
def api_stok(barang):
    """API untuk mendapatkan stok terkini per barang"""
    user_id = session['user_id']
    stok_data = get_stok_terkini(user_id, barang)
    stok = stok_data.get(barang, 0)
    return jsonify({"stok": stok})

@app.route("/laporan-persediaan")
@login_required
def laporan_persediaan_page():
    user_id = session['user_id']
    
    # Get stok terkini
    stok_terkini = get_stok_terkini(user_id)
    
    # Get riwayat persediaan
    riwayat_persediaan = get_riwayat_persediaan(user_id, 50)
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_LAPORAN_PERSEDIAAN)
    return render_template_string(full_html, 
                                title="Laporan Persediaan",
                                stok_terkini=stok_terkini,
                                riwayat_persediaan=riwayat_persediaan)

# --- Rute Persediaan (GANTI TOTAL) ---
@app.route("/persediaan", methods=["GET", "POST"])
@login_required
def persediaan_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "stok_awal":
            try:
                # Ambil tanggal dari form
                tanggal_str = request.form.get("tanggal_saldo_awal")
                waktu = datetime.combine(datetime.strptime(tanggal_str, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")

                barang = request.form.get("barang_ikan")
                qty = int(float(request.form.get("qty")))
                harga_satuan = int(float(request.form.get("harga_satuan", "0").replace(".", "").replace("Rp", "").strip()))
                
                if qty <= 0 or harga_satuan <= 0:
                    flash("Jumlah dan Harga Satuan harus lebih dari nol.", "danger")
                    return redirect(url_for('persediaan_page'))
                    
                total_nilai = qty * harga_satuan
                
                # 1. Simpan Stok Masuk (Persediaan)
                supabase.from_("persediaan").insert({
                    "tanggal": waktu,
                    "deskripsi": "Saldo Awal Bisnis",
                    "barang": barang,
                    "masuk": qty,
                    "keluar": 0,
                    "harga_satuan": harga_satuan,
                    "keterangan": "Input Saldo Awal",
                    "user_id": user_id
                }).execute()
                
                # 2. Buat Jurnal (Persediaan DEBIT, Historical Balancing KREDIT)
                akun_persediaan_aset = akun_persediaan.get(barang, "Persediaan - Ikan Koi")
                jurnal = [
                    {"Tanggal": waktu, "Akun": akun_persediaan_aset, "Debit": total_nilai, "Kredit": 0, "Keterangan": f"Stok Awal {barang}", "Kontak": ""},
                    {"Tanggal": waktu, "Akun": "Historical Balancing", "Debit": 0, "Kredit": total_nilai, "Keterangan": f"Stok Awal Kontribusi Modal {barang}", "Kontak": ""}
                ]
                buat_jurnal_batch(jurnal, user_id)
                
                flash(f"Stok Awal {barang} ({qty} ekor) berhasil dicatat ke Historical Balancing.", "success")
                
            except Exception as e:
                flash(f"Gagal mencatat stok awal: {e}", "danger")
            return redirect(url_for('persediaan_page'))

        # ... (Logika 'adjustment' tetap sama) ...
        
    # GET REQUEST
    stok_akhir = hitung_stok_akhir(user_id)
    kartu_stok = get_kartu_stok(user_id)
    total_aset = sum(x['stok_akhir'] * x['harga_rata_rata'] for x in stok_akhir)
    today = datetime.now().strftime("%Y-%m-%d") # Pastikan today didefinisikan
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PERSEDIAAN)
    return render_template_string(full_html, title="Kartu Stok", 
                                  stok_list=stok_akhir,
                                  stok_akhir=stok_akhir,
                                  kartu_stok=kartu_stok,
                                  total_aset=total_aset,
                                  jenis_ikan=jenis_ikan,
                                  today=today) 

# 5. FITUR TAMBAHAN (KELOLA, ASET, PENYUSUTAN)
# ==========================================
# app.py

# ... (Kode sebelumnya) ...

@app.route("/kelola")
@login_required
def kelola_page():
    user_id = session['user_id']
    
    # 1. Load data transaksi (Pemasukan/Pengeluaran)
    # ... (Pastikan load_data_from_db dan sort sudah benar)
    pemasukan_df = load_data_from_db("pemasukan", user_id)
    if not pemasukan_df.empty:
        pemasukan_df = clean_data_and_format_df(pemasukan_df) # PENTING: Bersihkan
        pemasukan_df = pemasukan_df.sort_values(by="Tanggal", ascending=False)
    
    pengeluaran_df = load_data_from_db("pengeluaran", user_id)
    if not pengeluaran_df.empty:
        pengeluaran_df = clean_data_and_format_df(pengeluaran_df) # PENTING: Bersihkan
        pengeluaran_df = pengeluaran_df.sort_values(by="Tanggal", ascending=False)

    # 2. Load SEMUA data jurnal
    jurnal_total = load_data_from_db("jurnal", user_id)
    jurnal_total = clean_data_and_format_df(jurnal_total)
    
    if not jurnal_total.empty and 'Tanggal' in jurnal_total.columns:
        # Gunakan Tanggal_str yang sudah aman dari clean_data_and_format_df
        # Jika kolom Tanggal_str belum ada, buat lagi.
        if 'Tanggal_str' not in jurnal_total.columns:
             jurnal_total['Tanggal_str'] = jurnal_total['Tanggal'].apply(
                 lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if hasattr(x, 'strftime') else str(x)
             )
        
    # 3. Hitung saldo piutang dan utang per kontak
    buku_besar_pembantu = aggregate_subsidiary_ledger(jurnal_total)
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_KELOLA_DATA)
    return render_template_string(full_html, 
                                  title="Kelola Data", 
                                  pemasukan_df=pemasukan_df.to_dict('records'), 
                                  pengeluaran_df=pengeluaran_df.to_dict('records'),
                                  # Kirim data Jurnal Total dan Buku Besar Pembantu ke template
                                  # Kita akan menggunakan kolom 'Tanggal_str' di HTML
                                  jurnal_total=jurnal_total.to_dict('records'),
                                  buku_besar_pembantu=buku_besar_pembantu)

# --- Rute Hapus Transaksi ---
@app.route("/hapus/<string:tipe>/<int:db_id>")
@login_required
def hapus_page(tipe, db_id):
    user_id = session['user_id']
    if tipe not in ['pemasukan', 'pengeluaran']:
        return redirect(url_for('kelola_page'))
    
    if hapus_transaksi_db(tipe, db_id, user_id):
        flash(f"Data {tipe} berhasil dihapus.", "success")
    else:
        flash("Gagal menghapus data.", "danger")
    return redirect(url_for('kelola_page'))

# --- Rute Aset Tetap ---
@app.route("/aset_tetap", methods=["GET", "POST"])
@login_required
def aset_tetap_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        action = request.form.get("action")
        
        # --- HANDLER HAPUS ASET ---
        if action == "hapus_aset":
            try:
                aset_id = int(request.form.get("aset_id"))
                hapus_aset_db(aset_id, user_id)
                flash("Aset dan semua jurnal terkait berhasil dihapus.", "success")
            except Exception as e:
                flash(f"Gagal menghapus aset: {e}", "danger")
            return redirect(url_for('aset_tetap_page'))
        # --------------------------
        
        # --- HANDLER TAMBAH ASET (Logika POST yang sudah ada) ---
        try:
            nama = request.form.get("nama_aset")
            tgl = request.form.get("tanggal_perolehan")
            harga = float(request.form.get("harga_perolehan", "0").replace(".", "").replace("Rp", "").strip())
            masa = int(request.form.get("masa_manfaat", "0"))
            residu = float(request.form.get("nilai_residu", "0").replace(".", "").replace("Rp", "").strip())
            kat = request.form.get("kategori_aset")
            metode = request.form.get("metode_bayar")
            
            if harga <= 0 or masa <= 0:
                flash("Harga dan Umur Aset harus valid.", "danger")
                return redirect(url_for('aset_tetap_page'))

            akun_set = kategori_aset.get(kat, kategori_aset['Bangunan'])
            
            data_aset = {
                "nama_aset": nama, "tanggal_perolehan": tgl, "harga_perolehan": harga,
                "masa_manfaat": masa, "nilai_residu": residu, "metode": "Garis Lurus",
                "akun_aset": akun_set['akun_aset'],
                "akun_akumulasi": akun_set['akun_akumulasi'],
                "akun_beban": akun_set['akun_beban']
            }
            append_data_to_db("aset_tetap", data_aset, user_id)
            
            # Jurnal Pembelian Aset
            akun_kredit = "Utang Dagang" if metode == "Utang Dagang" else metode
            jurnal = [
                {"Tanggal": tgl, "Akun": akun_set['akun_aset'], "Debit": harga, "Kredit": 0, "Keterangan": f"Beli Aset {nama}", "Kontak": ""},
                {"Tanggal": tgl, "Akun": akun_kredit, "Debit": 0, "Kredit": harga, "Keterangan": f"Beli Aset {nama}", "Kontak": ""}
            ]
            buat_jurnal_batch(jurnal, user_id)
            
            flash("Aset berhasil didaftarkan.", "success")
        except Exception as e:
            flash(f"Gagal: {e}", "danger")
        return redirect(url_for('aset_tetap_page'))
    
    # --- GET REQUEST ---
    aset_df = load_data_from_db("aset_tetap", user_id)
    if not aset_df.empty:
        aset_df = aset_df.sort_values('tanggal_perolehan', ascending=False)
        
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_ASET)
    return render_template_string(full_html, title="Aset Tetap", today=datetime.now().strftime("%Y-%m-%d"), kategori_aset=kategori_aset, daftar_aset=aset_df.to_dict('records'))

# --- Rute Proses Penyusutan ---
# --- Rute Proses Penyusutan (GANTI TOTAL) ---
@app.route("/proses_penyusutan", methods=["GET", "POST"])
@login_required
def proses_penyusutan_page():
    user_id = session['user_id']
    periode_pilihan = datetime.now().strftime("%Y-%m")
    preview_data = []
    
    if request.method == "POST":
        periode_pilihan = request.form.get("periode")
        action = request.form.get("action")
        
        try:
            periode_dt = datetime.strptime(periode_pilihan, "%Y-%m")
            akhir_bulan = (periode_dt + relativedelta(months=1) - relativedelta(days=1)).date()
            
            aset_df = load_data_from_db("aset_tetap", user_id)
            aset_siap = []
            
            if not aset_df.empty:
                # Fix timezone & format tanggal
                aset_df["tanggal_perolehan"] = pd.to_datetime(aset_df["tanggal_perolehan"]).dt.date
                aset_df["bulan_terakhir_disusutkan"] = pd.to_datetime(aset_df["bulan_terakhir_disusutkan"], errors='coerce').dt.date
                
                for _, aset in aset_df.iterrows():
                    # Belum dibeli, skip
                    if aset.tanggal_perolehan.strftime("%Y-%m") > periode_pilihan: continue
                    
                    # Cek apakah sudah disusutkan bulan ini
                    last_susut = aset.bulan_terakhir_disusutkan
                    if pd.isna(last_susut) or last_susut.strftime("%Y-%m") < periode_pilihan:
                         aset_siap.append(aset)
            
            jurnal_exec = []
            for aset in aset_siap:
                # Hitung Beban Penyusutan
                beban = int((float(aset.harga_perolehan) - float(aset.nilai_residu)) / int(aset.masa_manfaat))
                
                preview_data.append({"nama_aset": aset.nama_aset, "beban_bulanan": beban, "id": aset.id})
                
                jurnal_exec.extend([
                    {"Tanggal": akhir_bulan.strftime("%Y-%m-%d"), "Akun": aset.akun_beban, "Debit": beban, "Kredit": 0, "Keterangan": f"Penyusutan {aset.nama_aset} {periode_pilihan}", "Kontak": ""},
                    {"Tanggal": akhir_bulan.strftime("%Y-%m-%d"), "Akun": aset.akun_akumulasi, "Debit": 0, "Kredit": beban, "Keterangan": f"Penyusutan {aset.nama_aset} {periode_pilihan}", "Kontak": ""}
                ])
            
            # === LOGIKA HAPUS ===
            if action == "hapus_susut":
                aset_id = int(request.form.get("aset_id"))
                periode_susut = request.form.get("periode_susut") # ex: 2025-11
                
                hapus_penyusutan_db(aset_id, periode_susut, user_id)
                flash(f"Penyusutan untuk Aset ID {aset_id} pada {periode_susut} berhasil dibatalkan dan jurnal dihapus.", "success")
                return redirect(url_for('proses_penyusutan_page'))
            # ====================
            
            # === LOGIKA EKSEKUSI ===
            if action == "eksekusi" and jurnal_exec:
                buat_jurnal_batch(jurnal_exec, user_id)
                for p in preview_data:
                    supabase.from_("aset_tetap").update({"bulan_terakhir_disusutkan": akhir_bulan.strftime("%Y-%m-%d")}).eq("id", p['id']).execute()
                
                flash(f"Sukses! {len(preview_data)} aset telah disusutkan.", "success")
                return redirect(url_for('proses_penyusutan_page'))
                
        except Exception as e:
            flash(f"Error: {e}", "danger")
            
    aset_df = load_data_from_db("aset_tetap", user_id)
    
    # --- RENDER KE TEMPLATE ---
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_PENYUSUTAN)
    return render_template_string(full_html, title="Proses Penyusutan", periode_pilihan=periode_pilihan, preview_aset=preview_data, daftar_aset=aset_df.to_dict('records'))

@app.route("/setup_saldo", methods=["GET", "POST"])
@login_required
def setup_saldo_page():
    user_id = session['user_id']
    
    if request.method == "POST":
        try:
            # 1. Ambil dan bersihkan data
            tanggal = request.form.get("tanggal")
            # FIX: Gunakan format waktu yang aman untuk Supabase
            waktu = datetime.combine(datetime.strptime(tanggal, "%Y-%m-%d").date(), datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            
            akun = request.form.get("akun")
            posisi = request.form.get("posisi") 
            # Pastikan jumlah dikonversi ke float terlebih dahulu untuk presisi
            jumlah_float = float(request.form.get("jumlah", "0").replace(".", "").replace("Rp", "").strip())
            jumlah = int(round(jumlah_float))
            
            if jumlah <= 0:
                flash("Jumlah harus lebih dari 0.", "danger")
                return redirect(url_for('setup_saldo_page'))

            # *** KUNCI PENCEGAHAN ERROR: VALIDASI SALDO NORMAL SERVER-SIDE ***
            saldo_normal_akun = SALDO_NORMAL_MAP.get(akun)
            if saldo_normal_akun and saldo_normal_akun != posisi:
                # Jika input posisi (Debit/Kredit) tidak sesuai dengan saldo normal akun
                flash(f"⚠️ **GAGAL:** Posisi '{posisi}' SALAH untuk akun **{akun}**. Saldo normal {akun} seharusnya **{saldo_normal_akun}**.", "danger")
                return redirect(url_for('setup_saldo_page'))
            # ****************************************************

            # 2. Buat Jurnal Saldo Awal
            jurnal = []
            
            if posisi == "Debit":
                # Jurnal Debit: Kas/Aset (Debit) vs Historical Balancing (Kredit)
                jurnal.append({"Tanggal": waktu, "Akun": akun, "Debit": jumlah, "Kredit": 0, "Keterangan": "Saldo Awal", "Kontak": ""})
                jurnal.append({"Tanggal": waktu, "Akun": "Historical Balancing", "Debit": 0, "Kredit": jumlah, "Keterangan": "Saldo Awal", "Kontak": ""})
            else:
                # Jurnal Kredit: Historical Balancing (Debit) vs Utang/Modal (Kredit)
                jurnal.append({"Tanggal": waktu, "Akun": "Historical Balancing", "Debit": jumlah, "Kredit": 0, "Keterangan": "Saldo Awal", "Kontak": ""})
                jurnal.append({"Tanggal": waktu, "Akun": akun, "Debit": 0, "Kredit": jumlah, "Keterangan": "Saldo Awal", "Kontak": ""})
            
            # 3. Kirim ke Database (Ini adalah titik kritis)
            buat_jurnal_batch(jurnal, user_id)
            flash(f"Saldo awal {akun} berhasil ditambahkan.", "success")
            
        except Exception as e:
            # Jika ada kesalahan (misalnya dari buat_jurnal_batch), kita tangkap dan informasikan
            print(f"ERROR FATAL SAAT INPUT SALDO: {e}")
            flash(f"Gagal menyimpan Saldo Awal: {e}", "danger")
            
        return redirect(url_for('setup_saldo_page'))
            
    today = datetime.now().strftime("%Y-%m-%d")
    
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', HTML_SETUP)
    return render_template_string(
        full_html, 
        title="Setup Saldo", 
        today=today,
        jenis_ikan=jenis_ikan
    )

@app.before_request
def debug_before_request():
    print(f"🔍 [DEBUG] Accessing: {request.path} - User: {session.get('user_id', 'Not logged in')}")

@app.after_request
def debug_after_request(response):
    print(f"🔍 [DEBUG] Response: {response.status_code} for {request.path}")
    return response

# Tambahkan di akhir file sebelum app.run()
@app.errorhandler(Exception)
def handle_error(e):
    """
    Error handler global yang lebih bijak.
    Hanya redirect ke login jika error terkait authentication.
    Untuk error lain, tampilkan error page yang lebih informatif.
    """
    error_msg = str(e)
    print(f"❌ [ERROR] {error_msg}")
    print(traceback.format_exc())
    
    # Cek apakah error terkait authentication/session
    if 'access_token' not in session or 'user_id' not in session:
        flash("Sesi Anda telah berakhir. Harap login ulang.", "danger")
        return redirect(url_for('login_page'))
    
    # Untuk error lain, tampilkan halaman error yang lebih informatif
    # Jangan langsung redirect ke login karena akan mengganggu user experience
    error_html = """
    <div class="text-center py-12">
        <div class="bg-white rounded-2xl p-8 max-w-2xl mx-auto">
            <i class="fas fa-exclamation-triangle text-yellow-500 text-5xl mb-4"></i>
            <h2 class="text-2xl font-bold text-gray-900 mb-2">Terjadi Kesalahan</h2>
            <p class="text-gray-600 mb-4">Maaf, terjadi kesalahan saat memproses permintaan Anda.</p>
            <div class="bg-gray-50 p-4 rounded-lg text-left mb-6">
                <p class="text-sm text-gray-700 font-mono break-all">{{ error_msg }}</p>
            </div>
            <div class="flex flex-wrap gap-4 justify-center">
                <a href="/" class="btn-consistent btn-primary">
                    <i class="fas fa-home mr-2"></i>Kembali ke Dashboard
                </a>
                <button onclick="window.location.reload()" class="btn-consistent btn-secondary">
                    <i class="fas fa-redo mr-2"></i>Refresh Halaman
                </button>
            </div>
        </div>
    </div>
    """
    full_html = HTML_LAYOUT.replace('{% block content %}{% endblock %}', error_html)
    return render_template_string(full_html, title="Error", error_msg=error_msg), 500

# ---------------- Menjalankan Aplikasi ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5001)