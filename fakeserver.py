"""
fake_server.py — Test için sahte dashboard sunucusu
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime

class FakeDashboardHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/agent/update":
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data)
                
                print("\n" + "="*60)
                print(f"📥 FAKE SUNUCU - VERİ ALINDI ({datetime.now().strftime('%H:%M:%S')})")
                print("="*60)
                print(json.dumps(data, indent=2, ensure_ascii=False))
                print("="*60)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Data received"}).encode())
                
            except Exception as e:
                print(f"Hata: {e}")
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Logları temiz tutmak için

if __name__ == "__main__":
    server = HTTPServer(('0.0.0.0', 8080), FakeDashboardHandler)
    print("🚀 Fake Sunucu başlatıldı → http://0.0.0.0:8080")
    print("Test için main.py'de SERVER_URL = 'http://127.0.0.1:8080' yapın")
    print("Çıkmak için Ctrl+C")
    server.serve_forever()
