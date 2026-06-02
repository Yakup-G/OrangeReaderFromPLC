# main.py
import time
import logging
import requests
from .config import PLCConfig, SERVER_URL, MACHINE_ID, MACHINE_NAME, PLC_TAGS
from .plc_reader import PLCReader

# Konsol log ayarları
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("OrangePiAgent")

def send_data_to_server(payload):
    """Veriyi HTTP POST ile Merkez Flask Sunucusuna iletir."""
    try:
        response = requests.post(SERVER_URL, json=payload, timeout=3.0)
        if response.status_code == 200:
            logger.info(f"Veri sunucuya başarıyla gönderildi: {MACHINE_ID}")
        else:
            logger.error(f"Sunucu hatası: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Merkez sunucuya ulaşılamadı (Bağlantı Hatası): {e}")

def main():
    # PLC'nin ağdaki statik IP adresi (Her makinenin kendi PLC IP'sini yazabilirsin)
    plc_config = PLCConfig(ip="192.168.250.10")
    
    # plc_reader.py içindeki korumalı okuyucu sınıfını başlatıyoruz
    reader = PLCReader(config=plc_config, reconnect_delay=5.0, logger=logger)
    
    logger.info(f"[{MACHINE_ID}] için veri toplama ajanı başlatıldı. PLC aranıyor...")

    while True:
        try:
            # PLC'den tanımlanmış olan tüm tag'leri tek seferde oku
            plc_data = reader.read(PLC_TAGS)
            
            # Okunan ham verileri Flask sunucusunun anladığı şablona dönüştür
            payload = {
                "machine_id": MACHINE_ID,
                "machine_name": MACHINE_NAME,
                "status": str(plc_data.get("Machine_Status", "off")),
                "hours_this_week": float(plc_data.get("Weekly_Work_Hours", 0.0)),
                "efficiency": int(plc_data.get("Current_Efficiency", 0)),
                "total_hours": float(plc_data.get("Lifetime_Total_Hours", 0.0))
            }
            
            # Paketlenen veriyi merkez sunucuya fırlat
            send_data_to_server(payload)
            
        except Exception as e:
            logger.error(f"Ana döngü akışında hata oluştu: {e}")
            
        # Sorgu periyodu: 10 saniyede bir PLC'yi oku ve sunucuyu güncelle
        time.sleep(10.0)

if __name__ == "__main__":
    main()