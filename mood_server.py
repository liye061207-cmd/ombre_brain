import http.server
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state', 'persona_state.db')
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mood.html')

class MoodHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/mood':
            try:
                conn = sqlite3.connect(DB_PATH)
                row = conn.execute('SELECT * FROM persona_session_state ORDER BY updated_at DESC LIMIT 1').fetchone()
                conn.close()
                if row:
                    data = {
                        'valence': row[2], 'arousal': row[3], 'tenderness': row[4],
                        'possessiveness': row[5], 'longing': row[6], 'security': row[7],
                        'protective_drive': row[8], 'libido': row[9], 'mood_label': row[10],
                        'inner_thought': row[13] or '', 'updated_at': (row[14] or '')[:19].replace('T', ' ')
                    }
                else:
                    data = {'error': 'no data'}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        elif self.path == '/' or self.path == '/mood':
            try:
                with open(HTML_PATH, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content)
            except:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = http.server.HTTPServer(('0.0.0.0', 18003), MoodHandler)
    print('Mood server running on :18003')
    server.serve_forever()
