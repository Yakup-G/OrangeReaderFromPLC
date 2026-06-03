#!/bin/bash
# ─────────────────────────────────────────────────────────────
# install.sh  —  Orange Pi Agent Kurulum Scripti
#
# Kullanım:
#   chmod +x install.sh
#   sudo ./install.sh
#
# Bu script şunları yapar:
#   1. Gerekli sistem paketlerini kurar
#   2. Python sanal ortamı oluşturur
#   3. Python bağımlılıklarını kurar
#   4. Dosyaları doğru konuma kopyalar
#   5. systemd servisi olarak kaydeder
#   6. Otomatik başlatmayı aktif eder
# ─────────────────────────────────────────────────────────────

set -e   # Hata olursa dur

# ── Renkli çıktı ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warning() { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Root kontrolü ──
if [ "$EUID" -ne 0 ]; then
    error "Bu scripti sudo ile çalıştır: sudo ./install.sh"
fi

INSTALL_DIR="/home/orangepi/plc-agent"
SERVICE_USER="orangepi"

info "Orange Pi PLC Agent kurulumu başlıyor..."
echo ""

# ── 1. Sistem paketleri ──
info "Sistem paketleri güncelleniyor..."
apt-get update -q
apt-get install -y -q python3 python3-pip python3-venv git

# ── 2. Kurulum dizini ──
info "Kurulum dizini oluşturuluyor: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 3. Dosyaları kopyala ──
info "Agent dosyaları kopyalanıyor..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for f in main.py plc_reader.py config.py; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
        info "  Kopyalandı: $f"
    else
        error "$f bulunamadı! Tüm dosyaların aynı klasörde olduğundan emin ol."
    fi
done

# ── 4. Python sanal ortamı ──
info "Python sanal ortamı oluşturuluyor..."
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"

# ── 5. Python bağımlılıkları ──
info "Python kütüphaneleri kuruluyor..."
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install \
    fins \
    requests \
    -q

info "Kütüphaneler kuruldu."

# ── 6. systemd servisi ──
info "systemd servisi kaydediliyor..."
cp "$SCRIPT_DIR/plc-agent.service" /etc/systemd/system/plc-agent.service
systemctl daemon-reload
systemctl enable plc-agent
info "Servis otomatik başlatma aktif edildi."

# ── 7. Logrotate (log dosyaları şişmesin) ──
cat > /etc/logrotate.d/plc-agent << 'EOF'
/home/orangepi/plc-agent/logs/agent.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 644 orangepi orangepi
}
EOF
info "Log rotasyonu ayarlandı (7 gün)."

# ── 8. İzinler ──
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo ""
echo "─────────────────────────────────────────────"
info "Kurulum tamamlandı!"
echo ""
warning "ÖNEMLİ: Başlatmadan önce config.py dosyasını düzenle:"
echo "  nano $INSTALL_DIR/config.py"
echo ""
echo "  Değiştirmen gerekenler:"
echo "    AGENT_ID     → Bu makinenin adı (örn: CNC-01)"
echo "    PLC_IP       → PLC'nin IP adresi"
echo "    SERVER_URL   → Dashboard sunucusunun adresi"
echo "    SERVER_API_KEY → Sunucudaki ile aynı anahtar"
echo "    TAGS         → PLC'deki tag isimleri"
echo ""
warning "Ayarları yaptıktan sonra servisi başlat:"
echo "  sudo systemctl start plc-agent"
echo ""
echo "Durumu görmek için:"
echo "  sudo systemctl status plc-agent"
echo "  tail -f $INSTALL_DIR/logs/agent.log"
echo "─────────────────────────────────────────────"
